from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from agent.utils.action_helpers import ocr_roi, parse_action_param, swipe_points, tap_point
from agent.utils.input_guard import safe_screencap, sleep_with_stop
from agent.utils.recognition import _ocr_entries
from maa_resonance.logic.team_formation import (
    DEFAULT_TEAM_ROLES,
    choose_next_quick_team_step,
    extract_quick_team_cards,
    is_main_formation_needs_update,
    match_formation_role,
    parse_target_roles,
    quick_team_page_signature,
)

QUICK_TEAM_ROW_OCR_ROI = [0, 140, 1280, 220]
SCROLL_ROW_START_Y = 480
SCROLL_ROW_END_Y = 185
SCROLL_TOP_START_Y = 200
SCROLL_TOP_END_Y = 620
MAX_SCROLL_STEPS = 20
STALE_PAGE_LIMIT = 2


def _parse_action_param(argv: CustomAction.RunArg) -> dict[str, Any]:
    return parse_action_param(getattr(argv, "custom_action_param", None))


def _ocr_quick_team_row(context: Context, node_name: str) -> list[dict[str, Any]] | None:
    image = safe_screencap(context)
    if image is None:
        return None
    return ocr_roi(context, image, f"{node_name}RowOCR", QUICK_TEAM_ROW_OCR_ROI)


def _tap_point(context: Context, node_name: str, x: int, y: int) -> bool:
    return tap_point(context, node_name, (int(x), int(y)))


def _swipe_points(
    context: Context,
    node_name: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    duration: int = 550,
    end_hold: int = 150,
) -> bool:
    return swipe_points(
        context,
        node_name,
        (int(x1), int(y1)),
        (int(x2), int(y2)),
        duration=duration,
        end_hold=end_hold,
    )


def _scroll_down_one_row(context: Context, node_name: str) -> bool:
    if not _swipe_points(
        context,
        node_name,
        640,
        SCROLL_ROW_START_Y,
        640,
        SCROLL_ROW_END_Y,
        duration=550,
        end_hold=180,
    ):
        return False
    return sleep_with_stop(context, 0.35)


def _scroll_up_to_top(context: Context, node_name: str, *, swipes: int = 4) -> bool:
    for idx in range(swipes):
        if not _swipe_points(
            context,
            f"{node_name}Top{idx}",
            640,
            SCROLL_TOP_START_Y,
            640,
            SCROLL_TOP_END_Y,
            duration=220,
            end_hold=0,
        ):
            return False
        if not sleep_with_stop(context, 0.25):
            return False
    return sleep_with_stop(context, 0.35)


@AgentServer.custom_recognition("team_formation_needs_update")
class TeamFormationNeedsUpdateRecognition(CustomRecognition):
    """Detect whether the current formation screen requires quick-team selection."""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        params = parse_action_param(getattr(argv, "custom_recognition_param", None))

        image = getattr(argv, "image", None)
        if image is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False})

        targets = parse_target_roles(params.get("target_roles")) or list(DEFAULT_TEAM_ROLES)
        if not targets:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "empty_target_roles"})

        quick_detail = context.run_recognition(
            f"{argv.node_name}QuickBtn",
            image,
            {
                f"{argv.node_name}QuickBtn": {
                    "recognition": "OCR",
                    "expected": ["快速编队", "快速编"],
                    "roi": [1000, 15, 270, 90],
                    "action": "DoNothing",
                }
            },
        )
        if not (quick_detail and getattr(quick_detail, "hit", False)):
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "not_formation"})

        strict_match = bool(params.get("strict_match", False))

        empty_detail = context.run_recognition(
            f"{argv.node_name}EmptyCheck",
            image,
            {
                f"{argv.node_name}EmptyCheck": {
                    "recognition": "OCR",
                    "roi": [140, 260, 1000, 220],
                    "action": "DoNothing",
                }
            },
        )
        name_detail = context.run_recognition(
            f"{argv.node_name}NameCheck",
            image,
            {
                f"{argv.node_name}NameCheck": {
                    "recognition": "OCR",
                    "roi": [140, 530, 960, 65],
                    "action": "DoNothing",
                }
            },
        )
        banner_detail = context.run_recognition(
            f"{argv.node_name}StoryLockBanner",
            image,
            {
                f"{argv.node_name}StoryLockBanner": {
                    "recognition": "OCR",
                    "expected": ["剧情固定阵容"],
                    "roi": [460, 10, 360, 60],
                    "action": "DoNothing",
                }
            },
        )
        empty_entries = _ocr_entries(SimpleNamespace(reco_detail=empty_detail))
        name_entries = _ocr_entries(SimpleNamespace(reco_detail=name_detail))
        has_story_lock = bool(banner_detail and getattr(banner_detail, "hit", False))

        needs_update = is_main_formation_needs_update(
            name_entries,
            empty_entries,
            targets,
            strict_match=strict_match,
            has_story_lock=has_story_lock,
        )
        if not needs_update:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "already_satisfied"})

        detail = {"ok": True, "reason": "needs_update", "has_story_lock": has_story_lock}
        if not strict_match:
            # Carry the lineup from the formation screen. Some members may be off-screen in quick select.
            selected = {match_formation_role(entry["text"], targets) for entry in name_entries}
            selected.discard(None)
            # "添加" and "EMPTY" can describe the same slot. Group their centers by column.
            empty_centers = sorted(
                entry["x"] + entry["w"] / 2
                for entry in empty_entries
                if "添加" in entry["text"] or "EMPTY" in entry["text"].upper()
            )
            vacancies = sum(
                index == 0 or x - empty_centers[index - 1] > 80
                for index, x in enumerate(empty_centers)
            )
            if len(selected) + vacancies != 5:
                return CustomRecognition.AnalyzeResult(box=None, detail={"reason": "incomplete_lineup"})
            detail["selected_roles"] = sorted(selected)
        quick_box = getattr(getattr(quick_detail, "best_result", None), "box", None) or [1045, 36, 70, 35]
        return CustomRecognition.AnalyzeResult(
            box=quick_box,
            detail=detail,
        )


@AgentServer.custom_action("team_formation_quick_select")
class TeamFormationQuickSelectAction(CustomAction):
    """Fill vacancies or replace the lineup with the configured roles."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _parse_action_param(argv)
        targets = parse_target_roles(params.get("target_roles")) or list(DEFAULT_TEAM_ROLES)
        if not targets:
            print("[AutoTeamFormation] 未配置目标角色名单，保持现有阵容并直接确认。", flush=True)
            return True
        max_team_size = int(params.get("max_team_size") or 5)
        node = context.get_node_data(argv.node_name)
        if node is None:
            return False
        known_story_roles: set[str] = set()
        confirmed_selected: set[str] = set()
        fill_from = node.get("attach", {}).get("fill_empty_from")
        if fill_from:
            formation = context.tasker.get_latest_node(fill_from)
            if formation is None or formation.node_id not in argv.task_detail.node_id_list:
                return False
            previous = getattr(formation.recognition, "best_result", None)
            lineup = getattr(previous, "detail", None)
            if not isinstance(lineup, dict) or not isinstance(lineup.get("selected_roles"), list):
                return False
            confirmed_selected.update(lineup["selected_roles"])
        blocked_select_roles: set[str] = set()
        last_signature: tuple[str, ...] | None = None
        stale_count = 0
        scroll_count = 0
        returned_to_top = False

        for _ in range(60):
            entries = _ocr_quick_team_row(context, argv.node_name)
            if entries is None:
                return False
            cards = extract_quick_team_cards(entries, target_roles=targets)
            if not cards:
                if not sleep_with_stop(context, 0.3):
                    return False
                continue

            for card in cards:
                if card["state"] == "story_locked":
                    known_story_roles.add(card["role"])
                    confirmed_selected.add(card["role"])
                elif card["state"] == "selected":
                    confirmed_selected.add(card["role"])
                elif card["state"] == "unselected" and not fill_from:
                    confirmed_selected.discard(card["role"])

            step = choose_next_quick_team_step(
                cards,
                targets,
                known_story_roles=known_story_roles,
                confirmed_selected=confirmed_selected,
                max_team_size=max_team_size,
                fill_empty_only=bool(fill_from),
            )

            action = step["action"]
            if action == "confirm":
                return True

            if (
                action == "click"
                and step.get("reason") == "select_target"
                and step.get("role") in blocked_select_roles
            ):
                action = "scroll"

            if action == "click":
                px, py = step["point"]
                reason = step.get("reason")
                role = str(step.get("role") or "")
                print(
                    f"[AutoTeamFormation] {reason}: {role} @ ({px}, {py})",
                    flush=True,
                )
                if not _tap_point(context, argv.node_name, int(px), int(py)):
                    return False
                if not sleep_with_stop(context, 0.30):
                    return False

                if reason == "select_target":
                    verify_entries = _ocr_quick_team_row(context, f"{argv.node_name}Verify")
                    if verify_entries is None:
                        return False
                    verify_cards = extract_quick_team_cards(verify_entries, target_roles=targets)
                    matched = next((c for c in verify_cards if c["role"] == role), None)
                    if fill_from:
                        # A quick-team card toggles. Never tap it a second time after a missing badge.
                        if not matched or matched["state"] == "unselected":
                            print(f"[AutoTeamFormation] 未能确认「{role}」上阵，保留当前阵容。", flush=True)
                            return True
                        confirmed_selected.add(role)
                    if matched and matched["state"] == "unselected":
                        blocked_select_roles.add(role)
                    else:
                        blocked_select_roles.discard(role)
                elif reason == "deselect_unwanted":
                    confirmed_selected.discard(role)
                    blocked_select_roles.clear()
                continue

            if action == "scroll":
                sig = quick_team_page_signature(cards)
                if sig == last_signature:
                    stale_count += 1
                else:
                    last_signature = sig
                    stale_count = 0

                if stale_count >= STALE_PAGE_LIMIT or scroll_count >= MAX_SCROLL_STEPS:
                    if not returned_to_top and (
                        blocked_select_roles
                        or not set(step.get("desired_roles") or ()).issubset(confirmed_selected)
                    ):
                        returned_to_top = True
                        blocked_select_roles.clear()
                        stale_count = 0
                        last_signature = None
                        if not _scroll_up_to_top(context, argv.node_name):
                            return False
                        continue
                    print(
                        "[AutoTeamFormation] Reached list end; confirming current selection.",
                        flush=True,
                    )
                    return True

                scroll_count += 1
                if not _scroll_down_one_row(context, argv.node_name):
                    return False

        return True

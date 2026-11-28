from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from agent.utils.action_helpers import ocr_roi, parse_action_param, swipe_points, tap_point
from agent.utils.input_guard import safe_screencap, sleep_with_stop
from maa_resonance.logic.mainline_quest import (
    CITY_INTERACTIVE_ROI,
    CITY_PAN_SWIPES,
    DEFAULT_ICON_MIN_SCORE,
    LOBBY_RIGHT_PANEL_ROI,
    PULSE_RETRY_DELAY_SEC,
    TOP_RIGHT_TASK_PANEL_ROI,
    compute_city_avatar_target,
    parse_mainline_task_summary,
    select_best_quest_icon,
    select_lobby_quest_button,
)

QUEST_ICON_TEMPLATE = "quest/active_quest_icon.png"


def _parse_param(raw: Any) -> dict[str, Any]:
    return parse_action_param(raw)


@AgentServer.custom_recognition("mainline_map_unobstructed")
class MainlineMapUnobstructedRecognition(CustomRecognition):
    """Check the target and its blocking panels against the same map frame."""

    def analyze(self, context: Context, argv: CustomRecognition.AnalyzeArg):
        params = _parse_param(argv.custom_recognition_param)
        target = context.run_recognition(params["target"], argv.image)
        if target is None or not target.hit:
            return None
        for name in params["blockers"]:
            blocker = context.run_recognition(name, argv.image)
            if blocker is None or blocker.hit:
                return None
        return target.box


@AgentServer.custom_action("mainline_navigation_failed")
class MainlineNavigationFailedAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        return False


def _detect_quest_icon(
    context: Context,
    image: Any,
    node_name: str,
    *,
    roi: tuple[int, int, int, int],
    min_score: float = DEFAULT_ICON_MIN_SCORE,
    check_color: bool = True,
) -> dict[str, Any] | None:
    detail = context.run_recognition(
        node_name,
        image,
        {
            node_name: {
                "recognition": "TemplateMatch",
                "template": [QUEST_ICON_TEMPLATE],
                "green_mask": True,
                "threshold": float(min_score),
                "roi": list(roi),
                "action": "DoNothing",
            }
        },
    )
    candidates: list[Any] = []
    if detail is not None:
        candidates.extend(getattr(detail, "all_results", None) or [])
        candidates.extend(getattr(detail, "filtered_results", None) or [])
        best = getattr(detail, "best_result", None)
        if best is not None:
            candidates.append(best)
    return select_best_quest_icon(
        candidates,
        image_bgr=image if check_color else None,
        min_score=min_score,
    )


def _ocr_roi(context: Context, image: Any, node_name: str, roi: list[int]) -> list[dict[str, Any]]:
    return ocr_roi(context, image, node_name, roi)


def _tap_box(context: Context, node_name: str, box: tuple[int, int, int, int]) -> bool:
    x, y, w, h = box
    cx = int(round(x + w / 2.0))
    cy = int(round(y + h / 2.0))
    return tap_point(context, node_name, (cx, cy))


def _swipe_points(
    context: Context,
    node_name: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    duration: int = 450,
    end_hold: int = 180,
) -> bool:
    return swipe_points(
        context,
        node_name,
        (int(x1), int(y1)),
        (int(x2), int(y2)),
        duration=duration,
        end_hold=end_hold,
    )


@AgentServer.custom_recognition("mainline_city_quest_target")
class MainlineCityQuestTargetRecognition(CustomRecognition):
    """Detect active quest diamond inside a city and return its bottom-left avatar tap box."""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        params = _parse_param(getattr(argv, "custom_recognition_param", None))
        min_score = float(params.get("min_score", DEFAULT_ICON_MIN_SCORE) or DEFAULT_ICON_MIN_SCORE)
        image = getattr(argv, "image", None)
        if image is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False})

        matched = _detect_quest_icon(
            context,
            image,
            f"{argv.node_name}Icon",
            roi=CITY_INTERACTIVE_ROI,
            min_score=min_score,
        )
        if matched is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False})

        target_box = compute_city_avatar_target(matched["box"])
        return CustomRecognition.AnalyzeResult(
            box=target_box,
            detail={
                "ok": True,
                "icon_box": list(matched["box"]),
                "target_box": list(target_box),
                "score": round(float(matched["score"]), 4),
            },
        )


@AgentServer.custom_action("mainline_city_sweep_and_tap_quest")
class MainlineCitySweepAndTapQuestAction(CustomAction):
    """Handle 0.5s icon pulse retry and gentle horizontal city pans before alerting."""

    def _capture_and_find(
        self,
        context: Context,
        node_name: str,
        *,
        min_score: float,
        pulse_retry: bool = True,
    ) -> dict[str, Any] | None:
        attempts = 2 if pulse_retry else 1
        for idx in range(attempts):
            if idx > 0 and not sleep_with_stop(context, PULSE_RETRY_DELAY_SEC):
                return None
            image = safe_screencap(context)
            if image is None:
                return None
            matched = _detect_quest_icon(
                context,
                image,
                f"{node_name}Check{idx}",
                roi=CITY_INTERACTIVE_ROI,
                min_score=min_score,
            )
            if matched is not None:
                return matched
        return None

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _parse_param(getattr(argv, "custom_action_param", None))
        min_score = float(params.get("min_score", DEFAULT_ICON_MIN_SCORE) or DEFAULT_ICON_MIN_SCORE)
        retry_rounds = max(0, int(params.get("retry_rounds", 1) or 0))

        # 1. Re-sample current view in case previous frame caught the 0.5s icon pulse animation.
        matched = self._capture_and_find(
            context, argv.node_name, min_score=min_score, pulse_retry=True
        )
        if matched is not None:
            target = compute_city_avatar_target(matched["box"])
            print(
                f"[MainlineAdvance] Pulse retry hit quest icon {matched['box']} "
                f"(score={matched['score']:.3f}) -> tap avatar {target}",
                flush=True,
            )
            return _tap_box(context, argv.node_name, target)

        # 2. Gentle horizontal pans across the city.
        for round_idx in range(retry_rounds + 1):
            for step_idx, (x1, y1, x2, y2) in enumerate(CITY_PAN_SWIPES):
                if not _swipe_points(
                    context,
                    f"{argv.node_name}PanR{round_idx}S{step_idx}",
                    x1,
                    y1,
                    x2,
                    y2,
                ):
                    return False
                if not sleep_with_stop(context, 0.45):
                    return False
                matched = self._capture_and_find(
                    context,
                    f"{argv.node_name}PanR{round_idx}S{step_idx}",
                    min_score=min_score,
                    pulse_retry=True,
                )
                if matched is not None:
                    target = compute_city_avatar_target(matched["box"])
                    print(
                        f"[MainlineAdvance] Pan step {step_idx + 1} hit quest icon {matched['box']} "
                        f"(score={matched['score']:.3f}) -> tap avatar {target}",
                        flush=True,
                    )
                    return _tap_box(context, argv.node_name, target)
            if round_idx < retry_rounds and not sleep_with_stop(context, 1.0):
                return False

        image = safe_screencap(context)
        if image is None:
            return False
        task_entries = _ocr_roi(
            context,
            image,
            f"{argv.node_name}TaskPanel",
            list(TOP_RIGHT_TASK_PANEL_ROI),
        )
        summary = parse_mainline_task_summary(task_entries) or "未知任务"
        print(
            f"[MainlineAdvance] WARNING: 未在当前城市扫描到主线任务图标（当前右侧任务：{summary}），"
            "请确认是否为制作/非城市对话任务或手动介入处理。",
            flush=True,
        )
        return False


@AgentServer.custom_action("mainline_lobby_advance_action")
class MainlineLobbyAdvanceAction(CustomAction):
    """On the train-station lobby screen, enter local quest target or open the world map."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _parse_param(getattr(argv, "custom_action_param", None))
        min_score = float(params.get("min_score", DEFAULT_ICON_MIN_SCORE) or DEFAULT_ICON_MIN_SCORE)

        matched = None
        image = None
        for idx in range(2):
            if idx > 0 and not sleep_with_stop(context, PULSE_RETRY_DELAY_SEC):
                return False
            image = safe_screencap(context)
            if image is None:
                return False
            matched = _detect_quest_icon(
                context,
                image,
                f"{argv.node_name}LobbyIcon{idx}",
                roi=LOBBY_RIGHT_PANEL_ROI,
                min_score=min_score,
                check_color=True,
            )
            if matched is not None:
                break

        if matched is not None and image is not None:
            btn_entries = _ocr_roi(
                context,
                image,
                f"{argv.node_name}LobbyButtons",
                [960, 300, 320, 390],
            )
            filtered_buttons = [
                entry
                for entry in btn_entries
                if any(
                    kw in str(entry.get("text") or "")
                    for kw in ("访问城市", "访问地区", "作战终端", "启程", "START")
                )
            ]
            target_box = select_lobby_quest_button(matched["box"], filtered_buttons)
            print(
                f"[MainlineAdvance] Lobby quest icon at {matched['box']} -> tap button {target_box}",
                flush=True,
            )
            return _tap_box(context, argv.node_name, target_box)

        # No quest badge on current stop's right-side buttons -> open world map via 启程.
        if image is None:
            image = safe_screencap(context)
            if image is None:
                return False
        depart_entries = _ocr_roi(
            context,
            image,
            f"{argv.node_name}DepartBtn",
            [1100, 600, 180, 120],
        )
        for entry in depart_entries:
            txt = str(entry.get("text") or "")
            if "启程" in txt or "START" in txt.upper():
                box = entry.get("box")
                if isinstance(box, (list, tuple)) and len(box) >= 4:
                    return _tap_box(context, argv.node_name, (int(box[0]), int(box[1]), int(box[2]), int(box[3])))
                if all(k in entry for k in ("x", "y", "w", "h")):
                    return _tap_box(
                        context,
                        argv.node_name,
                        (int(entry["x"]), int(entry["y"]), int(entry["w"]), int(entry["h"])),
                    )

        print("[MainlineAdvance] Lobby has no local quest badge; tapping 启程 to open map.", flush=True)
        return _tap_box(context, argv.node_name, (1135, 625, 110, 60))


__all__ = [
    "MainlineCityQuestTargetRecognition",
    "MainlineCitySweepAndTapQuestAction",
    "MainlineLobbyAdvanceAction",
]

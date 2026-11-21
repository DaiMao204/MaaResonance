from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from agent.utils.action_helpers import ocr_roi, parse_action_param, tap_point
from agent.utils.input_guard import safe_screencap, sleep_with_stop
from maa_resonance.logic.clarity_recovery import (
    CLARITY_BACK_POINT,
    CLARITY_POPUP_ROI,
    choose_clarity_card,
    find_clarity_popup_button,
    is_clarity_confirm_popup,
    parse_clarity_cards,
    parse_clarity_limits,
    parse_clarity_status,
    popup_reports_no_stock,
)

_CLARITY_USED_BY_TASK: dict[int, dict[str, int]] = {}


def _clarity_used_counts_for_run(context: Context, argv: CustomAction.RunArg) -> dict[str, int]:
    task_detail = getattr(argv, "task_detail", None)
    task_id = getattr(task_detail, "task_id", None)
    key = int(task_id) if task_id is not None else id(context.tasker)
    if len(_CLARITY_USED_BY_TASK) > 32:
        _CLARITY_USED_BY_TASK.clear()
    return _CLARITY_USED_BY_TASK.setdefault(key, {})


@AgentServer.custom_action("clarity_recovery_action")
class ClarityRecoveryAction(CustomAction):
    """Consume a Clarity medicine respecting per-item usage limits on the Clarity recovery screen."""

    def _confirm_popup_and_finish(
        self,
        context: Context,
        node_name: str,
        popup_entries: list[dict[str, Any]],
        *,
        attempt: int,
        card_key: str | None,
        used_counts: dict[str, int],
    ) -> tuple[bool, bool]:
        """Confirm item use with up to 3 tap retries. Return ``(handled, succeeded)``."""
        cur_entries = popup_entries
        confirmed = False
        after_entries: list[dict[str, Any]] = []

        for retry in range(3):
            confirm_pt = find_clarity_popup_button(cur_entries, kind="confirm")
            if confirm_pt is None:
                break
            if not tap_point(context, f"{node_name}Confirm{attempt}_{retry}", confirm_pt):
                return True, False
            if not sleep_with_stop(context, 0.85):
                return True, False
            after_img = safe_screencap(context)
            if after_img is None:
                return True, False
            after_entries = ocr_roi(
                context,
                after_img,
                f"{node_name}After{attempt}_{retry}",
                [0, 0, 1280, 720],
            )
            if not is_clarity_confirm_popup(after_entries):
                confirmed = True
                break
            cur_entries = after_entries

        if not confirmed:
            cancel_pt = find_clarity_popup_button(cur_entries, kind="cancel")
            if cancel_pt is not None:
                tap_point(context, f"{node_name}AbortCancel{attempt}", cancel_pt)
                sleep_with_stop(context, 0.4)
            print(
                "[ClarityRecovery] WARNING: 澄明度恢复确认弹窗连续点击 3 次仍未关闭，已取消并停止防止死循环。",
                flush=True,
            )
            return True, False

        if card_key:
            used_counts[card_key] = used_counts.get(card_key, 0) + 1

        if any(
            kw in str(e.get("text") or "")
            for e in after_entries
            for kw in ("触碰空白区域退出", "点击空白处关闭", "点击任意位置继续", "已恢复", "已消除")
        ):
            if not tap_point(context, f"{node_name}CloseNotice{attempt}", (640, 650)):
                return True, False
            if not sleep_with_stop(context, 0.5):
                return True, False
            notice_img = safe_screencap(context)
            if notice_img is None:
                return True, False
            after_entries = ocr_roi(
                context,
                notice_img,
                f"{node_name}AfterNotice{attempt}",
                [0, 0, 1280, 720],
            )

        if any("请选择恢复方式" in str(e.get("text") or "") for e in after_entries):
            if not tap_point(context, f"{node_name}Back", CLARITY_BACK_POINT):
                return True, False
            sleep_with_stop(context, 0.7)
        return True, True

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = parse_action_param(getattr(argv, "custom_action_param", None))
        limits = parse_clarity_limits(params)
        used_counts = _clarity_used_counts_for_run(context, argv)
        excluded_keys: set[str] = set()

        for attempt in range(4):
            image = safe_screencap(context)
            if image is None:
                return False
            entries = ocr_roi(context, image, f"{argv.node_name}Scan{attempt}", [0, 0, 1280, 720])
            if is_clarity_confirm_popup(entries):
                _, ok = self._confirm_popup_and_finish(
                    context,
                    argv.node_name,
                    entries,
                    attempt=attempt,
                    card_key=None,
                    used_counts=used_counts,
                )
                return ok

            if not any("请选择恢复方式" in str(e.get("text") or "") for e in entries):
                return True

            status = parse_clarity_status(entries)
            cards = parse_clarity_cards(entries)
            chosen = choose_clarity_card(
                cards,
                limits=limits,
                used_counts=used_counts,
                excluded_keys=excluded_keys,
            )
            if chosen is None:
                print(
                    "[ClarityRecovery] WARNING: 澄明度不足且无可用体力药配额"
                    f"（limits={limits}, used={used_counts}, excluded={sorted(excluded_keys)}），停止推进等待人工处理。",
                    flush=True,
                )
                return False

            key = str(chosen["key"])
            print(
                f"[ClarityRecovery] Clarity {status or 'unknown'} -> trying {chosen['name']} "
                f"(+{chosen['restore']}, count={chosen.get('count')}, limited={chosen.get('is_limited')}, "
                f"used={used_counts.get(key, 0)}/{limits.get(key, 0)})",
                flush=True,
            )

            popup_entries: list[dict[str, Any]] = []
            for card_tap in range(2):
                if not tap_point(context, f"{argv.node_name}Card{attempt}_{card_tap}", chosen["tap_point"]):
                    return False
                if not sleep_with_stop(context, 0.65):
                    return False
                popup_img = safe_screencap(context)
                if popup_img is None:
                    return False
                popup_entries = ocr_roi(
                    context,
                    popup_img,
                    f"{argv.node_name}Popup{attempt}_{card_tap}",
                    list(CLARITY_POPUP_ROI),
                )
                if (
                    popup_reports_no_stock(popup_entries)
                    or find_clarity_popup_button(popup_entries, kind="confirm") is not None
                    or find_clarity_popup_button(popup_entries, kind="cancel") is not None
                ):
                    break

            if popup_reports_no_stock(popup_entries):
                cancel_pt = find_clarity_popup_button(popup_entries, kind="cancel") or (320, 585)
                if not tap_point(context, f"{argv.node_name}Cancel{attempt}", cancel_pt):
                    return False
                if not sleep_with_stop(context, 0.5):
                    return False
                excluded_keys.add(key)
                continue

            if find_clarity_popup_button(popup_entries, kind="confirm") is None:
                cancel_pt = find_clarity_popup_button(popup_entries, kind="cancel")
                if cancel_pt is not None:
                    tap_point(context, f"{argv.node_name}Dismiss{attempt}", cancel_pt)
                    sleep_with_stop(context, 0.4)
                excluded_keys.add(key)
                continue

            _, ok = self._confirm_popup_and_finish(
                context,
                argv.node_name,
                popup_entries,
                attempt=attempt,
                card_key=key,
                used_counts=used_counts,
            )
            return ok

        return False

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
    clarity_popup_item_keys,
    find_clarity_popup_button,
    has_clarity_popup_context,
    is_clarity_confirm_popup,
    parse_clarity_cards,
    parse_clarity_limits,
    parse_clarity_status,
    popup_reports_no_stock,
)

_CLARITY_USED_BY_TASK: dict[int, dict[str, int]] = {}


def _cancel_and_stop(context: Context, node_name: str, entries: list[dict[str, Any]], reason: str) -> bool:
    print(f"[ClarityRecovery] {reason}，已停止恢复。", flush=True)
    cancel = find_clarity_popup_button(entries, kind="cancel")
    if cancel is not None:
        tap_point(context, node_name, cancel)
    return False


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
        card: dict[str, Any],
        before_status: dict[str, int] | None,
        used_counts: dict[str, int],
    ) -> bool:
        """Retry on a positively identified dialog and count a verified recovery once."""
        entries = popup_entries
        key = card["key"]

        for retry in range(3):
            if not is_clarity_confirm_popup(entries) or popup_reports_no_stock(entries):
                return _cancel_and_stop(context, f"{node_name}AbortCancel{attempt}", entries, "无法确认当前恢复弹窗")
            if clarity_popup_item_keys(entries) - {key}:
                return _cancel_and_stop(context, f"{node_name}AbortCancel{attempt}", entries, "弹窗物品与本次选择不符")
            confirm_pt = find_clarity_popup_button(entries, kind="confirm")
            if not tap_point(context, f"{node_name}Confirm{attempt}_{retry}", confirm_pt):
                return False
            if not sleep_with_stop(context, 0.85):
                return False
            after_img = safe_screencap(context)
            if after_img is None:
                return False
            entries = ocr_roi(
                context,
                after_img,
                f"{node_name}After{attempt}_{retry}",
                [0, 0, 1280, 720],
            )
            if not is_clarity_confirm_popup(entries):
                break
        else:
            return _cancel_and_stop(
                context, f"{node_name}AbortCancel{attempt}", entries, "连续三次确认后恢复弹窗仍未关闭",
            )

        if popup_reports_no_stock(entries):
            return _cancel_and_stop(context, f"{node_name}AbortCancel{attempt}", entries, "恢复物品不可用")
        text = " ".join(str(e.get("text") or "") for e in entries)
        recovered = any(word in text for word in ("已恢复", "已消除", "恢复成功", "补充成功", "使用成功"))
        notice = recovered or any(word in text for word in ("触碰空白区域退出", "点击空白处关闭", "点击任意位置继续"))
        if recovered:
            used_counts[key] = used_counts.get(key, 0) + 1
        if notice:
            if not tap_point(context, f"{node_name}CloseNotice{attempt}", (640, 650)):
                return False
            if not sleep_with_stop(context, 0.5):
                return False
            notice_img = safe_screencap(context)
            if notice_img is None:
                return False
            entries = ocr_roi(
                context,
                notice_img,
                f"{node_name}AfterNotice{attempt}",
                [0, 0, 1280, 720],
            )

        at_picker = any("请选择恢复方式" in str(e.get("text") or "") for e in entries)
        if not recovered:
            if not at_picker or is_clarity_confirm_popup(entries) or popup_reports_no_stock(entries):
                print("[ClarityRecovery] 未能核实恢复结果，已停止。", flush=True)
                return False
            after_status = parse_clarity_status(entries)
            increased = False
            if before_status and after_status and before_status["total"] == after_status["total"]:
                expected_gain = max(1, min(card["restore"], before_status["remaining_gap"]))
                increased = after_status["current"] - before_status["current"] >= expected_gain
            remaining = next(c["count"] for c in parse_clarity_cards(entries) if c["key"] == key)
            consumed = remaining is not None and card["count"] is not None and remaining < card["count"]
            if not (increased or consumed):
                print("[ClarityRecovery] 未检测到澄明度增加或所选物品减少，已停止。", flush=True)
                return False
            used_counts[key] = used_counts.get(key, 0) + 1
        if at_picker:
            if not tap_point(context, f"{node_name}Back", CLARITY_BACK_POINT):
                return False
            sleep_with_stop(context, 0.7)
        return True

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = parse_action_param(getattr(argv, "custom_action_param", None))
        limits = parse_clarity_limits(params)
        task_id = getattr(getattr(argv, "task_detail", None), "task_id", None)
        task_key = int(task_id) if task_id is not None else id(context.tasker)
        used_counts = _CLARITY_USED_BY_TASK.get(task_key, {})
        excluded_keys: set[str] = set()

        for attempt in range(4):
            image = safe_screencap(context)
            if image is None:
                return False
            entries = ocr_roi(context, image, f"{argv.node_name}Scan{attempt}", [0, 0, 1280, 720])
            if (
                has_clarity_popup_context(entries)
                or find_clarity_popup_button(entries, kind="confirm")
                or find_clarity_popup_button(entries, kind="cancel")
            ):
                return _cancel_and_stop(context, f"{argv.node_name}UnexpectedCancel", entries, "检测到非本次选择打开的确认弹窗")

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

            if not tap_point(context, f"{argv.node_name}Card{attempt}", chosen["tap_point"]):
                return False
            for sample in range(2):
                if not sleep_with_stop(context, 0.65):
                    return False
                popup_img = safe_screencap(context)
                if popup_img is None:
                    return False
                popup_entries = ocr_roi(
                    context,
                    popup_img,
                    f"{argv.node_name}Popup{attempt}_{sample}",
                    list(CLARITY_POPUP_ROI),
                )
                if (
                    popup_reports_no_stock(popup_entries)
                    or find_clarity_popup_button(popup_entries, kind="confirm") is not None
                    or find_clarity_popup_button(popup_entries, kind="cancel") is not None
                ):
                    break

            if popup_reports_no_stock(popup_entries):
                cancel_pt = find_clarity_popup_button(popup_entries, kind="cancel")
                if cancel_pt is None or not tap_point(context, f"{argv.node_name}Cancel{attempt}", cancel_pt):
                    return False
                if not sleep_with_stop(context, 0.5):
                    return False
                excluded_keys.add(key)
                continue

            return self._confirm_popup_and_finish(
                context,
                argv.node_name,
                popup_entries,
                attempt=attempt,
                card=chosen,
                before_status=status,
                used_counts=_CLARITY_USED_BY_TASK.setdefault(task_key, used_counts),
            )

        return False


if hasattr(AgentServer, "tasker_sink"):
    from maa.event_sink import NotificationType
    from maa.tasker import TaskerEventSink

    @AgentServer.tasker_sink()
    class ClarityQuotaCleanup(TaskerEventSink):
        def on_tasker_task(self, tasker, noti_type, detail):
            if noti_type in (NotificationType.Succeeded, NotificationType.Failed):
                _CLARITY_USED_BY_TASK.pop(detail.task_id, None)

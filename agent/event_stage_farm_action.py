"""Custom MaaFramework recognitions and actions for Event Stage Farming."""
from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from agent.utils.action_helpers import ocr_roi, parse_action_param, poll_screen, swipe_points, tap_point
from agent.utils.activity_hub_nav import open_activity_hub, select_activity_tab
from agent.utils.input_guard import run_guarded_click, safe_screencap, sleep_with_stop
from agent.utils.lobby_nav import is_stopping, return_to_lobby
from maa_resonance.logic.daily_routine import REWARD_POPUP_TOP_SAFE_POINT
from maa_resonance.logic.event_stage_farm import (
    LOW_CLARITY_CANCEL_POINT,
    LOW_CLARITY_CONFIRM_POINT,
    LOW_CLARITY_PROMPT_ROI,
    MINISCAPE_BREAK_BTN_FALLBACK,
    MINISCAPE_BREAK_BTN_ROI,
    STAGE_AUTO_TEXT_ROI,
    STAGE_AUTO_TOGGLE_POINT,
    STAGE_DETAIL_CLARITY_ROI,
    STAGE_DETAIL_TITLE_ROI,
    STAGE_ENTER_BTN_FALLBACK,
    STAGE_ENTER_BTN_ROI,
    STAGE_LIST_SWIPE_LEFT,
    STAGE_LIST_SWIPE_RIGHT,
    find_miniscape_break_button,
    find_stage_card_point,
    find_stage_enter_button_point,
    has_auto_repeat_toggle_label,
    has_stage_detail_overlay_entries,
    is_low_clarity_confirm_popup,
    is_stage_auto_repeat_on,
    is_stage_battle_or_loading_entries,
    is_stage_detail_open,
    is_stage_list_screen_entries,
    parse_run_count_limit,
)

STAGE_FARM_ATTACH_NODES: tuple[str, ...] = (
    "EventStageFarmOptTarget",
    "EventStageFarmOptStageName",
    "EventStageFarmOptRunMode",
    "EventStageFarmOptRunCount",
    "EventStageFarmOptNativeRepeat",
    "EventStageFarmOptUseMedicine",
)
_STAGE_STATE_BY_TASK: dict[int, dict[str, Any]] = {}


def _stage_state(context: Context, argv: Any) -> dict[str, Any]:
    task_detail = getattr(argv, "task_detail", None)
    task_id = getattr(task_detail, "task_id", None)
    key = int(task_id) if task_id is not None else id(getattr(context, "tasker", context))
    if len(_STAGE_STATE_BY_TASK) > 32:
        _STAGE_STATE_BY_TASK.clear()
    return _STAGE_STATE_BY_TASK.setdefault(
        key,
        {"completed_runs": 0, "auto_wait_ticks": 0, "auto_toggle_attempts": 0, "done": False},
    )


def _resolve_stage_params(context: Context, argv: Any, param_attr: str = "custom_action_param") -> dict[str, Any]:
    merged = dict(parse_action_param(getattr(argv, param_attr, None)))
    get_node_data = getattr(context, "get_node_data", None)
    if callable(get_node_data):
        for node_name in STAGE_FARM_ATTACH_NODES:
            try:
                node_data = get_node_data(node_name)
            except Exception:
                node_data = None
            if isinstance(node_data, dict) and isinstance(node_data.get("attach"), dict):
                merged.update(node_data["attach"])
    return merged


def _select_stage_from_carousel_status(
    context: Context,
    prefix: str,
    target_stage_name: str,
) -> str:
    """Select target stage card on the horizontal carousel.

    Returns ``'selected' | 'interrupted' | 'not_found' | 'stopped'``.
    """
    for swipe_idx in range(5):
        img = safe_screencap(context)
        if img is None:
            return "stopped"
        entries = ocr_roi(context, img, f"{prefix}List{swipe_idx}", [0, 80, 1280, 560])
        if (
            is_stage_battle_or_loading_entries(entries)
            or has_stage_detail_overlay_entries(entries)
            or is_low_clarity_confirm_popup(entries)
        ):
            print("[EventStageFarm] 检测到页面已切换至详情/战斗/加载或体力弹窗，取消切卡让主循环接管。", flush=True)
            return "interrupted"
        if not is_stage_list_screen_entries(entries):
            if not sleep_with_stop(context, 0.4):
                return "stopped"
            return "interrupted"
        card_pt = find_stage_card_point(entries, target_stage_name)
        if card_pt is not None:
            if not tap_point(context, f"{prefix}TapCard{swipe_idx}", card_pt):
                return "stopped"
            if not sleep_with_stop(context, 1.1):
                return "stopped"
            return "selected"

        if swipe_idx < 2:
            x1, y1, x2, y2 = STAGE_LIST_SWIPE_LEFT
        elif swipe_idx < 4:
            x1, y1, x2, y2 = STAGE_LIST_SWIPE_RIGHT
        else:
            break
        if not swipe_points(
            context,
            f"{prefix}Swipe{swipe_idx}",
            (x1, y1),
            (x2, y2),
            duration=360,
            end_hold=150,
        ):
            return "stopped"
        if not sleep_with_stop(context, 0.85):
            return "stopped"
    return "not_found"


def _select_stage_from_carousel(
    context: Context,
    prefix: str,
    target_stage_name: str,
) -> bool:
    return _select_stage_from_carousel_status(context, prefix, target_stage_name) == "selected"


def _finish_to_lobby(context: Context, argv: Any, prefix: str) -> bool:
    state = _stage_state(context, argv)
    state["done"] = True
    img = safe_screencap(context)
    if img is not None:
        prompt_entries = ocr_roi(context, img, f"{prefix}PromptCheck", LOW_CLARITY_PROMPT_ROI)
        if is_low_clarity_confirm_popup(prompt_entries):
            tap_point(context, f"{prefix}CancelLowClarity", LOW_CLARITY_CANCEL_POINT)
            sleep_with_stop(context, 0.6)
    return_to_lobby(context, f"{prefix}Lobby", dismiss_point=REWARD_POPUP_TOP_SAFE_POINT)
    return not is_stopping(context)


@AgentServer.custom_recognition("event_stage_farm_is_done")
class EventStageFarmIsDoneRecognition(CustomRecognition):
    def analyze(self, context: Context, argv: CustomRecognition.AnalyzeArg) -> CustomRecognition.AnalyzeResult | None:
        if _stage_state(context, argv).get("done"):
            return CustomRecognition.AnalyzeResult(box=[0, 0, 10, 10], detail={"done": True})
        return None


@AgentServer.custom_recognition("event_stage_farm_detail_ready")
class EventStageFarmDetailReadyRecognition(CustomRecognition):
    def analyze(self, context: Context, argv: CustomRecognition.AnalyzeArg) -> CustomRecognition.AnalyzeResult | None:
        if _stage_state(context, argv).get("done"):
            return None
        params = _resolve_stage_params(context, argv, "custom_recognition_param")
        target_stage = "" if params.get("target") == "current_stage_detail" else str(params.get("target_stage_name") or "")
        title_entries = ocr_roi(context, argv.image, "StageDetailTitle", STAGE_DETAIL_TITLE_ROI)
        enter_entries = ocr_roi(context, argv.image, "StageDetailEnter", STAGE_ENTER_BTN_ROI)
        if is_stage_detail_open(title_entries, enter_entries, target_stage):
            return CustomRecognition.AnalyzeResult(box=[860, 535, 370, 80], detail={"detail": True})
        return None


@AgentServer.custom_recognition("event_stage_farm_list_ready")
class EventStageFarmListReadyRecognition(CustomRecognition):
    def analyze(self, context: Context, argv: CustomRecognition.AnalyzeArg) -> CustomRecognition.AnalyzeResult | None:
        if _stage_state(context, argv).get("done"):
            return None
        entries = ocr_roi(context, argv.image, "StageListCheck", [20, 20, 1240, 560])
        if is_stage_list_screen_entries(entries):
            return CustomRecognition.AnalyzeResult(box=[20, 200, 1240, 340], detail={"list": True})
        return None


@AgentServer.custom_action("event_stage_farm_navigate")
class EventStageFarmNavigateAction(CustomAction):
    """Reset per-run counters and navigate to the configured stage detail screen."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        state = _stage_state(context, argv)
        state["completed_runs"] = 0
        state["auto_wait_ticks"] = 0
        state["auto_toggle_attempts"] = 0
        state["done"] = False

        prefix = f"{argv.node_name}_Nav"
        params = _resolve_stage_params(context, argv)
        target = str(params.get("target") or "miniscape_break")
        target_stage_name = str(params.get("target_stage_name") or "调查报告7").strip() or "调查报告7"

        if target == "current_stage_detail":
            return CustomAction.RunResult(success=True)

        img = safe_screencap(context)
        if img is None:
            return CustomAction.RunResult(success=False)

        title_entries = ocr_roi(context, img, f"{prefix}InitTitle", STAGE_DETAIL_TITLE_ROI)
        enter_entries = ocr_roi(context, img, f"{prefix}InitEnter", STAGE_ENTER_BTN_ROI)
        if is_stage_detail_open(title_entries, enter_entries, target_stage_name):
            return CustomAction.RunResult(success=True)

        if not is_stage_list_screen_entries(ocr_roi(context, img, f"{prefix}InitList", [20, 20, 1240, 560])):
            if not open_activity_hub(context, prefix):
                return CustomAction.RunResult(success=False)
            entered, _ = select_activity_tab(context, prefix, "限时活动", ("箱庭内外",))
            if not entered:
                print("[EventStageFarm] 未找到限时活动「箱庭内外」，安全结束。", flush=True)
                _finish_to_lobby(context, argv, f"{prefix}NotFound")
                return CustomAction.RunResult(success=not is_stopping(context))
            _, break_pt, aborted = poll_screen(
                context,
                lambda frame, idx: find_miniscape_break_button(
                    ocr_roi(context, frame, f"{prefix}BreakBtn{idx}", MINISCAPE_BREAK_BTN_ROI)
                ),
                initial_delay=0.0,
                interval=0.45,
                max_checks=3,
                screencap_fn=safe_screencap,
                sleep_fn=sleep_with_stop,
            )
            if aborted:
                return CustomAction.RunResult(success=False)
            if not tap_point(context, f"{prefix}EnterBreak", break_pt or MINISCAPE_BREAK_BTN_FALLBACK):
                return CustomAction.RunResult(success=False)
            if not sleep_with_stop(context, 1.4):
                return CustomAction.RunResult(success=False)

            def _check_carousel_ready(frame: Any, idx: int) -> bool | None:
                carousel_entries = ocr_roi(context, frame, f"{prefix}WaitList{idx}", [0, 80, 1280, 560])
                if is_stage_list_screen_entries(carousel_entries) or has_stage_detail_overlay_entries(carousel_entries):
                    return True
                return None

            _, _, aborted = poll_screen(
                context,
                _check_carousel_ready,
                initial_delay=0.0,
                interval=0.45,
                max_checks=3,
                screencap_fn=safe_screencap,
                sleep_fn=sleep_with_stop,
            )
            if aborted:
                return CustomAction.RunResult(success=False)

        status = _select_stage_from_carousel_status(context, prefix, target_stage_name)
        if status == "stopped":
            return CustomAction.RunResult(success=False)
        if status == "not_found":
            print(f"[EventStageFarm] 未能定位关卡「{target_stage_name}」，返回大厅。", flush=True)
            _finish_to_lobby(context, argv, f"{prefix}StageMiss")
            return CustomAction.RunResult(success=not is_stopping(context))

        return CustomAction.RunResult(success=not is_stopping(context))


@AgentServer.custom_action("event_stage_farm_select_stage_from_list")
class EventStageFarmSelectStageFromListAction(CustomAction):
    """Select the target stage card when returned to the horizontal stage carousel."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        params = _resolve_stage_params(context, argv)
        target_stage_name = str(params.get("target_stage_name") or "调查报告7").strip() or "调查报告7"
        status = _select_stage_from_carousel_status(context, f"{argv.node_name}_Pick", target_stage_name)
        if status == "stopped":
            return CustomAction.RunResult(success=False)
        if status == "not_found" and not is_stopping(context):
            _finish_to_lobby(context, argv, f"{argv.node_name}_Miss")
        return CustomAction.RunResult(success=not is_stopping(context))


@AgentServer.custom_action("event_stage_farm_detail_step")
class EventStageFarmDetailStepAction(CustomAction):
    """Handle stage detail screen: fixed count vs native continuous auto-repeat."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        state = _stage_state(context, argv)
        prefix = f"{argv.node_name}_Detail"
        params = _resolve_stage_params(context, argv)
        run_mode = str(params.get("run_mode") or "until_clarity_exhausted")
        run_count = parse_run_count_limit(params.get("run_count", 0))
        use_native_repeat = bool(params.get("use_native_auto_repeat", True))

        img = safe_screencap(context)
        if img is None:
            return CustomAction.RunResult(success=False)

        auto_entries = ocr_roi(context, img, f"{prefix}AutoTxt", STAGE_AUTO_TEXT_ROI)
        has_toggle = has_auto_repeat_toggle_label(auto_entries)
        toggle_on = is_stage_auto_repeat_on(img, auto_entries) if has_toggle else False

        if run_mode == "fixed_count" and run_count > 0 and int(state["completed_runs"]) >= run_count:
            if toggle_on:
                tap_point(context, f"{prefix}TurnOffAutoStop", STAGE_AUTO_TOGGLE_POINT)
                sleep_with_stop(context, 0.5)
            print(f"[EventStageFarm] 已完成指定次数 {state['completed_runs']}/{run_count}，返回大厅。", flush=True)
            _finish_to_lobby(context, argv, f"{prefix}CountDone")
            return CustomAction.RunResult(success=not is_stopping(context))

        if run_mode != "fixed_count" and use_native_repeat and has_toggle:
            if not toggle_on:
                attempts = int(state.get("auto_toggle_attempts", 0)) + 1
                state["auto_toggle_attempts"] = attempts
                if attempts < 2:
                    if not tap_point(context, f"{prefix}TurnOnAuto", STAGE_AUTO_TOGGLE_POINT):
                        return CustomAction.RunResult(success=False)
                    print("[EventStageFarm] 已开启关卡原生「自动战斗」连战。", flush=True)
                    state["auto_wait_ticks"] = 0
                    sleep_with_stop(context, 1.2)
                    return CustomAction.RunResult(success=not is_stopping(context))
                state["auto_toggle_attempts"] = 0
                state["auto_wait_ticks"] = 0
            else:
                state["auto_toggle_attempts"] = 0
                state["auto_wait_ticks"] = int(state.get("auto_wait_ticks", 0)) + 1
                if int(state["auto_wait_ticks"]) < 3:
                    sleep_with_stop(context, 1.0)
                    return CustomAction.RunResult(success=not is_stopping(context))
                state["auto_wait_ticks"] = 0
        elif toggle_on:
            if not tap_point(context, f"{prefix}TurnOffAutoFixed", STAGE_AUTO_TOGGLE_POINT):
                return CustomAction.RunResult(success=False)
            if not sleep_with_stop(context, 0.55):
                return CustomAction.RunResult(success=False)

        enter_entries = ocr_roi(context, img, f"{prefix}EnterBtn", STAGE_ENTER_BTN_ROI)
        enter_pt = find_stage_enter_button_point(enter_entries) or STAGE_ENTER_BTN_FALLBACK
        if not tap_point(context, f"{prefix}EnterStage", enter_pt):
            return CustomAction.RunResult(success=False)
        sleep_with_stop(context, 1.2)
        return CustomAction.RunResult(success=not is_stopping(context))


@AgentServer.custom_action("event_stage_farm_settle_next")
class EventStageFarmSettleNextAction(CustomAction):
    """Click settlement '下一步' via guarded_click and increment completed_runs."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        state = _stage_state(context, argv)
        box = getattr(argv, "box", None)
        x = y = w = h = 0
        if isinstance(box, (list, tuple)) and len(box) >= 4:
            x, y, w, h = int(box[0]), int(box[1]), int(box[2]), int(box[3])
        elif box is not None and all(hasattr(box, attr) for attr in ("x", "y", "w", "h")):
            x, y, w, h = int(box.x), int(box.y), int(box.w), int(box.h)
        cx = int(round(x + w / 2.0)) if w > 0 else 1170
        cy = int(round(y + h / 2.0)) if h > 0 else 610
        ok = run_guarded_click(context, f"{argv.node_name}Guarded", cx, cy)
        if ok:
            state["completed_runs"] = int(state["completed_runs"]) + 1
            state["auto_wait_ticks"] = 0
            state["auto_toggle_attempts"] = 0
            print(f"[EventStageFarm] 本轮已完成第 {state['completed_runs']} 场结算。", flush=True)
        return CustomAction.RunResult(success=ok)


@AgentServer.custom_action("event_stage_farm_handle_low_clarity")
class EventStageFarmHandleLowClarityAction(CustomAction):
    """Either confirm into Clarity Recovery (if medicine enabled) or cancel and exit cleanly to lobby."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        params = _resolve_stage_params(context, argv)
        use_medicine = bool(params.get("use_medicine", False))
        if use_medicine:
            if not tap_point(context, f"{argv.node_name}Confirm", LOW_CLARITY_CONFIRM_POINT):
                return CustomAction.RunResult(success=False)
            sleep_with_stop(context, 0.8)
            return CustomAction.RunResult(success=not is_stopping(context))

        print("[EventStageFarm] 澄明度不足且未开启吃药，取消并返回大厅结束刷关。", flush=True)
        _finish_to_lobby(context, argv, f"{argv.node_name}Exit")
        return CustomAction.RunResult(success=not is_stopping(context))


@AgentServer.custom_action("event_stage_farm_finish_to_lobby")
class EventStageFarmFinishToLobbyAction(CustomAction):
    """Cancel any clarity modal and return cleanly to the train lobby."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        print("[EventStageFarm] 体力或药剂配额已耗尽，返回大厅结束刷关。", flush=True)
        ok = _finish_to_lobby(context, argv, f"{argv.node_name}_Finish")
        return CustomAction.RunResult(success=ok)

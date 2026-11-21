"""Custom MaaFramework recognitions and actions for Event Story Daily (糖霜记忆每日取景)."""
from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from agent.utils.action_helpers import ocr_roi, poll_screen, tap_point
from agent.utils.activity_hub_nav import open_activity_hub, select_activity_tab
from agent.utils.input_guard import safe_screencap, sleep_with_stop
from agent.utils.lobby_nav import is_stopping, return_to_lobby
from maa_resonance.logic.daily_routine import REWARD_POPUP_TOP_SAFE_POINT
from maa_resonance.logic.event_story_daily import (
    FROSTING_CARDS_ROI,
    FROSTING_DRAWER_BTN_FALLBACK,
    FROSTING_DRAWER_BTN_ROI,
    FROSTING_DRAWER_INFO_ROI,
    FROSTING_ENTER_FALLBACK,
    FROSTING_ENTER_ROI,
    FROSTING_HEADER_ROI,
    find_frosting_drawer_start_point,
    find_frosting_enter_point,
    find_frosting_start_card_point,
    is_frosting_cards_screen_entries,
    is_frosting_drawer_open,
    is_frosting_home_entries,
)

_STORY_DAILY_STATE: dict[int, dict[str, Any]] = {}


def _story_state(context: Context, argv: Any) -> dict[str, Any]:
    task_detail = getattr(argv, "task_detail", None)
    task_id = getattr(task_detail, "task_id", None)
    key = int(task_id) if task_id is not None else id(getattr(context, "tasker", context))
    if len(_STORY_DAILY_STATE) > 32:
        _STORY_DAILY_STATE.clear()
    return _STORY_DAILY_STATE.setdefault(key, {"steps": 0, "done": False})


@AgentServer.custom_recognition("event_story_daily_is_done")
class EventStoryDailyIsDoneRecognition(CustomRecognition):
    def analyze(self, context: Context, argv: CustomRecognition.AnalyzeArg) -> CustomRecognition.AnalyzeResult | None:
        if _story_state(context, argv).get("done"):
            return CustomRecognition.AnalyzeResult(box=[0, 0, 10, 10], detail={"done": True})
        return None


@AgentServer.custom_recognition("event_story_daily_cards_ready")
class EventStoryDailyCardsReadyRecognition(CustomRecognition):
    def analyze(self, context: Context, argv: CustomRecognition.AnalyzeArg) -> CustomRecognition.AnalyzeResult | None:
        if _story_state(context, argv).get("done"):
            return None
        header_entries = ocr_roi(context, argv.image, "FrostingHdrCheck", FROSTING_HEADER_ROI)
        card_entries = ocr_roi(context, argv.image, "FrostingCardsCheck", FROSTING_CARDS_ROI)
        info_entries = ocr_roi(context, argv.image, "FrostingDrawerInfoCheck", FROSTING_DRAWER_INFO_ROI)
        btn_entries = ocr_roi(context, argv.image, "FrostingDrawerBtnCheck", FROSTING_DRAWER_BTN_ROI)
        if is_frosting_cards_screen_entries(header_entries, card_entries) or is_frosting_drawer_open(
            info_entries, btn_entries
        ):
            return CustomRecognition.AnalyzeResult(box=[60, 540, 1160, 100], detail={"cards": True})
        return None


@AgentServer.custom_action("event_story_daily_enter")
class EventStoryDailyEnterAction(CustomAction):
    """Navigate to Activity Hub -> 糖霜记忆 -> 前往取景."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        state = _story_state(context, argv)
        state["steps"] = 0
        state["done"] = False

        prefix = f"{argv.node_name}_Enter"
        img = safe_screencap(context)
        if img is None:
            return CustomAction.RunResult(success=False)

        header_entries = ocr_roi(context, img, f"{prefix}InitHdr", FROSTING_HEADER_ROI)
        card_entries = ocr_roi(context, img, f"{prefix}InitCards", FROSTING_CARDS_ROI)
        if is_frosting_cards_screen_entries(header_entries, card_entries):
            return CustomAction.RunResult(success=True)

        home_entries = ocr_roi(context, img, f"{prefix}InitHome", FROSTING_ENTER_ROI)
        if not is_frosting_home_entries(home_entries):
            if not open_activity_hub(context, prefix):
                return CustomAction.RunResult(success=not is_stopping(context))
            entered, _ = select_activity_tab(context, prefix, "限时活动", ("糖霜记忆",))
            if not entered:
                print("[EventStoryDaily] 未找到限时活动「糖霜记忆」，返回大厅。", flush=True)
                state["done"] = True
                return_to_lobby(context, f"{prefix}NotFound")
                return CustomAction.RunResult(success=not is_stopping(context))

            def _check_frosting_home(frame: Any, idx: int) -> tuple[bool, list[dict[str, Any]]] | None:
                entries = ocr_roi(context, frame, f"{prefix}Home{idx}", FROSTING_ENTER_ROI)
                return (True, entries) if is_frosting_home_entries(entries) else None

            _, home_matched, aborted = poll_screen(
                context,
                _check_frosting_home,
                initial_delay=0.0,
                interval=0.45,
                max_checks=3,
                screencap_fn=safe_screencap,
                sleep_fn=sleep_with_stop,
            )
            if aborted:
                return CustomAction.RunResult(success=False)
            home_entries = home_matched[1] if home_matched is not None else []

        enter_pt = find_frosting_enter_point(home_entries) or FROSTING_ENTER_FALLBACK
        if not tap_point(context, f"{prefix}OpenCards", enter_pt):
            return CustomAction.RunResult(success=False)
        sleep_with_stop(context, 1.4)
        return CustomAction.RunResult(success=not is_stopping(context))


@AgentServer.custom_action("event_story_daily_card_step")
class EventStoryDailyCardStepAction(CustomAction):
    """Click active '开始取景' card and open formation, or exit to lobby when none remain."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        state = _story_state(context, argv)
        state["steps"] = int(state["steps"]) + 1
        prefix = f"{argv.node_name}_Step{state['steps']}"

        if int(state["steps"]) > 8:
            state["done"] = True
            return_to_lobby(context, f"{prefix}MaxSteps", dismiss_point=REWARD_POPUP_TOP_SAFE_POINT)
            return CustomAction.RunResult(success=not is_stopping(context))

        img = safe_screencap(context)
        if img is None:
            return CustomAction.RunResult(success=False)

        info_entries = ocr_roi(context, img, f"{prefix}Info", FROSTING_DRAWER_INFO_ROI)
        btn_entries = ocr_roi(context, img, f"{prefix}Btn", FROSTING_DRAWER_BTN_ROI)
        if is_frosting_drawer_open(info_entries, btn_entries):
            start_pt = find_frosting_drawer_start_point(btn_entries) or FROSTING_DRAWER_BTN_FALLBACK
            if not tap_point(context, f"{prefix}DrawerStart", start_pt):
                return CustomAction.RunResult(success=False)
            sleep_with_stop(context, 1.35)
            return CustomAction.RunResult(success=not is_stopping(context))

        card_entries = ocr_roi(context, img, f"{prefix}Cards", FROSTING_CARDS_ROI)
        card_pt = find_frosting_start_card_point(card_entries)
        if card_pt is None:
            if not sleep_with_stop(context, 0.7):
                return CustomAction.RunResult(success=False)
            retry_img = safe_screencap(context)
            if retry_img is None:
                return CustomAction.RunResult(success=False)
            card_entries = ocr_roi(context, retry_img, f"{prefix}CardsRetry", FROSTING_CARDS_ROI)
            card_pt = find_frosting_start_card_point(card_entries)
        if card_pt is None:
            print("[EventStoryDaily] 「糖霜记忆」当前无待取景卡片，返回大厅。", flush=True)
            state["done"] = True
            return_to_lobby(context, f"{prefix}AllDone", dismiss_point=REWARD_POPUP_TOP_SAFE_POINT)
            return CustomAction.RunResult(success=not is_stopping(context))

        if not tap_point(context, f"{prefix}TapCard", card_pt):
            return CustomAction.RunResult(success=False)
        if not sleep_with_stop(context, 1.1):
            return CustomAction.RunResult(success=False)

        img2 = safe_screencap(context)
        if img2 is not None:
            info2 = ocr_roi(context, img2, f"{prefix}Info2", FROSTING_DRAWER_INFO_ROI)
            btn2 = ocr_roi(context, img2, f"{prefix}Btn2", FROSTING_DRAWER_BTN_ROI)
            if is_frosting_drawer_open(info2, btn2):
                start_pt = find_frosting_drawer_start_point(btn2) or FROSTING_DRAWER_BTN_FALLBACK
                if not tap_point(context, f"{prefix}DrawerStart2", start_pt):
                    return CustomAction.RunResult(success=False)
                sleep_with_stop(context, 1.35)

        return CustomAction.RunResult(success=not is_stopping(context))

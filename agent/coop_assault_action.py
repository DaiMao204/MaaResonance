"""Custom MaaFramework recognitions and actions for Coop Assault (限时共斗 · 众志攻坚)."""
from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from agent.utils.action_helpers import ocr_roi, parse_action_param, poll_screen, tap_point
from agent.utils.activity_hub_nav import open_activity_hub, select_activity_tab
from agent.utils.input_guard import safe_screencap, sleep_with_stop
from agent.utils.lobby_nav import dismiss_reward_popup_if_present, is_stopping, return_to_lobby
from maa_resonance.logic.coop_assault import (
    COOP_HOME_ENTER_FALLBACK,
    COOP_HOME_ENTER_ROI,
    COOP_PREPARE_ENTER_ROI,
    COOP_REMAINING_ROI,
    COOP_REWARD_BTN_FALLBACK,
    COOP_REWARD_BTN_ROI,
    COOP_REWARD_CLAIM_ROI,
    COOP_REWARD_TABS_ROI,
    choose_coop_boss_slot,
    choose_coop_difficulty_point,
    detect_unlocked_coop_difficulties,
    find_coop_home_enter_point,
    find_coop_prepare_enter_point,
    find_coop_reward_claim_point,
    is_coop_boss_map_entries,
    is_coop_home_entries,
    is_coop_prepare_entries,
    is_coop_reward_screen_entries,
    parse_coop_boss_slots,
    parse_coop_remaining_attempts,
    parse_coop_reward_tabs,
)
from maa_resonance.logic.daily_routine import REWARD_POPUP_TOP_SAFE_POINT, TOP_BACK_POINT

COOP_ATTACH_NODES: tuple[str, ...] = (
    "CoopAssaultOptBossPreference",
    "CoopAssaultOptDifficulty",
    "CoopAssaultOptMaxRuns",
    "CoopAssaultOptClaimRewards",
)
_COOP_STATE_BY_TASK: dict[int, dict[str, Any]] = {}


def _task_state(context: Context, argv: Any) -> dict[str, Any]:
    task_detail = getattr(argv, "task_detail", None)
    task_id = getattr(task_detail, "task_id", None)
    key = int(task_id) if task_id is not None else id(getattr(context, "tasker", context))
    if len(_COOP_STATE_BY_TASK) > 32:
        _COOP_STATE_BY_TASK.clear()
    return _COOP_STATE_BY_TASK.setdefault(
        key,
        {"initial_remaining": None, "steps": 0, "done": False},
    )


def _resolve_coop_params(context: Context, argv: Any, param_attr: str) -> dict[str, Any]:
    merged = dict(parse_action_param(getattr(argv, param_attr, None)))
    get_node_data = getattr(context, "get_node_data", None)
    if callable(get_node_data):
        for node_name in COOP_ATTACH_NODES:
            try:
                node_data = get_node_data(node_name)
            except Exception:
                node_data = None
            if isinstance(node_data, dict) and isinstance(node_data.get("attach"), dict):
                merged.update(node_data["attach"])
    return merged


def _should_fight_now(
    context: Context,
    image: Any,
    prefix: str,
    argv: Any,
    param_attr: str,
) -> tuple[bool, bool, tuple[int, int] | None]:
    """Return ``(on_boss_map, should_fight, remaining_tuple)``."""
    full_entries = ocr_roi(context, image, f"{prefix}Full", [0, 0, 1280, 720])
    if not is_coop_boss_map_entries(full_entries):
        return False, False, None

    rem_entries = ocr_roi(context, image, f"{prefix}Rem", COOP_REMAINING_ROI)
    rem_pair = parse_coop_remaining_attempts(rem_entries) or parse_coop_remaining_attempts(full_entries)
    if rem_pair is None:
        return True, False, None

    remaining, _ = rem_pair
    state = _task_state(context, argv)
    if state["initial_remaining"] is None:
        state["initial_remaining"] = remaining

    params = _resolve_coop_params(context, argv, param_attr)
    max_runs = int(params.get("max_runs", 0) or 0)
    runs_done = max(0, int(state["initial_remaining"]) - remaining)
    step_cap = (max_runs if max_runs > 0 else 10) + 3
    should_fight = (
        remaining > 0
        and (max_runs <= 0 or runs_done < max_runs)
        and int(state["steps"]) < step_cap
    )
    return True, should_fight, rem_pair


@AgentServer.custom_recognition("coop_assault_is_done")
class CoopAssaultIsDoneRecognition(CustomRecognition):
    def analyze(self, context: Context, argv: CustomRecognition.AnalyzeArg) -> CustomRecognition.AnalyzeResult | None:
        state = _task_state(context, argv)
        if state.get("done"):
            return CustomRecognition.AnalyzeResult(box=[0, 0, 10, 10], detail={"done": True})
        return None


@AgentServer.custom_recognition("coop_assault_should_fight")
class CoopAssaultShouldFightRecognition(CustomRecognition):
    def analyze(self, context: Context, argv: CustomRecognition.AnalyzeArg) -> CustomRecognition.AnalyzeResult | None:
        if _task_state(context, argv).get("done"):
            return None
        on_map, should_fight, rem_pair = _should_fight_now(
            context, argv.image, "CoopCheckFight", argv, "custom_recognition_param"
        )
        if on_map and should_fight:
            return CustomRecognition.AnalyzeResult(box=[990, 15, 260, 60], detail={"remaining": rem_pair})
        return None


@AgentServer.custom_recognition("coop_assault_should_finish")
class CoopAssaultShouldFinishRecognition(CustomRecognition):
    def analyze(self, context: Context, argv: CustomRecognition.AnalyzeArg) -> CustomRecognition.AnalyzeResult | None:
        if _task_state(context, argv).get("done"):
            return None
        on_map, should_fight, rem_pair = _should_fight_now(
            context, argv.image, "CoopCheckFinish", argv, "custom_recognition_param"
        )
        if on_map and not should_fight:
            return CustomRecognition.AnalyzeResult(box=[990, 15, 260, 60], detail={"remaining": rem_pair})
        return None


@AgentServer.custom_recognition("coop_assault_prepare_ready")
class CoopAssaultPrepareReadyRecognition(CustomRecognition):
    def analyze(self, context: Context, argv: CustomRecognition.AnalyzeArg) -> CustomRecognition.AnalyzeResult | None:
        entries = ocr_roi(context, argv.image, "CoopPrepCheck", [300, 80, 820, 520])
        if is_coop_prepare_entries(entries):
            return CustomRecognition.AnalyzeResult(box=[300, 80, 820, 520], detail={"prepare": True})
        return None


@AgentServer.custom_action("coop_assault_enter_hub")
class CoopAssaultEnterHubAction(CustomAction):
    """Navigate to Activity Hub -> 众志攻坚 and enter the 3-boss map."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        state = _task_state(context, argv)
        state["initial_remaining"] = None
        state["steps"] = 0
        state["done"] = False

        prefix = f"{argv.node_name}_Hub"
        params = _resolve_coop_params(context, argv, "custom_action_param")
        claim_rewards = bool(params.get("claim_rewards", True))

        img = safe_screencap(context)
        if img is None:
            return CustomAction.RunResult(success=False)
        full_entries = ocr_roi(context, img, f"{prefix}Init", [0, 0, 1280, 720])
        if is_coop_boss_map_entries(full_entries):
            return CustomAction.RunResult(success=True)

        if not is_coop_home_entries(full_entries):
            if not open_activity_hub(context, prefix):
                return CustomAction.RunResult(success=False)
            entered, _ = select_activity_tab(context, prefix, "限时活动", ("众志攻坚",))
            if not entered:
                print("[CoopAssault] 未找到限时活动「众志攻坚」，结束任务。", flush=True)
                state["done"] = True
                return_to_lobby(context, f"{prefix}NotFound")
                return CustomAction.RunResult(success=not is_stopping(context))

            def _check_coop_home(frame: Any, idx: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
                f_e = ocr_roi(context, frame, f"{prefix}Home{idx}", [0, 0, 1280, 720])
                e_e = ocr_roi(context, frame, f"{prefix}EnterBtn{idx}", COOP_HOME_ENTER_ROI)
                if is_coop_home_entries(f_e) or find_coop_home_enter_point(e_e) is not None:
                    return (f_e, e_e)
                return None

            polled_img, home_matched, aborted = poll_screen(
                context,
                _check_coop_home,
                initial_delay=0.0,
                interval=0.45,
                max_checks=3,
                screencap_fn=safe_screencap,
                sleep_fn=sleep_with_stop,
            )
            if aborted:
                return CustomAction.RunResult(success=False)
            img = polled_img
            enter_roi_entries = (
                home_matched[1]
                if home_matched is not None
                else ocr_roi(context, img, f"{prefix}EnterBtn", COOP_HOME_ENTER_ROI)
            )
        else:
            enter_roi_entries = ocr_roi(context, img, f"{prefix}EnterBtn", COOP_HOME_ENTER_ROI)

        rem_pair = parse_coop_remaining_attempts(enter_roi_entries)
        if rem_pair is not None and rem_pair[0] <= 0 and not claim_rewards:
            print("[CoopAssault] 今日众志攻坚次数已耗尽（0/5）且无需领奖，返回大厅。", flush=True)
            state["done"] = True
            return_to_lobby(context, f"{prefix}ZeroAttempts")
            return CustomAction.RunResult(success=not is_stopping(context))

        enter_pt = find_coop_home_enter_point(enter_roi_entries) or COOP_HOME_ENTER_FALLBACK
        if not tap_point(context, f"{prefix}EnterBossMap", enter_pt):
            return CustomAction.RunResult(success=False)
        sleep_with_stop(context, 1.4)
        return CustomAction.RunResult(success=not is_stopping(context))


def _select_difficulty_and_enter(
    context: Context,
    prefix: str,
    preferred_difficulty: int,
) -> bool:
    for attempt in range(5):
        img = safe_screencap(context)
        if img is None:
            return False
        entries = ocr_roi(context, img, f"{prefix}Prep{attempt}", [300, 80, 820, 520])
        if not is_coop_prepare_entries(entries):
            if not sleep_with_stop(context, 0.5):
                return False
            continue
        unlocked = detect_unlocked_coop_difficulties(img)
        chosen_diff, diff_pt = choose_coop_difficulty_point(unlocked, preferred_difficulty)
        if not tap_point(context, f"{prefix}Diff{chosen_diff}", diff_pt):
            return False
        if not sleep_with_stop(context, 0.55):
            return False
        enter_entries = ocr_roi(context, img, f"{prefix}PrepBtn", COOP_PREPARE_ENTER_ROI)
        enter_pt = find_coop_prepare_enter_point(enter_entries)
        if not tap_point(context, f"{prefix}EnterFormation", enter_pt):
            return False
        if not sleep_with_stop(context, 1.25):
            return False
        return True
    return False


@AgentServer.custom_action("coop_assault_prepare_and_enter")
class CoopAssaultPrepareAndEnterAction(CustomAction):
    """Select target boss, choose difficulty, and enter formation."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        state = _task_state(context, argv)
        state["steps"] = int(state["steps"]) + 1
        prefix = f"{argv.node_name}_Fight{state['steps']}"
        params = _resolve_coop_params(context, argv, "custom_action_param")
        preference = str(params.get("boss_preference") or "alive_first")
        preferred_diff = int(params.get("preferred_difficulty", 0) or 0)

        img = safe_screencap(context)
        if img is None:
            return CustomAction.RunResult(success=False)
        full_entries = ocr_roi(context, img, f"{prefix}Scan", [0, 0, 1280, 720])
        slots = parse_coop_boss_slots(full_entries)
        chosen_slot = choose_coop_boss_slot(slots, preference=preference)
        if chosen_slot is None:
            print("[CoopAssault] 未能识别到可挑战的 BOSS 节点。", flush=True)
            return CustomAction.RunResult(success=False)

        print(
            f"[CoopAssault] 选择讨伐目标：{chosen_slot['name']} "
            f"(slot={chosen_slot['slot']}, hp={chosen_slot['hp_pct']}%)",
            flush=True,
        )
        if not tap_point(context, f"{prefix}BossTap", chosen_slot["tap_point"]):
            return CustomAction.RunResult(success=False)
        if not sleep_with_stop(context, 1.1):
            return CustomAction.RunResult(success=False)

        if not _select_difficulty_and_enter(context, prefix, preferred_diff):
            return CustomAction.RunResult(success=False)
        return CustomAction.RunResult(success=not is_stopping(context))


@AgentServer.custom_action("coop_assault_select_diff_and_enter")
class CoopAssaultSelectDiffAndEnterAction(CustomAction):
    """Select difficulty and enter formation when already on the boss prepare modal."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        params = _resolve_coop_params(context, argv, "custom_action_param")
        preferred_diff = int(params.get("preferred_difficulty", 0) or 0)
        ok = _select_difficulty_and_enter(context, f"{argv.node_name}_Modal", preferred_diff)
        return CustomAction.RunResult(success=ok and not is_stopping(context))


@AgentServer.custom_action("coop_assault_claim_and_finish")
class CoopAssaultClaimAndFinishAction(CustomAction):
    """Claim available Assault Report (攻坚战果) rewards across all boss tabs, then return to lobby."""

    def _claim_current_reward_tab(self, context: Context, prefix: str) -> bool:
        for step in range(4):
            img = safe_screencap(context)
            if img is None:
                return False
            claim_entries = ocr_roi(context, img, f"{prefix}Claim{step}", COOP_REWARD_CLAIM_ROI)
            claim_pt = find_coop_reward_claim_point(claim_entries)
            if claim_pt is None:
                return True
            if not tap_point(context, f"{prefix}TapClaim{step}", claim_pt):
                return False
            if not sleep_with_stop(context, 0.85):
                return False
            if not dismiss_reward_popup_if_present(
                context,
                f"{prefix}Dismiss{step}",
                dismiss_point=REWARD_POPUP_TOP_SAFE_POINT,
            ):
                return False
        return True

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        state = _task_state(context, argv)
        prefix = f"{argv.node_name}_Finish"
        params = _resolve_coop_params(context, argv, "custom_action_param")
        claim_rewards = bool(params.get("claim_rewards", True))

        if claim_rewards:
            img = safe_screencap(context)
            if img is None:
                return CustomAction.RunResult(success=False)
            btn_entries = ocr_roi(context, img, f"{prefix}RewardBtn", COOP_REWARD_BTN_ROI)
            btn_pt = COOP_REWARD_BTN_FALLBACK
            for entry in btn_entries:
                text = str(entry.get("text") or "")
                if "攻坚战果" in text or "REWARD" in text.upper():
                    if "center_x" in entry and "center_y" in entry:
                        btn_pt = (int(round(float(entry["center_x"]))), int(round(float(entry["center_y"]))))
                        break
            if not tap_point(context, f"{prefix}OpenRewards", btn_pt):
                return CustomAction.RunResult(success=False)

            img, matched_rewards, aborted = poll_screen(
                context,
                lambda frame, idx: is_coop_reward_screen_entries(
                    ocr_roi(context, frame, f"{prefix}Check{idx}", [300, 20, 960, 480])
                ),
                initial_delay=1.0,
                interval=0.5,
                max_checks=4,
                screencap_fn=safe_screencap,
                sleep_fn=sleep_with_stop,
            )
            if aborted:
                return CustomAction.RunResult(success=False)
            if matched_rewards:
                tab_entries = ocr_roi(context, img, f"{prefix}Tabs", COOP_REWARD_TABS_ROI)
                tabs = parse_coop_reward_tabs(tab_entries)
                for idx, (label, tab_pt) in enumerate(tabs):
                    if not tap_point(context, f"{prefix}Tab{idx}_{label}", tab_pt):
                        return CustomAction.RunResult(success=False)
                    if not sleep_with_stop(context, 0.75):
                        return CustomAction.RunResult(success=False)
                    if not self._claim_current_reward_tab(context, f"{prefix}T{idx}"):
                        return CustomAction.RunResult(success=False)
                tap_point(context, f"{prefix}RewardBack", TOP_BACK_POINT)
                sleep_with_stop(context, 0.85)

        state["done"] = True
        return_to_lobby(context, f"{prefix}Lobby", dismiss_point=REWARD_POPUP_TOP_SAFE_POINT)
        print("[CoopAssault] 众志攻坚讨伐与战果检查已全部完成。", flush=True)
        return CustomAction.RunResult(success=not is_stopping(context))

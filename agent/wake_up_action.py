"""Custom MaaFramework action for WakeUp (开始唤醒：过登录/热更/公告/月卡弹窗直达大厅)."""
from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from agent.utils.action_helpers import ocr_roi, parse_action_param, tap_point
from agent.utils.input_guard import get_effective_controller_info, safe_screencap, sleep_with_stop
from agent.utils.lobby_nav import is_drawer, is_lobby, is_stopping, return_to_lobby
from maa_resonance.logic.daily_routine import DRAWER_CLOSE_POINT
from maa_resonance.logic.wake_up import (
    WAKEUP_POPUP_SAFE_POINT,
    choose_wake_up_action,
    is_game_screen_entries,
)

WAKEUP_ATTACH_NODES: tuple[str, ...] = (
    "WakeUpOptAutoLaunchAdb",
    "WakeUpOptConfirmSmallUpdate",
    "WakeUpOptBlindDismiss",
)


def _resolve_wake_up_params(context: Context, argv: CustomAction.RunArg) -> dict[str, Any]:
    merged = dict(parse_action_param(getattr(argv, "custom_action_param", None)))
    get_node_data = getattr(context, "get_node_data", None)
    if callable(get_node_data):
        for node_name in WAKEUP_ATTACH_NODES:
            try:
                node_data = get_node_data(node_name)
            except Exception:
                node_data = None
            if isinstance(node_data, dict) and isinstance(node_data.get("attach"), dict):
                merged.update(node_data["attach"])
    return merged


def _is_adb_controller(context: Context) -> bool:
    info = get_effective_controller_info(context)
    ctrl_type = str(info.get("type") or "").strip().lower()
    if ctrl_type:
        return ctrl_type == "adb"
    ctrl = getattr(getattr(context, "tasker", None), "controller", None)
    cls_name = type(ctrl).__name__.lower() if ctrl is not None else ""
    return "adb" in cls_name


@AgentServer.custom_action("wake_up_to_lobby")
class WakeUpToLobbyAction(CustomAction):
    """Bring the game to the train lobby cleanly across ADB and Win32 PC."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        prefix = f"{argv.node_name}"
        params = _resolve_wake_up_params(context, argv)
        auto_launch_adb = bool(params.get("auto_launch_adb", True))
        auto_confirm_update = bool(params.get("auto_confirm_small_update", True))
        allow_blind_dismiss = bool(params.get("allow_blind_dismiss", True))
        max_download_mb = float(params.get("max_download_mb", 200.0) or 200.0)

        img = safe_screencap(context)
        if img is None:
            return CustomAction.RunResult(success=False)

        drawer_open, _ = is_drawer(context, f"{prefix}InitDrawer", img)
        if drawer_open:
            tap_point(context, f"{prefix}CloseInitDrawer", DRAWER_CLOSE_POINT)
            sleep_with_stop(context, 0.7)
            img = safe_screencap(context)
            if img is None:
                return CustomAction.RunResult(success=False)

        if is_lobby(context, f"{prefix}InitLobby", img):
            print("[WakeUp] 当前已在列车大厅，直接进入后续日常。", flush=True)
            return CustomAction.RunResult(success=True)

        full_entries = ocr_roi(context, img, f"{prefix}InitFull", [0, 0, 1280, 720])
        if _is_adb_controller(context) and auto_launch_adb and not is_game_screen_entries(full_entries):
            print("[WakeUp] 检测到 ADB 未处于游戏画面，尝试拉起《雷索纳斯》...", flush=True)
            context.run_action("WakeUpAdbStartApp", [0, 0, 1280, 720])
            if not sleep_with_stop(context, 6.0):
                return CustomAction.RunResult(success=False)

        unknown_streak = 0
        dismiss_streak = 0
        for step in range(36):
            img = safe_screencap(context)
            if img is None:
                return CustomAction.RunResult(success=False)

            drawer_open, _ = is_drawer(context, f"{prefix}D{step}", img)
            if drawer_open:
                if not tap_point(context, f"{prefix}CloseD{step}", DRAWER_CLOSE_POINT):
                    return CustomAction.RunResult(success=False)
                unknown_streak = 0
                dismiss_streak = 0
                if not sleep_with_stop(context, 0.7):
                    return CustomAction.RunResult(success=False)
                continue

            if is_lobby(context, f"{prefix}L{step}", img):
                # Wait briefly once to catch delayed login/monthly-card overlays right after entering lobby.
                if not sleep_with_stop(context, 1.2):
                    return CustomAction.RunResult(success=False)
                verify_img = safe_screencap(context)
                if verify_img is not None and is_lobby(context, f"{prefix}LVerify{step}", verify_img):
                    print("[WakeUp] 已稳定停在列车大厅。", flush=True)
                    return CustomAction.RunResult(success=True)
                unknown_streak = 0
                dismiss_streak = 0
                continue

            full_entries = ocr_roi(context, img, f"{prefix}Full{step}", [0, 0, 1280, 720])
            decision = choose_wake_up_action(
                full_entries,
                max_download_mb=max_download_mb,
                auto_confirm_small_update=auto_confirm_update,
                allow_blind_dismiss=allow_blind_dismiss,
                unknown_streak=unknown_streak,
                dismiss_attempt=dismiss_streak,
            )
            action = decision["action"]
            if action == "stop_auth":
                print("[WakeUp] 检测到账号登录/验证码/实名界面，已安全停止等待人工处理。", flush=True)
                return CustomAction.RunResult(success=False)
            if action == "stop_large_download":
                print(
                    f"[WakeUp] 资源更新包过大或未开启自动确认（{decision.get('size_mb')} MB），已停止。",
                    flush=True,
                )
                return CustomAction.RunResult(success=False)

            if action == "wait":
                dismiss_streak = 0
                if not is_game_screen_entries(full_entries):
                    unknown_streak += 1
                else:
                    unknown_streak = 0
                if unknown_streak >= 4 and return_to_lobby(
                    context,
                    f"{prefix}TryBack{step}",
                    max_steps=2,
                    dismiss_point=WAKEUP_POPUP_SAFE_POINT,
                ):
                    return CustomAction.RunResult(success=True)
                if not sleep_with_stop(context, 2.0):
                    return CustomAction.RunResult(success=False)
                continue

            unknown_streak = 0
            if action in ("dismiss_popup", "blind_dismiss", "dismiss_news"):
                dismiss_streak += 1
            else:
                dismiss_streak = 0
            point = decision.get("point")
            if point is not None:
                print(f"[WakeUp] 执行唤醒动作：{action} @ {point}", flush=True)
                if not tap_point(context, f"{prefix}Act{step}_{action}", point):
                    return CustomAction.RunResult(success=False)
                wait_sec = 4.0 if action == "confirm_download" else 2.0 if action == "tap_title" else 1.2
                if not sleep_with_stop(context, wait_sec):
                    return CustomAction.RunResult(success=False)

        print("[WakeUp] 超时未能确认到达列车大厅。", flush=True)
        return CustomAction.RunResult(success=False)

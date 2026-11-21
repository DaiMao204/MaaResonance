from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

try:
    from maa.controller import Controller, ControllerEventSink
except ImportError:  # pragma: no cover - lightweight test stubs without maa.controller
    Controller = Any  # type: ignore[assignment,misc]
    ControllerEventSink = None  # type: ignore[assignment,misc]

from agent.utils.action_helpers import parse_action_param
from agent.utils.input_guard import (
    record_controller_info,
    resolve_click_target_point,
    resolve_swipe_endpoints,
    run_guarded_click,
    run_guarded_swipe,
    wait_mouse_button_released,
)


def _parse_optional_int(raw: Any, *, min_value: int = 1, default: int | None = None) -> int | None:
    if raw is not None and not isinstance(raw, bool):
        try:
            parsed = int(raw)
            if parsed >= min_value:
                return parsed
        except (TypeError, ValueError):
            pass
    return default


@AgentServer.custom_action("guarded_click")
class GuardedClickAction(CustomAction):
    """Click action that delegates to the input bridge or protects Win32 background clicks."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = parse_action_param(getattr(argv, "custom_action_param", None))
        point = resolve_click_target_point(getattr(argv, "box", None), params)
        if point is None:
            return False

        duration_ms = _parse_optional_int(params.get("duration"), min_value=1, default=None)
        px, py = point
        tap_node = f"{argv.node_name}GuardedTap"
        return run_guarded_click(
            context,
            tap_node,
            px,
            py,
            duration_ms=duration_ms,
            wait_release=True,
            wait_release_fn=wait_mouse_button_released,
        )


@AgentServer.custom_action("guarded_swipe")
class GuardedSwipeAction(CustomAction):
    """Swipe action that protects Win32/ADB swipes by waiting for physical mouse release."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = parse_action_param(getattr(argv, "custom_action_param", None))
        endpoints = resolve_swipe_endpoints(params)
        if endpoints is None:
            return False

        start, end = endpoints
        duration_ms = _parse_optional_int(params.get("duration"), min_value=1, default=500) or 500
        end_hold_ms = _parse_optional_int(params.get("end_hold"), min_value=0, default=0)
        if end_hold_ms is None:
            end_hold_ms = 0

        swipe_node = f"{argv.node_name}GuardedSwipe"
        return run_guarded_swipe(
            context,
            swipe_node,
            start,
            end,
            duration_ms=duration_ms,
            end_hold_ms=end_hold_ms,
            wait_release=True,
            wait_release_fn=wait_mouse_button_released,
        )


if ControllerEventSink is not None and hasattr(AgentServer, "controller_sink"):
    if hasattr(AgentServer, "_set_api_properties"):
        AgentServer._set_api_properties()

    @AgentServer.controller_sink()
    class InputGuardControllerSink(ControllerEventSink):
        """Passively cache active controller metadata (type/mouse_method) without reverse IPC."""

        def on_controller_action(
            self,
            controller: Controller,
            noti_type: Any,
            detail: Any,
        ) -> None:
            _ = (controller, noti_type)
            record_controller_info(getattr(detail, "info", None))

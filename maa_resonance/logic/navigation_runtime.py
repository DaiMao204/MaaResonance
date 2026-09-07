"""Bounded page transitions that never click through loading or unknown pages."""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any


def _seconds(value: float, name: str, *, positive: bool = False) -> float:
    value = float(value)
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return value


def _point(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        if any(isinstance(v, (bool, str)) for v in value):
            return None
        numbers = tuple(float(v) for v in value)
        if not all(math.isfinite(v) and v >= 0 and v.is_integer() for v in numbers):
            return None
        return int(numbers[0]), int(numbers[1])
    except (TypeError, ValueError, OverflowError):
        return None


def run_navigation_transition(
    *,
    observe: Callable[[], dict[str, Any]],
    click: Callable[[tuple[int, int]], bool],
    should_stop: Callable[[], bool],
    timeout: float = 30.0,
    retry_interval: float = 2.0,
    poll_interval: float = 0.3,
    max_clicks: int = 3,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Observe fresh frames until the destination is ready or a bound is reached.

    ``observe`` owns screenshot acquisition and classification. Only its latest
    ``source`` result supplies an input point; ``loading`` and ``unknown`` never
    authorize input. ``click`` must wait for the input to complete and return its
    success. Retry spacing starts at completion, and the last click receives the
    same observation grace period before a visible source exhausts the budget.
    A synchronous callback already in progress cannot be interrupted, but its
    elapsed time is included in the deadline and no later input is sent.
    """
    timeout = _seconds(timeout, "timeout")
    retry_interval = _seconds(retry_interval, "retry_interval")
    poll_interval = _seconds(poll_interval, "poll_interval", positive=True)
    if isinstance(max_clicks, bool) or not isinstance(max_clicks, int) or max_clicks < 0:
        raise ValueError("max_clicks must be a nonnegative integer")
    started_at = clock()
    deadline = started_at + timeout
    last_click_completed_at: float | None = None
    result: dict[str, Any] = {
        "ok": False, "reason": "timeout", "clicks": 0, "click_attempts": 0,
        "observations": 0, "last_state": "unknown", "loading_observations": 0,
        "unknown_observations": 0,
    }

    def finish(reason: str, error: Exception | None = None) -> dict[str, Any]:
        result["ok"] = reason == "ready"
        result["reason"] = reason
        result["elapsed_ms"] = max(0.0, (clock() - started_at) * 1000)
        if error is not None:
            result["error"] = f"{type(error).__name__}: {error}"
        return result

    def interrupt() -> dict[str, Any] | None:
        try:
            if should_stop():
                return finish("stopped")
        except Exception as exc:
            return finish("stop_check_error", exc)
        if clock() >= deadline:
            return finish("timeout")
        return None

    while True:
        interrupted = interrupt()
        if interrupted is not None:
            return interrupted
        result["observations"] += 1
        try:
            observation = observe()
        except Exception as exc:
            return finish("observe_error", exc)
        interrupted = interrupt()
        if interrupted is not None:
            return interrupted
        if not isinstance(observation, dict):
            return finish("invalid_observation")
        state = observation.get("state")
        if state not in ("ready", "source", "loading", "unknown"):
            return finish("invalid_observation")
        result["last_state"] = state
        if state == "ready":
            return finish("ready")
        if state in ("loading", "unknown"):
            result[f"{state}_observations"] += 1
        elif last_click_completed_at is None or clock() - last_click_completed_at >= retry_interval:
            if result["click_attempts"] >= max_clicks:
                return finish("click_limit")
            point = _point(observation.get("point"))
            if point is None:
                return finish("invalid_source_point")
            # Recheck immediately before input, including when observe was slow.
            interrupted = interrupt()
            if interrupted is not None:
                return interrupted
            result["click_attempts"] += 1
            result["last_point"] = list(point)
            try:
                succeeded = click(point)
            except Exception as exc:
                return finish("click_error", exc)
            last_click_completed_at = clock()
            if not succeeded:
                return finish("click_failed")
            result["clicks"] += 1

        # A new observation is always acquired after waiting. Never reuse an old
        # source point once a sleep gives the game a chance to change pages.
        poll_deadline = min(deadline, clock() + poll_interval)
        while clock() < poll_deadline:
            interrupted = interrupt()
            if interrupted is not None:
                return interrupted
            remaining = poll_deadline - clock()
            if remaining > 0:
                sleep(min(0.1, remaining))

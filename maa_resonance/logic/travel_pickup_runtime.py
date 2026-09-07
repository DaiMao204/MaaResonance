"""Bounded right-side tapping bursts, guarded by fresh cruise-HUD checks.

Cargo recognition is deliberately absent: input targets never depend on an old
cargo position. Only the current travel state is recognized between bursts.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any


# Standard 1280x720 layout. The user confirms cargo only appears on the right.
# Keep every pickup press at the SAME interception point, including across HUD
# checks and windows. Camera rotation was still reported during multi-point
# tapping with an 80ms release gap. Use the user's marked rectangle center:
# (1181, 628) on the 1930x1086 screenshot maps to (783, 416) at 1280x720.
# Keep this exact point, without random jitter inside the rectangle.
# Keep the one-element sequence for compatibility with saved point indices;
# legacy multi-point cursors normalize to zero below.
PICKUP_TAP_POINTS = ((783, 416),)
MAX_PICKUP_FRAMES = 80
MAX_PICKUP_CLICKS = 128
MAX_BURST_CLICKS = 4


def _nonnegative_seconds(value: float, name: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return seconds


def _succeeded(job: Any) -> bool:
    succeeded = getattr(job, "succeeded", False)
    return bool(succeeded() if callable(succeeded) else succeeded)


def _image_size(image: Any) -> tuple[int, int] | None:
    shape = getattr(image, "shape", None)
    size = getattr(image, "size", None)
    try:
        if shape is not None and len(shape) >= 2:
            height, width = int(shape[0]), int(shape[1])
        elif isinstance(size, (list, tuple)) and len(size) == 2:
            width, height = (int(value) for value in size)
        else:
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def run_pickup_window(
    controller: Any,
    *,
    is_travel_hud: Callable[[Any], bool],
    should_stop: Callable[[], bool],
    on_click: Callable[[dict[str, Any]], None],
    start_index: int = 0,
    duration: float = 4.0,
    tap_interval: float = 0.08,
    hud_interval: float = 0.25,
    max_hud_age: float = 0.6,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Tap one stationary point; normally recheck after <=4 clicks or 250ms.

    No queued input backlog: each controller job is awaited before the next
    input. An in-flight job must finish before a stop or timeout can return.
    ``tap_count`` counts acknowledged inputs, never confirmed cargo rewards.
    ``tap_interval`` is the touch-free gap AFTER a completed click, not an
    interval between press starts. The first click also waits this long from
    window entry, so consecutive windows cannot bypass the release gap.
    Delayed HUD checks permit at most one tap when still fresh.
    A missed HUD pauses input and permits one immediate fresh-frame recheck;
    only two consecutive misses end the window as ``travel_hud_lost``.
    """
    duration = _nonnegative_seconds(duration, "duration")
    tap_interval = _nonnegative_seconds(tap_interval, "tap_interval")
    hud_interval = _nonnegative_seconds(hud_interval, "hud_interval")
    max_hud_age = _nonnegative_seconds(max_hud_age, "max_hud_age")
    cursor = int(start_index) % len(PICKUP_TAP_POINTS)
    started_at = clock()
    deadline = started_at + duration
    last_click_completed_at = started_at
    consecutive_hud_misses = 0
    result: dict[str, Any] = {
        "mode": "right_side_tapping", "reason": "duration_elapsed",
        "frames": 0, "tap_count": 0, "click_attempts": 0, "stale_frames": 0,
        "hud_misses": 0,
        "capture_ms": 0.0, "recognition_ms": 0.0, "click_ms": 0.0,
        "frame_limit": MAX_PICKUP_FRAMES, "click_limit": MAX_PICKUP_CLICKS,
        "next_point_index": cursor,
    }

    def finish(reason: str, error: Exception | None = None) -> dict[str, Any]:
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
            return finish("duration_elapsed")
        return None

    def release_failed_click() -> None:
        # A failed controller job may have sent down but not up. Only release
        # contact 0; never retry the press or move to a different coordinate.
        try:
            release = getattr(controller, "post_touch_up", None)
            result["cleanup_release_attempted"] = callable(release)
            result["cleanup_release_succeeded"] = bool(
                callable(release) and _succeeded(release(contact=0).wait())
            )
        except Exception as exc:
            result["cleanup_release_succeeded"] = False
            result["cleanup_release_error"] = f"{type(exc).__name__}: {exc}"

    for _ in range(MAX_PICKUP_FRAMES):
        interrupted = interrupt()
        if interrupted is not None:
            return interrupted
        if result["click_attempts"] >= MAX_PICKUP_CLICKS:
            return finish("click_limit")
        frame_started_at = clock()
        result["frames"] += 1
        try:
            capture_job = controller.post_screencap().wait()
            if not _succeeded(capture_job):
                return finish("screencap_failed")
            image = capture_job.get()
        except Exception as exc:
            return finish("screencap_error", exc)
        finally:
            result["capture_ms"] += max(0.0, (clock() - frame_started_at) * 1000)
        if image is None:
            return finish("no_image")
        if _image_size(image) != (1280, 720):
            return finish("invalid_image")
        interrupted = interrupt()
        if interrupted is not None:
            return interrupted
        recognition_started_at = clock()
        try:
            hud_ready = bool(is_travel_hud(image))
        except Exception as exc:
            return finish("recognition_error", exc)
        finally:
            result["recognition_ms"] += max(0.0, (clock() - recognition_started_at) * 1000)
        if clock() - frame_started_at > max_hud_age:
            result["stale_frames"] += 1
            return finish("stale_hud")
        interrupted = interrupt()
        if interrupted is not None:
            return interrupted
        if not hud_ready:
            result["hud_misses"] += 1
            consecutive_hud_misses += 1
            if consecutive_hud_misses >= 2:
                return finish("travel_hud_lost")
            # A single transient miss must not start several seconds of full
            # monitoring. Stop tapping now and confirm on a new screenshot;
            # no input is sent until that new frame passes the same HUD guard.
            continue
        consecutive_hud_misses = 0

        for burst_index in range(MAX_BURST_CLICKS):
            interrupted = interrupt()
            if interrupted is not None:
                return interrupted
            # If this frame will expire before the release gap is over, take
            # the next screenshot during that gap instead of sleeping first.
            next_tap_at = max(clock(), last_click_completed_at + tap_interval)
            next_frame_age = next_tap_at - frame_started_at
            if burst_index and (next_frame_age >= hud_interval or next_frame_age > max_hud_age):
                break
            delay = tap_interval - (clock() - last_click_completed_at)
            if delay > 0:
                sleep(min(delay, max(0.0, deadline - clock())))
            interrupted = interrupt()
            if interrupted is not None:
                return interrupted
            now = clock()
            frame_age = max(0.0, now - frame_started_at)
            if frame_age > max_hud_age:
                break
            if burst_index and frame_age >= hud_interval:
                break
            if result["click_attempts"] >= MAX_PICKUP_CLICKS:
                return finish("click_limit")
            point = PICKUP_TAP_POINTS[cursor]
            click_started_at = clock()
            result["click_attempts"] += 1
            try:
                click_job = controller.post_click(*point).wait()
                if not _succeeded(click_job):
                    release_failed_click()
                    return finish("click_failed")
            except Exception as exc:
                release_failed_click()
                return finish("click_error", exc)
            finally:
                last_click_completed_at = clock()
                click_duration = max(0.0, last_click_completed_at - click_started_at)
                result["click_ms"] += click_duration * 1000
            detail = {
                "mode": "right_side_tapping", "target": list(point),
                "point_index": cursor, "next_point_index": (cursor + 1) % len(PICKUP_TAP_POINTS),
                "frame_age_ms": frame_age * 1000, "click_duration_ms": click_duration * 1000,
                "min_release_gap_ms": tap_interval * 1000,
                "frame_index": result["frames"],
            }
            cursor = detail["next_point_index"]
            result["tap_count"] += 1
            result["next_point_index"] = cursor
            result["last_click"] = detail
            try:
                on_click(detail)
            except Exception as exc:
                return finish("on_click_error", exc)
    return finish("duration_elapsed" if clock() >= deadline else "frame_limit")

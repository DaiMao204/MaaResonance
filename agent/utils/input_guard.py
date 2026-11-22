from __future__ import annotations

from contextlib import contextmanager
import ctypes
import sys
import threading
import time
from typing import Any, Callable, Iterator

DEFAULT_DISPLAY_SHORT_SIDE = 720
_VK_LBUTTON = 0x01
_VK_RBUTTON = 0x02

# MaaWin32InputMethodEnum background cursor/window-pos methods:
# SendMessageWithCursorPos=32, PostMessageWithCursorPos=64,
# SendMessageWithWindowPos=128, PostMessageWithWindowPos=256.
WIN32_CURSOR_POS_MOUSE_METHODS = frozenset({32, 64})
WIN32_WINDOW_POS_MOUSE_METHODS = frozenset({128, 256})
WIN32_BG_MOUSE_METHODS = WIN32_CURSOR_POS_MOUSE_METHODS | WIN32_WINDOW_POS_MOUSE_METHODS

WIN32_BG_CLICK_DURATION_MS = 160
WIN32_CURSOR_PRE_HOVER_SEC = 0.045
WIN32_CURSOR_POST_UP_SETTLE_SEC = 0.075

_CONTROLLER_LOCK = threading.RLock()
_LAST_CONTROLLER_INFO: dict[str, Any] | None = None

if sys.platform == "win32":
    from ctypes import wintypes

    _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

    class _POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    _USER32 = ctypes.WinDLL("user32", use_last_error=True)
    _USER32.IsWindow.argtypes = [wintypes.HWND]
    _USER32.IsWindow.restype = wintypes.BOOL
    _USER32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _USER32.GetClientRect.restype = wintypes.BOOL
    _USER32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(_POINT)]
    _USER32.ClientToScreen.restype = wintypes.BOOL
    _USER32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
    _USER32.GetCursorPos.restype = wintypes.BOOL
    _USER32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    _USER32.SetCursorPos.restype = wintypes.BOOL
    if hasattr(_USER32, "SetThreadDpiAwarenessContext"):
        _USER32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        _USER32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p


def _round_coord(val: float) -> int:
    return int(val + 0.5) if val >= 0.0 else int(round(val))


def logical_point_to_client_point(
    px: int,
    py: int,
    client_w: int,
    client_h: int,
    *,
    short_side: int = DEFAULT_DISPLAY_SHORT_SIDE,
) -> tuple[int, int] | None:
    """Scale logical screenshot coordinates (e.g. 1280x720) to Win32 window client pixels."""
    if client_w <= 0 or client_h <= 0 or short_side <= 0:
        return None
    scale = float(client_w) / float(client_h)
    if client_w > client_h:
        target_w = _round_coord(float(short_side) * scale)
        target_h = int(short_side)
    else:
        target_w = int(short_side)
        target_h = _round_coord(float(short_side) / scale)
    if target_w <= 0 or target_h <= 0:
        return None
    cx = _round_coord(float(px) * (float(client_w) / float(target_w)))
    cy = _round_coord(float(py) * (float(client_h) / float(target_h)))
    cx = max(0, min(int(client_w) - 1, cx))
    cy = max(0, min(int(client_h) - 1, cy))
    return (cx, cy)


def parse_hwnd(raw: Any) -> int:
    """Parse an integer or decimal/hex string HWND into a positive int, or 0 if invalid."""
    if isinstance(raw, bool) or raw is None:
        return 0
    if isinstance(raw, int):
        return raw if raw > 0 else 0
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return 0
        try:
            value = int(text, 0)
            return value if value > 0 else 0
        except ValueError:
            return 0
    return 0


def is_physical_mouse_button_down() -> bool:
    """Return True when the user is holding the physical left or right mouse button on Windows."""
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        return bool(
            (user32.GetAsyncKeyState(_VK_LBUTTON) & 0x8000)
            or (user32.GetAsyncKeyState(_VK_RBUTTON) & 0x8000)
        )
    except Exception:
        return False


def record_controller_info(info: Any) -> None:
    """Cache the latest controller metadata emitted by MaaFramework events."""
    if not isinstance(info, dict):
        return
    with _CONTROLLER_LOCK:
        global _LAST_CONTROLLER_INFO
        _LAST_CONTROLLER_INFO = dict(info)


def clear_recorded_controller_info() -> None:
    """Clear cached controller metadata (primarily for deterministic unit tests)."""
    with _CONTROLLER_LOCK:
        global _LAST_CONTROLLER_INFO
        _LAST_CONTROLLER_INFO = None


def _win32_mouse_method(info: Any) -> int | None:
    if not isinstance(info, dict):
        return None
    if str(info.get("type") or "").strip().lower() != "win32":
        return None
    try:
        return int(info.get("mouse_method") or 0)
    except (TypeError, ValueError):
        return None


def get_effective_controller_info(context: Any) -> dict[str, Any] | None:
    """Return cached controller metadata from events, falling back to context.tasker.controller.info."""
    with _CONTROLLER_LOCK:
        cached = dict(_LAST_CONTROLLER_INFO) if _LAST_CONTROLLER_INFO is not None else None
    if cached is not None:
        return cached

    tasker = getattr(context, "tasker", None)
    controller = getattr(tasker, "controller", None)
    if controller is None:
        return None
    try:
        raw_info = getattr(controller, "info", None)
    except Exception:
        return None
    if isinstance(raw_info, dict):
        return dict(raw_info)
    return None


def is_win32_bg_controller_info(info: Any) -> bool:
    """Return True when info describes a Win32 controller using CursorPos or WindowPos background input."""
    method = _win32_mouse_method(info)
    return method is not None and method in WIN32_BG_MOUSE_METHODS


def is_win32_cursor_pos_controller_info(info: Any) -> bool:
    """Return True when info describes a Win32 controller using WithCursorPos background input."""
    method = _win32_mouse_method(info)
    return method is not None and method in WIN32_CURSOR_POS_MOUSE_METHODS


def _extract_rect(raw: Any) -> tuple[float, float, float, float] | None:
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        try:
            return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
        except (TypeError, ValueError):
            return None
    if isinstance(raw, dict) and all(k in raw for k in ("x", "y", "w", "h")):
        try:
            return (float(raw["x"]), float(raw["y"]), float(raw["w"]), float(raw["h"]))
        except (TypeError, ValueError):
            return None
    if all(hasattr(raw, attr) for attr in ("x", "y", "w", "h")):
        try:
            return (float(raw.x), float(raw.y), float(raw.w), float(raw.h))
        except (TypeError, ValueError):
            return None
    return None


def _parse_xy_or_rect(raw: Any) -> tuple[int, int] | None:
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            return (int(round(float(raw[0]))), int(round(float(raw[1]))))
        except (TypeError, ValueError):
            return None
    rect = _extract_rect(raw)
    if rect is not None:
        x, y, w, h = rect
        return (int(round(x + w / 2.0)), int(round(y + h / 2.0)))
    return None


def resolve_click_target_point(
    box: Any,
    param: dict[str, Any] | None = None,
) -> tuple[int, int] | None:
    """Resolve click target center from custom_action_param target/offset or recognized box."""
    cfg = param if isinstance(param, dict) else {}
    base = _parse_xy_or_rect(cfg.get("target"))
    if base is None:
        rect = _extract_rect(box)
        if rect is not None:
            bx, by, bw, bh = rect
            if bw > 0 or bh > 0 or bx > 0 or by > 0:
                base = (int(round(bx + bw / 2.0)), int(round(by + bh / 2.0)))
    if base is None:
        return None

    offset = _parse_xy_or_rect(cfg.get("target_offset"))
    if offset is not None:
        return (base[0] + offset[0], base[1] + offset[1])
    return base


def resolve_swipe_endpoints(
    param: dict[str, Any] | None,
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """Resolve begin/end points from custom_action_param swipe settings."""
    cfg = param if isinstance(param, dict) else {}
    begin = _parse_xy_or_rect(cfg.get("begin"))
    end = _parse_xy_or_rect(cfg.get("end"))
    if begin is None or end is None:
        return None

    begin_offset = _parse_xy_or_rect(cfg.get("begin_offset"))
    if begin_offset is not None:
        begin = (begin[0] + begin_offset[0], begin[1] + begin_offset[1])

    end_offset = _parse_xy_or_rect(cfg.get("end_offset"))
    if end_offset is not None:
        end = (end[0] + end_offset[0], end[1] + end_offset[1])

    return (begin, end)


def _is_stopping(context: Any) -> bool:
    tasker = getattr(context, "tasker", None)
    return getattr(tasker, "stopping", False) is True


def wait_mouse_button_released(
    context: Any,
    *,
    max_wait_sec: float = 1.2,
    poll_sec: float = 0.03,
    is_button_down: Callable[[], bool] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Wait briefly if the physical mouse button is held down; return False if task is stopping."""
    if _is_stopping(context):
        return False

    probe = is_button_down or is_physical_mouse_button_down
    if not probe():
        return True

    deadline = clock() + max(0.0, float(max_wait_sec))
    interval = max(0.005, float(poll_sec))
    while probe():
        if _is_stopping(context):
            return False
        if clock() >= deadline:
            return True
        sleep(interval)

    return not _is_stopping(context)


def sleep_with_stop(
    context: Any,
    seconds: float,
    *,
    step: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Sleep in small chunks, returning False promptly if the task starts stopping."""
    remaining = max(0.0, float(seconds))
    chunk_size = max(0.01, float(step))
    while remaining > 0.0:
        if _is_stopping(context):
            return False
        chunk = min(remaining, chunk_size)
        sleep(chunk)
        remaining -= chunk
    return not _is_stopping(context)


@contextmanager
def pin_cursor_for_win32_click(
    context: Any,
    info: dict[str, Any] | None,
    px: int,
    py: int,
    *,
    pre_hover_sec: float = WIN32_CURSOR_PRE_HOVER_SEC,
    post_up_settle_sec: float = WIN32_CURSOR_POST_UP_SETTLE_SEC,
    short_side: int = DEFAULT_DISPLAY_SHORT_SIDE,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[bool]:
    """Keep the physical cursor pinned over the target button across a Win32 WithCursorPos click."""
    if sys.platform != "win32" or not is_win32_cursor_pos_controller_info(info):
        yield False
        return

    hwnd = parse_hwnd((info or {}).get("hwnd"))
    if hwnd <= 0:
        yield False
        return

    set_dpi_ctx = getattr(_USER32, "SetThreadDpiAwarenessContext", None)
    prev_dpi_ctx: Any = None
    try:
        if set_dpi_ctx is not None:
            try:
                prev_dpi_ctx = set_dpi_ctx(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
            except Exception:
                prev_dpi_ctx = None

        rect = wintypes.RECT()
        orig_pt = _POINT()
        screen_pt = _POINT()
        moved = False
        try:
            if _USER32.IsWindow(hwnd) and _USER32.GetClientRect(hwnd, ctypes.byref(rect)):
                client_w = int(rect.right - rect.left)
                client_h = int(rect.bottom - rect.top)
                client_pt = logical_point_to_client_point(px, py, client_w, client_h, short_side=short_side)
                if client_pt is not None:
                    screen_pt.x, screen_pt.y = int(client_pt[0]), int(client_pt[1])
                    if (
                        _USER32.ClientToScreen(hwnd, ctypes.byref(screen_pt))
                        and _USER32.GetCursorPos(ctypes.byref(orig_pt))
                        and _USER32.SetCursorPos(screen_pt.x, screen_pt.y)
                    ):
                        moved = True
        except Exception:
            moved = False

        if not moved:
            yield False
            return

        try:
            if pre_hover_sec > 0 and not sleep_with_stop(context, pre_hover_sec, step=0.015, sleep=sleep):
                yield False
                return
            yield True
            if not _is_stopping(context) and post_up_settle_sec > 0:
                sleep_with_stop(context, post_up_settle_sec, step=0.02, sleep=sleep)
        finally:
            try:
                _USER32.SetCursorPos(orig_pt.x, orig_pt.y)
            except Exception:
                pass
    finally:
        if prev_dpi_ctx is not None and set_dpi_ctx is not None:
            try:
                restore_arg = ctypes.c_void_p(prev_dpi_ctx) if isinstance(prev_dpi_ctx, int) else prev_dpi_ctx
                set_dpi_ctx(restore_arg)
            except Exception:
                pass


def run_guarded_click(
    context: Any,
    tap_node: str,
    px: int,
    py: int,
    *,
    duration_ms: int | None = None,
    pre_hover_sec: float = WIN32_CURSOR_PRE_HOVER_SEC,
    post_up_settle_sec: float = WIN32_CURSOR_POST_UP_SETTLE_SEC,
    wait_release: bool = True,
    max_wait_sec: float = 1.2,
    wait_release_fn: Callable[..., bool] | None = None,
) -> bool:
    """Execute a click with Win32 background duration/cursor-pin protection and release waiting."""
    if _is_stopping(context):
        return False

    px_i, py_i = int(px), int(py)
    info = get_effective_controller_info(context)

    release_probe = wait_release_fn or wait_mouse_button_released
    if wait_release and not release_probe(context, max_wait_sec=max_wait_sec):
        return False
    if _is_stopping(context):
        return False

    is_win32_bg = is_win32_bg_controller_info(info)

    use_duration = 0
    if duration_ms is not None and int(duration_ms) > 0:
        use_duration = int(duration_ms)
    elif duration_ms is None and is_win32_bg:
        use_duration = WIN32_BG_CLICK_DURATION_MS

    if use_duration > 0:
        node_cfg: dict[str, Any] = {
            "action": "LongPress",
            "target": [px_i, py_i, 1, 1],
            "duration": use_duration,
            "pre_delay": 0,
            "post_delay": 0,
        }
    else:
        node_cfg = {
            "action": "Click",
            "target": [px_i, py_i, 1, 1],
            "pre_delay": 0,
            "post_delay": 0,
        }

    acted = False
    with pin_cursor_for_win32_click(
        context,
        info,
        px_i,
        py_i,
        pre_hover_sec=pre_hover_sec,
        post_up_settle_sec=post_up_settle_sec,
    ):
        if not _is_stopping(context):
            context.run_action(
                tap_node,
                (px_i, py_i, 1, 1),
                "",
                {tap_node: node_cfg},
            )
            acted = True
    return acted


def run_controller_click_guarded(
    context: Any,
    px: int,
    py: int,
    *,
    tap_node: str = "ControllerGuardedTap",
    max_wait_sec: float = 1.2,
    wait_release: bool = True,
) -> bool:
    """Click via guarded Win32 background helper or controller.post_click."""
    if _is_stopping(context):
        return False

    px_i, py_i = int(px), int(py)
    info = get_effective_controller_info(context)

    if (
        is_win32_bg_controller_info(info)
        and callable(getattr(context, "run_action", None))
    ):
        return run_guarded_click(
            context,
            tap_node,
            px_i,
            py_i,
            wait_release=wait_release,
            max_wait_sec=max_wait_sec,
        )

    if wait_release and not wait_mouse_button_released(context, max_wait_sec=max_wait_sec):
        return False
    if _is_stopping(context):
        return False
    tasker = getattr(context, "tasker", None)
    controller = getattr(tasker, "controller", None)
    if controller is None:
        return False
    job = controller.post_click(px_i, py_i).wait()
    return bool(getattr(job, "succeeded", True))


def run_guarded_swipe(
    context: Any,
    swipe_node: str,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    duration_ms: int = 500,
    end_hold_ms: int = 120,
    wait_release: bool = True,
    max_wait_sec: float = 1.2,
    use_controller_post_swipe: bool = False,
    wait_release_fn: Callable[..., bool] | None = None,
) -> bool:
    """Execute a swipe/drag after waiting for physical mouse release."""
    if _is_stopping(context):
        return False

    x1, y1 = int(start[0]), int(start[1])
    x2, y2 = int(end[0]), int(end[1])
    dur_ms = max(0, int(duration_ms))
    hold_ms = max(0, int(end_hold_ms))

    release_probe = wait_release_fn or wait_mouse_button_released
    if wait_release and not release_probe(context, max_wait_sec=max_wait_sec):
        return False
    if _is_stopping(context):
        return False

    if use_controller_post_swipe or not callable(getattr(context, "run_action", None)):
        tasker = getattr(context, "tasker", None)
        controller = getattr(tasker, "controller", None)
        if controller is None:
            return False
        job = controller.post_swipe(x1, y1, x2, y2, dur_ms).wait()
        return bool(getattr(job, "succeeded", True))

    context.run_action(
        swipe_node,
        (0, 0, 0, 0),
        "",
        {
            swipe_node: {
                "action": "Swipe",
                "begin": [x1, y1, 1, 1],
                "end": [x2, y2, 1, 1],
                "duration": dur_ms,
                "end_hold": hold_ms,
                "pre_delay": 0,
                "post_delay": 0,
            }
        },
    )
    return True


def safe_screencap(context: Any) -> Any | None:
    """Capture a frame safely without crashing if the task stops or controller disconnects."""
    if _is_stopping(context):
        return None
    tasker = getattr(context, "tasker", None)
    controller = getattr(tasker, "controller", None)
    if controller is None:
        return None
    try:
        job = controller.post_screencap().wait()
        if _is_stopping(context):
            return None
        if not getattr(job, "succeeded", True):
            return None
        return getattr(controller, "cached_image", None)
    except (OSError, RuntimeError, AttributeError):
        return None

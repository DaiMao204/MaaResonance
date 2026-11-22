from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Callable, Sequence

from maa.context import Context

from agent.utils.input_guard import (
    run_guarded_click,
    run_guarded_swipe,
    safe_screencap,
    sleep_with_stop,
    wait_mouse_button_released,
)
from agent.utils.recognition import _ocr_entries


def parse_action_param(raw: Any) -> dict[str, Any]:
    """Parse a CustomAction / CustomRecognition param dict or JSON string."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def resolve_attached_params(
    context: Context,
    argv: Any,
    suffixes: Sequence[str],
    *,
    param_attr: str = "custom_action_param",
) -> dict[str, Any]:
    """Merge node custom params with optional sibling ``<node_name><suffix>`` ``attach`` dicts."""
    merged = dict(parse_action_param(getattr(argv, param_attr, None)))
    node_name = str(getattr(argv, "node_name", "") or "").strip()
    get_node_data = getattr(context, "get_node_data", None)
    if not node_name or not callable(get_node_data):
        return merged

    for suffix in suffixes:
        try:
            node_data = get_node_data(f"{node_name}{suffix}")
        except Exception:
            node_data = None
        if isinstance(node_data, dict):
            attach = node_data.get("attach")
            if isinstance(attach, dict):
                merged.update(attach)
    return merged


def ocr_roi(
    context: Context,
    image: Any,
    node_name: str,
    roi: Sequence[int],
) -> list[dict[str, Any]]:
    """Run OCR on the specified ROI and return normalized entries."""
    detail = context.run_recognition(
        node_name,
        image,
        {
            node_name: {
                "recognition": "OCR",
                "roi": [int(v) for v in roi],
                "action": "DoNothing",
            }
        },
    )
    return _ocr_entries(SimpleNamespace(reco_detail=detail))


def tap_point(
    context: Context,
    node_name: str,
    point: tuple[int, int],
    *,
    max_wait_sec: float = 1.2,
    duration_ms: int | None = None,
    wait_release: bool = True,
) -> bool:
    """Tap a logical point via guarded Win32/ADB click protection."""
    px, py = int(point[0]), int(point[1])
    return run_guarded_click(
        context,
        f"{node_name}Tap",
        px,
        py,
        duration_ms=duration_ms,
        wait_release=wait_release,
        max_wait_sec=max_wait_sec,
    )


def swipe_points(
    context: Context,
    node_name: str,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    duration: int = 500,
    end_hold: int = 120,
    max_wait_sec: float = 1.2,
    node_suffix: str = "Swipe",
    wait_release: bool = True,
) -> bool:
    """Swipe between logical points via guarded swipe helper."""
    return run_guarded_swipe(
        context,
        f"{node_name}{node_suffix}",
        start,
        end,
        duration_ms=duration,
        end_hold_ms=end_hold,
        wait_release=wait_release,
        max_wait_sec=max_wait_sec,
    )


def poll_screen(
    context: Context,
    check_fn: Callable[[Any, int], Any],
    *,
    initial_delay: float = 1.0,
    interval: float = 0.5,
    max_checks: int = 5,
    screencap_fn: Callable[[Context], Any] = safe_screencap,
    sleep_fn: Callable[[Context, float], bool] = sleep_with_stop,
) -> tuple[Any | None, Any, bool]:
    """Wait ``initial_delay`` then poll ``check_fn(img, attempt)`` up to ``max_checks`` times.

    Returns ``(image, result, aborted)`` where ``aborted=True`` indicates stop requested or
    ``screencap_fn`` returned ``None``; truthy ``result`` indicates a match on that frame;
    falsy ``result`` with ``aborted=False`` indicates all checks completed without matching.
    """
    if initial_delay > 0 and not sleep_fn(context, initial_delay):
        return None, None, True
    last_img: Any = None
    checks = max(1, int(max_checks))
    for attempt in range(checks):
        img = screencap_fn(context)
        if img is None:
            return None, None, True
        last_img = img
        result = check_fn(img, attempt)
        if result:
            return img, result, False
        if attempt + 1 < checks and interval > 0:
            if not sleep_fn(context, interval):
                return None, None, True
    return last_img, None, False

"""Pure logic and pixel/OCR helpers for Activity Hub (活动中心左栏导航)."""
from __future__ import annotations

import re
from typing import Any

import numpy as np

LOBBY_ACTIVITY_ICON_POINT: tuple[int, int] = (797, 48)
ACTIVITY_HUB_SIDEBAR_ROI: tuple[int, int, int, int] = (10, 65, 250, 640)
ACTIVITY_HUB_SCROLL_SWIPE: tuple[int, int, int, int] = (110, 460, 110, 210)
ACTIVITY_CATEGORIES: tuple[str, ...] = ("限时活动", "常规活动", "剧情活动", "经营活动")


def _clean(text: Any) -> str:
    return re.sub(r"[\s▼▲►◄▶◀!！·•]+", "", str(text or "")).strip()


def _entry_box(entry: dict[str, Any]) -> tuple[int, int, int, int] | None:
    if not isinstance(entry, dict):
        return None
    box = entry.get("box")
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        try:
            return int(box[0]), int(box[1]), int(box[2]), int(box[3])
        except (TypeError, ValueError):
            return None
    if all(k in entry for k in ("x", "y", "w", "h")):
        try:
            return int(entry["x"]), int(entry["y"]), int(entry["w"]), int(entry["h"])
        except (TypeError, ValueError):
            return None
    return None


def _entry_center(entry: dict[str, Any]) -> tuple[int, int] | None:
    if isinstance(entry, dict) and "center_x" in entry and "center_y" in entry:
        try:
            return int(round(float(entry["center_x"]))), int(round(float(entry["center_y"])))
        except (TypeError, ValueError):
            pass
    box = _entry_box(entry)
    if box is None:
        return None
    x, y, w, h = box
    return int(round(x + w / 2.0)), int(round(y + h / 2.0))


def is_activity_hub_entries(sidebar_entries: list[dict[str, Any]]) -> bool:
    """Return True when the left accordion sidebar of Activity Hub is visible."""
    cleaned_texts = [_clean(e.get("text")) for e in sidebar_entries if isinstance(e, dict)]
    cat_hits = sum(1 for cat in ACTIVITY_CATEGORIES if any(cat in t for t in cleaned_texts))
    return cat_hits >= 2


def find_activity_category_point(
    sidebar_entries: list[dict[str, Any]],
    category: str,
) -> tuple[int, int] | None:
    """Locate the tap center for an Activity Hub accordion category."""
    target = _clean(category)
    for entry in sidebar_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text"))
        if target and target in cleaned:
            center = _entry_center(entry)
            if center is not None:
                return (130, center[1])
    return None


def is_category_expanded(sidebar_entries: list[dict[str, Any]], category: str) -> bool:
    """Return True when the given category accordion header appears expanded."""
    target = _clean(category)
    cat_y: int | None = None
    next_cat_y: int | None = None
    other_cats = {_clean(c) for c in ACTIVITY_CATEGORIES if _clean(c) != target}

    for entry in sidebar_entries:
        if not isinstance(entry, dict):
            continue
        raw_text = str(entry.get("text") or "")
        cleaned = _clean(raw_text)
        center = _entry_center(entry)
        if center is None:
            continue
        if target and target in cleaned:
            if "▼" in raw_text:
                return True
            cat_y = center[1]
        elif any(oc in cleaned for oc in other_cats):
            if cat_y is not None and center[1] > cat_y and (next_cat_y is None or center[1] < next_cat_y):
                next_cat_y = center[1]

    if cat_y is None:
        return False
    for entry in sidebar_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text"))
        if len(cleaned) < 2 or any(_clean(c) in cleaned for c in ACTIVITY_CATEGORIES):
            continue
        center = _entry_center(entry)
        if center is None:
            continue
        if center[0] <= 210 and center[1] > cat_y + 20 and (next_cat_y is None or center[1] < next_cat_y):
            return True
    return False


def find_activity_card(
    sidebar_entries: list[dict[str, Any]],
    keywords: tuple[str, ...],
) -> dict[str, Any] | None:
    """Find a sidebar activity card matching any keyword (excluding category headers)."""
    clean_kws = [_clean(kw) for kw in keywords if _clean(kw)]
    if not clean_kws:
        return None
    category_set = {_clean(c) for c in ACTIVITY_CATEGORIES}

    for entry in sidebar_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text"))
        if not cleaned or any(cat in cleaned for cat in category_set):
            continue
        center = _entry_center(entry)
        if center is None or center[0] > 220:
            continue
        if any(kw in cleaned for kw in clean_kws):
            label_cy = center[1]
            tap_y = max(120, min(680, label_cy - 18))
            return {
                "text": str(entry.get("text") or "").strip(),
                "label_cy": label_cy,
                "tap_point": (108, tap_y),
            }
    return None


def has_activity_card_red_dot(image: Any, label_cy: int) -> bool:
    """Return True when the red notification dot is present on the top-right corner of a card."""
    if not isinstance(image, np.ndarray) or image.ndim < 2 or image.shape[0] <= 0 or image.shape[1] <= 0:
        return False
    h, w = image.shape[:2]
    sx = w / 1280.0
    sy = h / 720.0
    y1 = max(95, int(label_cy) - 68)
    y2 = max(y1 + 10, int(label_cy) - 26)
    ix1 = max(0, min(w - 1, int(round(180 * sx))))
    ix2 = max(ix1 + 1, min(w, int(round(212 * sx))))
    iy1 = max(0, min(h - 1, int(round(y1 * sy))))
    iy2 = max(iy1 + 1, min(h, int(round(y2 * sy))))
    patch = image[iy1:iy2, ix1:ix2]
    if patch.size == 0:
        return False
    b = patch[:, :, 0].astype(np.float32)
    g = patch[:, :, 1].astype(np.float32)
    r = patch[:, :, 2].astype(np.float32)
    red_ratio = float(np.mean((r > 170) & (r - g > 70) & (r - b > 70)))
    return red_ratio >= 0.08

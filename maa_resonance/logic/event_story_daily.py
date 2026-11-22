"""Pure logic and OCR helpers for Event Story Daily (限时剧情活动 · 糖霜记忆)."""
from __future__ import annotations

import re
from typing import Any

FROSTING_ENTER_ROI: tuple[int, int, int, int] = (840, 480, 360, 160)
FROSTING_ENTER_FALLBACK: tuple[int, int] = (1000, 560)
FROSTING_HEADER_ROI: tuple[int, int, int, int] = (760, 20, 460, 95)
FROSTING_CARDS_ROI: tuple[int, int, int, int] = (60, 540, 1200, 80)
FROSTING_DRAWER_INFO_ROI: tuple[int, int, int, int] = (840, 160, 380, 380)
FROSTING_DRAWER_BTN_ROI: tuple[int, int, int, int] = (940, 550, 280, 100)
FROSTING_DRAWER_BTN_FALLBACK: tuple[int, int] = (1080, 594)


def _clean(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


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


def is_frosting_home_entries(entries: list[dict[str, Any]]) -> bool:
    """Return True when the Frosting Memory activity home screen is visible."""
    texts = [_clean(e.get("text")).upper() for e in entries if isinstance(e, dict)]
    return any("前往取景" in t or "VIEWFINDER" in t for t in texts)


def find_frosting_enter_point(entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Locate the '前往取景' button on the Frosting Memory home screen."""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text")).upper()
        if "前往取景" in cleaned or "VIEWFINDER" in cleaned:
            center = _entry_center(entry)
            if center is not None:
                return center
    return None


def is_frosting_cards_screen_entries(
    header_entries: list[dict[str, Any]],
    card_entries: list[dict[str, Any]],
) -> bool:
    """Return True when the 6-card Viewfinder progress screen is visible."""
    header_texts = [_clean(e.get("text")) for e in header_entries if isinstance(e, dict)]
    if any("取景进度" in t for t in header_texts):
        return True
    card_texts = [_clean(e.get("text")) for e in card_entries if isinstance(e, dict)]
    return any(kw in t for t in card_texts for kw in ("取景完成", "开始取景", "明日登录解锁"))


def is_frosting_drawer_open(
    info_entries: list[dict[str, Any]],
    btn_entries: list[dict[str, Any]],
) -> bool:
    """Return True when the right-hand Viewfinder stage detail drawer is open."""
    info_texts = [_clean(e.get("text")) for e in info_entries if isinstance(e, dict)]
    has_info = any("敌人等级" in t or "奖励预览" in t for t in info_texts)
    return has_info and (find_frosting_drawer_start_point(btn_entries) is not None)


def find_frosting_drawer_start_point(drawer_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Locate the '开始取景' / 'VIEWFINDER' button inside the right-hand drawer."""
    for entry in drawer_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text")).upper()
        if "开始取景" in cleaned or "VIEWFINDER" in cleaned:
            center = _entry_center(entry)
            if center is not None:
                return center
    return None


def find_frosting_start_card_point(card_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Locate an available '开始取景' card on the Viewfinder card strip."""
    for entry in card_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text"))
        if not cleaned:
            continue
        if any(bad in cleaned for bad in ("取景完成", "明日登录", "解锁")):
            continue
        if "开始取景" in cleaned:
            center = _entry_center(entry)
            if center is not None:
                return center
    return None

"""Pure logic and pixel/OCR helpers for Event Stage Farming (活动/通用连战刷关)."""
from __future__ import annotations

import re
from typing import Any

import numpy as np

MINISCAPE_BREAK_BTN_ROI: tuple[int, int, int, int] = (1060, 560, 200, 110)
MINISCAPE_BREAK_BTN_FALLBACK: tuple[int, int] = (1157, 625)

STAGE_LIST_SWIPE_LEFT: tuple[int, int, int, int] = (1050, 400, 200, 400)
STAGE_LIST_SWIPE_RIGHT: tuple[int, int, int, int] = (200, 400, 1050, 400)

STAGE_DETAIL_TITLE_ROI: tuple[int, int, int, int] = (800, 85, 360, 80)
STAGE_DETAIL_CLARITY_ROI: tuple[int, int, int, int] = (1020, 15, 220, 50)
STAGE_ENTER_BTN_ROI: tuple[int, int, int, int] = (860, 535, 370, 80)
STAGE_ENTER_BTN_FALLBACK: tuple[int, int] = (1055, 573)
STAGE_AUTO_TOGGLE_POINT: tuple[int, int] = (1098, 666)
STAGE_AUTO_TEXT_ROI: tuple[int, int, int, int] = (930, 640, 240, 75)

LOW_CLARITY_PROMPT_ROI: tuple[int, int, int, int] = (300, 280, 680, 140)
LOW_CLARITY_CANCEL_POINT: tuple[int, int] = (349, 505)
LOW_CLARITY_CONFIRM_POINT: tuple[int, int] = (986, 504)

_DIGIT_CONFUSIONS = str.maketrans({
    "O": "0",
    "o": "0",
    "I": "1",
    "l": "1",
    "|": "1",
})


def _clean(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def _normalize_stage_label(text: Any) -> str:
    cleaned = _clean(text)
    # Strip leading zeros before numbers so '07' and '调查报告7' align uniformly.
    return re.sub(r"0+(\d+)", r"\1", cleaned)


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


def find_miniscape_break_button(entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Locate '破坏箱庭' button on the Inside the Miniscape activity home screen."""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text")).upper()
        if "破坏箱庭" in cleaned or "BREAKTHEMINISCAPE" in cleaned:
            center = _entry_center(entry)
            if center is not None:
                return center
    return None


def find_stage_card_point(
    entries: list[dict[str, Any]],
    target_stage_name: str,
) -> tuple[int, int] | None:
    """Locate a stage card on the horizontal stage map (ignoring right detail title header)."""
    target_norm = _normalize_stage_label(target_stage_name)
    if not target_norm:
        return None
    num_match = re.search(r"\d+", target_norm)
    target_num = num_match.group(0) if num_match else ""

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        center = _entry_center(entry)
        if center is None:
            continue
        cx, cy = center
        # Ignore open right-hand detail panel header at top-right.
        if cx >= 780 and cy < 220:
            continue
        norm = _normalize_stage_label(entry.get("text"))
        if target_norm in norm:
            return cx, max(200, cy - 55)

    if target_num:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            center = _entry_center(entry)
            if center is None:
                continue
            cx, cy = center
            if cx >= 780 and cy < 220:
                continue
            norm = _normalize_stage_label(entry.get("text"))
            if norm == target_num and 220 <= cy <= 460:
                return cx, cy
    return None


def has_stage_detail_overlay_entries(entries: list[dict[str, Any]]) -> bool:
    """Return True when the right-side stage detail panel is overlaid on screen."""
    texts = [_clean(e.get("text")) for e in entries if isinstance(e, dict)]
    markers = ("破坏箱庭", "难度推荐", "奖励预览", "自动战斗", "秒后开始", "开始作战")
    return any(m in t for t in texts for m in markers)


def is_stage_battle_or_loading_entries(entries: list[dict[str, Any]]) -> bool:
    """Return True when OCR captures a battle HUD, battle alert, settlement, or loading screen."""
    texts_upper = [_clean(e.get("text")).upper() for e in entries if isinstance(e, dict)]
    markers = (
        "LOAD",
        "LOADING",
        "正在加载",
        "正在检测",
        "弃牌",
        "即时伤害",
        "COST不足",
        "敌方详情",
        "退出战斗",
        "紧急警告",
        "避险协议",
        "作战胜利",
        "作战失败",
        "挑战失败",
    )
    if any(m in t for t in texts_upper for m in markers):
        return True
    if any(t == "MAX" for t in texts_upper):
        return True
    has_list_context = any("破坏进度" in t or "调查报告" in t for t in texts_upper)
    if not has_list_context and any(re.fullmatch(r"\d{1,3}%", t) for t in texts_upper):
        return True
    return False


def is_stage_list_screen_entries(entries: list[dict[str, Any]]) -> bool:
    """Return True when the Break the Miniscape stage card carousel is clearly visible without overlays."""
    if is_stage_battle_or_loading_entries(entries) or has_stage_detail_overlay_entries(entries):
        return False
    texts = [_clean(e.get("text")) for e in entries if isinstance(e, dict)]
    return any("调查报告" in t for t in texts)


def find_stage_enter_button_point(enter_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Locate the stage detail entry button ('破坏箱庭' / '开始作战' / '前往作战' / '挑战')."""
    for entry in enter_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text"))
        if any(kw in cleaned for kw in ("破坏箱庭", "开始作战", "前往作战", "进入挑战", "挑战")):
            center = _entry_center(entry)
            if center is not None:
                return center
    return None


def is_stage_detail_open(
    detail_title_entries: list[dict[str, Any]],
    enter_entries: list[dict[str, Any]],
    target_stage_name: str = "",
) -> bool:
    """Return True when the right-side stage detail panel is open (and matches target if given)."""
    if find_stage_enter_button_point(enter_entries) is None:
        return False
    target_norm = _normalize_stage_label(target_stage_name)
    if not target_norm:
        return bool(detail_title_entries)
    title_norms = [_normalize_stage_label(e.get("text")) for e in detail_title_entries if isinstance(e, dict)]
    return any(target_norm in t for t in title_norms if t)


def parse_stage_clarity(clarity_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Parse stage clarity indicator such as '292/292+' or '14/292+'."""
    for entry in clarity_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text")).translate(_DIGIT_CONFUSIONS)
        match = re.search(r"(\d+)\s*/\s*(\d+)", cleaned)
        if not match:
            continue
        cur = int(match.group(1))
        cap = int(match.group(2))
        if cap > 0 and cur >= 0:
            return cur, cap
    return None


def has_auto_repeat_toggle_label(auto_text_entries: list[dict[str, Any]]) -> bool:
    """Return True when the native '自动战斗' toggle label is visible on the detail panel."""
    texts = [_clean(e.get("text")) for e in auto_text_entries if isinstance(e, dict)]
    return any("自动战斗" in t or "秒后开始" in t for t in texts)


def is_stage_auto_repeat_on(
    image: Any,
    auto_text_entries: list[dict[str, Any]] | None = None,
) -> bool:
    """Return True when the stage detail '自动战斗' capsule switch is toggled ON (right/white knob)."""
    if auto_text_entries:
        texts = [_clean(e.get("text")) for e in auto_text_entries if isinstance(e, dict)]
        if any("秒后开始" in t for t in texts):
            return True
    if not isinstance(image, np.ndarray) or image.ndim < 2 or image.shape[0] <= 0 or image.shape[1] <= 0:
        return False
    h, w = image.shape[:2]
    sx = w / 1280.0
    sy = h / 720.0
    ix1 = max(0, min(w - 1, int(round(1106 * sx))))
    ix2 = max(ix1 + 1, min(w, int(round(1134 * sx))))
    iy1 = max(0, min(h - 1, int(round(652 * sy))))
    iy2 = max(iy1 + 1, min(h, int(round(678 * sy))))
    patch = image[iy1:iy2, ix1:ix2].astype(np.float32)
    if patch.size == 0:
        return False
    b, g, r = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
    white_ratio = float(np.mean((r > 220) & (g > 220) & (b > 220)))
    bright = float(np.mean((r + g + b) / 3.0))
    return white_ratio >= 0.25 and bright >= 130.0


def is_low_clarity_confirm_popup(entries: list[dict[str, Any]]) -> bool:
    """Return True when '您当前的澄明度不足，是否补充澄明度？' modal is visible."""
    texts = [_clean(e.get("text")) for e in entries if isinstance(e, dict)]
    return any("澄明度不足" in t or "是否补充澄明度" in t for t in texts)


def parse_run_count_limit(raw: Any) -> int:
    """Parse run count config into int (<= 0 means unlimited until clarity exhausted)."""
    try:
        val = int(str(raw).strip())
        return val if val > 0 else 0
    except (TypeError, ValueError):
        return 0

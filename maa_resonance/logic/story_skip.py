from __future__ import annotations

from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None


STORY_HUD_KEYWORDS = ("回顾", "隐藏", "自动", "跳过")
STORY_DEFAULT_SKIP_POINT = (1190, 36)
STORY_TOP_Y_MAX = 100

CHOICE_X1 = 357
CHOICE_X2 = 922
CHOICE_Y1 = 150
CHOICE_Y2 = 560
CHOICE_CENTER_X = 640
CHOICE_MIN_HEIGHT = 40
CHOICE_MAX_HEIGHT = 95


def _entry_text(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("text") or "").strip()
    return str(getattr(entry, "text", "") or "").strip()


def _entry_box(entry: Any) -> tuple[int, int, int, int]:
    if isinstance(entry, dict):
        box = entry.get("box")
        if isinstance(box, (list, tuple)) and len(box) >= 4:
            return int(box[0]), int(box[1]), int(box[2]), int(box[3])
        return (
            int(entry.get("x", 0) or 0),
            int(entry.get("y", 0) or 0),
            int(entry.get("w", 0) or 0),
            int(entry.get("h", 0) or 0),
        )
    box = getattr(entry, "box", None)
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        return int(box[0]), int(box[1]), int(box[2]), int(box[3])
    return (0, 0, 0, 0)


def _entry_center(entry: Any) -> tuple[int, int]:
    x, y, w, h = _entry_box(entry)
    return int(round(x + w / 2.0)), int(round(y + h / 2.0))


def has_story_hud(top_entries: list[dict[str, Any]]) -> bool:
    """Return True when top HUD entries indicate an active story dialogue screen."""
    hits: set[str] = set()
    skip_top_hit = False
    for entry in top_entries:
        text = _entry_text(entry)
        if not text:
            continue
        cx, cy = _entry_center(entry)
        if cy > STORY_TOP_Y_MAX:
            continue
        for kw in STORY_HUD_KEYWORDS:
            if kw in text:
                hits.add(kw)
                if kw == "跳过" and cx >= 1000:
                    skip_top_hit = True
    return skip_top_hit or len(hits) >= 2


def find_story_skip_point(top_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Locate the top-right '跳过' button when story HUD is present."""
    for entry in top_entries:
        text = _entry_text(entry)
        if "跳过" not in text:
            continue
        cx, cy = _entry_center(entry)
        if cy <= STORY_TOP_Y_MAX and cx >= 1000:
            return cx, cy
    if has_story_hud(top_entries):
        return STORY_DEFAULT_SKIP_POINT
    return None


def find_story_confirm_point(center_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Locate a mid-screen confirmation button if a skip confirmation dialog appears."""
    for entry in center_entries:
        text = _entry_text(entry)
        if not text:
            continue
        cx, cy = _entry_center(entry)
        if not (220 <= cy <= 560 and 300 <= cx <= 980):
            continue
        if any(token in text for token in ("确认", "确定")):
            return cx, cy
    return None


def detect_dialogue_choices(image: Any) -> list[tuple[int, int]]:
    """Detect centered white dialogue choice bars and return their tap points top-to-bottom."""
    if np is None or image is None:
        return []
    arr = np.asarray(image)
    if arr.ndim != 3 or arr.shape[0] < CHOICE_Y2 or arr.shape[1] < CHOICE_X2:
        return []

    roi = arr[CHOICE_Y1:CHOICE_Y2, CHOICE_X1:CHOICE_X2, :3]
    min_c = roi.min(axis=2)
    max_c = roi.max(axis=2)
    white = (min_c >= 195) & ((max_c.astype(np.int16) - min_c.astype(np.int16)) <= 35)

    # Inner margins between the left speech icon / right arrow and centered choice text stay solid white.
    left_margin_white = white[:, 55:79].mean(axis=1) >= 0.85
    right_margin_white = white[:, -77:-47].mean(axis=1) >= 0.85
    row_white_ratio = white.mean(axis=1)
    candidate_rows = np.where(left_margin_white & right_margin_white & (row_white_ratio >= 0.45))[0]
    if candidate_rows.size == 0:
        return []

    bands: list[tuple[int, int]] = []
    start = prev = int(candidate_rows[0])
    for row_idx in candidate_rows[1:]:
        y = int(row_idx)
        if y <= prev + 4:
            prev = y
        else:
            bands.append((start, prev))
            start = prev = y
    bands.append((start, prev))

    points: list[tuple[int, int]] = []
    for band_start, band_end in bands:
        height = band_end - band_start + 1
        if not (CHOICE_MIN_HEIGHT <= height <= CHOICE_MAX_HEIGHT):
            continue
        # Ensure at least top/bottom border rows are mostly solid white (not a bright scene patch).
        border_rows = int((row_white_ratio[band_start : band_end + 1] >= 0.72).sum())
        if border_rows < 8:
            continue
        center_y = CHOICE_Y1 + int(round((band_start + band_end) / 2.0))
        points.append((CHOICE_CENTER_X, center_y))

    return points


def plan_story_skip_step(
    image: Any,
    top_entries: list[dict[str, Any]],
    center_entries: list[dict[str, Any]] = (),
    *,
    choice_index: int = 0,
) -> dict[str, Any]:
    """Plan the next action while skipping story dialogue."""
    confirm_point = find_story_confirm_point(list(center_entries))
    if confirm_point is not None:
        return {
            "action": "click",
            "reason": "confirm_skip",
            "point": confirm_point,
        }

    if not has_story_hud(top_entries):
        return {
            "action": "exit",
            "reason": "not_in_story",
        }

    choices = detect_dialogue_choices(image)
    if choices:
        idx = max(0, min(choice_index, len(choices) - 1))
        return {
            "action": "click",
            "reason": "select_choice",
            "point": choices[idx],
            "choice_count": len(choices),
        }

    skip_point = find_story_skip_point(top_entries)
    if skip_point is not None:
        return {
            "action": "click",
            "reason": "click_skip",
            "point": skip_point,
        }

    return {
        "action": "wait",
        "reason": "story_hud_transition",
    }

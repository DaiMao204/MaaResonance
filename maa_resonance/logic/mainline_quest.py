"""Pure logic helpers for mainline quest tracking, target offset, and city search."""
from __future__ import annotations

from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720

CITY_INTERACTIVE_ROI = (0, 20, 1280, 620)
TOP_RIGHT_TASK_PANEL_ROI = (960, 110, 320, 200)
LOBBY_RIGHT_PANEL_ROI = (900, 290, 380, 310)

EXCLUDED_HUD_ZONES: tuple[tuple[int, int, int, int], ...] = (
    TOP_RIGHT_TASK_PANEL_ROI,
    (0, 565, 420, 155),  # bottom-left city development & reputation bar
    (0, 0, 380, 48),     # top-left back / train-home / manual buttons strip (icon near y>=54 can still match)
)

CITY_QUEST_TO_AVATAR_OFFSET = (-42, 42)
DEFAULT_ICON_MIN_SCORE = 0.70
PULSE_RETRY_DELAY_SEC = 0.48

# Gentle horizontal pans to inspect off-screen parts of large cities, then recenter.
CITY_PAN_SWIPES: tuple[tuple[int, int, int, int], ...] = (
    (880, 360, 540, 360),   # pan right side into view
    (380, 360, 1040, 360),  # pan across center to left side
    (880, 360, 540, 360),   # return near center
)


def _normalize_box(box: Any) -> tuple[int, int, int, int] | None:
    if box is None:
        return None
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        try:
            x, y, w, h = int(box[0]), int(box[1]), int(box[2]), int(box[3])
            if w > 0 and h > 0:
                return x, y, w, h
        except (TypeError, ValueError):
            return None
    try:
        x = int(getattr(box, "x"))
        y = int(getattr(box, "y"))
        w = int(getattr(box, "w"))
        h = int(getattr(box, "h"))
        if w > 0 and h > 0:
            return x, y, w, h
    except (TypeError, ValueError, AttributeError):
        return None
    return None


def box_center(box: tuple[int, int, int, int]) -> tuple[int, int]:
    """Return integer ``(cx, cy)`` for an ``(x, y, w, h)`` box."""
    x, y, w, h = box
    return int(round(x + w / 2.0)), int(round(y + h / 2.0))


def boxes_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    """Return True when two ``(x, y, w, h)`` rectangles intersect."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def is_in_excluded_hud_zone(
    box: tuple[int, int, int, int],
    excluded_zones: tuple[tuple[int, int, int, int], ...] = EXCLUDED_HUD_ZONES,
) -> bool:
    """Check whether the center of ``box`` falls inside any HUD exclusion zone."""
    cx, cy = box_center(box)
    for zx, zy, zw, zh in excluded_zones:
        if zx <= cx < zx + zw and zy <= cy < zy + zh:
            return True
    return False


def compute_city_avatar_target(
    icon_box: tuple[int, int, int, int],
    *,
    offset: tuple[int, int] = CITY_QUEST_TO_AVATAR_OFFSET,
    bounds: tuple[int, int] = (SCREEN_WIDTH, SCREEN_HEIGHT),
    tap_size: int = 24,
) -> tuple[int, int, int, int]:
    """Shift from the top-right quest diamond to the circular NPC/node avatar center."""
    cx, cy = box_center(icon_box)
    dx, dy = int(offset[0]), int(offset[1])
    max_w, max_h = int(bounds[0]), int(bounds[1])
    size = max(4, int(tap_size))
    half = size // 2

    tx = max(half, min(max_w - half - 1, cx + dx))
    # Keep tap below the top-left back/home button bar (y <= 66) so top-edge NPCs don't accidentally hit go_home.
    ty = max(max(half, 74), min(max_h - half - 1, cy + dy))
    return (tx - half, ty - half, size, size)


def is_quest_icon_color_valid(
    image_bgr: Any,
    box: tuple[int, int, int, int],
    *,
    min_red_ratio: float = 0.14,
    min_white_ratio: float = 0.08,
) -> bool:
    """Verify the matched patch contains both vivid red diamond pixels and white book pixels."""
    if np is None or image_bgr is None:
        return True
    arr = np.asarray(image_bgr)
    if arr.ndim != 3 or arr.shape[2] < 3:
        return True

    h_img, w_img = int(arr.shape[0]), int(arr.shape[1])
    x, y, w, h = box
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(w_img, x + w)
    y2 = min(h_img, y + h)
    if x2 <= x1 or y2 <= y1:
        return False

    patch = arr[y1:y2, x1:x2, :3].astype(np.int16)
    b = patch[..., 0]
    g = patch[..., 1]
    r = patch[..., 2]

    red_mask = (r >= 170) & ((r - g) >= 70) & ((r - b) >= 70)
    white_mask = (r >= 205) & (g >= 205) & (b >= 205)

    red_ratio = float(red_mask.mean())
    white_ratio = float(white_mask.mean())
    return red_ratio >= float(min_red_ratio) and white_ratio >= float(min_white_ratio)


def select_best_quest_icon(
    candidates: list[Any],
    *,
    image_bgr: Any = None,
    excluded_zones: tuple[tuple[int, int, int, int], ...] = EXCLUDED_HUD_ZONES,
    min_score: float = DEFAULT_ICON_MIN_SCORE,
) -> dict[str, Any] | None:
    """Pick the highest-scoring valid quest icon candidate outside HUD exclusion zones."""
    parsed: list[tuple[float, tuple[int, int, int, int]]] = []
    for item in candidates or ():
        if isinstance(item, dict):
            box = _normalize_box(item.get("box"))
            raw_score = item.get("score", 0.0)
        else:
            box = _normalize_box(getattr(item, "box", None))
            raw_score = getattr(item, "score", 0.0)
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = 0.0
        if box is None or score < float(min_score):
            continue
        parsed.append((score, box))

    parsed.sort(key=lambda pair: pair[0], reverse=True)
    for score, box in parsed:
        if is_in_excluded_hud_zone(box, excluded_zones=excluded_zones):
            continue
        if image_bgr is not None and not is_quest_icon_color_valid(image_bgr, box):
            continue
        return {
            "box": box,
            "score": score,
            "center": box_center(box),
        }
    return None


def select_lobby_quest_button(
    icon_box: tuple[int, int, int, int],
    button_entries: list[dict[str, Any]] | None = None,
) -> tuple[int, int, int, int]:
    """Resolve which right-side lobby action button owns the quest icon."""
    ix, iy = box_center(icon_box)
    best_box: tuple[int, int, int, int] | None = None
    best_dist: float | None = None

    for entry in button_entries or ():
        if not isinstance(entry, dict):
            continue
        box = _normalize_box(entry.get("box"))
        if box is None and all(k in entry for k in ("x", "y", "w", "h")):
            box = _normalize_box((entry.get("x"), entry.get("y"), entry.get("w"), entry.get("h")))
        if box is None:
            continue
        bx, by = box_center(box)
        dist = ((bx - ix) ** 2 + (by - iy) ** 2) ** 0.5
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_box = box

    if best_box is not None and best_dist is not None and best_dist <= 220.0:
        return best_box

    # Fallback anchors in 1280x720 lobby right-hand column when OCR missed button label.
    if iy < 415:
        return (1100, 355, 140, 50)  # 作战终端
    if iy < 570:
        return (1090, 455, 160, 60)  # 访问城市 / 访问地区
    return (1135, 625, 110, 60)      # 启程 / START ENGINE


def parse_mainline_task_summary(ocr_entries: list[dict[str, Any]]) -> str:
    """Join visible top-right quest panel lines into a compact summary string."""
    lines: list[str] = []
    for entry in ocr_entries or ():
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").strip()
        if not text or text in {"任务", "主线", "支线"}:
            continue
        lines.append(text)
    return " | ".join(lines[:3])

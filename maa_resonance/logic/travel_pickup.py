"""Locate travel pickup icons in a fresh 1280x720 BGR frame, without input.

The blue icon is shared by ground cargo and balloon cargo.  Color only narrows
the search; native template matching must also confirm the inner cube.  The
caller must confirm ``is_travel_hud`` on this same frame before using targets.
"""

from __future__ import annotations

from typing import Any

import numpy as np


_PREFIX = "business/travel_pickup/"
_SIZES = tuple(range(10, 39, 2))
_HUD_ROI = [610, 107, 104, 35]
_HUD_TEXT_BOX = (60, 7, 81, 20)
_WORLD_ROI = (200, 145, 820, 405)
_MIN_SCORE = 0.65
# Bright pixels from the cruise HUD reference, relative to its matched box.
# CCOEFF alone is invariant to dark popup masks, so preserve absolute brightness.
_HUD_WHITE_POINTS = np.array([
    (37, 7), (39, 7), (41, 7), (43, 7), (35, 8), (37, 8),
    (41, 8), (45, 8), (34, 9), (46, 9), (33, 10), (35, 10),
    (48, 10), (33, 11), (46, 11), (68, 11), (49, 12), (64, 12),
    (116, 12), (129, 12), (50, 13), (86, 13), (88, 13), (128, 13),
    (50, 14), (31, 15), (39, 15), (50, 15), (64, 15), (79, 15),
    (31, 16), (33, 16), (40, 16), (42, 16), (49, 16), (51, 16),
    (111, 16), (31, 17), (40, 17), (42, 17), (51, 17), (129, 17),
    (30, 18), (40, 18), (42, 18), (64, 18), (128, 18), (39, 19),
    (41, 19), (51, 19), (82, 19), (41, 20), (78, 20), (31, 21),
    (51, 21), (31, 22), (32, 23), (34, 23), (48, 23), (50, 23),
    (33, 24), (49, 24),
], dtype=np.intp)


def _frame(image: Any) -> np.ndarray | None:
    if not isinstance(image, np.ndarray):
        return None
    # Resource coordinates and templates use the project's standard resolution.
    # Reject unknown layouts instead of placing clicks on their UI.
    if image.shape != (720, 1280, 3) or image.dtype != np.uint8:
        return None
    return image


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _accepted_match(detail: Any, minimum: float) -> tuple[list[int], float] | None:
    if not _field(detail, "hit", False):
        return None
    best = _field(detail, "best_result")
    box = _field(best, "box")
    score = _field(best, "score")
    try:
        if len(box) != 4:
            return None
        box = [int(value) for value in box]
        score = float(score)
    except (TypeError, ValueError, OverflowError):
        return None
    x, y, width, height = box
    if not np.isfinite(score) or score < minimum or width <= 0 or height <= 0:
        return None
    if x < 0 or y < 0 or x + width > 1280 or y + height > 720:
        return None
    return box, score


def _match(context: Any, image: np.ndarray, name: str, templates: list[str],
           roi: list[int], minimum: float) -> tuple[list[int], float] | None:
    detail = context.run_recognition(name, image, {name: {
        "recognition": "TemplateMatch", "template": templates, "roi": roi,
        "threshold": [minimum] * len(templates), "method": 5,
        "order_by": "Score",
    }})
    return _accepted_match(detail, minimum)


def is_travel_hud(context: Any, image: Any) -> bool:
    """Confirm the unmasked cruise HUD without OCR or controller operations."""
    frame = _frame(image)
    if frame is None:
        return False
    # The cruise pill is translucent: passing scenery (especially bright signs)
    # changes its background. Match only the stable text, at the same threshold.
    match = _match(context, frame, "TravelPickupCruiseHudTemplate",
                   [_PREFIX + "cruise_hud_text.png"], _HUD_ROI, 0.88)
    if match is None:
        return False
    (x, y, width, height), _ = match
    offset_x, offset_y, expected_width, expected_height = _HUD_TEXT_BOX
    if (width, height) != (expected_width, expected_height):
        return False
    # Preserve the existing full-HUD white samples and absolute thresholds.
    # Sampling only the text would change the brightness distribution.
    x, y = x - offset_x, y - offset_y
    if x < 0 or y < 0 or x + 162 > 1280 or y + 33 > 720:
        return False
    values = frame[y + _HUD_WHITE_POINTS[:, 1], x + _HUD_WHITE_POINTS[:, 0]].min(axis=1)
    return bool(np.mean(values >= 210) >= 0.85 and np.median(values) >= 225)


def _blue_components(image: np.ndarray) -> list[list[int]]:
    left, top, width, height = _WORLD_ROI
    crop = image[top:top + height, left:left + width].astype(np.int16)
    blue, green, red = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    mask = (blue - red > 38) & (blue - green > 14) & (green - red > 5) & (blue > 105)
    # Row spans keep the connected-component pass small without cv2/scipy.
    groups: list[list[int]] = []
    parents: list[int] = []
    previous: list[tuple[int, int, int]] = []

    def root(key: int) -> int:
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    transitions = np.diff(np.pad(mask, ((0, 0), (1, 1))).astype(np.int8), axis=1)
    for y, row in enumerate(transitions):
        starts = np.flatnonzero(row == 1).tolist()
        ends = np.flatnonzero(row == -1).tolist()
        current = []
        for x1, x2 in zip(starts, ends):
            touching = [root(key) for p1, p2, key in previous if p1 <= x2 and p2 >= x1]
            if touching:
                key = min(touching)
                for old in touching:
                    old = root(old)
                    if old != key:
                        parents[old] = key
                        a, b = groups[key], groups[old]
                        a[:] = [min(a[0], b[0]), min(a[1], b[1]),
                                max(a[2], b[2]), max(a[3], b[3]), a[4] + b[4]]
                a = groups[key]
                a[:] = [min(a[0], x1), min(a[1], y), max(a[2], x2), y + 1, a[4] + x2 - x1]
            else:
                key = len(groups)
                parents.append(key)
                groups.append([x1, y, x2, y + 1, x2 - x1])
            current.append((x1, x2, key))
        previous = current
    candidates = []
    for key, (x1, y1, x2, y2, count) in enumerate(groups):
        w, h = x2 - x1, y2 - y1
        if (root(key) == key and 12 <= w <= 72 and 12 <= h <= 72
                and 0.65 <= w / h <= 1.5 and count / (w * h) >= 0.38):
            candidates.append([x1 + left, y1 + top, w, h, count])
    # Bound work if scenery is unusually blue; strong compact icons go first.
    candidates.sort(key=lambda value: value[4] / (value[2] * value[3]), reverse=True)
    return candidates[:6]


def find_pickup_targets(context: Any, image: Any) -> list[dict[str, Any]]:
    """Find cube centers; caller must gate the same frame with is_travel_hud."""
    frame = _frame(image)
    if frame is None:
        return []
    targets = []
    for x, y, width, height, _ in _blue_components(frame):
        diameter = max(width, height)
        sizes = [size for size in _SIZES if 0.52 * diameter <= size <= 0.8 * diameter]
        if not sizes:
            continue
        templates = [_PREFIX + f"cube_{source}_{size}.png" for source in ("small", "large") for size in sizes]
        match = _match(context, frame, "TravelPickupCubeTemplate", templates,
                       [x - 7, y - 7, width + 14, height + 14], _MIN_SCORE)
        if match is None:
            continue
        box, score = match
        center = [box[0] + box[2] // 2, box[1] + box[3] // 2]
        # The cube must sit in the blue disk, not somewhere else in its ROI.
        if abs(center[0] - (x + width / 2)) > diameter * 0.22:
            continue
        if abs(center[1] - (y + height / 2)) > diameter * 0.22:
            continue
        targets.append({"box": box, "target": center, "score": score})
    return sorted(targets, key=lambda item: item["score"], reverse=True)

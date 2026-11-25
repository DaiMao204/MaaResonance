"""Pure logic helpers for Clarity (stamina) recovery in mainline progression."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class ClarityCardSpec:
    """Static layout metadata for a Clarity recovery card on a 1280x720 screen."""

    key: str
    name: str
    kind: str  # "medicine" | "huashi"
    restore: int
    card_roi: tuple[int, int, int, int]
    count_roi: tuple[int, int, int, int]
    tap_point: tuple[int, int]
    order: int


CLARITY_CARDS: tuple[ClarityCardSpec, ...] = (
    ClarityCardSpec(
        key="lollipop",
        name="仙人掌能量棒棒糖",
        kind="medicine",
        restore=40,
        card_roi=(40, 495, 295, 175),
        count_roi=(45, 610, 90, 45),
        tap_point=(195, 585),
        order=0,
    ),
    ClarityCardSpec(
        key="roll",
        name="仙人掌跳跳卷",
        kind="medicine",
        restore=60,
        card_roi=(345, 495, 290, 175),
        count_roi=(350, 610, 90, 45),
        tap_point=(495, 585),
        order=1,
    ),
    ClarityCardSpec(
        key="candy",
        name="仙人掌能量跳糖",
        kind="medicine",
        restore=180,
        card_roi=(640, 495, 295, 175),
        count_roi=(645, 610, 90, 45),
        tap_point=(790, 585),
        order=2,
    ),
    ClarityCardSpec(
        key="huashi",
        name="桦石",
        kind="huashi",
        restore=100,
        card_roi=(940, 495, 310, 175),
        count_roi=(940, 505, 150, 40),
        tap_point=(1085, 585),
        order=3,
    ),
)

CLARITY_BACK_POINT = (63, 32)
CLARITY_POPUP_ROI = (220, 120, 840, 540)
HUASHI_USE_CAP = 8

_UNAVAILABLE_KEYWORDS = ("获取途径", "库存不足", "数量不足", "无库存", "没有可用", "已达上限", "次数不足")
_LIMITED_KEYWORDS = ("剩余时间", "天后", "小时")
_CONFIRM_KEYWORDS = ("确定", "确认", "使用", "补充", "确认使用", "确定使用", "确认补充", "确定补充", "立即使用")
_CANCEL_KEYWORDS = ("取消", "关闭")


def _entry_box(entry: dict[str, Any]) -> tuple[int, int, int, int] | None:
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
    if "center_x" in entry and "center_y" in entry:
        try:
            return int(round(float(entry["center_x"]))), int(round(float(entry["center_y"])))
        except (TypeError, ValueError):
            pass
    box = _entry_box(entry)
    if box is None:
        return None
    return int(round(box[0] + box[2] / 2.0)), int(round(box[1] + box[3] / 2.0))


def _point_in_roi(pt: tuple[int, int] | None, roi: tuple[int, int, int, int]) -> bool:
    if pt is None:
        return False
    x, y = pt
    rx, ry, rw, rh = roi
    return rx <= x <= rx + rw and ry <= y <= ry + rh


def parse_clarity_status(ocr_entries: list[dict[str, Any]]) -> dict[str, int] | None:
    """Extract ``current``, ``total``, ``remaining_gap`` from the Clarity ratio text (e.g. ``29/288``)."""
    for entry in ocr_entries or ():
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").strip().replace("O", "0").replace("o", "0")
        center = _entry_center(entry)
        # Focus on the left Clarity readout area when box coordinates are present.
        if center is not None and (center[0] > 480 or center[1] < 320 or center[1] > 500):
            continue
        match = re.search(r"(\d{1,4})\s*/\s*(\d{2,4})", text)
        if not match:
            continue
        current = int(match.group(1))
        total = int(match.group(2))
        if total > 0 and 0 <= current <= total * 2:
            return {
                "current": current,
                "total": total,
                "remaining_gap": max(0, total - current),
            }
    return None


def parse_clarity_cards(ocr_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inspect OCR entries on the Clarity recovery screen and build per-card state."""
    cards: list[dict[str, Any]] = []
    for spec in CLARITY_CARDS:
        card_texts: list[str] = []
        count: int | None = None
        is_limited = False
        unavailable = False
        huashi_remaining: int | None = None

        for entry in ocr_entries or ():
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("text") or "").strip()
            if not text:
                continue
            center = _entry_center(entry)
            if not _point_in_roi(center, spec.card_roi):
                continue
            card_texts.append(text)
            if any(kw in text for kw in _LIMITED_KEYWORDS):
                is_limited = True
            if any(kw in text for kw in _UNAVAILABLE_KEYWORDS):
                unavailable = True

            if spec.kind == "huashi":
                limit_match = re.search(r"(\d{1,2})\s*/\s*8", text.replace("O", "0").replace("o", "0"))
                if limit_match:
                    huashi_remaining = int(limit_match.group(1))
                    if huashi_remaining <= 0:
                        unavailable = True
            elif _point_in_roi(center, spec.count_roi):
                norm = text.replace("O", "0").replace("o", "0").strip()
                if re.fullmatch(r"\d{1,4}", norm):
                    count = int(norm)

        if count == 0 or not card_texts:
            unavailable = True

        cards.append(
            {
                "key": spec.key,
                "name": spec.name,
                "kind": spec.kind,
                "restore": spec.restore,
                "order": spec.order,
                "count": huashi_remaining if spec.kind == "huashi" else count,
                "is_limited": is_limited,
                "unavailable": unavailable,
                "tap_point": spec.tap_point,
                "texts": card_texts,
            }
        )
    return cards


def parse_clarity_limits(params: dict[str, Any] | None) -> dict[str, int]:
    """Interpret -1 as unlimited for medicines and as the eight-use maximum for Huashi."""
    mapping = {
        "lollipop": ("lollipop_use_limit", None),
        "roll": ("roll_use_limit", None),
        "candy": ("candy_use_limit", None),
        "huashi": ("huashi_use_limit", HUASHI_USE_CAP),
    }
    limits: dict[str, int] = {}
    raw_params = params if isinstance(params, dict) else {}
    for card_key, (param_key, max_cap) in mapping.items():
        raw_val = raw_params.get(param_key, 0)
        try:
            parsed = int(raw_val)
        except (TypeError, ValueError):
            parsed = 0
        if parsed < -1:
            parsed = 0
        if max_cap is not None and (parsed == -1 or parsed > max_cap):
            parsed = max_cap
        limits[card_key] = parsed
    return limits


def choose_clarity_card(
    cards: list[dict[str, Any]],
    *,
    allow_huashi: bool = False,
    excluded_keys: set[str] | frozenset[str] = frozenset(),
    limits: dict[str, int] | None = None,
    used_counts: dict[str, int] | None = None,
) -> dict[str, Any] | None:
    """Pick the best Clarity recovery card respecting limits, time-limited priority, and stock."""
    candidates: list[dict[str, Any]] = []
    used_map = used_counts or {}
    for card in cards:
        key = str(card.get("key") or "")
        if key in excluded_keys or card.get("unavailable"):
            continue
        kind = str(card.get("kind") or "")
        if key == "huashi" and int(used_map.get(key, 0)) >= HUASHI_USE_CAP:
            continue
        if limits is not None:
            limit = int(limits.get(key, 0))
            if limit == 0:
                continue
            if limit > 0 and int(used_map.get(key, 0)) >= limit:
                continue
        elif kind == "huashi" and not allow_huashi:
            continue
        count = card.get("count")
        if count is not None and int(count) <= 0:
            continue
        candidates.append(card)

    if not candidates:
        return None

    candidates.sort(
        key=lambda c: (
            0 if c.get("kind") == "medicine" else 1,
            0 if (c.get("count") is not None and int(c.get("count") or 0) > 0) else 1,
            0 if c.get("is_limited") else 1,
            int(c.get("restore") or 0),
            int(c.get("order") or 0),
        )
    )
    return candidates[0]


def popup_reports_no_stock(ocr_entries: list[dict[str, Any]]) -> bool:
    """Return True when the confirmation/item popup reports missing inventory or limit reached."""
    joined = "".join(str(e.get("text") or "").strip() for e in (ocr_entries or ()) if isinstance(e, dict))
    return any(kw in joined for kw in _UNAVAILABLE_KEYWORDS)


_CONFIRM_POPUP_CONTEXT_KEYWORDS = ("当前澄明度", "补充后澄明度", "恢复后澄明度", "使用后澄明度", "补充次数", "恢复次数")


def clarity_popup_item_keys(ocr_entries: list[dict[str, Any]]) -> set[str]:
    """Read item names in the dialog, ignoring the picker cards visible behind it."""
    keys = set()
    for entry in ocr_entries:
        text = "".join(str(entry.get("text") or "").split())
        center = _entry_center(entry)
        if center is not None:
            if not _point_in_roi(center, CLARITY_POPUP_ROI):
                continue
            if center[1] >= CLARITY_CARDS[0].card_roi[1] and not any(
                word in text for word in ("消耗", "花费", "扣除", "使用")
            ):
                continue
        for spec in CLARITY_CARDS:
            if spec.name.removeprefix("仙人掌") in text:
                keys.add(spec.key)
    return keys


def has_clarity_popup_context(ocr_entries: list[dict[str, Any]]) -> bool:
    joined = "".join(str(e.get("text") or "").strip() for e in ocr_entries)
    return any(kw in joined for kw in _CONFIRM_POPUP_CONTEXT_KEYWORDS) or bool(clarity_popup_item_keys(ocr_entries))


def is_clarity_confirm_popup(ocr_entries: list[dict[str, Any]]) -> bool:
    """Return True when OCR entries indicate the Clarity item confirmation dialog is open."""
    if find_clarity_popup_button(ocr_entries, kind="confirm") is None:
        return False
    return has_clarity_popup_context(ocr_entries)


def find_clarity_popup_button(
    ocr_entries: list[dict[str, Any]],
    *,
    kind: str = "confirm",
) -> tuple[int, int] | None:
    """Locate confirm/cancel button center inside an item-use confirmation popup."""
    keywords = _CONFIRM_KEYWORDS if kind == "confirm" else _CANCEL_KEYWORDS
    matches: list[tuple[int, int, str]] = []
    for entry in ocr_entries or ():
        if not isinstance(entry, dict):
            continue
        text = "".join(str(entry.get("text") or "").split())
        if text not in keywords:
            continue
        center = _entry_center(entry)
        if center is None:
            continue
        cx, cy = center
        if not (240 <= cx <= 1120 and 320 <= cy <= 660):
            continue
        matches.append((cx, cy, text))

    if not matches:
        return None
    # Confirm buttons sit on the right half; cancel buttons sit on the left half.
    matches.sort(key=lambda item: item[0], reverse=(kind == "confirm"))
    return matches[0][0], matches[0][1]

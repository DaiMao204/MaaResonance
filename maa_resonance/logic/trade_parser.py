from __future__ import annotations

import re
from typing import Any

from .profile_parser import clean_text


PRODUCT_LOCKED_TEXTS = (
    "需要解锁",
    "未解锁",
    "本城声望达到",
    "声望达到",
    "投资方案",
)
PRODUCT_OUT_OF_STOCK_TEXTS = ("可补充", "库存不足", "已售罄")


def classify_product_unlock_texts(texts: list[str]) -> str:
    cleaned = [clean_text(text) for text in texts if str(text).strip()]
    if any(any(keyword in text for keyword in PRODUCT_LOCKED_TEXTS) for text in cleaned):
        return "locked"
    return "unknown"


def normalize_trade_good_text(text: Any) -> str:
    return clean_text(str(text or "")).replace(" ", "")


def match_trade_good(text: Any, targets: list[str]) -> str | None:
    normalized = normalize_trade_good_text(text)
    if not normalized:
        return None
    goods = [
        (str(good), normalize_trade_good_text(good))
        for good in targets
        if normalize_trade_good_text(good)
    ]
    for good, good_text in goods:
        if normalized == good_text:
            return good
    for good, good_text in sorted(goods, key=lambda item: len(item[1]), reverse=True):
        if good_text in normalized:
            return good
    if len(normalized) >= 3:
        for good, good_text in sorted(goods, key=lambda item: len(item[1])):
            if normalized in good_text:
                return good
    return None


def trade_good_row_entries(entries: list[dict[str, Any]], center_y: float) -> list[dict[str, Any]]:
    row_entries = [
        item
        for item in entries
        if -34 <= float(item.get("center_y") or 0) - center_y <= 78
    ]
    row_entries.sort(key=lambda item: (int(item.get("y") or 0), int(item.get("x") or 0)))
    return row_entries


def trade_good_row_texts(entries: list[dict[str, Any]], center_y: float) -> list[str]:
    row_entries = trade_good_row_entries(entries, center_y)
    texts: list[str] = []
    for item in row_entries:
        text = str(item.get("text") or "")
        if text and text not in texts:
            texts.append(text)
    return texts[:16]


def _numeric_text_variants(text: Any) -> list[str]:
    raw = str(text or "")
    normalized = clean_text(raw).replace(",", "").replace("，", "")
    variants = {
        normalized,
        normalized.replace("O", "0").replace("o", "0"),
        normalized.replace("I", "1").replace("l", "1").replace("|", "1"),
    }
    return [item for item in variants if item]


def _expected_buy_lot(value: Any) -> int | None:
    try:
        lot = int(value)
    except (TypeError, ValueError):
        return None
    return lot if lot > 0 else None


def _plausible_buy_lot_candidate(
    value: int,
    expected_lot: int | None,
    *,
    allow_below_expected: bool = False,
) -> bool:
    return 0 < value <= 99999


def _trade_good_buy_lot_candidate_values(
    digits: str,
    *,
    expected_lot: int | None,
    repair_by_expected: bool,
    allow_below_expected: bool,
) -> list[tuple[int, int]]:
    values: list[tuple[int, int]] = []
    try:
        raw_value = int(digits)
    except ValueError:
        return values
    if _plausible_buy_lot_candidate(
        raw_value,
        expected_lot,
        allow_below_expected=allow_below_expected,
    ):
        values.append((raw_value, 0))
    return values


def parse_trade_good_buy_lot(
    entries: list[dict[str, Any]],
    center_y: float,
    *,
    good_entry: dict[str, Any] | None = None,
    expected_lot: Any = None,
) -> int | None:
    """Read the small buy-lot number at the lower-right of a product card."""
    row_entries = trade_good_row_entries(entries, center_y)
    expected_buy_lot = _expected_buy_lot(expected_lot)
    try:
        good_x = float((good_entry or {}).get("center_x") or 0)
    except (TypeError, ValueError):
        good_x = 0
    candidates: list[tuple[int, float, float, int, str]] = []
    for item in row_entries:
        try:
            center_x = float(item.get("center_x") or 0)
            item_center_y = float(item.get("center_y") or 0)
        except (TypeError, ValueError):
            continue
        # The available quantity is printed at the lower-right of the product
        # image. The paper-number column to the right of the good name is price.
        icon_lot_region = center_x <= 705 and (not good_x or center_x < good_x - 80)
        if not icon_lot_region:
            continue
        raw_text = str(item.get("text") or "")
        for text in _numeric_text_variants(raw_text):
            if "%" in text or "/" in text or "." in text:
                continue
            match = re.fullmatch(r"\D*(\d{1,4})\D*", text)
            if not match:
                continue
            for value, repair_priority in _trade_good_buy_lot_candidate_values(
                match.group(1),
                expected_lot=expected_buy_lot,
                repair_by_expected=False,
                allow_below_expected=True,
            ):
                if expected_buy_lot is None:
                    score = 10
                else:
                    score = 100 + repair_priority * 20
                candidates.append((score, center_x, item_center_y, value, raw_text))
    if not candidates:
        return None
    # The quantity sits at the bottom-right corner of the product image.
    return max(candidates, key=lambda item: (item[0], item[1], item[2]))[3]


def parse_trade_tax_rate(texts: list[str]) -> float | None:
    candidates: list[tuple[int, float, str]] = []
    for raw_text in texts:
        text = clean_text(raw_text).replace("％", "%")
        if not text:
            continue
        priority = 1 if "税率" in text else 0
        for match in re.finditer(r"(\d{1,2}(?:\.\d{1,2})?)\s*%", text):
            value = float(match.group(1)) / 100
            if 0 <= value <= 1:
                candidates.append((priority, value, raw_text))
        if "税率" in text and not candidates:
            match = re.search(r"税率[^\d]*(\d{1,2}(?:\.\d{1,2})?)", text)
            if match:
                value = float(match.group(1))
                if value > 1:
                    value /= 100
                if 0 <= value <= 1:
                    candidates.append((priority, value, raw_text))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def visible_product_unlock_status(
    entries: list[dict[str, Any]],
    targets: list[str],
    *,
    expected_buy_lots: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    matched: dict[str, dict[str, Any]] = {}
    for entry in entries:
        good = match_trade_good(entry.get("text"), targets)
        if not good or good in matched:
            continue
        center_y = float(entry.get("center_y") or 0)
        row_texts = trade_good_row_texts(entries, center_y)
        buy_lot = parse_trade_good_buy_lot(
            entries,
            center_y,
            good_entry=entry,
            expected_lot=(expected_buy_lots or {}).get(good),
        )
        locked = any(
            any(keyword in clean_text(text) for keyword in PRODUCT_LOCKED_TEXTS)
            for text in row_texts
        )
        out_of_stock = any(
            any(keyword in clean_text(text) for keyword in PRODUCT_OUT_OF_STOCK_TEXTS)
            for text in row_texts
        )
        matched[good] = {
            "unlocked": not locked and not out_of_stock,
            "locked": locked,
            "out_of_stock": out_of_stock,
            "texts": row_texts[:12],
            "center_y": center_y,
            "buy_lot": buy_lot,
        }
    return matched


def visible_product_unlock_status_from_texts(texts: list[str], targets: list[str]) -> dict[str, dict[str, Any]]:
    matched: dict[str, dict[str, Any]] = {}
    cleaned = [clean_text(text) for text in texts if str(text or "").strip()]
    has_lock_hint = any(
        any(keyword in text for keyword in PRODUCT_LOCKED_TEXTS)
        for text in cleaned
    )
    if has_lock_hint:
        return matched
    for text in texts:
        good = match_trade_good(text, targets)
        if not good or good in matched:
            continue
        matched[good] = {
            "unlocked": True,
            "texts": [str(text)],
            "center_y": 0,
            "source": "text_fallback",
        }
    return matched


def trade_list_page_signature(entries: list[dict[str, Any]]) -> list[str]:
    rows: list[tuple[int, str]] = []
    for entry in entries:
        text = normalize_trade_good_text(entry.get("text"))
        if not text:
            continue
        center_y = int(round(float(entry.get("center_y") or 0) / 24) * 24)
        rows.append((center_y, text))
    rows.sort()
    return [f"{y}:{text}" for y, text in rows[:32]]


def trade_list_text_signature(texts: list[str]) -> list[str]:
    return [normalize_trade_good_text(text) for text in texts if normalize_trade_good_text(text)][:32]

from __future__ import annotations

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


def trade_good_row_texts(entries: list[dict[str, Any]], center_y: float) -> list[str]:
    row_entries = [
        item
        for item in entries
        if -34 <= float(item.get("center_y") or 0) - center_y <= 78
    ]
    row_entries.sort(key=lambda item: (int(item.get("y") or 0), int(item.get("x") or 0)))
    texts: list[str] = []
    for item in row_entries:
        text = str(item.get("text") or "")
        if text and text not in texts:
            texts.append(text)
    return texts[:16]


def visible_product_unlock_status(
    entries: list[dict[str, Any]],
    targets: list[str],
) -> dict[str, dict[str, Any]]:
    matched: dict[str, dict[str, Any]] = {}
    for entry in entries:
        good = match_trade_good(entry.get("text"), targets)
        if not good or good in matched:
            continue
        center_y = float(entry.get("center_y") or 0)
        row_texts = trade_good_row_texts(entries, center_y)
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

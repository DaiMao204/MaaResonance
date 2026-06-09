from __future__ import annotations

import re
from typing import Any

from .profile_parser import clean_text


def strength_status_from_texts(texts: list[str]) -> dict[str, int] | None:
    """Parse current/total fatigue from OCR texts."""
    cleaned = [clean_text(text) for text in texts if str(text).strip()]

    def result(current: int, total: int) -> dict[str, int] | None:
        if total <= 0 or current < 0:
            return None
        # The game can show over-fatigue values such as 923/920 after the train
        # has already exceeded the safe limit. Treat them as valid with zero
        # remaining fatigue, but still reject obvious OCR outliers.
        if current > total * 2:
            return None
        return {
            "current": current,
            "total": total,
            "remaining": max(0, total - current),
        }

    def parse_plain_number(text: str) -> int | None:
        if ":" in text or "：" in text or "-" in text:
            return None
        normalized = text.strip().replace("O", "0").replace("o", "0")
        normalized = re.sub(r"[\s,+]+", "", normalized)
        if re.fullmatch(r"\d{1,4}", normalized):
            return int(normalized)
        return None

    def parse_lost_slash_total(text: str) -> int | None:
        if ":" in text or "：" in text or "-" in text:
            return None
        normalized = text.strip().replace("O", "0").replace("o", "0")
        normalized = re.sub(r"[\s,+/]+", "", normalized)
        if not re.fullmatch(r"1\d{3,4}", normalized):
            return None
        total = int(normalized[1:])
        if 100 <= total <= 2000:
            return total
        return None

    for text in cleaned:
        normalized = text.replace("O", "0").replace("o", "0")
        match = re.search(r"(\d{1,4})\s*/\s*(\d{2,4})", normalized)
        if not match:
            continue
        parsed = result(int(match.group(1)), int(match.group(2)))
        if parsed:
            return parsed

    total_index: int | None = None
    total: int | None = None
    for index, text in enumerate(cleaned):
        normalized = text.replace("O", "0").replace("o", "0")
        match = re.search(r"/\s*(\d{2,4})", normalized)
        if match:
            total_index = index
            total = int(match.group(1))
            break
        lost_slash_total = parse_lost_slash_total(normalized)
        if lost_slash_total is not None:
            total_index = index
            total = lost_slash_total
            break
    if total_index is None or total is None:
        return None

    label_indices = [index for index, text in enumerate(cleaned) if "列车长疲劳值" in text or "疲劳值" == text]
    search_indices: list[int] = []
    for label_index in label_indices:
        search_indices.extend(range(max(0, label_index - 8), min(len(cleaned), label_index + 3)))
    search_indices.extend(range(max(0, total_index - 12), total_index))
    seen: set[int] = set()
    candidates: list[int] = []
    for index in search_indices:
        if index in seen or index == total_index:
            continue
        seen.add(index)
        current = parse_plain_number(cleaned[index])
        if current is None:
            continue
        parsed = result(current, total)
        if parsed:
            candidates.append(current)
    if candidates:
        current = max(candidates, key=lambda value: (len(str(value)), value))
        return result(current, total)
    return None


def medicine_inventory_count(texts: list[str]) -> int | None:
    """Parse medicine inventory count from the fatigue medicine popup."""
    candidates = [clean_text(text).replace("O", "0").replace("o", "0") for text in texts]
    for index, text in enumerate(candidates):
        if not any(keyword in text for keyword in ("持有数量", "拥有数量", "持有数", "拥有数", "持有", "拥有")):
            continue
        window = "|".join(candidates[index : index + 3])
        label_match = re.search(r"(?:持有数量|拥有数量|持有数|拥有数|持有|拥有)[:：]?\D*(\d{1,4})", window)
        if label_match:
            return int(label_match.group(1))
        numbers = [int(value) for value in re.findall(r"\d{1,4}", window)]
        if numbers:
            return numbers[0]
    return None


def medicine_no_inventory_seen(texts: list[str]) -> bool:
    joined = "".join(clean_text(text) for text in texts)
    return any(keyword in joined for keyword in ("无库存", "数量不足", "库存不足", "已用完", "没有可用"))


def huashi_daily_remaining(texts: list[str]) -> int | None:
    joined = "".join(clean_text(text).replace("O", "0").replace("o", "0") for text in texts)
    match = re.search(r"(?:每日)?限购[:：]?\s*(\d{1,2})\s*/\s*8", joined)
    if match:
        return int(match.group(1))
    match = re.search(r"(?:剩余|剩余次数|剩余可用|还可|可用|还能)[^\d]{0,8}(\d{1,2})", joined)
    if match:
        return int(match.group(1))
    return None


def huashi_notice_from_texts(texts: list[str]) -> dict[str, Any] | None:
    joined = "".join(texts).replace(" ", "").replace("O", "0").replace("o", "0")
    match = re.search(r"消耗[^\d]*(\d{1,4}).*?桦石.*?(?:消除|恢复)[^\d]*(\d{1,4}).*?疲劳", joined)
    if match:
        return {
            "cost": int(match.group(1)),
            "restore": int(match.group(2)),
            "text": f"本次消耗 {match.group(1)} 桦石，恢复 {match.group(2)} 疲劳",
            "exact": True,
        }
    if "桦石" in joined and "疲劳" in joined:
        return {
            "cost": None,
            "restore": None,
            "text": "确认弹窗已显示桦石与疲劳文本，但未读到明确数值",
            "exact": False,
        }
    return None


def huashi_exhausted_seen(texts: list[str]) -> bool:
    joined = "".join(clean_text(text) for text in texts)
    if huashi_daily_remaining(texts) == 0:
        return True
    return any(keyword in joined for keyword in ("购买次数不足", "次数不足", "今日已达上限", "今日次数已用完", "限购0/8"))

"""Pure logic, pixel/OCR parsers, and per-UID scheduling for AutoShop (自动商店采购)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Default conservative user configuration
# ---------------------------------------------------------------------------

DEFAULT_HQ_GOLD_ITEMS: str = (
    "拉普拉斯协议:周, 拉普拉斯协议:月, 追加注资申请书:月, 进货采买书:周, 仙人掌能量棒棒糖:周, 提神棒棒糖:周"
)
DEFAULT_HQ_GOLD_RESERVE: int = 3000000
DEFAULT_HQ_TICKET_ITEMS: str = ""
DEFAULT_HQ_TICKET_RESERVE: int = 0
DEFAULT_FUMING_ITEMS: str = "追加注资申请书:月, 进货采买书:周, 进货采买书:月"
DEFAULT_FUMING_PURPLE_RESERVE: int = 2000
DEFAULT_CHAMBER_ITEMS: str = "进货采买书:周, 进货采买书:月"
DEFAULT_CHAMBER_RESERVE: int = 1000

DEFAULT_AUTO_SHOP_STATE_PATH: Path = Path("config") / "auto_shop_state.json"

# ---------------------------------------------------------------------------
# 1280x720 ROIs and fallback tap/swipe coordinates (verified on MuMu)
# ---------------------------------------------------------------------------

HQ_BALANCE_ROI: tuple[int, int, int, int] = (830, 88, 335, 52)
HQ_GRID_ROI: tuple[int, int, int, int] = (580, 145, 695, 505)
HQ_SCROLL_DOWN_SWIPE: tuple[int, int, int, int] = (900, 560, 900, 290)

EXCHANGE_LIST_ROI: tuple[int, int, int, int] = (580, 145, 695, 560)
EXCHANGE_SCROLL_DOWN_SWIPE: tuple[int, int, int, int] = (900, 560, 900, 320)

SHOP_POPUP_ROI: tuple[int, int, int, int] = (280, 160, 740, 430)
SHOP_POPUP_CANCEL_FALLBACK: tuple[int, int] = (349, 534)
SHOP_POPUP_CONFIRM_FALLBACK: tuple[int, int] = (983, 534)
SHOP_POPUP_MIN_FALLBACK: tuple[int, int] = (386, 377)
SHOP_POPUP_DEC_FALLBACK: tuple[int, int] = (447, 377)
SHOP_POPUP_INC_FALLBACK: tuple[int, int] = (826, 377)
SHOP_POPUP_MAX_FALLBACK: tuple[int, int] = (892, 377)

_DIGIT_CONFUSIONS = str.maketrans({
    "O": "0",
    "o": "0",
    "I": "1",
    "l": "1",
    "|": "1",
})

PERIOD_KEYS: tuple[str, ...] = ("daily", "weekly", "monthly")


@dataclass(frozen=True)
class ShopBuyRule:
    """Single user-configured priority purchase rule."""

    raw: str
    item_name: str
    period: str | None = None
    currency: str | None = None
    max_buy: int | None = None
    pin_top: bool = False


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


def _slice_720(image: Any, x1: int, y1: int, x2: int, y2: int) -> np.ndarray | None:
    if not isinstance(image, np.ndarray) or image.ndim < 2 or image.shape[0] <= 0 or image.shape[1] <= 0:
        return None
    h, w = image.shape[:2]
    sx = w / 1280.0
    sy = h / 720.0
    ix1 = max(0, min(w - 1, int(round(x1 * sx))))
    ix2 = max(ix1 + 1, min(w, int(round(x2 * sx))))
    iy1 = max(0, min(h - 1, int(round(y1 * sy))))
    iy2 = max(iy1 + 1, min(h, int(round(y2 * sy))))
    return image[iy1:iy2, ix1:ix2]


# ---------------------------------------------------------------------------
# Rule & name normalization
# ---------------------------------------------------------------------------

def _cjk_count(text: Any) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", str(text or "")))


def normalize_shop_item_name(text: Any) -> str:
    """Normalize shop item names by stripping quotes, spaces, trailing '×N', and width variants."""
    cleaned = _clean(text)
    cleaned = (
        cleaned.replace("（", "(")
        .replace("）", ")")
        .replace("“", "")
        .replace("”", "")
        .replace('"', "")
        .replace("'", "")
    )
    cleaned = re.sub(r"[×xX]\d+$", "", cleaned)
    return cleaned


def shop_item_name_matches(ocr_name: Any, rule_name: Any) -> bool:
    """Match an OCR item name against a configured rule name, tolerating 1-char edge clips on long names."""
    ocr_norm = normalize_shop_item_name(ocr_name)
    rule_norm = normalize_shop_item_name(rule_name)
    if not ocr_norm or not rule_norm:
        return False
    if ocr_norm == rule_norm:
        return True
    if len(rule_norm) >= 6 and ocr_norm in rule_norm and len(ocr_norm) >= len(rule_norm) - 1:
        return True
    # Also tolerate single leading/trailing OCR misread on long names (e.g. '寺殊...' vs '特殊...').
    if len(rule_norm) >= 6 and len(ocr_norm) == len(rule_norm) and ocr_norm[1:] == rule_norm[1:]:
        return True
    return False


def _parse_period_tag(tag: str) -> str | None:
    t = _clean(tag).lower()
    if t in ("日", "每日", "当日", "daily", "day", "d"):
        return "daily"
    if t in ("周", "每周", "本周", "weekly", "week", "w"):
        return "weekly"
    if t in ("月", "每月", "本月", "monthly", "month", "m"):
        return "monthly"
    return None


def _parse_currency_tag(tag: str) -> str | None:
    t = _clean(tag).lower()
    if t in ("铁盟币", "金币", "gold", "coin"):
        return "gold"
    if t in ("采购券", "黑月采购券", "券", "ticket"):
        return "ticket"
    if t in ("桦石", "huashi", "stone", "crystal"):
        return "huashi"
    return None


def _strip_max_buy_suffix(text: str) -> tuple[str, int | None]:
    m = re.search(r"\s*[*＊xX×]\s*([1-9]\d*)$", text)
    if m is None:
        return text, None
    return text[: m.start()].strip(), int(m.group(1))


def parse_shop_buy_rules(raw_text: Any, *, default_currency: str | None = None) -> list[ShopBuyRule]:
    """Parse comma/semicolon/newline-separated priority item rules.

    Supports ``^`` prefix (explicit pin-to-top), suffixes ``:日/:周/:月``, ``@铁盟币/@采购券``,
    and quantity limit suffix ``*N`` / ``xN`` / ``×N``. Any explicit ``@桦石`` rule is rejected.
    """
    text = str(raw_text or "").strip()
    if not text:
        return []
    rules: list[ShopBuyRule] = []
    for token in re.split(r"[,，;；\n]+", text):
        raw_token = token.strip()
        if not raw_token:
            continue
        pin_top = False
        body = raw_token
        while body.startswith(("^", "＾")):
            pin_top = True
            body = body[1:].strip()
        if not body:
            continue
        max_buy: int | None = None
        body, parsed_max = _strip_max_buy_suffix(body)
        if parsed_max is not None:
            max_buy = parsed_max

        currency = default_currency
        if "@" in body:
            body, cur_part = body.rsplit("@", 1)
            parsed_cur = _parse_currency_tag(cur_part)
            if parsed_cur == "huashi":
                # Never allow currency=huashi purchases.
                continue
            if parsed_cur is not None:
                currency = parsed_cur
            if max_buy is None:
                body, parsed_max = _strip_max_buy_suffix(body)
                if parsed_max is not None:
                    max_buy = parsed_max

        period: str | None = None
        for sep in (":", "："):
            if sep in body:
                left, right = body.rsplit(sep, 1)
                parsed_period = _parse_period_tag(right)
                if parsed_period is not None:
                    body = left
                    period = parsed_period
                    if max_buy is None:
                        body, parsed_max = _strip_max_buy_suffix(body)
                        if parsed_max is not None:
                            max_buy = parsed_max
                    break

        item_name = normalize_shop_item_name(body)
        if not item_name:
            continue
        rules.append(
            ShopBuyRule(
                raw=raw_token,
                item_name=item_name,
                period=period,
                currency=currency,
                max_buy=max_buy,
                pin_top=pin_top,
            )
        )
    return rules


def compute_rule_remaining_quota(
    rule: ShopBuyRule,
    *,
    remaining: int | None,
    limit_total: int | None = None,
) -> int | None:
    """Compute remaining buyable quantity under ``rule.max_buy``."""
    if rule.max_buy is None:
        return remaining
    cap = max(0, int(rule.max_buy))
    if limit_total is not None and limit_total > 0 and remaining is not None:
        rem = max(0, int(remaining))
        already_bought = max(0, int(limit_total) - rem)
        return min(rem, max(0, cap - already_bought))
    if remaining is not None:
        return min(max(0, int(remaining)), cap)
    return cap


_PERIOD_LABELS: dict[str, str] = {
    "daily": "日",
    "weekly": "周",
    "monthly": "月",
}

_CURRENCY_LABELS: dict[str, str] = {
    "gold": "铁盟币",
    "ticket": "采购券",
}


def format_shop_buy_rules(rules: list[ShopBuyRule], *, default_currency: str | None = None) -> str:
    """Format parsed purchase rules into a canonical comma-separated signature string."""
    parts: list[str] = []
    for rule in rules:
        part = rule.item_name
        period_tag = _PERIOD_LABELS.get(str(rule.period or ""))
        if period_tag:
            part = f"{part}:{period_tag}"
        if rule.currency and rule.currency != default_currency:
            cur_tag = _CURRENCY_LABELS.get(rule.currency)
            if cur_tag:
                part = f"{part}@{cur_tag}"
        if rule.max_buy is not None:
            part = f"{part}*{rule.max_buy}"
        parts.append(part)
    return ", ".join(parts)


def resolve_shop_buy_rules(
    params: dict[str, Any],
    *,
    pick_prefix: str,
    extra_key: str,
    legacy_key: str,
    ui_configured_key: str,
    default_items: str,
    default_currency: str | None = None,
) -> list[ShopBuyRule]:
    """Resolve priority purchase rules from checkbox picks, extra input, or legacy list."""
    ui_configured = bool(params.get(ui_configured_key))
    extra_raw = str(params.get(extra_key) or "").strip()
    picked_entries = sorted(
        (str(key), str(val).strip())
        for key, val in params.items()
        if str(key).startswith(pick_prefix) and val is not None and not isinstance(val, bool) and str(val).strip()
    )

    if legacy_key in params and not ui_configured and not picked_entries and not extra_raw:
        return parse_shop_buy_rules(params.get(legacy_key), default_currency=default_currency)

    if ui_configured or picked_entries or extra_raw:
        dedup_picked: list[ShopBuyRule] = []
        picked_keys: set[tuple[str, str | None, str | None]] = set()
        for _key, raw_item in picked_entries:
            for rule in parse_shop_buy_rules(raw_item, default_currency=default_currency):
                dedup_key = (rule.item_name, rule.period, rule.currency)
                if dedup_key not in picked_keys:
                    picked_keys.add(dedup_key)
                    dedup_picked.append(rule)

        extra_rules = parse_shop_buy_rules(extra_raw, default_currency=default_currency)
        pinned_rules: list[ShopBuyRule] = []
        pinned_keys: set[tuple[str, str | None, str | None]] = set()
        in_place_overrides: dict[tuple[str, str | None, str | None], ShopBuyRule] = {}
        append_rules: list[ShopBuyRule] = []
        append_keys: set[tuple[str, str | None, str | None]] = set()

        for rule in extra_rules:
            dedup_key = (rule.item_name, rule.period, rule.currency)
            if rule.pin_top:
                if dedup_key not in pinned_keys:
                    pinned_keys.add(dedup_key)
                    pinned_rules.append(rule)
            elif dedup_key in picked_keys:
                if dedup_key not in pinned_keys:
                    in_place_overrides.setdefault(dedup_key, rule)
            else:
                if dedup_key not in append_keys:
                    append_keys.add(dedup_key)
                    append_rules.append(rule)

        merged: list[ShopBuyRule] = []
        seen: set[tuple[str, str | None, str | None]] = set()
        for rule in pinned_rules:
            dedup_key = (rule.item_name, rule.period, rule.currency)
            seen.add(dedup_key)
            merged.append(rule)
        for rule in dedup_picked:
            dedup_key = (rule.item_name, rule.period, rule.currency)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            merged.append(in_place_overrides.get(dedup_key, rule))
        for rule in append_rules:
            dedup_key = (rule.item_name, rule.period, rule.currency)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            merged.append(rule)
        return merged

    return parse_shop_buy_rules(default_items, default_currency=default_currency)


def parse_reserve_amount(raw_value: Any, default: int = 0) -> int:
    """Parse currency reserve threshold safely (>= 0)."""
    parsed = parse_compact_number(raw_value)
    if parsed is None or parsed < 0:
        return max(0, int(default))
    return parsed


# ---------------------------------------------------------------------------
# Numeric, limit, and currency parsers
# ---------------------------------------------------------------------------

def parse_compact_number(text: Any) -> int | None:
    """Parse integers or compact suffixes like '30.3k', '33.6m', '1.5w', '50万'."""
    cleaned = _clean(text).translate(_DIGIT_CONFUSIONS).replace(",", "")
    if not cleaned:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*([kKmMwW万]?)", cleaned)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "k":
        return int(round(val * 1000))
    if unit == "m":
        return int(round(val * 1000000))
    if unit in ("w", "万"):
        return int(round(val * 10000))
    return int(round(val))


def parse_exchange_cost_pair(text: Any) -> tuple[int, int] | None:
    """Parse the first 'balance/cost' pair such as '30.3k/150'."""
    pairs = parse_exchange_cost_pairs(text)
    return pairs[0] if pairs else None


def parse_exchange_cost_pairs(text: Any) -> list[tuple[int, int]]:
    """Parse one or more 'balance/cost' pairs from an exchange cost OCR string."""
    raw = re.sub(
        r"(?<=\d),(?=\d)",
        "",
        str(text or "").strip().translate(_DIGIT_CONFUSIONS),
    )
    if not raw:
        return []
    out: list[tuple[int, int]] = []
    for m in re.finditer(r"(\d+(?:\.\d+)?\s*[kKmMwW万]?)\s*/\s*(\d+(?:\.\d+)?\s*[kKmMwW万]?)", raw):
        bal = parse_compact_number(m.group(1))
        cost = parse_compact_number(m.group(2))
        if bal is not None and cost is not None and cost > 0:
            out.append((bal, cost))
    return out


def parse_hq_limit_badge(text: Any) -> tuple[str, int, int] | None:
    """Parse HQ limit badge like '每日限购5/5', '每周限购0/3' (including OCR typo '每固'), '每月限购4/4'."""
    cleaned = _clean(text).translate(_DIGIT_CONFUSIONS)
    m = re.search(r"每([日周固月])限购(\d+)/(\d+)", cleaned)
    if not m:
        return None
    ch = m.group(1)
    period = "daily" if ch == "日" else "monthly" if ch == "月" else "weekly"
    return period, int(m.group(2)), int(m.group(3))


def parse_exchange_limit_badge(text: Any) -> tuple[str, int] | None:
    """Parse exchange shop limit text into ('daily'|'weekly'|'monthly'|'account', remaining)."""
    cleaned = _clean(text).translate(_DIGIT_CONFUSIONS)
    if "已兑换完" in cleaned or "已售罄" in cleaned or "已售馨" in cleaned:
        return "soldout", 0
    m = re.search(r"(当日|每日|本周|每周|本月|每月)?剩余(\d+)次", cleaned)
    if not m:
        return None
    prefix = m.group(1) or ""
    rem = int(m.group(2))
    if prefix in ("当日", "每日"):
        return "daily", rem
    if prefix in ("本周", "每周"):
        return "weekly", rem
    if prefix in ("本月", "每月"):
        return "monthly", rem
    return "account", rem


def classify_hq_currency_patch(
    bgr_image: Any,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    dimmed: bool = False,
) -> str:
    """Classify HQ price icon patch into 'gold', 'ticket', or 'huashi_or_unknown'."""
    patch = _slice_720(bgr_image, x1, y1, x2, y2)
    if patch is None or patch.size == 0:
        return "huashi_or_unknown"
    b = patch[:, :, 0].astype(np.float32)
    g = patch[:, :, 1].astype(np.float32)
    r = patch[:, :, 2].astype(np.float32)
    gold_ratio = float(np.mean((r > 165) & (g > 120) & (b < 95) & ((r - b) > 80)))
    purple_ratio = float(np.mean((b > 135) & (r > 95) & ((b - g) > 30)))
    if gold_ratio >= 0.04 and purple_ratio < 0.03:
        return "gold"
    if purple_ratio >= 0.06 and gold_ratio < 0.03:
        return "ticket"
    if dimmed:
        dim_gold = float(np.mean((r > 80) & (g > 55) & (b < 65) & ((r - b) > 30)))
        dim_purple = float(np.mean((b > 75) & (r > 55) & ((b - g) > 18)))
        if dim_gold >= 0.04 and dim_purple < 0.03:
            return "gold"
        if dim_purple >= 0.05 and dim_gold < 0.03:
            return "ticket"
    return "huashi_or_unknown"


def classify_fuming_medal_slot(bgr_image: Any, cost_box: tuple[int, int, int, int] | None) -> str:
    """Classify the Fuming medal icon directly above a cost text box ('purple_medal' | 'gold_medal' | 'unknown')."""
    if cost_box is None or not isinstance(bgr_image, np.ndarray):
        return "unknown"
    cx, cy, _cw, _ch = cost_box
    ribbon = _slice_720(bgr_image, cx + 5, max(0, cy - 78), cx + 60, max(1, cy - 50))
    glow = _slice_720(bgr_image, cx + 5, max(0, cy - 28), cx + 60, max(1, cy - 4))
    if ribbon is None or glow is None or ribbon.size == 0 or glow.size == 0:
        return "unknown"

    rb, rg, rr = ribbon[:, :, 0].astype(np.float32), ribbon[:, :, 1].astype(np.float32), ribbon[:, :, 2].astype(np.float32)
    gb, gg, gr = glow[:, :, 0].astype(np.float32), glow[:, :, 1].astype(np.float32), glow[:, :, 2].astype(np.float32)

    orange_ribbon = float(np.mean((rr > 185) & (rg > 95) & (rg < 185) & (rb < 85)))
    blue_ribbon = float(np.mean((rb > 140) & (rr < 115) & ((rb - rr) > 35)))
    yellow_glow = float(np.mean((gr > 155) & (gg > 120) & (gb < 95) & ((gr - gb) > 65)))
    purple_glow = float(np.mean((gb > 130) & (gr > 90) & ((gb - gg) > 25)))

    purple_score = blue_ribbon + purple_glow
    gold_score = orange_ribbon + yellow_glow
    if purple_score >= 0.08 and gold_score < 0.06:
        return "purple_medal"
    if gold_score >= 0.08 and purple_score < 0.06:
        return "gold_medal"
    if purple_score > gold_score and purple_score >= 0.06:
        return "purple_medal"
    if gold_score > purple_score and gold_score >= 0.06:
        return "gold_medal"
    return "unknown"


# ---------------------------------------------------------------------------
# Shelf & Popup Parsers
# ---------------------------------------------------------------------------

def parse_hq_balances(entries: list[dict[str, Any]]) -> dict[str, int | None]:
    """Extract HQ shop top-bar balances {'ticket': int|None, 'gold': int|None}."""
    ticket: int | None = None
    gold: int | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text")).translate(_DIGIT_CONFUSIONS).replace(",", "")
        if not re.fullmatch(r"\d+", cleaned):
            continue
        center = _entry_center(entry)
        if center is None:
            continue
        val = int(cleaned)
        if center[0] < 985:
            ticket = val
        else:
            gold = val
    return {"ticket": ticket, "gold": gold}


def _is_hq_noise_text(cleaned: str) -> bool:
    if not cleaned:
        return True
    upper = cleaned.upper()
    if upper in ("SOLDOUT", "UNITOFGOODS", "RESTAREA", "Q", "C", "O", "X"):
        return True
    if "已售" in cleaned:
        return True
    if re.fullmatch(r"\d{1,3}%", upper) or "OFF" in upper:
        return True
    return False


def parse_hq_shop_cards(
    entries: list[dict[str, Any]],
    bgr_image: Any = None,
) -> list[dict[str, Any]]:
    """Parse visible 2-column HQ shop cards into structured items with period, currency, and tap point."""
    parsed_items: list[dict[str, Any]] = []
    # Split entries into columns: col 0 (x < 925), col 1 (x >= 925)
    for col_idx in (0, 1):
        col_entries: list[tuple[tuple[int, int, int, int], tuple[int, int], str]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            box = _entry_box(entry)
            center = _entry_center(entry)
            if box is None or center is None:
                continue
            cx, cy = center
            if col_idx == 0 and cx >= 925:
                continue
            if col_idx == 1 and cx < 925:
                continue
            if cy < 155 or cy > 645:
                continue
            cleaned = _clean(entry.get("text"))
            if not cleaned:
                continue
            col_entries.append((box, center, cleaned))

        # Identify candidate item-name anchors (contain >= 2 CJK chars, or parenthesized fragment like '（4钛）')
        name_rows: list[tuple[int, int, tuple[int, int, int, int], str]] = []
        name_min_x = 740 if col_idx == 0 else 1070
        for box, (cx, cy), cleaned in col_entries:
            if _is_hq_noise_text(cleaned) or parse_hq_limit_badge(cleaned) is not None:
                continue
            cjk_len = _cjk_count(cleaned)
            is_name_frag = cjk_len >= 2 or (("(" in cleaned or "（" in cleaned) and cjk_len >= 1)
            if is_name_frag and cx >= name_min_x and 172 <= cy <= 622:
                name_rows.append((cy, cx, box, cleaned))

        # Group same-line name fragments like '星云物质' + '（8钛）'
        name_rows.sort(key=lambda item: (item[0], item[1]))
        merged_names: list[dict[str, Any]] = []
        for cy, cx, box, text in name_rows:
            if merged_names and abs(cy - merged_names[-1]["cy"]) <= 14:
                merged_names[-1]["parts"].append((cx, text))
                merged_names[-1]["cy"] = int(round((merged_names[-1]["cy"] + cy) / 2.0))
            else:
                merged_names.append({"cy": cy, "cx": cx, "parts": [(cx, text)]})

        for group in merged_names:
            group["parts"].sort(key=lambda p: p[0])
            item_name = normalize_shop_item_name("".join(p[1] for p in group["parts"]))
            if _cjk_count(item_name) < 2:
                continue
            name_cy = group["cy"]
            period: str | None = None
            remaining: int | None = None
            limit_total: int | None = None
            sold_out = False
            unit_cost: int | None = None
            price_box: tuple[int, int, int, int] | None = None

            for box, (cx, cy), cleaned in col_entries:
                badge = parse_hq_limit_badge(cleaned)
                if badge is not None and -42 <= (cy - name_cy) <= -8:
                    period, remaining, limit_total = badge
                    continue
                if ("已售" in cleaned or "SOLDOUT" in cleaned.upper()) and -25 <= (cy - name_cy) <= 55:
                    sold_out = True
                    continue
                digits_str = cleaned.translate(_DIGIT_CONFUSIONS).replace(",", "")
                m_price = re.fullmatch(r"[^\d/\s]?(\d+)", digits_str)
                # Price sits below the item name on the right side of the card.
                if (
                    m_price is not None
                    and 14 <= (cy - name_cy) <= 58
                    and cx >= (800 if col_idx == 0 else 1130)
                ):
                    parsed_cost = int(m_price.group(1))
                    if unit_cost is None or parsed_cost > 0:
                        unit_cost = parsed_cost
                        price_box = box

            if remaining is not None and remaining <= 0:
                sold_out = True

            if price_box is not None:
                px, py, _pw, ph = price_box
                patch_bounds = (px - 32, py - 4, px + 22, py + max(24, ph + 8))
            else:
                # Fallback price icon zone when OCR misses single-digit price (e.g. '2' or '4').
                base_x = 875 if col_idx == 0 else 1205
                patch_bounds = (base_x - 32, name_cy + 14, base_x + 22, name_cy + 52)

            currency = "huashi_or_unknown"
            if isinstance(bgr_image, np.ndarray):
                currency = classify_hq_currency_patch(bgr_image, *patch_bounds, dimmed=False)
                if sold_out and currency == "huashi_or_unknown":
                    currency = classify_hq_currency_patch(bgr_image, *patch_bounds, dimmed=True)
            if sold_out and currency == "huashi_or_unknown" and unit_cost is not None and unit_cost >= 1000:
                currency = "gold"

            tap_x = 780 if col_idx == 0 else 1110
            parsed_items.append(
                {
                    "name": item_name,
                    "period": period or "unlimited",
                    "remaining": remaining,
                    "limit_total": limit_total,
                    "sold_out": sold_out,
                    "unit_cost": unit_cost,
                    "currency": currency,
                    "tap_point": (tap_x, name_cy),
                    "col": col_idx,
                    "cy": name_cy,
                }
            )

    parsed_items.sort(key=lambda item: (item["cy"], item["col"]))
    return parsed_items


def parse_exchange_shop_rows(
    entries: list[dict[str, Any]],
    bgr_image: Any = None,
    *,
    classify_medal: bool = False,
) -> list[dict[str, Any]]:
    """Parse vertical EXCHANGE STATION rows (Fuming Shop / Chamber Mileage)."""
    norm_entries: list[tuple[tuple[int, int, int, int], tuple[int, int], str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        box = _entry_box(entry)
        center = _entry_center(entry)
        if box is None or center is None:
            continue
        raw = str(entry.get("text") or "").strip()
        if not raw:
            continue
        norm_entries.append((box, center, raw))

    # Item names live in x in [620..810] and contain CJK (excluding '已兑换完').
    anchors: list[tuple[int, str]] = []
    for _box, (cx, cy), raw in norm_entries:
        if not (620 <= cx <= 810 and 190 <= cy <= 670):
            continue
        cleaned = _clean(raw)
        if "已兑换完" in cleaned or "已售" in cleaned:
            continue
        if re.search(r"[\u4e00-\u9fff]", cleaned):
            anchors.append((cy, normalize_shop_item_name(cleaned)))

    anchors.sort(key=lambda item: item[0])
    # Deduplicate close anchors on the same row.
    dedup_anchors: list[tuple[int, str]] = []
    for cy, name in anchors:
        if _cjk_count(name) < 2:
            continue
        if dedup_anchors and abs(cy - dedup_anchors[-1][0]) <= 24:
            continue
        dedup_anchors.append((cy, name))

    rows: list[dict[str, Any]] = []
    for name_cy, item_name in dedup_anchors:
        period = "unlimited"
        remaining: int | None = None
        sold_out = False
        exchange_btn_pt: tuple[int, int] | None = None
        cost_entries: list[tuple[int, tuple[int, int, int, int], tuple[int, int]]] = []
        incomplete_cost = False

        for box, (cx, cy), raw in norm_entries:
            cleaned = _clean(raw)
            if "已兑换完" in cleaned and -65 <= (cy - name_cy) <= 15:
                sold_out = True
                continue
            badge = parse_exchange_limit_badge(cleaned)
            if badge is not None and cx >= 1110 and abs(cy - name_cy) <= 22:
                b_period, b_rem = badge
                if b_period == "soldout":
                    sold_out = True
                else:
                    period = b_period
                    remaining = b_rem
                    if b_rem <= 0:
                        sold_out = True
                continue
            if cx >= 1110 and -82 <= (cy - name_cy) <= -14 and "EXCHANGE" in cleaned.upper():
                exchange_btn_pt = (cx, cy)
                continue
            if 805 <= cx <= 1115 and -24 <= (cy - name_cy) <= 26:
                # Preserve spaces separating two currencies in a single OCR box.
                pairs = parse_exchange_cost_pairs(raw)
                if len(pairs) != raw.count("/") or (not pairs and re.search(r"\d", raw)):
                    incomplete_cost = True
                for idx_p, (bal, cost) in enumerate(pairs):
                    sub_box = (box[0] + idx_p * 88, box[1], max(60, box[2] // max(1, len(pairs))), box[3])
                    cost_entries.append((cx + idx_p * 88, sub_box, (bal, cost)))

        cost_entries.sort(key=lambda item: item[0])
        costs: list[dict[str, Any]] = []
        for _cx, cbox, (bal, cost) in cost_entries:
            medal = classify_fuming_medal_slot(bgr_image, cbox) if classify_medal else "mileage"
            costs.append({"balance": bal, "unit_cost": cost, "medal": medal})

        # A second medal icon can survive OCR even when its balance/cost text disappears.
        if classify_medal and len(cost_entries) == 1:
            _, (x, y, w, h), _ = cost_entries[0]
            for adjacent_x in (x - 88, x + 88):
                if 805 <= adjacent_x + w // 2 <= 1115:
                    adjacent_medal = classify_fuming_medal_slot(bgr_image, (adjacent_x, y, w, h))
                    if adjacent_medal != "unknown" and adjacent_medal != costs[0]["medal"]:
                        incomplete_cost = True

        if exchange_btn_pt is None:
            exchange_btn_pt = (1177, max(150, name_cy - 48))

        rows.append(
            {
                "name": item_name,
                "period": period,
                "remaining": remaining,
                "sold_out": sold_out,
                "costs": [] if incomplete_cost else costs,
                "exchange_point": exchange_btn_pt,
                "cy": name_cy,
            }
        )
    return rows


def parse_shop_confirm_popup(
    entries: list[dict[str, Any]],
    bgr_image: Any = None,
    *,
    shop_kind: str = "hq",
) -> dict[str, Any] | None:
    """Parse quantity & price confirmation modal for HQ shop or Exchange shop."""
    cancel_pt: tuple[int, int] | None = None
    confirm_pt: tuple[int, int] | None = None
    min_pt: tuple[int, int] | None = None
    dec_pt: tuple[int, int] | None = None
    inc_pt: tuple[int, int] | None = None
    max_pt: tuple[int, int] | None = None
    cur_qty: int | None = None
    max_qty: int | None = None
    price: int | None = None
    hq_price_box: tuple[int, int, int, int] | None = None
    item_name: str = ""
    hq_name_candidates: list[str] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        box = _entry_box(entry)
        center = _entry_center(entry)
        if center is None:
            continue
        cx, cy = center
        cleaned = _clean(entry.get("text"))
        if not cleaned:
            continue

        if 495 <= cy <= 565:
            if "取消" in cleaned and cx < 640:
                cancel_pt = center
                continue
            if "确定" in cleaned and cx >= 640:
                confirm_pt = center
                continue

        if 345 <= cy <= 405:
            if cleaned == "最少":
                min_pt = center
                continue
            if cleaned in ("-1", "一1", "-I"):
                dec_pt = center
                continue
            if cleaned in ("+1", "+I", "十1"):
                inc_pt = center
                continue
            if cleaned == "最多":
                max_pt = center
                continue
            qty_m = re.fullmatch(r"(\d+)/(\d+)", cleaned.translate(_DIGIT_CONFUSIONS))
            if qty_m and 480 <= cx <= 800:
                cur_qty = int(qty_m.group(1))
                max_qty = int(qty_m.group(2))
                continue

        if shop_kind == "hq":
            if 420 <= cx <= 860 and 285 <= cy <= 340 and re.search(r"[\u4e00-\u9fff]", cleaned):
                hq_name_candidates.append(normalize_shop_item_name(cleaned))
            if 625 <= cx <= 860 and 425 <= cy <= 475:
                digits = cleaned.translate(_DIGIT_CONFUSIONS).replace(",", "")
                if re.fullmatch(r"\d+", digits):
                    price = int(digits)
                    hq_price_box = box
        else:
            if 320 <= cx <= 960 and 410 <= cy <= 475:
                m_ex = re.search(r"兑换(.+?)(?:[×xX]\d+)?吗", cleaned)
                if m_ex:
                    item_name = normalize_shop_item_name(m_ex.group(1))

    if cancel_pt is None or confirm_pt is None:
        return None

    if shop_kind == "hq" and hq_name_candidates:
        item_name = "".join(hq_name_candidates)

    currency = "unknown"
    if shop_kind == "hq" and isinstance(bgr_image, np.ndarray):
        if hq_price_box is not None:
            px, py, _pw, ph = hq_price_box
            currency = classify_hq_currency_patch(
                bgr_image,
                px - 40,
                py - 6,
                px + 8,
                py + max(28, ph + 8),
            )
        else:
            currency = classify_hq_currency_patch(bgr_image, 575, 430, 650, 472)

    return {
        "item_name": item_name,
        "cur_qty": cur_qty,
        "max_qty": max_qty,
        "price": price,
        "currency": currency,
        "min_pt": min_pt or SHOP_POPUP_MIN_FALLBACK,
        "dec_pt": dec_pt or SHOP_POPUP_DEC_FALLBACK,
        "inc_pt": inc_pt or SHOP_POPUP_INC_FALLBACK,
        "max_pt": max_pt or SHOP_POPUP_MAX_FALLBACK,
        "cancel_pt": cancel_pt or SHOP_POPUP_CANCEL_FALLBACK,
        "confirm_pt": confirm_pt or SHOP_POPUP_CONFIRM_FALLBACK,
    }


def plan_affordable_quantity(balance: int, reserve: int, unit_cost: int, max_qty: int) -> int:
    """Compute maximum affordable quantity without crossing ``reserve``."""
    if unit_cost <= 0 or max_qty <= 0:
        return 0
    budget = int(balance) - int(reserve)
    if budget < unit_cost:
        return 0
    return min(int(max_qty), budget // int(unit_cost))


def affordable_exchange_quantity(
    costs: list[dict[str, Any]],
    reserve: int,
    *,
    shop_kind: str,
    allow_gold_medal: bool,
) -> int:
    """Limit an exchange by every required currency; unknown or duplicate slots are ambiguous."""
    allowed = {"mileage"} if shop_kind == "chamber" else {"purple_medal"}
    if shop_kind == "fuming" and allow_gold_medal:
        allowed.add("gold_medal")
    limits: list[int] = []
    seen: set[str] = set()
    for slot in costs:
        medal = slot.get("medal")
        balance = slot.get("balance")
        unit_cost = slot.get("unit_cost")
        if medal not in allowed or medal in seen or not isinstance(balance, int):
            return 0
        if not isinstance(unit_cost, int) or unit_cost <= 0:
            return 0
        seen.add(medal)
        keep = 0 if medal == "gold_medal" else reserve
        limits.append(max(0, balance - keep) // unit_cost)
    return min(limits, default=0)


# ---------------------------------------------------------------------------
# ALAS-style per-UID schedule & persistence
# ---------------------------------------------------------------------------

def compute_next_refresh_time(now: datetime, period: str, reset_hour: int = 5) -> datetime:
    """Return the next game refresh timestamp strictly after ``now`` (05:00 boundary)."""
    today_reset = now.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
    if period == "weekly":
        days_since_mon = now.weekday()  # Monday = 0
        this_mon_reset = today_reset - timedelta(days=days_since_mon)
        return this_mon_reset + timedelta(days=7) if now >= this_mon_reset else this_mon_reset
    if period == "monthly":
        this_month_reset = today_reset.replace(day=1)
        if now < this_month_reset:
            return this_month_reset
        if now.month == 12:
            return this_month_reset.replace(year=now.year + 1, month=1, day=1)
        return this_month_reset.replace(month=now.month + 1, day=1)
    # Default: daily
    return today_reset + timedelta(days=1) if now >= today_reset else today_reset


def compute_shop_next_run(
    now: datetime,
    periods: set[str] | tuple[str, ...] | list[str],
    *,
    partial_due_to_budget: bool = False,
) -> datetime:
    """Choose the earliest upcoming refresh across observed/configured periods."""
    if partial_due_to_budget:
        return compute_next_refresh_time(now, "daily")
    valid = [p for p in periods if p in PERIOD_KEYS]
    if not valid:
        valid = ["daily"]
    return min(compute_next_refresh_time(now, p) for p in valid)


def compute_shop_config_hash(config_payload: dict[str, Any]) -> str:
    """Compute a short deterministic hash of a shop's configuration."""
    encoded = json.dumps(config_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def format_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_timestamp(text: Any) -> datetime | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def should_run_shop(
    state: dict[str, Any],
    uid: str,
    shop_key: str,
    config_hash: str,
    now: datetime,
    *,
    force_run: bool = False,
) -> tuple[bool, str]:
    """Return ``(should_run, reason_or_next_run_str)`` for a UID + shop."""
    if force_run:
        return True, "force"
    uid_key = str(uid or "default").strip() or "default"
    accounts = state.get("accounts")
    if not isinstance(accounts, dict):
        return True, "first_run"
    acct = accounts.get(uid_key)
    if not isinstance(acct, dict):
        return True, "first_run"
    record = acct.get(shop_key)
    if not isinstance(record, dict):
        return True, "first_run"
    if str(record.get("config_hash") or "") != str(config_hash):
        return True, "config_changed"
    next_run_str = str(record.get("next_run_at") or "").strip()
    next_run_dt = parse_timestamp(next_run_str)
    if next_run_dt is None:
        return True, "missing_timestamp"
    if now >= next_run_dt:
        return True, "due"
    return False, next_run_str


def update_shop_schedule_state(
    state: dict[str, Any],
    uid: str,
    shop_key: str,
    config_hash: str,
    now: datetime,
    next_run: datetime,
    *,
    summary: str = "",
) -> None:
    """Update per-UID shop scheduling entry in-place."""
    uid_key = str(uid or "default").strip() or "default"
    accounts = state.setdefault("accounts", {})
    if not isinstance(accounts, dict):
        accounts = {}
        state["accounts"] = accounts
    acct = accounts.setdefault(uid_key, {})
    if not isinstance(acct, dict):
        acct = {}
        accounts[uid_key] = acct
    acct[shop_key] = {
        "config_hash": str(config_hash),
        "last_run_at": format_timestamp(now),
        "next_run_at": format_timestamp(next_run),
        "summary": str(summary),
    }


def load_auto_shop_state(path: Path = DEFAULT_AUTO_SHOP_STATE_PATH) -> dict[str, Any]:
    """Load persisted AutoShop schedule state, returning empty structure if absent/corrupt."""
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("accounts"), dict):
                return data
    except Exception:
        pass
    return {"version": 1, "accounts": {}}


def save_auto_shop_state(path: Path, state: dict[str, Any]) -> None:
    """Persist AutoShop schedule state safely to UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)

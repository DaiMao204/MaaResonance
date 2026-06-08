from __future__ import annotations

import base64
import json
import os
import re
import struct
import zlib
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover - Maa 运行环境缺 numpy 时跳过模板识别。
    np = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESOURCES_PATH = PROJECT_ROOT / "resources"
PLANNER_MAX_PRESTIGE_LEVEL = 20
ROLE_RESONANCE_LEVELS = {0, 1, 2, 3, 4, 5}
CONFIG_ROLE_RESONANCE_LEVELS = {-1, 0, 1, 2, 3, 4, 5}
CREW_SAFE_NAME_Y_MIN = 280
CREW_SAFE_NAME_Y_MAX = 690
CREW_CARD_BASE_LEFTS = (16, 195, 375, 555, 735, 914, 1094)
CREW_CARD_BASE_WIDTH = 168
CREW_CARD_NAME_ROW_TO_TOP = 230
CREW_CARD_FULL_BADGE_FROM_RIGHT = (-78, -2)
CREW_CARD_FULL_BADGE_FROM_ROW_Y = (-250, -128)
CREW_CARD_TIGHT_BADGE_FROM_RIGHT = (-48, 6)
CREW_CARD_TIGHT_BADGE_FROM_ROW_Y = (-250, -150)
CREW_CARD_AWAKE_FROM_ROW_Y = (-250, -55)
CREW_TIGHT_RIGHT_BADGE_TEMPLATE_SIZE = (42, 80)
CREW_TIGHT_BADGE_TEMPLATE_MATCH_MIN = 0.58
CREW_TIGHT_BADGE_TEMPLATE_MATCH_MARGIN = 0.045
CREW_AWAKE_TEMPLATE_MATCH_MIN = 0.72
CREW_AWAKE_TEMPLATE_MATCH_MARGIN = 0.008
CREW_AWAKE_TEMPLATE_STRONG_MIN = 0.80
CREW_AWAKE_TEMPLATE_RELAXED_MIN = 0.70
CREW_AWAKE_TEMPLATE_RELAXED_MARGIN = 0.012
CREW_AWAKE_TEMPLATE_SCALES = (
    0.52,
    0.58,
    0.64,
    0.70,
    0.76,
    0.82,
    0.88,
    0.94,
    1.00,
    1.08,
)
CREW_AWAKE_SEARCH_PAD_X = 36
CREW_AWAKE_SEARCH_PAD_Y = 72
CREW_AWAKE_WIDE_MATCH_MAX_POSITIONS = 96
# A few card arts put the resonance mark against noisy character art. Keep the
# broader scan targeted so full runs do not fall back to slow matching for every card.
CREW_AWAKE_FULL_CARD_FALLBACK_ROLES = {"塞西尔", "真咲"}
CREW_NAME_EXCLUDE_KEYWORDS = (
    "乘员",
    "仓库",
    "获取",
    "时间",
    "筛选",
    "等级",
    "共振",
    "排序",
    "全部",
    "Lv",
    "LV",
)
CREW_SORT_TEXTS = ("获取时间", "获取时问", "获取時間")
ROLE_OCR_EQUIVALENTS = str.maketrans(
    {
        "鬃": "繁",
        "繁": "繁",
        "魔": "魇",
        "剎": "刹",
        "拉": "菈",
        "聯": "咲",
        "联": "咲",
        "唉": "咲",
        "集": "隼",
        "駒": "驹",
        "·": "",
        "・": "",
        " ": "",
    }
)
ROLE_OCR_ALIASES = {
    "拉姐": "拉妲",
    "狮": "狮鬃",
}
UNAVAILABLE_CITY_TEXTS = (
    "未开放",
    "暂未开放",
    "未解锁",
    "无法前往",
    "前往条件",
    "尚未开放",
)
AVAILABLE_CITY_TEXTS = (
    "前往目的地",
    "立即出发",
    "访问城市",
    "进入城市",
    "当前站点",
    "当前城市",
    "列车所在站",
)
CITY_DETAIL_PANEL_TEXTS = (
    "发展度",
    "声望",
    "交易品",
    "推荐等级",
    "路程",
)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def env_truthy(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def clean_text(text: str) -> str:
    return (
        str(text or "")
        .replace(" ", "")
        .replace(",", "")
        .replace("，", "")
        .replace("：", ":")
        .replace("O", "0")
        .replace("o", "0")
        .strip()
    )


def parse_account_uid(texts: list[str]) -> str | None:
    """Parse account UID from OCR texts around the main-map UID area."""
    joined = "".join(clean_text(text) for text in texts if str(text).strip())
    for pattern in (
        r"UID[:：]?(\d{4,})",
        r"U1D[:：]?(\d{4,})",
        r"ID[:：]?(\d{4,})",
    ):
        match = re.search(pattern, joined, re.I)
        if match:
            return match.group(1)
    digits = re.findall(r"\d{6,}", joined)
    return digits[0] if digits else None


def parse_cargo_capacity(texts: list[str]) -> int | None:
    """Parse max cargo capacity from OCR texts such as 13/545 or 011096."""
    slash_candidates: list[int] = []
    inferred_candidates: list[int] = []
    for text in texts:
        cleaned = clean_text(text)
        for match in re.finditer(r"(\d+)\s*/\s*(\d+)", cleaned):
            slash_candidates.append(int(match.group(2)))
        digits = re.sub(r"\D+", "", cleaned)
        if not digits:
            continue
        value = int(digits)
        if 100 <= value <= 9999:
            inferred_candidates.append(value)
        if len(digits) < 4:
            continue
        # OCR sometimes drops the slash and merges used/max cargo, e.g. 0/1096
        # becomes 011096. Try every split and keep plausible max-capacity parts.
        for split in range(1, len(digits)):
            try:
                used = int(digits[:split])
                capacity = int(digits[split:])
            except ValueError:
                continue
            if 100 <= capacity <= 9999 and used <= capacity * 2:
                inferred_candidates.append(capacity)
    if slash_candidates:
        return max(slash_candidates)
    return min(inferred_candidates) if inferred_candidates else None


def normalize_role_text(text: str) -> str:
    cleaned = clean_text(text)
    return ROLE_OCR_ALIASES.get(cleaned, cleaned.translate(ROLE_OCR_EQUIVALENTS))


@lru_cache(maxsize=1)
def load_attached_to_city() -> dict[str, str]:
    data = read_json(RESOURCES_PATH / "goods" / "AttachedToCityData.json", {})
    if not isinstance(data, dict):
        return {}
    return {str(city): str(master) for city, master in data.items() if str(city).strip()}


def prestige_master_city(city_name: str | None) -> str | None:
    if not city_name:
        return None
    city = str(city_name).strip()
    return load_attached_to_city().get(city, city)


@lru_cache(maxsize=1)
def load_prestige_thresholds() -> dict[str, Any]:
    data = read_json(RESOURCES_PATH / "goods" / "CityPrestigeThresholds2026.json", {})
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def load_city_names() -> tuple[str, ...]:
    thresholds = load_prestige_thresholds()
    raw_cities = thresholds.get("cities") if isinstance(thresholds, dict) else {}
    names: set[str] = set()
    if isinstance(raw_cities, dict):
        for city in raw_cities:
            master = prestige_master_city(str(city).strip())
            if master:
                names.add(master)
    return tuple(sorted(names, key=len, reverse=True))


def parse_city_names_from_texts(
    texts: list[str],
    city_names: tuple[str, ...] | None = None,
) -> list[str]:
    city_names = city_names or load_city_names()
    cleaned_texts = [clean_text(text) for text in texts if str(text).strip()]
    result: list[str] = []
    for city in city_names:
        city_key = clean_text(city)
        if city_key and any(city_key in text for text in cleaned_texts):
            result.append(city)
    return result


@lru_cache(maxsize=1)
def load_role_names() -> tuple[str, ...]:
    data = read_json(RESOURCES_PATH / "goods" / "RoleCatalog2026.json", {})
    roles = data.get("roles") if isinstance(data, dict) else []
    if not isinstance(roles, list):
        return ()
    return tuple(str(role).strip() for role in roles if str(role).strip())


def crew_warehouse_readiness(
    texts: list[str],
    role_names: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    cleaned = [clean_text(text) for text in texts if clean_text(text)]
    joined = "".join(cleaned)
    header_hits = sum(1 for text in ("获取时间", "稀有度", "等级") if text in joined)

    names = tuple(role_names or load_role_names())
    role_hits: set[str] = set()
    normalized_texts = [normalize_role_text(text) for text in cleaned]
    for role in names:
        role_key = normalize_role_text(role)
        if role_key and any(role_key in text for text in normalized_texts):
            role_hits.add(role)

    lv_hits = sum(1 for text in cleaned if "LV" in text.upper() or re.search(r"等级\d+", text))
    star_hits = sum(1 for text in cleaned if "★" in text or "星级" in text)
    ready = bool(
        ("获取时间" in joined and header_hits >= 2)
        or (len(role_hits) >= 3 and (lv_hits >= 2 or star_hits >= 2))
        or len(role_hits) >= 5
    )
    return {
        "ready": ready,
        "header_hits": header_hits,
        "role_hits": sorted(role_hits)[:20],
        "role_hit_count": len(role_hits),
        "lv_hits": lv_hits,
        "star_hits": star_hits,
        "texts": cleaned[:24],
    }


@lru_cache(maxsize=1)
def load_role_resonance_max() -> dict[str, int]:
    data = read_json(RESOURCES_PATH / "goods" / "RoleCatalog2026.json", {})
    raw = data.get("resonance_max_by_role") if isinstance(data, dict) else {}
    if not isinstance(raw, dict):
        return {}
    result: dict[str, int] = {}
    for role, value in raw.items():
        role_name = str(role).strip()
        if not role_name:
            continue
        try:
            result[role_name] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def role_resonance_max(role: str | None) -> int | None:
    if not role:
        return None
    return load_role_resonance_max().get(str(role).strip())


def normalize_role_resonance_level(level: int | str | None, *, missing: int = 0) -> int:
    try:
        if level is None or level == "":
            return missing
        value = int(level)
    except (TypeError, ValueError):
        return missing
    if value in CONFIG_ROLE_RESONANCE_LEVELS:
        return value
    return 5 if value >= 5 else missing


def cap_role_resonance_level(role: str | None, level: int | str | None, *, missing: int = 0) -> int:
    value = normalize_role_resonance_level(level, missing=missing)
    max_level = role_resonance_max(role)
    if max_level is None or value < 0:
        return value
    return min(value, max_level)


@lru_cache(maxsize=1)
def load_tight_badge_templates() -> dict[int, list[Any]]:
    if np is None:
        return {}
    data = read_json(RESOURCES_PATH / "goods" / "CrewTightBadgeTemplates2026.json", {})
    raw_templates = data.get("templates") if isinstance(data, dict) else {}
    if not isinstance(raw_templates, dict):
        return {}

    width, height = CREW_TIGHT_RIGHT_BADGE_TEMPLATE_SIZE
    bit_count = width * height
    byte_count = (bit_count + 7) // 8
    expected_len = ((byte_count + 2) // 3) * 4
    templates: dict[int, list[Any]] = {}
    for raw_level, encoded_items in raw_templates.items():
        try:
            level = int(raw_level)
        except (TypeError, ValueError):
            continue
        if level not in {4, 5} or not isinstance(encoded_items, list):
            continue
        for encoded in encoded_items:
            if not isinstance(encoded, str):
                continue
            if len(encoded) < expected_len:
                encoded = ("A" * (expected_len - len(encoded))) + encoded
            try:
                raw = base64.b64decode(encoded + ("=" * (-len(encoded) % 4)))
            except ValueError:
                continue
            if len(raw) * 8 < bit_count:
                continue
            bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:bit_count]
            template = bits.reshape((height, width)).astype(np.float32)
            template[int(height * 0.32) : int(height * 0.58), :] = 0
            templates.setdefault(level, []).append(template)
    return templates


def _paeth_predictor(left: int, up: int, upper_left: int) -> int:
    p = left + up - upper_left
    pa = abs(p - left)
    pb = abs(p - up)
    pc = abs(p - upper_left)
    if pa <= pb and pa <= pc:
        return left
    if pb <= pc:
        return up
    return upper_left


def _decode_png_pixels(encoded: str) -> Any | None:
    if np is None:
        return None
    try:
        raw = base64.b64decode(encoded)
    except (TypeError, ValueError):
        return None
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return None

    offset = 8
    width = height = bit_depth = color_type = interlace = None
    idat_chunks: list[bytes] = []
    while offset + 8 <= len(raw):
        length = int.from_bytes(raw[offset : offset + 4], "big")
        chunk_type = raw[offset + 4 : offset + 8]
        chunk_data = raw[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    if not width or not height or bit_depth != 8 or interlace not in {0, 1} or color_type not in {0, 2, 4, 6}:
        return None
    channel_count = {0: 1, 2: 3, 4: 2, 6: 4}[int(color_type)]
    try:
        inflated = zlib.decompress(b"".join(idat_chunks))
    except zlib.error:
        return None
    cursor = 0

    def read_pass_rows(pass_width: int, pass_height: int) -> Any | None:
        nonlocal cursor
        if pass_width <= 0 or pass_height <= 0:
            return None
        row_size = pass_width * channel_count
        rows: list[bytes] = []
        previous = bytearray(row_size)
        for _ in range(pass_height):
            if cursor + 1 + row_size > len(inflated):
                return None
            filter_type = inflated[cursor]
            cursor += 1
            current = bytearray(inflated[cursor : cursor + row_size])
            cursor += row_size
            for index in range(row_size):
                left = current[index - channel_count] if index >= channel_count else 0
                up = previous[index]
                upper_left = previous[index - channel_count] if index >= channel_count else 0
                if filter_type == 1:
                    current[index] = (current[index] + left) & 0xFF
                elif filter_type == 2:
                    current[index] = (current[index] + up) & 0xFF
                elif filter_type == 3:
                    current[index] = (current[index] + ((left + up) // 2)) & 0xFF
                elif filter_type == 4:
                    current[index] = (current[index] + _paeth_predictor(left, up, upper_left)) & 0xFF
                elif filter_type != 0:
                    return None
            rows.append(bytes(current))
            previous = current
        return np.frombuffer(b"".join(rows), dtype=np.uint8).reshape((pass_height, pass_width, channel_count))

    if interlace == 0:
        array = read_pass_rows(int(width), int(height))
        if array is None:
            return None
    else:
        array = np.zeros((int(height), int(width), channel_count), dtype=np.uint8)
        for start_x, start_y, step_x, step_y in (
            (0, 0, 8, 8),
            (4, 0, 8, 8),
            (0, 4, 4, 8),
            (2, 0, 4, 4),
            (0, 2, 2, 4),
            (1, 0, 2, 2),
            (0, 1, 1, 2),
        ):
            pass_width = 0 if int(width) <= start_x else (int(width) - start_x + step_x - 1) // step_x
            pass_height = 0 if int(height) <= start_y else (int(height) - start_y + step_y - 1) // step_y
            pass_array = read_pass_rows(pass_width, pass_height)
            if pass_array is None:
                continue
            ys = start_y + np.arange(pass_height) * step_y
            xs = start_x + np.arange(pass_width) * step_x
            array[ys[:, None], xs[None, :], :] = pass_array

    if color_type == 6:
        return array
    if color_type == 2:
        alpha = np.full((int(height), int(width), 1), 255, dtype=np.uint8)
        return np.concatenate([array, alpha], axis=2)
    if color_type == 4:
        gray = array[:, :, :1]
        alpha = array[:, :, 1:2]
        return np.concatenate([gray, gray, gray, alpha], axis=2)
    gray = array[:, :, :1]
    alpha = np.full((int(height), int(width), 1), 255, dtype=np.uint8)
    return np.concatenate([gray, gray, gray, alpha], axis=2)


def _gray_alpha_from_png(encoded: str) -> tuple[Any, Any] | None:
    image = _decode_png_pixels(encoded)
    if image is None or image.size == 0:
        return None
    gray = image[:, :, :3].astype(np.float32).mean(axis=2)
    alpha = image[:, :, 3].astype(np.float32)
    mask = alpha > 18
    if int(mask.sum()) <= 0:
        return None
    ys, xs = np.where(mask)
    y1, y2 = max(0, int(ys.min()) - 1), min(image.shape[0], int(ys.max()) + 2)
    x1, x2 = max(0, int(xs.min()) - 1), min(image.shape[1], int(xs.max()) + 2)
    return gray[y1:y2, x1:x2], mask[y1:y2, x1:x2].astype(np.float32)


def _resize_nearest(mask: Any, width: int, height: int) -> Any:
    if np is None or mask.size == 0:
        return None
    src_h, src_w = mask.shape[:2]
    if src_h <= 0 or src_w <= 0:
        return None
    ys = np.clip(np.linspace(0, src_h - 1, height).round().astype(int), 0, src_h - 1)
    xs = np.clip(np.linspace(0, src_w - 1, width).round().astype(int), 0, src_w - 1)
    return mask[ys][:, xs]


@lru_cache(maxsize=1)
def load_awake_icon_templates() -> dict[int, list[tuple[float, Any, Any]]]:
    if np is None:
        return {}
    data = read_json(RESOURCES_PATH / "goods" / "CrewAwakeIconTemplates2026.json", {})
    raw_icons = data.get("icons") if isinstance(data, dict) else {}
    if not isinstance(raw_icons, dict):
        return {}

    templates: dict[int, list[tuple[float, Any, Any]]] = {}
    for raw_level, encoded in raw_icons.items():
        try:
            level = int(raw_level)
        except (TypeError, ValueError):
            continue
        if level not in ROLE_RESONANCE_LEVELS or not isinstance(encoded, str):
            continue
        decoded = _gray_alpha_from_png(encoded)
        if decoded is None:
            continue
        gray, mask = decoded
        height, width = gray.shape[:2]
        for scale in CREW_AWAKE_TEMPLATE_SCALES:
            scaled_w = int(round(width * scale))
            scaled_h = int(round(height * scale))
            if scaled_w < 18 or scaled_h < 18:
                continue
            resized_gray = _resize_nearest(gray, scaled_w, scaled_h)
            resized_mask = _resize_nearest(mask, scaled_w, scaled_h)
            if resized_gray is None or resized_mask is None or int(resized_mask.sum()) <= 0:
                continue
            templates.setdefault(level, []).append(
                (float(scale), resized_gray.astype(np.float32), (resized_mask > 0).astype(np.float32))
            )
    return templates


def _tight_badge_digit_mask(crop: Any) -> Any | None:
    if np is None or crop is None or getattr(crop, "size", 0) == 0:
        return None
    array = np.asarray(crop)
    if array.ndim < 2:
        return None
    if array.shape[1] > 12:
        array = array[:, int(array.shape[1] * 0.18) :]
    width, height = CREW_TIGHT_RIGHT_BADGE_TEMPLATE_SIZE
    resized = _resize_nearest(array, width, height)
    if resized is None:
        return None
    if resized.ndim == 3 and resized.shape[2] >= 3:
        channels = resized[:, :, :3].astype(np.float32)
        gray = channels.mean(axis=2)
        high = channels.max(axis=2)
        low = channels.min(axis=2)
        saturation = np.zeros_like(high)
        np.divide((high - low) * 255.0, high, out=saturation, where=high > 0)
    else:
        gray = resized.astype(np.float32)
        saturation = np.zeros_like(gray)
    mask = (((gray > 140) & (saturation < 195)) | ((gray > 92) & (saturation < 75))).astype(np.float32)
    mask[int(height * 0.32) : int(height * 0.58), :] = 0
    mask[int(height * 0.58) :, : int(width * 0.16)] = 0
    if int(mask.sum()) < 60:
        return None
    return mask


def _badge_mask_similarity_shifted(left: Any, right: Any, *, max_dx: int = 3, max_dy: int = 12) -> float:
    left_sum = float(left.sum())
    right_sum = float(right.sum())
    if left_sum <= 0 or right_sum <= 0:
        return 0.0
    height, width = left.shape
    best = 0.0
    for dy in range(-max_dy, max_dy + 1, 2):
        if dy >= 0:
            left_y1, left_y2 = dy, height
            right_y1, right_y2 = 0, height - dy
        else:
            left_y1, left_y2 = 0, height + dy
            right_y1, right_y2 = -dy, height
        if left_y2 <= left_y1 or right_y2 <= right_y1:
            continue
        for dx in range(-max_dx, max_dx + 1):
            if dx >= 0:
                left_x1, left_x2 = dx, width
                right_x1, right_x2 = 0, width - dx
            else:
                left_x1, left_x2 = 0, width + dx
                right_x1, right_x2 = -dx, width
            if left_x2 <= left_x1 or right_x2 <= right_x1:
                continue
            overlap = (
                left[left_y1:left_y2, left_x1:left_x2]
                * right[right_y1:right_y2, right_x1:right_x2]
            ).sum()
            best = max(best, float(overlap / ((left_sum * right_sum) ** 0.5)))
    return best


def _focus_resonance_badge_crop(crop: Any) -> Any:
    if np is None or crop is None or getattr(crop, "size", 0) == 0:
        return crop
    array = np.asarray(crop)
    if array.ndim < 2:
        return crop
    height, width = array.shape[:2]
    if width < 24 or height < 24:
        return crop
    left = 0
    if width >= 70:
        left = int(width * 0.18)
    elif width >= 52:
        left = int(width * 0.08)
    return array[:, left:]


def _crop_to_gray(crop: Any, *, focus_badge: bool = False) -> Any | None:
    if np is None or crop is None or getattr(crop, "size", 0) == 0:
        return None
    array = np.asarray(crop)
    if focus_badge:
        array = _focus_resonance_badge_crop(array)
    if array.ndim == 2:
        return array.astype(np.float32)
    if array.ndim == 3 and array.shape[2] >= 3:
        return array[:, :, :3].astype(np.float32).mean(axis=2)
    return None


def _awake_match_positions(
    crop_width: int,
    crop_height: int,
    width: int,
    height: int,
    *,
    wide: bool = False,
) -> tuple[tuple[int, int], ...]:
    if width > crop_width or height > crop_height:
        return ()
    center_x = max(0, int(round((crop_width - width) / 2)))
    center_y = max(0, int(round((crop_height - height) / 2)))
    positions: list[tuple[int, int]] = []

    def add_position(x: int, y: int) -> None:
        if len(positions) >= CREW_AWAKE_WIDE_MATCH_MAX_POSITIONS:
            return
        item = (
            min(max(0, x), crop_width - width),
            min(max(0, y), crop_height - height),
        )
        if item not in positions:
            positions.append(item)

    if wide:
        right_x = crop_width - width
        x_step = max(3, int(round(width * 0.14)))
        y_step = max(3, int(round(height * 0.14)))
        x_min = max(0, right_x - max(int(round(crop_width * 0.48)), width * 2))
        y_max = max(0, min(crop_height - height, int(round((crop_height - height) * 0.78))))
        for y in range(0, y_max + 1, y_step):
            for x in range(right_x, x_min - 1, -x_step):
                add_position(x, y)
        for y_ratio in (0.00, 0.08, 0.16, 0.24, 0.34, 0.46, 0.60):
            y = int(round((crop_height - height) * y_ratio))
            for x_factor in (0.00, 0.25, 0.50, 0.80, 1.10):
                add_position(right_x - int(round(width * x_factor)), y)
        add_position(center_x, center_y)
        return tuple(positions)

    for dy in (0, -54, 54, -36, 36, -18, 18):
        for dx in (0, -16, 16):
            add_position(center_x + dx, center_y + dy)
    return tuple(positions)


def _awake_icon_similarity(region: Any, template: Any, mask: Any) -> float:
    mask_sum = float(mask.sum())
    if mask_sum <= 0:
        return 0.0
    diff = np.abs(region.astype(np.float32) - template.astype(np.float32)) * mask
    diff_score = max(0.0, 1.0 - float(diff.sum() / (mask_sum * 255.0)))

    weighted_region = region.astype(np.float32) * mask
    weighted_template = template.astype(np.float32) * mask
    denom = float((weighted_region * weighted_region).sum() * (weighted_template * weighted_template).sum())
    corr_score = 0.0
    if denom > 0:
        corr_score = float((weighted_region * weighted_template).sum() / (denom**0.5))

    template_shape = ((template > 120) & (mask > 0)).astype(np.float32)
    template_sum = float(template_shape.sum())
    if template_sum <= 0:
        return max(diff_score, corr_score)
    masked_region = region[mask > 0]
    if getattr(masked_region, "size", 0) <= 0:
        return max(diff_score, corr_score)
    threshold = max(150.0, float(np.percentile(masked_region, 78)))
    region_shape = ((region.astype(np.float32) >= threshold) & (mask > 0)).astype(np.float32)
    region_sum = float(region_shape.sum())
    if region_sum <= 0:
        return max(diff_score, corr_score)
    overlap = float((template_shape * region_shape).sum())
    shape_score = (2.0 * overlap) / (template_sum + region_sum)
    return max(diff_score, corr_score, shape_score)


def classify_crew_awake_icon_crop(
    crop: Any,
    *,
    wide: bool = False,
    relaxed: bool = False,
) -> tuple[int, float, float] | None:
    gray = _crop_to_gray(crop, focus_badge=not wide)
    templates = load_awake_icon_templates()
    if gray is None or not templates:
        return None
    crop_height, crop_width = gray.shape[:2]
    if crop_width < 24 or crop_height < 24:
        return None

    scores: list[tuple[float, int]] = []
    for level, level_templates in templates.items():
        best_score = 0.0
        for _, template, mask in level_templates:
            height, width = template.shape[:2]
            for x, y in _awake_match_positions(crop_width, crop_height, width, height, wide=wide):
                region = gray[y : y + height, x : x + width]
                best_score = max(best_score, _awake_icon_similarity(region, template, mask))
        scores.append((best_score, level))
    scores.sort(reverse=True)
    if not scores:
        return None
    best_score, best_level = scores[0]
    second_score = scores[1][0] if len(scores) > 1 else 0.0
    margin = best_score - second_score
    if best_score >= CREW_AWAKE_TEMPLATE_STRONG_MIN and margin >= CREW_AWAKE_TEMPLATE_MATCH_MARGIN * 0.5:
        return best_level, best_score, margin
    if best_score >= CREW_AWAKE_TEMPLATE_MATCH_MIN and margin >= CREW_AWAKE_TEMPLATE_MATCH_MARGIN:
        return best_level, best_score, margin
    if relaxed and best_score >= CREW_AWAKE_TEMPLATE_RELAXED_MIN and margin >= CREW_AWAKE_TEMPLATE_RELAXED_MARGIN:
        return best_level, best_score, margin
    return None


def classify_crew_badge_crop(crop: Any) -> tuple[int, float, float] | None:
    mask = _tight_badge_digit_mask(crop)
    templates = load_tight_badge_templates()
    if mask is None or not templates:
        return None
    scores: list[tuple[float, int]] = []
    for level, level_templates in templates.items():
        if level_templates:
            scores.append((max(_badge_mask_similarity_shifted(mask, template) for template in level_templates), level))
    if not scores:
        return None
    scores.sort(reverse=True)
    best_score, best_level = scores[0]
    second_score = scores[1][0] if len(scores) > 1 else 0.0
    margin = best_score - second_score
    if best_score >= CREW_TIGHT_BADGE_TEMPLATE_MATCH_MIN and margin >= CREW_TIGHT_BADGE_TEMPLATE_MATCH_MARGIN:
        return best_level, best_score, margin
    return None


def _clip_box(x1: int, y1: int, x2: int, y2: int, width: int, height: int) -> tuple[int, int, int, int]:
    return max(0, x1), max(0, y1), min(width, x2), min(height, y2)


def _crew_card_column_index(name_x: float, image_width: int) -> int:
    scale_x = image_width / 1280.0
    card_width = CREW_CARD_BASE_WIDTH * scale_x
    return min(
        range(len(CREW_CARD_BASE_LEFTS)),
        key=lambda index: abs(name_x - (CREW_CARD_BASE_LEFTS[index] * scale_x + card_width * 0.82)),
    )


def _crew_group_name_rows(
    items: list[tuple[dict[str, Any], str, float, float, int]],
    image_height: int,
) -> list[list[tuple[dict[str, Any], str, float, float, int]]]:
    scale_y = image_height / 720.0
    rows: list[list[tuple[dict[str, Any], str, float, float, int]]] = []
    row_tolerance = 42 * scale_y
    for item in sorted(items, key=lambda value: (value[3], value[2])):
        y = item[3]
        for row in rows:
            row_y = float(np.median([entry[3] for entry in row]))
            if abs(y - row_y) <= row_tolerance:
                row.append(item)
                break
        else:
            rows.append([item])
    return rows


def _role_badge_regions(
    entry: dict[str, Any],
    role_names: tuple[str, ...],
    *,
    image_width: int,
    image_height: int,
    row_y: float | None = None,
    column_index: int | None = None,
) -> dict[str, Any] | None:
    role = match_role_name(_entry_text(entry), role_names)
    if not role:
        return None
    name_x, name_y = _entry_center(entry)
    scale_x = image_width / 1280.0
    scale_y = image_height / 720.0
    if name_y < CREW_SAFE_NAME_Y_MIN * scale_y or name_y > CREW_SAFE_NAME_Y_MAX * scale_y:
        return None

    row_y = float(row_y if row_y is not None else name_y)
    column_index = _crew_card_column_index(name_x, image_width) if column_index is None else column_index
    column_index = max(0, min(len(CREW_CARD_BASE_LEFTS) - 1, int(column_index)))
    base_left = CREW_CARD_BASE_LEFTS[column_index] * scale_x
    card_right = base_left + CREW_CARD_BASE_WIDTH * scale_x
    card_top = row_y - CREW_CARD_NAME_ROW_TO_TOP * scale_y
    card_box = _clip_box(
        int(round(base_left)),
        int(round(card_top)),
        int(round(card_right)),
        int(round(card_top + 292 * scale_y)),
        image_width,
        image_height,
    )
    full_box = _clip_box(
        int(round(card_right + CREW_CARD_FULL_BADGE_FROM_RIGHT[0] * scale_x)),
        int(round(row_y + CREW_CARD_FULL_BADGE_FROM_ROW_Y[0] * scale_y)),
        int(round(card_right + CREW_CARD_FULL_BADGE_FROM_RIGHT[1] * scale_x)),
        int(round(row_y + CREW_CARD_FULL_BADGE_FROM_ROW_Y[1] * scale_y)),
        image_width,
        image_height,
    )
    tight_x1 = int(round(card_right + CREW_CARD_TIGHT_BADGE_FROM_RIGHT[0] * scale_x))
    tight_x2 = int(round(card_right + CREW_CARD_TIGHT_BADGE_FROM_RIGHT[1] * scale_x))
    tight_y1 = int(round(row_y + CREW_CARD_TIGHT_BADGE_FROM_ROW_Y[0] * scale_y))
    tight_y2 = int(round(row_y + CREW_CARD_TIGHT_BADGE_FROM_ROW_Y[1] * scale_y))
    tight_box = _clip_box(tight_x1, tight_y1, tight_x2, tight_y2, image_width, image_height)
    if (
        card_box[2] <= card_box[0]
        or card_box[3] <= card_box[1]
        or full_box[2] <= full_box[0]
        or full_box[3] <= full_box[1]
        or tight_box[2] <= tight_box[0]
        or tight_box[3] <= tight_box[1]
    ):
        return None

    awake_box = _clip_box(
        int(round(tight_box[0] - 12 * scale_x)),
        int(round(tight_box[1] - 24 * scale_y)),
        int(round(tight_box[2] + 12 * scale_x)),
        int(round(tight_box[3] + 24 * scale_y)),
        image_width,
        image_height,
    )
    card_awake_box = _clip_box(
        int(round(base_left)),
        int(round(row_y + CREW_CARD_AWAKE_FROM_ROW_Y[0] * scale_y)),
        int(round(card_right)),
        int(round(row_y + CREW_CARD_AWAKE_FROM_ROW_Y[1] * scale_y)),
        image_width,
        image_height,
    )
    return {
        "role": role,
        "name_center": (name_x, name_y),
        "row_y": row_y,
        "column_index": column_index,
        "entry": entry,
        "card": card_box,
        "full": full_box,
        "tight": tight_box,
        "awake": awake_box,
        "card_awake": card_awake_box,
    }


def _role_badge_region_candidates(
    entries: list[dict[str, Any]],
    role_names: tuple[str, ...],
    *,
    image_width: int,
    image_height: int,
) -> list[dict[str, Any]]:
    scale_y = image_height / 720.0
    name_items: list[tuple[dict[str, Any], str, float, float, int]] = []
    for entry in entries:
        role = match_role_name(_entry_text(entry), role_names)
        if not role:
            continue
        name_x, name_y = _entry_center(entry)
        if name_y < CREW_SAFE_NAME_Y_MIN * scale_y or name_y > CREW_SAFE_NAME_Y_MAX * scale_y:
            continue
        name_items.append((entry, role, name_x, name_y, _crew_card_column_index(name_x, image_width)))

    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for row in _crew_group_name_rows(name_items, image_height):
        row_y = float(np.median([item[3] for item in row]))
        for entry, role, name_x, _, column_index in row:
            key = (role, column_index, int(row_y // max(1, 24 * scale_y)))
            if key in seen:
                continue
            seen.add(key)
            regions = _role_badge_regions(
                entry,
                role_names,
                image_width=image_width,
                image_height=image_height,
                row_y=row_y,
                column_index=column_index,
            )
            if regions:
                candidates.append(regions)
    return candidates


def parse_role_badges_from_image(
    image: Any,
    entries: list[dict[str, Any]],
    role_names: tuple[str, ...] | None = None,
    *,
    weighted: bool = False,
) -> dict[str, int | tuple[int, int]]:
    if np is None or image is None or getattr(image, "size", 0) == 0:
        return {}
    array = np.asarray(image)
    if array.ndim < 2:
        return {}
    height, width = array.shape[:2]
    role_names = role_names or load_role_names()
    result: dict[str, int | tuple[int, int]] = {}

    for regions in _role_badge_region_candidates(entries, role_names, image_width=width, image_height=height):
        role = regions["role"]
        x1, y1, x2, y2 = regions["tight"]
        search_x1, search_y1, search_x2, search_y2 = regions["awake"]
        full_x1, full_y1, full_x2, full_y2 = regions["full"]
        card_x1, card_y1, card_x2, card_y2 = regions["card_awake"]
        card_focus_x1 = max(0, card_x2 - max(86, int(round((card_x2 - card_x1) * 0.58))))
        card_focus_x2 = min(width, card_x2 + max(16, int(round(width * 0.02))))
        card_focus_y1 = max(0, card_y1)
        card_focus_y2 = min(height, card_y1 + max(96, int(round((card_y2 - card_y1) * 0.78))))

        awake_matches: list[tuple[float, float, str, tuple[int, float, float]]] = []
        for source, (crop_x1, crop_y1, crop_x2, crop_y2) in (
            ("awake_tight", (x1, y1, x2, y2)),
            ("awake_full", (full_x1, full_y1, full_x2, full_y2)),
            ("awake_search", (search_x1, search_y1, search_x2, search_y2)),
        ):
            if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
                continue
            crop = array[crop_y1:crop_y2, crop_x1:crop_x2]
            awake_match = classify_crew_awake_icon_crop(crop)
            if awake_match is None:
                continue
            _, score, margin = awake_match
            awake_matches.append((float(score), float(margin), source, awake_match))
            if score >= CREW_AWAKE_TEMPLATE_STRONG_MIN:
                break
        if not awake_matches and card_focus_x2 > card_focus_x1 and card_focus_y2 > card_focus_y1:
            crop = array[card_focus_y1:card_focus_y2, card_focus_x1:card_focus_x2]
            awake_match = classify_crew_awake_icon_crop(crop)
            if awake_match is None:
                awake_match = classify_crew_awake_icon_crop(crop, wide=True)
            if awake_match is not None:
                _, score, margin = awake_match
                awake_matches.append((float(score), float(margin), "awake_card_right", awake_match))
            else:
                awake_match = classify_crew_awake_icon_crop(crop, relaxed=True)
                if awake_match is None:
                    awake_match = classify_crew_awake_icon_crop(crop, wide=True, relaxed=True)
                if awake_match is not None:
                    _, score, margin = awake_match
                    awake_matches.append((float(score), float(margin), "awake_card_right_relaxed", awake_match))
        use_full_card_fallback = (
            env_truthy("MAA_RESONANCE_ROLE_SLOW_BADGE_FALLBACK")
            or role in CREW_AWAKE_FULL_CARD_FALLBACK_ROLES
        )
        if (
            not awake_matches
            and use_full_card_fallback
            and card_x2 > card_x1
            and card_y2 > card_y1
        ):
            matched_source_name = "awake_card"
            awake_match = classify_crew_awake_icon_crop(array[card_y1:card_y2, card_x1:card_x2], wide=True)
            if awake_match is None:
                awake_match = classify_crew_awake_icon_crop(
                    array[card_y1:card_y2, card_x1:card_x2],
                    wide=True,
                    relaxed=True,
                )
                matched_source_name = "awake_card_relaxed"
            if awake_match is not None:
                _, score, margin = awake_match
                awake_matches.append((float(score), float(margin), matched_source_name, awake_match))

        matched: tuple[int, float, float] | None = None
        matched_source = ""
        if awake_matches:
            awake_matches.sort(reverse=True)
            _, _, matched_source, matched = awake_matches[0]
        if matched is None:
            matched = classify_crew_badge_crop(array[y1:y2, x1:x2])
            matched_source = "tight_badge"
        if matched is None:
            continue
        level, score, margin = matched
        capped_level = cap_role_resonance_level(role, level)
        if "relaxed" in matched_source:
            weight = 4
        elif matched_source.startswith("awake"):
            weight = 8 if score >= 0.88 and margin >= 0.03 else 6
        else:
            weight = 4 if score >= 0.72 or margin >= 0.12 else 2
        candidate = (capped_level, weight) if weighted else capped_level
        existing = result.get(role)
        existing_weight = existing[1] if isinstance(existing, tuple) else 0
        if not existing or (isinstance(candidate, tuple) and candidate[1] >= existing_weight):
            result[role] = candidate
    return result


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind)
    checksum = zlib.crc32(data, checksum) & 0xFFFFFFFF
    return len(data).to_bytes(4, "big") + kind + data + checksum.to_bytes(4, "big")


def _png_bytes_from_array(crop: Any, *, assume_bgr: bool = True) -> bytes | None:
    if np is None or crop is None or getattr(crop, "size", 0) == 0:
        return None
    array = np.asarray(crop)
    if array.ndim == 2:
        rgb = np.repeat(array[:, :, None], 3, axis=2)
    elif array.ndim == 3 and array.shape[2] >= 3:
        rgb = array[:, :, :3]
        if assume_bgr:
            rgb = rgb[:, :, ::-1]
    else:
        return None
    if rgb.dtype != np.uint8:
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    height, width = rgb.shape[:2]
    if width <= 0 or height <= 0:
        return None
    raw_rows = b"".join(b"\x00" + rgb[row].tobytes() for row in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw_rows, 6))
        + _png_chunk(b"IEND", b"")
    )


def _safe_debug_name(value: str) -> str:
    safe = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", str(value or "").strip())
    return safe[:48] or "unknown"


def save_role_badge_debug_crops(
    image: Any,
    entries: list[dict[str, Any]],
    role_names: tuple[str, ...] | None = None,
    *,
    roles: list[str] | tuple[str, ...] | set[str] | None = None,
    page_index: int = 0,
    run_id: str = "",
    debug_root: Path | None = None,
) -> list[str]:
    if np is None or image is None or getattr(image, "size", 0) == 0 or not entries:
        return []
    array = np.asarray(image)
    if array.ndim < 2:
        return []
    height, width = array.shape[:2]
    role_names = role_names or load_role_names()
    target_roles = {str(role) for role in roles or () if str(role)}
    if not target_roles:
        return []

    root = Path(debug_root or PROJECT_ROOT / "debug" / "role_resonance_crops")
    run_dir = root / _safe_debug_name(run_id or "latest")
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.jsonl"
    saved_paths: list[str] = []
    seen: set[tuple[str, str, tuple[int, int, int, int]]] = set()

    for regions in _role_badge_region_candidates(entries, role_names, image_width=width, image_height=height):
        role = str(regions["role"])
        if role not in target_roles:
            continue
        entry = regions.get("entry") or {}
        name_left, name_top, name_right, name_bottom = _entry_bounds(entry) if isinstance(entry, dict) else (0, 0, 0, 0)
        name_box = _clip_box(
            int(round(name_left - 12)),
            int(round(name_top - 8)),
            int(round(name_right + 12)),
            int(round(name_bottom + 8)),
            width,
            height,
        )
        crop_kinds = (
            ("overview", regions["card"]),
            ("name", name_box),
            ("card_awake", regions["card_awake"]),
            ("full", regions["full"]),
            ("awake", regions["awake"]),
            ("tight", regions["tight"]),
        )
        for kind, box in crop_kinds:
            x1, y1, x2, y2 = box
            if x2 <= x1 or y2 <= y1:
                continue
            key = (role, kind, (x1, y1, x2, y2))
            if key in seen:
                continue
            seen.add(key)
            payload = _png_bytes_from_array(array[y1:y2, x1:x2])
            if payload is None:
                continue
            file_name = f"page_{int(page_index):02d}_{_safe_debug_name(role)}_{kind}_{x1}_{y1}_{x2}_{y2}.png"
            path = run_dir / file_name
            path.write_bytes(payload)
            saved_paths.append(str(path))
            with manifest_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "page_index": page_index,
                            "role": role,
                            "kind": kind,
                            "box": [x1, y1, x2, y2],
                            "path": str(path),
                            "ocr_entry": {
                                "text": entry.get("text") if isinstance(entry, dict) else None,
                                "x": entry.get("x") if isinstance(entry, dict) else None,
                                "y": entry.get("y") if isinstance(entry, dict) else None,
                                "w": entry.get("w") if isinstance(entry, dict) else None,
                                "h": entry.get("h") if isinstance(entry, dict) else None,
                            },
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                )
                handle.write("\n")
    return saved_paths


def planner_role_resonance_level(level: int | str | None) -> int:
    value = normalize_role_resonance_level(level)
    if value <= 0:
        return 0
    if value < 4:
        return 1
    return 5 if value >= 5 else 4


def role_match_keys(role: str, role_names: tuple[str, ...] | set[str] | None = None) -> tuple[str, ...]:
    role_names_key = tuple(str(item).strip() for item in role_names or () if str(item).strip())
    return _role_match_keys_cached(str(role or "").strip(), role_names_key)


@lru_cache(maxsize=4096)
def _role_match_keys_cached(role: str, role_names_key: tuple[str, ...]) -> tuple[str, ...]:
    role = str(role or "").strip()
    if not role:
        return ()
    keys = [clean_text(role), normalize_role_text(role)]
    compact = role.replace("·", " ").replace("・", " ")
    for part in compact.split():
        part = clean_text(part)
        if len(part) >= 2:
            keys.append(part)
            keys.append(normalize_role_text(part))

    role_set = {clean_text(item) for item in role_names_key}
    safe_keys: list[str] = []
    for key in keys:
        if not key:
            continue
        conflicts = [name for name in role_set if name != clean_text(role) and key in name]
        if conflicts and key != clean_text(role):
            continue
        if key not in safe_keys:
            safe_keys.append(key)
    return tuple(safe_keys)


def match_role_name(text: str, role_names: tuple[str, ...] | None = None) -> str | None:
    role_names = tuple(role_names or load_role_names())
    return _match_role_name_cached(str(text or ""), role_names)


@lru_cache(maxsize=8192)
def _match_role_name_cached(text: str, role_names: tuple[str, ...]) -> str | None:
    cleaned = clean_text(text)
    normalized = normalize_role_text(text)
    if not cleaned:
        return None

    best_role: str | None = None
    best_score = 0.0
    for role in role_names:
        keys = role_match_keys(role, role_names)
        for key in keys:
            if cleaned == key or normalized == key:
                return role
            if key in cleaned or key in normalized:
                score = 2.0 + len(key) * 0.01
            elif abs(len(key) - len(normalized)) <= 2:
                score = SequenceMatcher(None, normalized, key).ratio()
            else:
                score = 0.0
            if score > best_score:
                best_role = role
                best_score = score
    if best_role and best_score >= 0.78:
        return best_role
    return None


def role_text_match_score(
    text: str,
    role: str,
    role_names: tuple[str, ...] | set[str] | None = None,
) -> float:
    cleaned = clean_text(text)
    normalized = normalize_role_text(text)
    if not cleaned or not role:
        return 0.0
    keys = role_match_keys(role, role_names)
    for key in keys:
        if cleaned == key or normalized == key:
            return 3.0 + len(key) * 0.01
    for key in keys:
        if key and (key in cleaned or key in normalized):
            return 2.0 + len(key) * 0.01
    if len(cleaned) < 2:
        return 0.0
    best_score = 0.0
    for key in keys:
        if abs(len(key) - len(normalized)) <= 2:
            best_score = max(best_score, SequenceMatcher(None, normalized, key).ratio())
    return best_score


def entry_resonance_level(text: str) -> int | None:
    cleaned = clean_text(text)
    if not cleaned:
        return None
    if re.search(r"(?:Lv|LV|等级)\d+", cleaned):
        return None
    match = re.search(r"共振([0-5])", cleaned)
    if match:
        return int(match.group(1))
    return None


def _entry_text(entry: dict[str, Any]) -> str:
    return str(entry.get("text") or "").strip()


def _entry_bounds(entry: dict[str, Any]) -> tuple[float, float, float, float]:
    if all(key in entry for key in ("x", "y", "w", "h")):
        x = float(entry.get("x") or 0)
        y = float(entry.get("y") or 0)
        w = float(entry.get("w") or 0)
        h = float(entry.get("h") or 0)
        return x, y, x + w, y + h
    box = entry.get("box")
    if isinstance(box, dict):
        x = float(box.get("x") or 0)
        y = float(box.get("y") or 0)
        w = float(box.get("w") or 0)
        h = float(box.get("h") or 0)
        return x, y, x + w, y + h
    center_x = float(entry.get("center_x") or 0)
    center_y = float(entry.get("center_y") or 0)
    return center_x, center_y, center_x, center_y


def _entry_center(entry: dict[str, Any]) -> tuple[float, float]:
    if "center_x" in entry and "center_y" in entry:
        return float(entry.get("center_x") or 0), float(entry.get("center_y") or 0)
    left, top, right, bottom = _entry_bounds(entry)
    return (left + right) / 2, (top + bottom) / 2


def crew_sort_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in entries:
        text = _entry_text(entry)
        if any(keyword in text for keyword in CREW_SORT_TEXTS):
            return entry
    return None


def crew_sort_arrow_down(image: Any, sort_entry: dict[str, Any]) -> bool | None:
    if np is None or image is None:
        return None
    raw = np.asarray(image)
    if raw.size == 0 or not hasattr(raw, "shape") or len(raw.shape) < 2:
        return None
    left, top, _, bottom = _entry_bounds(sort_entry)
    x1 = max(0, int(left) - 42)
    x2 = max(0, int(left) - 4)
    y1 = max(0, int(top) - 12)
    y2 = max(y1 + 1, int(bottom) + 12)
    crop = raw[y1:y2, x1:x2]
    if getattr(crop, "size", 0) == 0:
        return None
    gray = crop.mean(axis=2) if len(crop.shape) == 3 else crop
    dark = gray < 190
    ys, _ = np.where(dark)
    if len(ys) < 8:
        return None
    height = max(1, dark.shape[0])
    top_pixels = int((ys < height * 0.45).sum())
    bottom_pixels = int((ys > height * 0.55).sum())
    if abs(top_pixels - bottom_pixels) < max(4, int(len(ys) * 0.12)):
        return None
    return top_pixels > bottom_pixels


def crew_sort_tap_point(image: Any, sort_entry: dict[str, Any]) -> tuple[int, int] | None:
    shape = getattr(image, "shape", None)
    if shape and len(shape) >= 2:
        height, width = int(shape[0]), int(shape[1])
    else:
        height, width = 720, 1280
    if width <= 0 or height <= 0:
        return None
    left, top, right, bottom = _entry_bounds(sort_entry)
    center_y = min(height - 1, max(0, int((top + bottom) / 2)))
    arrow_x = int(left) - 20
    if 0 <= arrow_x < width:
        return arrow_x, center_y
    label_x = int(left + min(max((right - left) * 0.22, 12), 28))
    return min(width - 1, max(0, label_x)), center_y


def looks_like_crew_name_text(text: str) -> bool:
    if not text:
        return False
    if any(keyword in text for keyword in CREW_NAME_EXCLUDE_KEYWORDS):
        return False
    if any(char.isdigit() for char in text):
        return False
    if not re.search(r"[\u4e00-\u9fff]", text):
        return False
    return len(clean_text(text)) <= 8


def visible_role_names_from_entries(
    entries: list[dict[str, Any]],
    role_names: tuple[str, ...] | None = None,
) -> set[str]:
    role_names = role_names or load_role_names()
    result: set[str] = set()
    for entry in entries:
        text = _entry_text(entry)
        _, y = _entry_center(entry)
        if y < CREW_SAFE_NAME_Y_MIN or y > CREW_SAFE_NAME_Y_MAX:
            continue
        role = match_role_name(text, role_names)
        if role:
            result.add(role)
    return result


def crew_page_signature(
    entries: list[dict[str, Any]],
    role_names: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    role_names = role_names or load_role_names()
    items: list[str] = []
    for entry in entries:
        text = _entry_text(entry)
        x, y = _entry_center(entry)
        if y < CREW_SAFE_NAME_Y_MIN or y > CREW_SAFE_NAME_Y_MAX:
            continue
        role = match_role_name(text, role_names)
        if not role:
            continue
        item = f"{role}@{int(x // 32)}:{int(y // 24)}"
        if item not in items:
            items.append(item)
    return tuple(items)


def parse_role_resonance_from_entries(
    entries: list[dict[str, Any]],
    role_names: tuple[str, ...] | None = None,
    *,
    weighted: bool = False,
) -> dict[str, int | tuple[int, int]]:
    role_names = role_names or load_role_names()
    cleaned_entries: list[tuple[str, float, float, dict[str, Any]]] = []
    for entry in entries:
        text = _entry_text(entry)
        if not text:
            continue
        x, y = _entry_center(entry)
        cleaned_entries.append((text, x, y, entry))

    result: dict[str, int | tuple[int, int]] = {}
    result_priority: dict[str, tuple[int, float]] = {}
    for text, name_x, name_y, name_entry in cleaned_entries:
        role = match_role_name(text, role_names)
        if not role:
            continue
        if name_y < CREW_SAFE_NAME_Y_MIN or name_y > CREW_SAFE_NAME_Y_MAX:
            continue
        match_score = role_text_match_score(text, role, role_names)
        _, name_top, _, _ = _entry_bounds(name_entry)

        candidates: list[tuple[float, int]] = []
        for other_text, x, y, _ in cleaned_entries:
            level = entry_resonance_level(other_text)
            if level is None:
                continue
            if y < name_y - 120 or y > name_y + 45:
                continue
            if x < name_x - 20:
                continue
            score = abs(y - (name_top - 30)) + max(0, name_x - x) * 0.2
            candidates.append((score, level))

        inline_level = entry_resonance_level(text)
        if inline_level is not None:
            candidates.append((999.0, inline_level))

        if not candidates:
            continue
        level = cap_role_resonance_level(role, min(candidates, key=lambda item: item[0])[1])
        candidate = (level, 1) if weighted else level
        priority = (candidate[1] if isinstance(candidate, tuple) else 1, match_score)
        if priority > result_priority.get(role, (-1, -1.0)):
            result[role] = candidate
            result_priority[role] = priority
    return result


def normalize_resonance_vote(vote: int | tuple[int, int] | list[Any]) -> tuple[int, int]:
    if isinstance(vote, (tuple, list)):
        raw_level = vote[0] if vote else None
        raw_weight = vote[1] if len(vote) > 1 else 1
        try:
            weight = max(1, int(raw_weight))
        except (TypeError, ValueError):
            weight = 1
        return normalize_role_resonance_level(raw_level), weight
    return normalize_role_resonance_level(vote), 1


def resolve_resonance_votes(votes: list[int | tuple[int, int] | list[Any]]) -> int | None:
    if not votes:
        return None
    normalized_votes = [normalize_resonance_vote(vote) for vote in votes]
    counts: Counter[int] = Counter()
    for level, weight in normalized_votes:
        counts[level] += weight
    best_count = max(counts.values())
    best_levels = [level for level, count in counts.items() if count == best_count]
    if len(best_levels) == 1:
        return best_levels[0]
    return max(best_levels)


def parse_role_resonance_texts(
    texts: list[str],
    role_names: tuple[str, ...] | None = None,
) -> dict[str, int]:
    role_names = role_names or load_role_names()
    cleaned = [normalize_role_text(text) for text in texts if str(text).strip()]
    result: dict[str, int] = {}
    role_keys = {
        role: tuple(dict.fromkeys((clean_text(role), normalize_role_text(role))))
        for role in role_names
    }
    for role, keys in role_keys.items():
        for index, text in enumerate(cleaned):
            if not any(key and key in text for key in keys):
                continue
            window = "".join(cleaned[index : index + 4])
            match = re.search(r"共振([0-5])", window)
            if match:
                result[role] = cap_role_resonance_level(role, match.group(1))
                break
    return result


def classify_city_unlock_probe(texts: list[str]) -> str:
    cleaned = [clean_text(text) for text in texts if str(text).strip()]
    if not cleaned:
        return "unknown"
    window = "".join(cleaned)
    if any(keyword in window for keyword in UNAVAILABLE_CITY_TEXTS):
        return "unavailable"
    if re.search(r"路程:?0km", window, re.IGNORECASE):
        return "available"
    if any(keyword in window for keyword in AVAILABLE_CITY_TEXTS):
        return "available"
    if any(keyword in window for keyword in CITY_DETAIL_PANEL_TEXTS):
        return "unavailable"
    return "unknown"


@lru_cache(maxsize=1)
def load_city_aliases() -> tuple[tuple[str, str], ...]:
    thresholds = load_prestige_thresholds()
    raw_cities = thresholds.get("cities") if isinstance(thresholds, dict) else {}
    aliases: dict[str, str] = {}
    if isinstance(raw_cities, dict):
        for city in raw_cities:
            alias = str(city).strip()
            if not alias:
                continue
            master = prestige_master_city(alias) or alias
            aliases[alias] = master
            aliases.setdefault(master, master)
    return tuple(sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True))


def threshold_map(city_name: str | None = None) -> dict[int, int]:
    thresholds = load_prestige_thresholds()
    raw: dict[str, Any] | None = None
    master_city = prestige_master_city(city_name)
    cities = thresholds.get("cities") if isinstance(thresholds, dict) else {}
    if master_city and isinstance(cities, dict):
        city_raw = cities.get(master_city)
        if isinstance(city_raw, dict) and len(city_raw) >= 3:
            raw = city_raw
    if raw is None:
        raw = thresholds.get("default") if isinstance(thresholds, dict) else {}
    if not isinstance(raw, dict):
        return {}
    result: dict[int, int] = {}
    for level, value in raw.items():
        try:
            result[int(level)] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def prestige_value_to_level(
    prestige_value: int,
    city_name: str | None = None,
    *,
    max_level: int = PLANNER_MAX_PRESTIGE_LEVEL,
) -> int | None:
    thresholds = threshold_map(city_name)
    if not thresholds:
        return None
    level = 1
    for candidate_level, required_value in sorted(thresholds.items()):
        if candidate_level > max_level:
            continue
        if prestige_value >= required_value:
            level = candidate_level
        else:
            break
    return level


def numbers_near_city(text: str, city: str) -> list[int]:
    return [int(value) for value in re.findall(r"\d{1,6}", clean_text(text).replace(city, ""))]


def looks_like_prestige_value(value: int) -> bool:
    return 0 <= value <= 999999


def parse_city_prestige_values_from_entries(
    entries: list[dict[str, Any]],
    city_names: tuple[str, ...] | None = None,
) -> dict[str, int]:
    city_aliases = (
        tuple((city, city) for city in city_names)
        if city_names is not None
        else load_city_aliases()
    )
    cleaned_entries: list[tuple[str, float, float]] = []
    for entry in entries:
        text = clean_text(str(entry.get("text", "")))
        if not text:
            continue
        x = float(entry.get("center_x", 0.0) or 0.0)
        y = float(entry.get("center_y", 0.0) or 0.0)
        cleaned_entries.append((text, x, y))

    result: dict[str, int] = {}
    for city, master_city in city_aliases:
        city_key = clean_text(city)
        if not city_key:
            continue
        city_entry = next(((text, x, y) for text, x, y in cleaned_entries if city_key in text), None)
        if city_entry is None:
            continue
        city_text, city_x, city_y = city_entry
        candidates = [
            value for value in numbers_near_city(city_text, city_key) if looks_like_prestige_value(value)
        ]
        for text, x, y in cleaned_entries:
            if abs(y - city_y) > 36:
                continue
            if x < city_x - 20:
                continue
            candidates.extend(
                value for value in re.findall(r"\d{1,6}", text) if looks_like_prestige_value(int(value))
            )
        if candidates:
            value = max(int(value) for value in candidates)
            result[master_city] = max(result.get(master_city, value), value)
    return result


def parse_city_prestige_values(
    texts: list[str],
    city_names: tuple[str, ...] | None = None,
) -> dict[str, int]:
    city_aliases = (
        tuple((city, city) for city in city_names)
        if city_names is not None
        else load_city_aliases()
    )
    city_keys = tuple(clean_text(city) for city, _master in city_aliases)
    cleaned = [clean_text(text) for text in texts if str(text).strip()]
    result: dict[str, int] = {}
    for city, master_city in city_aliases:
        city_key = clean_text(city)
        if not city_key:
            continue
        for index, text in enumerate(cleaned):
            if city_key not in text:
                continue
            candidates: list[int] = []
            for piece in cleaned[index : index + 5]:
                if piece != text and any(other != city_key and other in piece for other in city_keys):
                    break
                candidates.extend(
                    value for value in numbers_near_city(piece, city_key) if looks_like_prestige_value(value)
                )
            if candidates:
                value = max(candidates)
                result[master_city] = max(result.get(master_city, value), value)
                break
    return result


def prestige_values_to_levels(values_by_city: dict[str, int]) -> dict[str, int]:
    levels: dict[str, int] = {}
    for city, value in values_by_city.items():
        level = prestige_value_to_level(value, city)
        if level is not None:
            levels[city] = level
    return levels

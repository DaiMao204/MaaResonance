"""Pure logic and pixel/OCR helpers for Coop Assault (限时共斗 · 众志攻坚)."""
from __future__ import annotations

import re
from typing import Any

import numpy as np

COOP_HOME_ENTER_ROI: tuple[int, int, int, int] = (740, 540, 480, 110)
COOP_HOME_ENTER_FALLBACK: tuple[int, int] = (975, 595)
COOP_REMAINING_ROI: tuple[int, int, int, int] = (990, 15, 260, 60)
COOP_REWARD_BTN_ROI: tuple[int, int, int, int] = (1080, 635, 185, 80)
COOP_REWARD_BTN_FALLBACK: tuple[int, int] = (1168, 668)
COOP_REWARD_TABS_ROI: tuple[int, int, int, int] = (300, 610, 720, 85)
COOP_REWARD_CLAIM_ROI: tuple[int, int, int, int] = (1060, 80, 190, 440)
COOP_PREPARE_HEADER_ROI: tuple[int, int, int, int] = (350, 80, 760, 130)
COOP_PREPARE_ENTER_ROI: tuple[int, int, int, int] = (800, 520, 310, 75)
COOP_PREPARE_ENTER_FALLBACK: tuple[int, int] = (960, 558)

COOP_DIFF_CENTERS_X: tuple[int, ...] = (510, 645, 778, 912, 1045)
COOP_DIFF_Y: int = 395

COOP_BOSS_SLOT_FALLBACKS: dict[str, tuple[int, int]] = {
    "left": (232, 260),
    "center": (640, 350),
    "right": (1045, 260),
}
COOP_REWARD_TAB_FALLBACKS: tuple[tuple[str, tuple[int, int]], ...] = (
    ("boss1", (403, 641)),
    ("boss2", (639, 641)),
    ("boss3", (874, 641)),
)

_DIGIT_CONFUSIONS = str.maketrans({
    "O": "0",
    "o": "0",
    "I": "1",
    "l": "1",
    "|": "1",
})


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


def parse_coop_remaining_attempts(entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Parse remaining challenge count such as '5/5' or '进入挑战5/5' (ignoring calendar dates like '11/16')."""
    candidates: list[tuple[int, int, int]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text")).translate(_DIGIT_CONFUSIONS)
        if "/" not in cleaned or ":" in cleaned:
            continue
        match = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", cleaned)
        if not match:
            continue
        cur = int(match.group(1))
        total = int(match.group(2))
        if 3 <= total <= 10 and 0 <= cur <= total:
            priority = 2 if ("挑战" in cleaned or "讨伐" in cleaned or re.fullmatch(r"\d{1,2}/\d{1,2}", cleaned)) else 1
            candidates.append((priority, cur, total))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, cur, total = candidates[0]
    return cur, total


def is_coop_home_entries(entries: list[dict[str, Any]]) -> bool:
    """Return True when the Joint Assault activity home page is visible."""
    texts = [_clean(e.get("text")).upper() for e in entries if isinstance(e, dict)]
    return any("进入挑战" in t for t in texts) and any(
        kw in t for t in texts for kw in ("众志攻坚", "ASSAULT", "攻坚战果")
    )


def find_coop_home_enter_point(entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Locate the yellow '进入挑战' button on the Joint Assault home page."""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text"))
        if "进入挑战" in cleaned:
            center = _entry_center(entry)
            if center is not None:
                return center
    return None


def is_coop_boss_map_entries(entries: list[dict[str, Any]]) -> bool:
    """Return True when on the Joint Assault 3-boss map screen."""
    texts = [_clean(e.get("text")).upper() for e in entries if isinstance(e, dict)]
    if any("当前剩余讨伐次数" in t for t in texts):
        return True
    hits = sum(
        1
        for kw in ("攻坚战果", "探访结局", "已击杀", "可继续重复挑战", "REWARD")
        if any(kw in t for t in texts)
    )
    return hits >= 2


def parse_coop_boss_slots(full_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse the left/center/right boss slots from full-screen OCR entries."""
    buckets: dict[str, list[tuple[dict[str, Any], tuple[int, int], str]]] = {
        "left": [],
        "center": [],
        "right": [],
    }
    for entry in full_entries:
        if not isinstance(entry, dict):
            continue
        center = _entry_center(entry)
        if center is None:
            continue
        cx, cy = center
        if cy < 150 or cy > 560:
            continue
        cleaned = _clean(entry.get("text"))
        if not cleaned:
            continue
        if cx < 430:
            buckets["left"].append((entry, center, cleaned))
        elif cx <= 850:
            buckets["center"].append((entry, center, cleaned))
        else:
            buckets["right"].append((entry, center, cleaned))

    slots: list[dict[str, Any]] = []
    for slot_key in ("left", "center", "right"):
        items = buckets[slot_key]
        if not items:
            continue
        defeated = any("已击杀" in t for _, _, t in items)
        repeatable = any("重复挑战" in t for _, _, t in items)
        hp_pct: float | None = None
        name: str = slot_key
        tap_point = COOP_BOSS_SLOT_FALLBACKS[slot_key]

        for _, (cx, cy), cleaned in items:
            pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", cleaned.translate(_DIGIT_CONFUSIONS))
            if pct_match and hp_pct is None:
                hp_pct = float(pct_match.group(1))
                continue
            if any(
                skip in cleaned
                for skip in ("已击杀", "重复挑战", "探访结局", "ENDING", "STRIKE", "BOSS", "%")
            ):
                continue
            if len(cleaned) >= 2 and re.search(r"[\u4e00-\u9fff]", cleaned):
                name = cleaned
                tap_point = (cx, max(220, cy - 60))

        if hp_pct is not None and hp_pct <= 0.0:
            defeated = True
        slots.append(
            {
                "slot": slot_key,
                "name": name,
                "hp_pct": hp_pct,
                "defeated": defeated,
                "repeatable": repeatable,
                "tap_point": tap_point,
            }
        )
    return slots


def choose_coop_boss_slot(
    slots: list[dict[str, Any]],
    preference: str = "alive_first",
) -> dict[str, Any] | None:
    """Choose which boss slot to attack based on preference."""
    if not slots:
        return None
    pref = str(preference or "alive_first").strip().lower()
    if pref in ("left", "center", "right"):
        for slot in slots:
            if slot.get("slot") == pref:
                return slot

    alive = [s for s in slots if not s.get("defeated") and (s.get("hp_pct") is None or s["hp_pct"] > 0.0)]
    if alive:
        return alive[0]

    repeatable = [s for s in slots if s.get("repeatable")]
    if repeatable:
        return repeatable[-1]
    return slots[0]


def is_coop_prepare_entries(entries: list[dict[str, Any]]) -> bool:
    """Return True when the boss difficulty selection modal is open."""
    texts = [_clean(e.get("text")) for e in entries if isinstance(e, dict)]
    has_diff = any("难度1" in t or "难度2" in t or "难度3" in t for t in texts)
    has_action = any("进入挑战" in t or "敌人等级" in t for t in texts)
    return has_diff and has_action


def find_coop_prepare_enter_point(entries: list[dict[str, Any]]) -> tuple[int, int]:
    """Find the '进入挑战' button center inside the boss difficulty modal."""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if "进入挑战" in _clean(entry.get("text")):
            center = _entry_center(entry)
            if center is not None:
                return center
    return COOP_PREPARE_ENTER_FALLBACK


def detect_unlocked_coop_difficulties(image: Any) -> list[int]:
    """Detect which difficulty cards (1..5) are unlocked via color chroma."""
    if not isinstance(image, np.ndarray) or image.ndim < 2 or image.shape[0] <= 0 or image.shape[1] <= 0:
        return [1]
    h, w = image.shape[:2]
    sx = w / 1280.0
    sy = h / 720.0
    unlocked: list[int] = []
    for idx, cx in enumerate(COOP_DIFF_CENTERS_X, start=1):
        ix1 = max(0, min(w - 1, int(round((cx - 40) * sx))))
        ix2 = max(ix1 + 1, min(w, int(round((cx + 40) * sx))))
        iy1 = max(0, min(h - 1, int(round(290 * sy))))
        iy2 = max(iy1 + 1, min(h, int(round(415 * sy))))
        patch = image[iy1:iy2, ix1:ix2].astype(np.float32)
        if patch.size == 0:
            continue
        b, g, r = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
        chroma = float(np.mean(np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)))
        if chroma >= 12.0:
            unlocked.append(idx)
    return unlocked or [1]


def choose_coop_difficulty_point(
    unlocked: list[int],
    preferred_difficulty: int = 0,
) -> tuple[int, tuple[int, int]]:
    """Return ``(chosen_level, tap_point)`` respecting unlocked levels."""
    valid = sorted({d for d in unlocked if 1 <= d <= len(COOP_DIFF_CENTERS_X)}) or [1]
    if preferred_difficulty > 0:
        if preferred_difficulty in valid:
            chosen = preferred_difficulty
        else:
            lower = [d for d in valid if d <= preferred_difficulty]
            chosen = max(lower) if lower else valid[-1]
    else:
        chosen = valid[-1]
    return chosen, (COOP_DIFF_CENTERS_X[chosen - 1], COOP_DIFF_Y)


def is_coop_reward_screen_entries(entries: list[dict[str, Any]]) -> bool:
    """Return True when the ASSAULT REPORT (攻坚战果) modal is open."""
    texts = [_clean(e.get("text")).upper() for e in entries if isinstance(e, dict)]
    return any("BOSS血量降低至" in t or "需要参与挑战次数" in t or "ASSAULTREPORT" in t for t in texts)


def parse_coop_reward_tabs(tab_entries: list[dict[str, Any]]) -> list[tuple[str, tuple[int, int]]]:
    """Extract bottom boss tabs ``[(label, tap_point), ...]`` sorted left-to-right."""
    tabs: list[tuple[int, str, tuple[int, int]]] = []
    for entry in tab_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text"))
        if len(cleaned) < 2 or "血量" in cleaned or "%" in cleaned:
            continue
        if not re.search(r"[\u4e00-\u9fff]", cleaned):
            continue
        center = _entry_center(entry)
        if center is not None and center[1] <= 665:
            tabs.append((center[0], cleaned, center))
    if not tabs:
        return list(COOP_REWARD_TAB_FALLBACKS)
    tabs.sort(key=lambda item: item[0])
    return [(label, pt) for _, label, pt in tabs]


def find_coop_reward_claim_point(claim_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Find an unclaimed '领取奖励' / 'CLAIM' button; strictly excludes '已领取' / 'CLAIMD'."""
    fallback_claim: tuple[int, int] | None = None
    for entry in claim_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text")).upper()
        if not cleaned:
            continue
        if any(bad in cleaned for bad in ("已领取", "CLAIMD", "CLAIMED")):
            continue
        center = _entry_center(entry)
        if center is None:
            continue
        if "领取奖励" in cleaned:
            return center
        if cleaned == "CLAIM" and fallback_claim is None:
            fallback_claim = center
    return fallback_claim

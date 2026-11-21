from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
import re
from typing import Any, Callable, Iterable

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None


DEFAULT_PLAY_TARGET = (640, 300)
LEADER_SKILL_POINT = (1190, 575)
DISCARD_BUTTON_POINT = (1070, 560)
NATIVE_AUTO_BUTTON_POINT = (126, 42)

NATIVE_AUTO_Y1 = 18
NATIVE_AUTO_Y2 = 66
NATIVE_AUTO_X1 = 102
NATIVE_AUTO_X2 = 150
NATIVE_AUTO_WHITE_RATIO_MIN = 0.05

HAND_BRIGHT_Y1 = 485
HAND_BRIGHT_Y2 = 535
HAND_BRIGHT_X1 = 280
HAND_BRIGHT_X2 = 950
HAND_BRIGHT_P90_MIN = 100.0

LEADER_RING_Y1 = 515
LEADER_RING_Y2 = 625
LEADER_RING_X1 = 1135
LEADER_RING_X2 = 1245
LEADER_BLUE_RATIO_MIN = 0.05

DIAMOND_BAND_Y1 = 555
DIAMOND_BAND_Y2 = 625
DIAMOND_BAND_X1 = 190
DIAMOND_BAND_X2 = 1000
CARD_DRAG_START_Y = 575
FAST_RUSH_FALLBACK_CENTERS: tuple[tuple[int, int], ...] = (
    (260, 575),
    (360, 575),
    (460, 575),
    (560, 575),
    (660, 575),
    (760, 575),
    (860, 575),
)

TOP_PILL_Y1 = 16
TOP_PILL_Y2 = 40
TOP_PILL_X1 = 515
TOP_PILL_X2 = 765
COST_TEXT_Y1 = 660
COST_TEXT_Y2 = 712
COST_TEXT_X1 = 1025
COST_TEXT_X2 = 1185

BATTLE_ENDED_MARKERS: tuple[str, ...] = (
    "作战胜利",
    "作战失败",
    "挑战失败",
    "作战数据",
    "下一步",
    "触碰空白区域退出",
    "点击空白区域退出",
    "任务完成",
    "MISSIONCOMPLETED",
    "前往作战",
    "驱逐任务",
    "快速编队",
)


@dataclass
class CardSlot:
    """Single detected hand card slot with reserved slots for future card-id/cost recognition."""

    index: int
    center: tuple[int, int]
    color: str = "neutral"
    cost: int | None = None
    card_id: str | None = None
    playable: bool = True


@dataclass
class BattleState:
    """Snapshot of the combat HUD and hand cards at a decision step."""

    current_cost: int | None = None
    max_cost: int | None = None
    hand_ready: bool = True
    leader_skill_ready: bool = False
    discard_ready: bool = True
    hand_cards: list[CardSlot] = field(default_factory=list)


@dataclass
class CardWeightConfig:
    """Extensible configuration matching the in-game custom card weight & settings model.

    Reserved extension points:
    - ``card_weights``: explicit priority score per ``card_id`` (higher plays first).
    - ``disabled_cards``: card IDs suppressed from auto-play (like the in-game card settings tab).
    - ``discard_weight``: threshold below which holding cards prefers triggering ``弃牌``.
    - ``target_zone_by_card``: per-card drag destination (ally left / center / enemy right).
    - ``custom_scorer``: optional callable ``(card, state, config) -> float`` hook.
    """

    card_weights: dict[str, int] = field(default_factory=dict)
    disabled_cards: set[str] = field(default_factory=set)
    discard_weight: int | None = None
    prefer_leader_skill: bool = True
    cost_preference: str = "left_to_right"
    min_cost_to_play: int = 2
    discard_when_stuck_at_cost: int = 10
    target_zone_by_card: dict[str, tuple[int, int]] = field(default_factory=dict)
    default_target_point: tuple[int, int] = DEFAULT_PLAY_TARGET
    play_mode: str = "weighted"
    custom_scorer: Callable[[CardSlot, BattleState, "CardWeightConfig"], float] | None = None


def is_battle_hud_likely_active(image: Any) -> bool:
    """Fast pixel-level check (<1ms) for active combat HUD to avoid per-step OCR overhead."""
    if np is None or image is None:
        return False
    arr = np.asarray(image)
    if arr.ndim != 3 or arr.shape[0] < COST_TEXT_Y2 or arr.shape[1] < COST_TEXT_X2:
        return False
    pill = arr[TOP_PILL_Y1:TOP_PILL_Y2, TOP_PILL_X1:TOP_PILL_X2, :3].astype(np.int16)
    dark_ratio = float((pill.max(axis=2) <= 55).mean())
    red_ratio = float(((pill[..., 2] >= 150) & ((pill[..., 2] - pill[..., 0]) >= 70)).mean())
    cost_box = arr[COST_TEXT_Y1:COST_TEXT_Y2, COST_TEXT_X1:COST_TEXT_X2, :3]
    cost_white = float((cost_box.min(axis=2) >= 180).mean())
    if dark_ratio >= 0.45 and red_ratio >= 0.012 and cost_white >= 0.008:
        return True
    # Tolerate skill-flash frames while still requiring the top-center red wave/timer badge.
    return dark_ratio >= 0.28 and red_ratio >= 0.006 and cost_white >= 0.005


def has_battle_ended_marker(texts: Iterable[str]) -> bool:
    """Return True when OCR texts from ActiveCheck already show victory/settlement/outside-battle UI."""
    for raw in texts:
        cleaned = re.sub(r"\s+", "", str(raw or "")).upper()
        if not cleaned:
            continue
        if any(marker in cleaned for marker in BATTLE_ENDED_MARKERS):
            return True
    return False


def is_native_auto_enabled(image: Any) -> bool:
    """Return True when the top-left native auto-battle button is illuminated (active)."""
    if np is None or image is None:
        return False
    arr = np.asarray(image)
    if arr.ndim != 3 or arr.shape[0] < NATIVE_AUTO_Y2 or arr.shape[1] < NATIVE_AUTO_X2:
        return False
    patch = arr[NATIVE_AUTO_Y1:NATIVE_AUTO_Y2, NATIVE_AUTO_X1:NATIVE_AUTO_X2, :3]
    white_ratio = (patch.min(axis=2) >= 210).mean()
    return float(white_ratio) >= NATIVE_AUTO_WHITE_RATIO_MIN


def is_hand_bright(image: Any) -> bool:
    """Return True when hand cards are lit/interactive (False during wave-run lock)."""
    if np is None or image is None:
        return True
    arr = np.asarray(image)
    if arr.ndim != 3 or arr.shape[0] < HAND_BRIGHT_Y2 or arr.shape[1] < HAND_BRIGHT_X2:
        return True
    band = arr[HAND_BRIGHT_Y1:HAND_BRIGHT_Y2, HAND_BRIGHT_X1:HAND_BRIGHT_X2, :3]
    return float(np.percentile(band, 90)) >= HAND_BRIGHT_P90_MIN


def is_leader_skill_ready(image: Any) -> bool:
    """Detect the glowing blue ring around the captain's leader skill button."""
    if np is None or image is None:
        return False
    arr = np.asarray(image)
    if arr.ndim != 3 or arr.shape[0] < LEADER_RING_Y2 or arr.shape[1] < LEADER_RING_X2:
        return False
    ring = arr[LEADER_RING_Y1:LEADER_RING_Y2, LEADER_RING_X1:LEADER_RING_X2, :3].astype(np.int16)
    b = ring[..., 0]
    r = ring[..., 2]
    blue_glow = ((b >= 150) & ((b - r) >= 60)).mean()
    return float(blue_glow) >= LEADER_BLUE_RATIO_MIN


def parse_current_cost(entries: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    """Parse ``(current_cost, max_cost)`` from bottom-right cost OCR results."""
    for entry in entries:
        text = str(entry.get("text") or "").strip() if isinstance(entry, dict) else ""
        if not text:
            continue
        match = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", text)
        if match:
            cur = int(match.group(1))
            max_v = int(match.group(2))
            if 0 <= cur <= max_v <= 20:
                return cur, max_v
    return None, None


def _classify_band_color(bgr_slice: Any) -> str:
    if np is None:
        return "neutral"
    pixels = bgr_slice.reshape(-1, 3).astype(np.int16)
    if pixels.size == 0:
        return "neutral"
    sat = pixels.max(axis=1) - pixels.min(axis=1)
    colorful = pixels[sat >= 45]
    if colorful.shape[0] < 10:
        return "neutral"
    mean_b, mean_g, mean_r = colorful.mean(axis=0)
    if mean_r >= mean_b + 35 and mean_r >= mean_g + 25:
        return "red"
    if mean_r >= 130 and mean_g >= 115 and mean_b <= min(mean_r, mean_g) - 35:
        return "yellow"
    if mean_b >= mean_r + 30 and mean_b >= mean_g + 15:
        return "blue"
    if mean_b >= 100 and mean_r >= 95 and mean_g + 25 < min(mean_b, mean_r):
        return "purple"
    return "neutral"


def detect_hand_cards(image: Any) -> list[CardSlot]:
    """Locate visible hand cards from the diamond skill-icon band left-to-right."""
    if np is None or image is None:
        return []
    arr = np.asarray(image)
    if arr.ndim != 3 or arr.shape[0] < DIAMOND_BAND_Y2 or arr.shape[1] < DIAMOND_BAND_X2:
        return []

    band = arr[DIAMOND_BAND_Y1:DIAMOND_BAND_Y2, DIAMOND_BAND_X1:DIAMOND_BAND_X2, :3].astype(np.int16)
    sat = band.max(axis=2) - band.min(axis=2)
    val = band.max(axis=2)
    icon_mask = (val >= 160) & ((sat >= 45) | (val >= 225))
    col_score = icon_mask.mean(axis=0)
    active = col_score >= 0.18

    raw_spans: list[tuple[int, int]] = []
    in_seg = False
    start = 0
    for idx, flag in enumerate(active):
        if flag and not in_seg:
            in_seg = True
            start = idx
        elif not flag and in_seg:
            in_seg = False
            if idx - start >= 8:
                raw_spans.append((start, idx))
    if in_seg and len(active) - start >= 8:
        raw_spans.append((start, len(active)))

    # Merge tiny internal gaps (e.g., dark borders inside a single diamond icon)
    merged: list[tuple[int, int]] = []
    for s, e in raw_spans:
        if merged and s - merged[-1][1] <= 12:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))

    # Filter tiny fragments and collapse peaks closer than 36px (full leftmost card splits)
    centers: list[tuple[int, int, int]] = []
    for s, e in merged:
        if e - s < 12:
            continue
        cx = DIAMOND_BAND_X1 + int(round((s + e) / 2.0))
        if centers and cx - centers[-1][2] < 36:
            prev_s, prev_e, _ = centers[-1]
            new_s, new_e = prev_s, e
            centers[-1] = (new_s, new_e, DIAMOND_BAND_X1 + int(round((new_s + new_e) / 2.0)))
        else:
            centers.append((s, e, cx))

    slots: list[CardSlot] = []
    for index, (s, e, cx) in enumerate(centers[:10]):
        color = _classify_band_color(arr[DIAMOND_BAND_Y1:DIAMOND_BAND_Y2, DIAMOND_BAND_X1 + s : DIAMOND_BAND_X1 + e, :3])
        slots.append(
            CardSlot(
                index=index,
                center=(cx, CARD_DRAG_START_Y),
                color=color,
            )
        )
    return slots


def score_card_action(
    card: CardSlot,
    state: BattleState,
    config: CardWeightConfig,
) -> float:
    """Score a candidate card play. Higher score plays first; -inf means unplayable."""
    if not card.playable:
        return -math.inf
    if card.card_id and card.card_id in config.disabled_cards:
        return -math.inf
    if card.cost is not None and state.current_cost is not None and card.cost > state.current_cost:
        return -math.inf

    if config.custom_scorer is not None:
        return float(config.custom_scorer(card, state, config))

    if card.card_id and card.card_id in config.card_weights:
        return float(config.card_weights[card.card_id])

    # Fallback heuristic before per-card icon recognition is wired in:
    # slight left-to-right tie-breaker (newly drawn cards enter on the left).
    base = float(config.card_weights.get(f"color:{card.color}", 0.0))
    if card.cost is not None:
        if config.cost_preference == "low_cost_first":
            base += 20.0 - float(card.cost)
        elif config.cost_preference == "high_cost_first":
            base += float(card.cost)
    return base - card.index * 0.01


def resolve_card_target_point(card: CardSlot, config: CardWeightConfig) -> tuple[int, int]:
    """Resolve drag destination point for a card (extensible for ally vs enemy targets)."""
    if card.card_id and card.card_id in config.target_zone_by_card:
        return config.target_zone_by_card[card.card_id]
    return config.default_target_point


def fast_hand_signature(image: Any) -> tuple[int, ...] | None:
    """Compute a sub-millisecond coarse hand-band signature to detect card/hand changes without OCR."""
    if np is None or image is None:
        return None
    arr = np.asarray(image)
    if arr.ndim != 3 or arr.shape[0] < DIAMOND_BAND_Y2 or arr.shape[1] < DIAMOND_BAND_X2:
        return None
    band = arr[DIAMOND_BAND_Y1:DIAMOND_BAND_Y2:8, DIAMOND_BAND_X1:DIAMOND_BAND_X2:32, :3]
    quantized = (band.mean(axis=0).mean(axis=1) // 16).astype(int)
    return tuple(int(v) for v in quantized)


def merge_fast_rush_slots(detected: list[CardSlot]) -> list[CardSlot]:
    """Fill dark-card gaps between detected slots, falling back to center lanes only when empty."""
    if not detected:
        return [
            CardSlot(index=idx, center=pt, color="neutral")
            for idx, pt in enumerate(((460, 575), (560, 575), (660, 575), (760, 575)))
        ]

    ordered = sorted(detected, key=lambda slot: slot.center[0])
    merged: list[CardSlot] = [ordered[0]]
    for slot in ordered[1:]:
        prev_x = merged[-1].center[0]
        gap = slot.center[0] - prev_x
        if gap >= 135:
            steps = max(1, int(round(gap / 85.0)) - 1)
            for step in range(1, steps + 1):
                fill_x = int(round(prev_x + gap * step / (steps + 1)))
                merged.append(CardSlot(index=0, center=(fill_x, CARD_DRAG_START_Y), color="neutral"))
        merged.append(slot)

    return [
        CardSlot(
            index=idx,
            center=slot.center,
            color=slot.color,
            cost=slot.cost,
            card_id=slot.card_id,
            playable=slot.playable,
        )
        for idx, slot in enumerate(merged)
    ]


def choose_fast_rush_action(
    state: BattleState,
    config: CardWeightConfig | None = None,
    *,
    stuck_cycles: int = 0,
    leader_skill_cooldown: int = 0,
    skipped_indices: set[int] | tuple[int, ...] = (),
    rng: Any = None,
    burst_count: int = 2,
) -> dict[str, Any]:
    """Fast-rush strategy: fire leader skill immediately when ready and throw random hand cards."""
    cfg = config or CardWeightConfig(play_mode="fast_rush")
    chooser = rng if rng is not None else random
    skipped = set(skipped_indices)

    if not state.hand_ready:
        return {"action": "wait", "reason": "hand_locked_transition"}

    if cfg.prefer_leader_skill and state.leader_skill_ready and leader_skill_cooldown <= 0:
        return {
            "action": "leader_skill",
            "reason": "leader_skill_ready",
            "start_point": LEADER_SKILL_POINT,
            "target_point": cfg.default_target_point,
        }

    if state.discard_ready and stuck_cycles >= 3:
        return {
            "action": "discard",
            "reason": "fast_rush_stuck_discard",
            "point": DISCARD_BUTTON_POINT,
        }

    cards = merge_fast_rush_slots(list(state.hand_cards))
    available = [c for c in cards if c.index not in skipped and c.playable]
    if not available:
        available = [c for c in cards if c.playable] or cards

    chosen = chooser.choice(available)
    target_pt = resolve_card_target_point(chosen, cfg)
    burst_plays = [(chosen.index, chosen.center, target_pt)]
    remaining = [c for c in available if c.index != chosen.index]
    count = max(1, int(burst_count or 1))
    while len(burst_plays) < count and remaining:
        extra = chooser.choice(remaining)
        remaining = [c for c in remaining if c.index != extra.index]
        burst_plays.append((extra.index, extra.center, resolve_card_target_point(extra, cfg)))

    return {
        "action": "play_card",
        "reason": "fast_rush_random_card",
        "card_index": chosen.index,
        "card_id": chosen.card_id,
        "color": chosen.color,
        "score": 1.0,
        "start_point": chosen.center,
        "target_point": target_pt,
        "burst_plays": burst_plays,
    }


def decide_battle_action(
    state: BattleState,
    config: CardWeightConfig | None = None,
    *,
    stuck_cycles: int = 0,
    leader_skill_cooldown: int = 0,
    skipped_indices: set[int] | tuple[int, ...] = (),
    rng: Any = None,
) -> dict[str, Any]:
    """Choose the next battle action given current state and weight configuration."""
    cfg = config or CardWeightConfig()
    if str(cfg.play_mode or "weighted").strip().lower() == "fast_rush":
        return choose_fast_rush_action(
            state,
            cfg,
            stuck_cycles=stuck_cycles,
            leader_skill_cooldown=leader_skill_cooldown,
            skipped_indices=skipped_indices,
            rng=rng,
        )
    skipped = set(skipped_indices)

    if not state.hand_ready:
        return {"action": "wait", "reason": "hand_locked_transition"}

    if cfg.prefer_leader_skill and state.leader_skill_ready and leader_skill_cooldown <= 0:
        return {
            "action": "leader_skill",
            "reason": "leader_skill_ready",
            "start_point": LEADER_SKILL_POINT,
            "target_point": cfg.default_target_point,
        }

    scored_cards: list[tuple[float, CardSlot]] = []
    for card in state.hand_cards:
        if card.index in skipped:
            continue
        score = score_card_action(card, state, cfg)
        if math.isfinite(score):
            scored_cards.append((score, card))

    if not scored_cards and skipped and state.hand_cards:
        # All visible indices were tried; fall back to full list unless stuck enough to discard.
        for card in state.hand_cards:
            score = score_card_action(card, state, cfg)
            if math.isfinite(score):
                scored_cards.append((score, card))

    if scored_cards:
        best_score, best_card = max(scored_cards, key=lambda item: item[0])
        if cfg.discard_weight is not None and state.discard_ready and best_score < cfg.discard_weight:
            return {
                "action": "discard",
                "reason": "below_discard_weight",
                "point": DISCARD_BUTTON_POINT,
                "best_score": best_score,
            }
        # Avoid spinning on 0-cost/insufficient-cost guesswork if cost is known very low.
        if (
            state.current_cost is not None
            and best_card.cost is None
            and state.current_cost < cfg.min_cost_to_play
        ):
            return {
                "action": "wait",
                "reason": "waiting_for_cost",
                "current_cost": state.current_cost,
            }
        return {
            "action": "play_card",
            "reason": "highest_weight_card",
            "card_index": best_card.index,
            "card_id": best_card.card_id,
            "color": best_card.color,
            "score": best_score,
            "start_point": best_card.center,
            "target_point": resolve_card_target_point(best_card, cfg),
        }

    if (
        state.discard_ready
        and (
            (state.current_cost is not None and state.current_cost >= cfg.discard_when_stuck_at_cost)
            or stuck_cycles >= 5
        )
    ):
        return {
            "action": "discard",
            "reason": "hand_stuck_discard",
            "point": DISCARD_BUTTON_POINT,
        }

    return {"action": "wait", "reason": "no_playable_card"}

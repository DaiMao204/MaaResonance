from __future__ import annotations

import time
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from agent.utils.action_helpers import ocr_roi, parse_action_param, swipe_points, tap_point
from agent.utils.input_guard import (
    safe_screencap,
    sleep_with_stop,
    wait_mouse_button_released,
)
from maa_resonance.logic.battle_autoplay import (
    BattleState,
    CardWeightConfig,
    NATIVE_AUTO_BUTTON_POINT,
    decide_battle_action,
    detect_hand_cards,
    fast_hand_signature,
    has_battle_ended_marker,
    is_battle_hud_likely_active,
    is_hand_bright,
    is_leader_skill_ready,
    is_native_auto_enabled,
    parse_current_cost,
)

COST_OCR_ROI = [1020, 645, 250, 75]
TOP_WAVE_OCR_ROI = [500, 0, 260, 60]
EXIT_MISS_STREAK_LIMIT = 5
EXIT_MISS_SECONDS_NORMAL = 2.5
EXIT_MISS_STREAK_NATIVE_AUTO = 7
EXIT_MISS_SECONDS_NATIVE_AUTO = 3.5
NATIVE_AUTO_OFF_CONFIRM_FRAMES = 3
NATIVE_AUTO_OFF_CONFIRM_INTERVAL = 0.25
BATTLE_OPTION_NODE_SUFFIXES = (
    "OptPlayMode",
    "OptPreferNativeAuto",
    "OptLeaderSkill",
    "OptMinCost",
)


def _parse_action_param(argv: CustomAction.RunArg) -> dict[str, Any]:
    return parse_action_param(getattr(argv, "custom_action_param", None))


def _resolve_action_params(context: Context, argv: CustomAction.RunArg) -> dict[str, Any]:
    merged = dict(_parse_action_param(argv))
    node_name = str(getattr(argv, "node_name", "") or "").strip()
    get_node_data = getattr(context, "get_node_data", None)
    if not node_name or not callable(get_node_data):
        return merged

    for suffix in BATTLE_OPTION_NODE_SUFFIXES:
        try:
            node_data = get_node_data(f"{node_name}{suffix}")
        except Exception:
            node_data = None
        if isinstance(node_data, dict):
            attach = node_data.get("attach")
            if isinstance(attach, dict):
                merged.update(attach)
    return merged


def _build_weight_config(params: dict[str, Any]) -> CardWeightConfig:
    raw_weights = params.get("card_weights")
    card_weights: dict[str, int] = {}
    if isinstance(raw_weights, dict):
        for key, value in raw_weights.items():
            try:
                card_weights[str(key)] = int(value)
            except (TypeError, ValueError):
                continue

    raw_disabled = params.get("disabled_cards") or ()
    disabled_cards = {str(item).strip() for item in raw_disabled if str(item).strip()}

    raw_discard_weight = params.get("discard_weight")
    discard_weight = int(raw_discard_weight) if raw_discard_weight is not None else None

    return CardWeightConfig(
        card_weights=card_weights,
        disabled_cards=disabled_cards,
        discard_weight=discard_weight,
        prefer_leader_skill=bool(params.get("prefer_leader_skill", True)),
        cost_preference=str(params.get("cost_preference") or "left_to_right"),
        min_cost_to_play=int(params.get("min_cost_to_play", 2) or 0),
        discard_when_stuck_at_cost=int(params.get("discard_when_stuck_at_cost", 10) or 10),
        play_mode=str(params.get("play_mode") or "fast_rush").strip().lower(),
    )


def _ocr_roi(context: Context, image: Any, node_name: str, roi: list[int]) -> list[dict[str, Any]]:
    return ocr_roi(context, image, node_name, roi)


def _extract_active_check_texts(detail: Any) -> list[str]:
    texts: list[str] = []

    def _collect_from_payload(payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        for key in ("bottom_texts", "top_texts"):
            items = payload.get(key)
            if isinstance(items, (list, tuple)):
                texts.extend(str(item) for item in items if item is not None)
        if "detail" in payload:
            _collect_from_payload(payload.get("detail"))
        if "all" in payload and isinstance(payload["all"], (list, tuple)):
            for entry in payload["all"]:
                _collect_from_payload(entry)

    if detail is None:
        return texts
    all_results = getattr(detail, "all_results", None) or ()
    for item in all_results:
        item_detail = item.get("detail") if isinstance(item, dict) else getattr(item, "detail", None)
        _collect_from_payload(item_detail)
    _collect_from_payload(getattr(detail, "raw_detail", None))
    return texts


def _check_fight_status(context: Context, image: Any, node_name: str) -> tuple[bool, bool]:
    """Return (is_active, definitely_ended)."""
    if is_battle_hud_likely_active(image):
        return (True, False)
    detail = context.run_recognition(
        f"{node_name}ActiveCheck",
        image,
        {
            f"{node_name}ActiveCheck": {
                "recognition": "Custom",
                "custom_recognition": "manual_two_city_business_fight_active",
                "action": "DoNothing",
            }
        },
    )
    if detail and getattr(detail, "hit", False):
        return (True, False)
    if has_battle_ended_marker(_extract_active_check_texts(detail)):
        return (False, True)
    return (False, False)


def _is_fight_still_active(context: Context, image: Any, node_name: str) -> bool:
    return _check_fight_status(context, image, node_name)[0]


def _tap_point(context: Context, node_name: str, x: int, y: int) -> bool:
    if not wait_mouse_button_released(context, max_wait_sec=0.6):
        return False
    return tap_point(context, node_name, (int(x), int(y)), max_wait_sec=0.6, wait_release=False)


def _drag_card(
    context: Context,
    node_name: str,
    start_point: tuple[int, int],
    target_point: tuple[int, int],
    *,
    duration: int = 150,
) -> bool:
    if not wait_mouse_button_released(context, max_wait_sec=0.6):
        return False
    return swipe_points(
        context,
        node_name,
        start_point,
        target_point,
        duration=duration,
        end_hold=0,
        max_wait_sec=0.6,
        node_suffix="DragCard",
        wait_release=False,
    )


def _recognize_cards_for_step(
    image: Any,
    config: CardWeightConfig,
) -> list[Any]:
    """Detect current hand card positions."""
    _ = config
    return detect_hand_cards(image)


@AgentServer.custom_action("battle_autoplay_loop")
class BattleAutoplayLoopAction(CustomAction):
    """Experimental combat loop: prefers native auto-battle, otherwise fast-rushes hand cards."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _resolve_action_params(context, argv)
        config = _build_weight_config(params)
        is_fast_rush = config.play_mode == "fast_rush"
        if is_fast_rush:
            print("[AutoBattle] Fast-rush mode active (leader skill priority + random card throw).", flush=True)

        prefer_native_auto = bool(params.get("prefer_native_auto", True))
        raw_max_steps = int(params.get("max_steps", 240) or 240)
        max_steps = max(raw_max_steps, 1200) if is_fast_rush else raw_max_steps
        exit_streak_limit = int(params.get("exit_streak_limit", EXIT_MISS_STREAK_LIMIT) or EXIT_MISS_STREAK_LIMIT)
        max_native_probe_attempts = 1 if is_fast_rush else 2

        miss_streak = 0
        miss_started_at: float | None = None
        stuck_cycles = 0
        leader_cooldown = 0
        discard_cooldown = 0
        skipped_indices: set[int] = set()
        last_tried_index: int | None = None
        last_signature: tuple[Any, ...] | None = None
        native_auto_attempts = 0
        native_auto_active = False
        native_auto_off_streak = 0
        last_off_sample_at = 0.0

        for _ in range(max_steps):
            image = safe_screencap(context)
            if image is None:
                return False

            is_active, definitely_ended = _check_fight_status(context, image, argv.node_name)
            if not is_active:
                if definitely_ended:
                    print("[AutoBattle] Settlement/exit screen detected; fight ended.", flush=True)
                    return True
                now = time.monotonic()
                if miss_started_at is None:
                    miss_started_at = now
                miss_streak += 1
                req_streak = (
                    max(exit_streak_limit, EXIT_MISS_STREAK_NATIVE_AUTO)
                    if native_auto_active
                    else exit_streak_limit
                )
                req_seconds = (
                    EXIT_MISS_SECONDS_NATIVE_AUTO
                    if native_auto_active
                    else EXIT_MISS_SECONDS_NORMAL
                )
                if miss_streak >= req_streak and (now - miss_started_at) >= req_seconds:
                    print("[AutoBattle] Fight ended.", flush=True)
                    return True
                native_auto_off_streak = 0
                if not sleep_with_stop(context, 0.45 if native_auto_active else 0.35):
                    return False
                continue

            miss_streak = 0
            miss_started_at = None
            hand_ready = is_hand_bright(image)

            if native_auto_attempts < max_native_probe_attempts:
                if prefer_native_auto:
                    if is_native_auto_enabled(image):
                        native_auto_active = True
                        native_auto_off_streak = 0
                        native_auto_attempts = max_native_probe_attempts
                        print("[AutoBattle] Native auto-battle already enabled; standing by.", flush=True)
                    elif hand_ready and is_battle_hud_likely_active(image):
                        now = time.monotonic()
                        if (
                            native_auto_off_streak == 0
                            or (now - last_off_sample_at) >= NATIVE_AUTO_OFF_CONFIRM_INTERVAL
                        ):
                            native_auto_off_streak += 1
                            last_off_sample_at = now
                        if native_auto_off_streak < NATIVE_AUTO_OFF_CONFIRM_FRAMES:
                            if not sleep_with_stop(context, NATIVE_AUTO_OFF_CONFIRM_INTERVAL):
                                return False
                            continue

                        native_auto_attempts += 1
                        native_auto_off_streak = 0
                        px, py = NATIVE_AUTO_BUTTON_POINT
                        if not _tap_point(
                            context, f"{argv.node_name}NativeAutoProbe{native_auto_attempts}", px, py
                        ):
                            return False
                        if not sleep_with_stop(context, 0.35):
                            return False
                        probe_img = safe_screencap(context)
                        if probe_img is None:
                            return False
                        if is_native_auto_enabled(probe_img):
                            native_auto_active = True
                            native_auto_attempts = max_native_probe_attempts
                            print("[AutoBattle] Enabled native auto-battle; standing by.", flush=True)
                        elif native_auto_attempts >= max_native_probe_attempts:
                            print(
                                "[AutoBattle] Native auto-battle unavailable; taking over hand cards.",
                                flush=True,
                            )
                    else:
                        native_auto_off_streak = 0
                else:
                    # Explicitly requested manual/custom autoplay: turn off native auto if active (e.g. training).
                    if is_native_auto_enabled(image):
                        native_auto_attempts += 1
                        px, py = NATIVE_AUTO_BUTTON_POINT
                        if not _tap_point(
                            context, f"{argv.node_name}DisableNativeAuto{native_auto_attempts}", px, py
                        ):
                            return False
                        print("[AutoBattle] Turned off native auto-battle to take over hand cards.", flush=True)
                        if not sleep_with_stop(context, 0.20 if is_fast_rush else 0.30):
                            return False
                        continue
                    elif hand_ready:
                        native_auto_attempts = max_native_probe_attempts

            if prefer_native_auto and not native_auto_active and is_native_auto_enabled(image):
                native_auto_active = True
                native_auto_off_streak = 0
                native_auto_attempts = max_native_probe_attempts
                print("[AutoBattle] Native auto-battle detected active; standing by.", flush=True)

            if native_auto_active:
                if not sleep_with_stop(context, 0.50):
                    return False
                continue

            leader_ready = is_leader_skill_ready(image)
            if is_fast_rush:
                current_cost, max_cost = None, None
                cards = detect_hand_cards(image) if hand_ready else []
                cur_signature = (len(cards), fast_hand_signature(image))
            else:
                cost_entries = _ocr_roi(context, image, f"{argv.node_name}CostOCR", COST_OCR_ROI)
                current_cost, max_cost = parse_current_cost(cost_entries)
                cards = _recognize_cards_for_step(image, config) if hand_ready else []
                cur_signature = (
                    current_cost,
                    len(cards),
                    tuple((c.center[0] // 24, c.color) for c in cards),
                )
            if last_tried_index is not None and last_signature == cur_signature:
                # Previous drag did not change hand/cost (likely high-cost or unplayable); rotate right.
                skipped_indices.add(last_tried_index)
                if len(skipped_indices) >= max(1, len(cards)):
                    skipped_indices.clear()
                    stuck_cycles += 1
            elif last_signature is not None and cur_signature != last_signature:
                skipped_indices.clear()
                stuck_cycles = 0

            state = BattleState(
                current_cost=current_cost,
                max_cost=max_cost,
                hand_ready=hand_ready,
                leader_skill_ready=leader_ready,
                discard_ready=discard_cooldown <= 0,
                hand_cards=cards,
            )
            decision = decide_battle_action(
                state,
                config,
                stuck_cycles=stuck_cycles,
                leader_skill_cooldown=leader_cooldown,
                skipped_indices=skipped_indices,
            )
            action = decision["action"]

            drag_duration = 65 if is_fast_rush else 150
            if action == "leader_skill":
                sp = decision["start_point"]
                tp = decision["target_point"]
                print(f"[AutoBattle] leader_skill drag {sp} -> {tp}", flush=True)
                if not _drag_card(context, f"{argv.node_name}Leader", sp, tp, duration=drag_duration):
                    return False
                last_tried_index = None
                last_signature = None
                stuck_cycles = 0
                leader_cooldown = 3 if is_fast_rush else 2
                discard_cooldown = max(0, discard_cooldown - 1)
                if not sleep_with_stop(context, 0.03 if is_fast_rush else 0.20, step=0.03):
                    return False
            elif action == "play_card":
                burst = decision.get("burst_plays") if is_fast_rush else None
                if burst:
                    for b_idx, (card_idx, sp, tp) in enumerate(burst):
                        if not _drag_card(context, f"{argv.node_name}B{b_idx}", sp, tp, duration=drag_duration):
                            return False
                        last_tried_index = int(card_idx)
                        if b_idx + 1 < len(burst):
                            if not sleep_with_stop(context, 0.01, step=0.01):
                                return False
                    print(
                        f"[AutoBattle] fast_rush burst={len(burst)} cards={[(x[0], x[1]) for x in burst]}",
                        flush=True,
                    )
                else:
                    sp = decision["start_point"]
                    tp = decision["target_point"]
                    print(
                        f"[AutoBattle] play_card idx={decision['card_index']} "
                        f"card={decision.get('card_id') or decision['color']} "
                        f"score={decision.get('score', 0):.2f} cost={current_cost}/{max_cost} {sp} -> {tp}",
                        flush=True,
                    )
                    if not _drag_card(context, argv.node_name, sp, tp, duration=drag_duration):
                        return False
                    last_tried_index = int(decision["card_index"])
                last_signature = cur_signature
                leader_cooldown = max(0, leader_cooldown - 1)
                discard_cooldown = max(0, discard_cooldown - 1)
                if not sleep_with_stop(context, 0.01 if is_fast_rush else 0.10, step=0.02):
                    return False
            elif action == "discard":
                px, py = decision["point"]
                print(f"[AutoBattle] discard ({decision['reason']}) @ ({px}, {py})", flush=True)
                if not _tap_point(context, argv.node_name, px, py):
                    return False
                last_tried_index = None
                last_signature = None
                skipped_indices.clear()
                stuck_cycles = 0
                leader_cooldown = max(0, leader_cooldown - 1)
                discard_cooldown = 8 if is_fast_rush else 12
                if not sleep_with_stop(context, 0.10 if is_fast_rush else 0.30, step=0.05):
                    return False
            else:
                last_tried_index = None
                last_signature = None
                stuck_cycles += 1
                leader_cooldown = max(0, leader_cooldown - 1)
                discard_cooldown = max(0, discard_cooldown - 1)
                if not sleep_with_stop(context, 0.05 if is_fast_rush else 0.16, step=0.05):
                    return False

        print("[AutoBattle] Reached max step limit.", flush=True)
        return True

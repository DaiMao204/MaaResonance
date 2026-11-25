import random
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from agent import battle_autoplay_action as baa
from maa_resonance.logic.battle_autoplay import (
    BattleState,
    CardSlot,
    CardWeightConfig,
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


class BattleAutoplayLogicTest(unittest.TestCase):
    def test_parse_current_cost(self):
        self.assertEqual(parse_current_cost([{"text": "12/12"}, {"text": "MAX"}]), (12, 12))
        self.assertEqual(parse_current_cost([{"text": "10 / 12"}]), (10, 12))
        self.assertEqual(parse_current_cost([{"text": "COST"}]), (None, None))

    def test_hand_brightness_and_leader_skill_glow(self):
        dark_frame = np.full((720, 1280, 3), 38, dtype=np.uint8)
        self.assertFalse(is_hand_bright(dark_frame))
        self.assertFalse(is_leader_skill_ready(dark_frame))

        bright_frame = dark_frame.copy()
        bright_frame[490:530, 300:900, :] = 190
        bright_frame[525:615, 1145:1235, 0] = 240
        bright_frame[525:615, 1145:1235, 2] = 40
        self.assertTrue(is_hand_bright(bright_frame))
        self.assertTrue(is_leader_skill_ready(bright_frame))

    def test_native_auto_enabled_detection(self):
        disabled_or_off = np.full((720, 1280, 3), 75, dtype=np.uint8)
        self.assertFalse(is_native_auto_enabled(disabled_or_off))

        enabled = disabled_or_off.copy()
        enabled[28:54, 114:138, :] = 245
        self.assertTrue(is_native_auto_enabled(enabled))

    def test_detect_hand_cards_extracts_diamond_centers(self):
        frame = np.full((720, 1280, 3), 35, dtype=np.uint8)
        # Draw 3 separated colorful diamond bands (red, yellow, purple) in BGR
        frame[560:620, 240:290, :] = (20, 30, 220)
        frame[560:620, 330:370, :] = (20, 210, 220)
        frame[560:620, 415:455, :] = (210, 40, 190)

        cards = detect_hand_cards(frame)
        self.assertEqual(len(cards), 3)
        self.assertEqual([c.color for c in cards], ["red", "yellow", "purple"])
        self.assertLess(cards[0].center[0], cards[1].center[0])
        self.assertLess(cards[1].center[0], cards[2].center[0])

    def test_decide_action_honors_weights_disabled_and_discard_threshold(self):
        config = CardWeightConfig(
            card_weights={"红之惨剧": 90, "连涌": 50, "洗牌": 80},
            disabled_cards={"红之惨剧"},
            discard_weight=60,
            target_zone_by_card={"洗牌": (420, 300)},
        )
        cards = [
            CardSlot(index=0, center=(260, 575), cost=5, card_id="红之惨剧"),
            CardSlot(index=1, center=(350, 575), cost=2, card_id="连涌"),
            CardSlot(index=2, center=(440, 575), cost=3, card_id="洗牌"),
        ]
        state = BattleState(current_cost=6, max_cost=12, hand_ready=True, hand_cards=cards)

        # 红之惨剧 is disabled -> picks 洗牌 (weight 80) and uses its custom target zone
        act1 = decide_battle_action(state, config)
        self.assertEqual(act1["action"], "play_card")
        self.assertEqual(act1["card_id"], "洗牌")
        self.assertEqual(act1["target_point"], (420, 300))

        # Only 连涌 (weight 50 < discard_weight 60) remains -> triggers discard
        state.hand_cards = [cards[1]]
        act2 = decide_battle_action(state, config)
        self.assertEqual(act2["action"], "discard")

    def test_decide_action_waits_when_hand_dark_or_plays_leader_first(self):
        cards = [CardSlot(index=0, center=(260, 575), color="red")]
        dark_state = BattleState(hand_ready=False, leader_skill_ready=True, hand_cards=cards)
        self.assertEqual(decide_battle_action(dark_state)["action"], "wait")

        ready_state = BattleState(hand_ready=True, leader_skill_ready=True, hand_cards=cards)
        leader_dec = decide_battle_action(ready_state)
        self.assertEqual(leader_dec["action"], "leader_skill")
        self.assertEqual(leader_dec["start_point"], (1190, 575))
        self.assertEqual(leader_dec["target_point"], (640, 300))

        # When leader_skill is cooling down, fall back to playing hand cards
        cd_dec = decide_battle_action(ready_state, leader_skill_cooldown=1)
        self.assertEqual(cd_dec["action"], "play_card")

    def test_decide_action_rotates_past_skipped_left_cards_and_fast_hud_check(self):
        cards = [
            CardSlot(index=0, center=(260, 575), color="red"),
            CardSlot(index=1, center=(360, 575), color="yellow"),
            CardSlot(index=2, center=(460, 575), color="blue"),
        ]
        state = BattleState(current_cost=4, max_cost=12, hand_ready=True, hand_cards=cards)
        dec = decide_battle_action(state, skipped_indices={0})
        self.assertEqual(dec["action"], "play_card")
        self.assertEqual(dec["card_index"], 1)

        blank = np.full((720, 1280, 3), 20, dtype=np.uint8)
        self.assertFalse(is_battle_hud_likely_active(blank))
        hud = blank.copy()
        hud[16:40, 515:765, :] = 30
        hud[22:32, 635:650, :] = (20, 20, 220)
        hud[670:700, 1030:1150, :] = 230
        self.assertTrue(is_battle_hud_likely_active(hud))

    def test_fast_rush_mode_fires_leader_first_throws_random_and_discards_when_stuck(self):
        cfg = CardWeightConfig(play_mode="fast_rush")
        cards = [
            CardSlot(index=0, center=(260, 575), color="red"),
            CardSlot(index=1, center=(360, 575), color="blue"),
            CardSlot(index=2, center=(460, 575), color="yellow"),
        ]
        # Leader ready -> fires immediately
        leader_state = BattleState(hand_ready=True, leader_skill_ready=True, hand_cards=cards)
        self.assertEqual(decide_battle_action(leader_state, cfg)["action"], "leader_skill")

        # Leader on cooldown -> picks random non-skipped card
        rng = random.Random(42)
        state = BattleState(hand_ready=True, leader_skill_ready=False, discard_ready=True, hand_cards=cards)
        dec = decide_battle_action(state, cfg, skipped_indices={0}, rng=rng)
        self.assertEqual(dec["action"], "play_card")
        self.assertIn(dec["card_index"], {1, 2})

        # Dark-card gap interpolation adds a middle slot when adjacent cards are >=135px apart
        gapped_state = BattleState(
            hand_ready=True,
            leader_skill_ready=False,
            hand_cards=[
                CardSlot(index=0, center=(300, 575), color="red"),
                CardSlot(index=1, center=(480, 575), color="blue"),
            ],
        )
        gap_dec = decide_battle_action(gapped_state, cfg, rng=rng)
        self.assertEqual(gap_dec["action"], "play_card")
        self.assertTrue(any(p[1] == (390, 575) for p in gap_dec["burst_plays"]) or len(gap_dec["burst_plays"]) == 2)

        # Fallback slots when detect_hand_cards returned empty while hand_ready=True
        empty_state = BattleState(hand_ready=True, leader_skill_ready=False, hand_cards=[])
        fallback_dec = decide_battle_action(empty_state, cfg, rng=rng)
        self.assertEqual(fallback_dec["action"], "play_card")
        self.assertEqual(len(fallback_dec["burst_plays"]), 2)

        # Stuck >= 3 cycles with discard ready -> discards to refresh hand
        stuck_dec = decide_battle_action(state, cfg, stuck_cycles=3, rng=rng)
        self.assertEqual(stuck_dec["action"], "discard")

        # Fast hand signature detects pixel change
        f1 = np.zeros((720, 1280, 3), dtype=np.uint8)
        f2 = f1.copy()
        f2[560:610, 220:320, :] = 220
        self.assertNotEqual(fast_hand_signature(f1), fast_hand_signature(f2))

    def test_resolve_action_params_merges_dedicated_option_nodes(self) -> None:
        node_map = {
            "CoopAssaultBattleAutoOptPlayMode": {"attach": {"play_mode": "weighted"}},
            "CoopAssaultBattleAutoOptPreferNativeAuto": {"attach": {"prefer_native_auto": False}},
            "CoopAssaultBattleAutoOptLeaderSkill": {"attach": {"prefer_leader_skill": False}},
            "CoopAssaultBattleAutoOptMinCost": {"attach": {"min_cost_to_play": 4}},
        }
        ctx = SimpleNamespace(get_node_data=lambda name: node_map.get(name))
        argv = SimpleNamespace(
            node_name="CoopAssaultBattleAuto",
            custom_action_param={
                "play_mode": "fast_rush",
                "prefer_native_auto": True,
                "prefer_leader_skill": True,
                "min_cost_to_play": 2,
            },
        )
        merged = baa._resolve_action_params(ctx, argv)
        self.assertEqual(merged["play_mode"], "weighted")
        self.assertFalse(merged["prefer_native_auto"])
        self.assertFalse(merged["prefer_leader_skill"])
        self.assertEqual(merged["min_cost_to_play"], 4)

    @staticmethod
    def _make_hud_frame(*, native_auto_on: bool) -> np.ndarray:
        frame = np.full((720, 1280, 3), 25, dtype=np.uint8)
        # Top pill + red timer text + bottom-right cost text -> is_battle_hud_likely_active == True
        frame[16:40, 515:765, :] = 30
        frame[22:32, 635:650, :] = (20, 20, 220)
        frame[670:700, 1030:1150, :] = 230
        # Bright hand band -> is_hand_bright == True
        frame[490:530, 300:900, :] = 190
        if native_auto_on:
            frame[28:54, 114:138, :] = 245
        return frame

    def test_native_auto_survives_cutscene_and_requires_multiframe_off_confirm(self) -> None:
        hud_on = self._make_hud_frame(native_auto_on=True)
        hud_off = self._make_hud_frame(native_auto_on=False)
        cutscene = np.zeros((720, 1280, 3), dtype=np.uint8)

        # 1. Active native-auto survives 4 cutscene frames (~1.8s) without exiting or tapping (126, 42).
        frames_cutscene = iter([hud_on] + [cutscene] * 4 + [hud_on] + [cutscene] * 12)
        taps: list[tuple[str, tuple[int, int]]] = []
        now = [0.0]

        def fake_screencap(_ctx):
            return next(frames_cutscene, cutscene)

        def fake_sleep(_ctx, sec: float, **_kw) -> bool:
            now[0] += float(sec)
            return True

        def fake_run_action(node_name, box, detail, override):
            taps.append((node_name, tuple(override[node_name]["target"][:2])))
            return SimpleNamespace(success=True)

        ctx = SimpleNamespace(
            tasker=SimpleNamespace(stopping=False, controller=None),
            run_recognition=lambda *_a, **_kw: SimpleNamespace(hit=False),
            run_action=fake_run_action,
        )
        argv = SimpleNamespace(
            node_name="TestBattle",
            custom_action_param={"play_mode": "fast_rush", "prefer_native_auto": True},
        )
        with patch("agent.battle_autoplay_action.safe_screencap", side_effect=fake_screencap), patch(
            "agent.battle_autoplay_action.sleep_with_stop", side_effect=fake_sleep
        ), patch("agent.battle_autoplay_action.wait_mouse_button_released", return_value=True), patch(
            "agent.battle_autoplay_action.time.monotonic", side_effect=lambda: now[0]
        ):
            self.assertTrue(baa.BattleAutoplayLoopAction().run(ctx, argv))
        self.assertEqual(taps, [])

        # 2. Single off-frame during HUD fade-in must NOT tap (126, 42) when native auto lights up next.
        frames_fade = iter([hud_off, hud_on] + [cutscene] * 12)
        now[0] = 0.0
        with patch("agent.battle_autoplay_action.safe_screencap", side_effect=lambda _c: next(frames_fade, cutscene)), patch(
            "agent.battle_autoplay_action.sleep_with_stop", side_effect=fake_sleep
        ), patch("agent.battle_autoplay_action.wait_mouse_button_released", return_value=True), patch(
            "agent.battle_autoplay_action.time.monotonic", side_effect=lambda: now[0]
        ):
            self.assertTrue(baa.BattleAutoplayLoopAction().run(ctx, argv))
        self.assertEqual(taps, [])

        # 3. Three consecutive stable bright-HUD off-frames -> taps (126, 42) once and stands by.
        frames_confirm = iter([hud_off, hud_off, hud_off, hud_on] + [cutscene] * 12)
        now[0] = 0.0
        with patch("agent.battle_autoplay_action.safe_screencap", side_effect=lambda _c: next(frames_confirm, cutscene)), patch(
            "agent.battle_autoplay_action.sleep_with_stop", side_effect=fake_sleep
        ), patch("agent.battle_autoplay_action.wait_mouse_button_released", return_value=True), patch(
            "agent.battle_autoplay_action.time.monotonic", side_effect=lambda: now[0]
        ):
            self.assertTrue(baa.BattleAutoplayLoopAction().run(ctx, argv))
        self.assertEqual(len(taps), 1)
        self.assertEqual(taps[0][1], (126, 42))

    def test_victory_screen_not_mistaken_for_hud_and_exits_immediately(self) -> None:
        # Simulated victory screen: dark header, bright MVP portrait in hand band, white button text bottom-right, NO red top pill.
        victory_frame = np.full((720, 1280, 3), 25, dtype=np.uint8)
        victory_frame[490:530, 300:900, :] = 190
        victory_frame[670:700, 1030:1150, :] = 230
        self.assertTrue(is_hand_bright(victory_frame))
        self.assertFalse(is_battle_hud_likely_active(victory_frame))

        self.assertTrue(has_battle_ended_marker(["作战胜利", "MVP", "小红帽"]))
        self.assertTrue(has_battle_ended_marker(["作战数据", "下一步"]))
        self.assertTrue(has_battle_ended_marker(["前往作战"]))
        self.assertFalse(has_battle_ended_marker([]))
        self.assertFalse(has_battle_ended_marker(["00:25", "12/12 MAX"]))

        hud_on = self._make_hud_frame(native_auto_on=True)
        cutscene = np.zeros((720, 1280, 3), dtype=np.uint8)
        # Active frame -> 2 blank cutscene frames (must NOT exit) -> victory frame (exits immediately on 1st frame!)
        frames = iter([hud_on, cutscene, cutscene, victory_frame, victory_frame, victory_frame])
        sleeps: list[float] = []
        now = [0.0]

        def fake_screencap(_ctx):
            return next(frames, victory_frame)

        def fake_sleep(_ctx, sec: float, **_kw) -> bool:
            sleeps.append(float(sec))
            now[0] += float(sec)
            return True

        def fake_run_reco(node_name, image, _override):
            # Cutscene frames return empty texts; victory frame returns settlement markers with hit=False.
            if int(image.max()) > 0:
                payload = {"bottom_texts": ["作战胜利", "作战数据", "下一步"], "top_texts": []}
            else:
                payload = {"bottom_texts": [], "top_texts": []}
            return SimpleNamespace(
                hit=False,
                all_results=[SimpleNamespace(detail=payload)],
                raw_detail={"all": [{"detail": payload}]},
            )

        ctx = SimpleNamespace(
            tasker=SimpleNamespace(stopping=False, controller=None),
            run_recognition=fake_run_reco,
            run_action=lambda *_a, **_kw: SimpleNamespace(success=True),
        )
        argv = SimpleNamespace(
            node_name="TestVictory",
            custom_action_param={"play_mode": "fast_rush", "prefer_native_auto": True},
        )
        with patch("agent.battle_autoplay_action.safe_screencap", side_effect=fake_screencap), patch(
            "agent.battle_autoplay_action.sleep_with_stop", side_effect=fake_sleep
        ), patch("agent.battle_autoplay_action.wait_mouse_button_released", return_value=True), patch(
            "agent.battle_autoplay_action.time.monotonic", side_effect=lambda: now[0]
        ):
            self.assertTrue(baa.BattleAutoplayLoopAction().run(ctx, argv))

        # 1 sleep for hud_on standby + 2 sleeps for the 2 blank cutscene frames, then immediate exit on 1st victory frame!
        self.assertEqual(len(sleeps), 3)


if __name__ == "__main__":
    unittest.main()

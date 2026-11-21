from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import sys
import unittest
import numpy as np

from maa_resonance.logic.coop_assault import (
    choose_coop_boss_slot,
    choose_coop_difficulty_point,
    detect_unlocked_coop_difficulties,
    find_coop_home_enter_point,
    find_coop_prepare_enter_point,
    find_coop_reward_claim_point,
    is_coop_boss_map_entries,
    is_coop_home_entries,
    is_coop_prepare_entries,
    is_coop_reward_screen_entries,
    parse_coop_boss_slots,
    parse_coop_remaining_attempts,
    parse_coop_reward_tabs,
)

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _real_maa_resource():
    saved = {}
    maa_mod = sys.modules.get("maa")
    stashed = maa_mod is not None and not hasattr(maa_mod, "__path__")
    if stashed:
        for name in list(sys.modules):
            if name == "maa" or name.startswith("maa."):
                saved[name] = sys.modules.pop(name)
    try:
        try:
            resource_mod = importlib.import_module("maa.resource")
            yield resource_mod.Resource
        except ImportError:
            yield None
    finally:
        if stashed:
            for name in list(sys.modules):
                if name == "maa" or name.startswith("maa."):
                    sys.modules.pop(name, None)
            sys.modules.update(saved)


class CoopAssaultLogicTest(unittest.TestCase):
    def test_home_map_and_remaining_attempts(self) -> None:
        home_entries = [
            {"text": "11/16 12:00", "box": [844, 236, 149, 57]},
            {"text": "12/31 12:00", "box": [1036, 239, 153, 53]},
            {"text": "众志攻坚", "box": [897, 144, 81, 28]},
            {"text": "》进入挑战5/5×", "box": [869, 573, 293, 45]},
        ]
        self.assertTrue(is_coop_home_entries(home_entries))
        self.assertEqual(find_coop_home_enter_point(home_entries), (1016, 596))
        self.assertEqual(parse_coop_remaining_attempts(home_entries), (5, 5))
        self.assertEqual(parse_coop_remaining_attempts([{"text": "4/5", "box": [1180, 26, 42, 34]}]), (4, 5))
        self.assertEqual(parse_coop_remaining_attempts([{"text": "0/5", "box": [1180, 26, 42, 34]}]), (0, 5))

    def test_boss_slots_selection_and_difficulty_detection(self) -> None:
        map_entries = [
            {"text": "当前剩余讨伐次数", "box": [1028, 31, 149, 23]},
            {"text": "5/5", "box": [1180, 26, 42, 34]},
            {"text": "已击杀", "box": [201, 194, 61, 32]},
            {"text": "可继续重复挑战", "box": [170, 227, 124, 23]},
            {"text": "莉耶芙", "box": [204, 272, 56, 24]},
            {"text": "0%8055", "box": [201, 334, 80, 28]},
            {"text": "玛丽·安", "box": [600, 419, 77, 24]},
            {"text": "95.9%BS5", "box": [566, 485, 151, 37]},
            {"text": "已击杀", "box": [1018, 202, 55, 20]},
            {"text": "玛丽·苏", "box": [1012, 272, 65, 24]},
            {"text": "0%H055×", "box": [1014, 334, 80, 28]},
            {"text": "攻坚战果", "box": [1144, 655, 78, 27]},
        ]
        self.assertTrue(is_coop_boss_map_entries(map_entries))
        slots = parse_coop_boss_slots(map_entries)
        self.assertEqual([s["name"] for s in slots], ["莉耶芙", "玛丽·安", "玛丽·苏"])
        self.assertTrue(slots[0]["defeated"])
        self.assertFalse(slots[1]["defeated"])
        self.assertAlmostEqual(slots[1]["hp_pct"], 95.9)
        chosen = choose_coop_boss_slot(slots, "alive_first")
        self.assertIsNotNone(chosen)
        assert chosen is not None
        self.assertEqual(chosen["name"], "玛丽·安")

        # Prepare screen & difficulty chroma check (cards 1..3 colored, 4..5 grayscale)
        prep_entries = [
            {"text": "玛丽·安", "box": [420, 97, 181, 65]},
            {"text": "难度1", "box": [482, 428, 56, 24]},
            {"text": "难度3", "box": [749, 428, 59, 24]},
            {"text": "进入挑战", "box": [865, 540, 119, 33]},
        ]
        self.assertTrue(is_coop_prepare_entries(prep_entries))
        self.assertEqual(find_coop_prepare_enter_point(prep_entries), (924, 556))

        img = np.full((720, 1280, 3), 120, dtype=np.uint8)
        for cx in (510, 645, 778):
            img[290:415, cx - 40 : cx + 40] = (90, 170, 130)
        unlocked = detect_unlocked_coop_difficulties(img)
        self.assertEqual(unlocked, [1, 2, 3])
        self.assertEqual(choose_coop_difficulty_point(unlocked, 0), (3, (778, 395)))
        # Requesting locked diff 5 gracefully falls back to highest unlocked (3)
        self.assertEqual(choose_coop_difficulty_point(unlocked, 5), (3, (778, 395)))

    def test_reward_tabs_and_strict_claim_filtering(self) -> None:
        self.assertTrue(is_coop_reward_screen_entries([{"text": "BOSS血量降低至", "box": [598, 109, 135, 26]}]))
        tab_entries = [
            {"text": "玛丽·安", "box": [828, 627, 93, 29]},
            {"text": "当前血量：96%", "box": [817, 653, 119, 23]},
            {"text": "莉耶芙", "box": [364, 627, 78, 29]},
            {"text": "本", "box": [700, 675, 12, 10]},
            {"text": "玛丽·苏", "box": [592, 627, 94, 29]},
        ]
        tabs = parse_coop_reward_tabs(tab_entries)
        self.assertEqual([t[0] for t in tabs], ["莉耶芙", "玛丽·苏", "玛丽·安"])

        claim_entries = [
            {"text": "已领取", "box": [1121, 264, 71, 28]},
            {"text": "CLAIMD", "box": [1137, 248, 52, 20]},
            {"text": "CLAIM", "box": [1146, 104, 43, 21]},
            {"text": "领取奖励", "box": [1100, 121, 92, 28]},
        ]
        self.assertEqual(find_coop_reward_claim_point(claim_entries), (1146, 135))
        self.assertIsNone(
            find_coop_reward_claim_point(
                [
                    {"text": "已领取", "box": [1121, 264, 71, 28]},
                    {"text": "CLAIMD", "box": [1137, 248, 52, 20]},
                ]
            )
        )

    def test_pipeline_and_task_integrity(self) -> None:
        pipeline = json.loads((ROOT / "assets/resource/base/pipeline/daily/coop_assault.json").read_text(encoding="utf-8"))
        task_cfg = json.loads((ROOT / "assets/resource/tasks/CoopAssault.json").read_text(encoding="utf-8"))

        for node_name, node in pipeline.items():
            act = node.get("action")
            act_type = act.get("type") if isinstance(act, dict) else act
            self.assertNotIn(act_type, ("Click", "Swipe"), msg=node_name)

        self.assertEqual(
            pipeline["CoopAssaultFormationReadyCheck"]["expected"],
            ["快速编队", "快速编", "清空编队"],
        )
        self.assertEqual(
            pipeline["CoopAssaultFormationStartBattle"]["expected"],
            ["START BATTLE", "开始作战", "开始", "作战"],
        )

        # Verify no two options overwrite the same custom_action_param or attach field on a shared node.
        seen_targets: dict[tuple[str, str], str] = {}
        for opt_name, opt in task_cfg["option"].items():
            for case in opt.get("cases", []):
                for target_node, override in case.get("pipeline_override", {}).items():
                    for key in ("attach", "custom_action_param"):
                        if key in override:
                            prev = seen_targets.get((target_node, key))
                            if prev is not None:
                                self.assertEqual(prev, opt_name, msg=f"{target_node}.{key} overwritten by {prev} and {opt_name}")
                            seen_targets[(target_node, key)] = opt_name

        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            res = Resource()
            self.assertTrue(res.post_bundle(ROOT / "assets" / "resource" / "base").wait().succeeded)
            for node_name in pipeline:
                self.assertIsNotNone(res.get_node_data(node_name), msg=f"Missing node: {node_name}")


if __name__ == "__main__":
    unittest.main()

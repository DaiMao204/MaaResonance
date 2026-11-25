from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import sys
import unittest

from maa_resonance.logic.event_story_daily import (
    find_frosting_drawer_start_point,
    find_frosting_enter_point,
    find_frosting_start_card_point,
    is_frosting_cards_screen_entries,
    is_frosting_drawer_open,
    is_frosting_home_entries,
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


class EventStoryDailyLogicTest(unittest.TestCase):
    def test_frosting_home_cards_and_drawer_distinction(self) -> None:
        self.assertTrue(is_frosting_home_entries([{"text": "前往取景", "box": [920, 540, 160, 40]}]))
        self.assertEqual(find_frosting_enter_point([{"text": "前往取景", "box": [920, 540, 160, 40]}]), (1000, 560))

        header_entries = [{"text": "取景进度", "box": [794, 41, 186, 54]}]
        cards_entries = [
            {"text": "取景完成", "box": [134, 563, 106, 32]},
            {"text": "开始取景", "box": [736, 562, 106, 36]},
            {"text": "明日登录解锁", "box": [925, 567, 129, 24]},
        ]
        self.assertTrue(is_frosting_cards_screen_entries(header_entries, cards_entries))
        self.assertEqual(find_frosting_start_card_point(cards_entries), (789, 580))

        # Card 05/06 alone without drawer info ('敌人等级' / '奖励预览') must NOT be misclassified as open drawer.
        self.assertFalse(is_frosting_drawer_open([], [{"text": "开始取景", "box": [996, 570, 168, 48]}]))
        info_entries = [{"text": "敌人等级22", "box": [869, 189, 121, 28]}, {"text": "奖励预览", "box": [881, 491, 77, 22]}]
        btn_entries = [{"text": "开始取景", "box": [996, 570, 168, 48]}]
        self.assertTrue(is_frosting_drawer_open(info_entries, btn_entries))
        self.assertEqual(find_frosting_drawer_start_point(btn_entries), (1080, 594))

        # Completed day: no '开始取景' card left.
        done_cards = [{"text": "取景完成", "box": [736, 563, 106, 33]}, {"text": "明日登录解锁", "box": [925, 567, 129, 24]}]
        self.assertIsNone(find_frosting_start_card_point(done_cards))

    def test_pipeline_loads_and_no_native_click_swipe(self) -> None:
        pipeline = json.loads((ROOT / "assets/resource/base/pipeline/daily/event_story_daily.json").read_text(encoding="utf-8"))
        task_cfg = json.loads((ROOT / "assets/resource/tasks/EventStoryDaily.json").read_text(encoding="utf-8"))
        for node_name, node in pipeline.items():
            act = node.get("action")
            act_type = act.get("type") if isinstance(act, dict) else act
            self.assertNotIn(act_type, ("Click", "Swipe"), msg=node_name)

        for opt_node in (
            "EventStoryDailyBattleAutoOptPlayMode",
            "EventStoryDailyBattleAutoOptPreferNativeAuto",
            "EventStoryDailyBattleAutoOptLeaderSkill",
            "EventStoryDailyBattleAutoOptMinCost",
        ):
            self.assertIn(opt_node, pipeline)

        prefer_opt = task_cfg["option"]["EventStoryPreferNativeAuto"]
        cases_by_name = {c["name"]: c["pipeline_override"] for c in prefer_opt["cases"]}
        self.assertEqual(
            cases_by_name["Yes"],
            {"EventStoryDailyBattleAutoOptPreferNativeAuto": {"attach": {"prefer_native_auto": True}}},
        )
        self.assertEqual(
            cases_by_name["No"],
            {"EventStoryDailyBattleAutoOptPreferNativeAuto": {"attach": {"prefer_native_auto": False}}},
        )

        self.assertEqual(
            pipeline["EventStoryDailyFormationReadyCheck"]["expected"],
            ["快速编队", "快速编", "清空编队"],
        )
        self.assertEqual(
            pipeline["EventStoryDailyFormationStartBattle"]["expected"],
            ["START BATTLE", "开始作战", "开始", "作战"],
        )

        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            res = Resource()
            self.assertTrue(res.post_bundle(ROOT / "assets" / "resource" / "base").wait().succeeded)
            for node_name in pipeline:
                self.assertIsNotNone(res.get_node_data(node_name), msg=f"Missing node: {node_name}")


if __name__ == "__main__":
    unittest.main()

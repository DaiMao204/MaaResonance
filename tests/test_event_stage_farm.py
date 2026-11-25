from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np

from maa_resonance.logic.event_stage_farm import (
    find_miniscape_break_button,
    find_stage_card_point,
    find_stage_enter_button_point,
    has_auto_repeat_toggle_label,
    is_low_clarity_confirm_popup,
    is_stage_auto_repeat_on,
    is_stage_detail_open,
    is_stage_list_screen_entries,
    parse_run_count_limit,
    parse_stage_clarity,
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
        except ImportError:
            yield None
            return
        # These tests bind to a local Resource. Loading the real AgentServer
        # decorators switches MaaFramework into its separate IPC server mode.
        def local_registration(_name):
            return lambda cls: cls

        server = SimpleNamespace(custom_action=local_registration, custom_recognition=local_registration)
        with patch.dict(sys.modules, {"maa.agent.agent_server": SimpleNamespace(AgentServer=server)}):
            yield resource_mod.Resource
    finally:
        if stashed:
            for name in list(sys.modules):
                if name == "maa" or name.startswith("maa."):
                    sys.modules.pop(name, None)
            sys.modules.update(saved)


class EventStageFarmLogicTest(unittest.TestCase):
    def test_activity_navigation_failures_leave_the_daily_queue_unblocked(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            from agent import coop_assault_action, daily_routine_action, event_stage_farm_action

            daily = ROOT / "assets/resource/base/pipeline/daily"
            recovery = "DailyActivityNavigationFailed"
            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
            cases = (
                (coop_assault_action, coop_assault_action.CoopAssaultEnterHubAction,
                 "CoopAssault", "coop_assault.json", "_COOP_STATE_BY_TASK"),
                (event_stage_farm_action, event_stage_farm_action.EventStageFarmNavigateAction,
                 "EventStageFarm", "event_stage_farm.json", "_STAGE_STATE_BY_TASK"),
            )
            for module, action, name, filename, state_attr in cases:
                with self.subTest(task=name):
                    argv = SimpleNamespace(node_name=name + "Start")
                    with (
                        patch.object(module, state_attr, {}),
                        patch.object(module, "safe_screencap", return_value=object()),
                        patch.object(module, "ocr_roi", return_value=[]),
                        patch.object(module, "open_activity_hub", return_value=False),
                        patch.object(module, "select_activity_tab") as select_tab,
                    ):
                        self.assertFalse(action().run(ctx, argv).success)
                        select_tab.assert_not_called()
                    pipeline = json.loads((daily / filename).read_text(encoding="utf-8"))
                    self.assertEqual(pipeline[name + "Start"]["on_error"], [recovery])
                    self.assertEqual(pipeline[name + "Loop"]["on_error"], [recovery])
                    self.assertLessEqual(pipeline[name + "Loop"]["timeout"], 180000)

            recovery_node = json.loads((daily / "daily_routine.json").read_text(encoding="utf-8"))[recovery]
            self.assertFalse(recovery_node.get("next"))
            self.assertFalse(recovery_node.get("on_error"))
            argv = SimpleNamespace(node_name=recovery)
            for returned in (True, False):
                with patch.object(daily_routine_action, "_return_to_lobby", return_value=returned) as recover:
                    result = daily_routine_action.DailyActivityReturnToLobbyAction().run(ctx, argv)
                    self.assertEqual(result, returned)
                    recover.assert_called_once()

    def test_stage_discovery_and_detail_checks(self) -> None:
        self.assertEqual(
            find_miniscape_break_button([{"text": "破坏箱庭", "box": [1114, 614, 87, 23]}]),
            (1158, 626),
        )
        list_entries = [
            {"text": "调查报告6", "box": [124, 393, 113, 27]},
            {"text": "调查报告7", "box": [549, 476, 115, 32]},
            {"text": "07", "box": [568, 362, 76, 64]},
            {"text": "破坏进度", "box": [993, 47, 77, 23]},
        ]
        self.assertTrue(is_stage_list_screen_entries(list_entries))
        self.assertEqual(find_stage_card_point(list_entries, "调查报告7"), (606, 437))

        # Should ignore the open right-side detail title header when searching stage cards.
        detail_entries = [{"text": "调查报告7", "box": [844, 105, 188, 43]}]
        self.assertIsNone(find_stage_card_point(detail_entries, "调查报告7"))
        enter_entries = [{"text": "破坏箱庭", "box": [986, 557, 120, 33]}]
        self.assertTrue(is_stage_detail_open(detail_entries, enter_entries, "调查报告7"))
        self.assertEqual(find_stage_enter_button_point(enter_entries), (1046, 574))
        self.assertEqual(parse_stage_clarity([{"text": "292/292+", "box": [1093, 25, 109, 31]}]), (292, 292))

    def test_stage_list_check_rejects_loading_detail_and_battle_frames(self) -> None:
        self.assertFalse(
            is_stage_list_screen_entries([{"text": "LOAD"}, {"text": "破坏进度"}, {"text": "100%"}])
        )
        self.assertFalse(
            is_stage_list_screen_entries(
                [
                    {"text": "调查报告4"},
                    {"text": "调查报告7"},
                    {"text": "难度推荐LV45"},
                    {"text": "奖励预览"},
                    {"text": "破坏箱庭"},
                ]
            )
        )
        self.assertFalse(is_stage_list_screen_entries([{"text": "弃牌"}, {"text": "MAX"}]))

    def test_select_stage_from_list_aborts_without_swipe_or_lobby_when_interrupted(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.event_stage_farm_action as esfa

            img = np.full((720, 1280, 3), 40, dtype=np.uint8)
            frames = [
                [
                    {"text": "调查报告4"},
                    {"text": "调查报告7"},
                    {"text": "难度推荐LV45"},
                    {"text": "奖励预览"},
                    {"text": "破坏箱庭"},
                ],
                [{"text": "弃牌"}, {"text": "MAX"}],
            ]
            for ocr_entries in frames:
                ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False), get_node_data=lambda _n: None)
                argv = SimpleNamespace(
                    node_name="EventStageFarmStageListStep",
                    task_detail=SimpleNamespace(task_id=987655),
                    custom_action_param={},
                )
                action = esfa.EventStageFarmSelectStageFromListAction()
                esfa._STAGE_STATE_BY_TASK.pop(987655, None)
                try:
                    with (
                        patch.object(esfa, "safe_screencap", return_value=img),
                        patch.object(esfa, "ocr_roi", return_value=ocr_entries),
                        patch.object(esfa, "swipe_points") as mock_swipe,
                        patch.object(esfa, "return_to_lobby") as mock_lobby,
                        patch.object(esfa, "sleep_with_stop", return_value=True),
                    ):
                        res = action.run(ctx, argv)
                    state_after = dict(esfa._stage_state(ctx, argv))
                finally:
                    esfa._STAGE_STATE_BY_TASK.pop(987655, None)

                self.assertTrue(getattr(res, "success", True))
                self.assertFalse(state_after["done"])
                mock_swipe.assert_not_called()
                mock_lobby.assert_not_called()

    def test_auto_repeat_toggle_and_low_clarity_popup(self) -> None:
        img = np.full((720, 1280, 3), 40, dtype=np.uint8)
        self.assertFalse(is_stage_auto_repeat_on(img))
        self.assertTrue(has_auto_repeat_toggle_label([{"text": "自动战斗", "box": [966, 653, 83, 24]}]))
        self.assertTrue(
            is_stage_auto_repeat_on(
                img,
                [{"text": "2秒后开始战斗", "box": [980, 682, 142, 27]}],
            )
        )
        # White toggle knob on the right [1106:1134, 652:678]
        img[652:678, 1106:1134] = (240, 240, 240)
        self.assertTrue(is_stage_auto_repeat_on(img))

        self.assertTrue(is_low_clarity_confirm_popup([{"text": "您当前的澄明度不足，是否补充澄明度？"}]))
        self.assertEqual(parse_run_count_limit("3"), 3)
        self.assertEqual(parse_run_count_limit("0"), 0)

    def test_pipeline_and_no_option_override_collisions(self) -> None:
        pipeline = json.loads((ROOT / "assets/resource/base/pipeline/daily/event_stage_farm.json").read_text(encoding="utf-8"))
        task_cfg = json.loads((ROOT / "assets/resource/tasks/EventStageFarm.json").read_text(encoding="utf-8"))

        for node_name, node in pipeline.items():
            act = node.get("action")
            act_type = act.get("type") if isinstance(act, dict) else act
            self.assertNotIn(act_type, ("Click", "Swipe"), msg=node_name)

        self.assertEqual(
            pipeline["EventStageFarmFormationReadyCheck"]["expected"],
            ["快速编队", "快速编", "清空编队"],
        )
        self.assertEqual(
            pipeline["EventStageFarmFormationStartBattle"]["expected"],
            ["START BATTLE", "开始作战", "开始", "作战"],
        )

        seen_targets: dict[tuple[str, str], str] = {}
        for opt_name, opt in task_cfg["option"].items():
            if "pipeline_override" in opt:
                for target_node, override in opt["pipeline_override"].items():
                    for key in ("attach", "custom_action_param"):
                        if key in override:
                            prev = seen_targets.get((target_node, key))
                            if prev is not None:
                                self.assertEqual(prev, opt_name, msg=f"{target_node}.{key} overwritten")
                            seen_targets[(target_node, key)] = opt_name
            for case in opt.get("cases", []):
                for target_node, override in case.get("pipeline_override", {}).items():
                    for key in ("attach", "custom_action_param"):
                        if key in override:
                            prev = seen_targets.get((target_node, key))
                            if prev is not None:
                                self.assertEqual(prev, opt_name, msg=f"{target_node}.{key} overwritten")
                            seen_targets[(target_node, key)] = opt_name

        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            res = Resource()
            self.assertTrue(res.post_bundle(ROOT / "assets" / "resource" / "base").wait().succeeded)
            for node_name in pipeline:
                self.assertIsNotNone(res.get_node_data(node_name), msg=f"Missing node: {node_name}")

    def test_detail_step_falls_back_to_enter_when_auto_toggle_stays_off(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.event_stage_farm_action as esfa

            img = np.full((720, 1280, 3), 40, dtype=np.uint8)
            tapped: list[tuple[str, tuple[int, int]]] = []

            def fake_ocr(_ctx, _img, name: str, _roi):
                if name.endswith("AutoTxt"):
                    return [{"text": "自动战斗", "box": [965, 651, 85, 28]}]
                if name.endswith("EnterBtn"):
                    return [{"text": "破坏箱庭", "box": [986, 557, 120, 33]}]
                return []

            def fake_tap(_ctx, name: str, pt: tuple[int, int]) -> bool:
                tapped.append((name, pt))
                return True

            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False), get_node_data=lambda _n: None)
            argv = SimpleNamespace(
                node_name="EventStageFarmDetailStep",
                task_detail=SimpleNamespace(task_id=987654),
                custom_action_param={},
            )
            action = esfa.EventStageFarmDetailStepAction()
            esfa._STAGE_STATE_BY_TASK.pop(987654, None)
            try:
                with (
                    patch.object(esfa, "safe_screencap", return_value=img),
                    patch.object(esfa, "ocr_roi", side_effect=fake_ocr),
                    patch.object(esfa, "tap_point", side_effect=fake_tap),
                    patch.object(esfa, "sleep_with_stop", return_value=True),
                ):
                    res1 = action.run(ctx, argv)
                    res2 = action.run(ctx, argv)
            finally:
                esfa._STAGE_STATE_BY_TASK.pop(987654, None)

            self.assertTrue(getattr(res1, "success", True))
            self.assertTrue(getattr(res2, "success", True))
            self.assertEqual(
                tapped,
                [
                    ("EventStageFarmDetailStep_DetailTurnOnAuto", (1098, 666)),
                    ("EventStageFarmDetailStep_DetailEnterStage", (1046, 574)),
                ],
            )


if __name__ == "__main__":
    unittest.main()

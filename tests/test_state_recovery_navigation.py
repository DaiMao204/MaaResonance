from __future__ import annotations

import json
import types
import unittest
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from tests.test_trade_runtime_fix import trade


class CaptureJob:
    def __init__(self, image=None, *, succeeded=True):
        self.image = image
        self.succeeded = succeeded

    def wait(self):
        return self

    def get(self):
        return self.image


class RecoveryController:
    def __init__(self, image):
        self.post_screencap = Mock(return_value=CaptureJob(image))
        self.post_click = Mock(return_value=CaptureJob(succeeded=True))

    @property
    def cached_image(self):
        raise AssertionError("recovery must never authorize a click from cached_image")


class StateRecoveryNavigationTest(unittest.TestCase):
    def setUp(self):
        self.image = types.SimpleNamespace(shape=(720, 1280, 3))
        self.controller = RecoveryController(self.image)
        self.hits = {}
        self.context = types.SimpleNamespace(
            tasker=types.SimpleNamespace(controller=self.controller, stopping=False),
            run_recognition=Mock(side_effect=self.recognize),
        )
        self.home_box = [158, 14, 79, 45]

    def recognize(self, name, image, override=None):
        self.assertIs(image, self.image)
        box = self.hits.get(name)
        return types.SimpleNamespace(
            hit=box is not None,
            best_result=types.SimpleNamespace(box=box) if box is not None else None,
            box=box,
        )

    def navigate(self, kind="home"):
        return trade._state_recovery_safe_navigation(self.context, kind)

    def home_visible(self):
        self.hits["StateRecoveryNavigationHomeProbe"] = self.home_box

    def test_fresh_home_template_clicks_center_instead_of_old_pipeline_point(self):
        self.home_visible()
        result = self.navigate()
        self.assertTrue(result["ok"])
        self.assertTrue(result["clicked"])
        self.controller.post_screencap.assert_called_once()
        self.controller.post_click.assert_called_once_with(197, 36)

    def test_already_home_does_not_click_even_when_home_template_also_matches(self):
        for main_probe in (
            "StateRecoveryNavigationMainMapTemplateProbe",
            "StateRecoveryNavigationMainMapOcrProbe",
        ):
            with self.subTest(probe=main_probe):
                self.hits = {main_probe: [1167, 651, 103, 42]}
                self.home_visible()
                result = self.navigate()
                self.assertTrue(result["ok"])
                self.assertFalse(result["clicked"])
                self.assertEqual(result["reason"], "main_map")
                self.controller.post_click.assert_not_called()

    def test_loading_blocks_readable_home_and_main_map_controls(self):
        self.hits = {
            "StateRecoveryNavigationLoadingProbe": [500, 340, 100, 40],
            "StateRecoveryNavigationMainMapTemplateProbe": [1167, 651, 103, 42],
        }
        self.home_visible()
        result = self.navigate()
        self.assertEqual(result["reason"], "loading")
        self.assertFalse(result["clicked"])
        self.controller.post_click.assert_not_called()
        self.assertEqual(
            [call.args[0] for call in self.context.run_recognition.call_args_list],
            ["StateRecoveryNavigationLoadingProbe"],
        )

    def test_disappeared_home_button_does_not_reuse_previous_point(self):
        self.home_visible()
        self.assertTrue(self.navigate()["clicked"])
        self.hits.clear()
        result = self.navigate()
        self.assertEqual(result["reason"], "button_absent")
        self.assertFalse(result["clicked"])
        self.controller.post_click.assert_called_once_with(197, 36)
        self.assertEqual(self.controller.post_screencap.call_count, 2)

    def test_failed_or_empty_capture_never_falls_back_to_cached_image(self):
        for capture in (CaptureJob(self.image, succeeded=False), CaptureJob(None)):
            with self.subTest(capture=capture):
                self.controller.post_screencap.return_value = capture
                self.assertFalse(self.navigate()["ok"])
                self.context.run_recognition.assert_not_called()
                self.controller.post_click.assert_not_called()

    def test_capture_exception_does_not_authorize_input(self):
        self.controller.post_screencap.side_effect = RuntimeError("capture disconnected")
        self.assertFalse(self.navigate()["ok"])
        self.context.run_recognition.assert_not_called()
        self.controller.post_click.assert_not_called()

    def test_recognition_not_run_or_exception_is_not_button_absence(self):
        for result in (None, RuntimeError("recognizer disconnected")):
            with self.subTest(result=result):
                self.context.run_recognition.side_effect = (
                    result if isinstance(result, Exception) else None
                )
                self.context.run_recognition.return_value = None
                self.assertFalse(self.navigate()["ok"])
                self.controller.post_click.assert_not_called()

    def test_template_hit_outside_home_roi_cannot_authorize_input(self):
        self.hits["StateRecoveryNavigationHomeProbe"] = [300, 14, 79, 45]
        result = self.navigate()
        self.assertFalse(result.get("clicked", False))
        self.controller.post_click.assert_not_called()

    def test_slow_recognition_cannot_click_a_stale_frame(self):
        self.home_visible()
        now = [10.0]

        def recognize(name, image, override=None):
            result = self.recognize(name, image, override)
            if name == "StateRecoveryNavigationHomeProbe":
                now[0] += 1.501
            return result

        self.context.run_recognition.side_effect = recognize
        with patch.object(trade.time, "monotonic", side_effect=lambda: now[0]):
            result = self.navigate()
        self.assertEqual(result["reason"], "stale_frame")
        self.assertFalse(result["clicked"])
        self.controller.post_click.assert_not_called()

    def test_capture_duration_does_not_age_the_newly_returned_frame(self):
        self.home_visible()
        now = [10.0]

        def capture():
            now[0] += 3.0
            return CaptureJob(self.image)

        self.controller.post_screencap.side_effect = capture
        with patch.object(trade.time, "monotonic", side_effect=lambda: now[0]):
            result = self.navigate()
        self.assertTrue(result["clicked"])
        self.controller.post_click.assert_called_once_with(197, 36)

    def test_click_failure_is_reported_as_failure(self):
        self.home_visible()
        self.controller.post_click.return_value = CaptureJob(succeeded=False)
        self.assertFalse(self.navigate()["ok"])
        self.controller.post_click.assert_called_once_with(197, 36)

    def test_task_center_can_return_using_fresh_back_template(self):
        self.hits["StateRecoveryNavigationBackProbe"] = [16, 14, 134, 45]
        result = self.navigate("back")
        self.assertTrue(result["ok"])
        self.assertTrue(result["clicked"])
        self.controller.post_click.assert_called_once_with(83, 36)

    def test_old_action_box_does_not_authorize_fixed_fallback_click(self):
        argv = types.SimpleNamespace(
            custom_action_param={"kind": "home"},
            box=self.home_box,
            reco_detail=types.SimpleNamespace(box=self.home_box),
        )
        with patch.object(trade, "_json_payload"):
            self.assertTrue(trade.StateRecoverySafeNavigationAction().run(self.context, argv))
        self.controller.post_click.assert_not_called()


class StateRecoveryPipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.pipeline = json.loads(
            (root / "assets/resource/base/pipeline/business/common/state_recovery.json")
            .read_text(encoding="utf-8")
        )

    def test_home_fallbacks_and_template_hits_share_fresh_image_guard(self):
        home_nodes = {
            name: node for name, node in self.pipeline.items()
            if name.startswith("StateRecoveryTapHome")
        }
        self.assertTrue(home_nodes)
        self.assertTrue(any("Fixed" in name for name in home_nodes))
        for name, node in home_nodes.items():
            with self.subTest(node=name):
                self.assertEqual(node["action"]["type"], "Custom")
                param = node["action"]["param"]
                self.assertEqual(param["custom_action"], "state_recovery_safe_navigation")
                self.assertEqual(param["custom_action_param"]["kind"], "home")
                self.assertTrue("Observe" in node["next"] or node["next"] == "StateRecoveryFailed")

    def test_task_center_tabs_are_recoverable_in_all_navigation_observations(self):
        node = self.pipeline["StateRecoveryCloseTaskCenter"]
        # A visible tab with a missing return button must not loop forever
        # through ObserveAfterStep001 while its safe action skips input.
        self.assertEqual(node["max_hit"], 2)
        expected = node["recognition"]["param"]["expected"]
        for text in ("每日活跃", "导航手册", "行动汇总", "拼单单"):
            self.assertTrue(any(text in pattern for pattern in expected), text)
        param = node["action"]["param"]
        self.assertEqual(param["custom_action"], "state_recovery_safe_navigation")
        self.assertEqual(param["custom_action_param"]["kind"], "back")
        observations = {
            name: item for name, item in self.pipeline.items()
            if isinstance(item.get("next"), list)
            and "StateRecoveryCloseMissionPanel" in item["next"]
        }
        self.assertTrue(observations)
        for name, item in observations.items():
            with self.subTest(node=name):
                self.assertIn("StateRecoveryCloseTaskCenter", item["next"])


class StateRecoveryIdentityGateTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.state = trade._manual_two_city_defaults()
        self.state.update(
            account_identity_source="main_map",
            account_identity_pending=True,
            uid="11111111",
            manual_params={"uid": "11111111", "start_city": "海角城"},
            active_leg_index=1,
            completed_rounds=2,
            buy_book_usage_by_leg={"1|1|海角城|岚心城": 3},
        )
        self.context = types.SimpleNamespace(
            tasker=types.SimpleNamespace(stopping=False, controller=Mock())
        )
        self.argv = types.SimpleNamespace(custom_action_param=None)
        self.stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=self.state))
        self.stack.enter_context(patch.object(trade, "_PROFILE_UID", "11111111"))
        self.stack.enter_context(patch.object(trade, "_append_user_log"))
        self.stack.enter_context(patch.object(trade, "_json_payload"))
        self.sleep = self.stack.enter_context(patch.object(trade.time, "sleep"))
        self.stack.enter_context(patch.object(trade.time, "monotonic", return_value=10.0))
        self.frame = self.stack.enter_context(patch.object(
            trade, "_state_recovery_navigation_frame",
            return_value={"ok": True, "reason": "main_map", "captured_at": 10.0},
        ))

    def run_gate(self):
        return trade.ManualTwoCityBusinessAccountIdentityMainMapReadyAction().run(self.context, self.argv)

    def test_two_fresh_main_map_observations_are_required_without_resetting_budget(self):
        self.state["account_identity_main_map_recoveries"] = 1
        before = deepcopy(self.state)
        self.assertTrue(self.run_gate())
        self.assertEqual(self.frame.call_count, 2)
        self.sleep.assert_called_once_with(0.3)
        self.assertEqual(self.state["account_identity_main_map_recoveries"], 1)
        for key in ("uid", "manual_params", "active_leg_index", "completed_rounds", "buy_book_usage_by_leg"):
            self.assertEqual(self.state[key], before[key])
        self.context.tasker.controller.post_click.assert_not_called()

    def test_old_source_label_cannot_bypass_actual_frame_verification(self):
        self.state["account_identity_source"] = "trade_page"
        self.assertTrue(self.run_gate())
        self.assertEqual(self.frame.call_count, 2)

    def test_second_frame_drift_does_not_start_uid_read(self):
        self.frame.side_effect = [
            {"ok": True, "reason": "main_map", "captured_at": 10.0},
            {"ok": True, "reason": "other", "captured_at": 10.0},
        ]
        self.assertFalse(self.run_gate())
        self.assertEqual(self.state["account_identity_main_map_recoveries"], 1)
        self.assertFalse(self.state.get("account_identity_failed", False))
        self.context.tasker.controller.post_click.assert_not_called()

    def test_loading_capture_failure_and_stale_observation_consume_bounded_recovery(self):
        outcomes = [
            {"ok": True, "reason": "loading", "captured_at": 10.0},
            {"ok": False, "reason": "screencap_failed"},
            {"ok": True, "reason": "main_map", "captured_at": 8.499},
            RuntimeError("capture disconnected"),
        ]
        for outcome in outcomes:
            with self.subTest(outcome=outcome):
                self.state.pop("account_identity_main_map_recoveries", None)
                self.frame.side_effect = outcome if isinstance(outcome, Exception) else None
                self.frame.return_value = outcome
                self.assertFalse(self.run_gate())
                self.assertEqual(self.state["account_identity_main_map_recoveries"], 1)
                self.assertFalse(self.state.get("account_identity_failed", False))
                self.context.tasker.controller.post_click.assert_not_called()

    def test_third_failed_verification_stops_instead_of_restarting_recovery_forever(self):
        self.frame.return_value = {"ok": True, "reason": "other", "captured_at": 10.0}
        for attempt in (1, 2):
            self.assertFalse(self.run_gate())
            self.assertEqual(self.state["account_identity_main_map_recoveries"], attempt)
            self.assertFalse(self.state.get("account_identity_failed", False))
        self.assertFalse(self.run_gate())
        self.assertTrue(self.state["account_identity_failed"])
        self.assertEqual(self.state["terminal_status"], trade.MANUAL_TWO_CITY_TERMINAL_FAILED)

    def test_stop_does_not_capture_confirm_or_consume_recovery_budget(self):
        self.context.tasker.stopping = True
        self.state["account_identity_main_map_recoveries"] = 1
        before = deepcopy(self.state)
        self.assertFalse(self.run_gate())
        self.assertEqual(self.state, before)
        self.frame.assert_not_called()
        self.context.tasker.controller.post_click.assert_not_called()

    def test_confirmed_uid_clears_the_pending_main_map_recovery_budget(self):
        self.state["account_identity_main_map_recoveries"] = 2
        with patch.object(trade, "_load_account_config", return_value={}):
            self.assertTrue(trade._manual_two_city_confirm_account_identity(["UID:22222222"]))
        self.assertNotIn("account_identity_main_map_recoveries", self.state)
        self.assertTrue(self.state["account_identity_confirmed"])

    def test_failed_gate_checks_terminal_state_before_retrying_recovery(self):
        root = Path(__file__).resolve().parents[1]
        pipeline = json.loads(
            (root / "assets/resource/base/pipeline/business/trade/manual_two_city_business.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(
            pipeline["ManualTwoCityBusinessAccountIdentityMainMapReady"]["on_error"],
            ["ManualTwoCityBusinessAccountIdentityFailedStop", "StateRecoveryStart"],
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tests.test_trade_runtime_fix import trade
from maa_resonance.logic.navigation_runtime import run_navigation_transition


class NavigationAgentTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.params = {
            "probe_name": "NavigationTest",
            "source_texts": ["我要买"],
            "source_roi": [700, 260, 530, 220],
            "ready_nodes": ["BuyReady"],
        }
        self.images = []
        self.controller = Mock()
        self.controller.post_click.return_value.wait.return_value.succeeded = True
        self.context = types.SimpleNamespace(
            tasker=types.SimpleNamespace(controller=self.controller, stopping=False),
            run_recognition=Mock(side_effect=self.recognize),
        )

    def recognize(self, name, image, override=None):
        if name.endswith("Loading"):
            return types.SimpleNamespace(hit=image.page == "loading")
        if name == "BuyReady":
            return types.SimpleNamespace(hit=image.page == "ready")
        if name.endswith("Source"):
            return types.SimpleNamespace(
                hit=image.page in ("menu", "loading"),
                all_results=[
                    {"text": "我要卖", "box": [780, 390, 80, 30]},
                    {"text": "我要买", "box": [780, 310, 80, 30]},
                ],
            )
        return types.SimpleNamespace(hit=False)

    def frames(self, pages):
        self.images = [types.SimpleNamespace(page=p, shape=(720, 1280, 3)) for p in pages]
        queue = iter(self.images)
        last = self.images[-1]

        def capture():
            image = next(queue, last)
            job = Mock(succeeded=True)
            job.get.return_value = image
            return types.SimpleNamespace(wait=lambda: job)

        self.controller.post_screencap.side_effect = capture

    def sleep(self, seconds):
        self.now += seconds

    def navigate(self):
        def runtime(**kwargs):
            return run_navigation_transition(**kwargs, clock=lambda: self.now, sleep=self.sleep)

        with patch.object(trade, "run_navigation_transition", side_effect=runtime):
            return trade._manual_two_city_open_navigation(self.context, **self.params)

    def test_loading_is_checked_before_readable_buttons_or_destination(self):
        self.frames(["loading", "loading", "menu", "ready"])
        result = self.navigate()
        self.assertTrue(result["ok"])
        self.assertEqual(result["loading_observations"], 2)
        self.controller.post_click.assert_called_once_with(820, 325)
        calls = self.context.run_recognition.call_args_list
        for loading_image in self.images[:2]:
            self.assertEqual([c.args[0] for c in calls if c.args[1] is loading_image], ["NavigationTestLoading"])
        self.assertEqual(self.controller.post_screencap.call_count, 4)

    def test_screencap_failure_does_not_use_cached_image(self):
        job = Mock(succeeded=False)
        self.controller.post_screencap.return_value.wait.return_value = job
        self.controller.cached_image = types.SimpleNamespace(page="menu", shape=(720, 1280, 3))
        result = self.navigate()
        self.assertEqual(result["reason"], "observe_error")
        self.controller.post_click.assert_not_called()
        self.context.run_recognition.assert_not_called()
        job.get.assert_not_called()

    def test_loading_probe_exception_does_not_authorize_input(self):
        self.frames(["menu"])
        self.context.run_recognition.side_effect = RuntimeError("OCR failed")
        self.assertEqual(self.navigate()["reason"], "observe_error")
        self.controller.post_click.assert_not_called()

    def test_loading_recognition_not_started_is_not_a_clear_page(self):
        self.frames(["menu"])
        self.context.run_recognition.return_value = None
        self.context.run_recognition.side_effect = None
        result = self.navigate()
        self.assertEqual(result["reason"], "observe_error")
        self.assertIn("loading recognition did not run", result["error"])
        self.context.run_recognition.assert_called_once()
        self.controller.post_click.assert_not_called()

    def test_menu_disappearing_does_not_reuse_old_click_point(self):
        self.frames(["menu", "unknown", "unknown", "ready"])
        self.assertTrue(self.navigate()["ok"])
        self.controller.post_click.assert_called_once_with(820, 325)

    def test_unchanged_menu_exhausts_local_click_budget(self):
        self.frames(["menu"])
        result = self.navigate()
        self.assertEqual(result["reason"], "click_limit")
        self.assertEqual(self.controller.post_click.call_count, 3)
        self.assertGreaterEqual(self.now, 6.0)

    def test_city_template_fallback_requires_a_fresh_hit(self):
        self.frames(["unknown"])
        self.params["allow_city_template"] = True
        self.context.run_recognition.side_effect = lambda name, image, *args: types.SimpleNamespace(
            hit=name == "ManualTwoCityBusinessOpenCurrentCityFallback",
        )
        observation = trade._manual_two_city_navigation_observation(self.context, **self.params)
        self.assertEqual(observation["point"], (1270, 494))
        self.assertEqual(observation["state"], "source")

    def test_trade_dispatch_returns_failure_when_input_did_not_enter_page(self):
        for phase, text in [("buy", "我要买"), ("sell", "我要卖")]:
            with self.subTest(phase=phase), \
                 patch.object(trade, "_manual_two_city_state", return_value={"trade_phase": phase}), \
                 patch.object(trade, "_manual_two_city_active_leg", return_value={}), \
                 patch.object(trade, "_append_user_log") as log, \
                 patch.object(trade, "_json_payload"), \
                 patch.object(trade, "_manual_two_city_open_navigation", return_value={
                     "ok": False, "reason": "click_limit", "clicks": 3,
                 }) as navigation:
                self.assertFalse(trade.ManualTwoCityBusinessShouldOpenSellAction().run(self.context, None))
                self.assertEqual(navigation.call_args.kwargs["source_texts"], [text])
                self.assertEqual(log.call_args.kwargs["event"], "manual_two_city_trade_outlet_dispatch_failed")

    def test_city_failure_routes_through_bounded_recovery(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / "assets/resource/base/pipeline/business/trade/manual_two_city_business.json").read_text(encoding="utf-8"))
        for node in ("ManualTwoCityBusinessOpenCurrentCityByOcr", "ManualTwoCityBusinessOpenCurrentCityFallback"):
            self.assertEqual(data[node]["action"]["param"]["custom_action"], "manual_two_city_business_open_current_city")
            self.assertEqual(data[node]["on_error"], "ManualTwoCityBusinessRecoverToCurrentCity")
        recovery = data["ManualTwoCityBusinessRecoverToCurrentCity"]
        self.assertEqual(recovery["action"]["param"]["custom_action_param"]["max_attempts"], 2)
        self.assertEqual(recovery["on_error"], "ManualTwoCityBusinessRecoveryFailedAfterResume")


if __name__ == "__main__":
    unittest.main()

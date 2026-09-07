from __future__ import annotations

import json
import re
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from tests.test_trade_runtime_fix import trade
from tests.test_travel_parser import SPLIT_605KM_TEXTS


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "ManualTwoCityBusiness"
STOPPED_TEXTS = ["剩余行程：790km", "目的地：海角城", "立即返航"]
CRUISING_TEXTS = ["剩余行程：790km", "目的地：海角城", "自动巡航中"]


class TravelStopRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.state = trade._manual_two_city_defaults()
        self.stack.enter_context(patch.object(trade, "_MANUAL_TWO_CITY_STATE", self.state))
        self.stack.enter_context(patch.object(trade, "_manual_two_city_active_leg", return_value={
            "buy_city": "栖羽站", "sell_city": "海角城",
        }))
        self.stack.enter_context(patch.object(trade, "_append_user_log"))
        self.stack.enter_context(patch.object(trade, "_json_payload"))
        self.stack.enter_context(patch.object(trade, "_manual_two_city_log_travel_progress"))
        self.stack.enter_context(patch.object(trade.CustomRecognition, "AnalyzeResult", types.SimpleNamespace, create=True))
        self.clock = self.stack.enter_context(patch.object(trade.time, "monotonic", return_value=100.0))
        self.context = object()
        self.image = object()
        self.argv = types.SimpleNamespace(image=self.image, node_name=PREFIX + "TapTravelContinue")
        path = ROOT / "assets/resource/base/pipeline/business/trade/manual_two_city_business.json"
        self.pipeline = json.loads(path.read_text(encoding="utf-8"))

    def continue_action(self, texts: list[str]) -> bool:
        with patch.object(trade, "_ocr_texts", return_value=texts):
            return trade.ManualTwoCityBusinessTravelContinueIfNeededAction().run(self.context, self.argv)

    def select_travel_candidate(self, node_name: str, edge: str, texts: list[str]) -> str:
        # Evaluate this one candidate list only: a candidate that does not match
        # cannot use its own on_error before it has been entered by Maa.
        candidates = self.pipeline[PREFIX + node_name][edge]
        if isinstance(candidates, str):
            candidates = [candidates]
        for name in candidates:
            recognition = self.pipeline[name]["recognition"]
            if recognition["type"] == "DirectHit":
                return name
            if recognition["type"] == "OCR":
                expected = recognition["param"]["expected"]
                if any(re.search(pattern, text) for pattern in expected for text in texts):
                    return name
            elif recognition["type"] == "Custom":
                self.assertEqual(name, PREFIX + "TapTravelContinue")
                with patch.object(trade, "_manual_two_city_ocr_entries_from_image", return_value=(True, [], texts)):
                    result = trade.ManualTwoCityBusinessTravelContinueAvailableRecognition().analyze(self.context, self.argv)
                if result.box is not None:
                    return name
        self.fail(f"{node_name}.{edge} has no matching candidate for {texts!r}")

    def test_stopped_790km_with_return_button_can_resume(self) -> None:
        status = trade.travel_status_from_texts(STOPPED_TEXTS)
        self.assertEqual(status["destination"], "海角城")
        self.assertEqual(status["remaining_km"], 790)
        self.assertFalse(status["cruising"])
        self.assertTrue(trade._manual_two_city_should_continue_travel(status))
        self.assertTrue(self.continue_action(STOPPED_TEXTS))

    def test_split_605km_reaches_d_guard_and_does_not_reset_watchdog_as_event(self) -> None:
        self.assertTrue(self.run_watchdog_then_continue(SPLIT_605KM_TEXTS))
        self.assertEqual(self.state["travel_stall_remaining_km"], 605)
        self.assertEqual(self.state["travel_stall_hit_count"], 1)
        self.clock.return_value = 105.0
        self.assertTrue(self.run_watchdog_then_continue(SPLIT_605KM_TEXTS))
        self.assertEqual(self.state["travel_stall_hit_count"], 2)

    def test_split_distance_with_cruising_zero_or_no_destination_never_allows_d(self) -> None:
        for texts in (
            [*SPLIT_605KM_TEXTS, "自动巡航中"],
            ["目的地：海角城", "剩余行程：", "0km"],
            ["目的地", "剩余行程：", "605km"],
            ["目的地：海角城", "剩余行程：", "605km", "606km"],
        ):
            with self.subTest(texts=texts):
                self.assertFalse(self.continue_action(texts))
                with patch.object(trade, "_manual_two_city_ocr_entries_from_image", return_value=(True, [], texts)):
                    result = trade.ManualTwoCityBusinessTravelContinueAvailableRecognition().analyze(self.context, self.argv)
                self.assertIsNone(result.box)

    def test_cruising_arrived_and_incomplete_route_evidence_cannot_resume(self) -> None:
        cases = (
            CRUISING_TEXTS,
            ["目的地：海角城", "剩余行程：0km"],
            ["目的地：海角城"],
            ["剩余行程：790km"],
            ["立即返航"],
            [],
        )
        for texts in cases:
            with self.subTest(texts=texts):
                status = trade.travel_status_from_texts(texts)
                self.assertFalse(trade._manual_two_city_should_continue_travel(status))
                self.assertFalse(self.continue_action(texts))

    def test_continue_recognition_uses_the_supplied_frame_and_top_hud_roi(self) -> None:
        with patch.object(trade, "_manual_two_city_ocr_entries_from_image", return_value=(True, [], STOPPED_TEXTS)) as ocr, patch.object(
            trade, "_manual_two_city_screencap"
        ) as capture:
            result = trade.ManualTwoCityBusinessTravelContinueAvailableRecognition().analyze(self.context, self.argv)
        self.assertIsNotNone(result.box)
        self.assertTrue(result.detail["ok"])
        self.assertEqual(result.detail["status"]["remaining_km"], 790)
        self.assertIn("reason", result.detail)
        ocr.assert_called_once_with(
            self.context, PREFIX + "TravelContinueProbe", ["目的地", "剩余行程", "巡航"], self.image,
            roi=[460, 16, 380, 145],
        )
        capture.assert_not_called()

    def test_resumed_cruising_between_initial_check_and_click_is_rejected(self) -> None:
        self.assertTrue(self.continue_action(STOPPED_TEXTS))
        with patch.object(trade, "_manual_two_city_ocr_entries_from_image", return_value=(True, [], CRUISING_TEXTS)):
            result = trade.ManualTwoCityBusinessTravelContinueAvailableRecognition().analyze(self.context, self.argv)
        self.assertIsNone(result.box)
        self.assertFalse(result.detail["ok"])
        self.assertTrue(result.detail["status"]["cruising"])

    def test_continue_recognition_does_not_reuse_an_old_frame_if_image_missing(self) -> None:
        with patch.object(trade, "_manual_two_city_ocr_entries_from_image") as ocr, patch.object(
            trade, "_manual_two_city_screencap"
        ) as capture:
            result = trade.ManualTwoCityBusinessTravelContinueAvailableRecognition().analyze(
                self.context, types.SimpleNamespace(image=None, node_name=PREFIX + "TapTravelContinue"),
            )
        self.assertIsNone(result.box)
        self.assertFalse(result.detail["ok"])
        ocr.assert_not_called()
        capture.assert_not_called()

    def test_continue_recognition_failure_never_allows_d_gear(self) -> None:
        for response in ((False, [], []), (False, [], STOPPED_TEXTS), RuntimeError("OCR unavailable")):
            with self.subTest(response=response):
                kwargs = {"side_effect": response} if isinstance(response, Exception) else {"return_value": response}
                with patch.object(trade, "_manual_two_city_ocr_entries_from_image", **kwargs):
                    result = trade.ManualTwoCityBusinessTravelContinueAvailableRecognition().analyze(self.context, self.argv)
                self.assertIsNone(result.box)
                self.assertFalse(result.detail["ok"])

    def run_watchdog_then_continue(self, texts: list[str]) -> bool:
        with patch.object(trade, "_manual_two_city_ocr_entries", return_value=(True, [], texts)) as ocr:
            stalled = trade.ManualTwoCityBusinessTravelStallWatchdogAction().run(self.context, self.argv)
        ocr.assert_called_once()
        self.assertFalse(stalled)
        progress_name = self.select_travel_candidate("TravelStallWatchdog", "on_error", texts)
        self.assertEqual(progress_name, PREFIX + "TravelInProgress")
        should_continue = self.continue_action(texts)
        progress_node = self.pipeline[progress_name]
        if should_continue:
            tap_name = self.select_travel_candidate("TravelInProgress", "next", texts)
            self.assertEqual(tap_name, PREFIX + "TapTravelContinue")
            with patch.object(trade, "_manual_two_city_ocr_entries_from_image", return_value=(True, [], texts)):
                result = trade.ManualTwoCityBusinessTravelContinueAvailableRecognition().analyze(self.context, self.argv)
            self.assertIsNotNone(result.box)
            self.assertEqual(self.pipeline[tap_name]["action"]["param"]["target"], [1248, 616])
        else:
            self.assertEqual(progress_node["on_error"], PREFIX + "TravelMonitor")
        return should_continue

    def test_non_stalled_watchdog_falls_through_to_stopped_train_recovery(self) -> None:
        self.assertTrue(self.run_watchdog_then_continue(STOPPED_TEXTS))
        self.assertEqual(self.state["travel_stall_remaining_km"], 790)
        self.assertEqual(self.state["travel_stall_hit_count"], 1)

    def test_normal_cruising_still_runs_watchdog_and_returns_without_d_click(self) -> None:
        self.assertFalse(self.run_watchdog_then_continue(CRUISING_TEXTS))
        self.assertEqual(self.state["travel_stall_hit_count"], 1)
        self.assertFalse(self.state.get("travel_stall_restart_pending"))

    def test_stopped_frame_after_restart_can_resume_without_second_failure(self) -> None:
        self.state.update(
            travel_stall_restart_count=1,
            travel_stall_remaining_km=790,
            travel_stall_since=1.0,
            travel_stall_hit_count=35,
        )
        self.assertTrue(trade.ManualTwoCityBusinessTravelStuckRestartDoneAction().run(self.context, self.argv))
        self.assertEqual(self.state["travel_stall_restart_count"], 1)
        self.assertNotIn("travel_stall_since", self.state)
        self.assertTrue(self.run_watchdog_then_continue(STOPPED_TEXTS))
        self.assertFalse(self.state.get("travel_stall_failed_pending"))

    def test_battle_loading_arrival_or_missing_hud_returns_to_monitor_after_watchdog(self) -> None:
        for texts in (["正在规划逃生路线"], ["00:18", "3/3"], ["访问地区"], ["确认"], []):
            with self.subTest(texts=texts):
                with patch.object(trade, "_manual_two_city_ocr_entries", return_value=(False, [], texts)):
                    self.assertFalse(trade.ManualTwoCityBusinessTravelStallWatchdogAction().run(self.context, self.argv))
                self.assertEqual(
                    self.select_travel_candidate("TravelStallWatchdog", "on_error", texts),
                    PREFIX + "TravelMonitor",
                )
                self.assertFalse(self.state.get("travel_stall_restart_pending"))

    def test_screen_change_before_d_click_returns_to_monitor_without_entering_click_node(self) -> None:
        for current_texts in (["正在规划逃生路线"], ["00:18", "3/3"], ["访问地区"], CRUISING_TEXTS, []):
            with self.subTest(current_texts=current_texts):
                self.assertTrue(self.continue_action(STOPPED_TEXTS))
                self.assertEqual(
                    self.select_travel_candidate("TravelInProgress", "next", current_texts),
                    PREFIX + "TravelMonitor",
                )

    def test_pipeline_preserves_watchdog_order_and_fresh_guard_before_d(self) -> None:
        candidates = self.pipeline[PREFIX + "TravelMonitor"]["next"]
        self.assertLess(candidates.index(PREFIX + "TravelStallWatchdog"), candidates.index(PREFIX + "TravelInProgress"))
        self.assertEqual(self.pipeline[PREFIX + "TravelStallWatchdog"]["on_error"], [
            PREFIX + "TravelInProgress", PREFIX + "TravelMonitor",
        ])
        progress = self.pipeline[PREFIX + "TravelInProgress"]
        self.assertEqual(progress["next"], [PREFIX + "TapTravelContinue", PREFIX + "TravelMonitor"])
        monitor = self.pipeline[PREFIX + "TravelMonitor"]
        self.assertEqual(monitor["recognition"]["type"], "DirectHit")
        self.assertEqual(monitor["action"]["type"], "DoNothing")
        self.assertEqual(progress["pre_delay"], 0)
        self.assertEqual(progress["post_delay"], 0)
        self.assertEqual(progress["action"]["param"]["custom_action"], "manual_two_city_business_travel_continue_if_needed")
        tap = self.pipeline[PREFIX + "TapTravelContinue"]
        self.assertEqual(tap["recognition"]["type"], "Custom")
        self.assertEqual(tap["recognition"]["param"]["custom_recognition"], "manual_two_city_business_travel_continue_available")
        self.assertEqual(tap["action"]["type"], "Click")
        self.assertEqual(tap["action"]["param"]["target"], [1248, 616])
        self.assertEqual(tap["pre_delay"], 0)
        self.assertEqual(tap["post_delay"], 900)
        self.assertEqual(tap["next"], PREFIX + "TravelMonitor")
        self.assertEqual(tap["on_error"], PREFIX + "TravelMonitor")


if __name__ == "__main__":
    unittest.main()

import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


PIPELINE = json.loads(
    (Path(__file__).resolve().parents[1] / "assets/resource/base/pipeline/mainline/mainline_advance.json")
    .read_text(encoding="utf-8")
)


class MainlineMapNavigationTest(unittest.TestCase):
    def test_zero_and_positive_distance_match_the_whole_field(self):
        zero = re.compile(PIPELINE["MainlineMapZeroDistance"]["expected"][0])
        positive = re.compile(PIPELINE["MainlineMapPositiveDistance"]["expected"][0])
        for text, kind in (
            ("0km", "zero"), ("路程： 0 KM", "zero"), ("路程:0.0km", "zero"),
            ("10km", "positive"), ("路程：790km", "positive"), ("791km", "positive"),
            ("路程：0.5km", "positive"), ("路程：10km 0km", ""), ("约0km", ""), ("路程：", ""),
        ):
            with self.subTest(text=text):
                self.assertEqual(bool(zero.search(text)), kind == "zero")
                self.assertEqual(bool(positive.search(text)), kind == "positive")

    def test_only_focusing_the_quest_station_can_authorize_travel(self):
        for target in ("MainlineMapAlreadyAtStation", "MainlineMapGoDestination"):
            sources = {name for name, node in PIPELINE.items() if target in node.get("next", [])}
            self.assertEqual(sources, {"MainlineMapFocusQuestStation"})
        self.assertEqual(
            PIPELINE["MainlineMapRemoteDestination"]["all_of"],
            ["MainlineMapGoButton", "MainlineMapPositiveDistance"],
        )
        self.assertEqual(
            PIPELINE["MainlineMapFocusQuestStation"]["custom_recognition_param"]["blockers"],
            ["MainlineMapSelectionVisible", "MainlineMapUnverifiedPrompt"],
        )

    def test_map_recognition_rejects_a_blocking_panel_on_the_target_frame(self):
        from agent.mainline_quest_action import MainlineMapUnobstructedRecognition

        hit = SimpleNamespace(hit=True, box=(80, 100, 30, 20))
        miss = SimpleNamespace(hit=False, box=None)
        image = object()
        argv = SimpleNamespace(
            custom_recognition_param=json.dumps({"target": "focus", "blockers": ["detail", "confirm"]}),
            image=image,
        )
        for detail, confirm, expected in ((miss, miss, hit.box), (hit, miss, None), (miss, hit, None), (None, miss, None)):
            with self.subTest(detail=detail, confirm=confirm):
                responses = {"focus": hit, "detail": detail, "confirm": confirm}
                context = Mock()
                context.run_recognition.side_effect = lambda node, frame: responses[node]
                self.assertEqual(MainlineMapUnobstructedRecognition().analyze(context, argv), expected)
                for call in context.run_recognition.call_args_list:
                    self.assertIs(call.args[1], image)

    def test_unverified_confirmation_cancels_and_awaits_disappearance(self):
        self.assertEqual(PIPELINE["MainlineMapUnverifiedPrompt"]["next"], ["MainlineMapCancelUnverifiedPrompt"])
        self.assertEqual(
            PIPELINE["MainlineMapCancelUnverifiedPrompt"]["all_of"],
            ["MainlineMapCancelButton", "MainlineMapUnverifiedPrompt"],
        )
        self.assertEqual(PIPELINE["MainlineMapCancelUnverifiedPrompt"]["next"], ["MainlineMapWaitPromptClosed"])
        self.assertTrue(PIPELINE["MainlineMapWaitPromptClosed"]["inverse"])

    def test_delayed_confirmation_waits_and_unrecognized_screens_end_the_task(self):
        fail = "MainlineAdvanceUnknownStop"
        for node in ("MainlineAdvanceLoop", "MainlineMapFocusQuestStation", "MainlineMapGoDestination",
                     "MainlineMapHighLevelConfirm", "MainlineMapDepartNow"):
            with self.subTest(node=node):
                self.assertEqual(PIPELINE[node]["on_error"], [fail])
                self.assertLessEqual(PIPELINE[node]["timeout"], 60_000)
        self.assertEqual(PIPELINE[fail]["custom_action"], "mainline_navigation_failed")
        for node in ("MainlineMapGoDestination", "MainlineMapHighLevelConfirm", "MainlineMapDepartNow"):
            self.assertNotIn("MainlineAdvanceLoop", PIPELINE[node]["next"])
            self.assertNotIn(node, PIPELINE[node]["next"])
        self.assertIn("MainlineMapDepartNow", PIPELINE["MainlineMapGoDestination"]["next"])
        self.assertIn("MainlineTravelInProgress", PIPELINE["MainlineMapDepartNow"]["next"])

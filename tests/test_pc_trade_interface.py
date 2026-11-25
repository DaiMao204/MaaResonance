import json
import unittest
from pathlib import Path


ASSETS = Path(__file__).resolve().parents[1] / "assets"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class PcTradeInterfaceTest(unittest.TestCase):
    def test_task_visibility_and_trade_presets(self):
        interface = read_json(ASSETS / "interface.json")
        tasks = [task for path in interface["import"] for task in read_json(ASSETS / path)["task"]]
        manual, auto, launch = "ManualTwoCityBusiness", "AutoTwoCityBusiness", "LaunchGame"
        custom_pc_tasks = {
            "WakeUp",
            "DailyPrep",
            "AutoShop",
            "CoopAssault",
            "EventStageFarm",
            "EventStoryDaily",
            "DailyClaim",
            "DailyRoutine",
            "AutoBattle",
            "AutoTeamFormation",
            "StorySkip",
        }
        pc_controllers = ("Win32", "Win32BackgroundWindowPos", "Win32BackgroundCursorPos")
        available = {ctrl: {t["name"] for t in tasks if ctrl in t["controller"]} for ctrl in ("ADB", *pc_controllers)}
        for ctrl in pc_controllers:
            with self.subTest(controller=ctrl):
                self.assertEqual(available[ctrl], {manual} | custom_pc_tasks)
        self.assertTrue(({manual, auto, launch} | custom_pc_tasks) <= available["ADB"])

        presets = {p["name"]: [t for t in p["task"] if t["enabled"]] for p in interface["preset"]}
        pc = presets["pc-manual-business"]
        self.assertEqual([t["name"] for t in pc], [manual])
        options = pc[0]["option"]
        self.assertEqual(options["ManualTwoCityRunMode"], "one_round")
        self.assertEqual(int(options["ManualTwoCityStartParams"]["start_book"]), 0)
        self.assertEqual(int(options["ManualTwoCityTargetParams"]["target_book"]), 0)
        for preset, task in (("manual-business", manual), ("auto-business", auto)):
            enabled = presets[preset]
            self.assertEqual([t["name"] for t in enabled], [launch, task])
            self.assertEqual(enabled[1]["option"]["ManualTwoCityRunMode"], "until_fatigue_exhausted")

        all_in_one = next(p for p in interface["preset"] if p["name"] == "daily-all-in-one")
        self.assertEqual(
            [(t["name"], bool(t["enabled"])) for t in all_in_one["task"]],
            [
                ("WakeUp", True),
                ("DailyPrep", True),
                ("AutoShop", True),
                ("CoopAssault", True),
                ("EventStageFarm", True),
                ("EventStoryDaily", True),
                ("AutoTwoCityBusiness", False),
                ("DailyClaim", True),
            ],
        )

    def test_android_lifecycle_actions_are_overridden_only_on_pc(self):
        interface = read_json(ASSETS / "interface.json")
        controllers = {entry["name"]: entry for entry in interface["controller"]}
        official = next(resource for resource in interface["resource"] if resource["name"] == "official")
        expected_pc_modes = {
            "Win32": ("Seize", "Seize"),
            "Win32BackgroundWindowPos": ("PostMessageWithWindowPos", "PostMessage"),
            "Win32BackgroundCursorPos": ("PostMessageWithCursorPos", "PostMessage"),
        }
        self.assertEqual(set(official["controller"]), {"ADB", *expected_pc_modes.keys()})
        self.assertEqual(official["path"], ["./resource/base"])
        self.assertFalse(controllers["ADB"].get("attach_resource_path"))
        for ctrl_name, (mouse_mode, keyboard_mode) in expected_pc_modes.items():
            with self.subTest(controller=ctrl_name):
                ctrl_cfg = controllers[ctrl_name]
                self.assertEqual(ctrl_cfg["type"], "Win32")
                self.assertEqual(ctrl_cfg["display_short_side"], 720)
                self.assertEqual(ctrl_cfg["attach_resource_path"], ["./resource/pc"])
                self.assertEqual(ctrl_cfg["win32"]["screencap"], "FramePool")
                self.assertEqual(ctrl_cfg["win32"]["mouse"], mouse_mode)
                self.assertEqual(ctrl_cfg["win32"]["keyboard"], keyboard_mode)
        base = {}
        for path in (ASSETS / official["path"][0] / "pipeline").rglob("*.json"):
            base.update(read_json(path))
        pc = read_json(ASSETS / "resource/pc/pipeline/pc_manual_business.json")
        expected = {
            "LaunchGameStartApp": "StartApp",
            "StateRecoveryRestartGameOnce": "StopApp",
            "StateRecoveryStartGameOnce": "StartApp",
            "ManualTwoCityBusinessTravelStuckRestartStopApp": "StopApp",
            "ManualTwoCityBusinessTravelStuckRestartStartApp": "StartApp",
        }
        for node, action in expected.items():
            with self.subTest(node=node):
                self.assertEqual(base[node]["action"], {"type": action, "param": {"package": "com.hermes.goda"}})
                self.assertEqual(pc[node]["action"], "DoNothing")

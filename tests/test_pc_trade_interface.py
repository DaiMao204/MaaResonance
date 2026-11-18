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
        available = {ctrl: {t["name"] for t in tasks if ctrl in t["controller"]} for ctrl in ("ADB", "Win32")}
        self.assertEqual(available["Win32"], {manual})
        self.assertTrue({manual, auto, launch} <= available["ADB"])

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

    def test_android_lifecycle_actions_are_overridden_only_on_pc(self):
        interface = read_json(ASSETS / "interface.json")
        controllers = {entry["name"]: entry for entry in interface["controller"]}
        official = next(resource for resource in interface["resource"] if resource["name"] == "official")
        self.assertEqual(set(official["controller"]), {"ADB", "Win32"})
        self.assertEqual(official["path"], ["./resource/base"])
        self.assertFalse(controllers["ADB"].get("attach_resource_path"))
        self.assertEqual(controllers["Win32"]["attach_resource_path"], ["./resource/pc"])
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

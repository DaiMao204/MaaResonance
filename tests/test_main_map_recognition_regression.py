import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def _iter_main_map_thresholds(node: object):
    if isinstance(node, dict):
        if node.get("template") == "main_map.png" and "threshold" in node:
            yield float(node["threshold"])
        for value in node.values():
            yield from _iter_main_map_thresholds(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_main_map_thresholds(item)


class MainMapRecognitionRegressionTests(unittest.TestCase):
    def test_all_pipeline_and_task_main_map_thresholds_are_relaxed(self) -> None:
        checked = 0
        for path in sorted((ROOT / "assets" / "resource").rglob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for threshold in _iter_main_map_thresholds(data):
                checked += 1
                self.assertLessEqual(
                    threshold,
                    0.90,
                    msg=f"{path} has overly strict main_map.png threshold={threshold}",
                )
        self.assertGreaterEqual(checked, 10)

    def test_agent_main_map_probe_threshold_is_relaxed(self) -> None:
        source = (ROOT / "agent" / "profile_prestige_action.py").read_text(encoding="utf-8")
        match = re.search(
            r'StateRecoveryNavigationMainMapTemplateProbe[\s\S]{0,200}?threshold=([0-9.]+)',
            source,
        )
        self.assertIsNotNone(match)
        self.assertLessEqual(float(match.group(1)), 0.90)

    def test_profile_entry_nodes_have_ocr_fallbacks(self) -> None:
        read_pipe = json.loads(
            (ROOT / "assets/resource/base/pipeline/business/profile/account_profile_read.json").read_text(
                encoding="utf-8"
            )
        )
        prestige_pipe = json.loads(
            (ROOT / "assets/resource/base/pipeline/business/profile/account_profile_prestige.json").read_text(
                encoding="utf-8"
            )
        )
        role_pipe = json.loads(
            (ROOT / "assets/resource/base/pipeline/business/profile/account_profile_role_resonance.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            read_pipe["AccountProfileReadStart"]["next"],
            ["AccountProfilePrestigeStart", "AccountProfilePrestigeStartByOcr"],
        )
        self.assertEqual(
            read_pipe["AccountProfileUidRead"]["next"],
            ["AccountProfilePrestigeStart", "AccountProfilePrestigeStartByOcr"],
        )
        self.assertIn("AccountProfilePrestigeStartByOcr", prestige_pipe)
        self.assertEqual(
            prestige_pipe["AccountProfilePrestigeStartByOcr"]["action"],
            prestige_pipe["AccountProfilePrestigeStart"]["action"],
        )
        self.assertEqual(
            prestige_pipe["AccountProfilePrestigeStartByOcr"]["next"],
            prestige_pipe["AccountProfilePrestigeStart"]["next"],
        )

        self.assertIn("AccountProfileRoleResonanceStartByOcr", role_pipe)
        self.assertEqual(
            role_pipe["AccountProfileRoleResonanceStartByOcr"]["target"],
            role_pipe["AccountProfileRoleResonanceStart"]["target"],
        )
        self.assertEqual(
            role_pipe["AccountProfileRoleResonanceStartByOcr"]["next"],
            role_pipe["AccountProfileRoleResonanceStart"]["next"],
        )

        for task_name in ("AutoTwoCityBusiness", "ManualTwoCityBusiness"):
            task = json.loads((ROOT / f"assets/resource/tasks/{task_name}.json").read_text(encoding="utf-8"))
            overrides = task["task"][0]["pipeline_override"]
            self.assertEqual(
                overrides["AccountProfileUidRead"]["next"],
                ["AccountProfilePrestigeStart", "AccountProfilePrestigeStartByOcr"],
            )
            self.assertEqual(
                overrides["AccountProfileCityUnlockDone"]["next"],
                ["AccountProfileRoleResonanceStart", "AccountProfileRoleResonanceStartByOcr"],
            )


if __name__ == "__main__":
    unittest.main()

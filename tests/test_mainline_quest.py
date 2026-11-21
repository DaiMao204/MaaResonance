from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np

from maa_resonance.logic.mainline_quest import (
    compute_city_avatar_target,
    is_in_excluded_hud_zone,
    is_quest_icon_color_valid,
    parse_mainline_task_summary,
    select_best_quest_icon,
    select_lobby_quest_button,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MAINLINE_PIPELINE_PATH = REPO_ROOT / "assets" / "resource" / "base" / "pipeline" / "mainline" / "mainline_advance.json"
MAINLINE_TASK_PATH = REPO_ROOT / "assets" / "resource" / "tasks" / "MainlineAdvance.json"


class MainlineQuestLogicTest(unittest.TestCase):
    def test_compute_city_avatar_target_shifts_to_bottom_left_avatar(self) -> None:
        # Icon around (491, 474, 46, 46) -> center (514, 497) -> target (472, 539)
        box = compute_city_avatar_target((491, 474, 46, 46))
        cx = box[0] + box[2] // 2
        cy = box[1] + box[3] // 2
        self.assertEqual((cx, cy), (472, 539))

    def test_compute_city_avatar_target_clamps_to_screen_bounds(self) -> None:
        box = compute_city_avatar_target((4, 680, 30, 30), tap_size=24)
        self.assertGreaterEqual(box[0], 0)
        self.assertLessEqual(box[1] + box[3], 720)

    def test_excluded_hud_zones_block_task_panel_and_dev_bar(self) -> None:
        self.assertTrue(is_in_excluded_hud_zone((1010, 140, 32, 32)))
        self.assertTrue(is_in_excluded_hud_zone((240, 580, 40, 40)))
        self.assertTrue(is_in_excluded_hud_zone((100, 10, 40, 30)))
        # Top-edge NPC quest icon like Simon at [181, 54, 46, 46] must NOT be blocked
        self.assertFalse(is_in_excluded_hud_zone((181, 54, 46, 46)))
        self.assertFalse(is_in_excluded_hud_zone((491, 474, 46, 46)))

        simon_target = compute_city_avatar_target((181, 54, 46, 46))
        self.assertEqual((simon_target[0] + 12, simon_target[1] + 12), (162, 119))

    def test_color_gate_rejects_pure_red_bar_and_accepts_red_white_icon(self) -> None:
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        # Pure red region (BGR: 20, 20, 220) -> missing white book
        img[10:50, 10:50] = (20, 20, 220)
        self.assertFalse(is_quest_icon_color_valid(img, (10, 10, 40, 40)))

        # Red diamond + white center (BGR: 245, 245, 245) -> valid
        img[18:36, 18:38] = (245, 245, 245)
        self.assertTrue(is_quest_icon_color_valid(img, (10, 10, 40, 40)))

    def test_select_best_quest_icon_filters_hud_and_invalid_color(self) -> None:
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        # Valid red+white icon at (491, 474, 46, 46)
        img[474:520, 491:537] = (25, 25, 225)
        img[486:506, 502:526] = (245, 245, 245)
        candidates = [
            {"box": [1010, 140, 46, 46], "score": 0.99},  # HUD task panel -> ignored
            {"box": [600, 300, 46, 46], "score": 0.95},   # Black patch -> color invalid
            {"box": [491, 474, 46, 46], "score": 0.88},   # Valid city target
        ]
        chosen = select_best_quest_icon(candidates, image_bgr=img, min_score=0.70)
        self.assertIsNotNone(chosen)
        assert chosen is not None
        self.assertEqual(chosen["box"], (491, 474, 46, 46))
        self.assertEqual(chosen["center"], (514, 497))

    def test_select_lobby_quest_button_picks_nearest_ocr_button(self) -> None:
        buttons = [
            {"text": "作战终端", "box": [1060, 355, 190, 60]},
            {"text": "访问城市", "box": [1060, 455, 190, 60]},
            {"text": "启程", "box": [1135, 625, 110, 60]},
        ]
        # Icon pinned at top-left of 访问城市 (around x=1015, y=435)
        picked = select_lobby_quest_button((995, 415, 46, 46), buttons)
        self.assertEqual(picked, (1060, 455, 190, 60))

        # Also accept agent._ocr_entries x/y/w/h schema
        agent_buttons = [
            {"text": "访问城市", "x": 1060, "y": 455, "w": 190, "h": 60, "center_x": 1155.0, "center_y": 485.0},
        ]
        self.assertEqual(select_lobby_quest_button((995, 415, 46, 46), agent_buttons), (1060, 455, 190, 60))

        # Fallback without OCR
        self.assertEqual(select_lobby_quest_button((995, 340, 46, 46), []), (1100, 355, 140, 50))

    def test_parse_mainline_task_summary(self) -> None:
        summary = parse_mainline_task_summary([
            {"text": "任务"},
            {"text": "在贡露城与徐佳心对话。"},
            {"text": "推荐等级：68"},
        ])
        self.assertEqual(summary, "在贡露城与徐佳心对话。 | 推荐等级：68")

    def test_mainline_pipeline_defeat_stop_and_lobby_threshold(self) -> None:
        pipeline = json.loads(MAINLINE_PIPELINE_PATH.read_text(encoding="utf-8"))
        loop_next = pipeline["MainlineAdvanceLoop"]["next"]
        self.assertIn("MainlineBattleDefeatStop", loop_next)
        defeat_idx = loop_next.index("MainlineBattleDefeatStop")
        for settle_node in (
            "MainlineSettleMission",
            "MainlineSettleNextTemplate",
            "MainlineSettleNextOcr",
        ):
            self.assertLess(defeat_idx, loop_next.index(settle_node))

        defeat = pipeline["MainlineBattleDefeatStop"]
        self.assertEqual(defeat["recognition"], "OCR")
        self.assertEqual(defeat["expected"], ["作战失败", "挑战失败", "重新挑战"])
        self.assertEqual(defeat["action"], "StopTask")
        self.assertEqual(pipeline["MainlineInLobbyCheckByTemplate"]["threshold"], 0.88)
        self.assertNotIn("MainlineBattleAutoOptMinCost", pipeline)

    def test_mainline_task_manifest_is_experimental_adb_only_without_weighted(self) -> None:
        manifest = json.loads(MAINLINE_TASK_PATH.read_text(encoding="utf-8"))
        task = next(item for item in manifest["task"] if item["name"] == "MainlineAdvance")
        self.assertEqual(task["controller"], ["ADB"])
        self.assertEqual(task["group"], ["experimental"])
        self.assertEqual(
            task["option"],
            [
                "MainlineUseClarityMedicine",
                "MainlineStoryChoice",
                "MainlineFormationMode",
                "MainlinePreferNativeAuto",
                "MainlineLeaderSkill",
            ],
        )
        self.assertEqual(
            set(manifest["option"].keys()),
            {
                "MainlineUseClarityMedicine",
                "MainlineClarityLimits",
                "MainlineStoryChoice",
                "MainlineFormationMode",
                "MainlineFormationRoles",
                "MainlinePreferNativeAuto",
                "MainlineLeaderSkill",
            },
        )


if __name__ == "__main__":
    unittest.main()

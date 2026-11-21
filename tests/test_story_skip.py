import unittest

import numpy as np

from maa_resonance.logic.story_skip import (
    detect_dialogue_choices,
    find_story_confirm_point,
    find_story_skip_point,
    has_story_hud,
    plan_story_skip_step,
)


class StorySkipLogicTest(unittest.TestCase):
    def _make_blank_frame(self, value: int = 30) -> np.ndarray:
        return np.full((720, 1280, 3), value, dtype=np.uint8)

    def _draw_choice_bar(self, image: np.ndarray, y1: int, y2: int) -> None:
        image[y1:y2, 357:922, :] = 240
        # Simulate left speech-bubble icon & centered text dark pixels
        image[y1 + 16 : y2 - 16, 372:406, :] = 20
        image[y1 + 22 : y2 - 22, 520:760, :] = 30

    def test_has_story_hud_and_skip_point(self):
        top_entries = [
            {"text": "回顾", "box": [80, 23, 46, 25]},
            {"text": "隐藏", "box": [225, 23, 45, 25]},
            {"text": "自动", "box": [961, 23, 45, 27]},
            {"text": "】跳过", "box": [1146, 22, 91, 29]},
        ]
        self.assertTrue(has_story_hud(top_entries))
        self.assertEqual(find_story_skip_point(top_entries), (1192, 36))

        non_story = [{"text": "快速编队", "box": [1045, 41, 65, 19]}]
        self.assertFalse(has_story_hud(non_story))
        self.assertIsNone(find_story_skip_point(non_story))

    def test_detect_dialogue_choices_finds_bars_even_with_text(self):
        frame = self._make_blank_frame(25)
        self._draw_choice_bar(frame, 256, 322)
        self._draw_choice_bar(frame, 346, 412)

        points = detect_dialogue_choices(frame)
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0][0], 640)
        self.assertAlmostEqual(points[0][1], 289, delta=2)
        self.assertAlmostEqual(points[1][1], 379, delta=2)

    def test_plan_story_skip_step_prioritizes_confirm_then_choice_then_skip(self):
        frame = self._make_blank_frame(25)
        self._draw_choice_bar(frame, 256, 322)
        top_entries = [{"text": "跳过", "box": [1148, 22, 89, 28]}]

        # Confirmation dialog takes highest priority
        step_confirm = plan_story_skip_step(
            frame,
            top_entries,
            center_entries=[{"text": "确认", "box": [740, 440, 120, 44]}],
        )
        self.assertEqual(step_confirm["reason"], "confirm_skip")
        self.assertEqual(step_confirm["point"], (800, 462))

        # Without dialog, choice bars are selected before clicking skip
        step_choice = plan_story_skip_step(frame, top_entries)
        self.assertEqual(step_choice["reason"], "select_choice")
        self.assertEqual(step_choice["choice_count"], 1)

        # Without choice bars, click skip
        plain_frame = self._make_blank_frame(25)
        step_skip = plan_story_skip_step(plain_frame, top_entries)
        self.assertEqual(step_skip["reason"], "click_skip")
        self.assertEqual(step_skip["point"], (1192, 36))

        # Outside story HUD, exit
        step_exit = plan_story_skip_step(plain_frame, [])
        self.assertEqual(step_exit["action"], "exit")
        self.assertIsNone(find_story_confirm_point([]))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
import numpy as np

from maa_resonance.logic.activity_hub import (
    find_activity_card,
    find_activity_category_point,
    has_activity_card_red_dot,
    is_activity_hub_entries,
    is_category_expanded,
)


class ActivityHubLogicTest(unittest.TestCase):
    def test_sidebar_recognition_and_card_lookup(self) -> None:
        sidebar_entries = [
            {"text": "▼限时活动", "box": [114, 83, 115, 28]},
            {"text": "启程签到", "box": [30, 174, 63, 19]},
            {"text": "糖霜记忆", "box": [29, 250, 63, 18]},
            {"text": "箱庭内外", "box": [25, 318, 67, 28]},
            {"text": "众志攻坚", "box": [26, 401, 66, 18]},
            {"text": "常规活动", "box": [140, 559, 94, 33]},
            {"text": "剧情活动", "box": [140, 615, 92, 29]},
            {"text": "经营活动", "box": [141, 669, 91, 29]},
        ]
        self.assertTrue(is_activity_hub_entries(sidebar_entries))
        self.assertTrue(is_category_expanded(sidebar_entries, "限时活动"))
        self.assertFalse(is_category_expanded(sidebar_entries, "常规活动"))
        self.assertEqual(find_activity_category_point(sidebar_entries, "常规活动"), (130, 576))

        card = find_activity_card(sidebar_entries, ("箱庭内外",))
        self.assertIsNotNone(card)
        assert card is not None
        self.assertEqual(card["label_cy"], 332)
        self.assertEqual(card["tap_point"], (108, 314))

        # Should never match category header as an activity card.
        self.assertIsNone(find_activity_card(sidebar_entries, ("限时活动",)))

    def test_red_dot_pixel_classifier(self) -> None:
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.assertFalse(has_activity_card_red_dot(img, 259))
        # BGR red dot in [180:212, 191:233]
        img[195:220, 185:208] = (20, 30, 230)
        self.assertTrue(has_activity_card_red_dot(img, 259))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from maa_resonance.logic.travel_parser import travel_status_from_texts


# Raw order from the 15:08 stopped-HUD OCR: the value is not next to its label.
SPLIT_605KM_TEXTS = [
    "□", "剩余行程：", "目的地：海角城", "J", "立即返航", "0", "605km", "□",
]


class TravelParserTest(unittest.TestCase):
    def test_real_stopped_hud_split_distance_is_order_independent(self):
        for texts in (SPLIT_605KM_TEXTS, list(reversed(SPLIT_605KM_TEXTS))):
            with self.subTest(texts=texts):
                status = travel_status_from_texts(texts)
                self.assertEqual(status["remaining_km"], 605)
                self.assertEqual(status["destination"], "海角城")
                self.assertFalse(status["cruising"])

    def test_split_distance_deduplicates_and_accepts_zero_and_unit_case(self):
        for values, expected in ((["605km", "605 KM"], 605), (["0km"], 0)):
            with self.subTest(values=values):
                status = travel_status_from_texts(["剩余行程：", *values])
                self.assertEqual(status["remaining_km"], expected)

    def test_missing_label_speed_bare_number_and_conflicting_values_stay_unknown(self):
        for texts in (
            ["605km"], ["目的地：海角城", "605km"],
            ["剩余行程：", "605"], ["剩余行程：", "605km/h"],
            ["剩余行程：605km/h"], ["剩余行程：", "605km", "606km"],
            ["剩余行程：6", "05km"],
            ["剩余行程：605km", "剩余行程：606km", "605km"],
        ):
            with self.subTest(texts=texts):
                self.assertIsNone(travel_status_from_texts(texts)["remaining_km"])

    def test_complete_labeled_distance_takes_priority_over_unrelated_value(self):
        status = travel_status_from_texts(["剩余行程：790km", "剩余行程：", "605km"])
        self.assertEqual(status["remaining_km"], 790)

    def test_destination_label_alone_is_never_a_destination(self):
        for text in ("目的地", "目的地：", "目的地:"):
            with self.subTest(text=text):
                self.assertIsNone(travel_status_from_texts([text, "剩余行程：", "605km"])["destination"])
        self.assertEqual(travel_status_from_texts(["目的地海角城"])["destination"], "海角城")

    def test_split_distance_does_not_hide_cruising(self):
        status = travel_status_from_texts([*SPLIT_605KM_TEXTS, "自动巡航中"])
        self.assertTrue(status["cruising"])
        self.assertEqual(status["remaining_km"], 605)


if __name__ == "__main__":
    unittest.main()

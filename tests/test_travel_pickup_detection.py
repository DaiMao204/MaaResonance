from __future__ import annotations

import types
import unittest
from unittest.mock import Mock

import numpy as np

from maa_resonance.logic import travel_pickup as pickup


def match(box, score=0.99, hit=True):
    return types.SimpleNamespace(
        hit=hit,
        best_result=types.SimpleNamespace(box=box, score=score),
    )


class TravelPickupDetectionTest(unittest.TestCase):
    def test_unknown_layout_never_produces_click_targets(self):
        context = types.SimpleNamespace(run_recognition=Mock())
        for image in (None, np.zeros((1080, 1920, 3), dtype=np.uint8),
                      np.zeros((720, 1280, 3), dtype=np.float32)):
            self.assertFalse(pickup.is_travel_hud(context, image))
            self.assertEqual(pickup.find_pickup_targets(context, image), [])
        context.run_recognition.assert_not_called()

    def test_dimmed_hud_is_rejected_even_if_template_score_is_high(self):
        # The matched text is offset within the original HUD; brightness must
        # still be sampled against that restored original origin.
        context = types.SimpleNamespace(run_recognition=Mock(return_value=match([622, 112, 81, 20])))
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        points = pickup._HUD_WHITE_POINTS
        image[105 + points[:, 1], 562 + points[:, 0]] = 240
        self.assertTrue(pickup.is_travel_hud(context, image))
        self.assertFalse(pickup.is_travel_hud(context, (image * 0.65).astype(np.uint8)))
        self.assertFalse(pickup.is_travel_hud(context, (image * 0.85).astype(np.uint8)))

    def test_missing_or_low_confidence_cruise_text_is_rejected_even_on_a_bright_screen(self):
        image = np.full((720, 1280, 3), 240, dtype=np.uint8)
        for detail in (match([622, 112, 81, 20], hit=False),
                       match([622, 112, 81, 20], score=0.879), None):
            with self.subTest(detail=detail):
                context = types.SimpleNamespace(run_recognition=Mock(return_value=detail))
                self.assertFalse(pickup.is_travel_hud(context, image))

    def test_invalid_restored_hud_bounds_or_template_size_are_rejected(self):
        image = np.full((720, 1280, 3), 240, dtype=np.uint8)
        for box in ([10, 112, 81, 20], [622, 2, 81, 20],
                    [1198, 112, 81, 20], [622, 112, 162, 33]):
            with self.subTest(box=box):
                context = types.SimpleNamespace(run_recognition=Mock(return_value=match(box)))
                self.assertFalse(pickup.is_travel_hud(context, image))

    def test_1080p_glyph_variant_uses_its_own_brightness_samples(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        points = pickup._HUD_1080_WHITE_POINTS
        image[114 + points[:, 1], 618 + points[:, 0]] = 240
        context = types.SimpleNamespace(run_recognition=Mock(side_effect=[
            match([618, 114, 81, 20], score=0.865, hit=False),
            match([618, 114, 81, 20]),
        ]))
        self.assertTrue(pickup.is_travel_hud(context, image))
        variant_call = context.run_recognition.call_args
        node = variant_call.args[2]["TravelPickupCruiseHud1080Template"]
        self.assertEqual(node["template"], ["business/travel_pickup/cruise_hud_text_1080.png"])
        self.assertEqual(node["threshold"], [0.88])

    def test_1080p_variant_does_not_bypass_dimmed_overlay_guard(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        points = pickup._HUD_1080_WHITE_POINTS
        image[114 + points[:, 1], 618 + points[:, 0]] = 240
        for factor in (0.65, 0.85):
            with self.subTest(factor=factor):
                context = types.SimpleNamespace(run_recognition=Mock(side_effect=[
                    match([618, 114, 81, 20], score=0.865, hit=False),
                    match([618, 114, 81, 20]),
                ]))
                self.assertFalse(pickup.is_travel_hud(context, (image * factor).astype(np.uint8)))

    def test_legacy_hud_success_does_not_run_fallback(self):
        context = types.SimpleNamespace(run_recognition=Mock(return_value=match([622, 112, 81, 20])))
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        points = pickup._HUD_WHITE_POINTS
        image[105 + points[:, 1], 562 + points[:, 0]] = 240
        self.assertTrue(pickup.is_travel_hud(context, image))
        context.run_recognition.assert_called_once()

    def test_blue_beams_and_train_light_alone_are_not_pickup_icons(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[180:500, 700:705] = [240, 130, 50]
        image[490:496, 260:880] = [240, 130, 50]
        context = types.SimpleNamespace(run_recognition=Mock())
        self.assertEqual(pickup.find_pickup_targets(context, image), [])
        context.run_recognition.assert_not_called()

    def test_blue_patch_needs_a_matching_cube_and_uses_its_center(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[300:330, 700:730] = [240, 130, 50]
        context = types.SimpleNamespace(run_recognition=Mock(return_value=match([706, 306, 18, 18], hit=False)))
        self.assertEqual(pickup.find_pickup_targets(context, image), [])
        context.run_recognition.return_value = match([706, 306, 18, 18])
        targets = pickup.find_pickup_targets(context, image)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["target"], [715, 315])
        # A pattern near the disk rather than inside it must not move the click.
        context.run_recognition.return_value = match([694, 294, 18, 18])
        self.assertEqual(pickup.find_pickup_targets(context, image), [])

    def test_task_panel_and_controls_are_outside_the_search(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[200:230, 1080:1110] = [240, 130, 50]
        image[650:680, 700:730] = [240, 130, 50]
        context = types.SimpleNamespace(run_recognition=Mock())
        self.assertEqual(pickup.find_pickup_targets(context, image), [])
        context.run_recognition.assert_not_called()

    def test_failed_malformed_or_low_confidence_sdk_results_are_rejected(self):
        for detail in (match([700, 300, 18, 18], hit=False),
                       match([700, 300, 18, 18], score=0.60),
                       match([700, 300, 18, 18], score=float("nan")),
                       match([700, 300, 0, 18]), match([-10, 300, 18, 18]),
                       match([1270, 300, 18, 18]), match(None)):
            self.assertIsNone(pickup._accepted_match(detail, 0.65))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import unittest
from pathlib import Path

from maa_resonance.logic.profile_parser import parse_account_uid


ROOT = Path(__file__).resolve().parents[1]


class ProfileUidParserTest(unittest.TestCase):
    def test_main_map_level_and_asset_boxes_do_not_extend_uid(self) -> None:
        texts = ["0", "9", "UID:8822020153", "079", "资产14604739", "妲己霸栾", "栾茶"]
        self.assertEqual(parse_account_uid(texts), "8822020153")
        self.assertEqual(parse_account_uid(list(reversed(texts))), "8822020153")

    def test_uid_labels_and_existing_number_lengths_are_supported(self) -> None:
        for text, expected in (
            ("UID: 1234", "1234"),
            ("uid：22222222", "22222222"),
            ("U1D:8822O2O153", "8822020153"),
            ("ID:123456789012", "123456789012"),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_account_uid([text, "079"]), expected)

    def test_separate_label_uses_one_number_box(self) -> None:
        for label in ("UID:", "uid", "U1D：", "ID", "WID:", "HID："):
            with self.subTest(label=label):
                self.assertEqual(parse_account_uid([label, "8822020153", "079"]), "8822020153")

    def test_observed_label_errors_do_not_fall_back_to_asset_amount(self) -> None:
        for texts in (
            ["UHD:8822020153"],
            ["O", "VID:8822020153", "妲己霸栾茶", "资产", "13242239"],
            ["WID:", "8822020153", "资产", "13242239"],
            ["HID：", "8822020153", "资产", "13242239"],
        ):
            with self.subTest(texts=texts):
                self.assertEqual(parse_account_uid(texts), "8822020153")

    def test_conflicting_labeled_uids_are_rejected(self) -> None:
        for texts in (
            ["UID:11111111", "UID:22222222"],
            ["UID:11111111", "UID:", "22222222"],
        ):
            with self.subTest(texts=texts):
                self.assertIsNone(parse_account_uid(texts))

    def test_duplicate_uid_observations_are_supported(self) -> None:
        self.assertEqual(parse_account_uid(["UID:8822020153", "UID:8822020153"]), "8822020153")
        self.assertEqual(parse_account_uid(["8822020153", "8822020153"]), "8822020153")

    def test_unlabeled_uid_must_be_one_unambiguous_number_box(self) -> None:
        self.assertEqual(parse_account_uid(["8822020153", "079", "资产14604739"]), "8822020153")
        for texts in (
            ["123", "456"],
            ["8822020153", "14604739"],
            ["资产14604739"],
            ["UID:???", "14604739"],
            [],
        ):
            with self.subTest(texts=texts):
                self.assertIsNone(parse_account_uid(texts))

    def test_uid_regions_cover_uid_without_the_level_row(self) -> None:
        profile = json.loads((ROOT / "assets/resource/base/pipeline/business/profile/account_profile_read.json").read_text(encoding="utf-8"))
        trade = json.loads((ROOT / "assets/resource/base/pipeline/business/trade/manual_two_city_business.json").read_text(encoding="utf-8"))
        regions = (
            profile["AccountProfileUidRead"]["recognition"]["param"]["roi"],
            trade["ManualTwoCityBusinessAccountIdentityRead"]["roi"],
        )
        # Actual UID and level boxes from the feedback's main-map OCR result.
        uid_x, uid_y, uid_w, uid_h = 124, 705, 69, 10
        level_bottom = 686 + 10
        for roi in regions:
            with self.subTest(roi=roi):
                x, y, w, h = roi
                self.assertLessEqual(x, uid_x)
                self.assertLessEqual(y, uid_y)
                self.assertGreaterEqual(x + w, uid_x + uid_w)
                self.assertGreaterEqual(y + h, uid_y + uid_h)
                self.assertGreaterEqual(y, level_bottom)


if __name__ == "__main__":
    unittest.main()

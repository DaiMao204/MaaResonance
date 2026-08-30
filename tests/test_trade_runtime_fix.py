from __future__ import annotations

import sys
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _decorator(_name):
    return lambda cls: cls


agent_server = types.ModuleType("maa.agent.agent_server")
agent_server.AgentServer = type(
    "AgentServer",
    (),
    {
        "custom_action": staticmethod(_decorator),
        "custom_recognition": staticmethod(_decorator),
    },
)
custom_action = types.ModuleType("maa.custom_action")
custom_action.CustomAction = type("CustomAction", (), {})
custom_recognition = types.ModuleType("maa.custom_recognition")
custom_recognition.CustomRecognition = type("CustomRecognition", (), {})
context = types.ModuleType("maa.context")
context.Context = type("Context", (), {})
sys.modules.update(
    {
        "maa": types.ModuleType("maa"),
        "maa.agent": types.ModuleType("maa.agent"),
        "maa.agent.agent_server": agent_server,
        "maa.custom_action": custom_action,
        "maa.custom_recognition": custom_recognition,
        "maa.context": context,
    }
)
sys.path.insert(0, str(ROOT / "agent"))

import profile_prestige_action as trade


class TradeRuntimeFixTest(unittest.TestCase):
    def setUp(self) -> None:
        self.goods = ["明前龙井", "龙井茶", "武林丝绸", "临安山核桃", "西湖醋鱼", "羽纸扇", "叫化童鸡"]
        self.leg = {
            "buy_city": "武林源",
            "sell_city": "岚心城",
            "restock": 3,
            "goods": self.goods,
            "goods_detail": [
                {"name": good, "num": amount}
                for good, amount in zip(self.goods, [84, 160, 104, 196, 156, 240, 360])
            ],
        }

    def test_inventory_and_product_lot_guards(self) -> None:
        entries = [
            {"text": "进货采买书", "center_x": 731, "center_y": 166},
            {"text": "0", "center_x": 664, "center_y": 191},
            {"text": "236", "center_x": 656, "center_y": 277},
        ]
        self.assertEqual(trade._manual_two_city_book_inventory_from_entries(entries), 0)
        entries[1]["text"] = "2"
        self.assertEqual(trade._manual_two_city_book_inventory_from_entries(entries), 2)
        self.assertTrue(trade._manual_two_city_product_scan_buy_lot_plausible(21, 4))
        self.assertTrue(trade._manual_two_city_product_scan_buy_lot_plausible(40, 13))
        self.assertFalse(trade._manual_two_city_product_scan_buy_lot_plausible(1, 39))
        self.assertFalse(trade._manual_two_city_product_scan_buy_lot_plausible(6, 65))

    def test_truncated_product_lot_retries_enhanced_ocr(self) -> None:
        digit_rois = [[578, 222, 56, 25], [572, 204, 74, 35]]
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_product_icon_lot_row_roi",
                    return_value=[560, 206, 92, 68],
                )
            )
            stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_product_icon_lot_digit_rois",
                    return_value=digit_rois,
                )
            )
            direct = stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_direct_digit_lot_ocr",
                    side_effect=[{"buy_lot": 1}, {"buy_lot": 11}],
                )
            )
            scaled = stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_scaled_digit_lot_ocr",
                    return_value={"buy_lot": 1},
                )
            )

            result = trade._manual_two_city_read_product_icon_lot_by_row(
                None,
                1,
                1,
                "岚心锦服",
                167.5,
                image=object(),
                expected_lot=9,
            )

        self.assertEqual(result["buy_lot"], 11)
        self.assertEqual(direct.call_count, 2)
        self.assertEqual(scaled.call_count, 2)
        first_attempt = result["digit_roi_attempts"][0]
        self.assertFalse(first_attempt["direct_digit_ocr"]["plausible"])
        self.assertFalse(first_attempt["scaled_digit_ocr"]["plausible"])

    def test_scaled_product_lot_prefers_plausible_variant(self) -> None:
        import numpy as np

        truncated = [{"text": "1", "x": 0, "y": 0, "w": 20, "h": 20, "center_x": 10, "center_y": 10}]
        complete = [{"text": "11", "x": 0, "y": 0, "w": 24, "h": 20, "center_x": 12, "center_y": 10}]
        with patch.object(
            trade,
            "_manual_two_city_ocr_entries_from_image",
            side_effect=[
                (True, truncated, ["1"]),
                (True, complete, ["11"]),
                (False, [], []),
                (False, [], []),
            ],
        ) as ocr:
            result = trade._manual_two_city_scaled_digit_lot_ocr(
                None,
                "TradeRuntimeFix",
                np.zeros((30, 70, 3), dtype=np.uint8),
                [0, 0, 56, 25],
                expected_lot=9,
            )

        self.assertEqual(result["buy_lot"], 11)
        self.assertEqual(result["source"], "contrast")
        self.assertEqual(ocr.call_count, 4)
        self.assertFalse(result["variants"][0]["plausible"])
        self.assertTrue(result["variants"][1]["plausible"])

    def test_product_lot_candidate_consensus_rejects_conflict(self) -> None:
        selected = trade._manual_two_city_select_product_lot_candidates(
            [
                {"value": 1, "source": "direct:1"},
                {"value": 11, "source": "direct:2"},
                {"value": 11, "source": "scaled:contrast"},
            ],
            9,
        )
        self.assertEqual(selected["buy_lot"], 11)
        self.assertEqual(selected["reason"], "candidate_consensus")

        conflict = trade._manual_two_city_select_product_lot_candidates(
            [
                {"value": 11, "source": "direct:1"},
                {"value": 12, "source": "direct:2"},
            ],
            9,
        )
        self.assertIsNone(conflict["buy_lot"])
        self.assertEqual(conflict["reason"], "candidate_conflict")

    def test_saved_product_lot_fallback_is_narrow_and_trusted(self) -> None:
        completion = {
            "missing_tax_rate": False,
            "missing_observed_buy_lot_goods": ["岚心锦服"],
            "saved_product_buy_lots": {"岚心锦服": 9},
        }
        self.assertEqual(
            trade._manual_two_city_safe_saved_buy_lot_fallbacks(
                completion,
                {"岚心锦服": 9},
            ),
            {"岚心锦服": 9},
        )
        completion["saved_product_buy_lots"] = {"岚心锦服": 1}
        self.assertEqual(
            trade._manual_two_city_safe_saved_buy_lot_fallbacks(
                completion,
                {"岚心锦服": 9},
            ),
            {},
        )
        completion.update(
            {
                "missing_observed_buy_lot_goods": ["岚心锦服", "黑毛牛排"],
                "saved_product_buy_lots": {"岚心锦服": 9, "黑毛牛排": 19},
            }
        )
        self.assertEqual(
            trade._manual_two_city_safe_saved_buy_lot_fallbacks(
                completion,
                {"岚心锦服": 9, "黑毛牛排": 19},
            ),
            {},
        )
        completion.update(
            {
                "missing_observed_buy_lot_goods": ["岚心锦服"],
                "saved_product_buy_lots": {"岚心锦服": 12},
            }
        )
        self.assertEqual(
            trade._manual_two_city_safe_saved_buy_lot_fallbacks(
                completion,
                {"岚心锦服": 9},
            ),
            {},
        )

    def test_product_scan_degrades_without_marking_saved_value_fresh(self) -> None:
        state = {
            "run_id": "trade-runtime-fix",
            "product_scan_city": "岚心城",
            "product_scan_targets": ["岚心锦服", "黑毛牛排"],
            "product_scan_statuses": {"岚心锦服": "normal", "黑毛牛排": "normal"},
            "product_scan_buy_lots": {"黑毛牛排": 22},
            "product_scan_expected_buy_lots": {"岚心锦服": 9, "黑毛牛排": 19},
            "product_scan_tax_rate": 0.05,
            "product_scan_city_trade_due": True,
            "product_scan_missing_trade_field_retry_count": 2,
            "product_scan_completed_cities": [],
        }
        completion = {
            "complete": False,
            "required_buy_lot_goods": ["岚心锦服", "黑毛牛排"],
            "missing_buy_lot_goods": ["岚心锦服"],
            "missing_observed_buy_lot_goods": ["岚心锦服"],
            "missing_effective_buy_lot_goods": [],
            "saved_fallback_buy_lot_goods": ["岚心锦服"],
            "saved_product_buy_lots": {"岚心锦服": 9, "黑毛牛排": 19},
            "missing_tax_rate": False,
            "effective_city_tax_rate": 0.05,
        }
        with ExitStack() as stack:
            stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=state))
            stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_update_city_product_statuses",
                    return_value={"changed": False},
                )
            )
            stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_city_trade_completion",
                    return_value=completion,
                )
            )
            observation = stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_update_city_trade_observation",
                    return_value={"changed": True},
                )
            )
            recalculate = stack.enter_context(
                patch.object(trade, "_manual_two_city_recalculate_after_product_scan", return_value=True)
            )
            stack.enter_context(patch.object(trade, "_append_user_log"))
            stack.enter_context(patch.object(trade, "_json_payload"))

            ok = trade.ManualTwoCityBusinessProductScanCompleteAction().run(None, None)

        self.assertTrue(ok)
        observation.assert_called_once()
        self.assertEqual(observation.call_args.kwargs["product_buy_lots"], {"黑毛牛排": 22})
        self.assertFalse(observation.call_args.kwargs["mark_read"])
        self.assertEqual(
            state["product_scan_degraded_trade_fallbacks"]["岚心城"]["product_buy_lots"],
            {"岚心锦服": 9},
        )
        self.assertIn("岚心城", state["product_scan_completed_cities"])
        self.assertFalse(state["product_scan_retry_missing_trade_fields"]["needed"])
        recalculate.assert_called_once_with("岚心城")

    def test_cargo_load_ocr_excludes_haggle_and_retries_until_stable(self) -> None:
        compact_entries = [
            {"text": "711300", "x": 1180, "y": 386, "w": 65, "h": 19},
            {"text": "砍价", "x": 905, "y": 444, "w": 45, "h": 20},
            {"text": "1+8", "x": 1207, "y": 451, "w": 25, "h": 12},
        ]
        compact = trade._manual_two_city_parse_buy_page_cargo_load(
            compact_entries,
            roi=trade.BUY_PAGE_CARGO_LOAD_PROBE_ROI,
        )
        self.assertEqual((compact["used"], compact["capacity"]), (7, 1300))

        selected_entries = [
            {"text": "7+1177", "x": 1136, "y": 388, "w": 57, "h": 16},
            {"text": "11300", "x": 1195, "y": 388, "w": 50, "h": 16},
            {"text": "1+8", "x": 1207, "y": 451, "w": 25, "h": 12},
        ]
        selected = trade._manual_two_city_parse_buy_page_cargo_load(
            selected_entries,
            roi=trade.BUY_PAGE_CARGO_LOAD_PROBE_ROI,
        )
        self.assertEqual((selected["used"], selected["capacity"]), (1184, 1300))

        with patch.object(
            trade,
            "_manual_two_city_probe_buy_page_cargo_load",
            side_effect=[
                ({"used": 9, "capacity": 1300, "priority": 4}, ["711300", "1+8"]),
                ({"used": 1184, "capacity": 1300, "priority": 4}, ["7+1177", "1300"]),
            ],
        ) as probe:
            cargo_load, texts, samples = trade._manual_two_city_probe_buy_page_cargo_load_with_retry(
                None,
                "TradeRuntimeFix",
                expected_capacity=1300,
                minimum_used=1170,
                attempts=3,
                delay=0,
            )
        self.assertEqual((cargo_load["used"], cargo_load["capacity"]), (1184, 1300))
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(len(samples), 2)
        self.assertIn("7+1177", texts)

    def test_quick_buy_cancel_is_verified_before_fallback(self) -> None:
        cancel_entry = {"text": "全部取消", "center_x": 1196, "center_y": 102}
        with ExitStack() as stack:
            ocr = stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_ocr_entries",
                    side_effect=[
                        (True, [cancel_entry], ["全部取消"]),
                        (True, [], ["全部买入"]),
                    ],
                )
            )
            click = stack.enter_context(patch.object(trade, "_manual_two_city_click"))
            cleared, texts = trade._manual_two_city_clear_top_all_buy_selection(None, "TradeRuntimeFix")
        self.assertTrue(cleared)
        self.assertEqual(ocr.call_count, 2)
        click.assert_called_once_with(None, (1196, 102), 0.55)
        self.assertEqual(texts, ["全部取消", "全部买入"])

    def _patch_runtime(self, stack: ExitStack, state: dict, ocr) -> tuple[Mock, list[tuple[int, int]]]:
        logs = Mock()
        clicks: list[tuple[int, int]] = []
        stack.enter_context(patch.object(trade, "_manual_two_city_state", side_effect=lambda reset=False: state))
        stack.enter_context(patch.object(trade, "_manual_two_city_active_leg", return_value=self.leg))
        stack.enter_context(patch.object(trade, "_manual_two_city_ocr_entries", side_effect=ocr))
        stack.enter_context(patch.object(trade, "_manual_two_city_click", side_effect=lambda _context, target, _delay: clicks.append(target)))
        stack.enter_context(patch.object(trade, "_manual_two_city_click_ocr_text", return_value=(True, [])))
        stack.enter_context(patch.object(trade, "_append_user_log", logs))
        stack.enter_context(patch.object(trade, "_json_payload"))
        return logs, clicks

    def test_uses_available_books_once_per_leg(self) -> None:
        state = {"completed_rounds": 0, "active_leg_index": 1}
        book_entries = [
            {"text": "进货采买书", "center_x": 731, "center_y": 166},
            {"text": "2", "center_x": 664, "center_y": 191},
        ]

        def fake_ocr(_context, _name, expected, **_kwargs):
            if expected == trade.BUY_BOOK_MENU_TEXTS:
                return True, book_entries, ["进货采买书", "2"]
            if expected == trade.BUY_BOOK_POPUP_TEXTS:
                return True, [], ["是否使用", "确认"]
            if expected == trade.BUY_PAGE_READY_TEXTS:
                return True, [], ["全部买入"]
            return False, [], []

        with ExitStack() as stack:
            logs, clicks = self._patch_runtime(stack, state, fake_ocr)
            action = trade.ManualTwoCityBusinessUseBuyBooksAction()
            self.assertTrue(action.run(None, None))
            usage = trade._manual_two_city_buy_book_usage(state, self.leg)
            self.assertEqual(usage["requested"], 3)
            self.assertEqual(usage["used"], 2)
            self.assertEqual(usage["used_batches"], [2])
            first_click_count = len(clicks)
            self.assertTrue(action.run(None, None))
            self.assertEqual(len(clicks), first_click_count)
            self.assertIn(
                "manual_two_city_buy_books_retry_skipped",
                [call.kwargs.get("event") for call in logs.call_args_list],
            )

    def test_zero_books_allows_verified_partial_cargo(self) -> None:
        state = {"completed_rounds": 0, "active_leg_index": 1}
        zero_entries = [
            {"text": "进货采买书", "center_x": 731, "center_y": 166},
            {"text": "0", "center_x": 664, "center_y": 191},
        ]

        def fake_ocr(_context, _name, expected, **_kwargs):
            if expected == trade.BUY_BOOK_MENU_TEXTS:
                return True, zero_entries, ["进货采买书", "0"]
            if expected == trade.BUY_PAGE_READY_TEXTS:
                return True, [], ["全部买入"]
            return False, [], []

        with ExitStack() as stack:
            self._patch_runtime(stack, state, fake_ocr)
            probe = stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_probe_buy_page_cargo_load",
                    return_value=({"used": 1107, "capacity": 1300, "ratio": 1107 / 1300}, ["1107/1300"]),
                )
            )
            stack.enter_context(patch.object(trade, "_ocr_texts", return_value=["全部取消", "1107/1300"]))

            self.assertTrue(trade.ManualTwoCityBusinessUseBuyBooksAction().run(None, None))
            usage = trade._manual_two_city_buy_book_usage(state, self.leg)
            self.assertEqual((usage["requested"], usage["used"]), (3, 0))
            state["selected_buy_goods"] = list(self.goods)
            state["selected_buy_goods_actual_load"] = {good: 1 for good in self.goods}
            self.assertTrue(trade.ManualTwoCityBusinessConfirmBuySelectionAction().run(None, None))
            state["buy_selection_verified_cargo_load"] = {"used": 1107, "capacity": 1300, "ratio": 1107 / 1300}
            self.assertTrue(trade.ManualTwoCityBusinessVerifyCargoAfterBuyAction().run(None, None))
            self.assertGreaterEqual(probe.call_count, 2)


if __name__ == "__main__":
    unittest.main()

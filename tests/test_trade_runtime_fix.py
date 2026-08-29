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

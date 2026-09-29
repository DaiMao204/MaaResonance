from __future__ import annotations

import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.test_trade_runtime_fix import trade


class BookDialog:
    """A stock-limited book picker, including the missing menu digit in the log."""

    def __init__(self, owned: int, *, menu_readable: bool = True,
                 popup_readable: bool = True, increment_works: bool = True) -> None:
        self.owned = owned
        self.menu_readable = menu_readable
        self.popup_readable = popup_readable
        self.increment_works = increment_works
        self.overlay = ""
        self.selected = 1
        self.confirmed: list[int] = []
        self.use_clicks = 0
        self.increment_clicks = 0

    def ocr(self, _context, name, expected, **_kwargs):
        if self.overlay == "menu":
            entries = [{"text": "进货采买书", "center_x": 733, "center_y": 167}]
            if self.menu_readable:
                entries.append({"text": str(self.owned), "center_x": 664, "center_y": 191})
            return True, entries, [entry["text"] for entry in entries]
        if self.overlay == "popup":
            texts = ["是否使用进货采买书增加交易品库存？", "确认", "取消"]
            if self.popup_readable:
                texts += [f"拥有：{self.owned}", f"{self.selected}/{min(10, self.owned)}"]
            entries = [{"text": text, "center_x": 640, "center_y": 372} for text in texts]
            return True, entries, texts
        if expected == trade.BUY_PAGE_READY_TEXTS:
            return True, [], ["全部买入"]
        return False, [], []

    def click(self, _context, target, _delay):
        if target == trade.BUY_BOOK_INCREMENT_TARGET:
            self.increment_clicks += 1
            if self.increment_works:
                self.selected = min(self.selected + 1, self.owned, 10)
        elif target[0] == trade.BUY_BOOK_MENU_USE_BUTTON_X:
            self.use_clicks += 1
            if self.owned:
                self.overlay = "popup"
                self.selected = 1

    def click_text(self, _context, _name, expected, **_kwargs):
        if "使用道具" in expected:
            self.overlay = "menu"
        elif "确认" in expected:
            self.confirmed.append(self.selected)
            self.owned -= self.selected
            self.overlay = ""
        return True, expected

    def close(self, *_args, **_kwargs):
        self.overlay = ""
        return True, ["全部买入"]


class BookExhaustionRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.leg = {
            "buy_city": "海角城", "sell_city": "岚心城", "restock": 3,
            "goods": ["珍珠", "蕾丝连衣裙", "单晶硅", "大龙虾", "学会书籍"],
            "goods_detail": [
                {"name": name, "num": count}
                for name, count in zip(
                    ["珍珠", "蕾丝连衣裙", "单晶硅", "大龙虾", "学会书籍"],
                    [140, 148, 252, 420, 340],
                )
            ],
        }
        self.state = {"completed_rounds": 1, "active_leg_index": 1}

    def patch_books(self, stack: ExitStack, ui: BookDialog):
        stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=self.state))
        stack.enter_context(patch.object(trade, "_manual_two_city_active_leg", return_value=self.leg))
        stack.enter_context(patch.object(trade, "_manual_two_city_existing_cargo_limited_buy", return_value=False))
        stack.enter_context(patch.object(trade, "_manual_two_city_ocr_entries", side_effect=ui.ocr))
        stack.enter_context(patch.object(trade, "_manual_two_city_click", side_effect=ui.click))
        stack.enter_context(patch.object(trade, "_manual_two_city_click_ocr_text", side_effect=ui.click_text))
        stack.enter_context(patch.object(trade, "_manual_two_city_close_buy_book_menu", side_effect=ui.close))
        stack.enter_context(patch.object(trade, "_append_user_log"))
        stack.enter_context(patch.object(trade, "_json_payload"))
        stack.enter_context(patch.object(trade.time, "sleep"))

    def usage(self):
        return trade._manual_two_city_buy_book_usage(self.state, self.leg)

    def test_popup_counts_keep_owned_and_picker_limit_separate(self):
        self.assertEqual(
            trade._manual_two_city_book_popup_counts_from_texts(["拥有：1", "1/1", "+1", "-1"]),
            {"owned": 1, "selected": 1, "limit": 1},
        )
        self.assertEqual(
            trade._manual_two_city_book_popup_counts_from_texts(["拥有：243", "3/10"]),
            {"owned": 243, "selected": 3, "limit": 10},
        )
        self.assertEqual(
            trade._manual_two_city_book_popup_counts_from_texts(["拥有：243", "1/243"]),
            {"owned": 243, "selected": 1, "limit": 243},
        )
        self.assertEqual(
            trade._manual_two_city_book_popup_counts_from_texts(["确认", "+1", "取消"]),
            {"owned": None, "selected": None, "limit": None},
        )

    def test_last_book_missing_menu_digit_records_one_and_switches_to_all_buy(self):
        ui = BookDialog(1, menu_readable=False)
        with ExitStack() as stack:
            self.patch_books(stack, ui)
            self.assertTrue(trade.ManualTwoCityBusinessUseBuyBooksAction().run(None, None))
            self.assertEqual(ui.confirmed, [1])
            self.assertEqual(ui.increment_clicks, 0)
            self.assertEqual(self.usage()["used"], 1)
            self.assertEqual(self.usage()["used_batches"], [1])
            self.assertTrue(self.usage()["inventory_shortfall"])
            self.assertTrue(self.state["buy_selection_skip_restock_quick_buy"])

    def test_zero_books_does_not_click_disabled_use_button(self):
        ui = BookDialog(0)
        with ExitStack() as stack:
            self.patch_books(stack, ui)
            self.assertTrue(trade.ManualTwoCityBusinessUseBuyBooksAction().run(None, None))
            self.assertEqual(ui.use_clicks, 0)
            self.assertEqual(ui.confirmed, [])
            self.assertEqual(self.usage()["used"], 0)
            self.assertTrue(self.usage()["inventory_shortfall"])
            self.assertTrue(self.state["buy_selection_skip_restock_quick_buy"])

    def test_adequate_books_keep_normal_planned_selection(self):
        ui = BookDialog(8)
        with ExitStack() as stack:
            self.patch_books(stack, ui)
            self.assertTrue(trade.ManualTwoCityBusinessUseBuyBooksAction().run(None, None))
            self.assertEqual(ui.confirmed, [3])
            self.assertEqual(ui.increment_clicks, 2)
            self.assertEqual(self.usage()["used"], 3)
            self.assertFalse(trade._manual_two_city_buy_book_shortfall(self.state, self.leg))
            self.assertFalse(self.state.get("buy_selection_skip_restock_quick_buy"))

    def test_unknown_counts_are_not_consumed_or_classified_as_shortfall(self):
        ui = BookDialog(8, menu_readable=False, popup_readable=False)
        with ExitStack() as stack:
            self.patch_books(stack, ui)
            action = trade.ManualTwoCityBusinessUseBuyBooksAction()
            self.assertFalse(action.run(None, None))
            self.assertEqual(ui.confirmed, [])
            self.assertEqual(self.usage()["used"], 0)
            self.assertFalse(trade._manual_two_city_buy_book_shortfall(self.state, self.leg))
            self.assertFalse(self.state.get("buy_selection_skip_restock_quick_buy"))
            self.assertFalse(action.run(None, None))
            self.assertEqual(ui.confirmed, [])

    def test_unconfirmed_picker_increment_never_counts_requested_books(self):
        ui = BookDialog(8, increment_works=False)
        with ExitStack() as stack:
            self.patch_books(stack, ui)
            self.assertFalse(trade.ManualTwoCityBusinessUseBuyBooksAction().run(None, None))
            self.assertEqual(ui.confirmed, [])
            self.assertEqual(self.usage()["used"], 0)
            self.assertFalse(trade._manual_two_city_buy_book_shortfall(self.state, self.leg))

    def test_recovery_preserves_shortfall_without_consuming_again(self):
        ui = BookDialog(1, menu_readable=False)
        with ExitStack() as stack:
            self.patch_books(stack, ui)
            action = trade.ManualTwoCityBusinessUseBuyBooksAction()
            self.assertTrue(action.run(None, None))
            self.state.pop("buy_selection_skip_restock_quick_buy", None)
            self.assertTrue(action.run(None, None))
            self.assertEqual(ui.confirmed, [1])
            self.assertEqual(ui.use_clicks, 1)
            self.assertTrue(self.state["buy_selection_skip_restock_quick_buy"])

    def test_shortfall_does_not_leak_into_next_leg(self):
        ui = BookDialog(0)
        with ExitStack() as stack:
            self.patch_books(stack, ui)
            action = trade.ManualTwoCityBusinessUseBuyBooksAction()
            self.assertTrue(action.run(None, None))
            self.state["active_leg_index"] = 0
            self.state["completed_rounds"] = 2
            self.leg["buy_city"], self.leg["sell_city"] = "岚心城", "海角城"
            ui.owned = 8
            self.assertTrue(action.run(None, None))
            self.assertFalse(self.state.get("buy_selection_skip_restock_quick_buy"))
            self.assertFalse(trade._manual_two_city_buy_book_shortfall(self.state, self.leg))
            self.assertEqual(ui.confirmed, [3])

    def test_running_route_consumes_seven_books_as_three_three_one(self):
        ui = BookDialog(7, menu_readable=False)
        with ExitStack() as stack:
            self.patch_books(stack, ui)
            action = trade.ManualTwoCityBusinessUseBuyBooksAction()
            for leg_index in range(3):
                self.state["completed_rounds"] = leg_index // 2
                self.state["active_leg_index"] = leg_index % 2
                self.assertTrue(action.run(None, None))
                self.assertEqual(
                    bool(self.state.get("buy_selection_skip_restock_quick_buy")),
                    leg_index == 2,
                )
            self.assertEqual(ui.confirmed, [3, 3, 1])
            self.assertEqual(self.usage()["used"], 1)
            self.assertNotIn("error", self.usage())

    def test_shortfall_in_second_batch_records_only_available_books(self):
        self.leg["restock"] = 13
        ui = BookDialog(12, menu_readable=False)
        with ExitStack() as stack:
            self.patch_books(stack, ui)
            self.assertTrue(trade.ManualTwoCityBusinessUseBuyBooksAction().run(None, None))
            self.assertEqual(ui.confirmed, [10, 2])
            self.assertEqual(self.usage()["used"], 12)
            self.assertTrue(self.usage()["inventory_shortfall"])
            self.assertTrue(self.state["buy_selection_skip_restock_quick_buy"])

    def test_ten_book_picker_limit_is_not_total_inventory_shortfall(self):
        self.leg["restock"] = 13
        ui = BookDialog(30, menu_readable=False)
        with ExitStack() as stack:
            self.patch_books(stack, ui)
            self.assertTrue(trade.ManualTwoCityBusinessUseBuyBooksAction().run(None, None))
            self.assertEqual(ui.confirmed, [10, 3])
            self.assertEqual(self.usage()["used"], 13)
            self.assertFalse(trade._manual_two_city_buy_book_shortfall(self.state, self.leg))
            self.assertFalse(self.state.get("buy_selection_skip_restock_quick_buy"))

    def patch_quick_buy(self, stack: ExitStack, *, selected=False, succeeds=True, clear_works=True):
        ui = {"selected": selected, "operations": [], "selected_load": 759 if selected else 13}
        context = SimpleNamespace(tasker=SimpleNamespace(controller=Mock()))

        def ocr(_context, _name, expected, **_kwargs):
            text = "全部取消" if ui["selected"] else "全部买入"
            entry = {"text": text, "center_x": 1192, "center_y": 104}
            return text in expected, [entry], [text]

        def clear_click(_context, _target, _delay):
            ui["operations"].append("clear")
            if clear_works:
                ui["selected"] = False
                ui["selected_load"] = 13

        def buy_all(_context, _entries):
            self.assertFalse(ui["selected"], "A stale selection must be cleared before all-buy")
            ui["operations"].append("all_buy")
            if succeeds:
                ui["selected"] = True
                ui["selected_load"] = 1080
            return (1192, 104)

        def cargo(*_args, **_kwargs):
            used = ui["selected_load"]
            return {"used": used, "capacity": 1272, "ratio": used / 1272}, [f"{used}/1272"]

        stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=self.state))
        stack.enter_context(patch.object(trade, "_manual_two_city_active_leg", return_value=self.leg))
        stack.enter_context(patch.object(trade, "_manual_two_city_set_active_leg_by_visible_goods", return_value=self.leg))
        stack.enter_context(patch.object(trade, "_manual_two_city_configured_locked_goods", return_value=[]))
        stack.enter_context(patch.object(trade, "_manual_two_city_ocr_entries", side_effect=ocr))
        stack.enter_context(patch.object(trade, "_manual_two_city_click", side_effect=clear_click))
        stack.enter_context(patch.object(trade, "_manual_two_city_click_top_all_buy_target", side_effect=buy_all))
        stack.enter_context(patch.object(trade, "_manual_two_city_probe_buy_page_cargo_load", side_effect=cargo))
        plan = stack.enter_context(patch.object(trade, "_manual_two_city_quick_buy_selection_plan"))
        stack.enter_context(patch.object(trade, "_ocr_entries", return_value=[]))
        stack.enter_context(patch.object(trade, "_argv_param", return_value={"page_index": 1}))
        stack.enter_context(patch.object(trade, "_append_user_log"))
        stack.enter_context(patch.object(trade, "_json_payload"))
        stack.enter_context(patch.object(trade.time, "sleep"))
        return ui, context, plan

    def test_restart_without_books_buys_all_despite_old_1300_plan_and_1272_capacity(self):
        ui = BookDialog(0)
        with ExitStack() as stack:
            self.patch_books(stack, ui)
            self.assertTrue(trade.ManualTwoCityBusinessUseBuyBooksAction().run(None, None))
        with ExitStack() as stack:
            selection, context, plan = self.patch_quick_buy(stack)
            self.assertTrue(trade.ManualTwoCityBusinessQuickBuySelectionAction().run(context, None))
            plan.assert_not_called()
            self.assertEqual(selection["operations"], ["all_buy"])
            self.assertTrue(trade.ManualTwoCityBusinessConfirmBuySelectionAction().run(context, None))

    def test_stale_selection_is_cleared_before_all_buy(self):
        self.state["buy_selection_skip_restock_quick_buy"] = True
        with ExitStack() as stack:
            ui, context, plan = self.patch_quick_buy(stack, selected=True)
            self.assertTrue(trade.ManualTwoCityBusinessQuickBuySelectionAction().run(context, None))
            self.assertEqual(ui["operations"], ["clear", "all_buy"])
            plan.assert_not_called()

    def test_failed_all_buy_does_not_fall_back_to_old_per_item_plan(self):
        self.state["buy_selection_skip_restock_quick_buy"] = True
        with ExitStack() as stack:
            ui, context, plan = self.patch_quick_buy(stack, succeeds=False)
            self.assertFalse(trade.ManualTwoCityBusinessQuickBuySelectionAction().run(context, None))
            trade.ManualTwoCityBusinessSelectBuyGoodsAction().run(context, None)
            context.tasker.controller.post_click.assert_not_called()
            self.assertFalse(trade.ManualTwoCityBusinessConfirmBuySelectionAction().run(context, None))
            self.assertEqual(ui["operations"], ["all_buy"])
            plan.assert_not_called()

    def test_failed_clear_never_toggles_stale_cart_into_all_buy(self):
        self.state["buy_selection_skip_restock_quick_buy"] = True
        with ExitStack() as stack:
            ui, context, _plan = self.patch_quick_buy(stack, selected=True, clear_works=False)
            self.assertFalse(trade.ManualTwoCityBusinessQuickBuySelectionAction().run(context, None))
            self.assertNotIn("all_buy", ui["operations"])
            trade.ManualTwoCityBusinessSelectBuyGoodsAction().run(context, None)
            context.tasker.controller.post_click.assert_not_called()


if __name__ == "__main__":
    unittest.main()

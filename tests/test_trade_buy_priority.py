from __future__ import annotations

import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from tests.test_trade_runtime_fix import trade


class TradeBuyPriorityTest(unittest.TestCase):
    def setUp(self):
        self.goods = ["珍珠", "大龙虾"]
        self.leg = {
            "buy_city": "海角城",
            "goods": self.goods,
            "goods_detail": [{"name": good, "num": 50} for good in self.goods],
        }

    def test_quick_buy_requires_the_same_fill_order_and_capacity(self):
        with ExitStack() as stack:
            order = stack.enter_context(patch.object(trade, "_known_buy_goods_for_city", return_value=self.goods))
            stack.enter_context(patch.object(
                trade, "_manual_two_city_product_status_for_city",
                return_value={good: trade.PRODUCT_STATUS_NORMAL for good in self.goods},
            ))
            lots = stack.enter_context(patch.object(
                trade, "_manual_two_city_available_lots_for_leg", return_value=({"珍珠": 50, "大龙虾": 80}, {}),
            ))
            cargo = {"capacity": 100, "used": 0}
            self.assertTrue(trade._manual_two_city_quick_buy_selection_plan(self.leg, cargo)["ok"])
            order.return_value = list(reversed(self.goods))
            self.assertFalse(trade._manual_two_city_quick_buy_selection_plan(self.leg, cargo)["ok"])
            order.return_value = self.goods
            self.assertFalse(trade._manual_two_city_quick_buy_selection_plan(self.leg, {"capacity": 100, "used": 7})["ok"])
            self.assertFalse(trade._manual_two_city_quick_buy_selection_plan(self.leg, {"capacity": 104, "used": 0})["ok"])
            lots.return_value = ({"珍珠": 80, "大龙虾": 50}, {})
            self.assertFalse(trade._manual_two_city_quick_buy_selection_plan(self.leg, cargo)["ok"])
            lots.return_value = ({"珍珠": 50, "大龙虾": 80}, {})
            self.leg["purchase_candidates"] = [{"name": good} for good in self.goods]
            order.return_value = self.goods + ["学会书籍"]
            self.assertFalse(trade._manual_two_city_quick_buy_selection_plan(self.leg, cargo)["ok"])

    def test_high_margin_on_later_page_is_selected_before_returning_to_low_margin(self):
        state = {}
        context = Mock()
        selected = []
        def click(x, y):
            selected.append({220: "珍珠", 320: "大龙虾"}[y])
            return Mock()

        def cargo(*_args):
            return {"used": 50 * len(selected), "capacity": 100}, []

        context.tasker.controller.post_click.side_effect = click
        rows = {
            "珍珠": {"text": "珍珠", "center_x": 670, "center_y": 220},
            "大龙虾": {"text": "大龙虾", "center_x": 670, "center_y": 320},
        }
        with ExitStack() as stack:
            stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=state))
            stack.enter_context(patch.object(trade, "_manual_two_city_set_active_leg_by_visible_goods", return_value=self.leg))
            stack.enter_context(patch.object(trade, "_manual_two_city_active_leg", return_value=self.leg))
            stack.enter_context(patch.object(trade, "_manual_two_city_configured_locked_goods", return_value=[]))
            stack.enter_context(patch.object(trade, "_manual_two_city_probe_buy_page_cargo_load", side_effect=cargo))
            stack.enter_context(patch.object(trade, "_manual_two_city_product_locked_after_click", return_value=(False, [])))
            stack.enter_context(patch.object(trade, "_manual_two_city_update_product_status"))
            stack.enter_context(patch.object(trade, "_json_payload"))
            stack.enter_context(patch.object(trade, "_append_user_log"))
            stack.enter_context(patch.object(trade.time, "sleep"))
            swipe = stack.enter_context(patch.object(trade, "_manual_two_city_swipe"))
            params = stack.enter_context(patch.object(trade, "_argv_param"))
            ocr = stack.enter_context(patch.object(trade, "_ocr_entries"))
            select = trade.ManualTwoCityBusinessSelectBuyGoodsAction()
            resume = trade.ManualTwoCityBusinessResumeBuyPriorityScanAction()
            for page, visible in enumerate([["大龙虾"], [], [], ["珍珠"]], start=1):
                params.return_value = {"page_index": page}
                ocr.return_value = [rows[name] for name in visible]
                self.assertFalse(select.run(context, None))
                if page == 1:
                    self.assertFalse(resume.run(context, None))
                    self.assertEqual(selected, [])
            self.assertEqual(selected, ["珍珠"])
            self.assertTrue(resume.run(context, None))
            self.assertEqual(swipe.call_count, 3)
            params.return_value = {"page_index": 1}
            ocr.return_value = [rows["大龙虾"]]
            self.assertTrue(select.run(context, None))
            self.assertEqual(selected, self.goods)
            self.assertEqual(state["selected_buy_goods"], self.goods)

    def test_short_stock_and_existing_cargo_use_quoted_alternatives_and_verified_quantities(self):
        # The original four-book plan only needed pearls. The shop shows an
        # unprofitable good above both profitable goods, and fewer pearls exist.
        leg = {
            "buy_city": "海角城", "sell_city": "栖羽站", "restock": 4, "goods": ["珍珠"],
            "goods_detail": [{"name": "珍珠", "num": 100}],
            "purchase_candidates": [
                {"name": "珍珠", "base_lot": 30, "single_profit": 300},
                {"name": "大龙虾", "base_lot": 25, "single_profit": 200},
            ],
        }
        for source, used_books, skip_books in [("live", 1, True), ("cache", 0, True), ("live", 4, False)]:
            with self.subTest(source=source, used_books=used_books), ExitStack() as stack:
                state = {
                    "result": {"market": {"source": source}},
                    "buy_selection_skip_restock_quick_buy": skip_books, "buy_selection_had_cargo": True,
                }
                if used_books:
                    marker = trade._manual_two_city_leg_run_marker(state, leg)
                    state["buy_book_usage_by_leg"] = {marker: {
                        "used": used_books, "requested": 4, "attempted": True, "inventory_shortfall": used_books < 4,
                    }}
                else:
                    state["buy_selection_limited_by_existing_cargo"] = True
                order = ["学会书籍", "大龙虾", "珍珠"]
                rows = [{"text": good, "center_x": 615, "center_y": 150 + 100 * i} for i, good in enumerate(order)]
                selected = []
                cargo = {"used": 40, "capacity": 100}
                def click(x, y):
                    name = order[(y - 150) // 100]
                    selected.append(name)
                    cargo["used"] += {"珍珠": 8, "大龙虾": 11}[name]
                    return Mock()

                context = Mock()
                context.tasker.controller.post_click.side_effect = click
                stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=state))
                stack.enter_context(patch.object(trade, "_manual_two_city_active_leg", return_value=leg))
                stack.enter_context(patch.object(trade, "_manual_two_city_set_active_leg_by_visible_goods", return_value=leg))
                stack.enter_context(patch.object(trade, "_manual_two_city_configured_locked_goods", return_value=[]))
                stack.enter_context(patch.object(trade, "_manual_two_city_product_locked_after_click", return_value=(False, [])))
                stack.enter_context(patch.object(trade, "_manual_two_city_update_product_status"))
                stack.enter_context(patch.object(trade, "_manual_two_city_clear_top_all_buy_selection", return_value=(True, [])))
                stack.enter_context(patch.object(trade, "_manual_two_city_probe_buy_page_cargo_load", side_effect=lambda *_: (dict(cargo), [])))
                stack.enter_context(patch.object(trade, "_ocr_entries", return_value=rows))
                stack.enter_context(patch.object(trade, "_argv_param", return_value={"page_index": 1}))
                stack.enter_context(patch.object(trade, "_json_payload"))
                stack.enter_context(patch.object(trade, "_append_user_log"))
                stack.enter_context(patch.object(trade.time, "sleep"))
                bulk = stack.enter_context(patch.object(trade, "_manual_two_city_click_top_all_buy_target"))
                self.assertFalse(trade.ManualTwoCityBusinessQuickBuySelectionAction().run(context, None))
                self.assertTrue(trade.ManualTwoCityBusinessSelectBuyGoodsAction().run(context, None))
                self.assertEqual(selected, ["珍珠", "大龙虾"])
                self.assertEqual(state["selected_buy_goods"], selected)
                self.assertEqual(state["selected_buy_goods_actual_load"], {"珍珠": 8, "大龙虾": 11})
                adapted = state["buy_selection_market_stock"]
                self.assertEqual(adapted["lots"], {"珍珠": min(60, 30 * (1 + used_books)), "大龙虾": min(60, 25 * (1 + used_books))})
                self.assertEqual(adapted["expected_load"], 60 if used_books else 55)
                self.assertEqual(leg["goods"], ["珍珠"])
                self.assertTrue(trade.ManualTwoCityBusinessConfirmBuySelectionAction().run(context, None))
                self.assertTrue(trade.ManualTwoCityBusinessVerifyCargoAfterBuyAction().run(context, None))
                cargo["used"] = 40
                self.assertFalse(trade.ManualTwoCityBusinessVerifyCargoAfterBuyAction().run(context, None))
                bulk.assert_not_called()

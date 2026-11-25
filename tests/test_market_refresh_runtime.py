from __future__ import annotations

import unittest
from contextlib import ExitStack
from unittest.mock import patch

from tests.test_trade_runtime_fix import trade


class MarketRefreshRuntimeTest(unittest.TestCase):
    @staticmethod
    def plan(origin, destination, stamp=1200, source="live"):
        return {
            "mode": "auto", "start_city": origin, "target_city": destination,
            "start_book": 2, "target_book": 4,
            "start_bargain_percent": 20, "start_raise_percent": 20,
            "target_bargain_percent": 0, "target_raise_percent": 0,
            "market": {"source": source, "refresh_time": stamp, "interval": 600},
            "summary": {"legs": [
                {"buy_city": origin, "sell_city": destination, "goods": ["丝"]},
                {"buy_city": destination, "sell_city": origin, "goods": ["茶"]},
            ]},
        }

    def setUp(self):
        self.state = trade._manual_two_city_defaults()
        self.state.update(result=self.plan("甲", "乙"), auto_route_enabled=True, active_leg_index=0,
                          auto_route_params={"uid": "123", "priority_cities": ["甲"]}, current_city="甲")
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(trade, "_MANUAL_TWO_CITY_STATE", self.state))
        self.now = stack.enter_context(patch.object(trade.time, "time", return_value=1800))
        self.auto = stack.enter_context(patch.object(trade, "calculate_auto_two_city_trade"))
        self.manual = stack.enter_context(patch.object(trade, "calculate_manual_two_city_trade"))
        self.save = stack.enter_context(patch.object(trade, "save_manual_two_city_result"))
        stack.enter_context(patch.object(trade, "_append_user_log"))
        stack.enter_context(patch.object(trade, "_json_payload"))

    def test_expiry_boundary_and_stale_cache_retry(self):
        self.now.return_value = 1799
        self.assertTrue(trade._manual_two_city_refresh_market_before_buy(self.state, "甲"))
        self.auto.assert_not_called()
        self.now.return_value = 1800
        self.auto.return_value = self.plan("甲", "丙", source="cache")
        self.assertTrue(trade._manual_two_city_refresh_market_before_buy(self.state, "甲"))
        self.assertEqual(self.auto.call_args.kwargs["departure_city"], "甲")
        self.assertEqual(trade._manual_two_city_active_leg()["sell_city"], "丙")
        self.now.return_value = 1859
        self.assertTrue(trade._manual_two_city_refresh_market_before_buy(self.state, "甲"))
        self.auto.assert_called_once()
        self.now.return_value = 1860
        self.auto.return_value = self.plan("甲", "乙", stamp=1800)
        self.assertTrue(trade._manual_two_city_refresh_market_before_buy(self.state, "甲"))
        self.assertEqual(self.auto.call_count, 2)
        self.assertNotIn("market_retry_after", self.state)

    def test_return_refresh_and_goods_rescan_preserve_route_and_books(self):
        self.state.update(active_leg_index=1, current_city="乙")
        self.manual.return_value = self.plan("甲", "乙", stamp=1800)
        self.assertTrue(trade._manual_two_city_refresh_market_before_buy(self.state, "乙"))
        self.assertEqual(self.manual.call_args.kwargs["target_book"], 4)
        self.assertEqual(trade._manual_two_city_active_leg()["sell_city"], "甲")
        self.state.update(active_leg_index=0, current_city="甲")
        marker = trade._manual_two_city_leg_run_marker()
        self.state["buy_book_usage_by_leg"] = {marker: {"attempted": True, "used": 2}}
        self.assertTrue(trade._manual_two_city_recalculate_at_station("甲", reason="商品状态扫描"))
        self.assertEqual(self.manual.call_args.kwargs["start_book"], 2)
        self.assertEqual(trade._manual_two_city_buy_book_usage()["used"], 2)
        self.auto.assert_not_called()

    def test_continuous_round_starts_new_route_at_last_sale_city(self):
        self.state.update(active_leg_index=1, current_city="甲", run_mode="until_fatigue_exhausted")
        self.auto.return_value = self.plan("甲", "丙", stamp=1800)
        self.assertTrue(trade.ManualTwoCityBusinessAfterSellAction().run(None, None))
        self.assertEqual(self.auto.call_args.kwargs["departure_city"], "甲")
        self.assertEqual(self.auto.call_args.kwargs["priority_cities"], ["甲"])
        self.assertEqual(self.state["completed_rounds"], 1)
        self.assertEqual(self.state["active_leg_index"], 0)
        self.assertEqual(trade._manual_two_city_active_leg()["sell_city"], "丙")

    def test_invalid_route_stops_before_applying_or_retrying(self):
        previous = self.state["result"]
        self.auto.return_value = self.plan("乙", "丙", stamp=1800)
        self.assertFalse(trade._manual_two_city_refresh_market_before_buy(self.state, "甲"))
        self.assertIs(self.state["result"], previous)
        self.save.assert_not_called()
        self.assertEqual(self.state["terminal_status"], trade.MANUAL_TWO_CITY_TERMINAL_FAILED)
        self.assertFalse(trade._manual_two_city_refresh_market_before_buy(self.state, "甲"))
        self.auto.assert_called_once()

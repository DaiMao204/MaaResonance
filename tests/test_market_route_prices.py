from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from maa_resonance.logic import planner


class MarketRoutePricesTest(unittest.TestCase):
    options = planner.RoutePlanOptions(max_goods_num=1, max_restock=0, auto_haggle=False)

    @staticmethod
    def market_and_catalog(buy: dict, sell: dict):
        catalog = {
            "cities": list(buy),
            "products": [
                {"name": good, "buyPrices": {city: 9999}, "buyLot": {city: 1}}
                for city, goods in buy.items()
                for good in goods
            ],
        }
        market = planner.MarketData(
            buy_goods={city: {good: {"num": 1} for good in goods} for city, goods in buy.items()},
            buy_prices={city: {good: {"price": price} for good, price in goods.items()} for city, goods in buy.items()},
            sell_prices={city: {good: {"price": price} for good, price in goods.items()} for city, goods in sell.items()},
            tired={f"{start}-{end}": 1 for start in buy for end in buy if start != end},
        )
        return market, catalog

    def test_market_quotes_change_goods_profit_and_best_destination(self):
        origin = "起点"
        sell = {origin: {"乙货": 20, "丙货": 20}, "乙城": {"丝": 100, "茶": 62}, "丙城": {"丝": 50, "茶": 110}}
        for use_catalog in (True, False):
            for silk, tea, best_city, best_profit, good_at_b, profit_at_b in (
                (10, 30, "乙城", 100, "丝", 90),
                (80, 5, "丙城", 115, "茶", 57),
            ):
                with self.subTest(use_catalog=use_catalog, silk=silk, tea=tea):
                    buy = {origin: {"丝": silk, "茶": tea}, "乙城": {"乙货": 10}, "丙城": {"丙货": 10}}
                    market, catalog = self.market_and_catalog(buy, sell)
                    with patch.object(planner, "load_columba_trade_data", return_value=catalog if use_catalog else {}):
                        routes = planner.plan_two_city_routes(market, self.options)

                    self.assertEqual({leg.buy_city_name for leg in routes[0].city_data}, {origin, best_city})
                    self.assertEqual(routes[0].profit, best_profit)
                    leg_at_b = next(
                        leg for route in routes for leg in route.city_data
                        if leg.buy_city_name == origin and leg.sell_city_name == "乙城"
                    )
                    self.assertEqual(list(leg_at_b.goods_data), [good_at_b])
                    self.assertEqual(leg_at_b.profit, profit_at_b)
                    self.assertEqual(leg_at_b.goods_data[good_at_b].buy_price, buy[origin][good_at_b])

    def test_empty_post_tax_result_does_not_restart_with_gross_spreads(self):
        market, catalog = self.market_and_catalog(
            {"甲": {"丝": 100}, "乙": {"茶": 100}}, {"甲": {"茶": 110}, "乙": {"丝": 110}},
        )
        catalog["prestige_levels"] = [{"level": 20, "generalTax": 0.2}]
        with patch.object(planner, "load_columba_trade_data", return_value=catalog):
            self.assertEqual(planner.plan_two_city_routes(market, self.options), [])

    def test_missing_buy_quote_cannot_be_replaced_by_a_local_sell_quote(self):
        market, _ = self.market_and_catalog(
            {"甲": {"丝": 10}, "乙": {"茶": 10}},
            {"甲": {"丝": 10, "茶": 100}, "乙": {"丝": 100, "茶": 10}},
        )
        options = replace(self.options, use_columba_onegraph=False)
        self.assertEqual(planner.plan_two_city_routes(replace(market, buy_prices={}), options), [])
        # Old exports intentionally combine the two price sides. Only goods
        # actually sold by each station may be bought from a combined table.
        combined = replace(market, buy_prices=None)
        self.assertEqual(planner.plan_two_city_routes(combined, options)[0].profit, 180)
        combined = replace(combined, buy_goods={"甲": {"丝": {"num": 1}}, "乙": {}})
        self.assertEqual(planner.plan_two_city_routes(combined, options), [])

    def test_wulinyuan_uses_online_base_prices_and_requires_two_currency_gains(self):
        wulinyuan = planner.WULINYUAN_CITY_NAME
        sell = {"甲": {"茶": 1500}, wulinyuan: {"丝": 1000}}
        for use_catalog, expected_jiaozi in ((True, 37), (False, 45)):
            for tea_price in (100, 1200):
                with self.subTest(use_catalog=use_catalog, tea_price=tea_price):
                    buy = {"甲": {"丝": 100}, wulinyuan: {"茶": tea_price}}
                    market, catalog = self.market_and_catalog(buy, sell)
                    with patch.object(planner, "load_columba_trade_data", return_value=catalog if use_catalog else {}):
                        routes = planner.plan_two_city_routes(market, self.options)
                    if tea_price == 1200:
                        self.assertEqual(routes, [])
                    else:
                        self.assertEqual(routes[0].jiaozi_profit, expected_jiaozi)
                        self.assertEqual(routes[0].tiemeng_profit, 1400)

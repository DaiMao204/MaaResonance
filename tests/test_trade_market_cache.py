from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from maa_resonance.logic import manual_trade, planner


def quote_payload(stamp: int, silk_price: int = 40) -> dict:
    return {
        "refresh_time": stamp,
        "interval": 600,
        "server_trade": {
            "丝": {"buy": {"甲城": {"price": silk_price, "base_price": 1, "stock": 1}},
                  "sell": {"乙城": {"price": 100}}},
            "茶": {"buy": {"甲城": {"price": 40}}, "sell": {"乙城": {"price": 110}}},
            "盐": {"buy": {"乙城": {"price": 10}}, "sell": {"甲城": {"price": 80}}},
        },
    }


class TradeMarketCacheTest(unittest.TestCase):
    def setUp(self):
        self.cache = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(planner, "MARKET_CACHE_DIR", self.cache))
        self.get = self.enterContext(patch.object(planner.requests, "get"))

    def serve(self, payload):
        self.get.side_effect = None
        self.get.return_value = Mock()
        self.get.return_value.json.return_value = payload

    def test_planners_fetch_again_even_with_a_fresh_cache_and_reuse_last_good_quotes_offline(self):
        catalog = {
            "cities": ["甲城", "乙城"],
            "products": [
                {"name": name, "buyPrices": {city: 500}, "buyLot": {city: 4}}
                for name, city in (("丝", "甲城"), ("茶", "甲城"), ("盐", "乙城"))
            ],
        }
        self.enterContext(patch.object(planner, "load_columba_trade_data", return_value=catalog))
        self.enterContext(patch.object(
            manual_trade, "find_account_config", return_value=(Path("account.json"), {"planner": {"max_goods_num": 4}}),
        ))
        self.enterContext(patch.object(planner, "load_default_tired_data", return_value={"甲城-乙城": 20}))
        manual = dict(start_city="甲城", target_city="乙城", start_book=0, target_book=0, start_haggle_percent=0)
        self.serve(quote_payload(1000))
        first = manual_trade.calculate_manual_two_city_trade(**manual)
        self.assertEqual(first["summary"]["legs"][0]["goods"], ["茶"])
        self.assertEqual(first["summary"]["profit"], 560)

        self.serve(quote_payload(1600, silk_price=10))
        second = manual_trade.calculate_manual_two_city_trade(**manual)
        self.assertEqual(second["summary"]["legs"][0]["goods"], ["丝"])
        self.assertEqual(second["summary"]["profit"], 640)
        self.assertEqual(second["market"], {"source": "live", "refresh_time": 1600, "interval": 600})
        candidates = second["summary"]["legs"][0]["purchase_candidates"]
        self.assertEqual([(item["name"], item["base_lot"]) for item in candidates], [("丝", 4), ("茶", 4)])

        self.get.side_effect = requests.Timeout("offline")
        offline = manual_trade.calculate_manual_two_city_trade(**manual)
        self.assertEqual(offline["summary"], second["summary"])
        self.assertEqual(offline["market"]["source"], "cache")
        auto = manual_trade.calculate_auto_two_city_trade(max_restock=0, departure_city="乙城")
        self.assertEqual(auto["market"], offline["market"])
        self.assertEqual(auto["start_city"], "乙城")
        self.assertEqual(auto["summary"]["legs"][1]["goods"], ["丝"])
        # A fixed return leg may inherit more than Columba's default four books
        # from the previous automatic round-trip allocation.
        six_books = manual_trade.calculate_manual_two_city_trade(**{**manual, "target_book": 6})
        self.assertEqual(six_books["summary"]["legs"][1]["restock"], 6)
        self.assertEqual(self.get.call_count, 5)
        self.assertTrue(all(call.args == (planner.TRADE_MARKET_API_URL,) for call in self.get.call_args_list))

    def test_invalid_and_older_responses_do_not_replace_last_success(self):
        self.serve(quote_payload(1600))
        saved = planner.load_trade_market_data()
        path = planner.market_cache_path(planner.TRADE_MARKET_API_URL)
        valid_cache = path.read_bytes()
        for payload in ({"server_trade": {}}, {"code": 503}, quote_payload(1000), []):
            with self.subTest(payload=payload):
                self.serve(payload)
                fallback = planner.load_trade_market_data()
                self.assertTrue(fallback.from_cache)
                self.assertEqual(fallback.refresh_time, saved.refresh_time)
                self.assertEqual(path.read_bytes(), valid_cache)

    def test_first_offline_run_or_damaged_cache_fails_without_using_static_prices(self):
        self.get.side_effect = requests.ConnectionError("offline")
        path = planner.market_cache_path(planner.TRADE_MARKET_API_URL)
        for content in (None, b"\xff", json.dumps({"fetched_at": 22, "payload": {"server_trade": {}}}).encode()):
            if content is not None:
                path.write_bytes(content)
            with self.assertRaisesRegex(RuntimeError, "没有可用的行情缓存"):
                planner.load_trade_market_data()

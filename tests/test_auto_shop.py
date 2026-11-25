from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from maa_resonance.logic.auto_shop import (
    DEFAULT_CHAMBER_ITEMS,
    DEFAULT_FUMING_ITEMS,
    DEFAULT_HQ_GOLD_ITEMS,
    ShopBuyRule,
    classify_fuming_medal_slot,
    classify_hq_currency_patch,
    compute_next_refresh_time,
    compute_rule_remaining_quota,
    compute_shop_config_hash,
    compute_shop_next_run,
    format_shop_buy_rules,
    format_timestamp,
    load_auto_shop_state,
    normalize_shop_item_name,
    parse_compact_number,
    parse_exchange_cost_pair,
    parse_exchange_cost_pairs,
    parse_exchange_limit_badge,
    parse_hq_balances,
    parse_hq_limit_badge,
    parse_hq_shop_cards,
    parse_exchange_shop_rows,
    parse_shop_buy_rules,
    parse_shop_confirm_popup,
    plan_affordable_quantity,
    resolve_shop_buy_rules,
    save_auto_shop_state,
    shop_item_name_matches,
    should_run_shop,
    update_shop_schedule_state,
)

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _real_maa_resource():
    saved = {}
    maa_mod = sys.modules.get("maa")
    stashed = maa_mod is not None and not hasattr(maa_mod, "__path__")
    if stashed:
        for name in list(sys.modules):
            if name == "maa" or name.startswith("maa."):
                saved[name] = sys.modules.pop(name)
    try:
        try:
            resource_mod = importlib.import_module("maa.resource")
            yield resource_mod.Resource
        except ImportError:
            yield None
    finally:
        if stashed:
            for name in list(sys.modules):
                if name == "maa" or name.startswith("maa."):
                    sys.modules.pop(name, None)
            sys.modules.update(saved)


def _paint_bgr(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, bgr: tuple[int, int, int]) -> None:
    img[max(0, y1):min(720, y2), max(0, x1):min(1280, x2)] = bgr


class AutoShopLogicTest(unittest.TestCase):
    def test_rule_parsing_and_name_matching(self) -> None:
        rules = parse_shop_buy_rules(
            "拉普拉斯协议:周, 追加注资申请书:月, 进货采买书@铁盟币, 本源之弦:月@采购券, 自观测胶卷:日@桦石",
            default_currency="gold",
        )
        self.assertEqual(
            rules,
            [
                ShopBuyRule(raw="拉普拉斯协议:周", item_name="拉普拉斯协议", period="weekly", currency="gold"),
                ShopBuyRule(raw="追加注资申请书:月", item_name="追加注资申请书", period="monthly", currency="gold"),
                ShopBuyRule(raw="进货采买书@铁盟币", item_name="进货采买书", period=None, currency="gold"),
                ShopBuyRule(raw="本源之弦:月@采购券", item_name="本源之弦", period="monthly", currency="ticket"),
            ],
        )
        # Hard rejection of huashi
        self.assertFalse(any(r.currency == "huashi" for r in rules))

        self.assertEqual(normalize_shop_item_name("“一元二次”×1"), "一元二次")
        self.assertEqual(normalize_shop_item_name("星云物质（4钛）×1"), "星云物质(4钛)")
        self.assertTrue(shop_item_name_matches("殊武装改造特许×1", "特殊武装改造特许"))
        self.assertTrue(shop_item_name_matches("寺殊武装改造特许×1", "特殊武装改造特许"))
        self.assertTrue(shop_item_name_matches("般武装改造凭证×1", "一般武装改造凭证"))
        self.assertFalse(shop_item_name_matches("空白录像带", "自观测胶卷"))

        self.assertGreaterEqual(len(parse_shop_buy_rules(DEFAULT_HQ_GOLD_ITEMS)), 4)
        self.assertGreaterEqual(len(parse_shop_buy_rules(DEFAULT_FUMING_ITEMS)), 3)
        self.assertGreaterEqual(len(parse_shop_buy_rules(DEFAULT_CHAMBER_ITEMS)), 2)

    def test_checkbox_and_extra_rule_resolution(self) -> None:
        # 1. Checkbox picks sort by ascending key (01..N)
        picked = resolve_shop_buy_rules(
            {
                "hq_gold_pick_06": "提神棒棒糖:周",
                "hq_gold_pick_01": "拉普拉斯协议:周",
                "hq_gold_pick_04": "进货采买书:周",
                "hq_gold_ui_configured": True,
            },
            pick_prefix="hq_gold_pick_",
            extra_key="hq_gold_extra",
            legacy_key="hq_gold_items",
            ui_configured_key="hq_gold_ui_configured",
            default_items=DEFAULT_HQ_GOLD_ITEMS,
            default_currency="gold",
        )
        self.assertEqual(
            format_shop_buy_rules(picked, default_currency="gold"),
            "拉普拉斯协议:周, 进货采买书:周, 提神棒棒糖:周",
        )

        # 2. Extra rules: in-place override preserves checkbox priority; ^ pins to top; unchecked appends at end
        with_extra_inplace = resolve_shop_buy_rules(
            {
                "hq_gold_pick_01": "拉普拉斯协议:周",
                "hq_gold_pick_05": "仙人掌能量棒棒糖:周",
                "hq_gold_extra": "仙人掌能量棒棒糖:周*3, 神秘新品:日, 本源之弦:月@采购券*2",
                "hq_gold_ui_configured": True,
            },
            pick_prefix="hq_gold_pick_",
            extra_key="hq_gold_extra",
            legacy_key="hq_gold_items",
            ui_configured_key="hq_gold_ui_configured",
            default_items=DEFAULT_HQ_GOLD_ITEMS,
            default_currency="gold",
        )
        self.assertEqual(
            format_shop_buy_rules(with_extra_inplace, default_currency="gold"),
            "拉普拉斯协议:周, 仙人掌能量棒棒糖:周*3, 神秘新品:日, 本源之弦:月@采购券*2",
        )

        with_extra_pinned = resolve_shop_buy_rules(
            {
                "hq_gold_pick_01": "拉普拉斯协议:周",
                "hq_gold_pick_05": "仙人掌能量棒棒糖:周",
                "hq_gold_extra": "^仙人掌能量棒棒糖:周×2, ^星云物质(4钛):日x5, 神秘新品:日",
                "hq_gold_ui_configured": True,
            },
            pick_prefix="hq_gold_pick_",
            extra_key="hq_gold_extra",
            legacy_key="hq_gold_items",
            ui_configured_key="hq_gold_ui_configured",
            default_items=DEFAULT_HQ_GOLD_ITEMS,
            default_currency="gold",
        )
        self.assertEqual(
            format_shop_buy_rules(with_extra_pinned, default_currency="gold"),
            "仙人掌能量棒棒糖:周*2, 星云物质(4钛):日*5, 拉普拉斯协议:周, 神秘新品:日",
        )

        # Syntax variants for *N / ^ and strict huashi rejection + quota calculations
        parsed_variants = parse_shop_buy_rules(
            "提神棒棒糖:周*3, 本源之弦:月@采购券*2, 独奏之弦:月*4@采购券, 广告投放券×2:周, ^进货采买书:周, ^自观测胶卷:日@桦石*2",
            default_currency="gold",
        )
        self.assertEqual(len(parsed_variants), 5)
        self.assertEqual(
            format_shop_buy_rules(parsed_variants, default_currency="gold"),
            "提神棒棒糖:周*3, 本源之弦:月@采购券*2, 独奏之弦:月@采购券*4, 广告投放券:周*2, 进货采买书:周",
        )
        self.assertTrue(parsed_variants[-1].pin_top)
        self.assertEqual(
            compute_rule_remaining_quota(ShopBuyRule("t", "提神棒棒糖", "weekly", "gold", 3), remaining=8, limit_total=8),
            3,
        )
        self.assertEqual(
            compute_rule_remaining_quota(ShopBuyRule("t", "提神棒棒糖", "weekly", "gold", 3), remaining=7, limit_total=8),
            2,
        )
        self.assertEqual(
            compute_rule_remaining_quota(ShopBuyRule("t", "提神棒棒糖", "weekly", "gold", 3), remaining=5, limit_total=8),
            0,
        )
        self.assertEqual(
            compute_rule_remaining_quota(ShopBuyRule("t", "星云物质(4钛)", "daily", None, 2), remaining=5, limit_total=None),
            2,
        )
        self.assertEqual(
            compute_rule_remaining_quota(ShopBuyRule("t", "提神棒棒糖", "weekly", "gold", None), remaining=5, limit_total=8),
            5,
        )

        # 3. Unchecking all boxes with empty extra under ui_configured=True returns []
        unchecked_all = resolve_shop_buy_rules(
            {"hq_gold_extra": "", "hq_gold_ui_configured": True},
            pick_prefix="hq_gold_pick_",
            extra_key="hq_gold_extra",
            legacy_key="hq_gold_items",
            ui_configured_key="hq_gold_ui_configured",
            default_items=DEFAULT_HQ_GOLD_ITEMS,
            default_currency="gold",
        )
        self.assertEqual(unchecked_all, [])

        # 4. Bare params without UI override or legacy key fall back to defaults
        fallback = resolve_shop_buy_rules(
            {"hq_gold_extra": "   "},
            pick_prefix="hq_gold_pick_",
            extra_key="hq_gold_extra",
            legacy_key="hq_gold_items",
            ui_configured_key="hq_gold_ui_configured",
            default_items=DEFAULT_HQ_GOLD_ITEMS,
            default_currency="gold",
        )
        self.assertEqual(
            format_shop_buy_rules(fallback, default_currency="gold"),
            DEFAULT_HQ_GOLD_ITEMS,
        )

        # 5. Legacy string parameter compatibility (both non-empty and explicit empty)
        legacy = resolve_shop_buy_rules(
            {"hq_gold_items": "进货采买书:周, 广告投放券:周", "hq_gold_extra": ""},
            pick_prefix="hq_gold_pick_",
            extra_key="hq_gold_extra",
            legacy_key="hq_gold_items",
            ui_configured_key="hq_gold_ui_configured",
            default_items=DEFAULT_HQ_GOLD_ITEMS,
            default_currency="gold",
        )
        self.assertEqual(format_shop_buy_rules(legacy, default_currency="gold"), "进货采买书:周, 广告投放券:周")
        legacy_empty = resolve_shop_buy_rules(
            {"hq_gold_items": ""},
            pick_prefix="hq_gold_pick_",
            extra_key="hq_gold_extra",
            legacy_key="hq_gold_items",
            ui_configured_key="hq_gold_ui_configured",
            default_items=DEFAULT_HQ_GOLD_ITEMS,
            default_currency="gold",
        )
        self.assertEqual(legacy_empty, [])

    def test_compact_numbers_and_limit_badges(self) -> None:
        self.assertEqual(parse_compact_number("33595719"), 33595719)
        self.assertEqual(parse_compact_number("30.3k"), 30300)
        self.assertEqual(parse_compact_number("33.6m"), 33600000)
        self.assertEqual(parse_compact_number("150万"), 1500000)

        self.assertEqual(parse_exchange_cost_pair("30.3k/150"), (30300, 150))
        self.assertEqual(
            parse_exchange_cost_pairs("2.1k/300 30.3k/1.5k 33.6m/1m"),
            [(2100, 300), (30300, 1500), (33600000, 1000000)],
        )

        self.assertEqual(parse_hq_limit_badge("每日限购5/5"), ("daily", 5, 5))
        # Real OCR typo observed in MuMu scan: '每固限购0/3'
        self.assertEqual(parse_hq_limit_badge("每固限购0/3"), ("weekly", 0, 3))
        self.assertEqual(parse_hq_limit_badge("每月限购4/4"), ("monthly", 4, 4))

        self.assertEqual(parse_exchange_limit_badge("当日剩余6次"), ("daily", 6))
        self.assertEqual(parse_exchange_limit_badge("本周剩余5次"), ("weekly", 5))
        self.assertEqual(parse_exchange_limit_badge("本月剩余10次"), ("monthly", 10))
        self.assertEqual(parse_exchange_limit_badge("剩余18次"), ("account", 18))
        self.assertEqual(parse_exchange_limit_badge("已兑换完"), ("soldout", 0))

    def test_pixel_currency_and_medal_classifiers(self) -> None:
        img = np.full((720, 1280, 3), 30, dtype=np.uint8)
        # Gold coin patch (BGR: low B, mid G, high R)
        _paint_bgr(img, 803, 256, 825, 278, (50, 180, 230))
        # Purple ticket patch (BGR: high B, low G, mid R)
        _paint_bgr(img, 845, 520, 868, 542, (210, 90, 150))
        # White/grey huashi patch
        _paint_bgr(img, 849, 344, 871, 366, (215, 215, 215))

        self.assertEqual(classify_hq_currency_patch(img, 800, 254, 845, 282), "gold")
        self.assertEqual(classify_hq_currency_patch(img, 842, 518, 888, 546), "ticket")
        self.assertEqual(classify_hq_currency_patch(img, 846, 342, 892, 370), "huashi_or_unknown")

        # Fuming medals: purple (blue ribbon + purple glow) vs gold (orange ribbon + yellow glow)
        cost_purple = (816, 503, 77, 18)
        _paint_bgr(img, 825, 430, 865, 450, (220, 120, 70))  # blue ribbon (BGR)
        _paint_bgr(img, 825, 478, 865, 496, (190, 80, 140))  # purple glow (BGR)
        self.assertEqual(classify_fuming_medal_slot(img, cost_purple), "purple_medal")

        cost_gold = (825, 208, 61, 19)
        _paint_bgr(img, 835, 136, 875, 154, (45, 140, 235))  # orange ribbon (BGR)
        _paint_bgr(img, 835, 184, 875, 202, (50, 175, 225))  # yellow glow (BGR)
        self.assertEqual(classify_fuming_medal_slot(img, cost_gold), "gold_medal")

    def test_hq_cards_exchange_rows_and_confirm_popup_parsers(self) -> None:
        img = np.full((720, 1280, 3), 28, dtype=np.uint8)
        # Left card: 进货采买书 (gold 15000)
        _paint_bgr(img, 808, 260, 830, 282, (45, 175, 230))
        # Right card: 进货采买书 (huashi 10)
        _paint_bgr(img, 1142, 260, 1164, 282, (220, 220, 220))
        # Left bottom: 战斗记忆体 (8钛) (ticket 2)
        _paint_bgr(img, 845, 555, 867, 577, (210, 90, 155))
        # Right bottom: 拉普拉斯协议 (sold out)
        _paint_bgr(img, 1145, 555, 1167, 577, (45, 175, 230))

        bal = parse_hq_balances(
            [
                {"text": "772", "box": [902, 106, 42, 24]},
                {"text": "33595719", "box": [1047, 106, 96, 21]},
            ]
        )
        self.assertEqual(bal, {"ticket": 772, "gold": 33595719})

        hq_entries = [
            {"text": "40%", "box": [674, 193, 54, 26]},
            {"text": "每周限购5/5", "box": [817, 204, 73, 14]},
            {"text": "进货采买书", "box": [808, 225, 92, 21]},
            {"text": "15000", "box": [835, 264, 66, 17]},
            {"text": "每日限购10/10", "box": [1139, 204, 90, 13]},
            {"text": "进货采买书", "box": [1145, 225, 92, 21]},
            {"text": "10", "box": [1175, 264, 21, 18]},
            {"text": "战斗记忆体", "box": [745, 512, 94, 18]},
            {"text": "（8钛）", "box": [831, 512, 56, 18]},
            {"text": "2", "box": [875, 558, 18, 16]},
            {"text": "每周限购0/3", "box": [1148, 490, 72, 14]},
            {"text": "已售馨", "box": [1062, 535, 48, 19]},
            {"text": "拉普拉斯协议", "box": [1126, 512, 111, 21]},
            {"text": "300000", "box": [1177, 558, 61, 18]},
        ]
        cards = parse_hq_shop_cards(hq_entries, img)
        self.assertEqual(len(cards), 4)
        self.assertEqual(cards[0]["name"], "进货采买书")
        self.assertEqual(cards[0]["period"], "weekly")
        self.assertEqual(cards[0]["currency"], "gold")
        self.assertEqual(cards[0]["unit_cost"], 15000)
        self.assertFalse(cards[0]["sold_out"])

        self.assertEqual(cards[1]["name"], "进货采买书")
        self.assertEqual(cards[1]["period"], "daily")
        self.assertEqual(cards[1]["currency"], "huashi_or_unknown")

        self.assertEqual(cards[2]["name"], "战斗记忆体(8钛)")
        self.assertEqual(cards[2]["currency"], "ticket")

        self.assertTrue(cards[3]["sold_out"])

        # Exchange shop rows: distinguish weekly vs account & gold vs purple medal
        _paint_bgr(img, 825, 170, 865, 192, (220, 120, 70))
        _paint_bgr(img, 825, 218, 865, 236, (190, 80, 140))
        _paint_bgr(img, 825, 430, 865, 452, (45, 140, 235))
        _paint_bgr(img, 825, 478, 865, 496, (50, 175, 225))
        exch_entries = [
            {"text": "进货采买书×1", "box": [656, 240, 110, 19]},
            {"text": "30.3k/150", "box": [816, 240, 77, 18]},
            {"text": "EXCHANGE", "box": [1134, 188, 85, 18]},
            {"text": "本周剩余5次", "box": [1142, 240, 95, 20]},
            {"text": "再交涉请求书×1", "box": [649, 500, 124, 20]},
            {"text": "2.1k/10", "box": [824, 500, 63, 20]},
            {"text": "EXCHANGE", "box": [1134, 448, 85, 18]},
            {"text": "本周剩余5次", "box": [1142, 500, 95, 20]},
            {"text": "自观测胶卷×1", "box": [659, 630, 108, 20]},
            {"text": "13.0k/200", "box": [816, 630, 79, 20]},
            {"text": "剩余18次", "box": [1153, 630, 72, 21]},
        ]
        rows = parse_exchange_shop_rows(exch_entries, img, classify_medal=True)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["period"], "weekly")
        self.assertEqual(rows[0]["costs"][0]["medal"], "purple_medal")
        self.assertEqual(rows[1]["costs"][0]["medal"], "gold_medal")
        self.assertEqual(rows[2]["period"], "account")

        # Confirm popup parsing (HQ & Exchange)
        _paint_bgr(img, 610, 434, 636, 466, (45, 175, 230))
        hq_pop = parse_shop_confirm_popup(
            [
                {"text": "诱饵气球", "box": [596, 302, 87, 28]},
                {"text": "最少", "box": [365, 365, 42, 24]},
                {"text": "-1", "box": [432, 365, 28, 22]},
                {"text": "1/30", "box": [611, 351, 58, 25]},
                {"text": "+1", "box": [812, 366, 28, 20]},
                {"text": "最多", "box": [871, 364, 43, 27]},
                {"text": "5000", "box": [656, 439, 55, 26]},
                {"text": "取消", "box": [323, 519, 52, 31]},
                {"text": "确定", "box": [957, 519, 52, 30]},
            ],
            img,
            shop_kind="hq",
        )
        self.assertIsNotNone(hq_pop)
        self.assertEqual(hq_pop["item_name"], "诱饵气球")
        self.assertEqual(hq_pop["cur_qty"], 1)
        self.assertEqual(hq_pop["max_qty"], 30)
        self.assertEqual(hq_pop["price"], 5000)
        self.assertEqual(hq_pop["currency"], "gold")

        ex_pop = parse_shop_confirm_popup(
            [
                {"text": "1/5", "box": [615, 345, 50, 24]},
                {"text": "确认消耗以上素材兑换进货采买书×1吗？", "box": [450, 430, 380, 26]},
                {"text": "取消", "box": [323, 519, 52, 31]},
                {"text": "确定", "box": [957, 519, 52, 30]},
            ],
            img,
            shop_kind="fuming",
        )
        self.assertIsNotNone(ex_pop)
        self.assertEqual(ex_pop["item_name"], "进货采买书")
        self.assertEqual(ex_pop["cur_qty"], 1)
        self.assertEqual(ex_pop["max_qty"], 5)

        self.assertEqual(plan_affordable_quantity(3500000, 3000000, 150000, 5), 3)
        self.assertEqual(plan_affordable_quantity(3000000, 3000000, 10000, 5), 0)

    def test_hq_noise_filtering_dimmed_sold_out_and_exchange_single_char_filter(self) -> None:
        img = np.full((720, 1280, 3), 28, dtype=np.uint8)
        # Bright huashi patch (white/grey) stays huashi_or_unknown even with dimmed=True
        _paint_bgr(img, 845, 255, 875, 280, (220, 220, 220))
        self.assertEqual(classify_hq_currency_patch(img, 835, 250, 885, 285, dimmed=False), "huashi_or_unknown")
        self.assertEqual(classify_hq_currency_patch(img, 835, 250, 885, 285, dimmed=True), "huashi_or_unknown")

        # Bright huashi icon next to 空白录像带 (glued price '国20000')
        _paint_bgr(img, 808, 357, 832, 381, (220, 220, 220))
        # Dimmed sold-out gold icon at (x=841, y=608 -> patch [809..863])
        _paint_bgr(img, 815, 604, 839, 628, (32, 95, 130))
        # Dimmed sold-out ticket icon at (x=1214, y=605 -> patch [1182..1236])
        _paint_bgr(img, 1188, 601, 1212, 625, (120, 48, 86))

        self.assertEqual(classify_hq_currency_patch(img, 809, 604, 863, 632, dimmed=False), "huashi_or_unknown")
        self.assertEqual(classify_hq_currency_patch(img, 809, 604, 863, 632, dimmed=True), "gold")
        self.assertEqual(classify_hq_currency_patch(img, 1182, 601, 1236, 629, dimmed=False), "huashi_or_unknown")
        self.assertEqual(classify_hq_currency_patch(img, 1182, 601, 1236, 629, dimmed=True), "ticket")

        common_entries = [
            {"text": "星云物质", "box": [1095, 192, 60, 21]},
            {"text": "（4钛）", "box": [1160, 192, 55, 21]},
            {"text": "每日限购35/35", "box": [1140, 170, 87, 14]},
            {"text": "每日限购10/10", "box": [803, 302, 87, 13]},
            {"text": "空白录像带", "box": [808, 322, 91, 21]},
            {"text": "国20000", "box": [834, 361, 67, 18]},
            {"text": "已售馨", "box": [724, 592, 48, 22]},
            {"text": "每周限购0/3", "box": [818, 548, 71, 14]},
            {"text": "拉普拉斯协议", "box": [789, 569, 111, 20]},
            {"text": "300000", "box": [841, 608, 60, 17]},
            {"text": "已售馨", "box": [1060, 592, 51, 23]},
            {"text": "每月限购0/10", "box": [1148, 548, 79, 14]},
            {"text": "拉普拉斯协议", "box": [1126, 569, 111, 20]},
            {"text": "20", "box": [1214, 605, 25, 21]},
        ]
        frame_a_noise = [
            {"text": "档", "box": [853, 205, 38, 34]},
            {"text": "市）", "box": [968, 423, 76, 72]},
            {"text": "宝", "box": [1166, 480, 14, 12]},
        ]
        frame_b_noise = [
            {"text": "堂", "box": [853, 205, 38, 34]},
            {"text": "国", "box": [966, 551, 80, 81]},
            {"text": "档", "box": [1182, 597, 37, 35]},
        ]

        cards_a = parse_hq_shop_cards(common_entries + frame_a_noise, img)
        cards_b = parse_hq_shop_cards(common_entries + frame_b_noise, img)
        sig_a = tuple((c["name"], c["period"]) for c in cards_a)
        sig_b = tuple((c["name"], c["period"]) for c in cards_b)
        self.assertEqual(sig_a, sig_b)
        self.assertEqual(
            sig_a,
            (
                ("星云物质(4钛)", "daily"),
                ("空白录像带", "daily"),
                ("拉普拉斯协议", "weekly"),
                ("拉普拉斯协议", "monthly"),
            ),
        )
        tape_card = next(c for c in cards_a if c["name"] == "空白录像带")
        self.assertEqual(tape_card["unit_cost"], 20000)
        self.assertEqual(tape_card["currency"], "huashi_or_unknown")
        lap_weekly = next(c for c in cards_a if c["name"] == "拉普拉斯协议" and c["period"] == "weekly")
        self.assertTrue(lap_weekly["sold_out"])
        self.assertEqual(lap_weekly["currency"], "gold")
        lap_monthly_tkt = next(c for c in cards_a if c["name"] == "拉普拉斯协议" and c["period"] == "monthly")
        self.assertTrue(lap_monthly_tkt["sold_out"])
        self.assertEqual(lap_monthly_tkt["currency"], "ticket")

        ex_rows = parse_exchange_shop_rows(
            [
                {"text": "档", "box": [660, 205, 24, 24]},
                {"text": "进货采买书×1", "box": [656, 240, 110, 19]},
                {"text": "30.3k/150", "box": [816, 240, 77, 18]},
                {"text": "本周剩余5次", "box": [1142, 240, 95, 20]},
                {"text": "堂", "box": [660, 320, 24, 24]},
            ],
            img,
            classify_medal=False,
        )
        self.assertEqual([(r["name"], r["period"]) for r in ex_rows], [("进货采买书", "weekly")])

    def test_alas_style_schedule_boundaries_and_persistence(self) -> None:
        # Saturday 2026-11-21 11:30 -> daily is tomorrow 05:00, weekly is Mon 11-23 05:00, monthly is 12-01 05:00
        now_sat = datetime(2026, 11, 21, 11, 30, 0)
        self.assertEqual(compute_next_refresh_time(now_sat, "daily"), datetime(2026, 11, 22, 5, 0, 0))
        self.assertEqual(compute_next_refresh_time(now_sat, "weekly"), datetime(2026, 11, 23, 5, 0, 0))
        self.assertEqual(compute_next_refresh_time(now_sat, "monthly"), datetime(2026, 12, 1, 5, 0, 0))

        # Before 05:00 on Monday -> same day 05:00
        now_mon_early = datetime(2026, 11, 23, 4, 15, 0)
        self.assertEqual(compute_next_refresh_time(now_mon_early, "daily"), datetime(2026, 11, 23, 5, 0, 0))
        self.assertEqual(compute_next_refresh_time(now_mon_early, "weekly"), datetime(2026, 11, 23, 5, 0, 0))

        # Year rollover monthly check
        now_dec = datetime(2026, 12, 15, 10, 0, 0)
        self.assertEqual(compute_next_refresh_time(now_dec, "monthly"), datetime(2027, 1, 1, 5, 0, 0))

        # Budget shortage forces daily retry at next 05:00
        self.assertEqual(
            compute_shop_next_run(now_sat, {"weekly", "monthly"}, partial_due_to_budget=True),
            datetime(2026, 11, 22, 5, 0, 0),
        )

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "auto_shop_state.json"
            state = load_auto_shop_state(state_path)
            cfg_hash = compute_shop_config_hash({"items": "进货采买书:周", "reserve": 3000000})
            due, reason = should_run_shop(state, "8820083699", "black_moon_hq", cfg_hash, now_sat)
            self.assertTrue(due)
            self.assertEqual(reason, "first_run")

            next_dt = compute_shop_next_run(now_sat, {"weekly"})
            update_shop_schedule_state(state, "8820083699", "black_moon_hq", cfg_hash, now_sat, next_dt, summary="ok")
            save_auto_shop_state(state_path, state)

            reloaded = load_auto_shop_state(state_path)
            due_later, reason_later = should_run_shop(
                reloaded, "8820083699", "black_moon_hq", cfg_hash, datetime(2026, 11, 22, 12, 0, 0)
            )
            self.assertFalse(due_later)
            self.assertEqual(reason_later, format_timestamp(next_dt))

            # Changing config invalidates cache immediately
            new_hash = compute_shop_config_hash({"items": "进货采买书:周, 提神棒棒糖:周", "reserve": 3000000})
            due_cfg, reason_cfg = should_run_shop(reloaded, "8820083699", "black_moon_hq", new_hash, now_sat)
            self.assertTrue(due_cfg)
            self.assertEqual(reason_cfg, "config_changed")

            # Force run bypasses timestamp cache
            due_force, reason_force = should_run_shop(
                reloaded, "8820083699", "black_moon_hq", cfg_hash, now_sat, force_run=True
            )
            self.assertTrue(due_force)
            self.assertEqual(reason_force, "force")

    def test_action_skips_when_not_due_and_aborts_on_huashi_or_escalating_reserve(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.auto_shop_action as asa

            img = np.full((720, 1280, 3), 28, dtype=np.uint8)
            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False), get_node_data=lambda _n: None)
            argv = SimpleNamespace(
                node_name="AutoShopStart",
                custom_action_param={
                    "schedule_mode": "smart",
                    "hq_enabled": True,
                    "hq_gold_items": "进货采买书:周",
                    "hq_gold_reserve": 3000000,
                    "hq_ticket_enabled": False,
                    "fuming_enabled": False,
                    "chamber_enabled": False,
                },
            )
            action = asa.AutoShopRunAction()

            # Case A: not due yet -> closes drawer without entering mall
            with tempfile.TemporaryDirectory() as tmp:
                state_path = Path(tmp) / "state.json"
                now_cfg_hash = compute_shop_config_hash(
                    {
                        "gold_items": "进货采买书:周",
                        "gold_reserve": 3000000,
                        "ticket_enabled": False,
                        "ticket_items": "",
                        "ticket_reserve": 0,
                    }
                )
                future_dt = datetime.now().replace(year=datetime.now().year + 1)
                state = {"version": 1, "accounts": {}}
                update_shop_schedule_state(
                    state, "8820083699", "black_moon_hq", now_cfg_hash, datetime.now(), future_dt, summary="done"
                )
                save_auto_shop_state(state_path, state)

                with (
                    patch.object(asa, "DEFAULT_AUTO_SHOP_STATE_PATH", state_path),
                    patch.object(asa, "open_drawer", return_value=(img, [])),
                    patch.object(asa, "read_drawer_uid", return_value="8820083699"),
                    patch.object(asa, "enter_mall_from_open_drawer") as mock_mall,
                    patch.object(asa, "tap_point", return_value=True) as mock_tap,
                    patch.object(asa, "sleep_with_stop", return_value=True),
                ):
                    res = action.run(ctx, argv)

                self.assertTrue(getattr(res, "success", True))
                mock_mall.assert_not_called()
                mock_tap.assert_called_once()

            # Case B: HQ popup safety abort if currency classifies as huashi, then escalating price step-down
            gold_card = {
                "name": "拉普拉斯协议",
                "period": "weekly",
                "remaining": 3,
                "limit_total": 3,
                "sold_out": False,
                "unit_cost": 300000,
                "currency": "gold",
                "tap_point": (1110, 520),
            }
            # Popup 1 claims huashi_or_unknown -> MUST cancel!
            huashi_pop = {
                "item_name": "拉普拉斯协议",
                "cur_qty": 1,
                "max_qty": 3,
                "price": 300000,
                "currency": "huashi_or_unknown",
                "min_pt": (386, 377),
                "dec_pt": (447, 377),
                "inc_pt": (826, 377),
                "max_pt": (892, 377),
                "cancel_pt": (349, 534),
                "confirm_pt": (983, 534),
            }
            tapped_names: list[str] = []

            def fake_tap(_ctx, name: str, _pt) -> bool:
                tapped_names.append(name)
                return True

            with tempfile.TemporaryDirectory() as tmp:
                state_path = Path(tmp) / "state2.json"
                with (
                    patch.object(asa, "DEFAULT_AUTO_SHOP_STATE_PATH", state_path),
                    patch.object(asa, "open_drawer", return_value=(img, [{"text": "商城", "box": [240, 530, 60, 30]}])),
                    patch.object(asa, "read_drawer_uid", return_value="8820083699"),
                    patch.object(asa, "enter_mall_from_open_drawer", return_value=True),
                    patch.object(asa, "select_mall_tab", return_value=(True, img, {"text": "总部商店"})),
                    patch.object(asa, "poll_screen", side_effect=[
                        (img, ({"gold": 3800000, "ticket": 772}, [gold_card]), False),
                        (img, huashi_pop, False),
                    ]),
                    patch.object(asa, "safe_screencap", return_value=img),
                    patch.object(asa, "ocr_roi", return_value=[]),
                    patch.object(asa, "parse_hq_balances", return_value={"gold": 3800000, "ticket": 772}),
                    patch.object(asa, "parse_hq_shop_cards", return_value=[gold_card]),
                    patch.object(asa, "tap_point", side_effect=fake_tap),
                    patch.object(asa, "swipe_points", return_value=True),
                    patch.object(asa, "sleep_with_stop", return_value=True),
                    patch.object(asa, "return_to_lobby", return_value=True),
                ):
                    argv_esc = SimpleNamespace(
                        node_name="AutoShopStart",
                        custom_action_param={
                            "schedule_mode": "force",
                            "hq_enabled": True,
                            "hq_gold_items": "拉普拉斯协议:周",
                            "hq_gold_reserve": 3000000,
                            "hq_ticket_enabled": False,
                            "fuming_enabled": False,
                            "chamber_enabled": False,
                        },
                    )
                    res2 = action.run(ctx, argv_esc)

                self.assertTrue(getattr(res2, "success", True))
                self.assertTrue(any("CancelCurrency" in n for n in tapped_names))
                self.assertFalse(any("Confirm" in n for n in tapped_names))

            # Case C: Escalating price after selecting target_qty=2 (3800000 - 1100000 < 3000000) steps down to qty=1 (3800000 - 300000 >= 3000000)
            valid_pop_1 = dict(huashi_pop, currency="gold", cur_qty=1, max_qty=3, price=300000)
            valid_pop_2_escalated = dict(huashi_pop, currency="gold", cur_qty=2, max_qty=3, price=1100000)
            valid_pop_stepped_1 = dict(huashi_pop, currency="gold", cur_qty=1, max_qty=3, price=300000)
            tapped_esc: list[str] = []

            def fake_tap_esc(_ctx, name: str, _pt) -> bool:
                tapped_esc.append(name)
                return True

            with tempfile.TemporaryDirectory() as tmp:
                state_path = Path(tmp) / "state3.json"
                with (
                    patch.object(asa, "DEFAULT_AUTO_SHOP_STATE_PATH", state_path),
                    patch.object(asa, "open_drawer", return_value=(img, [{"text": "商城", "box": [240, 530, 60, 30]}])),
                    patch.object(asa, "read_drawer_uid", return_value="8820083699"),
                    patch.object(asa, "enter_mall_from_open_drawer", return_value=True),
                    patch.object(asa, "select_mall_tab", return_value=(True, img, {"text": "总部商店"})),
                    patch.object(asa, "poll_screen", side_effect=[
                        (img, ({"gold": 3800000, "ticket": 772}, [gold_card]), False),
                        (img, valid_pop_1, False),
                    ]),
                    patch.object(asa, "safe_screencap", return_value=img),
                    patch.object(asa, "ocr_roi", return_value=[]),
                    patch.object(asa, "parse_hq_balances", return_value={"gold": 3800000, "ticket": 772}),
                    patch.object(asa, "parse_hq_shop_cards", return_value=[gold_card]),
                    patch.object(asa, "parse_shop_confirm_popup", side_effect=[valid_pop_2_escalated, valid_pop_stepped_1]),
                    patch.object(asa, "tap_point", side_effect=fake_tap_esc),
                    patch.object(asa, "swipe_points", return_value=True),
                    patch.object(asa, "sleep_with_stop", return_value=True),
                    patch.object(asa, "dismiss_reward_popup_if_present", return_value=True),
                    patch.object(asa, "return_to_lobby", return_value=True),
                ):
                    argv_esc2 = SimpleNamespace(
                        node_name="AutoShopStart",
                        custom_action_param={
                            "schedule_mode": "force",
                            "hq_enabled": True,
                            "hq_gold_items": "拉普拉斯协议:周",
                            "hq_gold_reserve": 3000000,
                            "hq_ticket_enabled": False,
                            "fuming_enabled": False,
                            "chamber_enabled": False,
                        },
                    )
                    res3 = action.run(ctx, argv_esc2)

                self.assertTrue(getattr(res3, "success", True))
                self.assertTrue(any("EscDec" in n for n in tapped_esc))
                self.assertTrue(any("ConfirmR0" in n for n in tapped_esc))
                saved_state = load_auto_shop_state(state_path)
                self.assertIn("black_moon_hq", saved_state["accounts"]["8820083699"])

    def test_action_bidirectional_scan_and_sold_out_skip(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.auto_shop_action as asa

            img = np.full((720, 1280, 3), 28, dtype=np.uint8)
            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False))

            page0_cards = [
                {
                    "name": "进货采买书",
                    "period": "weekly",
                    "remaining": 5,
                    "limit_total": 5,
                    "sold_out": False,
                    "unit_cost": 15000,
                    "currency": "gold",
                    "tap_point": (780, 278),
                    "col": 0,
                    "cy": 278,
                }
            ]
            page1_cards = [
                {
                    "name": "拉普拉斯协议",
                    "period": "weekly",
                    "remaining": 0,
                    "limit_total": 3,
                    "sold_out": True,
                    "unit_cost": 300000,
                    "currency": "gold",
                    "tap_point": (780, 569),
                    "col": 0,
                    "cy": 569,
                },
                {
                    "name": "拉普拉斯协议",
                    "period": "monthly",
                    "remaining": 0,
                    "limit_total": 10,
                    "sold_out": True,
                    "unit_cost": 1500000,
                    "currency": "gold",
                    "tap_point": (1110, 436),
                    "col": 1,
                    "cy": 436,
                },
            ]
            shelf = {"pos": 0}
            swipes: list[str] = []

            def fake_swipe(_ctx, _name: str, start, end, **_kwargs) -> bool:
                if start[1] > end[1]:
                    swipes.append("down")
                    shelf["pos"] = min(1, shelf["pos"] + 1)
                else:
                    swipes.append("up")
                    shelf["pos"] = max(0, shelf["pos"] - 1)
                return True

            pop_init = {
                "item_name": "进货采买书",
                "cur_qty": 1,
                "max_qty": 5,
                "price": 15000,
                "currency": "gold",
                "min_pt": (386, 377),
                "dec_pt": (447, 377),
                "inc_pt": (826, 377),
                "max_pt": (892, 377),
                "cancel_pt": (349, 534),
                "confirm_pt": (983, 534),
            }
            pop_max = dict(pop_init, cur_qty=5, price=75000)

            rules = parse_shop_buy_rules(
                "拉普拉斯协议:周, 拉普拉斯协议:月, 进货采买书:周",
                default_currency="gold",
            )
            with (
                patch.object(asa, "safe_screencap", return_value=img),
                patch.object(asa, "ocr_roi", return_value=[]),
                patch.object(asa, "parse_hq_balances", return_value={"gold": 34595719, "ticket": 772}),
                patch.object(
                    asa,
                    "parse_hq_shop_cards",
                    side_effect=lambda *_a, **_kw: page0_cards if shelf["pos"] == 0 else page1_cards,
                ),
                patch.object(asa, "swipe_points", side_effect=fake_swipe),
                patch.object(asa, "tap_point", return_value=True),
                patch.object(asa, "sleep_with_stop", return_value=True),
                patch.object(asa, "dismiss_reward_popup_if_present", return_value=True),
                patch.object(asa, "_wait_popup", return_value=(img, pop_init, False)),
                patch.object(asa, "parse_shop_confirm_popup", return_value=pop_max),
            ):
                ok, bought_logs, matched_periods, partial = asa._run_black_moon_hq(
                    ctx,
                    "TestHq",
                    rules,
                    3000000,
                    False,
                    [],
                    0,
                )

            self.assertTrue(ok)
            self.assertEqual(bought_logs, ["进货采买书(weekly)x5@75000"])
            self.assertEqual(matched_periods, {"weekly", "monthly"})
            self.assertFalse(partial)
            self.assertEqual(swipes, ["down", "up"])

    def test_action_max_buy_limit_stops_at_quota_and_skips_when_reached(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.auto_shop_action as asa

            img = np.full((720, 1280, 3), 28, dtype=np.uint8)
            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
            rules = parse_shop_buy_rules("提神棒棒糖:周*3", default_currency="gold")

            # Case 1: 8/8 -> buys 3 units with partial=False (not marked budget shortage)
            card_full = {
                "name": "提神棒棒糖",
                "period": "weekly",
                "remaining": 8,
                "limit_total": 8,
                "sold_out": False,
                "unit_cost": 10000,
                "currency": "gold",
                "tap_point": (780, 464),
                "col": 0,
                "cy": 464,
            }
            pop_init = {
                "item_name": "提神棒棒糖",
                "cur_qty": 1,
                "max_qty": 8,
                "price": 10000,
                "currency": "gold",
                "min_pt": (386, 377),
                "dec_pt": (447, 377),
                "inc_pt": (826, 377),
                "max_pt": (892, 377),
                "cancel_pt": (349, 534),
                "confirm_pt": (983, 534),
            }
            pop_three = dict(pop_init, cur_qty=3, price=90000)
            with (
                patch.object(asa, "safe_screencap", return_value=img),
                patch.object(asa, "ocr_roi", return_value=[]),
                patch.object(asa, "parse_hq_balances", return_value={"gold": 34595719, "ticket": 772}),
                patch.object(asa, "parse_hq_shop_cards", return_value=[card_full]),
                patch.object(asa, "swipe_points", return_value=True),
                patch.object(asa, "tap_point", return_value=True) as mock_tap,
                patch.object(asa, "sleep_with_stop", return_value=True),
                patch.object(asa, "dismiss_reward_popup_if_present", return_value=True),
                patch.object(asa, "_wait_popup", return_value=(img, pop_init, False)),
                patch.object(asa, "parse_shop_confirm_popup", return_value=pop_three),
            ):
                ok, bought_logs, matched_periods, partial = asa._run_black_moon_hq(
                    ctx, "TestLimit", rules, 3000000, False, [], 0
                )

            self.assertTrue(ok)
            self.assertEqual(bought_logs, ["提神棒棒糖(weekly)x3@90000"])
            self.assertEqual(matched_periods, {"weekly"})
            self.assertFalse(partial)
            self.assertGreaterEqual(mock_tap.call_count, 3)

            # Case 2: 5/8 (already bought 3/8 this week) -> 0 taps, skipped cleanly
            card_already = dict(card_full, remaining=5)
            with (
                patch.object(asa, "safe_screencap", return_value=img),
                patch.object(asa, "ocr_roi", return_value=[]),
                patch.object(asa, "parse_hq_balances", return_value={"gold": 34595719, "ticket": 772}),
                patch.object(asa, "parse_hq_shop_cards", return_value=[card_already]),
                patch.object(asa, "swipe_points", return_value=True),
                patch.object(asa, "tap_point", return_value=True) as mock_tap_skip,
                patch.object(asa, "sleep_with_stop", return_value=True),
            ):
                ok2, bought_logs2, matched_periods2, partial2 = asa._run_black_moon_hq(
                    ctx, "TestLimitSkip", rules, 3000000, False, [], 0
                )

            self.assertTrue(ok2)
            self.assertEqual(bought_logs2, [])
            self.assertEqual(matched_periods2, {"weekly"})
            self.assertFalse(partial2)
            mock_tap_skip.assert_not_called()

    def _replay_purchase(self, kind, maximum, reserve, *, costs=(), price=None, fault=None, allow_gold=True):
        """Drive the purchase action with a modal whose OCR changes in response to each button tap."""
        with _real_maa_resource() as resource:
            if resource is None:
                self.skipTest("maafw is not installed")
            import agent.auto_shop_action as asa

            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
            gold_image = np.full((720, 1280, 3), 28, dtype=np.uint8)
            blank_image = gold_image.copy()
            _paint_bgr(gold_image, 615, 429, 645, 470, (45, 175, 230))
            name = "进货采买书"
            qty = 1
            adjusted = False
            taps = []
            reads = []
            confirmations = []
            cost_fn = price or (lambda q: q)
            shelf = dict(name=name, period="weekly", remaining=maximum, sold_out=False,
                         limit_total=maximum, currency="gold", unit_cost=1, costs=costs,
                         tap_point=(780, 250), exchange_point=(1177, 250))
            rules = [ShopBuyRule(name, name, "weekly", "gold" if kind == "hq" else None)]

            def tap(_context, label, point):
                nonlocal qty, adjusted
                taps.append(label)
                if point == (983, 534):
                    confirmations.append((qty, cost_fn(qty)))
                elif point in [(386, 377), (447, 377), (826, 377), (892, 377)]:
                    adjusted = True
                    if point == (386, 377):
                        qty = 1
                    elif point == (892, 377):
                        qty = maximum
                    elif fault != "missed-taps":
                        qty += 1 if point == (826, 377) else -1
                return True

            def screenshot(_context):
                return blank_image if adjusted and fault == "currency" else gold_image

            def ocr(_context, _image, _label, roi):
                if roi != asa.SHOP_POPUP_ROI:
                    return []
                reads.append(qty)
                item = "另一件商品" if adjusted and fault == "item" else name
                entries = [
                    {"text": "取消", "box": [323, 519, 52, 30]},
                    {"text": "确定", "box": [957, 519, 52, 30]},
                ]
                if adjusted and fault == "modal":
                    return []
                if not (adjusted and fault == "quantity"):
                    entries.append({"text": f"{qty}/{maximum}", "box": [611, 351, 58, 25]})
                if kind == "hq":
                    entries.append({"text": item, "box": [590, 302, 100, 28]})
                    if not (adjusted and fault == "price"):
                        entries.append({"text": str(cost_fn(qty)), "box": [656, 439, 55, 26]})
                elif fault != "unnamed":
                    entries.append({"text": f"确认消耗以上素材兑换{item}×{qty}吗？", "box": [450, 430, 380, 26]})
                return entries

            with (
                patch.object(asa, "safe_screencap", side_effect=screenshot),
                patch.object(asa, "ocr_roi", side_effect=ocr),
                patch.object(asa, "tap_point", side_effect=tap),
                patch.object(asa, "sleep_with_stop", return_value=True),
                patch.object(asa, "dismiss_reward_popup_if_present", return_value=True),
                patch.object(asa, "parse_hq_balances", return_value={"gold": 100}),
                patch.object(asa, "parse_hq_shop_cards", return_value=[shelf]),
                patch.object(asa, "parse_exchange_shop_rows", return_value=[shelf]),
            ):
                if kind == "hq":
                    result = asa._run_black_moon_hq(ctx, "Replay", rules, reserve, False, [], 0)
                else:
                    result = asa._run_exchange_shop(
                        ctx, "Replay", rules, reserve, shop_kind=kind, allow_gold_medal=allow_gold
                    )
            return result, reads, taps, confirmations

    def test_exchange_reads_actual_quantity_after_40_steps(self) -> None:
        mileage = [{"medal": "mileage", "balance": 100, "unit_cost": 1}]
        result, reads, _, confirmations = self._replay_purchase("chamber", 99, 45, costs=mileage)
        self.assertEqual(reads, [1, 59, 55])
        self.assertEqual(confirmations, [(55, 55)])
        self.assertEqual(result[1], ["进货采买书(weekly)x55"])

        for fault in ("missed-taps", "quantity", "item", "unnamed", "modal"):
            with self.subTest(fault=fault):
                result, _, taps, confirmations = self._replay_purchase("chamber", 99, 45, costs=mileage, fault=fault)
                self.assertEqual(confirmations, [])
                self.assertEqual(result[1], [])
                if fault == "modal":
                    self.assertFalse(result[0])
                else:
                    self.assertTrue(any("Cancel" in tap for tap in taps))

    def test_hq_rechecks_tiered_price_and_identity(self) -> None:
        result, reads, taps, confirmations = self._replay_purchase("hq", 50, 50, price=lambda q: 2 * q - 1)
        self.assertEqual(reads[-1], 38)  # The twelfth decrement still costs 75 with only 50 spendable.
        self.assertEqual(sum("EscDec" in tap for tap in taps), 12)
        self.assertEqual(confirmations, [])
        self.assertEqual(result[1], [])
        self.assertTrue(result[3])
        for fault in ("price", "quantity", "currency", "item", "modal"):
            with self.subTest(fault=fault):
                result, _, _, confirmations = self._replay_purchase("hq", 5, 50, fault=fault)
                self.assertEqual(confirmations, [])
                self.assertEqual(result[1], [])
        _, _, _, confirmations = self._replay_purchase("hq", 5, 50, price=lambda q: q * 10)
        self.assertEqual(confirmations, [(5, 50)])

    def test_fuming_respects_second_currency_and_gold_permission(self) -> None:
        gold = {"medal": "gold_medal", "balance": 100, "unit_cost": 1}
        purple = {"medal": "purple_medal", "balance": 100, "unit_cost": 10}
        for costs in ([gold, purple], [purple, gold]):
            _, _, taps, confirmations = self._replay_purchase("fuming", 5, 100, costs=costs)
            self.assertEqual(taps, [])
            self.assertEqual(confirmations, [])
            _, _, _, confirmations = self._replay_purchase("fuming", 5, 75, costs=costs)
            self.assertEqual(confirmations, [(2, 2)])
        for costs in ([gold, dict(purple, medal="unknown")], [purple, purple], [dict(gold, balance=None)]):
            _, _, _, confirmations = self._replay_purchase("fuming", 5, 0, costs=costs)
            self.assertFalse(confirmations)
        _, _, _, confirmations = self._replay_purchase("fuming", 5, 0, costs=[gold, purple], allow_gold=False)
        self.assertFalse(confirmations)

    def test_fuming_reads_grouped_cost_text_and_rejects_missing_second_price(self) -> None:
        image = np.full((720, 1280, 3), 28, dtype=np.uint8)
        _paint_bgr(image, 821, 162, 876, 190, (45, 140, 235))
        _paint_bgr(image, 909, 162, 964, 190, (220, 120, 70))
        item = {"text": "进货采买书×1", "box": [656, 240, 110, 19]}
        for text, width in (("10000/1 100/10", 160), ("10000/1 100/?", 160), ("10000/1100/10", 160),
                            ("10000/1", 75)):
            with self.subTest(text=text):
                entries = [item, {"text": text, "box": [816, 240, width, 18]}]
                row, = parse_exchange_shop_rows(entries, image, classify_medal=True)
                costs = row["costs"]
                if text == "10000/1 100/10":
                    self.assertEqual(costs, [
                        {"medal": "gold_medal", "balance": 10000, "unit_cost": 1},
                        {"medal": "purple_medal", "balance": 100, "unit_cost": 10},
                    ])
                else:
                    self.assertEqual(costs, [])

    def test_pipeline_task_schema_and_maafw_bundle_load(self) -> None:
        pipeline = json.loads((ROOT / "assets/resource/base/pipeline/daily/auto_shop.json").read_text(encoding="utf-8"))
        task_cfg = json.loads((ROOT / "assets/resource/tasks/AutoShop.json").read_text(encoding="utf-8"))

        for node_name, node in pipeline.items():
            act = node.get("action")
            act_type = act.get("type") if isinstance(act, dict) else act
            self.assertNotIn(act_type, ("Click", "Swipe"), msg=node_name)

        # Ensure zero attach override collisions across all AutoShop options, and validate checkboxes.
        seen_targets: dict[tuple[str, str], str] = {}
        checkbox_opts: list[tuple[str, dict[str, object]]] = []
        for opt_name, opt in task_cfg["option"].items():
            if "pipeline_override" in opt:
                for target_node, override in opt["pipeline_override"].items():
                    for key in ("attach", "custom_action_param"):
                        if key in override:
                            prev = seen_targets.get((target_node, key))
                            if prev is not None:
                                self.assertEqual(prev, opt_name, msg=f"{target_node}.{key} overwritten")
                            seen_targets[(target_node, key)] = opt_name
            if opt.get("type") == "checkbox":
                checkbox_opts.append((opt_name, opt))
                cases = opt.get("cases", [])
                self.assertGreater(len(cases), 0, msg=f"{opt_name} has no cases")
                case_names = [c["name"] for c in cases]
                self.assertEqual(len(case_names), len(set(case_names)), msg=f"{opt_name} duplicate case names")
                for default_name in opt.get("default_case", []):
                    self.assertIn(default_name, case_names, msg=f"{opt_name} invalid default_case {default_name}")
                seen_checkbox_subkeys: dict[str, set[str]] = {}
                for case in cases:
                    for target_node, override in case.get("pipeline_override", {}).items():
                        attach = override.get("attach", {})
                        used = seen_checkbox_subkeys.setdefault(target_node, set())
                        overlap = used & set(attach.keys())
                        self.assertFalse(overlap, msg=f"{opt_name}.{case['name']} collides on {target_node}.{overlap}")
                        used.update(attach.keys())
            for case in opt.get("cases", []):
                for target_node, override in case.get("pipeline_override", {}).items():
                    for key in ("attach", "custom_action_param"):
                        if key in override:
                            prev = seen_targets.get((target_node, key))
                            if prev is not None:
                                self.assertEqual(prev, opt_name, msg=f"{target_node}.{key} overwritten")
                            seen_targets[(target_node, key)] = opt_name

        self.assertEqual(
            {name for name, _ in checkbox_opts},
            {
                "AutoShopHqGoldItems",
                "AutoShopHqTicketItems",
                "AutoShopFumingItems",
                "AutoShopChamberItems",
            },
        )

        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            res = Resource()
            self.assertTrue(res.post_bundle(ROOT / "assets" / "resource" / "base").wait().succeeded)
            for node_name in pipeline:
                self.assertIsNotNone(res.get_node_data(node_name), msg=f"Missing node: {node_name}")

            # Verify maafw merges multiple checkbox case pipeline_overrides onto attach without overwriting.
            hq_opt = task_cfg["option"]["AutoShopHqGoldItems"]
            picked_cases = [c for c in hq_opt["cases"] if c["name"] in hq_opt["default_case"]]
            for case in picked_cases:
                self.assertTrue(res.override_pipeline(case["pipeline_override"]))
            merged_attach = (res.get_node_data("AutoShopOptHqGoldItems") or {}).get("attach", {})
            self.assertEqual(
                merged_attach,
                {
                    "hq_gold_pick_01": "拉普拉斯协议:周",
                    "hq_gold_pick_02": "拉普拉斯协议:月",
                    "hq_gold_pick_03": "追加注资申请书:月",
                    "hq_gold_pick_04": "进货采买书:周",
                    "hq_gold_pick_05": "仙人掌能量棒棒糖:周",
                    "hq_gold_pick_06": "提神棒棒糖:周",
                },
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from maa_resonance.logic.planner import (
    MarketData,
    get_resonance_skill_buy_more_flat_amount,
    get_resonance_skill_buy_more_percent,
    get_resonance_skill_tax_cut_percent,
    load_columba_trade_data,
    route_tired,
)
from maa_resonance.logic.profile_parser import load_role_names, match_role_name, role_resonance_max
from tools.update_role_life_skills import trade_effects


class RoleLifeSkillDataTest(unittest.TestCase):
    def setUp(self):
        self.data = load_columba_trade_data()

    def percent(self, role, level, product, city="修格里城", kind="Normal"):
        return get_resonance_skill_buy_more_percent(
            self.data, {role: {"resonance": level}}, {"name": product, "type": kind}, city,
        )

    def test_new_roles_are_recognizable_and_have_complete_catalog_metadata(self):
        for role in ("美琪", "多萝西·瑰晨", "伊洛娜·暮光", "爱弥儿", "婕丝&西蒙"):
            with self.subTest(role=role):
                self.assertIn(role, load_role_names())
                self.assertEqual(match_role_name(role), role)
                self.assertEqual(role_resonance_max(role), 5)
                for defaults in (self.data["default_roles"], self.data["default_player_config"]["roles"],
                                 self.data["default_player_config_no_return_bargain"]["roles"]):
                    self.assertEqual(defaults[role]["resonance"], 5)
        self.assertEqual(match_role_name("多萝西"), "多萝西")
        self.assertEqual(match_role_name("伊洛娜"), "伊洛娜")

    def test_patrol_upgrades_do_not_add_trading_effects(self):
        for role, product in (("多萝西·瑰晨", "弹丸加速装置"), ("伊洛娜·暮光", "飞弹")):
            self.assertEqual(set(self.data["resonance_skills"][role]), {"4"})
            self.assertEqual(self.percent(role, 3, product), 0)
            self.assertEqual(self.percent(role, 4, product), 20)
            self.assertEqual(self.percent(role, 5, product), 20)
        for level in (4, 5):
            roles = {"美琪": {"resonance": level}}
            product = {"name": "家用机器人"}
            self.assertEqual(get_resonance_skill_buy_more_flat_amount(self.data, roles, product), 1)
            self.assertEqual(get_resonance_skill_buy_more_percent(self.data, roles, product, "修格里城"), 0)

    def test_crafting_probability_is_excluded_and_craft_goods_upgrade_is_cumulative(self):
        self.assertEqual(set(self.data["resonance_skills"]["爱弥儿"]), {"4", "5"})
        for level, expected in ((1, 0), (3, 0), (4, 20), (5, 30)):
            self.assertEqual(self.percent("爱弥儿", level, "羽纸扇"), expected)
            self.assertEqual(self.percent("爱弥儿", level, "啤酒"), 0)
        self.assertEqual(self.percent("伊洛娜·暮光", 5, "棉花"), 0)

    def test_specialty_quantity_and_tax_are_kept_separate(self):
        for role, city in (("沃斯托克", "阿妮塔发射中心"), ("蓝鹊儿", "武林源")):
            self.assertEqual(self.percent(role, 5, "特产", city, "Special"), 30)
            self.assertEqual(get_resonance_skill_tax_cut_percent(
                self.data, {role: {"resonance": 5}}, city,
            ), -0.005)
        self.assertEqual(self.percent("婕丝&西蒙", 4, "特产", "贡露城", "Special"), 20)
        self.assertEqual(self.percent("婕丝&西蒙", 5, "特产", "贡露城", "Special"), 30)
        self.assertEqual(self.percent("婕丝&西蒙", 5, "普通货", "贡露城"), 0)
        # Keep the source conflict auditable while applying the requested description override.
        note = next(x for x in self.data["source"]["role_life_skills"]["source_conflicts"]
                    if x["skill_id"] == 83900294)
        self.assertEqual(note["city_id"], 83000010)
        self.assertEqual(note["source_city"], "阿妮塔发射中心")
        self.assertEqual(note["applied_city"], "贡露城")
        for level, expected in ((1, 0), (4, -0.005), (5, -0.005)):
            with self.subTest(level=level):
                roles = {"婕丝&西蒙": {"resonance": level}}
                self.assertEqual(get_resonance_skill_tax_cut_percent(self.data, roles, "贡露城"), expected)
                self.assertEqual(get_resonance_skill_tax_cut_percent(self.data, roles, "阿妮塔发射中心"), 0)

    def test_generator_overrides_only_jess_and_simon_described_tax_city(self):
        stations = {83000010: {"name": "阿妮塔发射中心"}}
        cases = (
            (83900294, "TaxCuts", "贡露城税率%s%%", "贡露城"),
            (83900295, "TaxCuts", "贡露城税率%s%%", "阿妮塔发射中心"),
            (83900294, "TaxCuts", "阿妮塔发射中心税率%s%%", "阿妮塔发射中心"),
            (83900294, "AddSpecQty", "贡露城特产可买入数量+%s%%", "阿妮塔发射中心"),
        )
        for skill_id, kind, description, expected_city in cases:
            with self.subTest(skill_id=skill_id, kind=kind, description=description):
                unit = {"homeSkillList": [{"id": skill_id, "resonanceLv": 4}]}
                skills = {skill_id: {
                    "id": skill_id, "homeSkillType": kind, "city": 83000010,
                    "desc": description, "param": -0.005 if kind == "TaxCuts" else 0.2,
                }}
                self.assertEqual(trade_effects(unit, 1, skills, {}, stations), {})
                expected = ({"taxCut": {"city": {expected_city: -0.005}}} if kind == "TaxCuts"
                            else {"buyMore": {"city": {expected_city: 20}}})
                for level in (4, 5):
                    self.assertEqual(trade_effects(unit, level, skills, {}, stations), expected)

    def test_generator_ignores_irrelevant_fourth_tier(self):
        unit = {"homeSkillList": [{"id": 1, "resonanceLv": 1},
                                  {"id": 2, "resonanceLv": 4}, {"id": 3, "resonanceLv": 5}]}
        skills = {
            1: {"id": 1, "homeSkillType": "AddQty", "param": .2, "goodsList": [{"id": 10}]},
            2: {"id": 2, "homeSkillType": "AddEntrustReward", "param": .03},
            3: {"id": 3, "homeSkillType": "AddQty", "param": .1, "goodsList": [{"id": 10}]},
        }
        goods = {10: {"name": "测试商品"}}
        self.assertEqual(trade_effects(unit, 4, skills, goods, {}),
                         {"buyMore": {"product": {"测试商品": 20}}})
        self.assertEqual(trade_effects(unit, 5, skills, goods, {}),
                         {"buyMore": {"product": {"测试商品": 30}}})

    def test_unmapped_goods_category_never_becomes_an_all_goods_bonus(self):
        unit = {"homeSkillList": [{"id": 1, "resonanceLv": 4}]}
        skills = {1: {"id": 1, "homeSkillType": "AddTypeQty", "param": .2, "tagId": 99}}
        self.assertEqual(trade_effects(unit, 5, skills, {10: {"name": "普通商品", "goodsType": 1}}, {}), {})

    def test_bokshi_fourth_resonance_keeps_first_tier_driving_assistance(self):
        market = MarketData({}, {}, {"修格里城-铁盟哨站": 24})
        for level, expected in ((0, 24), (1, 23), (4, 23)):
            self.assertEqual(route_tired(market, "修格里城", "铁盟哨站",
                                        {"波克士": {"resonance": level}}), (expected, False))


if __name__ == "__main__":
    unittest.main()

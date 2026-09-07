from __future__ import annotations

import unittest

from maa_resonance.logic.planner import (
    RoutePlanOptions,
    get_resonance_skill_buy_more_flat_amount,
    get_resonance_skill_buy_more_percent,
    get_resonance_skill_tax_cut_percent,
    get_trade_roles,
    load_columba_trade_data,
)


class RoleLifeSkillsTest(unittest.TestCase):
    city = "修格里城"
    product = {"name": "测试商品", "type": "Special"}

    @staticmethod
    def snapshot(percent: int, flat: int, tax: float) -> dict:
        return {
            "buyMore": {"product": {"测试商品": percent}},
            "buyMoreFlat": {"product": {"测试商品": flat}},
            "taxCut": {"city": {"修格里城": tax}},
        }

    def effects(self, data: dict, roles: dict) -> tuple[float, int, float]:
        return (
            get_resonance_skill_buy_more_percent(data, roles, self.product, self.city),
            get_resonance_skill_buy_more_flat_amount(data, roles, self.product),
            get_resonance_skill_tax_cut_percent(data, roles, self.city),
        )

    def test_first_resonance_skill_survives_fourth_resonance(self) -> None:
        data = {"resonance_skills": {"角色": {"1": self.snapshot(20, 3, -0.005)}}}
        for level in (1, 2, 3, 4):
            with self.subTest(level=level):
                self.assertEqual(self.effects(data, {"角色": {"resonance": level}}), (20, 3, -0.005))

    def test_fourth_resonance_skill_survives_fifth_resonance(self) -> None:
        data = {"resonance_skills": {"角色": {"4": self.snapshot(20, 3, -0.005)}}}
        self.assertEqual(self.effects(data, {"角色": {"resonance": 3}}), (0, 0, 0))
        for level in (4, 5):
            with self.subTest(level=level):
                self.assertEqual(self.effects(data, {"角色": {"resonance": level}}), (20, 3, -0.005))

    def test_fifth_resonance_replaces_cumulative_snapshot_without_summing(self) -> None:
        data = {"resonance_skills": {"角色": {
            "5": self.snapshot(30, 5, -0.01),
            "1": self.snapshot(20, 3, -0.005),
        }}}
        self.assertEqual(self.effects(data, {"角色": {"resonance": 4}}), (20, 3, -0.005))
        self.assertEqual(self.effects(data, {"角色": {"resonance": 5}}), (30, 5, -0.01))

    def test_unowned_role_overrides_default_resonance(self) -> None:
        data = {
            "resonance_skills": {"角色": {"1": self.snapshot(20, 3, -0.005)}},
            "default_roles": {"角色": {"resonance": 5}},
        }
        for level in (0, -1):
            with self.subTest(level=level):
                roles = get_trade_roles(data, RoutePlanOptions(roles={"角色": {"resonance": level}}))
                self.assertEqual(self.effects(data, roles), (0, 0, 0))

    def test_disabled_role_overrides_default_and_explicit_resonance(self) -> None:
        data = {
            "resonance_skills": {"角色": {"1": self.snapshot(20, 3, -0.005)}},
            "default_player_config": {"roles": {"角色": {"resonance": 5}}},
        }
        roles = get_trade_roles(data, RoutePlanOptions(
            roles={"角色": {"resonance": 4}}, disabled_roles={"角色"},
        ))
        self.assertNotIn("角色", roles)
        self.assertEqual(self.effects(data, roles), (0, 0, 0))

    def test_missing_roles_stay_absent_when_defaults_disabled(self) -> None:
        data = {
            "resonance_skills": {"角色": {"1": self.snapshot(20, 3, -0.005)}},
            "default_roles": {"角色": {"resonance": 5}},
        }
        roles = get_trade_roles(data, RoutePlanOptions(roles={}, use_default_roles=False))
        self.assertEqual(roles, {})
        self.assertEqual(self.effects(data, roles), (0, 0, 0))

    def test_invalid_snapshot_and_non_level_metadata_do_not_hide_unlocked_skill(self) -> None:
        data = {"resonance_skills": {"角色": {
            "1": self.snapshot(20, 3, -0.005),
            "4": None,
            "5": self.snapshot(30, 5, -0.01),
            "description": "累计技能快照",
        }}}
        self.assertEqual(self.effects(data, {"角色": {"resonance": 4}}), (20, 3, -0.005))

    def test_existing_roles_retain_lower_tier_purchase_bonus(self) -> None:
        data = load_columba_trade_data()
        cases = (
            ("时萝", 4, "阿妮塔101民用无人机", 20),
            ("时萝", 5, "阿妮塔101民用无人机", 30),
            ("嘉尔", 5, "棉花", 20),
        )
        for name, level, product_name, expected in cases:
            with self.subTest(role=name, level=level):
                roles = get_trade_roles(data, RoutePlanOptions(
                    roles={name: {"resonance": level}}, use_default_roles=False,
                ))
                self.assertEqual(get_resonance_skill_buy_more_percent(
                    data, roles, {"name": product_name}, self.city,
                ), expected)

    def test_non_trade_fourth_resonance_does_not_invent_trade_effects(self) -> None:
        data = load_columba_trade_data()
        role_skills = data["resonance_skills"]["时萝"]
        self.assertEqual(set(role_skills), {"1", "5"})
        roles = {"时萝": {"resonance": 4}}
        product = {"name": "阿妮塔101民用无人机", "type": "Special"}
        self.assertEqual(get_resonance_skill_buy_more_percent(data, roles, product, self.city), 20)
        self.assertEqual(get_resonance_skill_buy_more_flat_amount(data, roles, product), 0)
        self.assertEqual(get_resonance_skill_tax_cut_percent(data, roles, self.city), 0)
        self.assertEqual(set(role_skills), {"1", "5"})


if __name__ == "__main__":
    unittest.main()

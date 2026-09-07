from __future__ import annotations

import types
import unittest
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import patch

from tests.test_trade_runtime_fix import trade
from maa_resonance.logic import manual_trade, planner


class RoleCatalogRefreshTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.roles = ("旧角色", "已读角色", "美琪", "未拥有新角色")
        self.stack.enter_context(patch.object(trade, "load_role_names", return_value=self.roles))
        self.stack.enter_context(patch.object(trade, "role_resonance_max", return_value=5))
        self.fingerprint = trade._role_catalog_fingerprint()
        self.account = {
            "uid": "12345678",
            "trade": {
                "role_resonance": {"旧角色": 4, "已读角色": 3},
                "city_unlock_probe": {city: {"status": "available"} for city in trade.CITY_UNLOCK_TARGETS},
            },
            "account_profile_read": {
                "last_smart_scan_date": date.today().isoformat(),
                "role_catalog_fingerprint": "old-catalog",
                "custom_metadata": "keep",
            },
        }
        self.stack.enter_context(patch.object(trade, "_load_account_config", return_value=self.account))
        self.stack.enter_context(patch.object(trade, "_PROFILE_UID", "12345678"))
        self.stack.enter_context(patch.object(trade, "_append_user_log"))
        self.stack.enter_context(patch.object(trade, "_json_payload"))
        self.save = self.stack.enter_context(patch.object(trade, "_save_profile_result", return_value="fake-account.json"))
        self.state = trade._manual_two_city_defaults()
        self.state.update(
            account_identity_confirmed=True,
            account_identity_uid="12345678",
            result={"uid": "12345678"},
        )
        self.stack.enter_context(patch.object(trade, "_MANUAL_TWO_CITY_STATE", self.state))
        self.stack.enter_context(patch.object(
            trade, "_manual_two_city_known_account_context",
            return_value=(Path("12345678.json"), self.account, "12345678", True),
        ))
        self.scan = trade._initial_role_resonance_state()
        self.stack.enter_context(patch.object(trade, "_ROLE_RESONANCE_STATE", self.scan))

    def seed_scan(self, *, reason="stale_page_signature"):
        self.scan.update(
            role_resonance_seen_roles=["已读角色", "美琪"],
            role_resonance_votes={"已读角色": [3], "美琪": [2]},
            role_resonance_pages=[
                {"visible_roles": ["旧角色", "已读角色"]},
                {"visible_roles": ["已读角色", "美琪"]},
            ],
            role_resonance_continue_state={"should_continue": False, "reason": reason},
        )

    def record_page_and_continue(self, page_index, page_roles):
        trade._record_role_resonance_page(
            page_index, page_roles, {}, set(page_roles),
            tuple(f"{role}@{index}:1" for index, role in enumerate(page_roles)), [],
        )
        return trade._role_resonance_continue_state(
            page_index, role_names=self.roles, stale_limit=2, max_pages=24, scan_mode="missing_roles"
        )

    def manual_options(self, account):
        return manual_trade._planner_options_from_account(
            account, start_city="修格里城", target_city="7号自由港", start_book=0, target_book=0,
            start_bargain_percent=0, start_raise_percent=0, target_bargain_percent=0, target_raise_percent=0,
        )

    def test_real_account_never_inherits_unread_default_roles(self):
        data = {"default_roles": {"旧角色": {"resonance": 5}, "美琪": {"resonance": 5}},
                "resonance_skills": {"美琪": {"1": {}, "5": {}}}}
        with patch.object(trade, "_manual_two_city_load_account_config_for_result", return_value=(Path("12345678.json"), self.account)):
            options = [
                self.manual_options(self.account),
                manual_trade._auto_planner_options_from_account(self.account),
                trade._manual_two_city_product_scan_plan_options({"uid": "12345678"}),
            ]
        with patch.object(planner, "get_default_player_config", return_value={}):
            for option in options:
                with self.subTest(option=option):
                    roles = planner.get_trade_roles(data, option)
                    self.assertNotIn("美琪", roles)
                    self.assertEqual(roles["旧角色"]["resonance"], 4)
                    self.assertFalse(option.use_default_roles)

    def test_explicit_default_estimate_still_supplies_full_roles(self):
        with patch.object(manual_trade, "load_role_names", return_value=self.roles), patch.object(
            manual_trade, "role_resonance_max", return_value=5
        ):
            account = manual_trade.build_default_account_config("12345678")
        with patch.object(trade, "_manual_two_city_load_account_config_for_result", return_value=(Path("12345678.json"), {})), patch.object(
            trade, "build_default_account_config", return_value=account
        ):
            product_options = trade._manual_two_city_product_scan_plan_options(
                {"uid": "12345678", "used_default_account_config": True}
            )
        for option in (self.manual_options(account), manual_trade._auto_planner_options_from_account(account), product_options):
            with self.subTest(option=option), patch.object(planner, "get_default_player_config", return_value={}):
                roles = planner.get_trade_roles({}, option)
                self.assertEqual(set(roles), set(self.roles))
                self.assertTrue(all(role["resonance"] == 5 for role in roles.values()))

    def test_changed_or_missing_catalog_bypasses_daily_and_weekly_cache(self):
        for fingerprint in (None, "old-catalog"):
            self.account["account_profile_read"]["role_catalog_fingerprint"] = fingerprint
            for interval in ("daily", "weekly"):
                with self.subTest(fingerprint=fingerprint, interval=interval):
                    status = trade._manual_two_city_smart_scan_status(self.state, interval)
                    self.assertTrue(status["due"])
                    self.assertEqual(status["reason"], "role_catalog_changed")

    def test_matching_catalog_keeps_the_smart_interval(self):
        self.account["account_profile_read"]["role_catalog_fingerprint"] = self.fingerprint
        for interval in ("daily", "weekly"):
            status = trade._manual_two_city_smart_scan_status(self.state, interval)
            self.assertFalse(status["due"])
            self.assertEqual(status["reason"], "interval_not_elapsed")

    def test_none_mode_does_not_scan_an_updated_catalog(self):
        self.state["account_profile_read_mode"] = "none"
        with patch.object(trade, "_manual_two_city_smart_scan_status") as status, patch.object(
            trade, "_manual_two_city_recalculate_after_account_profile", return_value=True
        ):
            self.assertFalse(trade.ManualTwoCityBusinessAccountProfileWarmupStartAction().run(
                None, types.SimpleNamespace(custom_action_param={"source": "main_map"})
            ))
        status.assert_not_called()
        self.save.assert_not_called()

    def test_catalog_upgrade_does_not_stop_at_a_known_first_page(self):
        self.scan.update(
            role_resonance={"旧角色": 4, "已读角色": 3},
            role_resonance_pages=[{"visible_roles": ["旧角色", "已读角色"]}],
            role_resonance_page_signatures=[["旧角色", "已读角色"]],
        )
        result = trade._role_resonance_continue_state(
            1, role_names=self.roles, stale_limit=2, max_pages=24, scan_mode="missing_roles"
        )
        self.assertTrue(result["should_continue"])
        self.assertEqual(result["scan_mode"], "catalog_refresh")
        self.assertEqual(result["reason"], "continue_scan")

    def test_successful_catalog_scan_preserves_old_roles_and_marks_fingerprint(self):
        first = self.record_page_and_continue(1, {"旧角色": 4, "已读角色": 3})
        self.assertTrue(first["should_continue"])
        next_page = self.record_page_and_continue(2, {"已读角色": 3, "美琪": 2})
        self.assertTrue(next_page["should_continue"])
        self.assertTrue(next_page["page_progressed"])
        last = self.record_page_and_continue(3, {"已读角色": 3, "美琪": 2})
        self.assertFalse(last["should_continue"])
        self.assertEqual(last["reason"], "stale_page_signature")
        result = trade._complete_role_resonance_read(self.roles, scan_mode="missing_roles")
        self.assertTrue(result["ok"])
        payload = self.save.call_args.args[0]
        self.assertEqual(payload["role_resonance"], {"旧角色": 4, "已读角色": 3, "美琪": 2})
        self.assertNotIn("未拥有新角色", payload["role_resonance"])
        self.assertEqual(payload["account_profile_read"]["role_catalog_fingerprint"], self.fingerprint)
        self.assertEqual(payload["account_profile_read"]["custom_metadata"], "keep")
        self.assertEqual(payload["account_profile_read"]["last_smart_scan_date"], date.today().isoformat())

        # Exercise the actual profile merge used by persistence, not only its partial input.
        merged = trade._merge_profile_result(trade._profile_result_from_account_config(self.account), payload)
        self.assertEqual(merged["role_resonance"]["旧角色"], 4)
        self.assertEqual(merged["role_resonance"]["美琪"], 2)
        self.account["trade"]["role_resonance"] = merged["role_resonance"]
        self.account["account_profile_read"] = merged["account_profile_read"]
        self.assertFalse(trade._manual_two_city_smart_scan_status(self.state, "weekly")["due"])

    def test_repeated_first_page_cannot_mark_the_catalog_refreshed(self):
        self.assertTrue(self.record_page_and_continue(1, {"旧角色": 4, "已读角色": 3})["should_continue"])
        last = self.record_page_and_continue(2, {"旧角色": 4, "已读角色": 3})
        self.assertFalse(last["should_continue"])
        self.assertFalse(last["page_progressed"])
        self.assertEqual(last["reason"], "stale_without_page_progress")
        result = trade._complete_role_resonance_read(self.roles, scan_mode="missing_roles")
        self.assertFalse(result["ok"])
        payload = self.save.call_args.args[0]
        self.assertNotIn("account_profile_read", payload)
        self.assertNotIn("美琪", payload["role_resonance"])
        merged = trade._merge_profile_result(trade._profile_result_from_account_config(self.account), payload)
        self.assertEqual(merged["account_profile_read"]["role_catalog_fingerprint"], "old-catalog")
        self.assertEqual(merged["role_resonance"], self.account["trade"]["role_resonance"])
        self.assertTrue(trade._manual_two_city_smart_scan_status(self.state, "daily")["due"])

    def test_same_page_ocr_changes_do_not_establish_page_progress(self):
        old_page = {"旧角色": 4, "已读角色": 3}
        wider_page = {**old_page, "美琪": 2}
        for first_page, next_page in (
            (old_page, dict(reversed(list(old_page.items())))),
            (old_page, wider_page),
            (wider_page, old_page),
        ):
            with self.subTest(first_page=first_page, next_page=next_page):
                self.scan.clear()
                self.scan.update(trade._initial_role_resonance_state())
                self.record_page_and_continue(1, first_page)
                self.record_page_and_continue(2, next_page)
                last = self.record_page_and_continue(3, next_page)
                self.assertFalse(last["should_continue"])
                self.assertFalse(last["page_progressed"])
                self.assertEqual(last["reason"], "stale_without_page_progress")
                # Completion independently checks recorded pages, including a
                # legacy caller that still supplies the old stale reason.
                self.scan["role_resonance_continue_state"]["reason"] = "stale_page_signature"
                result = trade._complete_role_resonance_read(self.roles, scan_mode="missing_roles")
                self.assertFalse(result["ok"])
                self.assertNotIn("account_profile_read", self.save.call_args.args[0])

    def test_all_targets_resolved_on_first_page_is_still_reliable(self):
        last = self.record_page_and_continue(1, {role: 3 for role in self.roles})
        self.assertFalse(last["should_continue"])
        self.assertFalse(last["page_progressed"])
        self.assertEqual(last["reason"], "all_targets_resolved")
        result = trade._complete_role_resonance_read(self.roles, scan_mode="missing_roles")
        self.assertTrue(result["ok"])
        self.assertEqual(
            self.save.call_args.args[0]["account_profile_read"]["role_catalog_fingerprint"], self.fingerprint
        )

    def test_incomplete_or_unresolved_scan_does_not_mark_catalog(self):
        for reason, unresolved in (("max_pages_reached", False), ("continue_scan", False), ("stale_page_signature", True)):
            with self.subTest(reason=reason, unresolved=unresolved):
                self.scan.clear()
                self.scan.update(trade._initial_role_resonance_state())
                self.seed_scan(reason=reason)
                if unresolved:
                    self.scan["role_resonance_votes"].pop("已读角色")
                result = trade._complete_role_resonance_read(self.roles, scan_mode="missing_roles")
                self.assertFalse(result["ok"])
                payload = self.save.call_args.args[0]
                self.assertNotIn("account_profile_read", payload)
                self.assertEqual(payload["role_resonance"]["旧角色"], 4)
                self.assertEqual(payload["role_resonance"]["已读角色"], 3)
                self.assertTrue(trade._manual_two_city_smart_scan_status(self.state, "daily")["due"])

    def test_targeted_scan_does_not_claim_whole_catalog_or_erase_old_roles(self):
        self.seed_scan(reason="all_targets_resolved")
        self.scan["role_resonance_seen_roles"] = ["美琪"]
        self.scan["role_resonance_votes"] = {"美琪": [2]}
        result = trade._complete_role_resonance_read(("美琪",), scan_mode="full")
        self.assertTrue(result["ok"])
        payload = self.save.call_args.args[0]
        self.assertNotIn("account_profile_read", payload)
        self.assertEqual(payload["role_resonance"], {"旧角色": 4, "已读角色": 3, "美琪": 2})

    def test_catalog_change_during_scan_cannot_mark_the_new_version(self):
        self.seed_scan()
        with patch.object(trade, "load_role_names", return_value=self.roles + ("下一版角色",)):
            trade._complete_role_resonance_read(self.roles, scan_mode="missing_roles")
        self.assertNotIn("account_profile_read", self.save.call_args.args[0])

    def test_fingerprint_ignores_order_but_detects_role_and_limit_changes(self):
        self.assertEqual(self.fingerprint, trade._role_catalog_fingerprint(tuple(reversed(self.roles))))
        self.assertNotEqual(self.fingerprint, trade._role_catalog_fingerprint(self.roles + ("新增角色",)))
        with patch.object(trade, "role_resonance_max", return_value=1):
            self.assertNotEqual(self.fingerprint, trade._role_catalog_fingerprint())


if __name__ == "__main__":
    unittest.main()

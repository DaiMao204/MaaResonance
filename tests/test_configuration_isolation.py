from __future__ import annotations

import copy
import subprocess
import types
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from tests.test_trade_runtime_fix import trade
from maa_resonance.logic.manual_trade import _auto_planner_options_from_account


class ConfigurationIsolationTest(unittest.TestCase):
    def test_city_observations_never_write_frontend_exclusions(self) -> None:
        with patch.object(trade, "_mxu_http_json") as api, patch.object(
            trade, "_fatigue_option_config_paths"
        ) as files:
            unavailable = trade._sync_auto_two_city_exclude_cities_from_unavailable(["岚心城"])
            unlocked = trade._sync_auto_two_city_exclude_cities_from_unavailable([])
        self.assertEqual(unavailable["case_names"], ["岚心城"])
        self.assertEqual(unlocked["case_names"], [])
        self.assertEqual(unavailable["reason"], "account_scoped_only")
        api.assert_not_called()
        files.assert_not_called()

    def test_unlocking_one_account_does_not_leave_automatic_exclusions(self) -> None:
        account_a = trade._compact_account_profile(
            {"unavailable_cities": ["岚心城"], "city_unlock_probe": {"岚心城": {"status": "unavailable"}}},
            uid="100001",
        )
        account_b = trade._compact_account_profile(
            {"available_cities": ["岚心城"], "city_unlock_probe": {"岚心城": {"status": "available"}}},
            uid="100002",
        )
        before_b = copy.deepcopy(account_b)
        self.assertIn("岚心城", _auto_planner_options_from_account(account_a).exclude_cities)
        self.assertNotIn("岚心城", _auto_planner_options_from_account(account_b).exclude_cities)
        profile_a = trade._profile_result_from_account_config(account_a)
        profile_a.update(available_cities=["岚心城"], unavailable_cities=[], city_unlock_probe={"岚心城": {"status": "available"}})
        account_a = trade._compact_account_profile(profile_a, uid="100001")
        options = _auto_planner_options_from_account(account_a, exclude_cities={"荒原站"})
        self.assertNotIn("岚心城", options.exclude_cities)
        self.assertIn("荒原站", options.exclude_cities)
        self.assertEqual(account_b, before_b)

    def test_account_unavailable_cities_and_manual_exclusions_are_combined(self) -> None:
        account = {"trade": {"unavailable_cities": ["岚心城"]}, "planner": {"exclude_cities": ["荒原站"]}}
        options = _auto_planner_options_from_account(account, exclude_cities={"贡露城"})
        self.assertEqual(options.exclude_cities, {"岚心城", "荒原站", "贡露城"})

    def test_medicine_consumption_and_task_end_do_not_replay_old_limits(self) -> None:
        state = {
            "task_entry": trade.AUTO_TWO_CITY_TASK_ENTRY,
            "auto_route_enabled": True,
            "lollipop_use_limit": 5,
            "run_mode": trade.MANUAL_TWO_CITY_RUN_MODE_ONE_ROUND,
            "terminal_status": trade.MANUAL_TWO_CITY_TERMINAL_ONE_ROUND_COMPLETE,
        }
        recovery = {"used": {}}
        frontend = {"remaining": 5}

        def decrement(_resource, _kind, count, **kwargs):
            frontend["remaining"] -= count
            return {"updated": True}

        with ExitStack() as stack:
            stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=state))
            stack.enter_context(patch.object(trade, "_manual_two_city_strength_recovery_state", return_value=recovery))
            decrement_call = stack.enter_context(patch.object(trade, "_fatigue_decrement_option_config_limit", side_effect=decrement))
            stack.enter_context(patch.object(trade, "_fatigue_read_option_config_values", side_effect=lambda **_: dict(frontend)))
            snapshot_write = stack.enter_context(patch.object(trade, "_fatigue_write_option_config_values"))
            process = stack.enter_context(patch.object(subprocess, "Popen"))
            stack.enter_context(patch.object(trade, "_append_user_log"))
            stack.enter_context(patch.object(trade, "_json_payload"))
            trade._manual_two_city_resource_used(state, "提神棒棒糖", "medicine")
            self.assertEqual(frontend["remaining"], 4)
            # A newer user setting must survive the next consumption and task end.
            frontend["remaining"] = 2
            trade._manual_two_city_resource_used(state, "提神棒棒糖", "medicine")
            self.assertEqual(frontend["remaining"], 1)
            self.assertTrue(trade.ManualTwoCityBusinessDoneAction().run(None, types.SimpleNamespace()))
        self.assertEqual(frontend["remaining"], 1)
        self.assertEqual(decrement_call.call_count, 2)
        self.assertEqual(recovery["used"]["提神棒棒糖"], 2)
        snapshot_write.assert_not_called()
        process.assert_not_called()


if __name__ == "__main__":
    unittest.main()

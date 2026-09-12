from __future__ import annotations

import copy
import json
import types
import unittest
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import patch

from tests.test_trade_runtime_fix import trade
from maa_resonance.logic import manual_trade


ROOT = Path(__file__).resolve().parents[1]


class AccountIdentityRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.state = trade._manual_two_city_defaults()
        self.state.update(
            result={"uid": "11111111", "account_config": "11111111.json"},
            manual_params={"uid": "", "start_city": "修格里城", "target_city": "7号自由港"},
            auto_route_params={"uid": ""},
        )
        self.stack.enter_context(patch.object(trade, "_MANUAL_TWO_CITY_STATE", self.state))
        self.stack.enter_context(patch.object(trade, "_PROFILE_UID", "11111111"))
        self.stack.enter_context(patch.object(trade, "_append_user_log"))
        self.stack.enter_context(patch.object(trade, "_json_payload"))
        self.save_profile = self.stack.enter_context(patch.object(trade, "_save_profile_result"))
        self.argv = types.SimpleNamespace(custom_action_param={"source": "main_map"})

    def account(self, uid: str = "22222222") -> dict:
        return {
            "uid": uid,
            "trade": {"city_unlock_probe": {city: {"status": "available"} for city in trade.CITY_UNLOCK_TARGETS}},
            "account_profile_read": {
                "last_smart_scan_date": date.today().isoformat(),
                "role_catalog_fingerprint": trade._role_catalog_fingerprint(),
            },
        }

    def test_startup_planners_do_not_choose_the_latest_account_without_uid(self) -> None:
        for calculate, params in (
            (manual_trade.calculate_auto_two_city_trade, {}),
            (manual_trade.calculate_manual_two_city_trade, {"start_city": "修格里城", "target_city": "7号自由港"}),
        ):
            with self.subTest(calculate=calculate.__name__), patch.object(
                manual_trade, "find_account_config", side_effect=AssertionError("must not load latest account")
            ) as find, patch.object(manual_trade, "build_default_account_config", return_value={}) as default, patch.object(
                manual_trade, "load_columba_baseline_market_data", side_effect=RuntimeError("market boundary")
            ):
                with self.assertRaisesRegex(RuntimeError, "market boundary"):
                    calculate(**params, uid="", require_uid=True, allow_default_account=True)
                find.assert_not_called()
                default.assert_called_once_with("")

    def test_same_day_account_switch_confirms_uid_before_using_smart_cache(self) -> None:
        with patch.object(trade, "_manual_two_city_smart_scan_status") as scan:
            self.assertTrue(trade.ManualTwoCityBusinessAccountProfileWarmupStartAction().run(None, self.argv))
            scan.assert_not_called()
        self.assertTrue(self.state["account_identity_pending"])
        account = self.account()
        with patch.object(trade, "_load_account_config", return_value=account) as load:
            self.assertTrue(trade._manual_two_city_confirm_account_identity(["UID:22222222"]))
            load.assert_called_once_with("22222222")
        self.assertEqual(self.state["result"]["uid"], "22222222")
        self.assertEqual(self.state["manual_params"]["uid"], "22222222")
        self.assertEqual(self.state["auto_route_params"]["uid"], "22222222")
        with patch.object(
            trade, "_manual_two_city_known_account_context", return_value=(Path("22222222.json"), account, "22222222", True)
        ), patch.object(trade, "_manual_two_city_recalculate_after_account_profile", return_value=True) as recalculate:
            self.assertFalse(trade.ManualTwoCityBusinessAccountProfileWarmupStartAction().run(None, self.argv))
            recalculate.assert_called_once_with()
        self.assertTrue(self.state["account_profile_warmup_done"])
        self.save_profile.assert_not_called()

    def test_uid_failure_clears_old_identity_and_stops_without_writing(self) -> None:
        self.assertFalse(trade._manual_two_city_confirm_account_identity(["主界面"]))
        self.assertEqual(trade._PROFILE_UID, "")
        self.assertTrue(self.state["account_identity_failed"])
        self.assertFalse(self.state["account_identity_confirmed"])
        self.assertEqual(self.state["terminal_status"], trade.MANUAL_TWO_CITY_TERMINAL_FAILED)
        self.assertFalse(trade._record_profile_uid([])["ok"])
        self.save_profile.assert_not_called()

    def test_main_map_ocr_binds_and_saves_uid_without_adjacent_level(self) -> None:
        entries = [
            {"box": [124, 705, 69, 10], "text": "UID:8822020153"},
            {"box": [150, 686, 21, 10], "text": "079"},
            {"box": [202, 681, 124, 20], "text": "资产14604739"},
        ]
        argv = types.SimpleNamespace(reco_detail={"all": entries, "filtered": entries, "best": entries[0]})
        with patch.object(trade, "_load_account_config", return_value=self.account("8822020153")) as load:
            self.assertTrue(trade.ManualTwoCityBusinessAccountIdentityReadAction().run(None, argv))
        load.assert_called_once_with("8822020153")
        self.assertEqual(self.state["account_identity_uid"], "8822020153")
        self.assertEqual(self.state["manual_params"]["uid"], "8822020153")
        self.assertEqual(self.state["auto_route_params"]["uid"], "8822020153")
        self.assertTrue(trade.ProfileUidReadAction().run(None, argv))
        self.save_profile.assert_called_once()
        self.assertEqual(self.save_profile.call_args.args[0]["uid"], "8822020153")

    def test_ambiguous_uid_stops_before_loading_or_writing_account(self) -> None:
        with patch.object(trade, "_load_account_config") as load:
            self.assertFalse(trade._manual_two_city_confirm_account_identity(["UID:11111111", "UID:22222222"]))
        load.assert_not_called()
        self.assertTrue(self.state["account_identity_failed"])
        self.assertEqual(self.state["terminal_status"], trade.MANUAL_TWO_CITY_TERMINAL_FAILED)
        self.save_profile.assert_not_called()

    def test_profile_uid_reread_must_match_the_confirmed_account(self) -> None:
        for texts in (["UID:33333333"], []):
            with self.subTest(texts=texts):
                self.state.update(account_identity_confirmed=True, account_identity_uid="22222222")
                trade._PROFILE_UID = "22222222"
                self.assertFalse(trade._record_profile_uid(texts)["ok"])
                self.assertEqual(trade._PROFILE_UID, "")
                self.assertTrue(self.state["account_identity_failed"])
                self.assertEqual(self.state["terminal_status"], trade.MANUAL_TWO_CITY_TERMINAL_FAILED)
        self.save_profile.assert_not_called()

    def test_none_mode_still_confirms_uid_but_skips_profile_scan(self) -> None:
        self.state["account_profile_read_mode"] = trade.MANUAL_TWO_CITY_ACCOUNT_READ_NONE
        with patch.object(trade, "_manual_two_city_recalculate_after_account_profile") as recalculate:
            self.assertTrue(trade.ManualTwoCityBusinessAccountProfileWarmupStartAction().run(None, self.argv))
            recalculate.assert_not_called()
        with patch.object(trade, "_load_account_config", return_value={}):
            self.assertTrue(trade._manual_two_city_confirm_account_identity(["UID:22222222"]))
        with patch.object(trade, "_manual_two_city_recalculate_after_account_profile", return_value=True) as recalculate:
            self.assertFalse(trade.ManualTwoCityBusinessAccountProfileWarmupStartAction().run(None, self.argv))
            recalculate.assert_called_once_with(allow_default_account=True)
        self.assertTrue(self.state["account_profile_warmup_done"])
        self.assertFalse(self.state.get("account_profile_warmup_pending", False))

    def test_cache_for_another_uid_never_allows_fast_path(self) -> None:
        self.state.update(account_identity_confirmed=True, account_identity_uid="22222222")
        with patch.object(
            trade, "_manual_two_city_known_account_context",
            return_value=(Path("11111111.json"), self.account("11111111"), "11111111", True),
        ):
            status = trade._manual_two_city_smart_scan_status(self.state, trade.MANUAL_TWO_CITY_SMART_SCAN_DAILY)
        self.assertTrue(status["due"])
        self.assertEqual(status["reason"], "account_identity_mismatch")

    def test_stale_result_account_path_is_not_written_after_identity_switch(self) -> None:
        self.state.update(account_identity_confirmed=True, account_identity_uid="22222222")
        with patch.object(Path, "read_text", return_value=json.dumps(self.account("11111111"))), patch.object(
            trade, "_load_account_config", return_value=self.account()
        ) as load, patch.object(trade, "_manual_two_city_persist_account_product_status_defaults", side_effect=lambda path, account: account) as persist:
            path, account = trade._manual_two_city_load_account_config_for_result(self.state["result"])
        load.assert_called_once_with("22222222")
        self.assertEqual(path.stem, "22222222")
        self.assertEqual(account["uid"], "22222222")
        self.assertEqual(persist.call_count, 1)
        self.assertEqual(persist.call_args.args[0].stem, "22222222")

    def test_replan_after_completed_transfer_uses_current_city(self) -> None:
        new_result = {
            "uid": "22222222", "start_city": "修格里城", "target_city": "7号自由港",
            "summary": {"legs": [
                {"buy_city": "修格里城", "sell_city": "7号自由港"},
                {"buy_city": "7号自由港", "sell_city": "修格里城"},
            ]},
        }
        self.state.update(
            auto_route_enabled=True, current_city="修格里城", initial_transfer_source_city="云岫桥基地",
            initial_transfer_done=True, initial_transfer_in_progress=False, result=copy.deepcopy(new_result),
        )
        with patch.object(trade, "calculate_auto_two_city_trade", return_value=new_result), patch.object(
            trade, "_manual_two_city_choose_initial_transfer_destination"
        ) as transfer, patch.object(trade, "save_manual_two_city_result", return_value=Path("unused.json")):
            result = trade._manual_two_city_replan_after_unavailable_destination("岚心城")
        self.assertTrue(result["ok"])
        self.assertEqual(result["current_city"], "修格里城")
        self.assertEqual(result["next_destination"], "7号自由港")
        self.assertFalse(self.state["initial_transfer_in_progress"])
        transfer.assert_not_called()

    def test_visit_region_is_available_without_distance_ocr(self) -> None:
        self.assertEqual(trade.classify_city_unlock_probe(["访问地区"]), "available")
        self.assertEqual(trade.classify_city_unlock_probe(["访问地区", "声望10级"]), "available")
        self.assertEqual(trade.classify_city_unlock_probe(["访问地区", "驭照等级60级开放"]), "unavailable")

    def test_uid_failure_pipeline_has_no_trade_continuation(self) -> None:
        pipeline = json.loads((ROOT / "assets/resource/base/pipeline/business/trade/manual_two_city_business.json").read_text(encoding="utf-8"))
        self.assertEqual(pipeline["ManualTwoCityBusinessAccountIdentityRead"]["on_error"], "ManualTwoCityBusinessAccountIdentityReadFailed")
        self.assertEqual(pipeline["ManualTwoCityBusinessAccountIdentityReadFailed"]["next"], "RunManualTwoCityBusinessDone")
        read_start = pipeline[pipeline["ManualTwoCityBusinessAccountIdentityMainMapReady"]["next"]]
        self.assertEqual(read_start["recognition"], "DirectHit")
        self.assertEqual(read_start["next"], "ManualTwoCityBusinessAccountIdentityRead")
        self.assertEqual(read_start["on_error"], "ManualTwoCityBusinessAccountIdentityReadFailed")
        for task_name in ("AutoTwoCityBusiness", "ManualTwoCityBusiness"):
            task = json.loads((ROOT / f"assets/resource/tasks/{task_name}.json").read_text(encoding="utf-8"))
            overrides = task["task"][0]["pipeline_override"]
            self.assertEqual(overrides["AccountProfileReadStart"]["on_error"], "ManualTwoCityBusinessAccountIdentityReadFailed")
            self.assertEqual(overrides["AccountProfileUidRead"]["on_error"], "ManualTwoCityBusinessAccountIdentityReadFailed")
        for name in ("ManualTwoCityBusinessAccountProfileWarmupStart", "ManualTwoCityBusinessAccountProfileWarmupStartFromMainMap"):
            self.assertEqual(pipeline[name]["next"], "ManualTwoCityBusinessAccountIdentityDispatch")
            self.assertEqual(pipeline[name]["on_error"][0], "ManualTwoCityBusinessAccountIdentityFailedStop")


if __name__ == "__main__":
    unittest.main()

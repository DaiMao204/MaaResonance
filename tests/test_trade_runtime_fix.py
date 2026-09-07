from __future__ import annotations

import json
import sys
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _decorator(_name):
    return lambda cls: cls


agent_server = types.ModuleType("maa.agent.agent_server")
agent_server.AgentServer = type(
    "AgentServer",
    (),
    {
        "custom_action": staticmethod(_decorator),
        "custom_recognition": staticmethod(_decorator),
    },
)
custom_action = types.ModuleType("maa.custom_action")
custom_action.CustomAction = type("CustomAction", (), {})
custom_recognition = types.ModuleType("maa.custom_recognition")
custom_recognition.CustomRecognition = type("CustomRecognition", (), {})
context = types.ModuleType("maa.context")
context.Context = type("Context", (), {})
sys.modules.update(
    {
        "maa": types.ModuleType("maa"),
        "maa.agent": types.ModuleType("maa.agent"),
        "maa.agent.agent_server": agent_server,
        "maa.custom_action": custom_action,
        "maa.custom_recognition": custom_recognition,
        "maa.context": context,
    }
)
sys.path.insert(0, str(ROOT / "agent"))

import profile_prestige_action as trade


class TradeRuntimeFixTest(unittest.TestCase):
    def setUp(self) -> None:
        self.goods = ["明前龙井", "龙井茶", "武林丝绸", "临安山核桃", "西湖醋鱼", "羽纸扇", "叫化童鸡"]
        self.leg = {
            "buy_city": "武林源",
            "sell_city": "岚心城",
            "restock": 3,
            "goods": self.goods,
            "goods_detail": [
                {"name": good, "num": amount}
                for good, amount in zip(self.goods, [84, 160, 104, 196, 156, 240, 360])
            ],
        }

    def test_inventory_and_product_lot_guards(self) -> None:
        entries = [
            {"text": "进货采买书", "center_x": 731, "center_y": 166},
            {"text": "0", "center_x": 664, "center_y": 191},
            {"text": "236", "center_x": 656, "center_y": 277},
        ]
        self.assertEqual(trade._manual_two_city_book_inventory_from_entries(entries), 0)
        entries[1]["text"] = "2"
        self.assertEqual(trade._manual_two_city_book_inventory_from_entries(entries), 2)
        self.assertTrue(trade._manual_two_city_product_scan_buy_lot_plausible(21, 4))
        self.assertTrue(trade._manual_two_city_product_scan_buy_lot_plausible(40, 13))
        self.assertFalse(trade._manual_two_city_product_scan_buy_lot_plausible(1, 39))
        self.assertFalse(trade._manual_two_city_product_scan_buy_lot_plausible(6, 65))

    def test_haggle_book_popup_respects_confirm_switch(self) -> None:
        with ExitStack() as stack:
            ocr = stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_ocr_entries",
                    return_value=(True, [], ["是否使用再交涉请求书重新议价?", "2/1", "确认"]),
                )
            )
            confirm = stack.enter_context(patch.object(trade, "_manual_two_city_click_ocr_text"))

            result = trade._manual_two_city_confirm_buy_haggle_book_popup(
                None,
                leg=self.leg,
                target_percent=20,
                current_percent=12.2,
                click_count=6,
                probe_name="TradeRuntimeFixBookDisabled",
                allow_confirm=False,
            )

        self.assertEqual(result["status"], "skipped")
        confirm.assert_not_called()
        ocr.assert_called_once()

    def test_haggle_book_popup_stops_when_inventory_is_empty(self) -> None:
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_ocr_entries",
                    return_value=(True, [], ["是否使用再交涉请求书重新议价?", "0/1", "确认"]),
                )
            )
            confirm = stack.enter_context(patch.object(trade, "_manual_two_city_click_ocr_text"))
            result = trade._manual_two_city_confirm_buy_haggle_book_popup(
                None,
                leg=self.leg,
                target_percent=20,
                current_percent=18.3,
                click_count=10,
                probe_name="TradeRuntimeFixNoBook",
            )

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["inventory"], 0)
        confirm.assert_not_called()

    def test_buy_and_sell_haggle_use_at_most_one_book_per_trade(self) -> None:
        cases = [
            (
                trade.ManualTwoCityBusinessApplyBuyHaggleAction,
                "_manual_two_city_buy_bargain_percent",
                "manual_two_city_business_apply_buy_haggle",
            ),
            (
                trade.ManualTwoCityBusinessApplySellHaggleAction,
                "_manual_two_city_sell_raise_percent",
                "manual_two_city_business_apply_sell_haggle",
            ),
        ]
        popup_results = [
            {"status": "absent"},
            {"status": "confirmed", "inventory": 130},
            {"status": "absent"},
            {"status": "skipped"},
        ]
        for action_type, percent_reader, payload_event in cases:
            with self.subTest(action=action_type.__name__), ExitStack() as stack:
                stack.enter_context(
                    patch.object(trade, "_manual_two_city_state", return_value={"use_haggle_book": True})
                )
                stack.enter_context(patch.object(trade, "_manual_two_city_active_leg", return_value=self.leg))
                stack.enter_context(patch.object(trade, percent_reader, return_value=20))
                popup = stack.enter_context(
                    patch.object(
                        trade,
                        "_manual_two_city_confirm_buy_haggle_book_popup",
                        side_effect=list(popup_results),
                    )
                )
                percent = stack.enter_context(
                    patch.object(
                        trade,
                        "_manual_two_city_read_buy_haggle_percent",
                        side_effect=[0.0, 10.0, 12.2],
                    )
                )
                click = stack.enter_context(
                    patch.object(trade, "_manual_two_city_click_ocr_text", return_value=(True, ["议价"]))
                )
                cancel = stack.enter_context(
                    patch.object(trade, "_manual_two_city_cancel_haggle_book_popup", return_value=(True, ["取消"]))
                )
                stack.enter_context(patch.object(trade.time, "perf_counter", return_value=0.0))
                stack.enter_context(patch.object(trade, "_append_user_log"))
                payload = stack.enter_context(patch.object(trade, "_json_payload"))

                ok = action_type().run(None, None)

            self.assertTrue(ok)
            self.assertEqual(popup.call_count, 4)
            self.assertEqual(
                [call.kwargs["allow_confirm"] for call in popup.call_args_list],
                [True, True, False, False],
            )
            self.assertEqual(percent.call_count, 3)
            self.assertEqual(click.call_count, 2)
            cancel.assert_called_once()
            self.assertEqual(payload.call_args.args[0], payload_event)
            self.assertFalse(payload.call_args.args[1]["target_reached"])
            self.assertEqual(payload.call_args.args[1]["haggle_books_used"], 1)
            self.assertEqual(payload.call_args.args[1]["stop_reason"], "book_limit_reached")

    def test_buy_and_sell_haggle_disabled_trade_without_using_book(self) -> None:
        cases = [
            (trade.ManualTwoCityBusinessApplyBuyHaggleAction, "_manual_two_city_buy_bargain_percent"),
            (trade.ManualTwoCityBusinessApplySellHaggleAction, "_manual_two_city_sell_raise_percent"),
        ]
        for action_type, percent_reader in cases:
            with self.subTest(action=action_type.__name__), ExitStack() as stack:
                stack.enter_context(
                    patch.object(trade, "_manual_two_city_state", return_value={"use_haggle_book": False})
                )
                stack.enter_context(patch.object(trade, "_manual_two_city_active_leg", return_value=self.leg))
                stack.enter_context(patch.object(trade, percent_reader, return_value=20))
                popup = stack.enter_context(
                    patch.object(
                        trade,
                        "_manual_two_city_confirm_buy_haggle_book_popup",
                        side_effect=[{"status": "absent"}, {"status": "skipped"}],
                    )
                )
                stack.enter_context(
                    patch.object(trade, "_manual_two_city_read_buy_haggle_percent", side_effect=[12.2, 12.2])
                )
                stack.enter_context(
                    patch.object(trade, "_manual_two_city_click_ocr_text", return_value=(True, ["议价"]))
                )
                cancel = stack.enter_context(
                    patch.object(trade, "_manual_two_city_cancel_haggle_book_popup", return_value=(True, ["取消"]))
                )
                stack.enter_context(patch.object(trade.time, "perf_counter", return_value=0.0))
                stack.enter_context(patch.object(trade, "_append_user_log"))
                payload = stack.enter_context(patch.object(trade, "_json_payload"))

                ok = action_type().run(None, None)

            self.assertTrue(ok)
            self.assertEqual([call.kwargs["allow_confirm"] for call in popup.call_args_list], [False, False])
            cancel.assert_called_once()
            self.assertEqual(payload.call_args.args[1]["haggle_books_used"], 0)
            self.assertEqual(payload.call_args.args[1]["stop_reason"], "book_disabled")

    def test_sell_haggle_book_shortfall_continues_current_trade(self) -> None:
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(trade, "_manual_two_city_state", return_value={"use_haggle_book": True})
            )
            stack.enter_context(patch.object(trade, "_manual_two_city_active_leg", return_value=self.leg))
            stack.enter_context(patch.object(trade, "_manual_two_city_sell_raise_percent", return_value=20))
            stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_confirm_buy_haggle_book_popup",
                    return_value={"status": "unavailable", "inventory": 0},
                )
            )
            cancel = stack.enter_context(
                patch.object(trade, "_manual_two_city_cancel_haggle_book_popup", return_value=(True, ["取消"]))
            )
            stack.enter_context(
                patch.object(trade, "_manual_two_city_read_buy_haggle_percent", return_value=18.3)
            )
            stack.enter_context(patch.object(trade.time, "perf_counter", return_value=0.0))
            stack.enter_context(patch.object(trade, "_append_user_log"))
            payload = stack.enter_context(patch.object(trade, "_json_payload"))

            ok = trade.ManualTwoCityBusinessApplySellHaggleAction().run(None, None)

        self.assertTrue(ok)
        cancel.assert_called_once()
        self.assertEqual(payload.call_args.args[0], "manual_two_city_business_apply_sell_haggle")
        self.assertFalse(payload.call_args.args[1]["target_reached"])
        self.assertEqual(payload.call_args.args[1]["stop_reason"], "unavailable")

    def test_haggle_book_switch_is_wired_below_haggle_settings(self) -> None:
        pipeline_path = ROOT / "assets" / "resource" / "base" / "pipeline" / "business" / "trade" / "manual_two_city_business.json"
        manual_task_path = ROOT / "assets" / "resource" / "tasks" / "ManualTwoCityBusiness.json"
        auto_task_path = ROOT / "assets" / "resource" / "tasks" / "AutoTwoCityBusiness.json"
        interface_path = ROOT / "assets" / "interface.json"
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        manual_task = json.loads(manual_task_path.read_text(encoding="utf-8"))
        auto_task = json.loads(auto_task_path.read_text(encoding="utf-8"))
        interface = json.loads(interface_path.read_text(encoding="utf-8"))

        manual_options = manual_task["task"][0]["option"]
        auto_options = auto_task["task"][0]["option"]
        self.assertEqual(
            manual_options.index("ManualTwoCityUseHaggleBook"),
            manual_options.index("ManualTwoCityTargetParams") + 1,
        )
        self.assertEqual(
            auto_options.index("ManualTwoCityUseHaggleBook"),
            auto_options.index("AutoTwoCityPlannerParams") + 1,
        )
        option = manual_task["option"]["ManualTwoCityUseHaggleBook"]
        self.assertEqual(option["label"], "使用再交涉请求书")
        self.assertEqual(option["default_case"], "No")
        self.assertEqual(
            pipeline["AutoTwoCityBusinessSetPlannerParams"]["next"],
            "ManualTwoCityBusinessSetUseHaggleBook",
        )
        self.assertEqual(
            pipeline["ManualTwoCityBusinessSetReturnParams"]["next"],
            "ManualTwoCityBusinessSetUseHaggleBook",
        )
        self.assertFalse(
            pipeline["ManualTwoCityBusinessSetUseHaggleBook"]["action"]["param"]["custom_action_param"]["use_haggle_book"]
        )
        preset_options = {
            task["name"]: task["option"]
            for preset in interface["preset"]
            for task in preset["task"]
            if task["name"] in {"ManualTwoCityBusiness", "AutoTwoCityBusiness"}
        }
        self.assertEqual(preset_options["ManualTwoCityBusiness"]["ManualTwoCityUseHaggleBook"], "No")
        self.assertEqual(preset_options["AutoTwoCityBusiness"]["ManualTwoCityUseHaggleBook"], "No")

    def test_auto_pickup_has_no_per_leg_tap_limit_and_yields_to_monitor(self) -> None:
        state = {"auto_pickup": True, "auto_pickup_tap_count": 100}
        self.assertTrue(trade._manual_two_city_auto_pickup_gate(state, 100.0)["allowed"])
        state["auto_pickup_yield_monitor_once"] = True
        self.assertEqual(
            trade._manual_two_city_auto_pickup_gate(state, 100.0)["reason"],
            "yield_to_travel_monitor",
        )
        state["auto_pickup"] = False
        self.assertEqual(trade._manual_two_city_auto_pickup_gate(state, 100.0)["reason"], "disabled")

    def test_auto_pickup_entry_yields_once_without_a_hud_probe(self) -> None:
        state = {"auto_pickup": True, "auto_pickup_yield_monitor_once": True}
        with ExitStack() as stack:
            stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=state))
            stack.enter_context(patch.object(trade.CustomRecognition, "AnalyzeResult", types.SimpleNamespace, create=True))
            hud = stack.enter_context(patch.object(trade, "is_travel_hud", return_value=True))
            argv = types.SimpleNamespace(image=object())
            first = trade.ManualTwoCityBusinessAutoPickupAvailableRecognition().analyze(None, argv)
            hud.assert_not_called()
            second = trade.ManualTwoCityBusinessAutoPickupAvailableRecognition().analyze(None, argv)
        self.assertIsNone(first.box)
        self.assertIsNotNone(second.box)
        self.assertNotIn("target", second.detail)
        self.assertNotIn("auto_pickup_pending_detail", state)

    def test_auto_pickup_entry_requires_travel_hud(self) -> None:
        with ExitStack() as stack:
            stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value={"auto_pickup": True}))
            stack.enter_context(patch.object(trade.CustomRecognition, "AnalyzeResult", types.SimpleNamespace, create=True))
            stack.enter_context(patch.object(trade, "is_travel_hud", return_value=False))
            result = trade.ManualTwoCityBusinessAutoPickupAvailableRecognition().analyze(
                None, types.SimpleNamespace(image=object()),
            )
        self.assertIsNone(result.box)

    def test_auto_pickup_normal_windows_resume_cursor_without_yield_or_per_click_logs(self) -> None:
        state = {"auto_pickup": True, "auto_pickup_tap_count": 8, "auto_pickup_next_point_index": 2}
        context = types.SimpleNamespace(tasker=types.SimpleNamespace(controller=object(), stopping=False))
        starts = []
        reasons = iter(("duration_elapsed", "frame_limit", "click_limit"))
        def window(_controller, **kwargs):
            self.assertNotIn("find_targets", kwargs)
            start = kwargs["start_index"]
            starts.append(start)
            calls_before = payload.call_count
            logs_before = log.call_count
            kwargs["on_click"]({"target": [801, 361], "point_index": start, "next_point_index": start + 1})
            kwargs["on_click"]({"target": [822, 358], "point_index": start + 1, "next_point_index": start + 2})
            self.assertEqual(payload.call_count, calls_before)
            self.assertEqual(log.call_count, logs_before)
            return {"reason": next(reasons), "tap_count": 2, "next_point_index": start + 2}
        with ExitStack() as stack:
            stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=state))
            stack.enter_context(patch.object(trade, "_manual_two_city_active_leg", return_value=self.leg))
            stack.enter_context(patch.object(trade, "run_pickup_window", side_effect=window))
            log = stack.enter_context(patch.object(trade, "_append_user_log"))
            payload = stack.enter_context(patch.object(trade, "_json_payload"))
            for _ in range(3):
                self.assertTrue(trade.ManualTwoCityBusinessAutoPickupUsedAction().run(context, None))
                self.assertNotIn("auto_pickup_yield_monitor_once", state)
        self.assertEqual(starts, [2, 4, 6])
        self.assertEqual(state["auto_pickup_tap_count"], 14)
        self.assertEqual(state["auto_pickup_next_point_index"], 8)
        log.assert_called_once()
        self.assertIn("右侧连续点击", log.call_args.args[1])
        self.assertEqual(payload.call_count, 3)
        self.assertTrue(all(call.args[0] == "manual_two_city_business_auto_pickup_window" for call in payload.call_args_list))

    def test_auto_pickup_non_normal_end_skips_light_and_full_monitor_entries(self) -> None:
        for reason in ("travel_hud_lost", "stopped", "screencap_failed"):
            with self.subTest(reason=reason), ExitStack() as stack:
                state = {"auto_pickup": True, "auto_pickup_next_point_index": 7}
                context = types.SimpleNamespace(tasker=types.SimpleNamespace(controller=object(), stopping=False))
                stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=state))
                stack.enter_context(patch.object(trade, "run_pickup_window", return_value={
                    "reason": reason, "next_point_index": 7, "tap_count": 0,
                }))
                stack.enter_context(patch.object(trade, "_json_payload"))
                stack.enter_context(patch.object(trade.CustomRecognition, "AnalyzeResult", types.SimpleNamespace, create=True))
                hud = stack.enter_context(patch.object(trade, "is_travel_hud", return_value=True))
                log = stack.enter_context(patch.object(trade, "_append_user_log"))
                self.assertTrue(trade.ManualTwoCityBusinessAutoPickupUsedAction().run(context, None))
                self.assertEqual(state["auto_pickup_yield_monitor_once"], 2)
                argv = types.SimpleNamespace(image=object())
                # Light branch's pickup candidate misses, then TravelMonitor's
                # pickup candidate misses, so the recovery candidates can run.
                self.assertIsNone(trade.ManualTwoCityBusinessAutoPickupAvailableRecognition().analyze(context, argv).box)
                self.assertEqual(state["auto_pickup_yield_monitor_once"], 1)
                self.assertIsNone(trade.ManualTwoCityBusinessAutoPickupAvailableRecognition().analyze(context, argv).box)
                hud.assert_not_called()
                self.assertNotIn("auto_pickup_yield_monitor_once", state)
                self.assertIsNotNone(trade.ManualTwoCityBusinessAutoPickupAvailableRecognition().analyze(context, argv).box)
                hud.assert_called_once()
                self.assertEqual(state["auto_pickup_next_point_index"], 7)
                log.assert_not_called()

    def test_auto_pickup_yields_after_error_and_does_not_invent_a_click(self) -> None:
        state = {"auto_pickup": True, "auto_pickup_tap_count": 4, "auto_pickup_next_point_index": 3,
                 "auto_pickup_progress_checked_at": 90.0}
        context = types.SimpleNamespace(tasker=types.SimpleNamespace(controller=object(), stopping=False))
        with ExitStack() as stack:
            stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=state))
            stack.enter_context(patch.object(trade, "run_pickup_window", side_effect=RuntimeError("capture failed")))
            stack.enter_context(patch.object(trade, "_json_payload"))
            self.assertTrue(trade.ManualTwoCityBusinessAutoPickupUsedAction().run(context, None))
        self.assertEqual(state["auto_pickup_tap_count"], 4)
        self.assertEqual(state["auto_pickup_yield_monitor_once"], 2)
        self.assertEqual(state["auto_pickup_next_point_index"], 3)
        trade._manual_two_city_reset_auto_pickup_state(state)
        self.assertNotIn("auto_pickup_yield_monitor_once", state)
        self.assertEqual(state["auto_pickup_tap_count"], 0)
        self.assertEqual(state["auto_pickup_next_point_index"], 0)
        self.assertNotIn("auto_pickup_progress_checked_at", state)

    def test_pickup_progress_check_is_due_once_per_ten_seconds(self) -> None:
        state = {"auto_pickup": True}
        with ExitStack() as stack:
            stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=state))
            stack.enter_context(patch.object(trade.CustomRecognition, "AnalyzeResult", types.SimpleNamespace, create=True))
            stack.enter_context(patch.object(trade.time, "monotonic", side_effect=[0.0, 9.999, 10.0]))
            recognition = trade.ManualTwoCityBusinessPickupProgressDueRecognition()
            self.assertIsNotNone(recognition.analyze(None, None).box)
            self.assertEqual(state["auto_pickup_progress_checked_at"], 0.0)
            self.assertIsNone(recognition.analyze(None, None).box)
            self.assertEqual(state["auto_pickup_progress_checked_at"], 0.0)
            self.assertIsNotNone(recognition.analyze(None, None).box)
            self.assertEqual(state["auto_pickup_progress_checked_at"], 10.0)

    def test_pickup_progress_check_does_not_run_when_disabled_or_consume_error_yield(self) -> None:
        for state in ({"auto_pickup": False}, {"auto_pickup": True, "auto_pickup_yield_monitor_once": 2}):
            with self.subTest(state=state), ExitStack() as stack:
                before = dict(state)
                stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=state))
                stack.enter_context(patch.object(trade.CustomRecognition, "AnalyzeResult", types.SimpleNamespace, create=True))
                stack.enter_context(patch.object(trade.time, "monotonic", return_value=100.0))
                result = trade.ManualTwoCityBusinessPickupProgressDueRecognition().analyze(None, None)
                self.assertIsNone(result.box)
                self.assertEqual(state, before)

    def test_pickup_progress_check_reuses_stall_threshold_without_duplicate_restart(self) -> None:
        state = {"auto_pickup": True}
        with ExitStack() as stack:
            stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=state))
            stack.enter_context(patch.object(trade.CustomRecognition, "AnalyzeResult", types.SimpleNamespace, create=True))
            clock = stack.enter_context(patch.object(trade.time, "monotonic"))
            ocr = stack.enter_context(patch.object(trade, "_manual_two_city_ocr_entries", return_value=(False, [], [])))
            stack.enter_context(patch.object(trade, "travel_status_from_texts", return_value={
                "remaining_km": 50, "destination": "海角城",
            }))
            stack.enter_context(patch.object(trade, "_json_payload"))
            stack.enter_context(patch.object(trade, "_append_user_log"))
            recognition = trade.ManualTwoCityBusinessPickupProgressDueRecognition()
            action = trade.ManualTwoCityBusinessTravelStallWatchdogAction()
            for now in (100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 175.0):
                clock.return_value = now
                self.assertIsNotNone(recognition.analyze(None, None).box)
                self.assertEqual(action.run(None, None), now == 175.0)
            self.assertEqual(state["travel_stall_hit_count"], 8)
            self.assertEqual(state["travel_stall_restart_count"], 1)
            clock.return_value = 175.001
            self.assertIsNone(recognition.analyze(None, None).box)
            self.assertEqual(state["travel_stall_restart_count"], 1)
            self.assertEqual(ocr.call_count, 8)

    def test_speed_projectile_zero_count_is_unavailable(self) -> None:
        context = types.SimpleNamespace(run_recognition=Mock(side_effect=[object(), types.SimpleNamespace(hit=False)]))
        with patch.object(trade, "_ocr_texts_from_detail", side_effect=[["0"], []]):
            status = trade._manual_two_city_speed_projectile_status(
                context,
                object(),
                "TradeRuntimeFixSpeedProjectile",
            )

        self.assertTrue(status["unavailable"])
        self.assertEqual(status["count"], 0)

    def test_speed_projectile_unavailable_disables_more_clicks(self) -> None:
        state = {
            "auto_use_speed_projectile": True,
            "speed_projectile_unavailable": False,
            "speed_projectile_unavailable_logged": False,
        }
        with ExitStack() as stack:
            stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=state))
            stack.enter_context(patch.object(trade, "_argv_param", return_value={"item": "speed_projectile"}))
            stack.enter_context(patch.object(trade, "_manual_two_city_screencap", return_value=object()))
            stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_speed_projectile_status",
                    return_value={"unavailable": True, "count": 0},
                )
            )
            stack.enter_context(patch.object(trade, "_manual_two_city_active_leg", return_value=self.leg))
            stack.enter_context(patch.object(trade, "_append_user_log"))
            stack.enter_context(patch.object(trade, "_json_payload"))

            ok = trade.ManualTwoCityBusinessRouteItemUsedAction().run(None, None)
            enabled, key = trade._manual_two_city_route_item_enabled("speed_projectile")

        self.assertTrue(ok)
        self.assertFalse(enabled)
        self.assertEqual(key, "auto_use_speed_projectile")
        self.assertTrue(state["speed_projectile_unavailable"])
        self.assertTrue(state["speed_projectile_unavailable_logged"])

    def test_auto_pickup_is_wired_into_both_business_tasks(self) -> None:
        pipeline_path = ROOT / "assets" / "resource" / "base" / "pipeline" / "business" / "trade" / "manual_two_city_business.json"
        manual_task_path = ROOT / "assets" / "resource" / "tasks" / "ManualTwoCityBusiness.json"
        auto_task_path = ROOT / "assets" / "resource" / "tasks" / "AutoTwoCityBusiness.json"
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        manual_task = json.loads(manual_task_path.read_text(encoding="utf-8"))
        auto_task = json.loads(auto_task_path.read_text(encoding="utf-8"))

        self.assertEqual(
            pipeline["ManualTwoCityBusinessSetAutoSpeedProjectile"]["next"],
            "ManualTwoCityBusinessSetAutoPickup",
        )
        pickup_node = pipeline["ManualTwoCityBusinessRouteAutoPickupAvailable"]
        self.assertEqual(
            pickup_node["recognition"]["param"]["custom_recognition"],
            "manual_two_city_business_auto_pickup_available",
        )
        self.assertEqual(pickup_node["action"]["type"], "Custom")
        self.assertEqual(pickup_node["action"]["param"]["custom_action"], "manual_two_city_business_auto_pickup_used")
        self.assertEqual(pickup_node["pre_delay"], 0)
        self.assertEqual(pickup_node["post_delay"], 0)
        self.assertEqual(pickup_node["next"], "ManualTwoCityBusinessTravelPickupContinue")
        self.assertEqual(pickup_node["on_error"], "ManualTwoCityBusinessTravelMonitor")
        continue_node = pipeline["ManualTwoCityBusinessTravelPickupContinue"]
        self.assertEqual(continue_node["recognition"]["type"], "DirectHit")
        self.assertEqual(continue_node["action"]["type"], "DoNothing")
        self.assertEqual(continue_node["pre_delay"], 0)
        self.assertEqual(continue_node["post_delay"], 0)
        self.assertEqual(continue_node["rate_limit"], 100)
        self.assertEqual(continue_node["next"], [
            "ManualTwoCityBusinessRouteSpeedProjectileEnabled",
            "ManualTwoCityBusinessTravelPickupProgressCheck",
            "ManualTwoCityBusinessRouteAutoPickupAvailable",
            "ManualTwoCityBusinessRouteImpactDrillEnabled",
            "ManualTwoCityBusinessTravelMonitor",
        ])
        progress_node = pipeline["ManualTwoCityBusinessTravelPickupProgressCheck"]
        self.assertEqual(progress_node["recognition"]["param"]["custom_recognition"],
                         "manual_two_city_business_pickup_progress_due")
        self.assertEqual(progress_node["action"]["param"]["custom_action"],
                         "manual_two_city_business_travel_stall_watchdog")
        self.assertEqual(progress_node["pre_delay"], 0)
        self.assertEqual(progress_node["post_delay"], 0)
        self.assertEqual(progress_node["next"], "ManualTwoCityBusinessTravelStallDispatch")
        self.assertEqual(progress_node["on_error"], "ManualTwoCityBusinessTravelPickupContinue")
        self.assertNotIn("ManualTwoCityBusinessRouteAutoPickupUsed", pipeline)
        startup_next = pipeline["ManualTwoCityBusinessStartupTravelRecover"]["next"]
        self.assertEqual(startup_next[0], "ManualTwoCityBusinessRouteAutoPickupAvailable")
        self.assertLess(
            startup_next.index("ManualTwoCityBusinessRouteAutoPickupAvailable"),
            startup_next.index("ManualTwoCityBusinessRouteSpeedProjectileEnabled"),
        )
        monitor_next = pipeline["ManualTwoCityBusinessTravelMonitor"]["next"]
        self.assertEqual(monitor_next[0], "ManualTwoCityBusinessRouteAutoPickupAvailable")
        self.assertLess(
            monitor_next.index("ManualTwoCityBusinessRouteAutoPickupAvailable"),
            monitor_next.index("ManualTwoCityBusinessRouteSpeedProjectileEnabled"),
        )
        self.assertLess(
            monitor_next.index("ManualTwoCityBusinessRouteAutoPickupAvailable"),
            monitor_next.index("ManualTwoCityBusinessTravelStallWatchdog"),
        )
        train_recovery = pipeline["ManualTwoCityBusinessTrainManageScreenRecovery"]
        self.assertEqual(train_recovery["action"]["param"]["target"], [80, 38])
        self.assertIn(
            "ManualTwoCityBusinessTrainManageScreenRecovery",
            pipeline["ManualTwoCityBusinessFightMonitor"]["next"],
        )
        self.assertIn("ManualTwoCityAutoPickup", manual_task["task"][0]["option"])
        self.assertIn("ManualTwoCityAutoPickup", auto_task["task"][0]["option"])
        self.assertEqual(manual_task["option"]["ManualTwoCityAutoPickup"]["default_case"], "No")

    def test_high_level_city_departure_dialog_is_handled_in_order(self) -> None:
        pipeline_path = ROOT / "assets" / "resource" / "base" / "pipeline" / "business" / "trade" / "manual_two_city_business.json"
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))

        departure_candidates = pipeline["ManualTwoCityBusinessTapGoDestination"]["next"]
        high_level_node_name = "ManualTwoCityBusinessTapHighLevelDepartDoNotRemind"
        self.assertLess(
            departure_candidates.index(high_level_node_name),
            departure_candidates.index("ManualTwoCityBusinessTapDepartNow"),
        )

        high_level_node = pipeline[high_level_node_name]
        self.assertEqual(
            high_level_node["recognition"]["param"]["expected"],
            "目标站点任务难度较高",
        )
        self.assertEqual(high_level_node["action"]["param"]["target"], [585, 585])
        self.assertEqual(
            high_level_node["next"],
            "ManualTwoCityBusinessTapHighLevelDepartConfirm",
        )

        confirm_node = pipeline["ManualTwoCityBusinessTapHighLevelDepartConfirm"]
        self.assertEqual(confirm_node["recognition"]["param"]["expected"], "确认")
        confirm_roi = confirm_node["recognition"]["param"]["roi"]
        self.assertGreaterEqual(confirm_roi[0], 640)
        self.assertLessEqual(confirm_roi[0] + confirm_roi[2], 1280)
        self.assertEqual(
            confirm_node["next"],
            [
                "ManualTwoCityBusinessTravelStarted",
                "ManualTwoCityBusinessDepartFatiguePopup",
            ],
        )

    def test_visit_region_city_entry_is_recognized_everywhere(self) -> None:
        pipeline_root = ROOT / "assets" / "resource" / "base" / "pipeline" / "business"
        trade_pipeline = json.loads(
            (pipeline_root / "trade" / "manual_two_city_business.json").read_text(encoding="utf-8")
        )
        state_recovery = json.loads(
            (pipeline_root / "common" / "state_recovery.json").read_text(encoding="utf-8")
        )
        cargo_profile = json.loads(
            (pipeline_root / "profile" / "account_profile_cargo.json").read_text(encoding="utf-8")
        )
        launch_game = json.loads(
            (pipeline_root / "common" / "launch_game.json").read_text(encoding="utf-8")
        )

        expected_lists = [
            trade_pipeline["ManualTwoCityBusinessOpenCurrentCityByOcr"]["recognition"]["param"]["expected"],
            trade_pipeline["ManualTwoCityBusinessArrivedMainMap"]["recognition"]["param"]["expected"],
            state_recovery["StateRecoveryEnterArrivedCity"]["recognition"]["param"]["expected"],
            cargo_profile["AccountProfileCargoCapacityStart"]["recognition"]["param"]["expected"],
            launch_game["LaunchGameAlreadyRunningByOcr"]["recognition"]["param"]["expected"],
        ]
        for expected in expected_lists:
            self.assertIn("访问地区", expected)

        city_unlock_pipeline = json.loads(
            (pipeline_root / "profile" / "account_profile_city_unlock.json").read_text(encoding="utf-8")
        )
        panel_nodes = [
            node
            for name, node in city_unlock_pipeline.items()
            if name.endswith("PanelOcr")
        ]
        self.assertGreater(len(panel_nodes), 0)
        for node in panel_nodes:
            self.assertIn("访问地区", node["recognition"]["param"]["expected"])

    def test_city_unlock_cache_is_loaded_from_current_uid_account(self) -> None:
        account = {
            "uid": "8810002570",
            "trade": {
                "city_unlock_probe": {
                    "岚心城": {
                        "status": "unavailable",
                        "texts": ["驭照等级60级开放"],
                    }
                }
            },
        }
        with ExitStack() as stack:
            stack.enter_context(patch.object(trade, "_current_profile_uid", return_value="8810002570"))
            load_account = stack.enter_context(patch.object(trade, "_load_account_config", return_value=account))
            stack.enter_context(patch.object(trade, "_trade_wulinyuan_disabled", return_value=False))

            state = trade._initial_city_unlock_state_from_saved()

        load_account.assert_called_once_with("8810002570")
        self.assertEqual(state["city_unlock_probe"]["岚心城"]["status"], "unavailable")
        self.assertIn("岚心城", state["unavailable_cities"])

    def test_legacy_city_unlock_cache_without_uid_evidence_forces_rescan(self) -> None:
        account = {
            "uid": "8810002570",
            "trade": {
                "available_cities": list(trade.CITY_UNLOCK_TARGETS),
                "unavailable_cities": [],
            },
            "account_profile_read": {"last_smart_scan_date": "2099-01-01"},
        }
        state = {
            "result": {"uid": "8810002570"},
            "account_identity_confirmed": True,
            "account_identity_uid": "8810002570",
        }
        with patch.object(
            trade,
            "_manual_two_city_known_account_context",
            return_value=(Path("config/accounts/8810002570.json"), account, "8810002570", True),
        ):
            status = trade._manual_two_city_smart_scan_status(state, trade.MANUAL_TWO_CITY_SMART_SCAN_DAILY)

        self.assertTrue(status["due"])
        self.assertEqual(status["reason"], "missing_uid_scoped_city_unlock_probe")
        self.assertIn("岚心城", status["missing_city_unlock_cities"])

    def test_locked_city_requirement_is_classified_as_unavailable(self) -> None:
        self.assertEqual(
            trade.classify_city_unlock_probe(["岚心城", "声望：0级", "驭照等级60级开放"]),
            "unavailable",
        )

    def test_unavailable_destination_is_checked_before_depart_and_replanned(self) -> None:
        pipeline_path = ROOT / "assets" / "resource" / "base" / "pipeline" / "business" / "trade" / "manual_two_city_business.json"
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        move_next = pipeline["ManualTwoCityBusinessMoveToDestination"]["next"]
        self.assertLess(
            move_next.index("ManualTwoCityBusinessDestinationUnavailable"),
            move_next.index("ManualTwoCityBusinessTapGoDestination"),
        )
        unavailable = pipeline["ManualTwoCityBusinessDestinationUnavailable"]
        self.assertIn("驭照等级", unavailable["recognition"]["param"]["expected"])
        self.assertEqual(
            unavailable["action"]["param"]["custom_action"],
            "manual_two_city_business_destination_unavailable",
        )

        state = {
            "task_entry": trade.AUTO_TWO_CITY_TASK_ENTRY,
            "auto_route_enabled": True,
            "auto_route_params": {
                "uid": "8810002570",
                "priority_cities": ["岚心城"],
                "exclude_cities": ["武林源"],
                "max_restock": 6,
            },
            "result": {"uid": "8810002570"},
            "current_city": "云岫桥基地",
            "initial_transfer_in_progress": True,
            "initial_transfer_source_city": "云岫桥基地",
            "recovery_attempt_counts": {"depart": 2},
        }
        new_result = {
            "uid": "8810002570",
            "start_city": "修格里城",
            "target_city": "7号自由港",
            "start_book": 3,
            "target_book": 3,
            "start_bargain_percent": 20,
            "start_raise_percent": 20,
            "target_bargain_percent": 20,
            "target_raise_percent": 20,
            "summary": {
                "legs": [
                    {"buy_city": "修格里城", "sell_city": "7号自由港"},
                    {"buy_city": "7号自由港", "sell_city": "修格里城"},
                ]
            },
        }
        with ExitStack() as stack:
            stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=state))
            calculate = stack.enter_context(
                patch.object(trade, "calculate_auto_two_city_trade", return_value=new_result)
            )
            stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_choose_initial_transfer_destination",
                    return_value={"city": "修格里城", "fatigue": 40, "estimated": False},
                )
            )
            stack.enter_context(patch.object(trade, "save_manual_two_city_result", return_value=Path("result.json")))

            replan = trade._manual_two_city_replan_after_unavailable_destination("岚心城")

        self.assertTrue(replan["ok"])
        calculate_params = calculate.call_args.kwargs
        self.assertIn("岚心城", calculate_params["exclude_cities"])
        self.assertNotIn("岚心城", calculate_params["priority_cities"])
        self.assertEqual(state["initial_transfer_destination_city"], "修格里城")
        self.assertTrue(state["destination_unavailable_replan_ready"])
        self.assertEqual(state["recovery_attempt_counts"]["depart"], 0)

    def test_truncated_product_lot_retries_enhanced_ocr(self) -> None:
        digit_rois = [[578, 222, 56, 25], [572, 204, 74, 35]]
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_product_icon_lot_row_roi",
                    return_value=[560, 206, 92, 68],
                )
            )
            stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_product_icon_lot_digit_rois",
                    return_value=digit_rois,
                )
            )
            direct = stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_direct_digit_lot_ocr",
                    side_effect=[{"buy_lot": 1}, {"buy_lot": 11}],
                )
            )
            scaled = stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_scaled_digit_lot_ocr",
                    return_value={"buy_lot": 1},
                )
            )

            result = trade._manual_two_city_read_product_icon_lot_by_row(
                None,
                1,
                1,
                "岚心锦服",
                167.5,
                image=object(),
                expected_lot=9,
            )

        self.assertEqual(result["buy_lot"], 11)
        self.assertEqual(direct.call_count, 2)
        self.assertEqual(scaled.call_count, 2)
        first_attempt = result["digit_roi_attempts"][0]
        self.assertFalse(first_attempt["direct_digit_ocr"]["plausible"])
        self.assertFalse(first_attempt["scaled_digit_ocr"]["plausible"])

    def test_scaled_product_lot_prefers_plausible_variant(self) -> None:
        import numpy as np

        truncated = [{"text": "1", "x": 0, "y": 0, "w": 20, "h": 20, "center_x": 10, "center_y": 10}]
        complete = [{"text": "11", "x": 0, "y": 0, "w": 24, "h": 20, "center_x": 12, "center_y": 10}]
        with patch.object(
            trade,
            "_manual_two_city_ocr_entries_from_image",
            side_effect=[
                (True, truncated, ["1"]),
                (True, complete, ["11"]),
                (False, [], []),
                (False, [], []),
            ],
        ) as ocr:
            result = trade._manual_two_city_scaled_digit_lot_ocr(
                None,
                "TradeRuntimeFix",
                np.zeros((30, 70, 3), dtype=np.uint8),
                [0, 0, 56, 25],
                expected_lot=9,
            )

        self.assertEqual(result["buy_lot"], 11)
        self.assertEqual(result["source"], "contrast")
        self.assertEqual(ocr.call_count, 4)
        self.assertFalse(result["variants"][0]["plausible"])
        self.assertTrue(result["variants"][1]["plausible"])

    def test_product_lot_candidate_consensus_rejects_conflict(self) -> None:
        selected = trade._manual_two_city_select_product_lot_candidates(
            [
                {"value": 1, "source": "direct:1"},
                {"value": 11, "source": "direct:2"},
                {"value": 11, "source": "scaled:contrast"},
            ],
            9,
        )
        self.assertEqual(selected["buy_lot"], 11)
        self.assertEqual(selected["reason"], "candidate_consensus")

        conflict = trade._manual_two_city_select_product_lot_candidates(
            [
                {"value": 11, "source": "direct:1"},
                {"value": 12, "source": "direct:2"},
            ],
            9,
        )
        self.assertIsNone(conflict["buy_lot"])
        self.assertEqual(conflict["reason"], "candidate_conflict")

    def test_saved_product_lot_fallback_is_narrow_and_trusted(self) -> None:
        completion = {
            "missing_tax_rate": False,
            "missing_observed_buy_lot_goods": ["岚心锦服"],
            "saved_product_buy_lots": {"岚心锦服": 9},
        }
        self.assertEqual(
            trade._manual_two_city_safe_saved_buy_lot_fallbacks(
                completion,
                {"岚心锦服": 9},
            ),
            {"岚心锦服": 9},
        )
        completion["saved_product_buy_lots"] = {"岚心锦服": 1}
        self.assertEqual(
            trade._manual_two_city_safe_saved_buy_lot_fallbacks(
                completion,
                {"岚心锦服": 9},
            ),
            {},
        )
        completion.update(
            {
                "missing_observed_buy_lot_goods": ["岚心锦服", "黑毛牛排"],
                "saved_product_buy_lots": {"岚心锦服": 9, "黑毛牛排": 19},
            }
        )
        self.assertEqual(
            trade._manual_two_city_safe_saved_buy_lot_fallbacks(
                completion,
                {"岚心锦服": 9, "黑毛牛排": 19},
            ),
            {},
        )
        completion.update(
            {
                "missing_observed_buy_lot_goods": ["岚心锦服"],
                "saved_product_buy_lots": {"岚心锦服": 12},
            }
        )
        self.assertEqual(
            trade._manual_two_city_safe_saved_buy_lot_fallbacks(
                completion,
                {"岚心锦服": 9},
            ),
            {},
        )

    def test_product_scan_degrades_without_marking_saved_value_fresh(self) -> None:
        state = {
            "run_id": "trade-runtime-fix",
            "product_scan_city": "岚心城",
            "product_scan_targets": ["岚心锦服", "黑毛牛排"],
            "product_scan_statuses": {"岚心锦服": "normal", "黑毛牛排": "normal"},
            "product_scan_buy_lots": {"黑毛牛排": 22},
            "product_scan_expected_buy_lots": {"岚心锦服": 9, "黑毛牛排": 19},
            "product_scan_tax_rate": 0.05,
            "product_scan_city_trade_due": True,
            "product_scan_missing_trade_field_retry_count": 2,
            "product_scan_completed_cities": [],
        }
        completion = {
            "complete": False,
            "required_buy_lot_goods": ["岚心锦服", "黑毛牛排"],
            "missing_buy_lot_goods": ["岚心锦服"],
            "missing_observed_buy_lot_goods": ["岚心锦服"],
            "missing_effective_buy_lot_goods": [],
            "saved_fallback_buy_lot_goods": ["岚心锦服"],
            "saved_product_buy_lots": {"岚心锦服": 9, "黑毛牛排": 19},
            "missing_tax_rate": False,
            "effective_city_tax_rate": 0.05,
        }
        with ExitStack() as stack:
            stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=state))
            stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_update_city_product_statuses",
                    return_value={"changed": False},
                )
            )
            stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_city_trade_completion",
                    return_value=completion,
                )
            )
            observation = stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_update_city_trade_observation",
                    return_value={"changed": True},
                )
            )
            recalculate = stack.enter_context(
                patch.object(trade, "_manual_two_city_recalculate_after_product_scan", return_value=True)
            )
            stack.enter_context(patch.object(trade, "_append_user_log"))
            stack.enter_context(patch.object(trade, "_json_payload"))

            ok = trade.ManualTwoCityBusinessProductScanCompleteAction().run(None, None)

        self.assertTrue(ok)
        observation.assert_called_once()
        self.assertEqual(observation.call_args.kwargs["product_buy_lots"], {"黑毛牛排": 22})
        self.assertFalse(observation.call_args.kwargs["mark_read"])
        self.assertEqual(
            state["product_scan_degraded_trade_fallbacks"]["岚心城"]["product_buy_lots"],
            {"岚心锦服": 9},
        )
        self.assertIn("岚心城", state["product_scan_completed_cities"])
        self.assertFalse(state["product_scan_retry_missing_trade_fields"]["needed"])
        recalculate.assert_called_once_with("岚心城")

    def test_cargo_load_ocr_excludes_haggle_and_retries_until_stable(self) -> None:
        compact_entries = [
            {"text": "711300", "x": 1180, "y": 386, "w": 65, "h": 19},
            {"text": "砍价", "x": 905, "y": 444, "w": 45, "h": 20},
            {"text": "1+8", "x": 1207, "y": 451, "w": 25, "h": 12},
        ]
        compact = trade._manual_two_city_parse_buy_page_cargo_load(
            compact_entries,
            roi=trade.BUY_PAGE_CARGO_LOAD_PROBE_ROI,
        )
        self.assertEqual((compact["used"], compact["capacity"]), (7, 1300))

        selected_entries = [
            {"text": "7+1177", "x": 1136, "y": 388, "w": 57, "h": 16},
            {"text": "11300", "x": 1195, "y": 388, "w": 50, "h": 16},
            {"text": "1+8", "x": 1207, "y": 451, "w": 25, "h": 12},
        ]
        selected = trade._manual_two_city_parse_buy_page_cargo_load(
            selected_entries,
            roi=trade.BUY_PAGE_CARGO_LOAD_PROBE_ROI,
        )
        self.assertEqual((selected["used"], selected["capacity"]), (1184, 1300))

        with patch.object(
            trade,
            "_manual_two_city_probe_buy_page_cargo_load",
            side_effect=[
                ({"used": 9, "capacity": 1300, "priority": 4}, ["711300", "1+8"]),
                ({"used": 1184, "capacity": 1300, "priority": 4}, ["7+1177", "1300"]),
            ],
        ) as probe:
            cargo_load, texts, samples = trade._manual_two_city_probe_buy_page_cargo_load_with_retry(
                None,
                "TradeRuntimeFix",
                expected_capacity=1300,
                minimum_used=1170,
                attempts=3,
                delay=0,
            )
        self.assertEqual((cargo_load["used"], cargo_load["capacity"]), (1184, 1300))
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(len(samples), 2)
        self.assertIn("7+1177", texts)

    def test_quick_buy_cancel_is_verified_before_fallback(self) -> None:
        cancel_entry = {"text": "全部取消", "center_x": 1196, "center_y": 102}
        with ExitStack() as stack:
            ocr = stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_ocr_entries",
                    side_effect=[
                        (True, [cancel_entry], ["全部取消"]),
                        (True, [], ["全部买入"]),
                    ],
                )
            )
            click = stack.enter_context(patch.object(trade, "_manual_two_city_click"))
            cleared, texts = trade._manual_two_city_clear_top_all_buy_selection(None, "TradeRuntimeFix")
        self.assertTrue(cleared)
        self.assertEqual(ocr.call_count, 2)
        click.assert_called_once_with(None, (1196, 102), 0.55)
        self.assertEqual(texts, ["全部取消", "全部买入"])

    def _patch_runtime(self, stack: ExitStack, state: dict, ocr) -> tuple[Mock, list[tuple[int, int]]]:
        logs = Mock()
        clicks: list[tuple[int, int]] = []
        stack.enter_context(patch.object(trade, "_manual_two_city_state", side_effect=lambda reset=False: state))
        stack.enter_context(patch.object(trade, "_manual_two_city_active_leg", return_value=self.leg))
        stack.enter_context(patch.object(trade, "_manual_two_city_ocr_entries", side_effect=ocr))
        stack.enter_context(patch.object(trade, "_manual_two_city_click", side_effect=lambda _context, target, _delay: clicks.append(target)))
        stack.enter_context(patch.object(trade, "_manual_two_city_click_ocr_text", return_value=(True, [])))
        stack.enter_context(patch.object(trade, "_append_user_log", logs))
        stack.enter_context(patch.object(trade, "_json_payload"))
        return logs, clicks

    def test_uses_available_books_once_per_leg(self) -> None:
        state = {"completed_rounds": 0, "active_leg_index": 1}
        book_entries = [
            {"text": "进货采买书", "center_x": 731, "center_y": 166},
            {"text": "2", "center_x": 664, "center_y": 191},
        ]

        def fake_ocr(_context, _name, expected, **_kwargs):
            if expected == trade.BUY_BOOK_MENU_TEXTS:
                return True, book_entries, ["进货采买书", "2"]
            if expected == trade.BUY_BOOK_POPUP_TEXTS:
                return True, [], ["是否使用", "确认"]
            if expected == trade.BUY_PAGE_READY_TEXTS:
                return True, [], ["全部买入"]
            return False, [], []

        with ExitStack() as stack:
            logs, clicks = self._patch_runtime(stack, state, fake_ocr)
            action = trade.ManualTwoCityBusinessUseBuyBooksAction()
            self.assertTrue(action.run(None, None))
            usage = trade._manual_two_city_buy_book_usage(state, self.leg)
            self.assertEqual(usage["requested"], 3)
            self.assertEqual(usage["used"], 2)
            self.assertEqual(usage["used_batches"], [2])
            first_click_count = len(clicks)
            self.assertTrue(action.run(None, None))
            self.assertEqual(len(clicks), first_click_count)
            self.assertIn(
                "manual_two_city_buy_books_retry_skipped",
                [call.kwargs.get("event") for call in logs.call_args_list],
            )

    def test_zero_books_allows_verified_partial_cargo(self) -> None:
        state = {"completed_rounds": 0, "active_leg_index": 1}
        zero_entries = [
            {"text": "进货采买书", "center_x": 731, "center_y": 166},
            {"text": "0", "center_x": 664, "center_y": 191},
        ]

        def fake_ocr(_context, _name, expected, **_kwargs):
            if expected == trade.BUY_BOOK_MENU_TEXTS:
                return True, zero_entries, ["进货采买书", "0"]
            if expected == trade.BUY_PAGE_READY_TEXTS:
                return True, [], ["全部买入"]
            return False, [], []

        with ExitStack() as stack:
            self._patch_runtime(stack, state, fake_ocr)
            probe = stack.enter_context(
                patch.object(
                    trade,
                    "_manual_two_city_probe_buy_page_cargo_load",
                    return_value=({"used": 1107, "capacity": 1300, "ratio": 1107 / 1300}, ["1107/1300"]),
                )
            )
            stack.enter_context(patch.object(trade, "_ocr_texts", return_value=["全部取消", "1107/1300"]))

            self.assertTrue(trade.ManualTwoCityBusinessUseBuyBooksAction().run(None, None))
            usage = trade._manual_two_city_buy_book_usage(state, self.leg)
            self.assertEqual((usage["requested"], usage["used"]), (3, 0))
            state["selected_buy_goods"] = list(self.goods)
            state["selected_buy_goods_actual_load"] = {good: 1 for good in self.goods}
            self.assertTrue(trade.ManualTwoCityBusinessConfirmBuySelectionAction().run(None, None))
            state["buy_selection_verified_cargo_load"] = {"used": 1107, "capacity": 1300, "ratio": 1107 / 1300}
            self.assertTrue(trade.ManualTwoCityBusinessVerifyCargoAfterBuyAction().run(None, None))
            self.assertGreaterEqual(probe.call_count, 2)


if __name__ == "__main__":
    unittest.main()

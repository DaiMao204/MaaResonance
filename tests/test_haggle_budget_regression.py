from __future__ import annotations

import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_trade_runtime_fix import trade


class HaggleBudgetRegressionTest(unittest.TestCase):
    def _patch_action(self, stack: ExitStack, state: dict, popup):
        stack.enter_context(patch.object(trade, "_manual_two_city_state", return_value=state))
        stack.enter_context(
            patch.object(trade, "_manual_two_city_active_leg", return_value={"buy_city": "A", "sell_city": "B"})
        )
        stack.enter_context(patch.object(trade, "_manual_two_city_buy_bargain_percent", return_value=20))
        stack.enter_context(patch.object(trade, "_manual_two_city_sell_raise_percent", return_value=20))
        popup_mock = None
        if popup is not None:
            popup_mock = stack.enter_context(
                patch.object(trade, "_manual_two_city_confirm_buy_haggle_book_popup", side_effect=popup)
            )
        stack.enter_context(patch.object(trade, "_manual_two_city_read_buy_haggle_percent", return_value=12.2))
        stack.enter_context(patch.object(trade, "_manual_two_city_click_ocr_text", return_value=(True, ["议价"])))
        cancel = stack.enter_context(
            patch.object(trade, "_manual_two_city_cancel_haggle_book_popup", return_value=(True, ["取消"]))
        )
        stack.enter_context(patch.object(trade.time, "perf_counter", return_value=0))
        stack.enter_context(patch.object(trade, "_append_user_log"))
        stack.enter_context(patch.object(trade, "_ocr_texts", return_value=[]))
        payload = stack.enter_context(patch.object(trade, "_json_payload"))
        return popup_mock, cancel, payload

    def test_sent_confirmation_keeps_budget_when_verification_fails(self):
        popup_texts = ["是否使用再交涉请求书重新议价?", "10/1", "确认"]
        for action_type in (
            trade.ManualTwoCityBusinessApplyBuyHaggleAction,
            trade.ManualTwoCityBusinessApplySellHaggleAction,
        ):
            for verification_raises in (False, True):
                with self.subTest(action=action_type.__name__, raises=verification_raises), ExitStack() as stack:
                    state = {"use_haggle_book": True}
                    _, _, payload = self._patch_action(stack, state, None)
                    ocr_results = [
                        (True, [], popup_texts),
                        RuntimeError("verification failed") if verification_raises else (True, [], popup_texts),
                        (True, [], popup_texts),
                    ]
                    stack.enter_context(patch.object(trade, "_manual_two_city_ocr_entries", side_effect=ocr_results))
                    confirm = stack.enter_context(
                        patch.object(trade, "_manual_two_city_click_ocr_text", return_value=(True, ["确认"]))
                    )
                    self.assertEqual(action_type().run(None, None), not verification_raises)
                    confirm.assert_called_once()

                    # The game may have applied the first click; recovery must not send another.
                    self.assertTrue(action_type().run(None, None))
                    confirm.assert_called_once()
                    self.assertEqual(payload.call_args.args[1]["haggle_books_used"], 1)
                    self.assertEqual(payload.call_args.args[1]["stop_reason"], "book_limit_reached")

    def test_no_reservation_without_a_usable_enabled_popup(self):
        for popup_hit, allow_confirm, inventory in ((False, True, "10/1"), (True, False, "10/1"), (True, True, "0/1")):
            with self.subTest(hit=popup_hit, enabled=allow_confirm, inventory=inventory), ExitStack() as stack:
                budget = {"used": 0}
                stack.enter_context(
                    patch.object(trade, "_manual_two_city_ocr_entries", return_value=(popup_hit, [], [inventory, "请求书"]))
                )
                confirm = stack.enter_context(patch.object(trade, "_manual_two_city_click_ocr_text"))
                trade._manual_two_city_confirm_buy_haggle_book_popup(
                    None,
                    leg={},
                    target_percent=20,
                    current_percent=12.2,
                    click_count=1,
                    probe_name="BudgetNotReserved",
                    allow_confirm=allow_confirm,
                    book_budget=budget,
                )
                self.assertEqual(budget["used"], 0)
                confirm.assert_not_called()

    def test_recovery_after_cancel_failure_keeps_spent_book_budget(self):
        for action_type in (
            trade.ManualTwoCityBusinessApplyBuyHaggleAction,
            trade.ManualTwoCityBusinessApplySellHaggleAction,
        ):
            for after_click in (False, True):
                with self.subTest(action=action_type.__name__, after_click=after_click), ExitStack() as stack:
                    state = {"use_haggle_book": True}
                    outcomes = ([{"status": "absent"}] if after_click else []) + [
                        {"status": "confirmed"},
                        {"status": "skipped"},
                    ]
                    popup, cancel, payload = self._patch_action(stack, state, outcomes)
                    cancel.return_value = (False, ["取消失败"])
                    self.assertFalse(action_type().run(None, None))

                    # Recovery can change route metadata without completing this trade.
                    state.update(active_leg_index=1, current_city="B", recovery_resumed_target="sell_page")
                    popup.reset_mock(side_effect=True)
                    popup.return_value = {"status": "skipped"}
                    cancel.return_value = (True, ["取消"])
                    self.assertTrue(action_type().run(None, None))
                    self.assertEqual([call.kwargs["allow_confirm"] for call in popup.call_args_list], [False])
                    self.assertEqual(payload.call_args.args[1]["haggle_books_used"], 1)
                    self.assertEqual(payload.call_args.args[1]["stop_reason"], "book_limit_reached")

    def test_trade_confirmation_retry_does_not_consume_a_second_book(self):
        for action_type in (
            trade.ManualTwoCityBusinessApplyBuyHaggleAction,
            trade.ManualTwoCityBusinessApplySellHaggleAction,
        ):
            with self.subTest(action=action_type.__name__), ExitStack() as stack:
                state = {"use_haggle_book": True}
                consumed = []

                def popup_result(_context, **kwargs):
                    if kwargs["allow_confirm"]:
                        consumed.append(1)
                        return {"status": "confirmed"}
                    return {"status": "skipped"}

                self._patch_action(stack, state, popup_result)
                self.assertTrue(action_type().run(None, None))
                # The purchase/sale confirmation failed; no report has been seen.
                self.assertTrue(action_type().run(None, None))
                self.assertEqual(len(consumed), 1)

    def test_settlement_allows_one_book_in_each_new_trade(self):
        for action_type, report_type in (
            (trade.ManualTwoCityBusinessApplyBuyHaggleAction, trade.ManualTwoCityBusinessBuyReportReadyAction),
            (trade.ManualTwoCityBusinessApplySellHaggleAction, trade.ManualTwoCityBusinessSellReportReadyAction),
        ):
            with self.subTest(action=action_type.__name__), ExitStack() as stack:
                state = {"use_haggle_book": True}
                consumed = []

                def popup_result(_context, **kwargs):
                    if kwargs["allow_confirm"]:
                        consumed.append(1)
                        return {"status": "confirmed"}
                    return {"status": "skipped"}

                self._patch_action(stack, state, popup_result)
                # A cleanup sale and the later normal sale must get separate budgets.
                state.update(pre_buy_cleanup=True, pre_buy_cleanup_raise_percent=20)
                self.assertTrue(action_type().run(None, None))
                self.assertTrue(report_type().run(None, None))
                state.pop("pre_buy_cleanup")
                self.assertTrue(action_type().run(None, None))
                self.assertEqual(len(consumed), 2)

    def test_buy_and_sell_budgets_do_not_reset_each_other(self):
        state = {"use_haggle_book": True}
        consumed = []

        def popup_result(_context, **kwargs):
            if kwargs["allow_confirm"]:
                consumed.append(1)
                return {"status": "confirmed"}
            return {"status": "skipped"}

        with ExitStack() as stack:
            self._patch_action(stack, state, popup_result)
            self.assertTrue(trade.ManualTwoCityBusinessApplyBuyHaggleAction().run(None, None))
            self.assertTrue(trade.ManualTwoCityBusinessApplySellHaggleAction().run(None, None))
            self.assertTrue(trade.ManualTwoCityBusinessSellReportReadyAction().run(None, None))
            self.assertTrue(trade.ManualTwoCityBusinessApplyBuyHaggleAction().run(None, None))
            self.assertEqual(len(consumed), 2)


if __name__ == "__main__":
    unittest.main()

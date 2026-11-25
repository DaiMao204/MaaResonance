from __future__ import annotations

from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from maa_resonance.logic.clarity_recovery import (
    choose_clarity_card,
    find_clarity_popup_button,
    is_clarity_confirm_popup,
    parse_clarity_cards,
    parse_clarity_limits,
    parse_clarity_status,
    popup_reports_no_stock,
)


class ClarityRecoveryLogicTest(unittest.TestCase):
    def _sample_screen_entries(self) -> list[dict[str, object]]:
        return [
            {"text": "澄明度", "box": [169, 321, 173, 65]},
            {"text": "29/288", "box": [165, 398, 187, 71]},
            {"text": "请选择恢复方式", "box": [349, 349, 191, 36]},
            {"text": "剩余时间7天", "box": [54, 516, 100, 18]},
            {"text": "3", "box": [68, 627, 21, 18]},
            {"text": "仙人掌能量棒棒糖", "box": [193, 558, 143, 19]},
            {"text": "1", "box": [373, 627, 15, 10]},
            {"text": "仙人掌跳跳卷", "box": [493, 553, 104, 18]},
            {"text": "15", "box": [664, 627, 28, 16]},
            {"text": "仙人掌能量跳糖", "box": [793, 551, 121, 23]},
            {"text": "每日限购8/8", "box": [968, 518, 72, 15]},
            {"text": "桦石", "box": [1094, 557, 36, 21]},
        ]

    def test_parse_clarity_status(self) -> None:
        status = parse_clarity_status(self._sample_screen_entries())
        self.assertEqual(status, {"current": 29, "total": 288, "remaining_gap": 259})

    def test_parse_and_choose_prioritizes_time_limited_medicine_and_skips_huashi_by_default(self) -> None:
        cards = parse_clarity_cards(self._sample_screen_entries())
        self.assertEqual([c["count"] for c in cards], [3, 1, 15, 8])
        self.assertTrue(cards[0]["is_limited"])

        picked = choose_clarity_card(cards, allow_huashi=False)
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertEqual(picked["key"], "lollipop")

        # When lollipop is excluded, pick next smallest medicine (roll)
        picked_next = choose_clarity_card(cards, allow_huashi=False, excluded_keys={"lollipop"})
        self.assertIsNotNone(picked_next)
        assert picked_next is not None
        self.assertEqual(picked_next["key"], "roll")

        # When all medicines are exhausted, huashi is only chosen if allow_huashi=True
        all_meds = {"lollipop", "roll", "candy"}
        self.assertIsNone(choose_clarity_card(cards, allow_huashi=False, excluded_keys=all_meds))
        picked_huashi = choose_clarity_card(cards, allow_huashi=True, excluded_keys=all_meds)
        self.assertIsNotNone(picked_huashi)
        assert picked_huashi is not None
        self.assertEqual(picked_huashi["key"], "huashi")

    def test_zero_count_or_unavailable_card_is_skipped(self) -> None:
        entries = [
            {"text": "0", "box": [68, 627, 21, 18]},
            {"text": "仙人掌能量棒棒糖", "box": [193, 558, 143, 19]},
            {"text": "2", "box": [664, 627, 28, 16]},
            {"text": "仙人掌能量跳糖", "box": [793, 551, 121, 23]},
        ]
        cards = parse_clarity_cards(entries)
        picked = choose_clarity_card(cards, allow_huashi=False)
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertEqual(picked["key"], "candy")

    def test_popup_helpers(self) -> None:
        entries = [
            {"text": "请选择补充次数", "box": [520, 220, 200, 30]},
            {"text": "取消", "box": [300, 570, 60, 30]},
            {"text": "确定", "box": [970, 570, 60, 30]},
        ]
        self.assertFalse(popup_reports_no_stock(entries))
        self.assertEqual(find_clarity_popup_button(entries, kind="confirm"), (1000, 585))
        self.assertEqual(find_clarity_popup_button(entries, kind="cancel"), (330, 585))
        self.assertTrue(is_clarity_confirm_popup(entries))
        self.assertTrue(
            is_clarity_confirm_popup(
                [
                    {"text": "取消", "box": [324, 567, 50, 31]},
                    {"text": "最少", "box": [364, 461, 48, 31]},
                    {"text": "当前澄明度", "box": [453, 406, 85, 22]},
                    {"text": "确认", "box": [958, 566, 52, 32]},
                ]
            )
        )
        self.assertFalse(is_clarity_confirm_popup(self._sample_screen_entries()))
        self.assertTrue(popup_reports_no_stock([{"text": "库存不足", "box": [500, 350, 100, 30]}]))

    def test_limits_respect_disabled_quota_and_huashi_cap(self) -> None:
        cards = parse_clarity_cards(self._sample_screen_entries())
        limits = parse_clarity_limits(
            {
                "lollipop_use_limit": "1",
                "roll_use_limit": "0",
                "candy_use_limit": "-1",
                "huashi_use_limit": "12",  # capped at 8
            }
        )
        self.assertEqual(limits, {"lollipop": 1, "roll": 0, "candy": -1, "huashi": 8})

        first = choose_clarity_card(cards, limits=limits, used_counts={})
        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual(first["key"], "lollipop")

        # After lollipop reaches its 1-use quota and roll is 0, falls back to unlimited candy
        second = choose_clarity_card(cards, limits=limits, used_counts={"lollipop": 1})
        self.assertIsNotNone(second)
        assert second is not None
        self.assertEqual(second["key"], "candy")

        # All zero limits -> disabled / returns None
        all_zero = parse_clarity_limits({})
        self.assertIsNone(choose_clarity_card(cards, limits=all_zero, used_counts={}))

    def test_accepts_agent_ocr_entries_xywh_schema(self) -> None:
        # Matches exact dict shape returned by agent.utils.recognition._ocr_entries
        agent_entries = [
            {"text": "请选择恢复方式", "x": 350, "y": 349, "w": 188, "h": 36, "center_x": 444.0, "center_y": 367.0},
            {"text": "4/288", "x": 165, "y": 398, "w": 157, "h": 74, "center_x": 243.5, "center_y": 435.0},
            {"text": "剩余时间7天", "x": 53, "y": 512, "w": 99, "h": 22, "center_x": 102.5, "center_y": 523.0},
            {"text": "3", "x": 65, "y": 628, "w": 23, "h": 15, "center_x": 76.5, "center_y": 635.5},
            {"text": "仙人掌能量棒棒糖", "x": 193, "y": 554, "w": 148, "h": 23, "center_x": 267.0, "center_y": 565.5},
            {"text": "确定", "x": 970, "y": 570, "w": 60, "h": 30, "center_x": 1000.0, "center_y": 585.0},
        ]
        self.assertEqual(parse_clarity_status(agent_entries), {"current": 4, "total": 288, "remaining_gap": 284})
        cards = parse_clarity_cards(agent_entries)
        picked = choose_clarity_card(cards, limits={"lollipop": 3, "roll": 0, "candy": 0, "huashi": 0})
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertEqual(picked["key"], "lollipop")
        self.assertEqual(find_clarity_popup_button(agent_entries, kind="confirm"), (1000, 585))

    def test_unlimited_huashi_keeps_eight_use_cap(self) -> None:
        cards = parse_clarity_cards(self._sample_screen_entries())
        limits = parse_clarity_limits({"huashi_use_limit": -1})
        self.assertEqual(limits["huashi"], 8)
        self.assertEqual(choose_clarity_card(cards, limits=limits, used_counts={"huashi": 7})["key"], "huashi")
        self.assertIsNone(choose_clarity_card(cards, limits=limits, used_counts={"huashi": 8}))

    def run_recovery(self, limits, screens, used=None):
        from agent import clarity_recovery_action as recovery

        counts = dict(used or {})
        argv = SimpleNamespace(node_name="TestRecovery", task_detail=SimpleNamespace(task_id=71),
                               custom_action_param=limits)
        with (
            patch.dict(recovery._CLARITY_USED_BY_TASK, {71: counts}, clear=True),
            patch.object(recovery, "safe_screencap", return_value=object()),
            patch.object(recovery, "sleep_with_stop", return_value=True),
            patch.object(recovery, "ocr_roi", side_effect=screens),
            patch.object(recovery, "tap_point", return_value=True) as tap,
        ):
            ok = recovery.ClarityRecoveryAction().run(SimpleNamespace(), argv)
        return ok, [call.args[2] for call in tap.call_args_list], counts

    def test_unselected_popup_never_uses_a_quota(self) -> None:
        prompt = [{"text": "当前澄明度"}, {"text": "确认", "box": [970, 570, 60, 30]}]
        cancel = {"text": "取消", "box": [300, 570, 60, 30]}
        for limits in ({}, {"huashi_use_limit": 8}):
            for extra, taps in (([], []), ([cancel], [(330, 585)])):
                with self.subTest(limits=limits, cancel=bool(extra)):
                    self.assertEqual(self.run_recovery(limits, [prompt + extra]), (False, taps, {}))

    def test_untrusted_dialog_and_unreadable_result_never_count(self) -> None:
        screen = self._sample_screen_entries()
        cancel = {"text": "取消", "box": [300, 570, 60, 30]}
        buttons = [cancel, {"text": "确认", "box": [970, 570, 60, 30]}]
        limits = {"huashi_use_limit": 1}
        self.assertEqual(self.run_recovery(limits, [screen, buttons]),
                         (False, [(1085, 585), (330, 585)], {}))
        self.assertEqual(self.run_recovery(limits, [screen, buttons + [{"text": "当前澄明度"}], []]),
                         (False, [(1085, 585), (1000, 585)], {}))

    def test_mismatching_payment_item_cancels_at_every_confirmation(self) -> None:
        screen = self._sample_screen_entries()
        limits = {"lollipop_use_limit": 1}
        buttons = [{"text": "取消", "box": [300, 570, 60, 30]}, {"text": "确认", "box": [970, 570, 60, 30]}]
        matched = buttons + [{"text": "当前澄明度"}, {"text": "使用仙人掌能量棒棒糖", "box": [540, 300, 175, 30]}]
        wrong = buttons + [{"text": "当前澄明度"}, {"text": "消耗桦石", "box": [540, 300, 70, 30]}]
        self.assertEqual(self.run_recovery(limits, [screen, wrong]), (False, [(195, 585), (330, 585)], {}))
        self.assertEqual(self.run_recovery(limits, [screen, matched, wrong]),
                         (False, [(195, 585), (1000, 585), (330, 585)], {}))
        self.assertFalse(is_clarity_confirm_popup(screen))

    def test_partial_stale_dialog_does_not_select_a_card_behind_it(self) -> None:
        screen = self._sample_screen_entries() + [{"text": "当前澄明度"}]
        self.assertEqual(self.run_recovery({"huashi_use_limit": 2}, [screen]), (False, [], {}))

    def test_eighth_verified_use_counts_once_and_ninth_never_taps(self) -> None:
        screen = self._sample_screen_entries()
        confirmed = [dict(entry, text="每日限购7/8") if entry["text"] == "每日限购8/8" else entry for entry in screen]
        dialog = [{"text": "请选择补充次数"}, {"text": "确定", "box": [970, 570, 60, 30]}]
        limits = {"huashi_use_limit": -1}
        self.assertEqual(self.run_recovery(limits, [screen, dialog, confirmed], {"huashi": 7}),
                         (True, [(1085, 585), (1000, 585), (63, 32)], {"huashi": 8}))
        self.assertEqual(self.run_recovery(limits, [screen], {"huashi": 8}),
                         (False, [], {"huashi": 8}))

    def test_finished_task_releases_only_its_own_quota(self) -> None:
        sinks = []

        def register_sink(cls):
            sinks.append(cls())
            return cls

        events = SimpleNamespace(Starting=1, Succeeded=2, Failed=3)
        server = SimpleNamespace(custom_action=lambda name: lambda cls: cls, tasker_sink=lambda: register_sink)
        with patch.dict(sys.modules, {
            "maa.agent.agent_server": SimpleNamespace(AgentServer=server),
            "maa.context": SimpleNamespace(Context=object),
            "maa.custom_action": SimpleNamespace(CustomAction=object),
            "maa.event_sink": SimpleNamespace(NotificationType=events),
            "maa.tasker": SimpleNamespace(TaskerEventSink=object),
        }):
            module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "agent" / "clarity_recovery_action.py"))
        sink, = sinks
        counts = module["_CLARITY_USED_BY_TASK"]
        counts.update({71: {"roll": 1}, 72: {"huashi": 8}})
        task = SimpleNamespace(task_id=71)
        sink.on_tasker_task(None, events.Starting, task)
        self.assertEqual(counts, {71: {"roll": 1}, 72: {"huashi": 8}})
        sink.on_tasker_task(None, events.Succeeded, task)
        self.assertEqual(counts, {72: {"huashi": 8}})
        sink.on_tasker_task(None, events.Failed, SimpleNamespace(task_id=72))
        self.assertEqual(counts, {})


if __name__ == "__main__":
    unittest.main()

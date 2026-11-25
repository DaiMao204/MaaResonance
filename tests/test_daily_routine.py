from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from maa_resonance.logic.daily_routine import (
    ACTIVITY_CHEST_XS,
    DRAWER_FRIEND_ICON_POINT,
    LOBBY_REVENUE_PILL_POINT,
    PASS_SIDEBAR_ROI,
    PASS_TITLE_ROI,
    REVENUE_LIKE_BTN_X,
    REVENUE_LIKE_ROW_YS,
    REVENUE_RANKING_STAMP_POINT,
    REWARD_POPUP_TOP_SAFE_POINT,
    classify_activity_chest,
    classify_leaderboard_like_slot,
    find_all_players_tab_point,
    find_battle_pass_claim_all_point,
    find_battle_pass_daily_tab_point,
    find_battle_pass_rewards_tab_point,
    find_battle_pass_sidebar_cards,
    find_battle_pass_single_claim_point,
    find_battle_pass_tasks_tab_point,
    find_battle_pass_weekly_tab_point,
    find_claimable_activity_chests,
    find_completed_dispatch_card_point,
    find_daily_activity_claim_point,
    find_daily_activity_tab_point,
    find_dispatch_claim_button_point,
    find_dispatch_report_action_point,
    find_drawer_entry_point,
    find_eternal_supply_claim_point,
    find_event_checkin_first_card_point,
    find_friend_support_coin_point,
    find_lobby_revenue_pill_point,
    find_mail_claim_all_point,
    find_revenue_ranking_stamp_point,
    find_unliked_leaderboard_points,
    has_friend_support_coin_bubble,
    has_like_limit_toast,
    has_mall_tab_red_dot,
    has_reward_popup_entries,
    images_differ_in_roi,
    is_all_players_tab_selected,
    is_battle_pass_daily_tab_selected,
    is_battle_pass_rewards_tab_selected,
    is_battle_pass_screen_entries,
    is_battle_pass_tasks_tab_selected,
    is_battle_pass_title_visited,
    is_battle_pass_weekly_tab_selected,
    is_daily_activity_panel_entries,
    is_daily_activity_tab_active,
    is_dispatch_report_entries,
    is_dispatch_screen_entries,
    is_drawer_entries,
    is_eternal_supply_page_entries,
    is_event_checkin_first_card_highlighted,
    is_event_checkin_screen_entries,
    is_friend_card_screen_entries,
    is_lobby_entries,
    is_mail_screen_entries,
    is_mall_top_bar_entries,
    is_revenue_ranking_entries,
    is_revenue_report_entries,
    is_tiger_wealth_ranking_entries,
    is_top_home_button_visible,
    parse_battle_pass_title,
    parse_daily_activity_score,
    parse_drawer_uid,
    parse_like_progress,
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


class DailyRoutineLogicTest(unittest.TestCase):
    def test_lobby_and_drawer_do_not_collide(self) -> None:
        # Both _ocr_entries (x/y/w/h/center_x/center_y) and box: [x,y,w,h] formats are supported.
        lobby_bottom = [
            {"text": "整备列车", "x": 934, "y": 694, "w": 43, "h": 15, "center_x": 955.5, "center_y": 701.5},
            {"text": "客运管理", "box": [1002, 694, 42, 15]},
        ]
        self.assertTrue(is_lobby_entries(lobby_bottom))
        self.assertFalse(is_drawer_entries(lobby_bottom))

        drawer = [
            {"text": "查看更多信息", "box": [344, 300, 84, 18]},
            {"text": "委托", "x": 250, "y": 420, "w": 38, "h": 22, "center_x": 269, "center_y": 431},
            {"text": "营运总览", "box": [349, 420, 68, 22]},
            {"text": "导航手册", "box": [462, 422, 68, 21]},
            {"text": "客运管理", "box": [576, 648, 68, 21]},
        ]
        self.assertTrue(is_drawer_entries(drawer))
        self.assertFalse(is_lobby_entries([], []))
        self.assertEqual(find_drawer_entry_point(drawer, ("委托",)), (269, 431))
        self.assertEqual(find_drawer_entry_point(drawer, ("营运总览", "运营总览")), (383, 431))
        self.assertEqual(find_drawer_entry_point(drawer, ("导航手册",)), (496, 432))

        pill = [{"text": "TODAY", "box": [1105, 546, 37, 13]}]
        self.assertEqual(find_lobby_revenue_pill_point(pill), LOBBY_REVENUE_PILL_POINT)
        self.assertIsNone(find_lobby_revenue_pill_point([{"text": "4529885", "box": [1105, 558, 85, 24]}]))

    def test_mail_and_reward_popup_parsers(self) -> None:
        bottom = [
            {"text": "删除已读", "box": [770, 655, 86, 27]},
            {"text": "一键领取", "box": [1026, 653, 84, 29]},
        ]
        self.assertTrue(is_mail_screen_entries(bottom))
        self.assertEqual(find_mail_claim_all_point(bottom), (1068, 668))
        # Must never select 删除已读 when 一键领取 is missing.
        self.assertIsNone(find_mail_claim_all_point([{"text": "删除已读", "box": [770, 655, 86, 27]}]))

        self.assertTrue(has_reward_popup_entries([{"text": "获得物品", "box": [592, 93, 168, 48]}]))
        self.assertTrue(has_reward_popup_entries([], [{"text": "触碰空白区域退出", "box": [601, 673, 109, 19]}]))
        self.assertFalse(has_reward_popup_entries([{"text": "每日活跃", "box": [405, 38, 92, 34]}]))

    def test_dispatch_parsers_never_hit_instant_complete_or_recall(self) -> None:
        self.assertTrue(is_dispatch_screen_entries([{"text": "派遣委托", "box": [438, 11, 115, 35]}]))
        self.assertTrue(is_dispatch_screen_entries([{"text": "当前委托队伍3/3", "box": [438, 42, 163, 26]}]))

        # Safety check: 立即完成 and 召回 must return None.
        in_progress_btns = [
            {"text": "立即完成", "box": [777, 620, 115, 28]},
            {"text": "召回", "box": [1029, 619, 80, 29]},
        ]
        self.assertIsNone(find_dispatch_claim_button_point(in_progress_btns))

        claim_btns = [{"text": "领取奖励", "box": [958, 628, 98, 24]}]
        self.assertEqual(find_dispatch_claim_button_point(claim_btns), (1007, 640))

        card_strip = [{"text": "已完成", "box": [114, 250, 58, 23]}]
        self.assertEqual(find_completed_dispatch_card_point(card_strip), (143, 262))

        self.assertTrue(is_dispatch_report_entries([{"text": "委托报告", "box": [556, 39, 174, 41]}]))
        self.assertTrue(is_dispatch_report_entries([{"text": "SETTLEMENT REPORT", "box": [576, 100, 126, 19]}]))
        report_btns = [
            {"text": "关闭", "box": [461, 624, 81, 33]},
            {"text": "再次委托", "box": [734, 627, 122, 28]},
        ]
        self.assertEqual(find_dispatch_report_action_point(report_btns, reassign=True), (795, 641))
        self.assertEqual(find_dispatch_report_action_point(report_btns, reassign=False), (502, 640))

    def test_revenue_and_like_parsers(self) -> None:
        report_title = [{"text": "近期营收统计", "box": [458, 228, 167, 28]}]
        report_bot = [{"text": "营收统计", "box": [532, 615, 96, 29]}]
        self.assertTrue(is_revenue_report_entries(report_title, report_bot))
        self.assertFalse(is_revenue_ranking_entries(report_title, report_bot))

        rank_title = [{"text": "营收总和排行榜", "box": [440, 215, 196, 28]}]
        rank_bot = [
            {"text": "好友", "box": [552, 614, 53, 30]},
            {"text": "全部玩家", "box": [844, 612, 94, 32]},
        ]
        self.assertFalse(is_revenue_report_entries(rank_title, rank_bot))
        self.assertTrue(is_revenue_ranking_entries(rank_title, rank_bot))
        self.assertEqual(find_all_players_tab_point(rank_bot), (891, 628))

        # OCR may confuse 排行榜 as 排行磅, and must shift tap into upper-right stamp circle
        # well clear of 虎闰千富 below-left.
        stamp_pt = find_revenue_ranking_stamp_point([{"text": "排行磅", "box": [1182, 84, 55, 29]}])
        self.assertEqual(stamp_pt, (1228, 70))
        self.assertGreaterEqual(REVENUE_RANKING_STAMP_POINT[0], 1220)
        self.assertLessEqual(REVENUE_RANKING_STAMP_POINT[1], 74)
        self.assertEqual(parse_like_progress([{"text": "1/3?", "box": [674, 218, 74, 24]}]), (1, 3))
        self.assertEqual(parse_like_progress([{"text": "3/3？", "box": [657, 217, 91, 25]}]), (3, 3))
        self.assertEqual(parse_like_progress([{"text": "O/3", "box": [657, 217, 91, 25]}]), (0, 3))
        self.assertTrue(has_like_limit_toast([{"text": "点赞数量已达上限", "box": [542, 346, 194, 28]}]))
        self.assertFalse(has_like_limit_toast([{"text": "1/3?", "box": [674, 218, 74, 24]}]))

    def test_daily_activity_parsers(self) -> None:
        tabs = [
            {"text": "每日活跃", "box": [405, 38, 92, 34]},
            {"text": "导航手册", "box": [578, 46, 123, 34]},
        ]
        self.assertTrue(is_daily_activity_panel_entries(tabs))
        self.assertEqual(find_daily_activity_tab_point(tabs), (451, 55))

        milestones = [{"text": "100"}, {"text": "200"}, {"text": "300"}]
        self.assertTrue(is_daily_activity_tab_active(milestones))

        # Must only return 可领取, never 前往 / 未完成 / 已领取.
        non_claimable = [
            {"text": "未完成", "box": [210, 607, 60, 24]},
            {"text": "前往", "box": [440, 606, 45, 25]},
            {"text": "已领取", "box": [1072, 604, 54, 29]},
        ]
        self.assertIsNone(find_daily_activity_claim_point(non_claimable))

        claimable = non_claimable + [{"text": "可领取", "box": [181, 604, 91, 28]}]
        self.assertEqual(find_daily_activity_claim_point(claimable), (226, 618))
        self.assertEqual(parse_daily_activity_score([{"text": "650", "box": [202, 190, 43, 32]}]), 650)

    def test_pixel_classifiers_on_synthetic_bgr_frames(self) -> None:
        # 1. Top home button visible vs dark screen
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.assertFalse(is_top_home_button_visible(img))
        img[22:50, 175:220] = (180, 180, 180)
        self.assertTrue(is_top_home_button_visible(img))

        # 2. 全部玩家 tab blue highlight vs unselected dark gray
        img[610:645, 760:830] = (56, 59, 57)  # BGR dark gray
        self.assertFalse(is_all_players_tab_selected(img))
        img[610:645, 760:830] = (255, 126, 63)  # BGR active blue
        self.assertTrue(is_all_players_tab_selected(img))

        # 3. Leaderboard like slots: row 1 liked (pink), row 2 unliked (white + gray thumb), row 3 none (dark)
        cy1, cy2, cy3, cy4 = REVENUE_LIKE_ROW_YS
        img[cy1 - 18 : cy1 + 18, 770:812] = (171, 145, 223)  # BGR pink
        img[cy2 - 18 : cy2 + 18, 770:812] = (250, 250, 250)  # BGR white card
        img[cy2 - 8 : cy2 + 8, 782:798] = (115, 115, 115)  # gray thumb inside
        img[cy3 - 18 : cy3 + 18, 770:812] = (49, 49, 49)  # self-row dark
        img[cy4 - 18 : cy4 + 18, 770:812] = (250, 250, 250)
        img[cy4 - 8 : cy4 + 8, 782:798] = (115, 115, 115)
        self.assertEqual(classify_leaderboard_like_slot(img, cy1), "liked")
        self.assertEqual(classify_leaderboard_like_slot(img, cy2), "unliked")
        self.assertEqual(classify_leaderboard_like_slot(img, cy3), "none")
        self.assertEqual(classify_leaderboard_like_slot(img, cy4), "unliked")
        self.assertEqual(
            find_unliked_leaderboard_points(img),
            [(REVENUE_LIKE_BTN_X, cy2), (REVENUE_LIKE_BTN_X, cy4)],
        )

        # 4. Daily activity chests: 100=claimed (slate), 200=claimable (yellow), 300..600=locked (blue)
        img[160:196, ACTIVITY_CHEST_XS[0] - 16 : ACTIVITY_CHEST_XS[0] + 16] = (127, 79, 59)
        img[160:196, ACTIVITY_CHEST_XS[1] - 16 : ACTIVITY_CHEST_XS[1] + 16] = (25, 195, 250)
        for cx in ACTIVITY_CHEST_XS[2:]:
            img[160:196, cx - 16 : cx + 16] = (240, 140, 60)
        self.assertEqual(classify_activity_chest(img, ACTIVITY_CHEST_XS[0]), "claimed")
        self.assertEqual(classify_activity_chest(img, ACTIVITY_CHEST_XS[1]), "claimable")
        self.assertEqual(classify_activity_chest(img, ACTIVITY_CHEST_XS[2]), "locked")
        chests = find_claimable_activity_chests(img)
        self.assertEqual([c["milestone"] for c in chests], [200])

    def test_battle_pass_parsers_and_pixel_classifiers(self) -> None:
        header = [{"text": "环游手册等级", "box": [440, 42, 126, 28]}]
        bottom_tabs = [
            {"text": "环游手册", "box": [429, 655, 95, 27]},
            {"text": "任务列表", "box": [672, 655, 93, 27]},
        ]
        self.assertTrue(is_battle_pass_screen_entries(header, bottom_tabs))
        self.assertTrue(is_battle_pass_screen_entries([], bottom_tabs))
        self.assertFalse(is_battle_pass_screen_entries([{"text": "每日活跃"}], []))

        title_entries = [
            {"text": "环游手册", "box": [128, 457, 92, 31]},
            {"text": "自箱庭来", "box": [96, 495, 161, 50]},
        ]
        self.assertEqual(parse_battle_pass_title(title_entries), "自箱庭来")
        self.assertEqual(find_battle_pass_rewards_tab_point(bottom_tabs), (476, 668))
        self.assertEqual(find_battle_pass_tasks_tab_point(bottom_tabs), (718, 668))

        subtabs = [
            {"text": "每日任务", "box": [468, 141, 110, 24]},
            {"text": "每周任务", "box": [892, 141, 112, 24]},
        ]
        self.assertEqual(find_battle_pass_daily_tab_point(subtabs), (523, 153))
        self.assertEqual(find_battle_pass_weekly_tab_point(subtabs), (948, 153))

        # Safety: must never match 购买等级 or 进阶无垠手册
        unsafe_btns = [
            {"text": "购买等级", "box": [1118, 48, 104, 32]},
            {"text": "进阶无垠手册", "box": [114, 575, 123, 23]},
        ]
        self.assertIsNone(find_battle_pass_claim_all_point(unsafe_btns))
        self.assertEqual(
            find_battle_pass_claim_all_point(unsafe_btns + [{"text": "一键领取", "box": [1118, 655, 68, 27]}]),
            (1152, 668),
        )

        # Single card claim must strictly match 领取, never 已领取 / 一键领取 / 前往
        non_single = [
            {"text": "已领取", "box": [450, 530, 36, 21]},
            {"text": "一键领取", "box": [1118, 655, 68, 27]},
            {"text": "前往", "box": [657, 530, 37, 21]},
        ]
        self.assertIsNone(find_battle_pass_single_claim_point(non_single))
        self.assertEqual(
            find_battle_pass_single_claim_point(non_single + [{"text": "领取", "box": [865, 530, 36, 21]}]),
            (883, 540),
        )

        # Synthetic BGR tab highlight & ROI diff checks
        img_a = np.zeros((720, 1280, 3), dtype=np.uint8)
        img_a[655:695, 365:405] = (252, 252, 252)  # rewards tab white
        img_a[655:695, 760:810] = (1, 1, 1)
        img_a[135:175, 380:460] = (220, 236, 253)  # BGR daily cream
        img_a[135:175, 820:880] = (18, 40, 75)     # BGR weekly dark brown
        self.assertTrue(is_battle_pass_rewards_tab_selected(img_a))
        self.assertFalse(is_battle_pass_tasks_tab_selected(img_a))
        self.assertTrue(is_battle_pass_daily_tab_selected(img_a))
        self.assertFalse(is_battle_pass_weekly_tab_selected(img_a))

        img_b = img_a.copy()
        img_b[655:695, 365:405] = (1, 1, 1)
        img_b[655:695, 760:810] = (246, 246, 246)
        img_b[135:175, 380:460] = (18, 40, 75)
        img_b[135:175, 820:880] = (220, 236, 253)
        self.assertFalse(is_battle_pass_rewards_tab_selected(img_b))
        self.assertTrue(is_battle_pass_tasks_tab_selected(img_b))
        self.assertFalse(is_battle_pass_daily_tab_selected(img_b))
        self.assertTrue(is_battle_pass_weekly_tab_selected(img_b))

        self.assertFalse(images_differ_in_roi(img_a, img_b, PASS_TITLE_ROI))
        img_b[495:545, 96:250] = (200, 180, 160)
        self.assertTrue(images_differ_in_roi(img_a, img_b, PASS_TITLE_ROI))

    def test_daily_routine_pipeline_task_interface_integrity(self) -> None:
        pipe_path = ROOT / "assets/resource/base/pipeline/daily/daily_routine.json"
        task_path = ROOT / "assets/resource/tasks/DailyRoutine.json"
        iface_path = ROOT / "assets/interface.json"

        pipeline = json.loads(pipe_path.read_text(encoding="utf-8"))
        task_cfg = json.loads(task_path.read_text(encoding="utf-8"))
        iface_cfg = json.loads(iface_path.read_text(encoding="utf-8"))

        missing_refs: list[tuple[str, str]] = []
        for node_name, node_def in pipeline.items():
            for field in ("next", "on_error"):
                refs = node_def.get(field) or []
                for ref in refs:
                    if ref not in pipeline:
                        missing_refs.append((node_name, ref))
        self.assertEqual(missing_refs, [])

        task_entry = task_cfg["task"][0]
        self.assertEqual(task_entry["name"], "DailyRoutine")
        self.assertIn(task_entry["entry"], pipeline)
        self.assertIn("DailyBattlePassEnabled", task_entry["option"])
        start_next = pipeline["DailyRoutineStart"]["next"]
        self.assertLess(
            start_next.index("DailyRoutineActivityStep"),
            start_next.index("DailyRoutineBattlePassStep"),
        )
        self.assertLess(
            start_next.index("DailyRoutineBattlePassStep"),
            start_next.index("DailyRoutineComplete"),
        )
        for opt_name in task_entry["option"]:
            self.assertIn(opt_name, task_cfg["option"])

        for opt_name, opt_def in task_cfg["option"].items():
            for case in opt_def.get("cases", []):
                for target_node in (case.get("pipeline_override") or {}):
                    self.assertIn(target_node, pipeline, msg=f"{opt_name}.{case['name']} -> {target_node}")

        self.assertIn("resource/tasks/DailyRoutine.json", iface_cfg["import"])
        group_names = {g["name"] for g in iface_cfg["group"]}
        self.assertIn("daily", group_names)
        preset_names = {p["name"] for p in iface_cfg["preset"]}
        self.assertIn("daily-routine", preset_names)

        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed in current interpreter")
            res = Resource()
            self.assertTrue(res.post_bundle(ROOT / "assets" / "resource" / "base").wait().succeeded)
            for node_name in pipeline:
                self.assertIsNotNone(res.get_node_data(node_name), msg=f"Missing node in Resource: {node_name}")

    def test_live_pc_log_regressions(self) -> None:
        # 1. Dropped leading '一' -> '键领取' in Battle Pass & Mail claim-all ROI.
        self.assertEqual(
            find_battle_pass_claim_all_point([{"text": "键领取", "box": [1121, 657, 65, 24]}]),
            (1154, 669),
        )
        self.assertIsNone(
            find_battle_pass_claim_all_point(
                [
                    {"text": "购买等级", "box": [1118, 48, 104, 32]},
                    {"text": "进阶无垠手册", "box": [114, 575, 123, 23]},
                    {"text": "已领取", "box": [1120, 657, 65, 24]},
                ]
            )
        )
        self.assertEqual(
            find_mail_claim_all_point([{"text": "键领取", "box": [1030, 655, 76, 26]}]),
            (1068, 668),
        )
        self.assertIsNone(find_mail_claim_all_point([{"text": "删除已读", "box": [770, 655, 86, 27]}]))

        # 2. Revenue '排行榜' stamp shifts up-right into the clear upper circle, never text center (1210, 98).
        stamp_pt = find_revenue_ranking_stamp_point([{"text": "排行榜", "box": [1181, 84, 59, 29]}])
        self.assertEqual(stamp_pt, (1228, 70))
        self.assertNotEqual(stamp_pt, (1210, 98))
        self.assertGreaterEqual(stamp_pt[0], 1220)
        self.assertGreaterEqual(stamp_pt[1], 52)
        self.assertLessEqual(stamp_pt[1], 74)

        # 3. 虎闰千富榜 / 虎润千富榜 / 闰千富榜 must be rejected even with 好友 / 全部玩家 tabs visible.
        rank_tabs = [
            {"text": "好友", "box": [553, 612, 53, 31]},
            {"text": "全部玩家", "box": [843, 612, 97, 32]},
        ]
        self.assertTrue(is_tiger_wealth_ranking_entries([{"text": "虎闰千富榜"}]))
        self.assertTrue(is_tiger_wealth_ranking_entries([{"text": "虎润千富榜"}]))
        self.assertTrue(is_tiger_wealth_ranking_entries([{"text": "闰千富榜"}]))
        self.assertFalse(
            is_revenue_ranking_entries(
                [{"text": "虎闰千富榜", "box": [433, 215, 149, 28]}],
                rank_tabs,
            )
        )
        self.assertTrue(is_revenue_ranking_entries([{"text": "营收总和排行榜"}], rank_tabs))
        self.assertTrue(is_revenue_ranking_entries([], rank_tabs))

    def test_battle_pass_sidebar_cards_visited_guard_and_mouse_lock(self) -> None:
        self.assertEqual(PASS_SIDEBAR_ROI, (10, 190, 220, 250))
        sidebar_entries = [
            {"text": "SELECT", "box": [18, 220, 12, 40]},
            {"text": "自箱庭来", "box": [34, 255, 54, 14]},
            {"text": "解惑之旅", "box": [34, 328, 57, 18]},
        ]
        cards = find_battle_pass_sidebar_cards(sidebar_entries)
        self.assertEqual([c["label"] for c in cards], ["自箱庭来", "解惑之旅"])
        self.assertEqual(cards[0]["card_point"], (110, 244))
        self.assertEqual(cards[1]["card_point"], (110, 319))

        visited = {"自箱庭来"}
        self.assertTrue(is_battle_pass_title_visited("自箱庭来", visited))
        self.assertTrue(is_battle_pass_title_visited("自箱庭", visited))
        self.assertTrue(is_battle_pass_title_visited("自箱庭未", visited))
        self.assertFalse(is_battle_pass_title_visited("解惑之旅", visited))

        with _real_maa_resource():
            import agent.daily_routine_action as dra
        import agent.utils.input_guard as ig

        pin_calls: list[tuple[int, int]] = []
        release_calls: list[float] = []

        @contextmanager
        def _fake_pin(context, info, px, py, **_kw):
            _ = (context, info)
            pin_calls.append((int(px), int(py)))
            yield True

        def _fake_wait_release(_ctx, max_wait_sec=1.2):
            release_calls.append(float(max_wait_sec))
            return True

        ran_actions: list[str] = []

        def fake_run_action(name, *args, **kwargs):
            ran_actions.append(name)
            return SimpleNamespace(success=True)

        ctx = SimpleNamespace(
            tasker=SimpleNamespace(
                stopping=False,
                controller=SimpleNamespace(info={"type": "win32", "mouse_method": 64}),
            ),
            run_action=fake_run_action,
        )
        ig.clear_recorded_controller_info()
        try:
            with (
                patch("agent.utils.input_guard.wait_mouse_button_released", side_effect=_fake_wait_release),
                patch("agent.utils.input_guard.pin_cursor_for_win32_click", side_effect=_fake_pin),
            ):
                self.assertTrue(dra._tap_point(ctx, "SidebarTest", (110, 319)))
                self.assertTrue(dra._swipe_points(ctx, "ScrollTest", 700, 470, 700, 290, duration=380))
        finally:
            ig.clear_recorded_controller_info()

        self.assertEqual(ran_actions, ["SidebarTestTap", "ScrollTestSwipe"])
        self.assertEqual(pin_calls, [(110, 319)])
        self.assertEqual(len(release_calls), 2)

    def test_friend_support_event_checkin_and_split_pipelines(self) -> None:
        self.assertEqual(DRAWER_FRIEND_ICON_POINT, (39, 289))
        self.assertEqual(REWARD_POPUP_TOP_SAFE_POINT, (640, 120))
        self.assertTrue(
            is_friend_card_screen_entries(
                [{"text": "我的名片"}, {"text": "好友列表"}, {"text": "添加好友"}]
            )
        )
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.assertFalse(has_friend_support_coin_bubble(img))
        img[225:320, 455:550] = (245, 245, 245)
        self.assertTrue(has_friend_support_coin_bubble(img))
        self.assertEqual(
            find_friend_support_coin_point([{"text": "40K", "box": [481, 292, 41, 28]}]),
            (502, 288),
        )

        self.assertTrue(
            is_event_checkin_screen_entries(
                [{"text": "启程签到", "box": [870, 93, 195, 56]}],
                [{"text": "17 DAY", "box": [648, 190, 166, 52]}],
            )
        )
        self.assertEqual(
            find_event_checkin_first_card_point(
                [
                    {"text": "18 DAY", "box": [822, 189, 175, 57]},
                    {"text": "17 DAY", "box": [648, 190, 166, 52]},
                ]
            ),
            (731, 336),
        )
        self.assertFalse(is_event_checkin_first_card_highlighted(img))
        img[178:200, 580:820] = (240, 200, 60)
        self.assertTrue(is_event_checkin_first_card_highlighted(img))

        prep_pipe = json.loads((ROOT / "assets/resource/base/pipeline/daily/daily_prep.json").read_text(encoding="utf-8"))
        claim_pipe = json.loads((ROOT / "assets/resource/base/pipeline/daily/daily_claim.json").read_text(encoding="utf-8"))
        prep_task = json.loads((ROOT / "assets/resource/tasks/DailyPrep.json").read_text(encoding="utf-8"))
        claim_task = json.loads((ROOT / "assets/resource/tasks/DailyClaim.json").read_text(encoding="utf-8"))
        self.assertIn("DailyPrepFriendSupportStep", prep_pipe)
        self.assertIn("DailyPrepEventCheckinStep", prep_pipe)
        self.assertIn("DailyPrepEternalSupplyStep", prep_pipe)
        self.assertIn("DailyPrepEternalSupplyEnabled", prep_task["option"])
        self.assertIn("DailyClaimActivityStep", claim_pipe)
        self.assertIn("DailyClaimBattlePassStep", claim_pipe)
        self.assertEqual(prep_task["task"][0]["name"], "DailyPrep")
        self.assertEqual(claim_task["task"][0]["name"], "DailyClaim")

        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            res = Resource()
            self.assertTrue(res.post_bundle(ROOT / "assets" / "resource" / "base").wait().succeeded)
            for node_name in (*prep_pipe.keys(), *claim_pipe.keys()):
                self.assertIsNotNone(res.get_node_data(node_name), msg=f"Missing node: {node_name}")

    def test_daily_activity_chest_claiming_left_to_right_retry_and_skip_stuck(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.daily_routine_action as dra

            def _make_board(yellow_indices: tuple[int, ...], slate_indices: tuple[int, ...] = ()) -> np.ndarray:
                frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                for idx, cx in enumerate(ACTIVITY_CHEST_XS):
                    if idx in yellow_indices:
                        frame[160:196, cx - 16 : cx + 16] = (25, 195, 250)
                    elif idx in slate_indices:
                        frame[160:196, cx - 16 : cx + 16] = (127, 79, 59)
                    else:
                        frame[160:196, cx - 16 : cx + 16] = (240, 140, 60)
                return frame

            # Scenario 1: after card claim, chests light up 1 frame later -> retries and claims 100 then 200 left-to-right.
            frames_s1 = [
                _make_board(()),
                _make_board(()),
                _make_board(()),
                _make_board(()),
                _make_board((0, 1)),
                _make_board((1,), (0,)),
                _make_board((), (0, 1)),
            ]
            cap_idx_1 = {"i": 0}
            tapped_1: list[tuple[str, tuple[int, int]]] = []

            def fake_screencap_1(_ctx):
                idx = min(cap_idx_1["i"], len(frames_s1) - 1)
                cap_idx_1["i"] += 1
                return frames_s1[idx]

            def fake_ocr_1(_ctx, _img, name: str, _roi):
                if "TopTabs" in name:
                    return [{"text": "每日活跃", "box": [406, 40, 92, 33]}]
                if "Milestones" in name:
                    return [{"text": "100"}, {"text": "200"}]
                if "InitCards" in name or name.endswith("Cards0"):
                    return [{"text": "可领取", "box": [200, 605, 80, 30]}]
                if name.endswith("Cards1"):
                    return [{"text": "前往", "box": [440, 605, 60, 26]}]
                if name.endswith("Score"):
                    return [{"text": "200", "box": [205, 193, 38, 27]}]
                return []

            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
            argv = SimpleNamespace(node_name="DailyClaimActivityStep", custom_action_param={})
            action = dra.DailyRoutineActivityAction()
            with (
                patch.object(dra, "_open_drawer", return_value=(frames_s1[0], [{"text": "导航手册", "box": [450, 420, 90, 24]}])),
                patch.object(dra, "safe_screencap", side_effect=fake_screencap_1),
                patch.object(dra, "_ocr_roi", side_effect=fake_ocr_1),
                patch.object(dra, "_tap_point", side_effect=lambda _c, n, pt: tapped_1.append((n, pt)) or True),
                patch.object(dra, "sleep_with_stop", return_value=True),
                patch.object(dra, "_dismiss_reward_popup_if_present", return_value=True),
                patch.object(dra, "_return_to_lobby", return_value=True),
            ):
                res1 = action.run(ctx, argv)

            self.assertTrue(getattr(res1, "success", True))
            chest_taps_1 = [pt for name, pt in tapped_1 if "ActChest" in name]
            self.assertEqual(chest_taps_1, [(441, 173), (562, 173)])

            # Scenario 2: chest 100 remains yellow after 2 taps -> skips 100 and advances to 200 without looping.
            stuck_frame = _make_board((0, 1))
            tapped_2: list[tuple[str, tuple[int, int]]] = []

            def fake_ocr_2(_ctx, _img, name: str, _roi):
                if "TopTabs" in name:
                    return [{"text": "每日活跃", "box": [406, 40, 92, 33]}]
                if "Milestones" in name:
                    return [{"text": "100"}, {"text": "200"}]
                if "Cards" in name:
                    return [{"text": "前往", "box": [440, 605, 60, 26]}]
                if name.endswith("Score"):
                    return [{"text": "200", "box": [205, 193, 38, 27]}]
                return []

            with (
                patch.object(dra, "_open_drawer", return_value=(stuck_frame, [{"text": "导航手册", "box": [450, 420, 90, 24]}])),
                patch.object(dra, "safe_screencap", return_value=stuck_frame),
                patch.object(dra, "_ocr_roi", side_effect=fake_ocr_2),
                patch.object(dra, "_tap_point", side_effect=lambda _c, n, pt: tapped_2.append((n, pt)) or True),
                patch.object(dra, "sleep_with_stop", return_value=True),
                patch.object(dra, "_dismiss_reward_popup_if_present", return_value=True),
                patch.object(dra, "_return_to_lobby", return_value=True),
            ):
                res2 = action.run(ctx, argv)

            self.assertTrue(getattr(res2, "success", True))
            chest_taps_2 = [pt for name, pt in tapped_2 if "ActChest" in name]
            self.assertEqual(chest_taps_2, [(441, 173), (441, 173), (562, 173), (562, 173)])

    def test_open_drawer_waits_for_slide_animation_and_reocrs_settled_entries(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.utils.lobby_nav as lobby_nav

            lobby_img = np.zeros((720, 1280, 3), dtype=np.uint8)
            mid_slide_img = np.zeros((720, 1280, 3), dtype=np.uint8)
            mid_slide_img[410:450, 380:460] = 90
            settled_img = np.zeros((720, 1280, 3), dtype=np.uint8)
            settled_img[410:450, 440:530] = 200

            frames = [lobby_img, lobby_img, mid_slide_img, settled_img, settled_img]
            cap = {"i": 0}

            def fake_screencap(_ctx):
                idx = min(cap["i"], len(frames) - 1)
                cap["i"] += 1
                return frames[idx]

            def fake_ocr(_ctx, image, name: str, _roi):
                if np.array_equal(image, lobby_img):
                    if "LobbyBot" in name:
                        return [{"text": "整备列车"}, {"text": "客运管理"}, {"text": "启程"}]
                    return []
                if "DrawerIdent" in name:
                    return [{"text": "查看更多信息"}, {"text": "列车长形象"}]
                if "DrawerGrid" in name:
                    if np.array_equal(image, mid_slide_img):
                        return [{"text": "营运总览", "box": [286, 423, 65, 18]}, {"text": "导航手册", "box": [399, 423, 66, 18]}]
                    return [{"text": "营运总览", "box": [349, 422, 65, 18]}, {"text": "导航手册", "box": [463, 423, 66, 18]}]
                return []

            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
            with (
                patch.object(lobby_nav, "safe_screencap", side_effect=fake_screencap),
                patch.object(lobby_nav, "ocr_roi", side_effect=fake_ocr),
                patch.object(lobby_nav, "tap_point", return_value=True),
                patch.object(lobby_nav, "sleep_with_stop", return_value=True),
            ):
                img, entries = lobby_nav.open_drawer(ctx, "Test")

            self.assertIs(img, settled_img)
            self.assertEqual(find_drawer_entry_point(entries, ("导航手册",)), (496, 432))

    def test_poll_screen_exits_early_on_hit_and_respects_stop(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            from agent.utils.action_helpers import poll_screen

            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
            f0 = np.zeros((10, 10, 3), dtype=np.uint8)
            f1 = np.ones((10, 10, 3), dtype=np.uint8)
            f2 = np.full((10, 10, 3), 2, dtype=np.uint8)
            seen_attempts: list[int] = []

            def check_hit_second(_img, attempt: int):
                seen_attempts.append(attempt)
                return ("hit", attempt) if attempt == 1 else None

            caps = iter([f0, f1, f2])
            sleeps: list[float] = []
            img, res, aborted = poll_screen(
                ctx,
                check_hit_second,
                initial_delay=1.0,
                interval=0.5,
                max_checks=5,
                screencap_fn=lambda _c: next(caps),
                sleep_fn=lambda _c, sec: sleeps.append(sec) or True,
            )
            self.assertFalse(aborted)
            self.assertIs(img, f1)
            self.assertEqual(res, ("hit", 1))
            self.assertEqual(seen_attempts, [0, 1])
            self.assertEqual(sleeps, [1.0, 0.5])

            # Stop during initial sleep aborts cleanly.
            img_stop, res_stop, aborted_stop = poll_screen(
                ctx,
                lambda _i, _a: True,
                initial_delay=1.0,
                screencap_fn=lambda _c: f0,
                sleep_fn=lambda _c, _s: False,
            )
            self.assertTrue(aborted_stop)
            self.assertIsNone(img_stop)
            self.assertIsNone(res_stop)

            # All misses returns last frame without aborting.
            caps_miss = iter([f0, f1, f2])
            img_miss, res_miss, aborted_miss = poll_screen(
                ctx,
                lambda _i, _a: None,
                initial_delay=0.0,
                interval=0.5,
                max_checks=3,
                screencap_fn=lambda _c: next(caps_miss),
                sleep_fn=lambda _c, _s: True,
            )
            self.assertFalse(aborted_miss)
            self.assertIs(img_miss, f2)
            self.assertIsNone(res_miss)

    def test_battle_pass_polls_across_slow_loading_frames_instead_of_skipping(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.daily_routine_action as dra

            blank_img = np.zeros((720, 1280, 3), dtype=np.uint8)
            pass_img = np.full((720, 1280, 3), 20, dtype=np.uint8)
            cap = {"i": 0}
            ocr_names: list[str] = []

            def fake_screencap(_ctx):
                idx = cap["i"]
                cap["i"] += 1
                return blank_img if idx < 2 else pass_img

            def fake_ocr(_ctx, image, name: str, _roi):
                ocr_names.append(name)
                if np.array_equal(image, blank_img):
                    return []
                if "Hdr" in name:
                    return [{"text": "环游手册等级", "box": [120, 45, 160, 28]}]
                if "Bot" in name:
                    return [
                        {"text": "环游手册", "box": [110, 665, 110, 30]},
                        {"text": "任务列表", "box": [280, 665, 110, 30]},
                    ]
                if "Title" in name:
                    return [{"text": "自箱庭来", "box": [80, 110, 140, 36]}]
                return []

            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
            argv = SimpleNamespace(node_name="DailyClaimBattlePassStep", custom_action_param={})
            action = dra.DailyRoutineBattlePassAction()
            tapped: list[str] = []
            with (
                patch.object(
                    dra,
                    "_open_drawer",
                    return_value=(blank_img, [{"text": "环游手册", "box": [110, 535, 90, 24]}]),
                ) as open_mock,
                patch.object(dra, "safe_screencap", side_effect=fake_screencap),
                patch.object(dra, "_ocr_roi", side_effect=fake_ocr),
                patch.object(dra, "_tap_point", side_effect=lambda _c, n, _pt: tapped.append(n) or True),
                patch.object(dra, "sleep_with_stop", return_value=True),
                patch.object(dra, "_dismiss_reward_popup_if_present", return_value=True),
                patch.object(dra, "_return_to_lobby", return_value=True) as ret_mock,
            ):
                res = action.run(ctx, argv)

            self.assertTrue(getattr(res, "success", True))
            self.assertEqual(open_mock.call_count, 1)
            self.assertIn("DailyClaimBattlePassStep_PassInit0_2Hdr", ocr_names)
            self.assertTrue(any("ClaimAll" in name for name in ocr_names))
            ret_mock.assert_called_once_with(ctx, "DailyClaimBattlePassStep_PassDone")

    def test_dispatch_polls_across_slow_loading_frames_instead_of_skipping(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.daily_routine_action as dra

            blank_img = np.zeros((720, 1280, 3), dtype=np.uint8)
            dispatch_img = np.full((720, 1280, 3), 30, dtype=np.uint8)
            cap = {"i": 0}
            tapped: list[str] = []

            def fake_screencap(_ctx):
                idx = cap["i"]
                cap["i"] += 1
                return blank_img if idx < 2 else dispatch_img

            def fake_ocr(_ctx, image, name: str, _roi):
                if np.array_equal(image, blank_img):
                    return []
                if "InitHeader" in name or "Header" in name:
                    return [{"text": "派遣委托", "box": [90, 25, 140, 32]}]
                if "ClaimBtn0" in name:
                    return [{"text": "领取奖励", "box": [950, 610, 120, 36]}]
                return []

            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
            argv = SimpleNamespace(node_name="DailyPrepDispatchStep", custom_action_param={"reassign": True})
            action = dra.DailyRoutineDispatchAction()
            with (
                patch.object(
                    dra,
                    "_open_drawer",
                    return_value=(blank_img, [{"text": "委托", "box": [230, 420, 70, 24]}]),
                ),
                patch.object(dra, "safe_screencap", side_effect=fake_screencap),
                patch.object(dra, "_ocr_roi", side_effect=fake_ocr),
                patch.object(dra, "_tap_point", side_effect=lambda _c, n, _pt: tapped.append(n) or True),
                patch.object(dra, "sleep_with_stop", return_value=True),
                patch.object(dra, "_dismiss_reward_popup_if_present", return_value=True),
                patch.object(dra, "_return_to_lobby", return_value=True) as ret_mock,
            ):
                res = action.run(ctx, argv)

            self.assertTrue(getattr(res, "success", True))
            self.assertIn("DailyPrepDispatchStep_DispatchOpenTile", tapped)
            self.assertIn("DailyPrepDispatchStep_DispatchClaim0", tapped)
            ret_mock.assert_called_once_with(ctx, "DailyPrepDispatchStep_DispatchDone")

    def test_drawer_uid_mall_bar_and_eternal_supply_helpers(self) -> None:
        self.assertEqual(
            parse_drawer_uid(
                [{"text": "UID:", "box": [109, 12, 33, 18]}, {"text": "8820083699", "box": [143, 17, 75, 10]}]
            ),
            "8820083699",
        )
        self.assertTrue(is_mall_top_bar_entries([{"text": "无垠补给", "box": [383, 23, 77, 29]}]))
        self.assertTrue(is_eternal_supply_page_entries([{"text": "无垠补给礼包7日"}]))

        img = np.full((720, 1280, 3), 25, dtype=np.uint8)
        tab = {"text": "无垠补给", "box": [383, 23, 77, 29]}
        self.assertFalse(has_mall_tab_red_dot(img, tab))
        img[10:35, 455:478] = (30, 30, 220)  # BGR red dot
        self.assertTrue(has_mall_tab_red_dot(img, tab))

        # Orange claim button at day 3 (878, 435), ignoring '已领取' and bottom-right area (y>=565)
        img[405:455, 845:910] = (35, 155, 240)  # BGR orange button
        entries = [
            {"text": "已领取", "box": [1194, 323, 60, 23]},
            {"text": "领取", "box": [859, 425, 38, 21]},
            {"text": "领取", "box": [1120, 605, 50, 25]},
        ]
        self.assertEqual(find_eternal_supply_claim_point(img, entries), (878, 436))
        # Grey/non-orange button must be ignored
        img_grey = np.full((720, 1280, 3), 80, dtype=np.uint8)
        self.assertIsNone(find_eternal_supply_claim_point(img_grey, entries))


if __name__ == "__main__":
    unittest.main()

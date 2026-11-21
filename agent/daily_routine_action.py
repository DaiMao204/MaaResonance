"""Custom MaaFramework actions for Auto Daily (自动日常)."""
from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from agent.utils.action_helpers import ocr_roi, parse_action_param, poll_screen, swipe_points, tap_point
from agent.utils.activity_hub_nav import open_activity_hub, select_activity_tab
from agent.utils.input_guard import safe_screencap, sleep_with_stop
from agent.utils.mall_nav import open_mall_from_lobby, select_mall_tab
from agent.utils.lobby_nav import (
    dismiss_reward_popup_if_present as _shared_dismiss_reward_popup,
    is_drawer as _shared_is_drawer,
    is_lobby as _shared_is_lobby,
    is_stopping as _shared_is_stopping,
    open_drawer as _shared_open_drawer,
    return_to_lobby as _shared_return_to_lobby,
)
from maa_resonance.logic.daily_routine import (
    ACTIVITY_CARD_BOTTOM_ROI,
    ACTIVITY_CHEST_MILESTONES,
    ACTIVITY_CHEST_XS,
    ACTIVITY_MILESTONE_LABEL_ROI,
    ACTIVITY_SCORE_ROI,
    ACTIVITY_TAB_FALLBACK,
    ACTIVITY_TOP_TABS_ROI,
    CHECKIN_CARDS_ROI,
    CHECKIN_HEADER_ROI,
    DISPATCH_CARD_STRIP_ROI,
    DISPATCH_CLAIM_BTN_ROI,
    DISPATCH_HEADER_ROI,
    DISPATCH_REPORT_BTN_ROI,
    DISPATCH_REPORT_TITLE_ROI,
    DRAWER_CLOSE_POINT,
    DRAWER_FRIEND_ICON_POINT,
    DRAWER_GRID_ROI,
    DRAWER_IDENT_ROI,
    DRAWER_MAIL_ICON_POINT,
    ETERNAL_SUPPLY_GRID_ROI,
    ETERNAL_SUPPLY_HEADER_ROI,
    FRIEND_NAV_ROI,
    FRIEND_SUPPORT_COIN_ROI,
    LOBBY_AVATAR_POINT,
    LOBBY_BOTTOM_RIGHT_ROI,
    LOBBY_REVENUE_PILL_POINT,
    LOBBY_REVENUE_PILL_ROI,
    LOBBY_RIGHT_MID_ROI,
    MAIL_BOTTOM_ROI,
    MAIL_CLAIM_ALL_FALLBACK,
    MAIL_CLAIM_ALL_ROI,
    PASS_BOTTOM_TABS_ROI,
    PASS_CLAIM_ALL_ROI,
    PASS_DAILY_TAB_FALLBACK,
    PASS_HEADER_ROI,
    PASS_REWARDS_TAB_FALLBACK,
    PASS_SIDEBAR_ROI,
    PASS_SLOT_POINTS,
    PASS_TASKS_TAB_FALLBACK,
    PASS_TASK_SUBTABS_ROI,
    PASS_TITLE_ROI,
    PASS_WEEKLY_TAB_FALLBACK,
    REVENUE_ALL_PLAYERS_TAB_FALLBACK,
    REVENUE_BOTTOM_TABS_ROI,
    REVENUE_LIKE_BADGE_ROI,
    REVENUE_LIMIT_TOAST_ROI,
    REVENUE_LIST_SWIPE,
    REVENUE_RANKING_STAMP_ALT_POINT,
    REVENUE_RANKING_STAMP_POINT,
    REVENUE_REPORT_TITLE_ROI,
    REVENUE_STAMP_ROI,
    REWARD_POPUP_DISMISS_POINT,
    REWARD_POPUP_HINT_ROI,
    REWARD_POPUP_TITLE_ROI,
    REWARD_POPUP_TOP_SAFE_POINT,
    TOP_BACK_POINT,
    TOP_HOME_POINT,
    find_all_players_tab_point,
    find_battle_pass_claim_all_point,
    find_battle_pass_daily_tab_point,
    find_battle_pass_rewards_tab_point,
    find_battle_pass_sidebar_cards,
    find_battle_pass_tasks_tab_point,
    find_battle_pass_weekly_tab_point,
    classify_activity_chest,
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
    is_revenue_ranking_entries,
    is_revenue_report_entries,
    is_tiger_wealth_ranking_entries,
    is_top_home_button_visible,
    parse_battle_pass_title,
    parse_daily_activity_score,
    parse_like_progress,
)


def _is_stopping(context: Context) -> bool:
    return _shared_is_stopping(context)


def _parse_param(raw: Any) -> dict[str, Any]:
    return parse_action_param(raw)


def _ocr_roi(
    context: Context,
    image: Any,
    node_name: str,
    roi: tuple[int, int, int, int],
) -> list[dict[str, Any]]:
    return ocr_roi(context, image, node_name, roi)


def _tap_point(context: Context, node_name: str, point: tuple[int, int]) -> bool:
    return tap_point(context, node_name, point)


def _poll_screen(
    context: Context,
    check_fn: Any,
    *,
    initial_delay: float = 1.0,
    interval: float = 0.5,
    max_checks: int = 5,
) -> tuple[Any | None, Any, bool]:
    return poll_screen(
        context,
        check_fn,
        initial_delay=initial_delay,
        interval=interval,
        max_checks=max_checks,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )


def _swipe_points(
    context: Context,
    node_name: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    duration: int = 380,
) -> bool:
    return swipe_points(
        context,
        node_name,
        (int(x1), int(y1)),
        (int(x2), int(y2)),
        duration=duration,
        end_hold=150,
    )


def _dismiss_reward_popup_if_present(
    context: Context,
    prefix: str,
    image: Any = None,
    *,
    max_taps: int = 2,
    dismiss_point: tuple[int, int] = REWARD_POPUP_DISMISS_POINT,
) -> bool:
    """Dismiss '获得物品' reward overlay if visible. Returns False only on stop."""
    return _shared_dismiss_reward_popup(
        context,
        prefix,
        image,
        max_taps=max_taps,
        dismiss_point=dismiss_point,
    )


def _is_lobby(context: Context, prefix: str, image: Any) -> bool:
    return _shared_is_lobby(context, prefix, image)


def _is_drawer(context: Context, prefix: str, image: Any) -> tuple[bool, list[dict[str, Any]]]:
    return _shared_is_drawer(context, prefix, image)


def _return_to_lobby(
    context: Context,
    prefix: str,
    max_steps: int = 6,
    *,
    dismiss_point: tuple[int, int] = REWARD_POPUP_DISMISS_POINT,
) -> bool:
    """Navigate back to the train lobby from any subpage/drawer/modal."""
    return _shared_return_to_lobby(context, prefix, max_steps=max_steps, dismiss_point=dismiss_point)


def _open_drawer(context: Context, prefix: str) -> tuple[Any | None, list[dict[str, Any]]]:
    """Ensure the left navigation drawer is open and return (image, entries)."""
    return _shared_open_drawer(context, prefix)


@AgentServer.custom_action("daily_routine_mail")
class DailyRoutineMailAction(CustomAction):
    """Open Mail from the drawer, tap '一键领取', dismiss popup, and return to lobby."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        prefix = f"{argv.node_name}_Mail"
        img, _ = _open_drawer(context, prefix)
        if img is None:
            if _is_stopping(context):
                return CustomAction.RunResult(success=False)
            print("[DailyRoutine] 未能打开个人抽屉，跳过邮箱领取。", flush=True)
            _return_to_lobby(context, f"{prefix}Abort")
            return CustomAction.RunResult(success=True)

        mail_entered = False
        for attempt in range(2):
            if not _tap_point(context, f"{prefix}RailMail{attempt}", DRAWER_MAIL_ICON_POINT):
                return CustomAction.RunResult(success=False)
            img, matched, aborted = _poll_screen(
                context,
                lambda frame, idx, _att=attempt: is_mail_screen_entries(
                    _ocr_roi(context, frame, f"{prefix}Bottom{_att}_{idx}", MAIL_BOTTOM_ROI)
                ),
                initial_delay=1.0,
                interval=0.5,
                max_checks=4,
            )
            if aborted:
                return CustomAction.RunResult(success=False)
            if matched:
                mail_entered = True
                break

        if not mail_entered:
            print("[DailyRoutine] 未识别到邮箱底部操作栏，跳过邮箱领取。", flush=True)
            _return_to_lobby(context, f"{prefix}Back")
            return CustomAction.RunResult(success=True)

        claim_entries = _ocr_roi(context, img, f"{prefix}ClaimBtn", MAIL_CLAIM_ALL_ROI)
        claim_pt = find_mail_claim_all_point(claim_entries) or MAIL_CLAIM_ALL_FALLBACK
        if not _tap_point(context, f"{prefix}ClaimAll", claim_pt):
            return CustomAction.RunResult(success=False)
        if not sleep_with_stop(context, 1.0):
            return CustomAction.RunResult(success=False)
        if not _dismiss_reward_popup_if_present(context, f"{prefix}AfterClaim"):
            return CustomAction.RunResult(success=False)

        print("[DailyRoutine] 邮箱「一键领取」已执行完毕。", flush=True)
        _return_to_lobby(context, f"{prefix}Done")
        return CustomAction.RunResult(success=not _is_stopping(context))



@AgentServer.custom_action("daily_routine_dispatch")
class DailyRoutineDispatchAction(CustomAction):
    """Claim completed Dispatch rewards and optionally click '再次委托'."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        params = _parse_param(getattr(argv, "custom_action_param", None))
        reassign = bool(params.get("reassign", True))
        prefix = f"{argv.node_name}_Dispatch"

        img, drawer_entries = _open_drawer(context, prefix)
        if img is None:
            if _is_stopping(context):
                return CustomAction.RunResult(success=False)
            print("[DailyRoutine] 未能打开个人抽屉，跳过派遣委托。", flush=True)
            _return_to_lobby(context, f"{prefix}Abort")
            return CustomAction.RunResult(success=True)

        dispatch_pt = find_drawer_entry_point(drawer_entries, ("委托",)) or (269, 431)
        if not _tap_point(context, f"{prefix}OpenTile", dispatch_pt):
            return CustomAction.RunResult(success=False)

        def _check_dispatch_open(frame: Any, idx: int) -> str | None:
            rep = _ocr_roi(context, frame, f"{prefix}InitReport{idx}", DISPATCH_REPORT_TITLE_ROI)
            if is_dispatch_report_entries(rep):
                return "report"
            hdr = _ocr_roi(context, frame, f"{prefix}InitHeader{idx}", DISPATCH_HEADER_ROI)
            if is_dispatch_screen_entries(hdr):
                return "dispatch"
            return None

        pending_img, open_kind, aborted = _poll_screen(
            context,
            _check_dispatch_open,
            initial_delay=1.1,
            interval=0.5,
            max_checks=5,
        )
        if aborted:
            return CustomAction.RunResult(success=False)
        if not open_kind:
            print("[DailyRoutine] 未进入派遣委托界面，跳过。", flush=True)
            _return_to_lobby(context, f"{prefix}NotDispatch")
            return CustomAction.RunResult(success=not _is_stopping(context))

        claimed_or_reassigned = False
        for step in range(4):
            if pending_img is not None:
                img = pending_img
                pending_img = None
            else:
                img = safe_screencap(context)
                if img is None:
                    return CustomAction.RunResult(success=False)

            report_entries = _ocr_roi(context, img, f"{prefix}Report{step}", DISPATCH_REPORT_TITLE_ROI)
            if is_dispatch_report_entries(report_entries):
                btn_entries = _ocr_roi(context, img, f"{prefix}ReportBtns{step}", DISPATCH_REPORT_BTN_ROI)
                action_pt = find_dispatch_report_action_point(btn_entries, reassign=reassign)
                if action_pt is None:
                    action_pt = (795, 641) if reassign else (501, 640)
                if not _tap_point(context, f"{prefix}ReportAct{step}", action_pt):
                    return CustomAction.RunResult(success=False)
                if not sleep_with_stop(context, 1.1):
                    return CustomAction.RunResult(success=False)
                if not _dismiss_reward_popup_if_present(context, f"{prefix}ReportDismiss{step}"):
                    return CustomAction.RunResult(success=False)
                claimed_or_reassigned = True
                action_label = "再次委托" if reassign else "关闭报告"
                print(f"[DailyRoutine] 派遣委托报告已处理：{action_label}。", flush=True)
                continue

            header_entries = _ocr_roi(context, img, f"{prefix}Header{step}", DISPATCH_HEADER_ROI)
            if not is_dispatch_screen_entries(header_entries):
                if claimed_or_reassigned:
                    if not sleep_with_stop(context, 0.55):
                        return CustomAction.RunResult(success=False)
                    retry_img = safe_screencap(context)
                    if retry_img is None:
                        return CustomAction.RunResult(success=False)
                    retry_rep = _ocr_roi(context, retry_img, f"{prefix}ReportRetry{step}", DISPATCH_REPORT_TITLE_ROI)
                    retry_hdr = _ocr_roi(context, retry_img, f"{prefix}HeaderRetry{step}", DISPATCH_HEADER_ROI)
                    if is_dispatch_report_entries(retry_rep) or is_dispatch_screen_entries(retry_hdr):
                        pending_img = retry_img
                        continue
                    break
                print("[DailyRoutine] 未进入派遣委托界面，跳过。", flush=True)
                break

            claim_entries = _ocr_roi(context, img, f"{prefix}ClaimBtn{step}", DISPATCH_CLAIM_BTN_ROI)
            claim_pt = find_dispatch_claim_button_point(claim_entries)

            if claim_pt is None:
                strip_entries = _ocr_roi(context, img, f"{prefix}Strip{step}", DISPATCH_CARD_STRIP_ROI)
                card_pt = find_completed_dispatch_card_point(strip_entries)
                if card_pt is not None:
                    if not _tap_point(context, f"{prefix}SelectCard{step}", card_pt):
                        return CustomAction.RunResult(success=False)
                    if not sleep_with_stop(context, 0.75):
                        return CustomAction.RunResult(success=False)
                    img = safe_screencap(context)
                    if img is None:
                        return CustomAction.RunResult(success=False)
                    claim_entries = _ocr_roi(context, img, f"{prefix}ClaimRetry{step}", DISPATCH_CLAIM_BTN_ROI)
                    claim_pt = find_dispatch_claim_button_point(claim_entries)

            if claim_pt is not None:
                if not _tap_point(context, f"{prefix}Claim{step}", claim_pt):
                    return CustomAction.RunResult(success=False)
                if not sleep_with_stop(context, 1.15):
                    return CustomAction.RunResult(success=False)
                claimed_or_reassigned = True
                continue

            if not claimed_or_reassigned:
                print("[DailyRoutine] 派遣委托当前无可领取项，跳过。", flush=True)
            break

        _return_to_lobby(context, f"{prefix}Done")
        return CustomAction.RunResult(success=not _is_stopping(context))



@AgentServer.custom_action("daily_routine_revenue_like")
class DailyRoutineRevenueLikeAction(CustomAction):
    """Open Revenue Leaderboard, switch to '全部玩家', and like until daily limit (3/3)."""

    def _enter_revenue_screen(self, context: Context, prefix: str) -> Any | None:
        _return_to_lobby(context, f"{prefix}ToLobby")
        img = safe_screencap(context)
        if img is None:
            return None

        pill_entries = _ocr_roi(context, img, f"{prefix}LobbyPill", LOBBY_REVENUE_PILL_ROI)
        pill_pt = find_lobby_revenue_pill_point(pill_entries)
        if pill_pt is not None:
            if not _tap_point(context, f"{prefix}TapPill", pill_pt):
                return None
            img, matched, aborted = _poll_screen(
                context,
                lambda frame, idx: self._is_on_revenue_or_ranking(context, f"{prefix}CheckPill{idx}", frame),
                initial_delay=1.0,
                interval=0.5,
                max_checks=4,
            )
            if aborted:
                return None
            if matched:
                return img

        img, drawer_entries = _open_drawer(context, f"{prefix}FallbackDrawer")
        if img is None:
            return None
        rev_pt = find_drawer_entry_point(drawer_entries, ("营运总览", "运营总览")) or (383, 431)
        if not _tap_point(context, f"{prefix}TapDrawerRev", rev_pt):
            return None
        img, matched, aborted = _poll_screen(
            context,
            lambda frame, idx: self._is_on_revenue_or_ranking(context, f"{prefix}CheckDrawer{idx}", frame),
            initial_delay=1.0,
            interval=0.5,
            max_checks=4,
        )
        if aborted or not matched:
            return None
        return img

    def _is_on_revenue_or_ranking(self, context: Context, prefix: str, image: Any) -> bool:
        title_entries = _ocr_roi(context, image, f"{prefix}Title", REVENUE_REPORT_TITLE_ROI)
        bottom_entries = _ocr_roi(context, image, f"{prefix}Bot", REVENUE_BOTTOM_TABS_ROI)
        return (
            is_revenue_ranking_entries(title_entries, bottom_entries)
            or is_revenue_report_entries(title_entries, bottom_entries)
            or is_tiger_wealth_ranking_entries(title_entries)
        )

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        prefix = f"{argv.node_name}_RevLike"
        img = self._enter_revenue_screen(context, prefix)
        if img is None:
            if _is_stopping(context):
                return CustomAction.RunResult(success=False)
            print("[DailyRoutine] 未能进入营收报告/排行榜界面，跳过点赞。", flush=True)
            _return_to_lobby(context, f"{prefix}Abort")
            return CustomAction.RunResult(success=True)

        confirmed_ranking = False
        title_entries: list[dict[str, Any]] = []
        bottom_entries: list[dict[str, Any]] = []
        for attempt in range(2):
            title_entries = _ocr_roi(context, img, f"{prefix}RankCheckTitle{attempt}", REVENUE_REPORT_TITLE_ROI)
            bottom_entries = _ocr_roi(context, img, f"{prefix}RankCheckBot{attempt}", REVENUE_BOTTOM_TABS_ROI)
            if is_revenue_ranking_entries(title_entries, bottom_entries):
                confirmed_ranking = True
                break
            if attempt == 0:
                stamp_entries = _ocr_roi(context, img, f"{prefix}Stamp", REVENUE_STAMP_ROI)
                stamp_pt = find_revenue_ranking_stamp_point(stamp_entries) or REVENUE_RANKING_STAMP_POINT
            else:
                stamp_pt = REVENUE_RANKING_STAMP_ALT_POINT
            if not _tap_point(context, f"{prefix}ToRanking{attempt}", stamp_pt):
                return CustomAction.RunResult(success=False)

            def _check_ranking(frame: Any, idx: int, _att: int = attempt) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
                t_e = _ocr_roi(context, frame, f"{prefix}RankTitle{_att}_{idx}", REVENUE_REPORT_TITLE_ROI)
                b_e = _ocr_roi(context, frame, f"{prefix}RankBot{_att}_{idx}", REVENUE_BOTTOM_TABS_ROI)
                return (t_e, b_e) if is_revenue_ranking_entries(t_e, b_e) else None

            polled_img, matched_rank, aborted = _poll_screen(
                context,
                _check_ranking,
                initial_delay=1.0,
                interval=0.5,
                max_checks=4,
            )
            if aborted:
                return CustomAction.RunResult(success=False)
            if matched_rank is not None:
                img = polled_img
                title_entries, bottom_entries = matched_rank
                confirmed_ranking = True
                break
            img = polled_img

        if not confirmed_ranking:
            print("[DailyRoutine] 未确认进入营收排行榜，跳过点赞。", flush=True)
            _return_to_lobby(context, f"{prefix}NotRank")
            return CustomAction.RunResult(success=True)

        badge_entries = _ocr_roi(context, img, f"{prefix}InitBadge", REVENUE_LIKE_BADGE_ROI)
        progress = parse_like_progress(badge_entries)
        if progress is not None and progress[0] >= progress[1]:
            print(f"[DailyRoutine] 营收排行榜今日点赞已满（{progress[0]}/{progress[1]}），跳过。", flush=True)
            _return_to_lobby(context, f"{prefix}AlreadyDone")
            return CustomAction.RunResult(success=True)

        if not is_all_players_tab_selected(img):
            all_pt = find_all_players_tab_point(bottom_entries) or REVENUE_ALL_PLAYERS_TAB_FALLBACK
            if not _tap_point(context, f"{prefix}AllTab", all_pt):
                return CustomAction.RunResult(success=False)
            if not sleep_with_stop(context, 0.95):
                return CustomAction.RunResult(success=False)

        attempts_by_row: dict[int, int] = {}
        swipes = 0
        for step in range(8):
            if not _dismiss_reward_popup_if_present(context, f"{prefix}StepDismiss{step}"):
                return CustomAction.RunResult(success=False)
            img = safe_screencap(context)
            if img is None:
                return CustomAction.RunResult(success=False)

            toast_entries = _ocr_roi(context, img, f"{prefix}Toast{step}", REVENUE_LIMIT_TOAST_ROI)
            if has_like_limit_toast(toast_entries):
                print("[DailyRoutine] 检测到「点赞数量已达上限」，排行榜点赞完成。", flush=True)
                break

            badge_entries = _ocr_roi(context, img, f"{prefix}Badge{step}", REVENUE_LIKE_BADGE_ROI)
            cur_progress = parse_like_progress(badge_entries)
            if cur_progress is not None and cur_progress[0] >= cur_progress[1]:
                print(
                    f"[DailyRoutine] 营收排行榜点赞完成（{cur_progress[0]}/{cur_progress[1]}）。",
                    flush=True,
                )
                break

            candidates = [
                pt for pt in find_unliked_leaderboard_points(img) if attempts_by_row.get(pt[1], 0) < 2
            ]
            if candidates:
                target_pt = candidates[0]
                attempts_by_row[target_pt[1]] = attempts_by_row.get(target_pt[1], 0) + 1
                if not _tap_point(context, f"{prefix}Like{step}", target_pt):
                    return CustomAction.RunResult(success=False)
                if not sleep_with_stop(context, 0.9):
                    return CustomAction.RunResult(success=False)
                if not _dismiss_reward_popup_if_present(context, f"{prefix}AfterLike{step}"):
                    return CustomAction.RunResult(success=False)
                continue

            if swipes < 2:
                x1, y1, x2, y2 = REVENUE_LIST_SWIPE
                if not _swipe_points(context, f"{prefix}Scroll{step}", x1, y1, x2, y2):
                    return CustomAction.RunResult(success=False)
                if not sleep_with_stop(context, 0.65):
                    return CustomAction.RunResult(success=False)
                attempts_by_row.clear()
                swipes += 1
                continue

            break

        _return_to_lobby(context, f"{prefix}Done")
        return CustomAction.RunResult(success=not _is_stopping(context))



@AgentServer.custom_action("daily_routine_activity")
class DailyRoutineActivityAction(CustomAction):
    """Open Navigation Manual -> 每日活跃, claim all completed tasks, then claim 100~600 chests."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        prefix = f"{argv.node_name}_Act"
        top_tabs: list[dict[str, Any]] = []
        milestones: list[dict[str, Any]] = []
        card_bottom: list[dict[str, Any]] = []
        tab_active = False
        panel_visible = False
        for open_attempt in range(2):
            img, drawer_entries = _open_drawer(context, f"{prefix}{open_attempt}" if open_attempt else prefix)
            if img is None:
                if _is_stopping(context):
                    return CustomAction.RunResult(success=False)
                print("[DailyRoutine] 未能打开个人抽屉，跳过每日活跃领奖。", flush=True)
                _return_to_lobby(context, f"{prefix}Abort")
                return CustomAction.RunResult(success=True)

            manual_pt = find_drawer_entry_point(drawer_entries, ("导航手册",)) or (496, 432)
            tap_tag = f"{prefix}OpenManual{open_attempt}" if open_attempt else f"{prefix}OpenManual"
            if not _tap_point(context, tap_tag, manual_pt):
                return CustomAction.RunResult(success=False)

            def _check_activity_open(frame: Any, idx: int) -> tuple[list[dict[str, Any]], bool, bool] | None:
                tt = _ocr_roi(context, frame, f"{prefix}TopTabs{idx}", ACTIVITY_TOP_TABS_ROI)
                ms = _ocr_roi(context, frame, f"{prefix}Milestones{idx}", ACTIVITY_MILESTONE_LABEL_ROI)
                cb = _ocr_roi(context, frame, f"{prefix}InitCards{idx}", ACTIVITY_CARD_BOTTOM_ROI)
                ta = is_daily_activity_tab_active(ms, cb)
                pv = is_daily_activity_panel_entries(tt)
                return (tt, ta, pv) if (ta or pv) else None

            polled_img, matched_act, aborted = _poll_screen(
                context,
                _check_activity_open,
                initial_delay=1.1,
                interval=0.5,
                max_checks=5,
            )
            if aborted:
                return CustomAction.RunResult(success=False)
            if matched_act is not None:
                img = polled_img
                top_tabs, tab_active, panel_visible = matched_act
                break
            if open_attempt == 0:
                print("[DailyRoutine] 误入非导航手册页面，返回大厅重试一次。", flush=True)
                _return_to_lobby(context, f"{prefix}RetryLobby")

        if not (tab_active or panel_visible):
            print("[DailyRoutine] 未识别到导航手册/每日活跃界面，跳过每日活跃领奖。", flush=True)
            _return_to_lobby(context, f"{prefix}NotPanel")
            return CustomAction.RunResult(success=True)

        if not tab_active:
            tab_pt = find_daily_activity_tab_point(top_tabs) or ACTIVITY_TAB_FALLBACK
            if not _tap_point(context, f"{prefix}SelectTab", tab_pt):
                return CustomAction.RunResult(success=False)
            if not sleep_with_stop(context, 0.95):
                return CustomAction.RunResult(success=False)

        # Sub-step A: claim completed task points (clicking one '可领取' claims all completed tasks).
        claimed_cards = 0
        for step in range(2):
            img = safe_screencap(context)
            if img is None:
                return CustomAction.RunResult(success=False)
            card_bottom = _ocr_roi(context, img, f"{prefix}Cards{step}", ACTIVITY_CARD_BOTTOM_ROI)
            claim_pt = find_daily_activity_claim_point(card_bottom)
            if claim_pt is None:
                break
            if not _tap_point(context, f"{prefix}ClaimCard{step}", claim_pt):
                return CustomAction.RunResult(success=False)
            claimed_cards += 1
            if not sleep_with_stop(context, 1.15):
                return CustomAction.RunResult(success=False)
            if not _dismiss_reward_popup_if_present(context, f"{prefix}CardDismiss{step}"):
                return CustomAction.RunResult(success=False)

        # Sub-step B: claim yellow 100~600 milestone chests left-to-right with retry/skip guards.
        claimed_chests = 0
        empty_retries = 0
        attempts_by_milestone: dict[int, int] = {}
        for step in range(12):
            if not _dismiss_reward_popup_if_present(
                context,
                f"{prefix}ChestPre{step}",
                dismiss_point=REWARD_POPUP_TOP_SAFE_POINT,
            ):
                return CustomAction.RunResult(success=False)
            img = safe_screencap(context)
            if img is None:
                return CustomAction.RunResult(success=False)
            claimable = find_claimable_activity_chests(img)
            active_claimable = [
                chest
                for chest in claimable
                if attempts_by_milestone.get(int(chest["milestone"]), 0) < 2
            ]
            if not active_claimable:
                if not claimable and claimed_cards > 0 and claimed_chests == 0 and empty_retries < 3:
                    empty_retries += 1
                    if not sleep_with_stop(context, 0.75):
                        return CustomAction.RunResult(success=False)
                    continue
                score_entries = _ocr_roi(context, img, f"{prefix}Score", ACTIVITY_SCORE_ROI)
                score = parse_daily_activity_score(score_entries)
                chest_states = ", ".join(
                    f"{m}:{classify_activity_chest(img, cx)}"
                    for m, cx in zip(ACTIVITY_CHEST_MILESTONES, ACTIVITY_CHEST_XS)
                )
                print(
                    f"[DailyRoutine] 每日活跃检查完成（当前活跃度={score if score is not None else '未知'}，"
                    f"本次点击宝箱={claimed_chests}，宝箱状态=[{chest_states}]）。",
                    flush=True,
                )
                break
            target = active_claimable[0]
            milestone = int(target["milestone"])
            attempts_by_milestone[milestone] = attempts_by_milestone.get(milestone, 0) + 1
            if not _tap_point(context, f"{prefix}Chest{step}", (target["x"], target["y"])):
                return CustomAction.RunResult(success=False)
            claimed_chests += 1
            if not sleep_with_stop(context, 1.0):
                return CustomAction.RunResult(success=False)
            if not _dismiss_reward_popup_if_present(
                context,
                f"{prefix}ChestDismiss{step}",
                dismiss_point=REWARD_POPUP_TOP_SAFE_POINT,
            ):
                return CustomAction.RunResult(success=False)

        _return_to_lobby(context, f"{prefix}Done")
        return CustomAction.RunResult(success=not _is_stopping(context))



@AgentServer.custom_action("daily_routine_battle_pass")
class DailyRoutineBattlePassAction(CustomAction):
    """Open Battle Pass (环游手册), claim 每日任务 & 每周任务 + tier rewards across all left passes."""

    def _is_on_pass_screen(self, context: Context, prefix: str, image: Any) -> bool:
        header = _ocr_roi(context, image, f"{prefix}Hdr", PASS_HEADER_ROI)
        bottom = _ocr_roi(context, image, f"{prefix}Bot", PASS_BOTTOM_TABS_ROI)
        return is_battle_pass_screen_entries(header, bottom)

    def _claim_claim_all_loop(self, context: Context, prefix: str, *, max_rounds: int = 2) -> bool:
        """Click bottom-right '一键领取' up to max_rounds. Returns (False only on stop)."""
        for step in range(max_rounds):
            img = safe_screencap(context)
            if img is None:
                return False
            claim_entries = _ocr_roi(context, img, f"{prefix}ClaimAll{step}", PASS_CLAIM_ALL_ROI)
            claim_pt = find_battle_pass_claim_all_point(claim_entries)
            if claim_pt is None:
                return True
            if not _tap_point(context, f"{prefix}ClaimAllTap{step}", claim_pt):
                return False
            if not sleep_with_stop(context, 1.0):
                return False
            if not _dismiss_reward_popup_if_present(context, f"{prefix}ClaimAllDismiss{step}", max_taps=3):
                return False
        return True

    def _claim_task_subtab(self, context: Context, prefix: str, *, tab: str) -> bool:
        """Switch to 'daily' or 'weekly' sub-tab under 任务列表 and click bottom-right 一键领取."""
        img = safe_screencap(context)
        if img is None:
            return False

        is_selected = is_battle_pass_daily_tab_selected if tab == "daily" else is_battle_pass_weekly_tab_selected
        if not is_selected(img):
            subtab_entries = _ocr_roi(context, img, f"{prefix}SubTabs", PASS_TASK_SUBTABS_ROI)
            if tab == "daily":
                tab_pt = find_battle_pass_daily_tab_point(subtab_entries) or PASS_DAILY_TAB_FALLBACK
            else:
                tab_pt = find_battle_pass_weekly_tab_point(subtab_entries) or PASS_WEEKLY_TAB_FALLBACK
            if not _tap_point(context, f"{prefix}SubTabTap", tab_pt):
                return False
            if not sleep_with_stop(context, 0.9):
                return False

        return self._claim_claim_all_loop(context, f"{prefix}All", max_rounds=2)

    def _claim_current_pass(self, context: Context, prefix: str, pass_label: str) -> bool:
        """For the currently selected pass: claim 每日任务, 每周任务, and 环游手册 tier rewards."""
        img = safe_screencap(context)
        if img is None:
            return False

        if not is_battle_pass_tasks_tab_selected(img):
            bottom_entries = _ocr_roi(context, img, f"{prefix}ToTasksBot", PASS_BOTTOM_TABS_ROI)
            tasks_pt = find_battle_pass_tasks_tab_point(bottom_entries) or PASS_TASKS_TAB_FALLBACK
            if not _tap_point(context, f"{prefix}ToTasks", tasks_pt):
                return False
            if not sleep_with_stop(context, 0.95):
                return False

        if not self._claim_task_subtab(context, f"{prefix}_Daily", tab="daily"):
            return False
        if not self._claim_task_subtab(context, f"{prefix}_Weekly", tab="weekly"):
            return False

        img = safe_screencap(context)
        if img is None:
            return False
        if not is_battle_pass_rewards_tab_selected(img):
            bottom_entries = _ocr_roi(context, img, f"{prefix}ToRewBot", PASS_BOTTOM_TABS_ROI)
            rew_pt = find_battle_pass_rewards_tab_point(bottom_entries) or PASS_REWARDS_TAB_FALLBACK
            if not _tap_point(context, f"{prefix}ToRew", rew_pt):
                return False
            if not sleep_with_stop(context, 0.95):
                return False

        if not self._claim_claim_all_loop(context, f"{prefix}_Rewards", max_rounds=2):
            return False

        print(f"[DailyRoutine] 通行证「{pass_label}」每日/每周任务与等级奖励检查完毕。", flush=True)
        return True

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        prefix = f"{argv.node_name}_Pass"
        img: Any = None
        pass_entered = False
        for open_attempt in range(2):
            drawer_prefix = f"{prefix}{open_attempt}" if open_attempt else prefix
            drawer_img, drawer_entries = _open_drawer(context, drawer_prefix)
            if drawer_img is None:
                if _is_stopping(context):
                    return CustomAction.RunResult(success=False)
                print("[DailyRoutine] 未能打开个人抽屉，跳过通行证领取。", flush=True)
                _return_to_lobby(context, f"{prefix}Abort")
                return CustomAction.RunResult(success=True)

            pass_pt = find_drawer_entry_point(drawer_entries, ("环游手册",)) or (155, 545)
            open_tag = f"{prefix}OpenPass{open_attempt}" if open_attempt else f"{prefix}OpenPass"
            if not _tap_point(context, open_tag, pass_pt):
                return CustomAction.RunResult(success=False)

            polled_img, matched, aborted = _poll_screen(
                context,
                lambda frame, idx, _att=open_attempt: self._is_on_pass_screen(
                    context,
                    f"{prefix}Init{_att}_{idx}",
                    frame,
                ),
                initial_delay=1.1,
                interval=0.5,
                max_checks=5,
            )
            if aborted:
                return CustomAction.RunResult(success=False)
            if matched:
                img = polled_img
                pass_entered = True
                break
            if open_attempt == 0:
                print("[DailyRoutine] 环游手册界面尚未就绪，返回大厅重试一次。", flush=True)
                _return_to_lobby(context, f"{prefix}RetryLobby")

        if not pass_entered:
            print("[DailyRoutine] 未识别到环游手册（通行证）界面，跳过。", flush=True)
            _return_to_lobby(context, f"{prefix}NotPass")
            return CustomAction.RunResult(success=True)

        title_0 = parse_battle_pass_title(_ocr_roi(context, img, f"{prefix}Title0", PASS_TITLE_ROI))
        visited_titles: set[str] = {title_0} if title_0 else set()
        if not self._claim_current_pass(context, f"{prefix}_P0", title_0 or "Pass1"):
            return CustomAction.RunResult(success=False)

        prev_img = safe_screencap(context)
        if prev_img is None:
            return CustomAction.RunResult(success=False)

        init_cards = find_battle_pass_sidebar_cards(_ocr_roi(context, prev_img, f"{prefix}InitSidebar", PASS_SIDEBAR_ROI))
        visited_card_ys = [
            card["card_point"][1]
            for card in init_cards
            if is_battle_pass_title_visited(card["label"], visited_titles)
        ]
        if not visited_card_ys:
            visited_card_ys = [PASS_SLOT_POINTS[0][1]]

        for loop_idx in range(3):
            if loop_idx == 0:
                sidebar_cards = init_cards
            else:
                sidebar_cards = find_battle_pass_sidebar_cards(
                    _ocr_roi(context, prev_img, f"{prefix}Sidebar{loop_idx}", PASS_SIDEBAR_ROI)
                )

            next_ocr_card = next(
                (
                    card
                    for card in sidebar_cards
                    if not is_battle_pass_title_visited(card["label"], visited_titles)
                    and all(abs(card["card_point"][1] - vy) >= 35 for vy in visited_card_ys)
                ),
                None,
            )

            if next_ocr_card is not None:
                target_label = next_ocr_card["label"]
                card_x, card_y = next_ocr_card["card_point"]
                text_x, text_y = next_ocr_card["text_point"]
                tap_candidates = [
                    (card_x, card_y),
                    (max(60, text_x + 15), max(210, text_y - 4)),
                    (145, card_y),
                ]
                is_ocr_target = True
            else:
                slot_pt = next(
                    (
                        pt
                        for pt in PASS_SLOT_POINTS
                        if all(abs(pt[1] - vy) >= 35 for vy in visited_card_ys)
                    ),
                    None,
                )
                if slot_pt is None:
                    break
                target_label = f"Slot{loop_idx + 2}"
                card_y = slot_pt[1]
                tap_candidates = [slot_pt] if sidebar_cards else [slot_pt, (85, slot_pt[1] + 10)]
                is_ocr_target = False

            switched = False
            left_pass_screen = False
            new_img = None
            new_title = ""
            for attempt_idx, tap_pt in enumerate(tap_candidates):
                if not _tap_point(context, f"{prefix}Slot{loop_idx}_{attempt_idx}", tap_pt):
                    return CustomAction.RunResult(success=False)
                if not sleep_with_stop(context, 1.0):
                    return CustomAction.RunResult(success=False)
                if not _dismiss_reward_popup_if_present(context, f"{prefix}SlotDismiss{loop_idx}_{attempt_idx}"):
                    return CustomAction.RunResult(success=False)

                new_img, on_pass, aborted = _poll_screen(
                    context,
                    lambda frame, idx, _li=loop_idx, _ai=attempt_idx: self._is_on_pass_screen(
                        context,
                        f"{prefix}Check{_li}_{_ai}_{idx}",
                        frame,
                    ),
                    initial_delay=0.0,
                    interval=0.45,
                    max_checks=3,
                )
                if aborted:
                    return CustomAction.RunResult(success=False)
                if not on_pass:
                    left_pass_screen = True
                    break

                new_title = parse_battle_pass_title(
                    _ocr_roi(context, new_img, f"{prefix}Title{loop_idx}_{attempt_idx}", PASS_TITLE_ROI)
                )
                switched = (bool(new_title) and not is_battle_pass_title_visited(new_title, visited_titles)) or (
                    not new_title and images_differ_in_roi(prev_img, new_img, PASS_TITLE_ROI, threshold=15.0)
                )
                if switched:
                    break

            if left_pass_screen:
                break
            if not switched:
                if is_ocr_target:
                    print(
                        f"[DailyRoutine] 尝试切换通行证「{target_label}」{len(tap_candidates)}次均未生效，结束通行证遍历。",
                        flush=True,
                    )
                break

            if new_title:
                visited_titles.add(new_title)
            if is_ocr_target:
                visited_titles.add(target_label)
            visited_card_ys.append(card_y)
            if not self._claim_current_pass(context, f"{prefix}_P{loop_idx + 1}", new_title or target_label):
                return CustomAction.RunResult(success=False)
            prev_img = safe_screencap(context)
            if prev_img is None:
                return CustomAction.RunResult(success=False)

        _return_to_lobby(context, f"{prefix}Done")
        return CustomAction.RunResult(success=not _is_stopping(context))



@AgentServer.custom_action("daily_routine_friend_support")
class DailyRoutineFriendSupportAction(CustomAction):
    """Collect friend support coins from Business Card screen and return safely to lobby."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        prefix = f"{argv.node_name}_Friend"
        img, _ = _open_drawer(context, prefix)
        if img is None:
            if _is_stopping(context):
                return CustomAction.RunResult(success=False)
            print("[DailyRoutine] 未能打开个人抽屉，跳过好友支援奖励。", flush=True)
            _return_to_lobby(context, f"{prefix}Abort")
            return CustomAction.RunResult(success=True)

        entered = False
        for attempt in range(2):
            if not _tap_point(context, f"{prefix}RailFriend{attempt}", DRAWER_FRIEND_ICON_POINT):
                return CustomAction.RunResult(success=False)
            img, matched, aborted = _poll_screen(
                context,
                lambda frame, idx, _att=attempt: is_friend_card_screen_entries(
                    _ocr_roi(context, frame, f"{prefix}Nav{_att}_{idx}", FRIEND_NAV_ROI)
                ),
                initial_delay=1.0,
                interval=0.5,
                max_checks=4,
            )
            if aborted:
                return CustomAction.RunResult(success=False)
            if matched:
                entered = True
                break

        if not entered:
            print("[DailyRoutine] 未识别到好友/名片界面，跳过支援奖励。", flush=True)
            _return_to_lobby(context, f"{prefix}Back")
            return CustomAction.RunResult(success=True)

        coin_entries = _ocr_roi(context, img, f"{prefix}CoinRoi", FRIEND_SUPPORT_COIN_ROI)
        if has_friend_support_coin_bubble(img, coin_entries):
            tap_pt = find_friend_support_coin_point(coin_entries)
            if not _tap_point(context, f"{prefix}ClaimCoin", tap_pt):
                return CustomAction.RunResult(success=False)
            if not sleep_with_stop(context, 1.05):
                return CustomAction.RunResult(success=False)
            # Dismiss strictly above the bottom-left card strip to avoid opening '修改显示'.
            if not _dismiss_reward_popup_if_present(
                context,
                f"{prefix}AfterClaim",
                dismiss_point=REWARD_POPUP_TOP_SAFE_POINT,
            ):
                return CustomAction.RunResult(success=False)
            print("[DailyRoutine] 好友名片支援金币奖励已收取。", flush=True)
        else:
            print("[DailyRoutine] 好友名片当前无待领取的支援金币。", flush=True)

        _return_to_lobby(context, f"{prefix}Done", dismiss_point=REWARD_POPUP_TOP_SAFE_POINT)
        return CustomAction.RunResult(success=not _is_stopping(context))


@AgentServer.custom_action("daily_routine_event_checkin")
class DailyRoutineEventCheckinAction(CustomAction):
    """Open Activity Hub -> 限时活动 -> 启程签到 and claim available check-in reward."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        prefix = f"{argv.node_name}_Checkin"
        if not open_activity_hub(context, prefix):
            if _is_stopping(context):
                return CustomAction.RunResult(success=False)
            print("[DailyRoutine] 未能进入活动中心，跳过限时签到。", flush=True)
            _return_to_lobby(context, f"{prefix}HubAbort")
            return CustomAction.RunResult(success=True)

        entered, had_red_dot = select_activity_tab(
            context,
            prefix,
            "限时活动",
            ("启程签到",),
            check_red_dot=True,
        )
        if not entered:
            print("[DailyRoutine] 未找到限时活动「启程签到」，跳过。", flush=True)
            _return_to_lobby(context, f"{prefix}NotFound")
            return CustomAction.RunResult(success=True)

        def _check_checkin_ready(frame: Any, idx: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
            hdr = _ocr_roi(context, frame, f"{prefix}HdrReady{idx}", CHECKIN_HEADER_ROI)
            cards = _ocr_roi(context, frame, f"{prefix}CardsReady{idx}", CHECKIN_CARDS_ROI)
            return (hdr, cards) if is_event_checkin_screen_entries(hdr, cards) else None

        init_img, init_matched, aborted = _poll_screen(
            context,
            _check_checkin_ready,
            initial_delay=0.25,
            interval=0.5,
            max_checks=4,
        )
        if aborted:
            return CustomAction.RunResult(success=False)

        claimed_any = False
        if init_matched is not None:
            for step in range(2):
                if step == 0:
                    img = init_img
                    header_entries, card_entries = init_matched
                else:
                    img = safe_screencap(context)
                    if img is None:
                        return CustomAction.RunResult(success=False)
                    header_entries = _ocr_roi(context, img, f"{prefix}Hdr{step}", CHECKIN_HEADER_ROI)
                    card_entries = _ocr_roi(context, img, f"{prefix}Cards{step}", CHECKIN_CARDS_ROI)
                    if not is_event_checkin_screen_entries(header_entries, card_entries):
                        break
                can_claim = (had_red_dot and step == 0) or is_event_checkin_first_card_highlighted(img)
                if not can_claim:
                    break
                tap_pt = find_event_checkin_first_card_point(card_entries)
                if not _tap_point(context, f"{prefix}TapDay{step}", tap_pt):
                    return CustomAction.RunResult(success=False)
                if not sleep_with_stop(context, 1.0):
                    return CustomAction.RunResult(success=False)
                if not _dismiss_reward_popup_if_present(
                    context,
                    f"{prefix}Dismiss{step}",
                    dismiss_point=REWARD_POPUP_TOP_SAFE_POINT,
                ):
                    return CustomAction.RunResult(success=False)
                claimed_any = True
                had_red_dot = False

        if claimed_any:
            print("[DailyRoutine] 限时「启程签到」已领取完成。", flush=True)
        else:
            print("[DailyRoutine] 限时「启程签到」今日已签或暂无可领项。", flush=True)

        _return_to_lobby(context, f"{prefix}Done", dismiss_point=REWARD_POPUP_TOP_SAFE_POINT)
        return CustomAction.RunResult(success=not _is_stopping(context))


@AgentServer.custom_action("daily_routine_eternal_supply")
class DailyRoutineEternalSupplyAction(CustomAction):
    """Open Mall -> 无垠补给 and claim unlocked 7-day supply reward if purchased."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        prefix = f"{argv.node_name}_Supply"
        entered, _uid = open_mall_from_lobby(context, prefix)
        if not entered:
            if _is_stopping(context):
                return CustomAction.RunResult(success=False)
            print("[DailyRoutine] 未能进入商城，跳过无垠补给检查。", flush=True)
            _return_to_lobby(context, f"{prefix}MallAbort")
            return CustomAction.RunResult(success=True)

        tab_ok, img, _tab = select_mall_tab(context, prefix, ("无垠补给",), drag_left_if_missing=True)
        if not tab_ok or img is None:
            if _is_stopping(context):
                return CustomAction.RunResult(success=False)
            print("[DailyRoutine] 商城顶栏未找到「无垠补给」，跳过。", flush=True)
            _return_to_lobby(context, f"{prefix}TabMiss")
            return CustomAction.RunResult(success=True)

        ready_img, ready, aborted = _poll_screen(
            context,
            lambda frame, idx: is_eternal_supply_page_entries(
                _ocr_roi(context, frame, f"{prefix}Hdr{idx}", ETERNAL_SUPPLY_HEADER_ROI)
            ),
            initial_delay=0.0,
            interval=0.45,
            max_checks=3,
        )
        if aborted:
            return CustomAction.RunResult(success=False)

        claimed = 0
        if ready:
            for step in range(3):
                cur_img = ready_img if (step == 0 and ready_img is not None) else safe_screencap(context)
                if cur_img is None:
                    return CustomAction.RunResult(success=False)
                grid_entries = _ocr_roi(context, cur_img, f"{prefix}Grid{step}", ETERNAL_SUPPLY_GRID_ROI)
                claim_pt = find_eternal_supply_claim_point(cur_img, grid_entries)
                if claim_pt is None:
                    break
                if not _tap_point(context, f"{prefix}Claim{step}", claim_pt):
                    return CustomAction.RunResult(success=False)
                if not sleep_with_stop(context, 0.9):
                    return CustomAction.RunResult(success=False)
                if not _dismiss_reward_popup_if_present(
                    context,
                    f"{prefix}Dismiss{step}",
                    dismiss_point=REWARD_POPUP_TOP_SAFE_POINT,
                ):
                    return CustomAction.RunResult(success=False)
                claimed += 1

        if claimed > 0:
            print(f"[DailyRoutine] 「无垠补给」已领取 {claimed} 项每日补给。", flush=True)
        else:
            print("[DailyRoutine] 「无垠补给」当前无可领取补给（未购买或今日已领），跳过。", flush=True)

        _return_to_lobby(context, f"{prefix}Done", dismiss_point=REWARD_POPUP_TOP_SAFE_POINT)
        return CustomAction.RunResult(success=not _is_stopping(context))

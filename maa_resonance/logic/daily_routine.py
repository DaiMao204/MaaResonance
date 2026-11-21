"""Pure logic and pixel/OCR helpers for Auto Daily (自动日常)."""
from __future__ import annotations

import re
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# 1280x720 ROIs and reference tap coordinates (verified on real screenshots)
# ---------------------------------------------------------------------------

LOBBY_AVATAR_POINT: tuple[int, int] = (155, 675)
# Keep bottom-right lobby ROI strictly x >= 880 so Drawer's '客运管理' (x=576) never false-matches.
LOBBY_BOTTOM_RIGHT_ROI: tuple[int, int, int, int] = (880, 620, 400, 100)
LOBBY_RIGHT_MID_ROI: tuple[int, int, int, int] = (1020, 360, 260, 240)
LOBBY_REVENUE_PILL_ROI: tuple[int, int, int, int] = (1030, 525, 240, 75)
LOBBY_REVENUE_PILL_POINT: tuple[int, int] = (1145, 562)

TOP_BACK_POINT: tuple[int, int] = (83, 36)
TOP_HOME_POINT: tuple[int, int] = (198, 36)

DRAWER_CLOSE_POINT: tuple[int, int] = (960, 360)
DRAWER_IDENT_ROI: tuple[int, int, int, int] = (80, 195, 600, 265)
DRAWER_GRID_ROI: tuple[int, int, int, int] = (100, 390, 560, 290)
DRAWER_UID_ROI: tuple[int, int, int, int] = (85, 8, 260, 45)
DRAWER_SCROLL_UP_SWIPE: tuple[int, int, int, int] = (350, 400, 350, 650)
DRAWER_MAIL_ICON_POINT: tuple[int, int] = (39, 512)

MALL_TOP_BAR_ROI: tuple[int, int, int, int] = (220, 0, 860, 75)
MALL_TOP_BAR_SWIPE_LEFT: tuple[int, int, int, int] = (960, 38, 280, 38)
ETERNAL_SUPPLY_HEADER_ROI: tuple[int, int, int, int] = (720, 90, 560, 160)
ETERNAL_SUPPLY_GRID_ROI: tuple[int, int, int, int] = (220, 240, 1040, 330)

REWARD_POPUP_TITLE_ROI: tuple[int, int, int, int] = (480, 60, 340, 200)
REWARD_POPUP_HINT_ROI: tuple[int, int, int, int] = (520, 645, 250, 65)
REWARD_POPUP_DISMISS_POINT: tuple[int, int] = (200, 660)
REWARD_POPUP_TOP_SAFE_POINT: tuple[int, int] = (640, 120)

# Friend Support Coin (好友名片支援奖励)
DRAWER_FRIEND_ICON_POINT: tuple[int, int] = (39, 289)
FRIEND_NAV_ROI: tuple[int, int, int, int] = (1080, 100, 190, 400)
FRIEND_SUPPORT_COIN_ROI: tuple[int, int, int, int] = (445, 215, 120, 125)
FRIEND_SUPPORT_COIN_FALLBACK: tuple[int, int] = (501, 285)

# Event Check-in (限时活动 · 启程签到)
CHECKIN_HEADER_ROI: tuple[int, int, int, int] = (780, 75, 480, 95)
CHECKIN_CARDS_ROI: tuple[int, int, int, int] = (530, 175, 740, 260)
CHECKIN_FIRST_CARD_FALLBACK: tuple[int, int] = (675, 340)

# Mail
MAIL_BOTTOM_ROI: tuple[int, int, int, int] = (680, 625, 500, 85)
MAIL_CLAIM_ALL_ROI: tuple[int, int, int, int] = (930, 625, 250, 85)
MAIL_CLAIM_ALL_FALLBACK: tuple[int, int] = (1068, 667)

# Dispatch (派遣委托)
DISPATCH_HEADER_ROI: tuple[int, int, int, int] = (390, 0, 260, 80)
# Strictly y <= 295 to avoid colliding with the bottom-right progress circle '已完成' at y=498.
DISPATCH_CARD_STRIP_ROI: tuple[int, int, int, int] = (30, 230, 1210, 65)
DISPATCH_CLAIM_BTN_ROI: tuple[int, int, int, int] = (880, 595, 290, 80)
DISPATCH_REPORT_TITLE_ROI: tuple[int, int, int, int] = (500, 20, 280, 90)
DISPATCH_REPORT_BTN_ROI: tuple[int, int, int, int] = (380, 600, 540, 75)

# Revenue Report & Leaderboard (营收报告 / 排行榜)
REVENUE_REPORT_TITLE_ROI: tuple[int, int, int, int] = (420, 195, 260, 65)
REVENUE_BOTTOM_TABS_ROI: tuple[int, int, int, int] = (420, 595, 620, 65)
REVENUE_STAMP_ROI: tuple[int, int, int, int] = (1140, 25, 135, 115)
REVENUE_RANKING_STAMP_POINT: tuple[int, int] = (1228, 68)
REVENUE_RANKING_STAMP_ALT_POINT: tuple[int, int] = (1236, 62)
REVENUE_LIKE_BADGE_ROI: tuple[int, int, int, int] = (640, 205, 135, 48)
REVENUE_LIMIT_TOAST_ROI: tuple[int, int, int, int] = (480, 325, 320, 70)
REVENUE_ALL_PLAYERS_TAB_FALLBACK: tuple[int, int] = (892, 628)
REVENUE_LIKE_ROW_YS: tuple[int, ...] = (294, 356, 419, 481)
REVENUE_LIKE_BTN_X: int = 791
REVENUE_LIST_SWIPE: tuple[int, int, int, int] = (700, 470, 700, 290)

# Daily Activity (每日活跃)
ACTIVITY_TOP_TABS_ROI: tuple[int, int, int, int] = (300, 0, 920, 120)
ACTIVITY_TAB_FALLBACK: tuple[int, int] = (451, 55)
ACTIVITY_SCORE_ROI: tuple[int, int, int, int] = (180, 180, 90, 50)
ACTIVITY_MILESTONE_LABEL_ROI: tuple[int, int, int, int] = (400, 120, 690, 40)
ACTIVITY_CARD_BOTTOM_ROI: tuple[int, int, int, int] = (100, 580, 1060, 80)
ACTIVITY_CHEST_XS: tuple[int, ...] = (441, 562, 683, 806, 927, 1050)
ACTIVITY_CHEST_MILESTONES: tuple[int, ...] = (100, 200, 300, 400, 500, 600)
ACTIVITY_CHEST_Y: int = 173

# Battle Pass (环游手册 / 通行证)
PASS_HEADER_ROI: tuple[int, int, int, int] = (360, 20, 260, 75)
PASS_TITLE_ROI: tuple[int, int, int, int] = (70, 488, 210, 65)
PASS_BOTTOM_TABS_ROI: tuple[int, int, int, int] = (350, 640, 480, 70)
PASS_REWARDS_TAB_FALLBACK: tuple[int, int] = (476, 668)
PASS_TASKS_TAB_FALLBACK: tuple[int, int] = (718, 668)
PASS_TASK_SUBTABS_ROI: tuple[int, int, int, int] = (380, 125, 820, 55)
PASS_DAILY_TAB_FALLBACK: tuple[int, int] = (523, 153)
PASS_WEEKLY_TAB_FALLBACK: tuple[int, int] = (948, 153)
PASS_CLAIM_ALL_ROI: tuple[int, int, int, int] = (1020, 635, 250, 75)
PASS_TASK_CLAIM_BTN_ROI: tuple[int, int, int, int] = (360, 510, 880, 65)
PASS_SLOT_POINTS: tuple[tuple[int, int], ...] = ((110, 242), (110, 318), (110, 394))
PASS_SIDEBAR_ROI: tuple[int, int, int, int] = (10, 190, 220, 250)

_DIGIT_CONFUSIONS = str.maketrans({
    "O": "0",
    "o": "0",
    "I": "1",
    "l": "1",
    "|": "1",
})


# ---------------------------------------------------------------------------
# Entry & geometry helpers
# ---------------------------------------------------------------------------

def _clean(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def _entry_box(entry: dict[str, Any]) -> tuple[int, int, int, int] | None:
    if not isinstance(entry, dict):
        return None
    box = entry.get("box")
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        try:
            return int(box[0]), int(box[1]), int(box[2]), int(box[3])
        except (TypeError, ValueError):
            return None
    if all(k in entry for k in ("x", "y", "w", "h")):
        try:
            return int(entry["x"]), int(entry["y"]), int(entry["w"]), int(entry["h"])
        except (TypeError, ValueError):
            return None
    return None


def _entry_center(entry: dict[str, Any]) -> tuple[int, int] | None:
    if isinstance(entry, dict) and "center_x" in entry and "center_y" in entry:
        try:
            return int(round(float(entry["center_x"]))), int(round(float(entry["center_y"])))
        except (TypeError, ValueError):
            pass
    box = _entry_box(entry)
    if box is None:
        return None
    x, y, w, h = box
    return int(round(x + w / 2.0)), int(round(y + h / 2.0))


def _find_entry_center(
    entries: list[dict[str, Any]],
    keywords: tuple[str, ...],
    *,
    exact: bool = False,
    excluded_keywords: tuple[str, ...] = (),
) -> tuple[int, int] | None:
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text"))
        if not cleaned:
            continue
        if any(bad in cleaned for bad in excluded_keywords):
            continue
        matched = any(cleaned == kw for kw in keywords) if exact else any(kw in cleaned for kw in keywords)
        if matched:
            center = _entry_center(entry)
            if center is not None:
                return center
    return None


def _slice_720(image: Any, x1: int, y1: int, x2: int, y2: int) -> np.ndarray | None:
    """Slice a BGR numpy image using 1280x720 reference coordinates, scaled to image size."""
    if not isinstance(image, np.ndarray) or image.ndim < 2 or image.shape[0] <= 0 or image.shape[1] <= 0:
        return None
    h, w = image.shape[:2]
    sx = w / 1280.0
    sy = h / 720.0
    ix1 = max(0, min(w - 1, int(round(x1 * sx))))
    ix2 = max(ix1 + 1, min(w, int(round(x2 * sx))))
    iy1 = max(0, min(h - 1, int(round(y1 * sy))))
    iy2 = max(iy1 + 1, min(h, int(round(y2 * sy))))
    return image[iy1:iy2, ix1:ix2]


# ---------------------------------------------------------------------------
# Pure OCR state & target parsers
# ---------------------------------------------------------------------------

def is_lobby_entries(
    bottom_right_entries: list[dict[str, Any]],
    right_mid_entries: list[dict[str, Any]] | None = None,
) -> bool:
    """Return True when lobby bottom-right / right-mid OCR markers are present."""
    bottom_texts = [_clean(e.get("text")) for e in bottom_right_entries if isinstance(e, dict)]
    if any(
        kw in txt
        for txt in bottom_texts
        for kw in ("整备列车", "客运管理", "STARTENGINE", "启程")
    ):
        return True
    if right_mid_entries:
        mid_texts = [_clean(e.get("text")) for e in right_mid_entries if isinstance(e, dict)]
        if any(kw in txt for txt in mid_texts for kw in ("作战终端", "C.R.B.S.E", "访问城市")):
            return True
    return False


def is_drawer_entries(drawer_entries: list[dict[str, Any]]) -> bool:
    """Return True when the left profile/navigation drawer is open."""
    texts = [_clean(e.get("text")) for e in drawer_entries if isinstance(e, dict)]
    if any("查看更多信息" in t or "列车长形象" in t for t in texts):
        return True
    grid_hits = sum(
        1
        for kw in ("委托", "营运总览", "运营总览", "导航手册", "环游手册")
        if any(kw in t for t in texts)
    )
    return grid_hits >= 2


def find_drawer_entry_point(
    drawer_entries: list[dict[str, Any]],
    targets: tuple[str, ...],
) -> tuple[int, int] | None:
    """Find the click point for a labeled tile inside the open drawer."""
    exact_point = _find_entry_center(drawer_entries, targets, exact=True)
    if exact_point is not None:
        return exact_point
    return _find_entry_center(drawer_entries, targets, exact=False)


def find_lobby_revenue_pill_point(entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Detect the TODAY revenue pill on the lobby right side and return its click point."""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text")).upper()
        if "TODAY" in cleaned:
            center = _entry_center(entry)
            if center is not None:
                return LOBBY_REVENUE_PILL_POINT
    return None


def has_reward_popup_entries(
    title_entries: list[dict[str, Any]],
    hint_entries: list[dict[str, Any]] | None = None,
) -> bool:
    """Return True when the '获得物品' reward overlay is visible."""
    for group in (title_entries, hint_entries or []):
        for entry in group:
            if not isinstance(entry, dict):
                continue
            cleaned = _clean(entry.get("text"))
            if "获得物品" in cleaned or "触碰空白区域退出" in cleaned:
                return True
    return False


def is_mail_screen_entries(bottom_entries: list[dict[str, Any]]) -> bool:
    """Return True when the Mail screen bottom bar ('一键领取' / '删除已读') is visible."""
    texts = [_clean(e.get("text")) for e in bottom_entries if isinstance(e, dict)]
    return any("一键领取" in t or "删除已读" in t for t in texts)


def find_mail_claim_all_point(bottom_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Find '一键领取' button center in Mail; tolerates dropped leading character and excludes '删除已读'."""
    return _find_entry_center(
        bottom_entries,
        ("一键领取", "键领取", "全部领取"),
        excluded_keywords=("删除",),
    )


def is_dispatch_screen_entries(header_entries: list[dict[str, Any]]) -> bool:
    """Return True when the Dispatch (派遣委托) header is visible."""
    texts = [_clean(e.get("text")) for e in header_entries if isinstance(e, dict)]
    return any("派遣委托" in t or "当前委托队伍" in t for t in texts)


def is_dispatch_report_entries(report_entries: list[dict[str, Any]]) -> bool:
    """Return True when the Dispatch Settlement Report (委托报告) modal is open."""
    texts = [_clean(e.get("text")).upper() for e in report_entries if isinstance(e, dict)]
    return any("委托报告" in t or "SETTLEMENT" in t for t in texts)


def find_dispatch_claim_button_point(bottom_right_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Find ONLY the green '领取奖励' button on Dispatch; never match '立即完成' or '召回'."""
    return _find_entry_center(
        bottom_right_entries,
        ("领取奖励",),
        excluded_keywords=("立即完成", "召回", "加速"),
    )


def find_completed_dispatch_card_point(card_strip_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Find a completed dispatch card ('已完成') in the top card strip."""
    return _find_entry_center(card_strip_entries, ("已完成",))


def find_dispatch_report_action_point(
    button_entries: list[dict[str, Any]],
    *,
    reassign: bool,
) -> tuple[int, int] | None:
    """Find '再次委托' (reassign=True) or '关闭' (reassign=False) on the Dispatch report modal."""
    if reassign:
        return _find_entry_center(button_entries, ("再次委托",), excluded_keywords=("关闭",))
    return _find_entry_center(button_entries, ("关闭",), excluded_keywords=("再次",))


def is_revenue_report_entries(
    title_entries: list[dict[str, Any]],
    bottom_entries: list[dict[str, Any]] | None = None,
) -> bool:
    """Return True when on the Revenue Report page (not the Leaderboard sub-page)."""
    title_texts = [_clean(e.get("text")) for e in title_entries if isinstance(e, dict)]
    if any("排行榜" in t for t in title_texts):
        return False
    if any("近期营收统计" in t for t in title_texts):
        return True
    if bottom_entries:
        bottom_texts = [_clean(e.get("text")) for e in bottom_entries if isinstance(e, dict)]
        if any("全部玩家" in t or "好友" in t for t in bottom_texts):
            return False
        if any("营收统计" in t or "营收占比" in t for t in bottom_texts):
            return True
    return False


def is_tiger_wealth_ranking_entries(title_entries: list[dict[str, Any]]) -> bool:
    """Return True when on the '虎闰千富榜' sub-leaderboard rather than '营收总和排行榜'."""
    title_texts = [_clean(e.get("text")) for e in title_entries if isinstance(e, dict)]
    return any(
        kw in t
        for t in title_texts
        for kw in ("虎闰", "虎润", "虎闹", "千富")
    )


def is_revenue_ranking_entries(
    title_entries: list[dict[str, Any]],
    bottom_entries: list[dict[str, Any]] | None = None,
) -> bool:
    """Return True when on the Revenue Leaderboard (营收总和排行榜) screen, rejecting 虎闰千富榜."""
    if is_tiger_wealth_ranking_entries(title_entries):
        return False
    title_texts = [_clean(e.get("text")) for e in title_entries if isinstance(e, dict)]
    if any("排行榜" in t for t in title_texts):
        return True
    if bottom_entries:
        bottom_texts = [_clean(e.get("text")) for e in bottom_entries if isinstance(e, dict)]
        if any("全部玩家" in t or "好友" in t for t in bottom_texts):
            return True
    return False


def find_revenue_ranking_stamp_point(stamp_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Find the top-right '排行榜' (or OCR '排行磅') stamp and shift up-right clear of '虎闰千富'."""
    for entry in stamp_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text"))
        if re.search(r"排行[榜磅]", cleaned) or "排行" in cleaned:
            center = _entry_center(entry)
            if center is not None:
                cx, cy = center
                tx = min(1255, max(1220, cx + 18))
                ty = max(52, min(74, cy - 28))
                return tx, ty
    return None


def parse_like_progress(badge_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Parse daily like counter such as '1/3?' or '3/3？' into (current, total)."""
    for entry in badge_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text")).translate(_DIGIT_CONFUSIONS)
        match = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", cleaned)
        if not match:
            continue
        current = int(match.group(1))
        total = int(match.group(2))
        if total > 0 and 0 <= current <= total:
            return current, total
    return None


def has_like_limit_toast(toast_entries: list[dict[str, Any]]) -> bool:
    """Return True when '点赞数量已达上限' banner is visible."""
    texts = [_clean(e.get("text")) for e in toast_entries if isinstance(e, dict)]
    return any("已达上限" in t or "点赞数量" in t for t in texts)


def find_all_players_tab_point(bottom_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Find the '全部玩家' bottom tab on the Revenue Leaderboard."""
    return _find_entry_center(bottom_entries, ("全部玩家",))


def is_daily_activity_panel_entries(tab_entries: list[dict[str, Any]]) -> bool:
    """Return True when any of the 4 Navigation Manual top tabs is visible."""
    texts = [_clean(e.get("text")) for e in tab_entries if isinstance(e, dict)]
    return any(
        kw in t
        for t in texts
        for kw in ("每日活跃", "导航手册", "行动汇总", "拼单单")
    )


def is_daily_activity_tab_active(
    milestone_entries: list[dict[str, Any]],
    card_bottom_entries: list[dict[str, Any]] | None = None,
) -> bool:
    """Return True when currently viewing the 每日活跃 tab contents."""
    milestone_texts = {_clean(e.get("text")).translate(_DIGIT_CONFUSIONS) for e in milestone_entries if isinstance(e, dict)}
    expected_milestones = {"100", "200", "300", "400", "500", "600"}
    if len(milestone_texts & expected_milestones) >= 2:
        return True
    if card_bottom_entries:
        bottom_texts = [_clean(e.get("text")) for e in card_bottom_entries if isinstance(e, dict)]
        if any(kw in t for t in bottom_texts for kw in ("可领取", "未完成", "前往")):
            return True
    return False


def find_daily_activity_tab_point(tab_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Find the '每日活跃' top tab point."""
    return _find_entry_center(tab_entries, ("每日活跃",))


def find_daily_activity_claim_point(card_bottom_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Find a yellow '可领取' card button; never matches '已领取', '前往', or '未完成'."""
    return _find_entry_center(
        card_bottom_entries,
        ("可领取",),
        excluded_keywords=("已领取", "前往", "未完成"),
    )


def parse_daily_activity_score(score_entries: list[dict[str, Any]]) -> int | None:
    """Parse current activity score (e.g. '650') from the top-left score badge."""
    for entry in score_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text")).translate(_DIGIT_CONFUSIONS)
        match = re.fullmatch(r"\d{1,4}", cleaned)
        if match:
            return int(cleaned)
    return None


def is_battle_pass_screen_entries(
    header_entries: list[dict[str, Any]],
    bottom_tab_entries: list[dict[str, Any]] | None = None,
) -> bool:
    """Return True when inside any Battle Pass (环游手册 / 开拓手册) page."""
    header_texts = [_clean(e.get("text")) for e in header_entries if isinstance(e, dict)]
    if any("环游手册等级" in t or "手册等级" in t for t in header_texts):
        return True
    if bottom_tab_entries:
        tab_texts = [_clean(e.get("text")) for e in bottom_tab_entries if isinstance(e, dict)]
        has_tasks = any("任务列表" in t for t in tab_texts)
        has_pass = any("手册" in t for t in tab_texts)
        if has_tasks and has_pass:
            return True
    return False


def parse_battle_pass_title(title_entries: list[dict[str, Any]]) -> str:
    """Extract the active Battle Pass season title (e.g. '自箱庭来') from PASS_TITLE_ROI."""
    ignored = ("环游手册", "进阶无垠手册", "剩余时间")
    parts: list[str] = []
    for entry in title_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text"))
        if not cleaned or any(kw in cleaned for kw in ignored):
            continue
        parts.append(cleaned)
    return "".join(parts)


def _strip_pass_label(text: Any) -> str:
    return re.sub(r"[·!！|.,:\-_：\s]+", "", str(text or "")).strip()


def is_battle_pass_title_visited(label: str, visited_titles: set[str]) -> bool:
    """Return True if a Battle Pass title or sidebar card label matches any already-visited pass."""
    cleaned = _strip_pass_label(label)
    if not cleaned:
        return False
    cleaned_chars = set(cleaned)
    for raw_seen in visited_titles:
        seen = _strip_pass_label(raw_seen)
        if not seen:
            continue
        if cleaned == seen:
            return True
        if len(cleaned) >= 2 and len(seen) >= 2:
            if cleaned in seen or seen in cleaned:
                return True
            seen_chars = set(seen)
            common = sum(1 for ch in cleaned_chars if ch in seen_chars)
            denom = min(len(cleaned_chars), len(seen_chars))
            if common >= 2 and denom > 0 and (common / denom) >= 0.65:
                return True
    return False


def find_battle_pass_sidebar_cards(sidebar_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse left-sidebar Battle Pass cards (e.g. 自箱庭来, 解惑之旅) from PASS_SIDEBAR_ROI."""
    ignored = ("环游手册", "进阶", "剩余时间", "标准手册", "开拓手册", "任务列表", "购买等级")
    candidates: list[dict[str, Any]] = []
    for entry in sidebar_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _strip_pass_label(entry.get("text"))
        if len(cleaned) < 2 or re.fullmatch(r"[0-9A-Za-z]+", cleaned):
            continue
        if any(kw in cleaned for kw in ignored):
            continue
        center = _entry_center(entry)
        if center is None:
            continue
        cx, cy = center
        if not (195 <= cy <= 450):
            continue
        card_y = max(215, min(420, cy - 18))
        candidates.append(
            {
                "label": cleaned,
                "text_point": (cx, cy),
                "card_point": (110, card_y),
            }
        )

    candidates.sort(key=lambda item: item["text_point"][1])
    deduped: list[dict[str, Any]] = []
    for item in candidates:
        if deduped and abs(item["text_point"][1] - deduped[-1]["text_point"][1]) < 40:
            if len(item["label"]) > len(deduped[-1]["label"]):
                deduped[-1] = item
            continue
        deduped.append(item)
    return deduped


def find_battle_pass_rewards_tab_point(bottom_tab_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Find the bottom-left '环游手册' / '开拓手册' rewards tab point."""
    return _find_entry_center(
        bottom_tab_entries,
        ("环游手册", "开拓手册", "手册"),
        excluded_keywords=("等级", "进阶", "任务"),
    )


def find_battle_pass_tasks_tab_point(bottom_tab_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Find the bottom '任务列表' tab point."""
    return _find_entry_center(bottom_tab_entries, ("任务列表",))


def find_battle_pass_daily_tab_point(subtab_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Find the '每日任务' sub-tab point inside 任务列表."""
    return _find_entry_center(subtab_entries, ("每日任务",))


def find_battle_pass_weekly_tab_point(subtab_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Find the '每周任务' sub-tab point inside 任务列表."""
    return _find_entry_center(subtab_entries, ("每周任务",))


def find_battle_pass_claim_all_point(claim_all_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Find bottom-right '一键领取' / '全部领取' button (tolerating missing '一'); excludes purchase/upgrade."""
    return _find_entry_center(
        claim_all_entries,
        ("一键领取", "键领取", "全部领取", "部领取", "一键领", "键领", "领取"),
        excluded_keywords=("购买", "进阶", "等级", "已领取", "已领"),
    )


def find_battle_pass_single_claim_point(card_entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Find an individual task card's yellow '领取' button as a fallback."""
    return _find_entry_center(
        card_entries,
        ("领取",),
        exact=True,
        excluded_keywords=("已领取", "一键领取", "前往", "购买", "进阶"),
    )


# ---------------------------------------------------------------------------
# Pure numpy/pixel classifiers (BGR image input)
# ---------------------------------------------------------------------------

def is_top_home_button_visible(image: Any) -> bool:
    """Return True when the white/light-gray top-left train Home button at (198, 36) is visible."""
    patch = _slice_720(image, 175, 22, 220, 50)
    if patch is None:
        return False
    b = patch[:, :, 0].astype(np.float32)
    g = patch[:, :, 1].astype(np.float32)
    r = patch[:, :, 2].astype(np.float32)
    chroma = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    pill_ratio = float(np.mean((r > 130) & (g > 130) & (b > 130) & (chroma < 30)))
    return pill_ratio >= 0.45


def is_all_players_tab_selected(image: Any) -> bool:
    """Return True when the '全部玩家' leaderboard tab is highlighted in active blue."""
    patch = _slice_720(image, 760, 610, 830, 645)
    if patch is None:
        return False
    b = patch[:, :, 0].astype(np.float32)
    r = patch[:, :, 2].astype(np.float32)
    blue_ratio = float(np.mean((b > 180) & (b - r > 90)))
    return blue_ratio >= 0.45


def classify_leaderboard_like_slot(image: Any, cy: int) -> str:
    """Classify a leaderboard row's like button at y=cy as 'liked', 'unliked', or 'none'."""
    patch = _slice_720(image, 770, cy - 18, 812, cy + 18)
    if patch is None:
        return "none"
    b = patch[:, :, 0].astype(np.float32)
    g = patch[:, :, 1].astype(np.float32)
    r = patch[:, :, 2].astype(np.float32)
    pink = float(np.mean((r > 195) & (g < 170) & (b > 130) & (r - g > 45)))
    if pink >= 0.30:
        return "liked"
    chroma = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    gray_thumb = float(np.mean((r > 70) & (r < 165) & (chroma < 25)))
    white_bg = float(np.mean((r > 230) & (g > 230) & (b > 230)))
    if pink < 0.10 and gray_thumb >= 0.08 and white_bg >= 0.35:
        return "unliked"
    return "none"


def find_unliked_leaderboard_points(image: Any) -> list[tuple[int, int]]:
    """Return clickable (x, y) coordinates for all visible unliked leaderboard rows."""
    return [
        (REVENUE_LIKE_BTN_X, cy)
        for cy in REVENUE_LIKE_ROW_YS
        if classify_leaderboard_like_slot(image, cy) == "unliked"
    ]


def classify_activity_chest(image: Any, cx: int) -> str:
    """Classify a milestone chest circle at x=cx as 'claimable', 'locked', 'claimed', or 'unknown'."""
    patch = _slice_720(image, cx - 16, 160, cx + 16, 196)
    if patch is None:
        return "unknown"
    b = patch[:, :, 0].astype(np.float32)
    g = patch[:, :, 1].astype(np.float32)
    r = patch[:, :, 2].astype(np.float32)
    yellow = float(np.mean((r > 200) & (g > 150) & (b < 80)))
    if yellow >= 0.18:
        return "claimable"
    blue = float(np.mean((b > 200) & (g > 100) & (r < 110)))
    if blue >= 0.25:
        return "locked"
    slate = float(np.mean((r > 50) & (r < 140) & (b > r + 15) & (b < 185)))
    if slate >= 0.45:
        return "claimed"
    return "unknown"


def find_claimable_activity_chests(image: Any) -> list[dict[str, Any]]:
    """Return claimable milestone chests in ascending milestone order."""
    claimable: list[dict[str, Any]] = []
    for milestone, cx in zip(ACTIVITY_CHEST_MILESTONES, ACTIVITY_CHEST_XS):
        if classify_activity_chest(image, cx) == "claimable":
            claimable.append({"milestone": milestone, "x": cx, "y": ACTIVITY_CHEST_Y})
    return claimable


def _white_ratio_in_720(image: Any, x1: int, y1: int, x2: int, y2: int) -> float:
    patch = _slice_720(image, x1, y1, x2, y2)
    if patch is None:
        return 0.0
    b = patch[:, :, 0].astype(np.float32)
    g = patch[:, :, 1].astype(np.float32)
    r = patch[:, :, 2].astype(np.float32)
    return float(np.mean((r > 200) & (g > 200) & (b > 200)))


def _cream_ratio_in_720(image: Any, x1: int, y1: int, x2: int, y2: int) -> float:
    patch = _slice_720(image, x1, y1, x2, y2)
    if patch is None:
        return 0.0
    b = patch[:, :, 0].astype(np.float32)
    g = patch[:, :, 1].astype(np.float32)
    r = patch[:, :, 2].astype(np.float32)
    return float(np.mean((r > 200) & (g > 190) & (b > 170)))


def is_battle_pass_rewards_tab_selected(image: Any) -> bool:
    """Return True when the bottom '环游手册' rewards tab is white-highlighted."""
    return _white_ratio_in_720(image, 365, 655, 405, 695) >= 0.60


def is_battle_pass_tasks_tab_selected(image: Any) -> bool:
    """Return True when the bottom '任务列表' tab is white-highlighted."""
    return _white_ratio_in_720(image, 760, 655, 810, 695) >= 0.60


def is_battle_pass_daily_tab_selected(image: Any) -> bool:
    """Return True when the '每日任务' sub-tab is highlighted in light cream."""
    return _cream_ratio_in_720(image, 380, 135, 460, 175) >= 0.50


def is_battle_pass_weekly_tab_selected(image: Any) -> bool:
    """Return True when the '每周任务' sub-tab is highlighted in light cream."""
    return _cream_ratio_in_720(image, 820, 135, 880, 175) >= 0.50


def images_differ_in_roi(
    img_a: Any,
    img_b: Any,
    roi: tuple[int, int, int, int],
    threshold: float = 15.0,
) -> bool:
    """Return True when mean absolute pixel difference inside a 1280x720 ROI exceeds threshold."""
    x, y, w, h = roi
    patch_a = _slice_720(img_a, x, y, x + w, y + h)
    patch_b = _slice_720(img_b, x, y, x + w, y + h)
    if patch_a is None or patch_b is None or patch_a.shape != patch_b.shape:
        return False
    diff = float(np.mean(np.abs(patch_a.astype(np.float32) - patch_b.astype(np.float32))))
    return diff >= float(threshold)


def is_friend_card_screen_entries(nav_entries: list[dict[str, Any]]) -> bool:
    """Return True when the Friend / Business Card right-hand menu is visible."""
    texts = [_clean(e.get("text")) for e in nav_entries if isinstance(e, dict)]
    hits = sum(1 for kw in ("我的名片", "好友列表", "添加好友", "好友申请") if any(kw in t for t in texts))
    return hits >= 2


def has_friend_support_coin_bubble(
    image: Any,
    coin_entries: list[dict[str, Any]] | None = None,
) -> bool:
    """Return True when the white support-reward coin bubble is visible on the Friend Card screen."""
    patch = _slice_720(image, 455, 225, 550, 320)
    if patch is not None and patch.size > 0:
        b = patch[:, :, 0].astype(np.float32)
        g = patch[:, :, 1].astype(np.float32)
        r = patch[:, :, 2].astype(np.float32)
        white_ratio = float(np.mean((r > 220) & (g > 220) & (b > 220)))
        if white_ratio >= 0.20:
            return True
    if coin_entries:
        for entry in coin_entries:
            if not isinstance(entry, dict):
                continue
            cleaned = _clean(entry.get("text")).upper()
            if re.search(r"\d+(?:\.\d+)?[KM]?", cleaned):
                return True
    return False


def find_friend_support_coin_point(coin_entries: list[dict[str, Any]]) -> tuple[int, int]:
    """Locate the support-reward coin bubble tap point."""
    for entry in coin_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text")).upper()
        if re.search(r"\d+(?:\.\d+)?[KM]?", cleaned):
            center = _entry_center(entry)
            if center is not None:
                return center[0], max(235, center[1] - 18)
    return FRIEND_SUPPORT_COIN_FALLBACK


def is_event_checkin_screen_entries(
    header_entries: list[dict[str, Any]],
    card_entries: list[dict[str, Any]],
) -> bool:
    """Return True when the '启程签到' sign-in event panel is visible."""
    header_texts = [_clean(e.get("text")) for e in header_entries if isinstance(e, dict)]
    if any("启程签到" in t for t in header_texts):
        return True
    card_texts = [_clean(e.get("text")).upper() for e in card_entries if isinstance(e, dict)]
    day_hits = sum(1 for t in card_texts if re.search(r"\d+\s*DAY", t))
    return day_hits >= 2


def find_event_checkin_first_card_point(card_entries: list[dict[str, Any]]) -> tuple[int, int]:
    """Find the leftmost DAY card center on the Event Check-in screen."""
    candidates: list[tuple[int, int, int]] = []
    for entry in card_entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text")).upper()
        if re.search(r"\d+\s*DAY", cleaned):
            center = _entry_center(entry)
            if center is not None:
                candidates.append((center[0], center[0], center[1]))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        _, cx, cy = candidates[0]
        return cx, min(500, cy + 120)
    return CHECKIN_FIRST_CARD_FALLBACK


def is_event_checkin_first_card_highlighted(image: Any) -> bool:
    """Return True when the leftmost DAY card top bar shows the bright cyan claimable highlight."""
    patch = _slice_720(image, 580, 178, 820, 200)
    if patch is None or patch.size == 0:
        return False
    b = patch[:, :, 0].astype(np.float32)
    g = patch[:, :, 1].astype(np.float32)
    r = patch[:, :, 2].astype(np.float32)
    cyan_ratio = float(np.mean((b > 180) & (g > 150) & (b - r > 70)))
    return cyan_ratio >= 0.20


def parse_drawer_uid(entries: list[dict[str, Any]]) -> str:
    """Extract 6-14 digit account UID from the open drawer's top-left UID OCR entries."""
    cleaned_items: list[tuple[int, int, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text")).translate(_DIGIT_CONFUSIONS).upper()
        if not cleaned:
            continue
        m = re.search(r"UID[:：]?(\d{6,14})", cleaned)
        if m:
            return m.group(1)
        if re.fullmatch(r"\d{6,14}", cleaned):
            return cleaned
        center = _entry_center(entry)
        cx, cy = center if center is not None else (0, 0)
        cleaned_items.append((cy, cx, cleaned))

    cleaned_items.sort(key=lambda item: (item[0] // 20, item[1]))
    joined = "".join(item[2] for item in cleaned_items)
    m = re.search(r"UID[:：]?(\d{6,14})", joined)
    if m:
        return m.group(1)
    digits_m = re.search(r"(\d{6,14})", joined)
    return digits_m.group(1) if digits_m else ""


def is_mall_top_bar_entries(entries: list[dict[str, Any]]) -> bool:
    """Return True when the Mall top navigation bar tabs are visible."""
    markers = (
        "星选推荐",
        "桦石专柜",
        "特惠礼包",
        "惠礼包",
        "无垠补给",
        "限定服装",
        "外观车间",
        "总部商店",
        "赴命商店",
    )
    texts = [_clean(e.get("text")) for e in entries if isinstance(e, dict)]
    return any(m in t for t in texts for m in markers)


def find_mall_tab_entry(
    entries: list[dict[str, Any]],
    keywords: tuple[str, ...],
) -> dict[str, Any] | None:
    """Find the first Mall top bar entry matching any keyword with valid box/center."""
    for kw in keywords:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            cleaned = _clean(entry.get("text"))
            if not cleaned or kw not in cleaned:
                continue
            if _entry_box(entry) is not None or _entry_center(entry) is not None:
                return entry
    return None


def has_mall_tab_red_dot(image: Any, tab_entry: dict[str, Any] | None) -> bool:
    """Return True when the red notification dot at top-right of a Mall tab is visible."""
    if not isinstance(tab_entry, dict):
        return False
    box = _entry_box(tab_entry)
    if box is None:
        center = _entry_center(tab_entry)
        if center is None:
            return False
        x1, y1, x2, y2 = center[0] + 20, max(0, center[1] - 28), center[0] + 65, center[1] + 8
    else:
        bx, by, bw, _bh = box
        x1 = bx + bw - 8
        x2 = bx + bw + 32
        y1 = max(0, by - 16)
        y2 = by + 20
    patch = _slice_720(image, x1, y1, x2, y2)
    if patch is None or patch.size == 0:
        return False
    b = patch[:, :, 0].astype(np.float32)
    g = patch[:, :, 1].astype(np.float32)
    r = patch[:, :, 2].astype(np.float32)
    red_ratio = float(np.mean((r > 170) & (g < 80) & (b < 80)))
    return red_ratio >= 0.04


def is_eternal_supply_page_entries(entries: list[dict[str, Any]]) -> bool:
    """Return True when the '无垠补给礼包7日' daily claim screen is visible."""
    texts = [_clean(e.get("text")).upper() for e in entries if isinstance(e, dict)]
    return any("无垠补给" in t or "ETERNALSUPPLY" in t or "累计登录7日" in t for t in texts)


def find_eternal_supply_claim_point(
    image: Any,
    grid_entries: list[dict[str, Any]],
) -> tuple[int, int] | None:
    """Locate an active orange '领取' button inside the 7-day Eternal Supply grid."""
    for entry in grid_entries:
        if not isinstance(entry, dict):
            continue
        if _clean(entry.get("text")) != "领取":
            continue
        center = _entry_center(entry)
        if center is None:
            continue
        cx, cy = center
        # Strictly exclude the bottom-right purchase button area (y >= 585).
        if cy >= 565:
            continue
        patch = _slice_720(image, cx - 35, cy - 35, cx + 35, cy + 25)
        if patch is not None:
            if patch.size == 0:
                continue
            b = patch[:, :, 0].astype(np.float32)
            g = patch[:, :, 1].astype(np.float32)
            r = patch[:, :, 2].astype(np.float32)
            orange_ratio = float(np.mean((r > 200) & (g > 110) & (g < 200) & (b < 70)))
            if orange_ratio < 0.30:
                continue
        return cx, cy
    return None

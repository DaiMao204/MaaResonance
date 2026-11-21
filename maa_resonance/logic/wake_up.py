"""Pure logic and OCR helpers for WakeUp (开始唤醒 / 过登录与弹窗进大厅)."""
from __future__ import annotations

import re
from typing import Any

WAKEUP_DOWNLOAD_CONFIRM_POINT: tuple[int, int] = (640, 505)
WAKEUP_NEWS_DISMISS_POINT: tuple[int, int] = (640, 680)
WAKEUP_TITLE_TAP_POINT: tuple[int, int] = (640, 520)
WAKEUP_POPUP_SAFE_POINT: tuple[int, int] = (640, 680)
WAKEUP_BLIND_DISMISS_POINT: tuple[int, int] = (640, 680)
WAKEUP_POPUP_DISMISS_POINTS: tuple[tuple[int, int], ...] = (
    (640, 680),
    (200, 660),
    (40, 360),
    (640, 120),
)


def _clean(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def _entry_center(entry: dict[str, Any]) -> tuple[int, int] | None:
    if not isinstance(entry, dict):
        return None
    if "center_x" in entry and "center_y" in entry:
        try:
            return int(round(float(entry["center_x"]))), int(round(float(entry["center_y"])))
        except (TypeError, ValueError):
            pass
    box = entry.get("box")
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        try:
            return int(round(int(box[0]) + int(box[2]) / 2.0)), int(round(int(box[1]) + int(box[3]) / 2.0))
        except (TypeError, ValueError):
            return None
    if all(k in entry for k in ("x", "y", "w", "h")):
        try:
            return int(round(int(entry["x"]) + int(entry["w"]) / 2.0)), int(round(int(entry["y"]) + int(entry["h"]) / 2.0))
        except (TypeError, ValueError):
            return None
    return None


def parse_resource_download_mb(entries: list[dict[str, Any]]) -> float | None:
    """Return download size in MB when resource download prompt is visible."""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text")).upper()
        if "下载资源包" not in cleaned and "需要下载资源" not in cleaned:
            continue
        match = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB|KB)", cleaned)
        if not match:
            return 0.0
        val = float(match.group(1))
        unit = match.group(2)
        if unit == "GB":
            return val * 1024.0
        if unit == "KB":
            return val / 1024.0
        return val
    return None


def is_login_auth_blocker(entries: list[dict[str, Any]]) -> bool:
    """Return True when login credentials, CAPTCHA, or real-name auth require manual user input."""
    texts = [_clean(e.get("text")) for e in entries if isinstance(e, dict)]
    blockers = ("验证码", "请输入密码", "手机号登录", "实名认证", "扫码登录", "账号登录", "请输入账号")
    return any(b in t for t in texts for b in blockers)


def is_news_announcement_popup(entries: list[dict[str, Any]]) -> bool:
    """Return True when the title screen '资讯 | 公告' dialog is visible."""
    texts = [_clean(e.get("text")) for e in entries if isinstance(e, dict)]
    if any("触碰空白区域退出" in t for t in texts) and any("资讯" in t or "公告" in t for t in texts):
        return True
    has_news = any("资讯" in t for t in texts)
    has_ann = any("公告" in t for t in texts)
    if has_news and has_ann:
        return True
    return any(kw in t for t in texts for kw in ("更新公告", "活动公告", "维护公告"))


def is_title_start_screen(entries: list[dict[str, Any]]) -> bool:
    """Return True when the title '点击屏幕进入游戏' screen is visible."""
    texts = [_clean(e.get("text")) for e in entries if isinstance(e, dict)]
    return any(
        kw in t
        for t in texts
        for kw in ("点击屏幕进入游戏", "点击任意位置进入游戏", "下载已经完成")
    )


def is_loading_screen(entries: list[dict[str, Any]]) -> bool:
    """Return True when a loading progress bar or percentage overlay is active."""
    texts = [_clean(e.get("text")) for e in entries if isinstance(e, dict)]
    if any(kw in t for t in texts for kw in ("正在加载", "正在检查", "资源解压")):
        return True
    return any(re.fullmatch(r"\d{1,3}(?:\.\d+)?%", t) for t in texts)


def is_game_screen_entries(entries: list[dict[str, Any]]) -> bool:
    """Return True when full-screen OCR shows any recognizable game state (not OS launcher)."""
    texts = [_clean(e.get("text")).upper() for e in entries if isinstance(e, dict)]
    game_markers = (
        "整备列车",
        "客运管理",
        "STARTENGINE",
        "点击屏幕进入游戏",
        "下载资源包",
        "资讯",
        "公告",
        "活动",
        "限时活动",
        "访问城市",
        "访问地区",
        "作息",
        "作战终端",
        "RESONANCESOLSTICE",
    )
    return any(m in t for t in texts for m in game_markers) or is_loading_screen(entries)


def choose_wake_up_action(
    full_entries: list[dict[str, Any]],
    *,
    max_download_mb: float = 200.0,
    auto_confirm_small_update: bool = True,
    allow_blind_dismiss: bool = True,
    unknown_streak: int = 0,
    dismiss_attempt: int = 0,
) -> dict[str, Any]:
    """Decide the next WakeUp action from full-screen OCR entries."""
    if is_login_auth_blocker(full_entries):
        return {"action": "stop_auth", "point": None}

    dl_mb = parse_resource_download_mb(full_entries)
    if dl_mb is not None:
        if auto_confirm_small_update and dl_mb <= max_download_mb:
            confirm_pt = WAKEUP_DOWNLOAD_CONFIRM_POINT
            for entry in full_entries:
                if isinstance(entry, dict) and _clean(entry.get("text")) in ("确认", "确定"):
                    center = _entry_center(entry)
                    if center is not None:
                        confirm_pt = center
                        break
            return {"action": "confirm_download", "point": confirm_pt, "size_mb": dl_mb}
        return {"action": "stop_large_download", "point": None, "size_mb": dl_mb}

    dismiss_pt = WAKEUP_POPUP_DISMISS_POINTS[
        max(0, int(dismiss_attempt)) % len(WAKEUP_POPUP_DISMISS_POINTS)
    ]

    if is_news_announcement_popup(full_entries):
        return {
            "action": "dismiss_news",
            "point": WAKEUP_NEWS_DISMISS_POINT if dismiss_attempt <= 0 else dismiss_pt,
        }

    if is_title_start_screen(full_entries):
        return {"action": "tap_title", "point": WAKEUP_TITLE_TAP_POINT}

    texts = [_clean(e.get("text")) for e in full_entries if isinstance(e, dict)]
    if any(
        kw in t
        for t in texts
        for kw in ("获得物品", "触碰空白区域退出", "点击空白处关闭", "点击任意位置继续", "月卡", "每日签到", "签到奖励")
    ):
        return {"action": "dismiss_popup", "point": dismiss_pt}

    if is_loading_screen(full_entries):
        return {"action": "wait", "point": None}

    if allow_blind_dismiss and unknown_streak >= 2:
        return {"action": "blind_dismiss", "point": dismiss_pt}

    return {"action": "wait", "point": None}

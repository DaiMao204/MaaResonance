"""Shared Lobby, Drawer, and Reward Popup navigation helpers."""
from __future__ import annotations

from typing import Any

from maa.context import Context

from agent.utils.action_helpers import ocr_roi, poll_screen, tap_point
from agent.utils.input_guard import safe_screencap, sleep_with_stop
from maa_resonance.logic.daily_routine import (
    DISPATCH_REPORT_BTN_ROI,
    DISPATCH_REPORT_TITLE_ROI,
    DRAWER_CLOSE_POINT,
    DRAWER_GRID_ROI,
    DRAWER_IDENT_ROI,
    LOBBY_AVATAR_POINT,
    LOBBY_BOTTOM_RIGHT_ROI,
    LOBBY_RIGHT_MID_ROI,
    REWARD_POPUP_DISMISS_POINT,
    REWARD_POPUP_HINT_ROI,
    REWARD_POPUP_TITLE_ROI,
    TOP_BACK_POINT,
    TOP_HOME_POINT,
    find_dispatch_report_action_point,
    has_reward_popup_entries,
    images_differ_in_roi,
    is_dispatch_report_entries,
    is_drawer_entries,
    is_lobby_entries,
    is_top_home_button_visible,
)


def is_stopping(context: Context) -> bool:
    """Return True when the current MaaFramework tasker is stopping."""
    tasker = getattr(context, "tasker", None)
    return getattr(tasker, "stopping", False) is True


def dismiss_reward_popup_if_present(
    context: Context,
    prefix: str,
    image: Any = None,
    *,
    max_taps: int = 2,
    dismiss_point: tuple[int, int] = REWARD_POPUP_DISMISS_POINT,
) -> bool:
    """Dismiss '获得物品' reward overlay if visible. Returns False only on stop."""
    for idx in range(max_taps):
        cur_img = image if (idx == 0 and image is not None) else safe_screencap(context)
        if cur_img is None:
            return not is_stopping(context)
        title_entries = ocr_roi(context, cur_img, f"{prefix}RewardTitle{idx}", REWARD_POPUP_TITLE_ROI)
        hint_entries = ocr_roi(context, cur_img, f"{prefix}RewardHint{idx}", REWARD_POPUP_HINT_ROI)
        if not has_reward_popup_entries(title_entries, hint_entries):
            return True
        if not tap_point(context, f"{prefix}RewardDismiss{idx}", dismiss_point):
            return False
        if not sleep_with_stop(context, 0.55):
            return False
        image = None
    return True


def is_lobby(context: Context, prefix: str, image: Any) -> bool:
    """Return True when the train lobby screen is visible."""
    bottom_entries = ocr_roi(context, image, f"{prefix}LobbyBot", LOBBY_BOTTOM_RIGHT_ROI)
    if is_lobby_entries(bottom_entries):
        return True
    mid_entries = ocr_roi(context, image, f"{prefix}LobbyMid", LOBBY_RIGHT_MID_ROI)
    return is_lobby_entries(bottom_entries, mid_entries)


def is_drawer(context: Context, prefix: str, image: Any) -> tuple[bool, list[dict[str, Any]]]:
    """Return ``(is_open, combined_entries)`` for the left profile/navigation drawer."""
    ident_entries = ocr_roi(context, image, f"{prefix}DrawerIdent", DRAWER_IDENT_ROI)
    grid_entries = ocr_roi(context, image, f"{prefix}DrawerGrid", DRAWER_GRID_ROI)
    combined = ident_entries + grid_entries
    return is_drawer_entries(combined), combined


def return_to_lobby(
    context: Context,
    prefix: str,
    max_steps: int = 6,
    *,
    dismiss_point: tuple[int, int] = REWARD_POPUP_DISMISS_POINT,
) -> bool:
    """Navigate back to the train lobby from any subpage/drawer/modal."""
    last_action: str | None = None
    for step in range(max_steps):
        img = safe_screencap(context)
        if img is None:
            return False

        # Check drawer BEFORE lobby so background lobby text on the right cannot trigger early.
        drawer_open, _ = is_drawer(context, f"{prefix}Ret{step}", img)
        if drawer_open:
            if not tap_point(context, f"{prefix}CloseDrawer{step}", DRAWER_CLOSE_POINT):
                return False
            last_action = "drawer"
            if not sleep_with_stop(context, 0.75):
                return False
            continue

        if is_lobby(context, f"{prefix}Ret{step}", img):
            return True

        reward_title = ocr_roi(context, img, f"{prefix}RetRewardT{step}", REWARD_POPUP_TITLE_ROI)
        reward_hint = ocr_roi(context, img, f"{prefix}RetRewardH{step}", REWARD_POPUP_HINT_ROI)
        if has_reward_popup_entries(reward_title, reward_hint):
            if not tap_point(context, f"{prefix}RetRewardTap{step}", dismiss_point):
                return False
            last_action = "reward"
            if not sleep_with_stop(context, 0.55):
                return False
            continue

        report_title = ocr_roi(context, img, f"{prefix}RetDispRep{step}", DISPATCH_REPORT_TITLE_ROI)
        if is_dispatch_report_entries(report_title):
            btn_entries = ocr_roi(context, img, f"{prefix}RetDispBtn{step}", DISPATCH_REPORT_BTN_ROI)
            close_pt = find_dispatch_report_action_point(btn_entries, reassign=False) or (501, 640)
            if not tap_point(context, f"{prefix}RetDispClose{step}", close_pt):
                return False
            last_action = "dispatch_report"
            if not sleep_with_stop(context, 0.7):
                return False
            continue

        use_home = is_top_home_button_visible(img) and last_action != "home"
        tap_pt = TOP_HOME_POINT if use_home else TOP_BACK_POINT
        last_action = "home" if use_home else "back"
        if not tap_point(context, f"{prefix}Nav{step}", tap_pt):
            return False
        if not sleep_with_stop(context, 1.05):
            return False

    img = safe_screencap(context)
    if img is None:
        return False
    drawer_open, _ = is_drawer(context, f"{prefix}RetFinal", img)
    if drawer_open:
        return False
    return is_lobby(context, f"{prefix}RetFinal", img)


def _settle_drawer(
    context: Context,
    prefix: str,
    img: Any,
    entries: list[dict[str, Any]],
) -> tuple[Any | None, list[dict[str, Any]]]:
    """Wait until the left drawer finishes sliding in, then re-OCR settled tile coordinates."""
    ever_moved = False
    for _ in range(3):
        if not sleep_with_stop(context, 0.25):
            return None, []
        next_img = safe_screencap(context)
        if next_img is None:
            return img, entries
        moved = images_differ_in_roi(img, next_img, DRAWER_GRID_ROI, threshold=4.0)
        ever_moved = ever_moved or moved
        img = next_img
        if not moved:
            break
    if ever_moved:
        drawer_open, fresh_entries = is_drawer(context, f"{prefix}Settled", img)
        if drawer_open:
            return img, fresh_entries
    return img, entries


def open_drawer(context: Context, prefix: str) -> tuple[Any | None, list[dict[str, Any]]]:
    """Ensure the left navigation drawer is open and return ``(image, entries)``."""
    img = safe_screencap(context)
    if img is None:
        return None, []

    drawer_open, entries = is_drawer(context, f"{prefix}Init", img)
    if drawer_open:
        return _settle_drawer(context, f"{prefix}Init", img, entries)

    if not return_to_lobby(context, f"{prefix}ToLobby"):
        if is_stopping(context):
            return None, []

    for attempt in range(2):
        if not tap_point(context, f"{prefix}OpenDrawer{attempt}", LOBBY_AVATAR_POINT):
            return None, []

        def _check_drawer_open(frame: Any, idx: int, _att: int = attempt) -> tuple[bool, list[dict[str, Any]]] | None:
            tag = f"{prefix}Check{_att}_{idx}" if idx else f"{prefix}Check{_att}"
            drawer_open, entries = is_drawer(context, tag, frame)
            return (True, entries) if drawer_open else None

        img, matched, aborted = poll_screen(
            context,
            _check_drawer_open,
            initial_delay=0.95,
            interval=0.45,
            max_checks=3,
            screencap_fn=safe_screencap,
            sleep_fn=sleep_with_stop,
        )
        if aborted:
            return None, []
        if matched is not None:
            _, entries = matched
            return _settle_drawer(context, f"{prefix}Check{attempt}", img, entries)

    return None, []

"""Shared Activity Hub (活动中心) navigation helpers."""
from __future__ import annotations

from maa.context import Context

from agent.utils.action_helpers import ocr_roi, poll_screen, swipe_points, tap_point
from agent.utils.input_guard import safe_screencap, sleep_with_stop
from agent.utils.lobby_nav import is_stopping, open_drawer, return_to_lobby
from maa_resonance.logic.activity_hub import (
    ACTIVITY_HUB_SCROLL_SWIPE,
    ACTIVITY_HUB_SIDEBAR_ROI,
    LOBBY_ACTIVITY_ICON_POINT,
    find_activity_card,
    find_activity_category_point,
    has_activity_card_red_dot,
    is_activity_hub_entries,
    is_category_expanded,
)
from maa_resonance.logic.daily_routine import find_drawer_entry_point


def open_activity_hub(context: Context, prefix: str) -> bool:
    """Navigate to the Activity Hub sidebar screen from anywhere."""
    img = safe_screencap(context)
    if img is None:
        return False

    sidebar_entries = ocr_roi(context, img, f"{prefix}HubCheckInit", ACTIVITY_HUB_SIDEBAR_ROI)
    if is_activity_hub_entries(sidebar_entries):
        return True

    if not return_to_lobby(context, f"{prefix}ToLobby"):
        if is_stopping(context):
            return False

    for attempt in range(2):
        if not tap_point(context, f"{prefix}LobbyActivity{attempt}", LOBBY_ACTIVITY_ICON_POINT):
            return False
        _, matched, aborted = poll_screen(
            context,
            lambda frame, idx, _att=attempt: is_activity_hub_entries(
                ocr_roi(context, frame, f"{prefix}HubCheck{_att}_{idx}", ACTIVITY_HUB_SIDEBAR_ROI)
            ),
            initial_delay=1.1,
            interval=0.5,
            max_checks=4,
            screencap_fn=safe_screencap,
            sleep_fn=sleep_with_stop,
        )
        if aborted:
            return False
        if matched:
            return True

    # Fallback via left profile drawer -> 活动 tile.
    drawer_img, drawer_entries = open_drawer(context, f"{prefix}FallbackDrawer")
    if drawer_img is None:
        return False
    act_pt = find_drawer_entry_point(drawer_entries, ("活动",)) or (609, 431)
    if not tap_point(context, f"{prefix}DrawerActivity", act_pt):
        return False
    _, matched, aborted = poll_screen(
        context,
        lambda frame, idx: is_activity_hub_entries(
            ocr_roi(context, frame, f"{prefix}HubCheckDrawer{idx}", ACTIVITY_HUB_SIDEBAR_ROI)
        ),
        initial_delay=1.1,
        interval=0.5,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    return bool(matched) and not aborted


def select_activity_tab(
    context: Context,
    prefix: str,
    category: str,
    tab_keywords: tuple[str, ...],
    *,
    check_red_dot: bool = False,
) -> tuple[bool, bool]:
    """Open ``category`` in the Activity Hub sidebar and select the matching card.

    Returns ``(entered, had_red_dot)``.
    """
    for attempt in range(3):
        img = safe_screencap(context)
        if img is None:
            return False, False
        sidebar_entries = ocr_roi(context, img, f"{prefix}Sidebar{attempt}", ACTIVITY_HUB_SIDEBAR_ROI)
        if not is_activity_hub_entries(sidebar_entries):
            return False, False

        if not is_category_expanded(sidebar_entries, category):
            cat_pt = find_activity_category_point(sidebar_entries, category)
            if cat_pt is not None:
                if not tap_point(context, f"{prefix}Expand{attempt}", cat_pt):
                    return False, False
                if not sleep_with_stop(context, 0.9):
                    return False, False
                img = safe_screencap(context)
                if img is None:
                    return False, False
                sidebar_entries = ocr_roi(context, img, f"{prefix}SidebarAfterExp{attempt}", ACTIVITY_HUB_SIDEBAR_ROI)

        card = find_activity_card(sidebar_entries, tab_keywords)
        if card is not None:
            had_red_dot = has_activity_card_red_dot(img, card["label_cy"]) if check_red_dot else False
            if not tap_point(context, f"{prefix}SelectCard", card["tap_point"]):
                return False, False
            if not sleep_with_stop(context, 1.15):
                return False, False
            return True, had_red_dot

        if attempt < 2:
            x1, y1, x2, y2 = ACTIVITY_HUB_SCROLL_SWIPE
            if not swipe_points(
                context,
                f"{prefix}Scroll{attempt}",
                (x1, y1),
                (x2, y2),
                duration=360,
                end_hold=150,
            ):
                return False, False
            if not sleep_with_stop(context, 0.55):
                return False, False

    return False, False

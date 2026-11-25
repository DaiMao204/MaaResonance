"""Shared Mall (商城) and City Chamber (商会) navigation helpers."""
from __future__ import annotations

from typing import Any

from maa.context import Context

from agent.utils.action_helpers import ocr_roi, poll_screen, swipe_points, tap_point
from agent.utils.input_guard import safe_screencap, sleep_with_stop
from agent.utils.lobby_nav import is_stopping, open_drawer, return_to_lobby
from maa_resonance.logic.daily_routine import (
    DRAWER_GRID_ROI,
    DRAWER_SCROLL_UP_SWIPE,
    DRAWER_UID_ROI,
    MALL_TOP_BAR_ROI,
    MALL_TOP_BAR_SWIPE_LEFT,
    find_drawer_entry_point,
    find_mall_tab_entry,
    is_mall_top_bar_entries,
    parse_drawer_uid,
)

LOBBY_VISIT_CITY_ROI: tuple[int, int, int, int] = (1020, 440, 240, 100)
CITY_LANDMARKS_ROI: tuple[int, int, int, int] = (0, 60, 1280, 620)
CHAMBER_MENU_ROI: tuple[int, int, int, int] = (650, 200, 600, 480)
EXCHANGE_TITLE_ROI: tuple[int, int, int, int] = (580, 40, 695, 130)


def _clean_text(text: Any) -> str:
    return "".join(str(text or "").split()).strip()


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


def read_drawer_uid(context: Context, prefix: str, image: Any) -> str:
    """Read account UID from top-left of an already-open navigation drawer."""
    if image is None:
        return ""
    uid_entries = ocr_roi(context, image, f"{prefix}Uid", DRAWER_UID_ROI)
    return parse_drawer_uid(uid_entries)


def enter_mall_from_open_drawer(
    context: Context,
    prefix: str,
    entries: list[dict[str, Any]],
) -> bool:
    """Click '商城' from an already-open left drawer (scrolling up if needed) and wait for Mall top bar."""
    mall_pt = find_drawer_entry_point(entries, ("商城",))
    if mall_pt is None:
        x1, y1, x2, y2 = DRAWER_SCROLL_UP_SWIPE
        for attempt in range(2):
            if not swipe_points(
                context,
                f"{prefix}ScrollDrawerUp{attempt}",
                (x1, y1),
                (x2, y2),
                duration=400,
                end_hold=100,
            ):
                return False
            if not sleep_with_stop(context, 0.7):
                return False
            img = safe_screencap(context)
            if img is None:
                return False
            entries = ocr_roi(context, img, f"{prefix}DrawerGridRetry{attempt}", DRAWER_GRID_ROI)
            mall_pt = find_drawer_entry_point(entries, ("商城",))
            if mall_pt is not None:
                break

    if mall_pt is None:
        return False

    if not tap_point(context, f"{prefix}OpenMall", mall_pt):
        return False

    _, matched, aborted = poll_screen(
        context,
        lambda frame, idx: is_mall_top_bar_entries(
            ocr_roi(context, frame, f"{prefix}MallTop{idx}", MALL_TOP_BAR_ROI)
        ),
        initial_delay=1.2,
        interval=0.5,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    return bool(matched) and not aborted


def open_mall_from_lobby(context: Context, prefix: str) -> tuple[bool, str]:
    """Open the left navigation drawer, read UID, and enter '商城'."""
    img, entries = open_drawer(context, prefix)
    if img is None:
        return False, ""

    uid = read_drawer_uid(context, prefix, img)
    entered = enter_mall_from_open_drawer(context, prefix, entries)
    return entered, uid


def select_mall_tab(
    context: Context,
    prefix: str,
    keywords: tuple[str, ...],
    *,
    drag_left_if_missing: bool = True,
) -> tuple[bool, Any | None, dict[str, Any] | None]:
    """Select a tab along the Mall top bar, swiping left if hidden off-screen."""
    matched_entry: dict[str, Any] | None = None
    for step in range(3 if drag_left_if_missing else 1):
        img = safe_screencap(context)
        if img is None:
            return False, None, None
        bar_entries = ocr_roi(context, img, f"{prefix}Bar{step}", MALL_TOP_BAR_ROI)
        matched_entry = find_mall_tab_entry(bar_entries, keywords)
        if matched_entry is not None:
            break
        if not drag_left_if_missing or step >= 2:
            return False, img, None
        x1, y1, x2, y2 = MALL_TOP_BAR_SWIPE_LEFT
        if not swipe_points(
            context,
            f"{prefix}SwipeBar{step}",
            (x1, y1),
            (x2, y2),
            duration=450,
            end_hold=120,
        ):
            return False, None, None
        if not sleep_with_stop(context, 0.65):
            return False, None, None

    if matched_entry is None:
        return False, None, None
    tap_pt = _entry_center(matched_entry)
    if tap_pt is None:
        return False, None, None
    if not tap_point(context, f"{prefix}TapTab", tap_pt):
        return False, None, None
    if not sleep_with_stop(context, 1.1):
        return False, None, None
    fresh_img = safe_screencap(context)
    return fresh_img is not None, fresh_img, matched_entry


def enter_current_city_chamber_exchange(context: Context, prefix: str) -> tuple[bool, str]:
    """Enter '当前城市 -> 商会 -> 里程点数兑换' from the train lobby.

    Returns ``(True, 'ok')`` on success or ``(False, reason)`` when docked outside a city or missing '商会'.
    """
    if not return_to_lobby(context, f"{prefix}ToLobby"):
        if is_stopping(context):
            return False, "stopped"

    img = safe_screencap(context)
    if img is None:
        return False, "stopped"

    visit_entries = ocr_roi(context, img, f"{prefix}VisitCity", LOBBY_VISIT_CITY_ROI)
    visit_pt: tuple[int, int] | None = None
    for entry in visit_entries:
        if not isinstance(entry, dict):
            continue
        if "访问城市" in _clean_text(entry.get("text")):
            visit_pt = _entry_center(entry)
            if visit_pt is not None:
                break
    if visit_pt is None:
        return False, "not_at_city"

    if not tap_point(context, f"{prefix}TapVisitCity", visit_pt):
        return False, "stopped"

    def _check_city_loaded(frame: Any, idx: int) -> list[dict[str, Any]] | None:
        entries = ocr_roi(context, frame, f"{prefix}City{idx}", CITY_LANDMARKS_ROI)
        texts = [_clean_text(e.get("text")) for e in entries if isinstance(e, dict)]
        if any(kw in t for t in texts for kw in ("商会", "交易所", "铁安局", "市政厅")):
            return entries
        return None

    _city_img, city_entries, aborted = poll_screen(
        context,
        _check_city_loaded,
        initial_delay=1.3,
        interval=0.5,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return False, "stopped"
    if not city_entries:
        return_to_lobby(context, f"{prefix}CityMissBack")
        return False, "no_chamber"

    chamber_pt: tuple[int, int] | None = None
    for entry in city_entries:
        if not isinstance(entry, dict):
            continue
        if "商会" in _clean_text(entry.get("text")):
            box = entry.get("box")
            if isinstance(box, (list, tuple)) and len(box) >= 4:
                cx = int(round(int(box[0]) + int(box[2]) / 2.0))
                cy = min(680, int(round(int(box[1]) + int(box[3]) + 55)))
                chamber_pt = (cx, cy)
                break
            center = _entry_center(entry)
            if center is not None:
                chamber_pt = (center[0], min(680, center[1] + 55))
                break
    if chamber_pt is None:
        return_to_lobby(context, f"{prefix}NoChamberBack")
        return False, "no_chamber"

    if not tap_point(context, f"{prefix}TapChamberNpc", chamber_pt):
        return False, "stopped"

    def _find_exchange_menu(frame: Any, idx: int) -> tuple[int, int] | None:
        menu_entries = ocr_roi(context, frame, f"{prefix}ChamberMenu{idx}", CHAMBER_MENU_ROI)
        for entry in menu_entries:
            if not isinstance(entry, dict):
                continue
            txt = _clean_text(entry.get("text"))
            if "里程点数兑换" in txt or ("里程" in txt and "兑换" in txt):
                pt = _entry_center(entry)
                if pt is not None:
                    return pt
        return None

    _menu_img, exch_pt, aborted = poll_screen(
        context,
        _find_exchange_menu,
        initial_delay=1.1,
        interval=0.45,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return False, "stopped"
    if exch_pt is None:
        return_to_lobby(context, f"{prefix}NoExchangeMenuBack")
        return False, "exchange_open_failed"

    if not tap_point(context, f"{prefix}TapMileageExchange", exch_pt):
        return False, "stopped"

    def _check_exchange_open(frame: Any, idx: int) -> bool | None:
        title_entries = ocr_roi(context, frame, f"{prefix}ExchTitle{idx}", EXCHANGE_TITLE_ROI)
        texts = [_clean_text(e.get("text")).upper() for e in title_entries if isinstance(e, dict)]
        if any("里程点数兑换" in t or "EXCHANGE" in t for t in texts):
            return True
        return None

    _, entered_exch, aborted = poll_screen(
        context,
        _check_exchange_open,
        initial_delay=1.0,
        interval=0.45,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return False, "stopped"
    if not entered_exch:
        return_to_lobby(context, f"{prefix}ExchTimeoutBack")
        return False, "exchange_open_failed"
    return True, "ok"

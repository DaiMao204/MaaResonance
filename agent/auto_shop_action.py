"""Custom MaaFramework action for AutoShop (自动商店周期采购)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from agent.utils.action_helpers import ocr_roi, parse_action_param, poll_screen, swipe_points, tap_point
from agent.utils.input_guard import safe_screencap, sleep_with_stop
from agent.utils.lobby_nav import dismiss_reward_popup_if_present, is_stopping, open_drawer, return_to_lobby
from agent.utils.mall_nav import (
    enter_current_city_chamber_exchange,
    enter_mall_from_open_drawer,
    read_drawer_uid,
    select_mall_tab,
)
from maa_resonance.logic.auto_shop import (
    DEFAULT_AUTO_SHOP_STATE_PATH,
    DEFAULT_CHAMBER_ITEMS,
    DEFAULT_CHAMBER_RESERVE,
    DEFAULT_FUMING_ITEMS,
    DEFAULT_FUMING_PURPLE_RESERVE,
    DEFAULT_HQ_GOLD_ITEMS,
    DEFAULT_HQ_GOLD_RESERVE,
    DEFAULT_HQ_TICKET_ITEMS,
    DEFAULT_HQ_TICKET_RESERVE,
    EXCHANGE_LIST_ROI,
    EXCHANGE_SCROLL_DOWN_SWIPE,
    HQ_BALANCE_ROI,
    HQ_GRID_ROI,
    HQ_SCROLL_DOWN_SWIPE,
    PERIOD_KEYS,
    SHOP_POPUP_ROI,
    ShopBuyRule,
    compute_rule_remaining_quota,
    compute_shop_config_hash,
    compute_shop_next_run,
    format_shop_buy_rules,
    format_timestamp,
    load_auto_shop_state,
    parse_exchange_shop_rows,
    parse_hq_balances,
    parse_hq_shop_cards,
    parse_reserve_amount,
    parse_shop_confirm_popup,
    plan_affordable_quantity,
    resolve_shop_buy_rules,
    save_auto_shop_state,
    shop_item_name_matches,
    should_run_shop,
    update_shop_schedule_state,
)
from maa_resonance.logic.daily_routine import (
    DRAWER_CLOSE_POINT,
    REWARD_POPUP_TOP_SAFE_POINT,
)

AUTO_SHOP_ATTACH_NODES: tuple[str, ...] = (
    "AutoShopOptScheduleMode",
    "AutoShopOptBlackMoonHqEnabled",
    "AutoShopOptHqGoldItems",
    "AutoShopOptHqGoldConfig",
    "AutoShopOptHqTicketEnabled",
    "AutoShopOptHqTicketItems",
    "AutoShopOptHqTicketConfig",
    "AutoShopOptFumingEnabled",
    "AutoShopOptFumingItems",
    "AutoShopOptFumingConfig",
    "AutoShopOptFumingAllowGoldMedal",
    "AutoShopOptChamberEnabled",
    "AutoShopOptChamberItems",
    "AutoShopOptChamberConfig",
)


def _resolve_shop_params(context: Context, argv: Any) -> dict[str, Any]:
    merged = dict(parse_action_param(getattr(argv, "custom_action_param", None)))
    get_node_data = getattr(context, "get_node_data", None)
    if callable(get_node_data):
        for node_name in AUTO_SHOP_ATTACH_NODES:
            try:
                node_data = get_node_data(node_name)
            except Exception:
                node_data = None
            if isinstance(node_data, dict) and isinstance(node_data.get("attach"), dict):
                merged.update(node_data["attach"])
    return merged


def _wait_popup(
    context: Context,
    prefix: str,
    shop_kind: str,
) -> tuple[Any | None, dict[str, Any] | None, bool]:
    def _check(frame: Any, idx: int) -> dict[str, Any] | None:
        entries = ocr_roi(context, frame, f"{prefix}Pop{idx}", SHOP_POPUP_ROI)
        return parse_shop_confirm_popup(entries, frame, shop_kind=shop_kind)

    return poll_screen(
        context,
        _check,
        initial_delay=0.75,
        interval=0.35,
        max_checks=3,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )


def _adjust_popup_quantity(
    context: Context,
    prefix: str,
    popup: dict[str, Any],
    target_qty: int,
    *,
    shop_kind: str,
) -> dict[str, Any] | None:
    """Adjust modal slider to ``target_qty`` using fewest taps, returning refreshed popup state."""
    cur_qty = int(popup.get("cur_qty") or 1)
    max_qty = max(1, int(popup.get("max_qty") or target_qty or 1))
    target = max(1, min(max_qty, int(target_qty)))
    if target == cur_qty:
        return popup

    if target == max_qty:
        if not tap_point(context, f"{prefix}Max", popup["max_pt"]):
            return None
        if not sleep_with_stop(context, 0.3):
            return None
    else:
        inc_steps = target - cur_qty if target > cur_qty else max_qty + 1
        dec_steps_from_max = (max_qty - target) + 1
        if inc_steps <= dec_steps_from_max and target > cur_qty:
            for idx in range(min(inc_steps, 40)):
                if not tap_point(context, f"{prefix}Inc{idx}", popup["inc_pt"]):
                    return None
                if not sleep_with_stop(context, 0.16):
                    return None
        elif dec_steps_from_max < inc_steps and max_qty > target:
            if not tap_point(context, f"{prefix}MaxForStep", popup["max_pt"]):
                return None
            if not sleep_with_stop(context, 0.25):
                return None
            for idx in range(min(max_qty - target, 40)):
                if not tap_point(context, f"{prefix}Dec{idx}", popup["dec_pt"]):
                    return None
                if not sleep_with_stop(context, 0.16):
                    return None
        elif target < cur_qty:
            for idx in range(min(cur_qty - target, 40)):
                if not tap_point(context, f"{prefix}DecCur{idx}", popup["dec_pt"]):
                    return None
                if not sleep_with_stop(context, 0.16):
                    return None

    img = safe_screencap(context)
    if img is None:
        return None
    entries = ocr_roi(context, img, f"{prefix}PopRefreshed", SHOP_POPUP_ROI)
    refreshed = parse_shop_confirm_popup(entries, img, shop_kind=shop_kind)
    return refreshed or popup


def _find_matched_sold_out_period(
    rule: ShopBuyRule,
    seen_sold_out_keys: set[tuple[Any, ...]],
    *,
    expected_currency: str | None = None,
) -> str | None:
    """Return the matched sold-out period if a previously scanned shelf entry satisfies ``rule``."""
    for skey in seen_sold_out_keys:
        s_name, s_period = skey[0], skey[1]
        s_cur = skey[2] if len(skey) >= 3 else None
        if expected_currency is not None and s_cur is not None and s_cur != expected_currency:
            continue
        if _rule_matches_item(rule, s_name, s_period, s_cur):
            return s_period
    return None


def _plan_scan_directions(
    rule: ShopBuyRule,
    seen_page_hint: dict[tuple[Any, ...], int],
    *,
    scroll_pos: int,
    at_top: bool,
    at_bottom: bool,
    expected_currency: str | None = None,
) -> list[str]:
    """Choose the initial scan direction from page hints and boundary state, plus optional reverse pass."""
    hint_pos: int | None = None
    for hkey, hpos in seen_page_hint.items():
        h_name, h_period = hkey[0], hkey[1]
        h_cur = hkey[2] if len(hkey) >= 3 else None
        if expected_currency is not None and h_cur is not None and h_cur != expected_currency:
            continue
        if _rule_matches_item(rule, h_name, h_period, h_cur):
            hint_pos = hpos
            break

    if hint_pos is not None and hint_pos < scroll_pos and not at_top:
        initial_dir = "up"
    elif hint_pos is not None and hint_pos > scroll_pos and not at_bottom:
        initial_dir = "down"
    elif at_bottom and not at_top:
        initial_dir = "up"
    else:
        initial_dir = "down"

    started_at_opposite = (initial_dir == "down" and at_top) or (initial_dir == "up" and at_bottom)
    if started_at_opposite:
        return [initial_dir]
    reverse_dir = "up" if initial_dir == "down" else "down"
    return [initial_dir, reverse_dir]


def _step_shop_scroll(
    context: Context,
    tag: str,
    swipe_down_coords: tuple[int, int, int, int],
    direction: str,
    *,
    scroll_pos: int,
) -> tuple[bool, int]:
    """Swipe down or up one shop page and return ``(ok, updated_scroll_pos)``."""
    x1, y1, x2, y2 = swipe_down_coords
    start, end = ((x1, y1), (x2, y2)) if direction == "down" else ((x2, y2), (x1, y1))
    if not swipe_points(context, tag, start, end, duration=480):
        return False, scroll_pos
    if not sleep_with_stop(context, 0.7):
        return False, scroll_pos
    next_pos = scroll_pos + 1 if direction == "down" else max(0, scroll_pos - 1)
    return True, next_pos


def _rule_matches_item(rule: ShopBuyRule, item_name: str, period: str, currency: str | None = None) -> bool:
    if period not in ("daily", "weekly", "monthly"):
        return False
    if rule.period is not None and rule.period != period:
        return False
    if rule.currency is not None and currency is not None and rule.currency != currency:
        return False
    return shop_item_name_matches(item_name, rule.item_name)


def _run_black_moon_hq(
    context: Context,
    prefix: str,
    gold_rules: list[ShopBuyRule],
    gold_reserve: int,
    ticket_enabled: bool,
    ticket_rules: list[ShopBuyRule],
    ticket_reserve: int,
) -> tuple[bool, list[str], set[str], bool]:
    """Execute priority purchases inside '总部商店'.

    Returns ``(ok, bought_logs, matched_periods, partial_due_to_budget)``.
    """
    active_rules: list[ShopBuyRule] = list(gold_rules)
    if ticket_enabled:
        active_rules.extend(ticket_rules)
    if not active_rules:
        return True, [], set(), False

    # Wait briefly for cards & balances to populate.
    def _ready(frame: Any, idx: int) -> tuple[dict[str, int | None], list[dict[str, Any]]] | None:
        bal = parse_hq_balances(ocr_roi(context, frame, f"{prefix}InitBal{idx}", HQ_BALANCE_ROI))
        cards = parse_hq_shop_cards(ocr_roi(context, frame, f"{prefix}InitGrid{idx}", HQ_GRID_ROI), frame)
        return (bal, cards) if cards else None

    _, ready_res, aborted = poll_screen(
        context,
        _ready,
        initial_delay=0.0,
        interval=0.45,
        max_checks=3,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return False, [], set(), False
    if ready_res is None:
        print("[AutoShop] 黑月总部商店货架未加载，跳过。", flush=True)
        return False, [], set(), False

    bought_logs: list[str] = []
    matched_periods: set[str] = set()
    partial_due_to_budget = False
    settled_keys: set[tuple[str, str, str]] = set()
    seen_sold_out_keys: set[tuple[str, str, str]] = set()
    seen_page_hint: dict[tuple[str, str, str], int] = {}
    scroll_pos = 0
    at_top = True
    at_bottom = False

    for rule_idx, rule in enumerate(active_rules):
        expected_currency = rule.currency or "gold"
        if expected_currency == "huashi":
            continue
        reserve = ticket_reserve if expected_currency == "ticket" else gold_reserve

        if rule.period is not None:
            sold_period = _find_matched_sold_out_period(
                rule,
                seen_sold_out_keys,
                expected_currency=expected_currency,
            )
            if sold_period is not None:
                matched_periods.add(sold_period)
                print(f"[AutoShop] 黑月总部「{rule.item_name}」({sold_period}) 已售罄，跳过。", flush=True)
                continue

        directions = _plan_scan_directions(
            rule,
            seen_page_hint,
            scroll_pos=scroll_pos,
            at_top=at_top,
            at_bottom=at_bottom,
            expected_currency=expected_currency,
        )
        rule_done = False

        for direction in directions:
            if rule_done:
                break
            prev_sig: tuple[tuple[str, str], ...] | None = None

            for page_step in range(8):
                img = safe_screencap(context)
                if img is None:
                    return False, bought_logs, matched_periods, partial_due_to_budget
                bal = parse_hq_balances(ocr_roi(context, img, f"{prefix}R{rule_idx}Bal{page_step}", HQ_BALANCE_ROI))
                cards = parse_hq_shop_cards(
                    ocr_roi(context, img, f"{prefix}R{rule_idx}Grid{page_step}", HQ_GRID_ROI),
                    img,
                )
                sig = tuple((c["name"], c["period"]) for c in cards)
                if page_step > 0 and sig == prev_sig:
                    if direction == "down":
                        at_bottom = True
                        scroll_pos = max(0, scroll_pos - 1)
                    else:
                        at_top = True
                        scroll_pos = 0
                    break
                prev_sig = sig

                for card_info in cards:
                    if card_info["period"] in PERIOD_KEYS:
                        ckey = (card_info["name"], card_info["period"], card_info["currency"])
                        seen_page_hint[ckey] = scroll_pos
                        if card_info["sold_out"]:
                            seen_sold_out_keys.add(ckey)

                rescan_same_page = False
                for card in cards:
                    if not _rule_matches_item(rule, card["name"], card["period"], card["currency"]):
                        continue
                    if card["currency"] != expected_currency:
                        continue
                    key = (card["name"], card["period"], card["currency"])
                    matched_periods.add(card["period"])
                    if key in settled_keys:
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue
                    if card["sold_out"]:
                        settled_keys.add(key)
                        seen_sold_out_keys.add(key)
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue

                    allowed_qty = compute_rule_remaining_quota(
                        rule,
                        remaining=card.get("remaining"),
                        limit_total=card.get("limit_total"),
                    )
                    if allowed_qty is not None and allowed_qty <= 0:
                        print(
                            f"[AutoShop] 黑月总部「{card['name']}」({card['period']}) 已达设定上限 *{rule.max_buy}，跳过。",
                            flush=True,
                        )
                        settled_keys.add(key)
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue

                    cur_balance = bal.get(expected_currency)
                    if cur_balance is None:
                        continue
                    est_unit = card.get("unit_cost") or 1
                    if card.get("unit_cost") and cur_balance - est_unit < reserve:
                        print(
                            f"[AutoShop] 黑月总部跳过「{card['name']}」({card['period']}): "
                            f"余额 {cur_balance} 扣单价 {est_unit} 将低于保留下限 {reserve}。",
                            flush=True,
                        )
                        partial_due_to_budget = True
                        settled_keys.add(key)
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue

                    if not tap_point(context, f"{prefix}TapR{rule_idx}", card["tap_point"]):
                        return False, bought_logs, matched_periods, partial_due_to_budget
                    _pop_img, popup, pop_aborted = _wait_popup(context, f"{prefix}R{rule_idx}", "hq")
                    if pop_aborted:
                        return False, bought_logs, matched_periods, partial_due_to_budget
                    if popup is None:
                        print(f"[AutoShop] 黑月总部点击「{card['name']}」未弹出确认窗，跳过。", flush=True)
                        settled_keys.add(key)
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue

                    if not shop_item_name_matches(popup["item_name"], rule.item_name):
                        print(
                            f"[AutoShop] 安全拦截：弹窗商品名「{popup['item_name']}」与预期「{rule.item_name}」不符，已取消。",
                            flush=True,
                        )
                        tap_point(context, f"{prefix}CancelMismatch{rule_idx}", popup["cancel_pt"])
                        sleep_with_stop(context, 0.55)
                        settled_keys.add(key)
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue

                    if popup["currency"] != expected_currency:
                        print(
                            f"[AutoShop] 安全拦截：弹窗货币「{popup['currency']}」非预期「{expected_currency}」（严禁桦石），已取消。",
                            flush=True,
                        )
                        tap_point(context, f"{prefix}CancelCurrency{rule_idx}", popup["cancel_pt"])
                        sleep_with_stop(context, 0.55)
                        settled_keys.add(key)
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue

                    unit_cost = card.get("unit_cost") or popup.get("price") or 0
                    max_qty = popup.get("max_qty") or card.get("remaining") or 1
                    desired_qty = min(max_qty, allowed_qty) if allowed_qty is not None else max_qty
                    target_qty = plan_affordable_quantity(cur_balance, reserve, unit_cost, desired_qty)
                    if target_qty <= 0:
                        tap_point(context, f"{prefix}CancelReserve{rule_idx}", popup["cancel_pt"])
                        sleep_with_stop(context, 0.55)
                        partial_due_to_budget = True
                        settled_keys.add(key)
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue

                    adjusted = _adjust_popup_quantity(
                        context,
                        f"{prefix}AdjR{rule_idx}",
                        popup,
                        target_qty,
                        shop_kind="hq",
                    )
                    if adjusted is None:
                        return False, bought_logs, matched_periods, partial_due_to_budget

                    # Guard against escalating prices (e.g. 拉普拉斯协议): step down until within reserve.
                    for dec_try in range(12):
                        total_price = adjusted.get("price")
                        cur_q = int(adjusted.get("cur_qty") or 1)
                        if total_price is None or (cur_balance - total_price >= reserve):
                            break
                        if cur_q <= 1:
                            adjusted["__abort_budget"] = True
                            break
                        if not tap_point(context, f"{prefix}EscDec{rule_idx}_{dec_try}", adjusted["dec_pt"]):
                            return False, bought_logs, matched_periods, partial_due_to_budget
                        if not sleep_with_stop(context, 0.25):
                            return False, bought_logs, matched_periods, partial_due_to_budget
                        chk_img = safe_screencap(context)
                        if chk_img is None:
                            return False, bought_logs, matched_periods, partial_due_to_budget
                        chk_entries = ocr_roi(context, chk_img, f"{prefix}EscChk{rule_idx}_{dec_try}", SHOP_POPUP_ROI)
                        re_pop = parse_shop_confirm_popup(chk_entries, chk_img, shop_kind="hq")
                        if re_pop is not None:
                            adjusted = re_pop
                        else:
                            adjusted["cur_qty"] = max(1, cur_q - 1)

                    if adjusted.get("__abort_budget"):
                        tap_point(context, f"{prefix}CancelEsc{rule_idx}", adjusted["cancel_pt"])
                        sleep_with_stop(context, 0.55)
                        partial_due_to_budget = True
                        settled_keys.add(key)
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue

                    final_qty = int(adjusted.get("cur_qty") or target_qty)
                    final_price = adjusted.get("price")
                    if not tap_point(context, f"{prefix}ConfirmR{rule_idx}", adjusted["confirm_pt"]):
                        return False, bought_logs, matched_periods, partial_due_to_budget
                    if not sleep_with_stop(context, 0.95):
                        return False, bought_logs, matched_periods, partial_due_to_budget
                    if not dismiss_reward_popup_if_present(
                        context,
                        f"{prefix}AfterBuy{rule_idx}",
                        dismiss_point=REWARD_POPUP_TOP_SAFE_POINT,
                    ):
                        return False, bought_logs, matched_periods, partial_due_to_budget
                    bought_logs.append(f"{card['name']}({card['period']})x{final_qty}@{final_price or '?'}")
                    if final_qty < desired_qty:
                        partial_due_to_budget = True
                    if final_qty >= max_qty:
                        at_bottom = False
                        seen_sold_out_keys.add(key)
                    settled_keys.add(key)
                    if rule.period is not None:
                        rule_done = True
                    else:
                        rescan_same_page = True
                    break

                if rule_done:
                    break
                if rescan_same_page:
                    prev_sig = None
                    continue
                if (direction == "down" and at_bottom) or (direction == "up" and at_top):
                    break
                dir_tag = "Down" if direction == "down" else "Up"
                swiped, scroll_pos = _step_shop_scroll(
                    context,
                    f"{prefix}R{rule_idx}{dir_tag}{page_step}",
                    HQ_SCROLL_DOWN_SWIPE,
                    direction,
                    scroll_pos=scroll_pos,
                )
                if not swiped:
                    return False, bought_logs, matched_periods, partial_due_to_budget
                if direction == "down":
                    at_top = False
                else:
                    at_bottom = False

    return True, bought_logs, matched_periods, partial_due_to_budget


def _run_exchange_shop(
    context: Context,
    prefix: str,
    rules: list[ShopBuyRule],
    reserve: int,
    *,
    shop_kind: str,
    allow_gold_medal: bool = False,
) -> tuple[bool, list[str], set[str], bool]:
    """Execute priority exchanges inside Fuming Shop or Chamber Mileage Exchange."""
    if not rules:
        return True, [], set(), False

    classify_medal = shop_kind == "fuming"
    _, ready_rows, aborted = poll_screen(
        context,
        lambda frame, idx: parse_exchange_shop_rows(
            ocr_roi(context, frame, f"{prefix}Init{idx}", EXCHANGE_LIST_ROI),
            frame,
            classify_medal=classify_medal,
        ),
        initial_delay=0.0,
        interval=0.45,
        max_checks=3,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return False, [], set(), False
    if not ready_rows:
        print(f"[AutoShop] {shop_kind} 列表未加载，跳过。", flush=True)
        return False, [], set(), False

    bought_logs: list[str] = []
    matched_periods: set[str] = set()
    partial_due_to_budget = False
    settled_keys: set[tuple[str, str]] = set()
    seen_sold_out_keys: set[tuple[str, str]] = set()
    seen_page_hint: dict[tuple[str, str], int] = {}
    scroll_pos = 0
    at_top = True
    at_bottom = False

    for rule_idx, rule in enumerate(rules):
        if rule.period is not None:
            sold_period = _find_matched_sold_out_period(rule, seen_sold_out_keys)
            if sold_period is not None:
                matched_periods.add(sold_period)
                print(f"[AutoShop] {shop_kind}「{rule.item_name}」({sold_period}) 已售罄，跳过。", flush=True)
                continue

        directions = _plan_scan_directions(
            rule,
            seen_page_hint,
            scroll_pos=scroll_pos,
            at_top=at_top,
            at_bottom=at_bottom,
        )
        rule_done = False

        for direction in directions:
            if rule_done:
                break
            prev_sig: tuple[tuple[str, str], ...] | None = None

            for page_step in range(8):
                img = safe_screencap(context)
                if img is None:
                    return False, bought_logs, matched_periods, partial_due_to_budget
                rows = parse_exchange_shop_rows(
                    ocr_roi(context, img, f"{prefix}R{rule_idx}List{page_step}", EXCHANGE_LIST_ROI),
                    img,
                    classify_medal=classify_medal,
                )
                sig = tuple((r["name"], r["period"]) for r in rows)
                if page_step > 0 and sig == prev_sig:
                    if direction == "down":
                        at_bottom = True
                        scroll_pos = max(0, scroll_pos - 1)
                    else:
                        at_top = True
                        scroll_pos = 0
                    break
                prev_sig = sig

                for row_info in rows:
                    if row_info["period"] in PERIOD_KEYS:
                        rkey = (row_info["name"], row_info["period"])
                        seen_page_hint[rkey] = scroll_pos
                        if row_info["sold_out"]:
                            seen_sold_out_keys.add(rkey)

                rescan_same_page = False
                for row in rows:
                    if not _rule_matches_item(rule, row["name"], row["period"]):
                        continue
                    key = (row["name"], row["period"])
                    matched_periods.add(row["period"])
                    if key in settled_keys:
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue
                    if row["sold_out"]:
                        settled_keys.add(key)
                        seen_sold_out_keys.add(key)
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue

                    costs = row.get("costs") or []
                    if not costs:
                        continue
                    if shop_kind == "fuming" and not allow_gold_medal:
                        if len(costs) != 1 or costs[0]["medal"] != "purple_medal":
                            settled_keys.add(key)
                            if rule.period is not None:
                                rule_done = True
                                break
                            continue
                    if shop_kind == "chamber" and len(costs) != 1:
                        settled_keys.add(key)
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue

                    allowed_qty = compute_rule_remaining_quota(
                        rule,
                        remaining=row.get("remaining"),
                        limit_total=None,
                    )
                    if allowed_qty is not None and allowed_qty <= 0:
                        settled_keys.add(key)
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue

                    primary_cost = costs[0]
                    bal = int(primary_cost["balance"])
                    unit_cost = int(primary_cost["unit_cost"])
                    row_reserve = reserve if (shop_kind != "fuming" or primary_cost["medal"] == "purple_medal") else 0
                    row_max = int(row.get("remaining") or 1)
                    row_desired = min(row_max, allowed_qty) if allowed_qty is not None else row_max
                    est_qty = plan_affordable_quantity(bal, row_reserve, unit_cost, row_desired)
                    if est_qty <= 0:
                        print(
                            f"[AutoShop] {shop_kind} 跳过「{row['name']}」({row['period']}): "
                            f"余额 {bal} 扣单价 {unit_cost} 将低于保留下限 {row_reserve}。",
                            flush=True,
                        )
                        partial_due_to_budget = True
                        settled_keys.add(key)
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue

                    if not tap_point(context, f"{prefix}TapR{rule_idx}", row["exchange_point"]):
                        return False, bought_logs, matched_periods, partial_due_to_budget
                    _pop_img, popup, pop_aborted = _wait_popup(context, f"{prefix}R{rule_idx}", shop_kind)
                    if pop_aborted:
                        return False, bought_logs, matched_periods, partial_due_to_budget
                    if popup is None:
                        settled_keys.add(key)
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue

                    if popup["item_name"] and not shop_item_name_matches(popup["item_name"], rule.item_name):
                        print(
                            f"[AutoShop] 安全拦截：兑换弹窗「{popup['item_name']}」与预期「{rule.item_name}」不符，已取消。",
                            flush=True,
                        )
                        tap_point(context, f"{prefix}CancelMismatch{rule_idx}", popup["cancel_pt"])
                        sleep_with_stop(context, 0.55)
                        settled_keys.add(key)
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue

                    max_qty = popup.get("max_qty") or row.get("remaining") or 1
                    desired_qty = min(max_qty, allowed_qty) if allowed_qty is not None else max_qty
                    target_qty = plan_affordable_quantity(bal, row_reserve, unit_cost, desired_qty)
                    if target_qty <= 0:
                        tap_point(context, f"{prefix}CancelReserve{rule_idx}", popup["cancel_pt"])
                        sleep_with_stop(context, 0.55)
                        partial_due_to_budget = True
                        settled_keys.add(key)
                        if rule.period is not None:
                            rule_done = True
                            break
                        continue

                    adjusted = _adjust_popup_quantity(
                        context,
                        f"{prefix}AdjR{rule_idx}",
                        popup,
                        target_qty,
                        shop_kind=shop_kind,
                    )
                    if adjusted is None:
                        return False, bought_logs, matched_periods, partial_due_to_budget
                    final_qty = int(adjusted.get("cur_qty") or target_qty)
                    if not tap_point(context, f"{prefix}ConfirmR{rule_idx}", adjusted["confirm_pt"]):
                        return False, bought_logs, matched_periods, partial_due_to_budget
                    if not sleep_with_stop(context, 0.95):
                        return False, bought_logs, matched_periods, partial_due_to_budget
                    if not dismiss_reward_popup_if_present(
                        context,
                        f"{prefix}AfterBuy{rule_idx}",
                        dismiss_point=REWARD_POPUP_TOP_SAFE_POINT,
                    ):
                        return False, bought_logs, matched_periods, partial_due_to_budget
                    bought_logs.append(f"{row['name']}({row['period']})x{final_qty}")
                    if final_qty < desired_qty:
                        partial_due_to_budget = True
                    if final_qty >= max_qty:
                        at_bottom = False
                        seen_sold_out_keys.add(key)
                    settled_keys.add(key)
                    if rule.period is not None:
                        rule_done = True
                    else:
                        rescan_same_page = True
                    break

                if rule_done:
                    break
                if rescan_same_page:
                    prev_sig = None
                    continue
                if (direction == "down" and at_bottom) or (direction == "up" and at_top):
                    break
                dir_tag = "Down" if direction == "down" else "Up"
                swiped, scroll_pos = _step_shop_scroll(
                    context,
                    f"{prefix}R{rule_idx}{dir_tag}{page_step}",
                    EXCHANGE_SCROLL_DOWN_SWIPE,
                    direction,
                    scroll_pos=scroll_pos,
                )
                if not swiped:
                    return False, bought_logs, matched_periods, partial_due_to_budget
                if direction == "down":
                    at_top = False
                else:
                    at_bottom = False

    return True, bought_logs, matched_periods, partial_due_to_budget


@AgentServer.custom_action("auto_shop_run")
class AutoShopRunAction(CustomAction):
    """Run periodic AutoShop across Black Moon HQ, Fuming Shop, and Chamber Mileage with per-UID caching."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        prefix = f"{argv.node_name}"
        params = _resolve_shop_params(context, argv)

        force_run = str(params.get("schedule_mode") or "smart").strip().lower() == "force"
        hq_enabled = bool(params.get("hq_enabled", True))
        gold_rules = resolve_shop_buy_rules(
            params,
            pick_prefix="hq_gold_pick_",
            extra_key="hq_gold_extra",
            legacy_key="hq_gold_items",
            ui_configured_key="hq_gold_ui_configured",
            default_items=DEFAULT_HQ_GOLD_ITEMS,
            default_currency="gold",
        )
        hq_gold_reserve = parse_reserve_amount(params.get("hq_gold_reserve"), DEFAULT_HQ_GOLD_RESERVE)
        hq_ticket_enabled = bool(params.get("hq_ticket_enabled", False))
        ticket_rules = (
            resolve_shop_buy_rules(
                params,
                pick_prefix="hq_ticket_pick_",
                extra_key="hq_ticket_extra",
                legacy_key="hq_ticket_items",
                ui_configured_key="hq_ticket_ui_configured",
                default_items=DEFAULT_HQ_TICKET_ITEMS,
                default_currency="ticket",
            )
            if hq_ticket_enabled
            else []
        )
        hq_ticket_reserve = parse_reserve_amount(params.get("hq_ticket_reserve"), DEFAULT_HQ_TICKET_RESERVE)

        fuming_enabled = bool(params.get("fuming_enabled", True))
        fuming_rules = resolve_shop_buy_rules(
            params,
            pick_prefix="fuming_pick_",
            extra_key="fuming_extra",
            legacy_key="fuming_items",
            ui_configured_key="fuming_ui_configured",
            default_items=DEFAULT_FUMING_ITEMS,
        )
        fuming_purple_reserve = parse_reserve_amount(
            params.get("fuming_purple_reserve"), DEFAULT_FUMING_PURPLE_RESERVE
        )
        fuming_allow_gold = bool(params.get("fuming_allow_gold_medal", False))

        chamber_enabled = bool(params.get("chamber_enabled", True))
        chamber_rules = resolve_shop_buy_rules(
            params,
            pick_prefix="chamber_pick_",
            extra_key="chamber_extra",
            legacy_key="chamber_items",
            ui_configured_key="chamber_ui_configured",
            default_items=DEFAULT_CHAMBER_ITEMS,
        )
        chamber_reserve = parse_reserve_amount(params.get("chamber_reserve"), DEFAULT_CHAMBER_RESERVE)

        if not (hq_enabled or fuming_enabled or chamber_enabled):
            print("[AutoShop] 三个自动商店子开关均已关闭，跳过。", flush=True)
            return CustomAction.RunResult(success=True)

        drawer_img, drawer_entries = open_drawer(context, f"{prefix}Drawer")
        if drawer_img is None:
            if is_stopping(context):
                return CustomAction.RunResult(success=False)
            print("[AutoShop] 未能打开个人抽屉，安全跳过本次商店检查。", flush=True)
            return_to_lobby(context, f"{prefix}DrawerAbort")
            return CustomAction.RunResult(success=True)

        uid = read_drawer_uid(context, f"{prefix}Uid", drawer_img) or "default"
        now = datetime.now()
        state = load_auto_shop_state(DEFAULT_AUTO_SHOP_STATE_PATH)

        hq_hash = compute_shop_config_hash(
            {
                "gold_items": format_shop_buy_rules(gold_rules, default_currency="gold"),
                "gold_reserve": hq_gold_reserve,
                "ticket_enabled": hq_ticket_enabled,
                "ticket_items": format_shop_buy_rules(ticket_rules, default_currency="ticket") if hq_ticket_enabled else "",
                "ticket_reserve": hq_ticket_reserve,
            }
        )
        fuming_hash = compute_shop_config_hash(
            {
                "items": format_shop_buy_rules(fuming_rules),
                "purple_reserve": fuming_purple_reserve,
                "allow_gold": fuming_allow_gold,
            }
        )
        chamber_hash = compute_shop_config_hash(
            {
                "items": format_shop_buy_rules(chamber_rules),
                "reserve": chamber_reserve,
            }
        )

        run_hq, hq_reason = (
            should_run_shop(state, uid, "black_moon_hq", hq_hash, now, force_run=force_run)
            if hq_enabled
            else (False, "disabled")
        )
        run_fuming, fuming_reason = (
            should_run_shop(state, uid, "fuming", fuming_hash, now, force_run=force_run)
            if fuming_enabled
            else (False, "disabled")
        )
        run_chamber, chamber_reason = (
            should_run_shop(state, uid, "chamber_mileage", chamber_hash, now, force_run=force_run)
            if chamber_enabled
            else (False, "disabled")
        )

        for label, enabled_flag, due_flag, reason in (
            ("黑月总部商店", hq_enabled, run_hq, hq_reason),
            ("赴命商店", fuming_enabled, run_fuming, fuming_reason),
            ("商会里程兑换", chamber_enabled, run_chamber, chamber_reason),
        ):
            if enabled_flag and not due_flag:
                print(f"[AutoShop] UID={uid} {label}未到下次运行时间（{reason}），跳过。", flush=True)

        if not (run_hq or run_fuming or run_chamber):
            tap_point(context, f"{prefix}CloseDrawer", DRAWER_CLOSE_POINT)
            sleep_with_stop(context, 0.7)
            return CustomAction.RunResult(success=not is_stopping(context))

        state_dirty = False

        if run_hq or run_fuming:
            entered_mall = enter_mall_from_open_drawer(context, f"{prefix}Mall", drawer_entries)
            if not entered_mall:
                if is_stopping(context):
                    return CustomAction.RunResult(success=False)
                print("[AutoShop] 未能进入商城，跳过黑月总部与赴命商店。", flush=True)
            else:
                if run_hq:
                    tab_ok, _tab_img, _tab = select_mall_tab(context, f"{prefix}HqTab", ("总部商店",))
                    if tab_ok:
                        ok, logs, periods, partial = _run_black_moon_hq(
                            context,
                            f"{prefix}Hq",
                            gold_rules,
                            hq_gold_reserve,
                            hq_ticket_enabled,
                            ticket_rules,
                            hq_ticket_reserve,
                        )
                        if ok:
                            if not periods:
                                periods = {r.period for r in (*gold_rules, *ticket_rules) if r.period} or {"weekly"}
                            next_dt = compute_shop_next_run(now, periods, partial_due_to_budget=partial)
                            summary = ", ".join(logs) if logs else "无可购项"
                            update_shop_schedule_state(
                                state, uid, "black_moon_hq", hq_hash, now, next_dt, summary=summary
                            )
                            state_dirty = True
                            print(
                                f"[AutoShop] UID={uid} 黑月总部商店完成（{summary}），下次运行: {format_timestamp(next_dt)}",
                                flush=True,
                            )

                if run_fuming and not is_stopping(context):
                    tab_ok, _tab_img, _tab = select_mall_tab(context, f"{prefix}FumingTab", ("赴命商店",))
                    if tab_ok:
                        ok, logs, periods, partial = _run_exchange_shop(
                            context,
                            f"{prefix}Fuming",
                            fuming_rules,
                            fuming_purple_reserve,
                            shop_kind="fuming",
                            allow_gold_medal=fuming_allow_gold,
                        )
                        if ok:
                            if not periods:
                                periods = {r.period for r in fuming_rules if r.period} or {"weekly"}
                            next_dt = compute_shop_next_run(now, periods, partial_due_to_budget=partial)
                            summary = ", ".join(logs) if logs else "无可购项"
                            update_shop_schedule_state(
                                state, uid, "fuming", fuming_hash, now, next_dt, summary=summary
                            )
                            state_dirty = True
                            print(
                                f"[AutoShop] UID={uid} 赴命商店完成（{summary}），下次运行: {format_timestamp(next_dt)}",
                                flush=True,
                            )

        if run_chamber and not is_stopping(context):
            entered_ch, ch_reason = enter_current_city_chamber_exchange(context, f"{prefix}ChamberNav")
            if not entered_ch:
                if is_stopping(context):
                    if state_dirty:
                        save_auto_shop_state(DEFAULT_AUTO_SHOP_STATE_PATH, state)
                    return CustomAction.RunResult(success=False)
                print(f"[AutoShop] 当前站点未进入「商会里程兑换」（{ch_reason}），本次跳过且不推进周期时间。", flush=True)
            else:
                ok, logs, periods, partial = _run_exchange_shop(
                    context,
                    f"{prefix}Chamber",
                    chamber_rules,
                    chamber_reserve,
                    shop_kind="chamber",
                )
                if ok:
                    if not periods:
                        periods = {r.period for r in chamber_rules if r.period} or {"weekly"}
                    next_dt = compute_shop_next_run(now, periods, partial_due_to_budget=partial)
                    summary = ", ".join(logs) if logs else "无可购项"
                    update_shop_schedule_state(
                        state, uid, "chamber_mileage", chamber_hash, now, next_dt, summary=summary
                    )
                    state_dirty = True
                    print(
                        f"[AutoShop] UID={uid} 商会里程兑换完成（{summary}），下次运行: {format_timestamp(next_dt)}",
                        flush=True,
                    )

        if state_dirty:
            save_auto_shop_state(DEFAULT_AUTO_SHOP_STATE_PATH, state)

        return_to_lobby(context, f"{prefix}Done", dismiss_point=REWARD_POPUP_TOP_SAFE_POINT)
        return CustomAction.RunResult(success=not is_stopping(context))

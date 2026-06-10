from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .planner import RoutePlanOptions
from .planner import load_columba_baseline_market_data
from .planner import load_columba_trade_data
from .planner import normalize_mixed_currency_priority
from .planner import plan_two_city_routes
from .planner import summarize_routes
from .planner import normalize_city_name
from .profile_parser import load_role_names
from .profile_parser import role_resonance_max


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FALLBACK_CARGO_CAPACITY = 1016
PRODUCT_STATUS_LOCKED = "locked"
PRODUCT_STATUS_MISSING = "missing"
PRODUCT_STATUS_NEVER_SCANNED = "never_scanned"
PRODUCT_STATUS_NORMAL = "normal"
PRODUCT_PLANNER_BLOCKED_STATUSES = {PRODUCT_STATUS_LOCKED, PRODUCT_STATUS_MISSING}
PRODUCT_STATUS_ALIASES = {
    "true": PRODUCT_STATUS_NORMAL,
    "1": PRODUCT_STATUS_NORMAL,
    "yes": PRODUCT_STATUS_NORMAL,
    "normal": PRODUCT_STATUS_NORMAL,
    "ok": PRODUCT_STATUS_NORMAL,
    "正常": PRODUCT_STATUS_NORMAL,
    "已解锁": PRODUCT_STATUS_NORMAL,
    "false": PRODUCT_STATUS_LOCKED,
    "0": PRODUCT_STATUS_LOCKED,
    "no": PRODUCT_STATUS_LOCKED,
    "locked": PRODUCT_STATUS_LOCKED,
    "未解锁": PRODUCT_STATUS_LOCKED,
    "missing": PRODUCT_STATUS_MISSING,
    "not_found": PRODUCT_STATUS_MISSING,
    "未扫描": PRODUCT_STATUS_MISSING,
    "缺失": PRODUCT_STATUS_MISSING,
}
AUTO_TWO_CITY_TASK_ENTRY = "AutoTwoCityBusiness"
MANUAL_TWO_CITY_TASK_ENTRY = "ManualTwoCityBusiness"


def _read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _blocked_product_unlock_status_by_city(*sources: Any) -> dict[str, dict[str, bool]]:
    blocked: dict[str, dict[str, bool]] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for city, goods in source.items():
            if not isinstance(goods, dict):
                continue
            city_name = normalize_city_name(str(city))
            if not city_name:
                continue
            city_status = blocked.setdefault(city_name, {})
            for good, raw_status in goods.items():
                good_name = str(good or "").strip()
                if not good_name:
                    continue
                if isinstance(raw_status, bool):
                    if raw_status is False:
                        city_status[good_name] = False
                    elif good_name in city_status:
                        city_status.pop(good_name, None)
                    continue
                text = str(raw_status or "").strip()
                status = PRODUCT_STATUS_ALIASES.get(text.lower()) or PRODUCT_STATUS_ALIASES.get(text)
                if status in PRODUCT_PLANNER_BLOCKED_STATUSES:
                    city_status[good_name] = False
                elif good_name in city_status and text in {"true", "1", "normal", "已解锁", "正常"}:
                    city_status.pop(good_name, None)
    return {
        city: goods
        for city, goods in blocked.items()
        if goods
    }


def _city_tax_rate_by_city(*sources: Any) -> dict[str, float]:
    rates: dict[str, float] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for city, value in source.items():
            city_name = normalize_city_name(str(city or "").strip())
            if not city_name:
                continue
            try:
                rate = float(value)
            except (TypeError, ValueError):
                continue
            if rate > 1:
                rate /= 100
            if 0 <= rate <= 1:
                rates[city_name] = rate
    return rates


def _product_buy_lot_by_city(*sources: Any) -> dict[str, dict[str, int]]:
    lots: dict[str, dict[str, int]] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for city, goods in source.items():
            city_name = normalize_city_name(str(city or "").strip())
            if not city_name or not isinstance(goods, dict):
                continue
            city_lots = lots.setdefault(city_name, {})
            for good, value in goods.items():
                good_name = str(good or "").strip()
                if not good_name:
                    continue
                try:
                    lot = int(value)
                except (TypeError, ValueError):
                    continue
                if lot > 0:
                    city_lots[good_name] = lot
    return {city: goods for city, goods in lots.items() if goods}


def _city_trade_read_meta_by_city(*sources: Any) -> dict[str, dict[str, Any]]:
    meta_by_city: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for city, raw_meta in source.items():
            city_name = normalize_city_name(str(city or "").strip())
            if not city_name or not isinstance(raw_meta, dict):
                continue
            meta_by_city.setdefault(city_name, {}).update(raw_meta)
    return {city: meta for city, meta in meta_by_city.items() if meta}


def _known_buy_goods_by_city() -> dict[str, list[str]]:
    trade_data = load_columba_trade_data()
    products = trade_data.get("products") if isinstance(trade_data, dict) else []
    by_city: dict[str, list[str]] = {}
    for product in products if isinstance(products, list) else []:
        if not isinstance(product, dict):
            continue
        name = str(product.get("name") or "").strip()
        buy_lots = product.get("buyLot") if isinstance(product.get("buyLot"), dict) else {}
        if not name:
            continue
        for city in buy_lots:
            city_name = normalize_city_name(str(city or "").strip())
            if city_name:
                by_city.setdefault(city_name, []).append(name)
    return {city: sorted(set(goods)) for city, goods in by_city.items() if goods}


def _product_status_by_city(*sources: Any) -> dict[str, dict[str, str]]:
    status_by_city: dict[str, dict[str, str]] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for city, goods in source.items():
            city_name = normalize_city_name(str(city or "").strip())
            if not city_name or not isinstance(goods, dict):
                continue
            city_status = status_by_city.setdefault(city_name, {})
            for good, raw_status in goods.items():
                good_name = str(good or "").strip()
                if not good_name:
                    continue
                if isinstance(raw_status, bool):
                    normalized = PRODUCT_STATUS_NORMAL if raw_status else PRODUCT_STATUS_LOCKED
                else:
                    text = str(raw_status or "").strip()
                    normalized = PRODUCT_STATUS_ALIASES.get(text.lower()) or PRODUCT_STATUS_ALIASES.get(text)
                    if normalized is None:
                        normalized = text if text in {
                            PRODUCT_STATUS_NORMAL,
                            PRODUCT_STATUS_LOCKED,
                            PRODUCT_STATUS_MISSING,
                            PRODUCT_STATUS_NEVER_SCANNED,
                        } else PRODUCT_STATUS_NEVER_SCANNED
                previous = city_status.get(good_name)
                if (
                    isinstance(raw_status, bool)
                    and raw_status is False
                    and previous
                    and previous != PRODUCT_STATUS_NEVER_SCANNED
                ):
                    continue
                city_status[good_name] = normalized
    return {city: goods for city, goods in status_by_city.items() if goods}


def _required_buy_lot_goods_for_city(city: str, status_by_city: dict[str, dict[str, str]]) -> list[str]:
    known = _known_buy_goods_by_city().get(city, [])
    status = status_by_city.get(city) or {}
    return [
        good
        for good in known
        if status.get(good, PRODUCT_STATUS_NEVER_SCANNED) == PRODUCT_STATUS_NORMAL
    ]


def _complete_product_buy_lot_by_city(account: dict[str, Any]) -> dict[str, dict[str, int]]:
    planner = account.get("planner") if isinstance(account.get("planner"), dict) else {}
    trade = account.get("trade") if isinstance(account.get("trade"), dict) else {}
    lots_by_city = _product_buy_lot_by_city(
        trade.get("product_buy_lot_by_city"),
        planner.get("product_buy_lot_by_city"),
    )
    tax_rates = _city_tax_rate_by_city(
        trade.get("city_tax_rate_by_city"),
        planner.get("city_tax_rate_by_city"),
    )
    status_by_city = _product_status_by_city(
        trade.get("product_status_by_city"),
        planner.get("product_status_by_city"),
        trade.get("product_unlock_status_by_city"),
        planner.get("product_unlock_status_by_city"),
    )
    read_meta = _city_trade_read_meta_by_city(
        trade.get("city_trade_read"),
        planner.get("city_trade_read"),
        account.get("city_trade_read"),
    )
    complete: dict[str, dict[str, int]] = {}
    for city, lots in lots_by_city.items():
        required_goods = _required_buy_lot_goods_for_city(city, status_by_city)
        if not required_goods:
            continue
        if city not in tax_rates:
            continue
        if any(good not in lots for good in required_goods):
            continue
        meta = read_meta.get(city) or {}
        if meta and not bool(meta.get("tax_rate_read", True)):
            continue
        complete[city] = {good: lots[good] for good in required_goods if good in lots}
    return complete


def _city_set(values: Any) -> set[str]:
    if values is None:
        return set()
    if isinstance(values, str):
        raw_values = values.replace("，", ",").split(",")
    else:
        raw_values = values
    result: set[str] = set()
    for value in raw_values:
        city = normalize_city_name(str(value or "").strip())
        if city:
            result.add(city)
    return result


def _account_config_dirs() -> list[Path]:
    return [
        PROJECT_ROOT / "config" / "accounts",
        PROJECT_ROOT / "install" / "config" / "accounts",
    ]


def _is_real_account_config_path(path: Path) -> bool:
    name = path.name.lower()
    if name == "unknown.json":
        return False
    if name.endswith(".product_status_report.json"):
        return False
    if name.endswith(".corrupted_report_backup.json"):
        return False
    return path.suffix.lower() == ".json"


def find_account_config(uid: str = "") -> tuple[Path | None, dict[str, Any]]:
    uid = str(uid or "").strip()
    if uid:
        for directory in _account_config_dirs():
            path = directory / f"{uid}.json"
            data = _read_json(path, {})
            if isinstance(data, dict) and data:
                return path, data
        return None, {}

    candidates: list[Path] = []
    for directory in _account_config_dirs():
        if not directory.exists():
            continue
        candidates.extend(
            path
            for path in directory.glob("*.json")
            if _is_real_account_config_path(path)
        )
    if not candidates:
        return None, {}
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    data = _read_json(path, {})
    return path, data if isinstance(data, dict) else {}


def _default_full_resonance_roles() -> dict[str, dict[str, int]]:
    roles: dict[str, dict[str, int]] = {}
    for role in load_role_names():
        max_level = role_resonance_max(role)
        roles[role] = {"resonance": int(max_level if max_level is not None else 5)}
    return roles


def build_default_account_config(uid: str = "") -> dict[str, Any]:
    roles = _default_full_resonance_roles()
    role_resonance = {role: data["resonance"] for role, data in roles.items()}
    return {
        "uid": str(uid or "default"),
        "source": "manual_trade_default_fallback",
        "trade": {
            "cargo_capacity": DEFAULT_FALLBACK_CARGO_CAPACITY,
            "role_resonance": role_resonance,
            "product_status_by_city": {},
            "product_unlock_status_by_city": {},
        },
        "planner": {
            "max_goods_num": DEFAULT_FALLBACK_CARGO_CAPACITY,
            "roles": roles,
            "product_status_by_city": {},
            "product_unlock_status_by_city": {},
        },
    }


def _planner_options_from_account(
    account: dict[str, Any],
    *,
    start_city: str,
    target_city: str,
    start_book: int,
    target_book: int,
    start_bargain_percent: int,
    start_raise_percent: int,
    target_bargain_percent: int,
    target_raise_percent: int,
    transient_product_status_by_city: dict[str, dict[str, Any]] | None = None,
) -> RoutePlanOptions:
    planner = account.get("planner") if isinstance(account.get("planner"), dict) else {}
    trade = account.get("trade") if isinstance(account.get("trade"), dict) else {}
    max_goods_num = planner.get("max_goods_num") or trade.get("cargo_capacity")
    try:
        max_goods_num = int(max_goods_num)
    except (TypeError, ValueError):
        max_goods_num = None

    prestige_by_city = planner.get("prestige_by_city") or trade.get("prestige_by_city") or {}
    if not isinstance(prestige_by_city, dict):
        prestige_by_city = {}

    roles = planner.get("roles")
    if not isinstance(roles, dict):
        role_resonance = trade.get("role_resonance")
        roles = {
            str(name): {"resonance": int(level)}
            for name, level in role_resonance.items()
        } if isinstance(role_resonance, dict) else {}

    product_unlock_status = planner.get("product_unlock_status")
    if not isinstance(product_unlock_status, dict):
        product_unlock_status = trade.get("product_unlock_status")
    if not isinstance(product_unlock_status, dict):
        product_unlock_status = {}

    product_unlock_status_by_city = _blocked_product_unlock_status_by_city(
        trade.get("product_status_by_city"),
        planner.get("product_status_by_city"),
        trade.get("product_unlock_status_by_city"),
        planner.get("product_unlock_status_by_city"),
    )
    city_tax_rate_by_city = _city_tax_rate_by_city(
        trade.get("city_tax_rate_by_city"),
        planner.get("city_tax_rate_by_city"),
    )
    product_buy_lot_by_city = _complete_product_buy_lot_by_city(account)
    transient_blocked_by_city = _blocked_product_unlock_status_by_city(transient_product_status_by_city)
    for city, goods in transient_blocked_by_city.items():
        product_unlock_status_by_city.setdefault(city, {}).update(goods)

    exclude_cities = set()
    for value in planner.get("exclude_cities") or trade.get("unavailable_cities") or []:
        exclude_cities.add(normalize_city_name(str(value)))
    exclude_cities.discard(start_city)
    exclude_cities.discard(target_city)
    max_book_by_city = {
        start_city: max(0, int(start_book)),
        target_city: max(0, int(target_book)),
    }
    haggle_by_city = {
        start_city: max(0, int(max(start_bargain_percent, start_raise_percent))),
        target_city: max(0, int(max(target_bargain_percent, target_raise_percent))),
    }
    bargain_percent_by_city = {
        start_city: max(0, int(start_bargain_percent)),
        target_city: max(0, int(target_bargain_percent)),
    }
    raise_percent_by_city = {
        start_city: max(0, int(start_raise_percent)),
        target_city: max(0, int(target_raise_percent)),
    }

    return RoutePlanOptions(
        strategy="general_profit_index",
        mixed_currency_priority="total",
        max_goods_num=max_goods_num,
        prestige_by_city={normalize_city_name(str(k)): int(v) for k, v in prestige_by_city.items()},
        roles=roles,
        exclude_cities=exclude_cities,
        include_cities={start_city, target_city},
        directed_city_pairs={(start_city, target_city), (target_city, start_city)},
        max_book_by_city=max_book_by_city,
        haggle_by_city=haggle_by_city,
        bargain_percent_by_city=bargain_percent_by_city,
        raise_percent_by_city=raise_percent_by_city,
        auto_haggle=False,
        use_columba_onegraph=True,
        product_unlock_status={str(good): bool(unlocked) for good, unlocked in product_unlock_status.items()},
        product_unlock_status_by_city=product_unlock_status_by_city,
        city_tax_rate_by_city=city_tax_rate_by_city,
        product_buy_lot_by_city=product_buy_lot_by_city,
    )


def _auto_planner_options_from_account(
    account: dict[str, Any],
    *,
    priority_cities: set[str] | None = None,
    exclude_cities: set[str] | None = None,
    max_restock: int | None = None,
    mixed_currency_priority: Any = "total",
    transient_product_status_by_city: dict[str, dict[str, Any]] | None = None,
) -> RoutePlanOptions:
    planner = account.get("planner") if isinstance(account.get("planner"), dict) else {}
    trade = account.get("trade") if isinstance(account.get("trade"), dict) else {}
    max_goods_num = planner.get("max_goods_num") or trade.get("cargo_capacity")
    try:
        max_goods_num = int(max_goods_num)
    except (TypeError, ValueError):
        max_goods_num = None

    prestige_by_city = planner.get("prestige_by_city") or trade.get("prestige_by_city") or {}
    if not isinstance(prestige_by_city, dict):
        prestige_by_city = {}

    roles = planner.get("roles")
    if not isinstance(roles, dict):
        role_resonance = trade.get("role_resonance")
        roles = {
            str(name): {"resonance": int(level)}
            for name, level in role_resonance.items()
        } if isinstance(role_resonance, dict) else {}

    product_unlock_status = planner.get("product_unlock_status")
    if not isinstance(product_unlock_status, dict):
        product_unlock_status = trade.get("product_unlock_status")
    if not isinstance(product_unlock_status, dict):
        product_unlock_status = {}

    product_unlock_status_by_city = _blocked_product_unlock_status_by_city(
        trade.get("product_status_by_city"),
        planner.get("product_status_by_city"),
        trade.get("product_unlock_status_by_city"),
        planner.get("product_unlock_status_by_city"),
    )
    city_tax_rate_by_city = _city_tax_rate_by_city(
        trade.get("city_tax_rate_by_city"),
        planner.get("city_tax_rate_by_city"),
    )
    product_buy_lot_by_city = _complete_product_buy_lot_by_city(account)
    transient_blocked_by_city = _blocked_product_unlock_status_by_city(transient_product_status_by_city)
    for city, goods in transient_blocked_by_city.items():
        product_unlock_status_by_city.setdefault(city, {}).update(goods)

    account_exclude_cities = set()
    for value in planner.get("exclude_cities") or trade.get("unavailable_cities") or []:
        city = normalize_city_name(str(value))
        if city:
            account_exclude_cities.add(city)
    resolved_exclude_cities = account_exclude_cities | set(exclude_cities or set())

    return RoutePlanOptions(
        strategy="general_profit_index",
        mixed_currency_priority=normalize_mixed_currency_priority(mixed_currency_priority),
        max_goods_num=max_goods_num,
        max_restock=max(0, int(max_restock)) if max_restock is not None else None,
        prestige_by_city={normalize_city_name(str(k)): int(v) for k, v in prestige_by_city.items()},
        roles=roles,
        exclude_cities=resolved_exclude_cities,
        auto_haggle=True,
        bargain_percent=20,
        raise_percent=20,
        use_columba_onegraph=True,
        product_unlock_status={str(good): bool(unlocked) for good, unlocked in product_unlock_status.items()},
        product_unlock_status_by_city=product_unlock_status_by_city,
        city_tax_rate_by_city=city_tax_rate_by_city,
        product_buy_lot_by_city=product_buy_lot_by_city,
    )


def _route_city_names(summary: dict[str, Any]) -> set[str]:
    cities: set[str] = set()
    for leg in summary.get("legs") or []:
        buy_city = normalize_city_name(str(leg.get("buy_city") or "").strip())
        sell_city = normalize_city_name(str(leg.get("sell_city") or "").strip())
        if buy_city:
            cities.add(buy_city)
        if sell_city:
            cities.add(sell_city)
    return cities


def calculate_auto_two_city_trade(
    *,
    uid: str = "",
    priority_cities: Any = None,
    exclude_cities: Any = None,
    max_restock: int = 6,
    wulinyuan_priority: Any = "total",
    transient_product_status_by_city: dict[str, dict[str, Any]] | None = None,
    allow_default_account: bool = False,
) -> dict[str, Any]:
    priority_city_set = _city_set(priority_cities)
    exclude_city_set = _city_set(exclude_cities)
    conflict_cities = sorted(priority_city_set & exclude_city_set)
    if conflict_cities:
        raise ValueError("优先城市和排除城市不能重复：" + "、".join(conflict_cities))
    if len(priority_city_set) > 2:
        raise ValueError("双城跑商线路最多只能包含 2 个优先城市")

    config_path, account = find_account_config(uid)
    if not account:
        if not allow_default_account:
            raise FileNotFoundError("未找到账号配置，请先运行读取账号配置")
        account = build_default_account_config(uid)
    used_default_account = config_path is None

    market = load_columba_baseline_market_data()
    options = _auto_planner_options_from_account(
        account,
        priority_cities=priority_city_set,
        exclude_cities=exclude_city_set,
        max_restock=max_restock,
        mixed_currency_priority=wulinyuan_priority,
        transient_product_status_by_city=transient_product_status_by_city,
    )
    routes = plan_two_city_routes(market, options)
    if priority_city_set:
        routes = [
            route
            for route in routes
            if priority_city_set.issubset({item.buy_city_name for item in route.city_data} | {item.sell_city_name for item in route.city_data})
        ]
    if not routes:
        raise RuntimeError("未能计算符合条件的自动双城跑商线路")

    route = routes[0]
    summary = summarize_routes(route, options.strategy)
    legs = summary.get("legs") if isinstance(summary.get("legs"), list) else []
    if len(legs) < 2 or not isinstance(legs[0], dict) or not isinstance(legs[1], dict):
        raise RuntimeError("自动双城跑商规划结果不完整")

    start_city = normalize_city_name(str(legs[0].get("buy_city") or "").strip())
    target_city = normalize_city_name(str(legs[0].get("sell_city") or "").strip())
    result = {
        "version": 1,
        "mode": "auto",
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "uid": str(account.get("uid") or uid or ""),
        "account_config": str(config_path) if config_path else "",
        "used_default_account_config": bool(used_default_account),
        "default_account_cargo_capacity": DEFAULT_FALLBACK_CARGO_CAPACITY if used_default_account else None,
        "start_city": start_city,
        "target_city": target_city,
        "start_book": max(0, int(legs[0].get("restock") or 0)),
        "target_book": max(0, int(legs[1].get("restock") or 0)),
        "start_bargain_percent": 20 if bool(legs[0].get("uses_haggle")) else 0,
        "start_raise_percent": 20 if bool(legs[0].get("uses_haggle")) else 0,
        "target_bargain_percent": 20 if bool(legs[1].get("uses_haggle")) else 0,
        "target_raise_percent": 20 if bool(legs[1].get("uses_haggle")) else 0,
        "start_haggle_percent": max(0, int(legs[0].get("haggle_num") or 0)),
        "target_haggle_percent": max(0, int(legs[1].get("haggle_num") or 0)),
        "cargo_capacity": options.max_goods_num,
        "priority_cities": sorted(priority_city_set),
        "exclude_cities": sorted(exclude_city_set),
        "max_restock": max(0, int(max_restock)),
        "wulinyuan_priority": normalize_mixed_currency_priority(wulinyuan_priority),
        "summary": summary,
    }
    return result


def calculate_manual_two_city_trade(
    *,
    start_city: str,
    target_city: str,
    uid: str = "",
    start_book: int = 4,
    target_book: int = 0,
    start_haggle_percent: int | None = None,
    target_haggle_percent: int | None = None,
    start_bargain_percent: int | None = None,
    start_raise_percent: int | None = None,
    target_bargain_percent: int | None = None,
    target_raise_percent: int | None = None,
    transient_product_status_by_city: dict[str, dict[str, Any]] | None = None,
    allow_default_account: bool = False,
) -> dict[str, Any]:
    start_city = normalize_city_name(str(start_city or "").strip())
    target_city = normalize_city_name(str(target_city or "").strip())
    if not start_city or not target_city:
        raise ValueError("起点城市和目标城市不能为空")
    if start_city == target_city:
        raise ValueError("起点城市和目标城市不能相同")

    config_path, account = find_account_config(uid)
    if not account:
        if not allow_default_account:
            raise FileNotFoundError("未找到账号配置，请先运行读取账号配置")
        account = build_default_account_config(uid)
    used_default_account = config_path is None

    if start_bargain_percent is None:
        start_bargain_percent = 20 if start_haggle_percent is None else int(start_haggle_percent)
    if start_raise_percent is None:
        start_raise_percent = 20 if start_haggle_percent is None else int(start_haggle_percent)
    if target_bargain_percent is None:
        target_bargain_percent = 0 if target_haggle_percent is None else int(target_haggle_percent)
    if target_raise_percent is None:
        target_raise_percent = 0 if target_haggle_percent is None else int(target_haggle_percent)

    market = load_columba_baseline_market_data()
    options = _planner_options_from_account(
        account,
        start_city=start_city,
        target_city=target_city,
        start_book=start_book,
        target_book=target_book,
        start_bargain_percent=int(start_bargain_percent),
        start_raise_percent=int(start_raise_percent),
        target_bargain_percent=int(target_bargain_percent),
        target_raise_percent=int(target_raise_percent),
        transient_product_status_by_city=transient_product_status_by_city,
    )
    routes = plan_two_city_routes(market, options)
    if not routes:
        raise RuntimeError(f"未能计算 {start_city} <-> {target_city} 的预期收益")

    route = next(
        (
            item
            for item in routes
            if item.city_data
            and item.city_data[0].buy_city_name == start_city
            and item.city_data[0].sell_city_name == target_city
        ),
        routes[0],
    )
    # With directed_city_pairs/include_cities fixed, this is the best goods
    # selection for the requested pair rather than a city-route search result.
    summary = summarize_routes(route, options.strategy)
    legs = summary.get("legs") if isinstance(summary.get("legs"), list) else []
    if (
        len(legs) == 2
        and isinstance(legs[0], dict)
        and isinstance(legs[1], dict)
        and legs[0].get("buy_city") == target_city
        and legs[0].get("sell_city") == start_city
        and legs[1].get("buy_city") == start_city
        and legs[1].get("sell_city") == target_city
    ):
        summary["legs"] = [legs[1], legs[0]]
    result = {
        "version": 1,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "uid": str(account.get("uid") or uid or ""),
        "account_config": str(config_path) if config_path else "",
        "used_default_account_config": bool(used_default_account),
        "default_account_cargo_capacity": DEFAULT_FALLBACK_CARGO_CAPACITY if used_default_account else None,
        "start_city": start_city,
        "target_city": target_city,
        "start_book": max(0, int(start_book)),
        "target_book": max(0, int(target_book)),
        "start_bargain_percent": max(0, int(start_bargain_percent)),
        "start_raise_percent": max(0, int(start_raise_percent)),
        "target_bargain_percent": max(0, int(target_bargain_percent)),
        "target_raise_percent": max(0, int(target_raise_percent)),
        "start_haggle_percent": max(0, int(max(int(start_bargain_percent), int(start_raise_percent)))),
        "target_haggle_percent": max(0, int(max(int(target_bargain_percent), int(target_raise_percent)))),
        "cargo_capacity": options.max_goods_num,
        "summary": summary,
    }
    return result


def save_manual_two_city_result(result: dict[str, Any], *, task_entry: str = MANUAL_TWO_CITY_TASK_ENTRY) -> Path:
    task_dir = PROJECT_ROOT / "config" / "tasks" / task_entry
    task_dir.mkdir(parents=True, exist_ok=True)
    output_path = task_dir / "manual_two_city_business.json"
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path

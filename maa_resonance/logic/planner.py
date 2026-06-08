from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Literal

import requests
from loguru import logger

from .models import RouteModel, RoutesModel
from .paths import RESOURCES_PATH, ROOT_PATH, read_json

RouteStrategy = Literal["profit", "tired_profit", "book_profit", "general_profit_index"]
MixedCurrencyPriority = Literal["total", "jiaozi", "tiemeng"]
MIXED_CURRENCY_PRIORITIES: tuple[MixedCurrencyPriority, ...] = ("total", "jiaozi", "tiemeng")
MIXED_CURRENCY_PRIORITY_ALIASES = {
    "0": "total",
    "total": "total",
    "mixed-total-first": "total",
    "综合": "total",
    "综合优先": "total",
    "总和": "total",
    "总和优先": "total",
    "1": "jiaozi",
    "jiaozi": "jiaozi",
    "mixed-jiaozi-first": "jiaozi",
    "交子": "jiaozi",
    "交子优先": "jiaozi",
    "2": "tiemeng",
    "tiemeng": "tiemeng",
    "mixed-tiemeng-first": "tiemeng",
    "铁盟": "tiemeng",
    "铁盟币": "tiemeng",
    "铁盟优先": "tiemeng",
    "铁盟币优先": "tiemeng",
}
TIRED_DISTANCE_RATIO = 40.0
GENERAL_PROFIT_INDEX_RESTOCK_FATIGUE_CONSTANT = 33
PLANNED_HAGGLE_PERCENT = 20
COLUMBA_TRADE_DATA_PATH = RESOURCES_PATH / "goods" / "ColumbaTradeData2026.json"
COLUMBA_FATIGUE_DATA_PATH = RESOURCES_PATH / "goods" / "CityFatigueData2026.json"
COLUMBA_LOCAL_MARKET_DATA_PATH = RESOURCES_PATH / "goods" / "ColumbaLocalMarketData2026.json"
DEFAULT_MARKET_CACHE_TTL = 300.0
MARKET_CACHE_DIR = ROOT_PATH / "cache" / "market"
CITY_NAME_ALIASES = {
    "\u4e03\u53f7\u81ea\u7531\u6e2f": "7\u53f7\u81ea\u7531\u6e2f",
}
WULINYUAN_CITY_NAME = "武林源"
WULINYUAN_CURRENCY_NAME = "交子"
WULINYUAN_BASE_CURRENCY_NAME = "铁盟币"
WULINYUAN_PRICE_DIVISOR_FROM_BASE = 20


@dataclass(frozen=True)
class MarketData:
    buy_goods: dict[str, dict[str, dict[str, Any]]]
    sell_prices: dict[str, dict[str, dict[str, Any]]]
    tired: dict[str, int]
    buy_prices: dict[str, dict[str, dict[str, Any]]] | None = None


@dataclass(frozen=True)
class RoutePlanOptions:
    strategy: RouteStrategy = "general_profit_index"
    mixed_currency_priority: MixedCurrencyPriority = "total"
    max_goods_num: int | None = None
    max_restock: int | None = None
    max_book_by_city: dict[str, int] | None = None
    haggle_by_city: dict[str, int] | None = None
    auto_haggle: bool = True
    include_cities: set[str] | None = None
    exclude_cities: set[str] | None = None
    directed_city_pairs: set[tuple[str, str]] | None = None
    allowed_city_pairs: set[frozenset[str]] | None = None
    blocked_city_pairs: set[frozenset[str]] | None = None
    allowed_goods: set[str] | None = None
    blocked_goods: set[str] | None = None
    min_profit: int = 1
    bargain_percent: int = 20
    raise_percent: int = 20
    bargain_percent_by_city: dict[str, int] | None = None
    raise_percent_by_city: dict[str, int] | None = None
    bargain_fatigue: int = 20
    raise_fatigue: int = 20
    compare_no_return_bargain: bool = True
    default_prestige_level: int = 20
    prestige_by_city: dict[str, int] | None = None
    roles: dict[str, dict[str, int]] | None = None
    use_default_roles: bool = True
    disabled_roles: set[str] | None = None
    events: dict[str, dict[str, bool]] | None = None
    product_unlock_status: dict[str, bool] | None = None
    product_unlock_status_by_city: dict[str, dict[str, bool]] | None = None
    use_default_product_unlock_status: bool = False
    use_columba_onegraph: bool = True


@dataclass(frozen=True)
class BargainProfile:
    bargain_percent: int
    raise_percent: int
    bargain_fatigue: int
    raise_fatigue: int
    disabled: bool = False


def js_round(value: float) -> int:
    return math.floor(value + 0.5)


def normalize_city_name(name: str) -> str:
    return CITY_NAME_ALIASES.get(str(name), str(name))


def normalize_mixed_currency_priority(value: Any) -> MixedCurrencyPriority:
    normalized = MIXED_CURRENCY_PRIORITY_ALIASES.get(str(value).strip().lower())
    if normalized in MIXED_CURRENCY_PRIORITIES:
        return normalized
    normalized = MIXED_CURRENCY_PRIORITY_ALIASES.get(str(value).strip())
    if normalized in MIXED_CURRENCY_PRIORITIES:
        return normalized
    return "total"


def normalize_route_key(key: str) -> str:
    parts = str(key).split("-", 1)
    if len(parts) != 2:
        return str(key)
    return f"{normalize_city_name(parts[0])}-{normalize_city_name(parts[1])}"


def normalize_city_pair(value: str) -> frozenset[str] | None:
    text = str(value).strip()
    if not text:
        return None
    for delimiter in ("<->", "->", "-", "，", ",", " "):
        if delimiter in text:
            parts = [normalize_city_name(part.strip()) for part in text.split(delimiter, 1)]
            break
    else:
        return None
    parts = [part for part in parts if part]
    if len(parts) != 2 or parts[0] == parts[1]:
        return None
    return frozenset(parts)


def normalize_city_pairs(values: Iterable[str] | None) -> set[frozenset[str]] | None:
    pairs = {pair for value in values or [] if (pair := normalize_city_pair(value))}
    return pairs or None


def route_pair(buy_city: str, sell_city: str) -> frozenset[str]:
    return frozenset((normalize_city_name(buy_city), normalize_city_name(sell_city)))


def normalize_city_mapping_keys(data: dict[str, Any]) -> dict[str, Any]:
    return {normalize_city_name(key): value for key, value in data.items()}


def normalize_tired_data(data: dict[str, Any]) -> dict[str, int]:
    if isinstance(data.get("map"), dict):
        data = data["map"]
    return {
        normalize_route_key(key): int(value)
        for key, value in data.items()
        if not isinstance(value, dict)
    }


@lru_cache(maxsize=1)
def load_columba_trade_data() -> dict[str, Any]:
    if not COLUMBA_TRADE_DATA_PATH.exists():
        return {}
    return read_json(COLUMBA_TRADE_DATA_PATH)


@lru_cache(maxsize=1)
def load_default_tired_data() -> dict[str, int]:
    if COLUMBA_FATIGUE_DATA_PATH.exists():
        data = read_json(COLUMBA_FATIGUE_DATA_PATH)
        if isinstance(data, dict) and isinstance(data.get("map"), dict):
            return normalize_tired_data(data)
    legacy_path = RESOURCES_PATH / "goods" / "CityTiredData.json"
    if legacy_path.exists():
        return normalize_tired_data(read_json(legacy_path))
    return {}


def load_station_world_coords() -> dict[str, tuple[float, float]]:
    path = RESOURCES_PATH / "map" / "CityWorld2026.json"
    if not path.exists():
        return {}
    data = read_json(path)
    stations = data.get("stations", []) + data.get("hidden_stations", [])
    return {
        normalize_city_name(station["name"]): (float(station["x"]), float(station["y"]))
        for station in stations
        if station.get("name") and "x" in station and "y" in station
    }


def load_local_market_data() -> MarketData:
    local_prices = read_json(RESOURCES_PATH / "goods" / "CityGoodsSellData.json")
    return MarketData(
        buy_goods=read_json(RESOURCES_PATH / "goods" / "CityGoodsData.json"),
        sell_prices=local_prices,
        tired=load_default_tired_data(),
        buy_prices=local_prices,
    )


def load_columba_baseline_market_data() -> MarketData:
    if not COLUMBA_LOCAL_MARKET_DATA_PATH.exists():
        raise FileNotFoundError(f"columba baseline market data not found: {COLUMBA_LOCAL_MARKET_DATA_PATH}")
    return load_market_data_file(COLUMBA_LOCAL_MARKET_DATA_PATH)


def market_data_from_server_trade(payload: dict[str, Any]) -> MarketData:
    server_trade = payload.get("server_trade") if "server_trade" in payload else payload
    if not isinstance(server_trade, dict):
        raise ValueError("server_trade is not a JSON object")

    buy_goods: dict[str, dict[str, dict[str, Any]]] = {}
    buy_prices: dict[str, dict[str, dict[str, Any]]] = {}
    sell_prices: dict[str, dict[str, dict[str, Any]]] = {}
    for good_name, trade_info in server_trade.items():
        if not isinstance(trade_info, dict):
            continue
        for city_name, info in (trade_info.get("buy") or {}).items():
            if not isinstance(info, dict):
                continue
            city = normalize_city_name(city_name)
            stock = int(info.get("stock") or 1)
            buy_goods.setdefault(city, {})[good_name] = {
                "num": max(1, stock),
                "stock": stock,
                "trend": info.get("trend"),
                "base_price": info.get("base_price"),
            }
            buy_prices.setdefault(city, {})[good_name] = info
        for city_name, info in (trade_info.get("sell") or {}).items():
            if not isinstance(info, dict):
                continue
            sell_prices.setdefault(normalize_city_name(city_name), {})[good_name] = info

    tired = (
        payload.get("tired")
        or payload.get("CityTiredData")
        or payload.get("cityTiredData")
        or load_default_tired_data()
    )
    if isinstance(tired, dict):
        tired = normalize_tired_data(tired)
    return MarketData(
        buy_goods=buy_goods,
        buy_prices=buy_prices,
        sell_prices=sell_prices,
        tired=tired,
    )


def market_data_from_payload(payload: dict[str, Any]) -> MarketData:
    """Accept both project-style and API-style market payloads."""
    if "server_trade" in payload or all(
        isinstance(item, dict) and ("buy" in item or "sell" in item)
        for item in payload.values()
    ):
        return market_data_from_server_trade(payload)

    buy_goods = (
        payload.get("buy_goods")
        or payload.get("goods")
        or payload.get("CityGoodsData")
        or payload.get("cityGoodsData")
    )
    buy_prices = payload.get("buy_prices") or payload.get("buyPrices")
    sell_prices = (
        payload.get("sell_prices")
        or payload.get("prices")
        or payload.get("CityGoodsSellData")
        or payload.get("cityGoodsSellData")
    )
    tired = (
        payload.get("tired")
        or payload.get("CityTiredData")
        or payload.get("cityTiredData")
        or load_default_tired_data()
    )
    if not isinstance(buy_goods, dict) or not isinstance(sell_prices, dict) or not isinstance(tired, dict):
        raise ValueError("market payload is missing buy_goods/sell_prices/tired")
    return MarketData(
        buy_goods=normalize_city_mapping_keys(buy_goods),
        buy_prices=normalize_city_mapping_keys(buy_prices) if isinstance(buy_prices, dict) else None,
        sell_prices=normalize_city_mapping_keys(sell_prices),
        tired=normalize_tired_data(tired),
    )


def unwrap_market_payload(payload: Any, source: str = "market API") -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    if not isinstance(payload, dict):
        raise ValueError(f"{source} did not return a JSON object")
    return payload


def market_cache_path(api_url: str, cache_dir: str | Path | None = None) -> Path:
    digest = hashlib.sha1(api_url.encode("utf-8")).hexdigest()
    return Path(cache_dir or MARKET_CACHE_DIR) / f"{digest}.json"


def resolve_market_data_file_path(path: str | Path) -> Path:
    """把 Maa UI 中填写的本地行情路径解析到项目根目录。"""
    market_path = Path(path).expanduser()
    if not market_path.is_absolute():
        market_path = ROOT_PATH / market_path
    return market_path


def read_market_cache(
    api_url: str,
    *,
    cache_dir: str | Path | None = None,
) -> tuple[dict[str, Any], float, Path] | None:
    path = market_cache_path(api_url, cache_dir)
    if not path.exists():
        return None
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"读取行情缓存失败，已忽略: {path} ({exc})")
        return None
    if not isinstance(cache, dict):
        return None
    if cache.get("url") and cache.get("url") != api_url:
        return None
    payload = cache.get("payload")
    fetched_at = cache.get("fetched_at")
    if not isinstance(payload, dict) or not isinstance(fetched_at, (int, float)):
        return None
    return payload, float(fetched_at), path


def write_market_cache(
    api_url: str,
    payload: dict[str, Any],
    *,
    cache_dir: str | Path | None = None,
) -> None:
    path = market_cache_path(api_url, cache_dir)
    cache = {
        "url": api_url,
        "fetched_at": time.time(),
        "payload": payload,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    except OSError as exc:
        logger.warning(f"写入行情缓存失败，已继续使用实时数据: {path} ({exc})")


def market_cache_is_fresh(fetched_at: float, cache_ttl: float | None) -> bool:
    if cache_ttl is None:
        return True
    return cache_ttl > 0 and time.time() - fetched_at < cache_ttl


def market_data_from_cache(payload: dict[str, Any], path: Path) -> MarketData | None:
    try:
        return market_data_from_payload(unwrap_market_payload(payload, "market cache"))
    except Exception as exc:
        logger.warning(f"行情缓存不可用，已忽略: {path} ({exc})")
        return None


def fetch_market_data(
    api_url: str,
    *,
    timeout: float = 10.0,
    headers: dict[str, str] | None = None,
    cache_ttl: float | None = DEFAULT_MARKET_CACHE_TTL,
    use_cache: bool = True,
    refresh_cache: bool = False,
    cache_dir: str | Path | None = None,
) -> MarketData:
    cached = read_market_cache(api_url, cache_dir=cache_dir) if use_cache else None
    if cached and not refresh_cache and market_cache_is_fresh(cached[1], cache_ttl):
        market = market_data_from_cache(cached[0], cached[2])
        if market:
            logger.info(f"使用本地行情缓存: {cached[2]}")
            return market

    try:
        response = requests.get(api_url, timeout=timeout, headers=headers)
        response.raise_for_status()
        raw_payload = response.json()
        payload = unwrap_market_payload(raw_payload)
        market = market_data_from_payload(payload)
    except Exception as exc:
        if cached:
            market = market_data_from_cache(cached[0], cached[2])
            if market:
                logger.warning(f"实时行情请求失败，使用本地缓存: {exc}")
                return market
        raise

    if use_cache and isinstance(raw_payload, dict):
        write_market_cache(api_url, raw_payload, cache_dir=cache_dir)
    return market


def load_market_data_file(path: str | Path) -> MarketData:
    payload = json.loads(resolve_market_data_file_path(path).read_text(encoding="utf-8"))
    payload = unwrap_market_payload(payload, "market data file")
    return market_data_from_payload(payload)


def load_market_data(
    api_url: str | None = None,
    *,
    cache_ttl: float | None = DEFAULT_MARKET_CACHE_TTL,
    use_cache: bool = True,
    refresh_cache: bool = False,
    use_local_baseline: bool = False,
) -> MarketData:
    if api_url:
        return fetch_market_data(
            api_url,
            cache_ttl=cache_ttl,
            use_cache=use_cache,
            refresh_cache=refresh_cache,
        )
    if use_local_baseline:
        return load_columba_baseline_market_data()
    return load_local_market_data()


def calculate_general_profit_index(profit: int, fatigue: int, restock: int) -> int:
    denominator = fatigue + restock * GENERAL_PROFIT_INDEX_RESTOCK_FATIGUE_CONSTANT
    if denominator <= 0:
        return 0
    return js_round(profit / denominator)


def route_score(route: RouteModel, strategy: RouteStrategy) -> float:
    if strategy == "tired_profit":
        return route.tired_profit
    if strategy == "book_profit":
        return route.book_profit
    if strategy == "general_profit_index":
        return route.general_profit_index or route.book_profit
    return route.profit


def routes_score(routes: RoutesModel, strategy: RouteStrategy) -> float:
    if strategy == "general_profit_index" and routes.general_profit_index:
        return routes.general_profit_index
    if strategy == "tired_profit" and routes.tired_profit:
        return routes.tired_profit
    if strategy == "profit" and routes.profit:
        return routes.profit
    return sum(route_score(route, strategy) for route in routes.city_data)


def mixed_currency_score_tuple(
    metrics: dict[str, int],
    priority: MixedCurrencyPriority,
) -> tuple[int, int, int, int]:
    priority = normalize_mixed_currency_priority(priority)
    jiaozi_index = int(metrics.get("jiaozi_general_profit_index", 0) or 0)
    tiemeng_index = int(metrics.get("tiemeng_general_profit_index", 0) or 0)
    total_index = int(metrics.get("total_general_profit_index", jiaozi_index + tiemeng_index) or 0)
    jiaozi_profit_score = int(
        metrics.get("jiaozi_profit_score", metrics.get("jiaozi_profit", 0)) or 0
    )
    tiemeng_profit = int(metrics.get("tiemeng_profit", 0) or 0)
    total_profit_score = int(
        metrics.get("profit_score", jiaozi_profit_score + tiemeng_profit) or 0
    )
    if priority == "jiaozi":
        return (jiaozi_index, tiemeng_index, jiaozi_profit_score, tiemeng_profit)
    if priority == "tiemeng":
        return (tiemeng_index, jiaozi_index, tiemeng_profit, jiaozi_profit_score)
    return (total_index, tiemeng_index, total_profit_score, tiemeng_profit)


def routes_mixed_currency_score_tuple(
    routes: RoutesModel,
    priority: MixedCurrencyPriority,
) -> tuple[int, int, int, int] | None:
    if routes.jiaozi_profit is None or routes.tiemeng_profit is None:
        return None
    jiaozi_profit_score = max(0, int(routes.profit) - int(routes.tiemeng_profit))
    return mixed_currency_score_tuple(
        {
            "jiaozi_general_profit_index": int(routes.jiaozi_general_profit_index or 0),
            "tiemeng_general_profit_index": int(routes.tiemeng_general_profit_index or 0),
            "total_general_profit_index": int(routes.general_profit_index or 0),
            "jiaozi_profit": int(routes.jiaozi_profit or 0),
            "jiaozi_profit_score": jiaozi_profit_score,
            "tiemeng_profit": int(routes.tiemeng_profit or 0),
            "profit_score": int(routes.profit or 0),
        },
        priority,
    )


def routes_sort_key(
    routes: RoutesModel,
    strategy: RouteStrategy,
    mixed_currency_priority: MixedCurrencyPriority = "total",
) -> tuple[float, float, float, float]:
    mixed_score = (
        routes_mixed_currency_score_tuple(routes, mixed_currency_priority)
        if strategy == "general_profit_index"
        else None
    )
    if mixed_score is not None:
        return mixed_score
    return (routes_score(routes, strategy), 0, 0, 0)


def route_tired(
    market: MarketData,
    buy_city: str,
    sell_city: str,
    roles: dict[str, dict[str, int]] | None = None,
) -> tuple[int, bool]:
    buy_city = normalize_city_name(buy_city)
    sell_city = normalize_city_name(sell_city)
    tired_value = market.tired.get(f"{buy_city}-{sell_city}") or market.tired.get(f"{sell_city}-{buy_city}")
    if tired_value is not None:
        fatigue = int(tired_value)
        if fatigue and (roles or {}).get("\u6ce2\u514b\u58eb", {}).get("resonance") == 1:
            fatigue -= 1
        return fatigue, False

    coords = load_station_world_coords()
    if buy_city not in coords or sell_city not in coords:
        return 999, True

    ax, ay = coords[buy_city]
    bx, by = coords[sell_city]
    estimated = max(1, int(round(math.hypot(ax - bx, ay - by) / TIRED_DISTANCE_RATIO)))
    return estimated, True


def get_trade_products(trade_data: dict[str, Any]) -> list[dict[str, Any]]:
    products = trade_data.get("products", [])
    return products if isinstance(products, list) else []


def get_default_player_config(trade_data: dict[str, Any]) -> dict[str, Any]:
    config = trade_data.get("default_player_config")
    return config if isinstance(config, dict) else {}


def get_default_max_lot(trade_data: dict[str, Any]) -> int:
    return int(get_default_player_config(trade_data).get("maxLot") or 1136)


def get_default_max_restock(trade_data: dict[str, Any]) -> int:
    onegraph = get_default_player_config(trade_data).get("onegraph") or {}
    return int(onegraph.get("maxRestock") or 4)


def normalize_roles_config(roles: dict[str, Any] | None) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for role_name, value in (roles or {}).items():
        if isinstance(value, dict):
            resonance = int(value.get("resonance") or 0)
        else:
            resonance = int(value or 0)
        if resonance <= 0:
            resonance = 0
        elif resonance < 4:
            resonance = 1
        elif resonance > 5:
            resonance = 5
        result[role_name] = {"resonance": resonance}
    return result


def get_trade_roles(trade_data: dict[str, Any], options: RoutePlanOptions) -> dict[str, dict[str, int]]:
    default_config = get_default_player_config(trade_data)
    roles: dict[str, dict[str, int]] = {}
    if options.use_default_roles:
        roles.update(normalize_roles_config(default_config.get("roles") or trade_data.get("default_roles")))
    roles.update(normalize_roles_config(options.roles))
    skills = trade_data.get("resonance_skills") or {}
    for role_name, skill_by_level in skills.items():
        if roles.get(role_name, {}).get("resonance") is not None:
            continue
        levels = [
            int(level)
            for level in (skill_by_level or {}).keys()
            if str(level).isdigit()
        ]
        if levels and options.use_default_roles:
            roles[role_name] = {"resonance": max(levels)}
    for role_name in options.disabled_roles or set():
        roles.pop(role_name, None)
    return roles


def get_events_config(trade_data: dict[str, Any], options: RoutePlanOptions) -> dict[str, dict[str, bool]]:
    events = dict((get_default_player_config(trade_data).get("events") or {}))
    events.update(options.events or {})
    return events


def get_product_unlock_status(trade_data: dict[str, Any], options: RoutePlanOptions) -> dict[str, bool]:
    status: dict[str, bool] = {}
    if options.use_default_product_unlock_status:
        status.update(get_default_player_config(trade_data).get("productUnlockStatus") or {})
    status.update(options.product_unlock_status or {})
    return status


def product_unlocked(
    product_name: str,
    buy_city: str,
    global_status: dict[str, bool],
    options: RoutePlanOptions,
) -> bool:
    city_status = (options.product_unlock_status_by_city or {}).get(buy_city) or {}
    if product_name in city_status:
        return bool(city_status[product_name])
    for delimiter in ("/", "\\", "|"):
        city_key = f"{buy_city}{delimiter}{product_name}"
        if city_key in global_status:
            return bool(global_status[city_key])
    return global_status.get(product_name) is not False


def get_max_lot(trade_data: dict[str, Any], options: RoutePlanOptions) -> int:
    return max(1, int(options.max_goods_num if options.max_goods_num is not None else get_default_max_lot(trade_data)))


def get_max_restock(trade_data: dict[str, Any], options: RoutePlanOptions) -> int:
    return max(0, int(options.max_restock if options.max_restock is not None else get_default_max_restock(trade_data)))


def get_city_master(trade_data: dict[str, Any], city: str) -> str:
    city_belongs_to = trade_data.get("city_belongs_to") or {}
    return normalize_city_name(city_belongs_to.get(city, city))


def get_prestige_config(trade_data: dict[str, Any], city: str, options: RoutePlanOptions) -> dict[str, Any]:
    master = get_city_master(trade_data, city)
    default_prestige = get_default_player_config(trade_data).get("prestige") or {}
    level = (options.prestige_by_city or {}).get(master)
    if level is None:
        level = (options.prestige_by_city or {}).get(city)
    if level is None:
        level = default_prestige.get(master, default_prestige.get(city, options.default_prestige_level))
    for item in trade_data.get("prestige_levels") or []:
        if int(item.get("level", 0)) == int(level):
            return item
    levels = trade_data.get("prestige_levels") or []
    return levels[-1] if levels else {"generalTax": 0, "specialTax": {}, "extraBuy": 0}


def get_prestige_tax_rate(prestige: dict[str, Any], master_city: str) -> float:
    special_tax = prestige.get("specialTax") or {}
    city_tax = special_tax.get(master_city)
    return float(city_tax if city_tax is not None else prestige.get("generalTax", 0))


def get_resonance_skill_buy_more_percent(
    trade_data: dict[str, Any],
    roles: dict[str, dict[str, int]],
    product: dict[str, Any],
    from_city: str,
) -> float:
    percent = 0.0
    role_skills = trade_data.get("resonance_skills") or {}
    for role_name, player_role in roles.items():
        level = player_role.get("resonance", 0)
        if not level:
            continue
        skill = (role_skills.get(role_name) or {}).get(str(level))
        if not skill:
            continue
        buy_more = skill.get("buyMore") or {}
        percent += float((buy_more.get("product") or {}).get(product.get("name"), 0))
        if product.get("type") == "Special":
            percent += float((buy_more.get("city") or {}).get(from_city, 0))
        percent += float(buy_more.get("all") or 0)
    return percent


def get_resonance_skill_tax_cut_percent(
    trade_data: dict[str, Any],
    roles: dict[str, dict[str, int]],
    from_city: str,
) -> float:
    percent = 0.0
    role_skills = trade_data.get("resonance_skills") or {}
    for role_name, player_role in roles.items():
        level = player_role.get("resonance", 0)
        if not level:
            continue
        skill = (role_skills.get(role_name) or {}).get(str(level))
        if not skill:
            continue
        tax_cut = skill.get("taxCut") or {}
        percent += float((tax_cut.get("city") or {}).get(from_city, 0))
    return percent


def event_is_active(event: dict[str, Any], events_config: dict[str, dict[str, bool]]) -> bool:
    if not event.get("playConfigurable", False):
        return True
    return bool((events_config.get(event.get("name", "")) or {}).get("activated"))


def get_game_event_buy_more_percent(
    trade_data: dict[str, Any],
    product: dict[str, Any],
    from_city: str,
    events_config: dict[str, dict[str, bool]],
) -> float:
    percent = 0.0
    for event in trade_data.get("events") or []:
        if not event_is_active(event, events_config):
            continue
        buy_more = event.get("buyMore") or {}
        percent += float((buy_more.get("product") or {}).get(product.get("name"), 0))
        if product.get("type") == "Special":
            percent += float((buy_more.get("city") or {}).get(from_city, 0))
    return percent


def get_game_event_tax_variation(
    trade_data: dict[str, Any],
    product: dict[str, Any],
    from_city: str,
    events_config: dict[str, dict[str, bool]],
) -> float:
    variation = 0.0
    for event in trade_data.get("events") or []:
        if not event_is_active(event, events_config):
            continue
        tax_variation = event.get("taxVariation") or {}
        variation += float((tax_variation.get("product") or {}).get(product.get("name"), 0))
        if product.get("type") == "Special":
            variation += float((tax_variation.get("city") or {}).get(from_city, 0))
    return variation


def get_price(info: dict[str, Any] | None) -> float:
    if not isinstance(info, dict):
        return 0.0
    try:
        return float(info.get("price") or 0)
    except (TypeError, ValueError):
        return 0.0


def city_allowed(buy_city: str, sell_city: str, options: RoutePlanOptions) -> bool:
    if buy_city == sell_city:
        return False
    if options.directed_city_pairs and (buy_city, sell_city) not in options.directed_city_pairs:
        return False
    if options.include_cities:
        if len(options.include_cities) == 1:
            if buy_city not in options.include_cities and sell_city not in options.include_cities:
                return False
        elif buy_city not in options.include_cities or sell_city not in options.include_cities:
            return False
    if options.exclude_cities and (buy_city in options.exclude_cities or sell_city in options.exclude_cities):
        return False
    pair = route_pair(buy_city, sell_city)
    if options.allowed_city_pairs and pair not in options.allowed_city_pairs:
        return False
    if options.blocked_city_pairs and pair in options.blocked_city_pairs:
        return False
    return True


def make_bargain_profile(
    options: RoutePlanOptions,
    *,
    city: str | None = None,
    disabled: bool = False,
) -> BargainProfile:
    bargain_percent = options.bargain_percent
    raise_percent = options.raise_percent
    if city:
        bargain_percent = int((options.bargain_percent_by_city or {}).get(city, bargain_percent) or 0)
        raise_percent = int((options.raise_percent_by_city or {}).get(city, raise_percent) or 0)
    return BargainProfile(
        bargain_percent=bargain_percent,
        raise_percent=raise_percent,
        bargain_fatigue=options.bargain_fatigue,
        raise_fatigue=options.raise_fatigue,
        disabled=disabled,
    )


def should_enable_fixed_haggle(options: RoutePlanOptions, city: str) -> bool:
    profile = make_bargain_profile(options, city=city)
    if profile.bargain_percent <= 0 and profile.raise_percent <= 0:
        return False
    return int((options.haggle_by_city or {}).get(city, 0) or 0) > 0


def bargain_profiles_for_city(options: RoutePlanOptions, city: str) -> list[tuple[str, BargainProfile]]:
    no_haggle = ("no_haggle", make_bargain_profile(options, city=city, disabled=True))
    full_haggle = ("full_haggle", make_bargain_profile(options, city=city))
    if full_haggle[1].bargain_percent <= 0 and full_haggle[1].raise_percent <= 0:
        return [no_haggle]
    if options.auto_haggle:
        return [no_haggle, full_haggle]
    if should_enable_fixed_haggle(options, city):
        return [("fixed_haggle", make_bargain_profile(options, city=city))]
    return [no_haggle]


def calculate_columba_price_items(
    market: MarketData,
    trade_data: dict[str, Any],
    from_city: str,
    to_city: str,
    options: RoutePlanOptions,
    bargain: BargainProfile,
) -> list[dict[str, Any]]:
    roles = get_trade_roles(trade_data, options)
    events_config = get_events_config(trade_data, options)
    product_unlock_status = get_product_unlock_status(trade_data, options)
    buy_prestige = get_prestige_config(trade_data, from_city, options)
    sell_prestige = get_prestige_config(trade_data, to_city, options)
    from_city_master = get_city_master(trade_data, from_city)
    to_city_master = get_city_master(trade_data, to_city)
    buy_resonance_tax_cut = get_resonance_skill_tax_cut_percent(trade_data, roles, from_city)
    sell_resonance_tax_cut = get_resonance_skill_tax_cut_percent(trade_data, roles, to_city)
    items: list[dict[str, Any]] = []

    for product in get_trade_products(trade_data):
        product_name = product.get("name")
        if not product_name or product.get("type") == "Craft":
            continue
        if options.allowed_goods and product_name not in options.allowed_goods:
            continue
        if options.blocked_goods and product_name in options.blocked_goods:
            continue
        if not product_unlocked(product_name, from_city, product_unlock_status, options):
            continue
        static_buy_price = (product.get("buyPrices") or {}).get(from_city)
        static_buy_lot = (product.get("buyLot") or {}).get(from_city)
        if not static_buy_price or not static_buy_lot:
            continue
        if (product.get("buyPrices") or {}).get(to_city):
            continue

        buy_price = get_price((market.buy_prices or {}).get(from_city, {}).get(product_name))
        sell_price = get_price(market.sell_prices.get(to_city, {}).get(product_name))
        if buy_price <= 0 or sell_price <= 0:
            continue

        if not bargain.disabled:
            buy_price *= 1 - bargain.bargain_percent / 100
            sell_price = js_round(sell_price * (1 + bargain.raise_percent / 100))

        buy_tax_rate = get_prestige_tax_rate(buy_prestige, from_city_master)
        buy_tax_rate += get_game_event_tax_variation(trade_data, product, from_city, events_config)
        buy_tax_rate += buy_resonance_tax_cut

        sell_tax_rate = get_prestige_tax_rate(sell_prestige, to_city_master)
        sell_tax_rate += sell_resonance_tax_cut

        rounded_buy_price = js_round(buy_price)
        rounded_sell_price = js_round(sell_price)
        single_cost = js_round(rounded_buy_price * (1 + buy_tax_rate))
        single_income = js_round(rounded_sell_price * (1 - sell_tax_rate))
        single_profit = rounded_sell_price - rounded_buy_price
        single_profit -= single_profit * sell_tax_rate
        single_profit -= rounded_buy_price * buy_tax_rate
        single_profit = js_round(single_profit)
        if single_profit < options.min_profit:
            continue

        buy_more_percent = get_resonance_skill_buy_more_percent(trade_data, roles, product, from_city)
        buy_more_percent += float(buy_prestige.get("extraBuy", 0)) * 100
        buy_more_percent += get_game_event_buy_more_percent(trade_data, product, from_city, events_config)
        buy_lot = js_round(float(static_buy_lot) * (100 + buy_more_percent) / 100)
        if buy_lot <= 0:
            continue

        items.append(
            {
                "name": product_name,
                "buy_price": buy_price,
                "sell_price": sell_price,
                "single_cost": single_cost,
                "single_income": single_income,
                "single_profit": single_profit,
                "buy_lot": buy_lot,
            }
        )
    return sorted(items, key=lambda item: item["single_profit"], reverse=True)


def calculate_columba_combinations(
    market: MarketData,
    trade_data: dict[str, Any],
    from_city: str,
    to_city: str,
    options: RoutePlanOptions,
    bargain: BargainProfile,
    max_restock: int,
) -> dict[int, dict[str, Any]]:
    price_items = calculate_columba_price_items(market, trade_data, from_city, to_city, options, bargain)
    if not price_items:
        return {}

    roles = get_trade_roles(trade_data, options)
    base_fatigue, fatigue_estimated = route_tired(market, from_city, to_city, roles)
    if base_fatigue <= 0:
        return {}

    stats_by_restock: dict[int, dict[str, Any]] = {}
    max_lot = get_max_lot(trade_data, options)
    for restock in range(max(0, max_restock) + 1):
        used_lot = 0
        combinations = []
        for item in price_items:
            if used_lot >= max_lot:
                break
            available_lot = item["buy_lot"] * (restock + 1)
            buy_lot = min(max_lot - used_lot, available_lot)
            if buy_lot <= 0:
                continue
            used_lot += buy_lot
            combinations.append(
                {
                    "name": item["name"],
                    "availableLot": available_lot,
                    "buyLot": buy_lot,
                    "buyPrice": js_round(item["buy_price"]),
                    "sellPrice": js_round(item["sell_price"]),
                    "singleCost": int(item.get("single_cost", 0)),
                    "singleIncome": int(item.get("single_income", 0)),
                    "cost": int(item.get("single_cost", 0)) * buy_lot,
                    "income": int(item.get("single_income", 0)) * buy_lot,
                    "singleProfit": item["single_profit"],
                    "profit": item["single_profit"] * buy_lot,
                }
            )
        if not combinations:
            continue

        total_profit = int(sum(item["profit"] for item in combinations))
        total_cost = int(sum(item.get("cost", 0) for item in combinations))
        total_income = int(sum(item.get("income", 0) for item in combinations))
        fatigue = base_fatigue
        if not bargain.disabled:
            fatigue += bargain.bargain_fatigue + bargain.raise_fatigue
        last_not_wasting_restock = restock
        wasting_restock = restock > 0 and total_profit == stats_by_restock.get(restock - 1, {}).get("profit")
        if wasting_restock:
            previous = stats_by_restock[restock - 1]
            if previous.get("lastNotWastingRestock") == restock - 1:
                last_not_wasting_restock = restock - 1
            else:
                last_not_wasting_restock = previous.get("lastNotWastingRestock", restock - 1)

        stats_by_restock[restock] = {
            "combinations": combinations,
            "profit": total_profit,
            "cost": total_cost,
            "income": total_income,
            "restock": restock,
            "fatigue": fatigue,
            "fatigueEstimated": fatigue_estimated,
            "profitPerFatigue": js_round(total_profit / fatigue) if fatigue > 0 else 0,
            "generalProfitIndex": calculate_general_profit_index(total_profit, fatigue, restock),
            "usedLot": used_lot,
            "lastNotWastingRestock": last_not_wasting_restock,
            "bargainDisabled": bargain.disabled,
        }
    return stats_by_restock


def stats_to_route_model(
    stats: dict[str, Any],
    buy_city: str,
    sell_city: str,
    options: RoutePlanOptions,
) -> RouteModel:
    goods_data: dict[str, RouteModel.GoodsData] = {}
    buy_price_total = 0
    sell_price_total = 0
    cost_total = 0
    income_total = 0
    for item in stats["combinations"]:
        buy_lot = int(item["buyLot"])
        buy_price = int(item["buyPrice"])
        sell_price = int(item["sellPrice"])
        buy_price_total += buy_price * buy_lot
        sell_price_total += sell_price * buy_lot
        cost_total += int(item.get("cost", 0))
        income_total += int(item.get("income", 0))
        goods_data[item["name"]] = RouteModel.GoodsData(
            num=buy_lot,
            buy_price=buy_price,
            sell_price=sell_price,
            profit=int(item["profit"]),
        )

    if stats.get("bargainDisabled"):
        haggle_num = 0
    elif options.auto_haggle:
        haggle_num = PLANNED_HAGGLE_PERCENT
    else:
        haggle_num = int((options.haggle_by_city or {}).get(buy_city, 0))
    return RouteModel(
        buy_city_name=buy_city,
        sell_city_name=sell_city,
        haggle_num=haggle_num,
        goods_data=goods_data,
        buy_price=buy_price_total,
        sell_price=sell_price_total,
        cost=cost_total,
        income=income_total,
        city_tired=int(stats["fatigue"]),
        city_tired_estimated=bool(stats.get("fatigueEstimated", False)),
        tired_profit=int(stats["profitPerFatigue"]),
        book_profit=int(stats["generalProfitIndex"]),
        general_profit_index=int(stats["generalProfitIndex"]),
        book=int(stats["restock"]),
        num=int(stats["usedLot"]),
        profit=int(stats["profit"]),
        last_not_wasting_restock=int(stats["lastNotWastingRestock"]),
    )


def is_wulinyuan_pair(from_city: str, to_city: str) -> bool:
    return WULINYUAN_CITY_NAME in {normalize_city_name(from_city), normalize_city_name(to_city)}


def convert_base_price_to_wulinyuan_currency(price: int) -> int:
    if price <= 0:
        return 0
    return int(math.ceil(price / WULINYUAN_PRICE_DIVISOR_FROM_BASE))


def wulinyuan_currency_profit_metrics(
    jiaozi_income_base: int,
    jiaozi_cost_base: int,
    tiemeng_income: int,
    tiemeng_cost: int,
    total_fatigue: int,
    total_restock: int,
) -> dict[str, int] | None:
    jiaozi_income = convert_base_price_to_wulinyuan_currency(jiaozi_income_base)
    jiaozi_cost = convert_base_price_to_wulinyuan_currency(jiaozi_cost_base)
    jiaozi_profit = jiaozi_income - jiaozi_cost
    jiaozi_profit_for_index = jiaozi_income_base - jiaozi_cost_base
    tiemeng_profit = tiemeng_income - tiemeng_cost
    if jiaozi_profit <= 0 or jiaozi_profit_for_index <= 0 or tiemeng_profit <= 0:
        return None

    jiaozi_index = calculate_general_profit_index(jiaozi_profit_for_index, total_fatigue, total_restock)
    tiemeng_index = calculate_general_profit_index(tiemeng_profit, total_fatigue, total_restock)
    return {
        "jiaozi_profit": jiaozi_profit,
        "jiaozi_profit_score": jiaozi_profit_for_index,
        "tiemeng_profit": tiemeng_profit,
        "profit_score": jiaozi_profit_for_index + tiemeng_profit,
        "jiaozi_general_profit_index": jiaozi_index,
        "tiemeng_general_profit_index": tiemeng_index,
        "total_general_profit_index": jiaozi_index + tiemeng_index,
    }


def wulinyuan_stats_metrics(
    go: dict[str, Any],
    ret: dict[str, Any],
    from_city: str,
    to_city: str,
) -> dict[str, int] | None:
    from_city = normalize_city_name(from_city)
    to_city = normalize_city_name(to_city)
    if not is_wulinyuan_pair(from_city, to_city) or from_city == to_city:
        return None
    if to_city == WULINYUAN_CITY_NAME:
        jiaozi_route, tiemeng_route = go, ret
    elif from_city == WULINYUAN_CITY_NAME:
        jiaozi_route, tiemeng_route = ret, go
    else:
        return None

    total_fatigue = int(go.get("fatigue", 0)) + int(ret.get("fatigue", 0))
    total_restock = int(go.get("restock", 0)) + int(ret.get("restock", 0))
    return wulinyuan_currency_profit_metrics(
        int(jiaozi_route.get("income", 0)),
        int(tiemeng_route.get("cost", 0)),
        int(tiemeng_route.get("income", 0)),
        int(jiaozi_route.get("cost", 0)),
        total_fatigue,
        total_restock,
    )


def wulinyuan_route_metrics(first: RouteModel, second: RouteModel) -> dict[str, int] | None:
    if not is_wulinyuan_pair(first.buy_city_name, first.sell_city_name):
        return None
    if first.sell_city_name == WULINYUAN_CITY_NAME:
        jiaozi_route, tiemeng_route = first, second
    elif first.buy_city_name == WULINYUAN_CITY_NAME:
        jiaozi_route, tiemeng_route = second, first
    else:
        return None

    total_fatigue = int(first.city_tired) + int(second.city_tired)
    total_restock = int(first.book) + int(second.book)
    return wulinyuan_currency_profit_metrics(
        int(jiaozi_route.income),
        int(tiemeng_route.cost),
        int(tiemeng_route.income),
        int(jiaozi_route.cost),
        total_fatigue,
        total_restock,
    )


def make_routes_model(
    go: dict[str, Any],
    ret: dict[str, Any],
    from_city: str,
    to_city: str,
    options: RoutePlanOptions,
    label: str,
) -> RoutesModel | None:
    first = stats_to_route_model(go, from_city, to_city, options)
    second = stats_to_route_model(ret, to_city, from_city, options)
    total_fatigue = first.city_tired + second.city_tired
    total_restock = first.book + second.book
    special_metrics = wulinyuan_route_metrics(first, second)
    if is_wulinyuan_pair(from_city, to_city):
        if not special_metrics:
            return None
        total_profit = special_metrics["profit_score"]
        general_profit_index = special_metrics["total_general_profit_index"]
    else:
        total_profit = first.profit + second.profit
        general_profit_index = calculate_general_profit_index(total_profit, total_fatigue, total_restock)
    return RoutesModel(
        city_data=[first, second],
        profit=total_profit,
        city_tired=total_fatigue,
        tired_profit=js_round(total_profit / total_fatigue) if total_fatigue > 0 else 0,
        book=total_restock,
        general_profit_index=general_profit_index,
        jiaozi_profit=(special_metrics or {}).get("jiaozi_profit"),
        tiemeng_profit=(special_metrics or {}).get("tiemeng_profit"),
        jiaozi_general_profit_index=(special_metrics or {}).get("jiaozi_general_profit_index"),
        tiemeng_general_profit_index=(special_metrics or {}).get("tiemeng_general_profit_index"),
        strategy_label=label,
    )


def best_round_trip_for_restock(
    go_stats: dict[int, dict[str, Any]],
    return_stats: dict[int, dict[str, Any]],
    max_restock: int,
    from_city: str | None = None,
    to_city: str | None = None,
    mixed_currency_priority: MixedCurrencyPriority = "total",
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    best: tuple[dict[str, Any], dict[str, Any]] | None = None
    best_score: tuple[int, int, int, int] = (-1, -1, -1, -1)
    special_pair = bool(from_city and to_city and is_wulinyuan_pair(from_city, to_city))
    for go_restock in range(max_restock + 1):
        return_restock = max_restock - go_restock
        go = go_stats.get(go_restock)
        ret = return_stats.get(return_restock)
        if not go or not ret:
            continue
        if special_pair:
            metrics = wulinyuan_stats_metrics(go, ret, from_city or "", to_city or "")
            if not metrics:
                continue
            score = mixed_currency_score_tuple(metrics, mixed_currency_priority)
        else:
            profit = int(go["profit"]) + int(ret["profit"])
            score = (profit, 0, 0, 0)
        if score > best_score:
            best_score = score
            best = (go, ret)
    return best


def fixed_restock_for_city(options: RoutePlanOptions, city: str) -> int | None:
    if not options.max_book_by_city:
        return None
    if city not in options.max_book_by_city:
        return None
    return max(0, int(options.max_book_by_city[city] or 0))


def plan_columba_two_city_routes(
    market: MarketData,
    options: RoutePlanOptions,
    trade_data: dict[str, Any],
) -> list[RoutesModel]:
    max_restock = get_max_restock(trade_data, options)
    price_cities = set((market.buy_prices or {}).keys()) & set(market.sell_prices.keys())
    trade_cities = set(trade_data.get("cities") or [])
    cities = sorted(price_cities & trade_cities) if trade_cities else sorted(price_cities)
    if not cities:
        return []

    plans: list[RoutesModel] = []
    for from_city in cities:
        for to_city in cities:
            if not city_allowed(from_city, to_city, options):
                continue
            for go_label, go_bargain in bargain_profiles_for_city(options, from_city):
                go_stats = calculate_columba_combinations(
                    market,
                    trade_data,
                    from_city,
                    to_city,
                    options,
                    go_bargain,
                    max_restock,
                )
                if not go_stats:
                    continue
                for return_label, return_bargain in bargain_profiles_for_city(options, to_city):
                    label = f"{go_label}+{return_label}"
                    return_stats = calculate_columba_combinations(
                        market,
                        trade_data,
                        to_city,
                        from_city,
                        options,
                        return_bargain,
                        max_restock,
                    )
                    if not return_stats:
                        continue
                    fixed_go_restock = fixed_restock_for_city(options, from_city)
                    fixed_return_restock = fixed_restock_for_city(options, to_city)
                    if fixed_go_restock is not None and fixed_return_restock is not None:
                        go = go_stats.get(fixed_go_restock)
                        ret = return_stats.get(fixed_return_restock)
                        best = (go, ret) if go and ret else None
                    else:
                        best = best_round_trip_for_restock(
                            go_stats,
                            return_stats,
                            max_restock,
                            from_city,
                            to_city,
                            options.mixed_currency_priority,
                        )
                    if not best:
                        continue
                    route = make_routes_model(best[0], best[1], from_city, to_city, options, label)
                    if route:
                        plans.append(route)

    plans.sort(
        key=lambda route: routes_sort_key(
            route,
            options.strategy,
            options.mixed_currency_priority,
        ),
        reverse=True,
    )
    deduped: list[RoutesModel] = []
    seen: set[tuple[frozenset[str], int, int, str]] = set()
    for route in plans:
        first, second = route.city_data
        key = (
            frozenset((first.buy_city_name, second.buy_city_name)),
            route.profit,
            route.general_profit_index,
            route.strategy_label,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(route)
    return deduped


def plan_one_way_route(
    market: MarketData,
    buy_city: str,
    sell_city: str,
    options: RoutePlanOptions | None = None,
) -> RouteModel | None:
    options = options or RoutePlanOptions(use_columba_onegraph=False)
    if not city_allowed(buy_city, sell_city, options):
        return None

    buy_prices = (market.buy_prices or market.sell_prices).get(buy_city, {})
    sell_prices = market.sell_prices.get(sell_city, {})
    buy_goods = market.buy_goods.get(buy_city, {})
    goods: list[tuple[str, int, int, int, int]] = []
    for good_name, buy_price_info in buy_prices.items():
        if options.allowed_goods and good_name not in options.allowed_goods:
            continue
        if options.blocked_goods and good_name in options.blocked_goods:
            continue
        global_status = options.product_unlock_status or {}
        if not product_unlocked(good_name, buy_city, global_status, options):
            continue
        buy_price = int((buy_price_info or {}).get("price", 0))
        sell_price = int((sell_prices.get(good_name) or {}).get("price", 0))
        unit_profit = sell_price - buy_price
        if buy_price <= 0 or sell_price <= 0 or unit_profit < options.min_profit:
            continue
        good_info = buy_goods.get(good_name, {})
        num = max(1, int((good_info or {}).get("num", 1)))
        goods.append((good_name, num, buy_price, sell_price, unit_profit))

    if not goods:
        return None

    goods.sort(key=lambda item: item[4], reverse=True)
    remaining = max(1, int(options.max_goods_num or 625))
    goods_data: dict[str, RouteModel.GoodsData] = {}
    buy_price_total = 0
    sell_price_total = 0
    total_num = 0
    for good_name, num, buy_price, sell_price, unit_profit in goods:
        if remaining <= 0:
            break
        take_num = min(num, remaining)
        remaining -= take_num
        total_num += take_num
        buy_price_total += take_num * buy_price
        sell_price_total += take_num * sell_price
        goods_data[good_name] = RouteModel.GoodsData(
            num=take_num,
            buy_price=buy_price,
            sell_price=sell_price,
            profit=take_num * unit_profit,
        )

    if not goods_data:
        return None

    tired, tired_estimated = route_tired(market, buy_city, sell_city)
    profit = sell_price_total - buy_price_total
    book = (options.max_book_by_city or {}).get(buy_city, int(options.max_restock or 0))
    haggle_num = (
        PLANNED_HAGGLE_PERCENT
        if options.auto_haggle
        else int((options.haggle_by_city or {}).get(buy_city, 0))
    )
    general_profit_index = calculate_general_profit_index(profit, tired, book)
    return RouteModel(
        buy_city_name=buy_city,
        sell_city_name=sell_city,
        haggle_num=haggle_num,
        goods_data=goods_data,
        buy_price=buy_price_total,
        sell_price=sell_price_total,
        cost=buy_price_total,
        income=sell_price_total,
        city_tired=tired,
        city_tired_estimated=tired_estimated,
        tired_profit=int(profit / max(tired, 1)),
        book_profit=general_profit_index,
        general_profit_index=general_profit_index,
        profit=profit,
        book=book,
        num=total_num,
    )


def iter_one_way_routes(
    market: MarketData,
    options: RoutePlanOptions | None = None,
) -> Iterable[RouteModel]:
    cities = sorted(set((market.buy_prices or market.sell_prices).keys()) & set(market.sell_prices.keys()))
    for buy_city in cities:
        for sell_city in cities:
            route = plan_one_way_route(market, buy_city, sell_city, options)
            if route:
                yield route


def plan_two_city_routes(
    market: MarketData,
    options: RoutePlanOptions | None = None,
) -> list[RoutesModel]:
    options = options or RoutePlanOptions()
    if options.use_columba_onegraph:
        trade_data = load_columba_trade_data()
        if trade_data.get("products"):
            plans = plan_columba_two_city_routes(market, options, trade_data)
            if plans:
                return plans

    plans: list[RoutesModel] = []
    cities = sorted(set((market.buy_prices or market.sell_prices).keys()) & set(market.sell_prices.keys()))
    for buy_city in cities:
        for sell_city in cities:
            first = plan_one_way_route(market, buy_city, sell_city, options)
            second = plan_one_way_route(market, sell_city, buy_city, options)
            if first and second:
                profit = first.profit + second.profit
                tired = first.city_tired + second.city_tired
                book = first.book + second.book
                plans.append(
                    RoutesModel(
                        city_data=[first, second],
                        profit=profit,
                        city_tired=tired,
                        tired_profit=int(profit / max(tired, 1)),
                        book=book,
                        general_profit_index=calculate_general_profit_index(profit, tired, book),
                        strategy_label="legacy",
                    )
                )

    plans.sort(
        key=lambda route: routes_sort_key(
            route,
            options.strategy,
            options.mixed_currency_priority,
        ),
        reverse=True,
    )
    return plans


def summarize_routes(routes: RoutesModel, strategy: RouteStrategy = "general_profit_index") -> dict[str, Any]:
    legs = []
    for route in routes.city_data:
        legs.append(
            {
                "buy_city": route.buy_city_name,
                "sell_city": route.sell_city_name,
                "profit": route.profit,
                "cost": route.cost,
                "income": route.income,
                "tired": route.city_tired,
                "tired_estimated": route.city_tired_estimated,
                "tired_profit": route.tired_profit,
                "restock": route.book,
                "haggle_num": route.haggle_num,
                "uses_haggle": route.haggle_num > 0,
                "general_profit_index": route.general_profit_index,
                "last_not_wasting_restock": route.last_not_wasting_restock,
                "score": route_score(route, strategy),
                "goods": list(route.goods_data.keys()),
                "goods_detail": [
                    {
                        "name": name,
                        "num": data.num,
                        "buy_price": data.buy_price,
                        "sell_price": data.sell_price,
                        "profit": data.profit,
                    }
                    for name, data in route.goods_data.items()
                ],
            }
        )
    profit = routes.profit or sum(route.profit for route in routes.city_data)
    tired = routes.city_tired or sum(route.city_tired for route in routes.city_data)
    restock = routes.book if routes.book >= 0 else sum(route.book for route in routes.city_data)
    general_profit_index = routes.general_profit_index or calculate_general_profit_index(profit, tired, restock)
    is_wulinyuan = any(
        WULINYUAN_CITY_NAME in {route.buy_city_name, route.sell_city_name}
        for route in routes.city_data
    )
    return {
        "strategy": strategy,
        "mode": routes.strategy_label,
        "score": routes_score(routes, strategy),
        "profit": profit,
        "total_profit": None if is_wulinyuan else profit,
        "mixed_currency_profit": is_wulinyuan,
        "tired": tired,
        "restock": restock,
        "profit_per_fatigue": routes.tired_profit or int(profit / max(tired, 1)),
        "general_profit_index": general_profit_index,
        "reference_profit": general_profit_index,
        "reference_profit_label": "总和综合参考利润" if is_wulinyuan else "综合参考利润",
        "jiaozi_profit": routes.jiaozi_profit,
        "tiemeng_profit": routes.tiemeng_profit,
        "jiaozi_general_profit_index": routes.jiaozi_general_profit_index,
        "tiemeng_general_profit_index": routes.tiemeng_general_profit_index,
        "legs": legs,
    }

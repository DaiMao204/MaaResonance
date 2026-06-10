from __future__ import annotations

import copy
import calendar
import json
import math
import os
import re
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import date
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition
from maa.context import Context


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from maa_resonance.logic.profile_parser import classify_city_unlock_probe
from maa_resonance.logic.profile_parser import clean_text
from maa_resonance.logic.profile_parser import crew_page_signature
from maa_resonance.logic.profile_parser import crew_sort_arrow_down
from maa_resonance.logic.profile_parser import crew_sort_entry
from maa_resonance.logic.profile_parser import crew_sort_tap_point
from maa_resonance.logic.profile_parser import crew_warehouse_readiness
from maa_resonance.logic.profile_parser import load_city_names
from maa_resonance.logic.profile_parser import load_role_names
from maa_resonance.logic.profile_parser import parse_account_uid
from maa_resonance.logic.profile_parser import parse_cargo_capacity
from maa_resonance.logic.profile_parser import parse_city_prestige_values
from maa_resonance.logic.profile_parser import parse_city_prestige_values_from_entries
from maa_resonance.logic.profile_parser import parse_role_badges_from_image
from maa_resonance.logic.profile_parser import parse_role_resonance_from_entries
from maa_resonance.logic.profile_parser import parse_role_resonance_texts
from maa_resonance.logic.profile_parser import planner_role_resonance_level
from maa_resonance.logic.profile_parser import normalize_role_resonance_level
from maa_resonance.logic.profile_parser import prestige_values_to_levels
from maa_resonance.logic.profile_parser import resolve_resonance_votes
from maa_resonance.logic.profile_parser import save_role_badge_debug_crops
from maa_resonance.logic.profile_parser import visible_role_names_from_entries
from maa_resonance.logic.fatigue import huashi_daily_remaining
from maa_resonance.logic.fatigue import huashi_exhausted_seen
from maa_resonance.logic.fatigue import huashi_notice_from_texts
from maa_resonance.logic.fatigue import medicine_inventory_count
from maa_resonance.logic.fatigue import medicine_no_inventory_seen
from maa_resonance.logic.fatigue import strength_status_from_texts
from maa_resonance.logic.manual_trade import calculate_auto_two_city_trade
from maa_resonance.logic.manual_trade import calculate_manual_two_city_trade
from maa_resonance.logic.manual_trade import save_manual_two_city_result
from maa_resonance.logic.planner import COLUMBA_LOCAL_MARKET_DATA_PATH
from maa_resonance.logic.planner import COLUMBA_TRADE_DATA_PATH
from maa_resonance.logic.planner import load_default_tired_data
from maa_resonance.logic.planner import load_station_world_coords
from maa_resonance.logic.planner import normalize_city_name
from maa_resonance.logic.trade_parser import match_trade_good
from maa_resonance.logic.trade_parser import trade_good_row_texts
from maa_resonance.logic.trade_parser import trade_list_page_signature
from maa_resonance.logic.trade_parser import trade_list_text_signature
from maa_resonance.logic.trade_parser import visible_product_unlock_status
from maa_resonance.logic.trade_parser import visible_product_unlock_status_from_texts
from maa_resonance.logic.travel_parser import travel_status_from_texts
from utils.map_probe import destination_map_coordinate_probe
from utils.map_probe import destination_map_vicinity_probe


TASK_ENTRY = "ReadAccountPrestige"
CITY_UNLOCK_TASK_ENTRY = "ReadAccountCityUnlock"
ROLE_RESONANCE_TASK_ENTRY = "ReadAccountRoleResonance"
CARGO_TASK_ENTRY = "ReadAccountCargoCapacity"
ACCOUNT_PROFILE_TASK_ENTRY = "ReadAccountProfile"
LAUNCH_GAME_TASK_ENTRY = "LaunchGame"
MANUAL_TWO_CITY_TASK_ENTRY = "ManualTwoCityBusiness"
AUTO_TWO_CITY_TASK_ENTRY = "AutoTwoCityBusiness"
AUTO_TWO_CITY_EXCLUDE_OPTION = "AutoTwoCityExcludeCities"
MANUAL_TWO_CITY_RUN_MODE_ONE_ROUND = "one_round"
MANUAL_TWO_CITY_RUN_MODE_UNTIL_FATIGUE_EXHAUSTED = "until_fatigue_exhausted"
MANUAL_TWO_CITY_ACCOUNT_READ_SMART = "smart"
MANUAL_TWO_CITY_ACCOUNT_READ_FULL = "full"
MANUAL_TWO_CITY_ACCOUNT_READ_NONE = "none"
MANUAL_TWO_CITY_SMART_SCAN_DAILY = "daily"
MANUAL_TWO_CITY_SMART_SCAN_EVERY_3_DAYS = "every_3_days"
MANUAL_TWO_CITY_SMART_SCAN_WEEKLY = "weekly"
MANUAL_TWO_CITY_SMART_SCAN_MONTHLY = "monthly"
MANUAL_TWO_CITY_SMART_SCAN_INTERVAL_DAYS = {
    MANUAL_TWO_CITY_SMART_SCAN_DAILY: 1,
    MANUAL_TWO_CITY_SMART_SCAN_EVERY_3_DAYS: 3,
    MANUAL_TWO_CITY_SMART_SCAN_WEEKLY: 7,
    MANUAL_TWO_CITY_SMART_SCAN_MONTHLY: 30,
}
MANUAL_TWO_CITY_SMART_SCAN_INTERVAL_LABELS = {
    MANUAL_TWO_CITY_SMART_SCAN_DAILY: "每天",
    MANUAL_TWO_CITY_SMART_SCAN_EVERY_3_DAYS: "每 3 天",
    MANUAL_TWO_CITY_SMART_SCAN_WEEKLY: "每周",
    MANUAL_TWO_CITY_SMART_SCAN_MONTHLY: "每月",
}
MANUAL_TWO_CITY_TERMINAL_ONE_ROUND_COMPLETE = "one_round_complete"
MANUAL_TWO_CITY_TERMINAL_FATIGUE_EXHAUSTED = "fatigue_exhausted"
MANUAL_TWO_CITY_TERMINAL_FAILED = "failed"
MANUAL_TWO_CITY_RECOVERY_DEFAULT_MAX_ATTEMPTS = 2
MANUAL_TWO_CITY_RECOVERY_TARGET_LABELS = {
    "current_city": "当前城市",
    "trade_page": "交易所",
    "buy_page": "买入页",
    "sell_page": "卖出页",
}
MANUAL_TWO_CITY_FATIGUE_SAFETY_BUFFER = 50
BUY_BOOK_MAX_PER_BATCH = 10
BUY_BOOK_TOOL_TARGET = (1082, 104)
BUY_BOOK_MENU_TARGET = (1082, 162)
BUY_BOOK_INCREMENT_TARGET = (827, 387)
BUY_BOOK_CONFIRM_TARGET = (966, 537)
BUY_HAGGLE_BUTTON_TARGET = (1177, 461)
BUY_BOOK_MENU_USE_BUTTON_X = 922
BUY_BOOK_MENU_FALLBACK_TARGETS = ((1082, 162), (1082, 206), (1050, 162))
BUY_BOOK_TOOL_ROI = [980, 70, 180, 65]
BUY_BOOK_MENU_ROI = [880, 90, 330, 270]
BUY_BOOK_MENU_PANEL_ROI = [560, 60, 480, 660]
BUY_BOOK_POPUP_ROI = [300, 150, 720, 440]
BUY_BOOK_CONFIRM_ROI = [880, 500, 200, 90]
BUY_HAGGLE_BUTTON_ROI = [1080, 405, 190, 120]
BUY_HAGGLE_PERCENT_ROI = [988, 450, 54, 25]
BUY_CART_SELECTED_ROI = [860, 80, 400, 90]
BUY_GOODS_LIST_ROI = [500, 105, 430, 585]
BUY_PAGE_READY_TEXTS = ["预计买入", "全部买入", "全部取消"]
BUY_PAGE_CARGO_LOAD_ROI = [880, 360, 390, 85]
BUY_PAGE_CARGO_LOAD_PROBE_ROI = [1070, 345, 210, 120]
POST_BUY_CARGO_VERIFY_PLANNED_RATIO = 0.95
POST_BUY_CARGO_VERIFY_PASS_RATIO = 0.98
TRADE_SWITCH_TO_SELL_ROI = [0, 600, 430, 100]
TRADE_SWITCH_TO_SELL_TARGET = (336, 669)
TRADE_SWITCH_TO_BUY_ROI = [0, 600, 430, 100]
TRADE_SWITCH_TO_BUY_TARGET = (116, 669)
TRADE_STRENGTH_ENTRY_TARGET = (974, 32)
TRADE_STRENGTH_STATUS_ROI = [820, 0, 300, 65]
TRADE_STRENGTH_STATUS_TEXT = r"\d+\s*/\s*\d+"
RECOVERY_PAGE_BACK_TARGET = (83, 36)
PRE_BUY_CLEANUP_WARN_RATIO = 0.10
PRE_BUY_CLEANUP_RAISE_RATIO = 0.50
PRE_BUY_CLEANUP_RAISE_PERCENT = 20
PRE_BUY_SKIP_BUY_FULL_RATIO = 0.90
SELL_CART_SELECTED_ROI = [860, 80, 400, 90]
SELL_CONFIRM_BUTTON_ROI = [880, 585, 360, 115]
SELL_CONFIRM_BUTTON_TARGET = (1056, 647)
SELL_PAGE_READY_TEXTS = ["预计卖出", "全部卖出", "全部出售", "全部取消"]
SELL_ALL_TEXTS = ["全部卖出", "全部出售"]
SELL_CONFIRM_TEXTS = ["确认卖出", "确认出售", "卖出", "出售"]
SELL_REPORT_TEXTS = ["卖出结算报告", "出售结算报告", "触碰空白区域退出"]
SETTLEMENT_REPORT_TEXTS = ["买入结算报告", "卖出结算报告", "出售结算报告", "触碰空白区域退出", "SETTLEMENT REPORT"]
SETTLEMENT_REPORT_CLOSE_TARGETS = ((640, 680), (584, 680), (1080, 680), (640, 630))
TRADE_CONFIRM_POPUP_TEXTS = ["确认", "确定"]
TRADE_CONFIRM_POPUP_ROI = [820, 420, 420, 230]
MARKET_CHANGE_TEXTS = ["行情变动", "行情变化", "价格变动", "价格变化", "价格已变化", "市场行情"]
MARKET_CHANGE_CONFIRM_TEXTS = ["确认", "确定"]
MARKET_CHANGE_CONFIRM_ROI = [860, 430, 260, 230]
TRADE_PRODUCT_LOCK_TEXTS = ["需要解锁", "未解锁", "本城声望达到", "声望达到", "投资方案"]
TRADE_PRODUCT_LOCK_CHECK_ROI = [360, 95, 820, 520]
TRADE_PRODUCT_DETAIL_CLOSE_TARGET = (100, 100)
PRODUCT_STATUS_NORMAL = "normal"
PRODUCT_STATUS_LOCKED = "locked"
PRODUCT_STATUS_MISSING = "missing"
PRODUCT_STATUS_NEVER_SCANNED = "never_scanned"
PRODUCT_STATUSES = {
    PRODUCT_STATUS_NORMAL,
    PRODUCT_STATUS_LOCKED,
    PRODUCT_STATUS_MISSING,
    PRODUCT_STATUS_NEVER_SCANNED,
}
PRODUCT_STATUS_ALIASES = {
    "true": PRODUCT_STATUS_NORMAL,
    "1": PRODUCT_STATUS_NORMAL,
    "yes": PRODUCT_STATUS_NORMAL,
    "unlocked": PRODUCT_STATUS_NORMAL,
    "normal": PRODUCT_STATUS_NORMAL,
    "ok": PRODUCT_STATUS_NORMAL,
    "正常": PRODUCT_STATUS_NORMAL,
    "已解锁": PRODUCT_STATUS_NORMAL,
    "已出现": PRODUCT_STATUS_NORMAL,
    "false": PRODUCT_STATUS_LOCKED,
    "0": PRODUCT_STATUS_LOCKED,
    "no": PRODUCT_STATUS_LOCKED,
    "locked": PRODUCT_STATUS_LOCKED,
    "未解锁": PRODUCT_STATUS_LOCKED,
    "锁定": PRODUCT_STATUS_LOCKED,
    "missing": PRODUCT_STATUS_MISSING,
    "not_found": PRODUCT_STATUS_MISSING,
    "未扫描": PRODUCT_STATUS_MISSING,
    "没扫到": PRODUCT_STATUS_MISSING,
    "缺失": PRODUCT_STATUS_MISSING,
    "never_scanned": PRODUCT_STATUS_NEVER_SCANNED,
    "unknown": PRODUCT_STATUS_NEVER_SCANNED,
    "未扫描过": PRODUCT_STATUS_NEVER_SCANNED,
    "未知": PRODUCT_STATUS_NEVER_SCANNED,
}
PRODUCT_PLANNER_BLOCKED_STATUSES = {PRODUCT_STATUS_LOCKED, PRODUCT_STATUS_MISSING}
PRODUCT_SCAN_REQUIRED_STATUSES = {
    PRODUCT_STATUS_LOCKED,
    PRODUCT_STATUS_MISSING,
    PRODUCT_STATUS_NEVER_SCANNED,
}
PRODUCT_SCAN_MAX_PAGES = 8
BUY_BOOK_MENU_TEXTS = ["使用进货书", "使用进货采购书", "进货采购书", "进货采买书", "进货书", "采购书", "采买书"]
BUY_BOOK_POPUP_TEXTS = ["是否使用", "增加交易品库存", "进货采购书", "进货采买书", "进货书", "确认"]
BUY_HAGGLE_BUTTON_TEXTS = ["议价", "砍价", "降价", "抬价"]
BUY_HAGGLE_UNAVAILABLE_TEXTS = ["议价次数不足", "砍价次数不足", "降价次数不足", "抬价次数不足"]
BUY_HAGGLE_BOOK_POPUP_TEXTS = [
    "议价次数不足",
    "砍价次数不足",
    "抬价次数不足",
    "是否使用",
    "重新议价",
    "请求书",
    "议价书",
    "确认",
]
BUY_HAGGLE_BOOK_POPUP_ROI = [250, 220, 780, 360]
BUY_HAGGLE_BOOK_CONFIRM_ROI = [880, 500, 200, 90]
BUY_HAGGLE_BOOK_CONFIRM_TARGET = (966, 537)
FATIGUE_MEDICINE_RESOURCES = {
    "提神棒棒糖": {"restore": 60, "limit_key": "lollipop_use_limit"},
    "提神口香糖": {"restore": 100, "limit_key": "gum_use_limit"},
    "仙人掌提神跳糖": {"restore": 900, "limit_key": "cactus_candy_use_limit"},
}
FATIGUE_RECOVERY_RESOURCE_LABELS = {
    "drink": "喝酒",
    "bento": "便当",
    "medicine": "疲劳药",
    "huashi": "桦石",
}
FATIGUE_MEDICINE_POPUP_MAX_STEPS = 30
HUASHI_MAX_USE_LIMIT = 8
HUASHI_RESTORE_DEFAULT = 150
MXU_WEB_API_DEFAULT_PORT = 12701
MXU_WEB_API_MAX_PORT_ATTEMPTS = 10
_MXU_CONFIG_API_BASE_URL: str | None = None
FATIGUE_DRINK_MAX_ATTEMPTS = 6
FATIGUE_DRINK_ACTION_TEXTS = ["前往休息区", "喝一杯", "喝酒", "饮酒", "小酌"]
FATIGUE_DRINK_SELECT_TEXTS = ["银枝气泡水", "本次免费", "喝一杯吗"]
FATIGUE_DRINK_REST_AREA_TEXTS = ["休息区", "喝一杯", "所有城市合计每日提供"]
FATIGUE_DRINK_CONFIRM_TEXTS = ["确认", "确定", "喝一杯", "喝酒", "饮用", "再喝一杯", "再来一杯"]
FATIGUE_DRINK_REPEAT_TEXTS = ["再喝一杯", "再来一杯"]
FATIGUE_DRINK_REPEAT_CONFIRM_TEXTS = ["还没有到失效时间", "还没到失效时间", "还要再喝一杯吗", "还要再喝", "当前生效", "当天不再提醒"]
FATIGUE_DRINK_SKIP_TEXTS = ["SKIP", "Skip", "skip", "跳过"]
FATIGUE_DRINK_SKIP_CONFIRM_TEXTS = ["是否跳过该段演出", "是否跳过演出", "跳过该段演出"]
FATIGUE_DRINK_COST_CONFIRM_TEXTS = ["使用银枝", "消耗银枝", "是否使用银枝", "使用银枝气泡水", "消耗银枝气泡水"]
FATIGUE_DRINK_RESULT_TEXTS = ["疲劳值已消除", "疲劳已消除", "已消除", "当前生效", "剩余30分钟", "心意"]
FATIGUE_DRINK_UNAVAILABLE_TEXTS = [
    "不在范围内",
    "今日已饮",
    "已经喝",
    "次数不足",
    "无法饮酒",
    "不可饮酒",
    "次数已用完",
    "没有可用次数",
    "今日次数已用完",
    "每日次数已用完",
]
FATIGUE_NO_REMIND_TEXTS = [
    "不再提示",
    "不再提醒",
    "不再弹出",
    "下次跳过",
    "下次不提示",
    "下次不再",
    "当天不再",
    "当日不再",
    "今日不再",
    "本日不再",
]
FATIGUE_STRENGTH_PAGE_TEXTS = ["FATIGUE", "疲劳值", "请选择恢复疲劳值方式", "前往便当柜"]
FATIGUE_BENTO_ENTRY_TEXTS = ["前往便当柜", "便当柜"]
FATIGUE_BENTO_ENTRY_ROI = [900, 480, 360, 200]
FATIGUE_BENTO_PAGE_TEXTS = ["BENTOCABINET", "BOXMEAL", "工作餐", "全部使用", "爱心便当"]
FATIGUE_BENTO_ALL_TEXTS = ["全部使用", "全都使用", "全部使"]
FATIGUE_BENTO_ALL_ROI = [780, 360, 420, 130]
FATIGUE_BENTO_SHORTAGE_TEXTS = ["便当余量不足", "余量不足", "数量不足", "不足"]
FATIGUE_BENTO_CONFIRM_TEXTS = ["补充", "确认", "确定"]
FATIGUE_BENTO_SUCCESS_TEXTS = ["疲劳值已消除", "已消除", "恢复成功", "疲劳已恢复"]
FATIGUE_BENTO_CONFIRM_PROMPT_TEXTS = ["确定", "确认", "完成", "关闭", "知道了"]
FATIGUE_MEDICINE_POPUP_TEXTS = ["请选择补充次数", "当前疲劳值", "补充后疲劳值", "持有数量", "拥有数量", "补充"]
FATIGUE_MEDICINE_POPUP_ROI = [430, 90, 720, 560]
FATIGUE_MEDICINE_MAX_TEXTS = ["最多", "最大", "MAX", "Max", "max"]
FATIGUE_MEDICINE_PLUS_TARGET = (827, 479)
FATIGUE_MEDICINE_MAX_TARGET = (892, 479)
FATIGUE_MEDICINE_CONFIRM_TARGET = (1000, 585)
FATIGUE_MEDICINE_CANCEL_TARGET = (320, 585)
FATIGUE_MEDICINE_CARD_ROIS = {
    "提神棒棒糖": [540, 190, 230, 220],
    "提神口香糖": [780, 190, 250, 220],
    "仙人掌提神跳糖": [540, 450, 240, 210],
}
FATIGUE_MEDICINE_CARD_UNAVAILABLE_TEXTS = ["获取途径", "不在范围内", "库存不足", "数量不足", "无库存", "没有可用"]
FATIGUE_MEDICINE_FALLBACK_TARGETS = {
    "提神棒棒糖": (660, 354),
    "提神口香糖": (900, 354),
    "仙人掌提神跳糖": (660, 613),
}
FATIGUE_HUASHI_ROI = [760, 420, 260, 235]
FATIGUE_HUASHI_FALLBACK_TARGET = (900, 613)
FATIGUE_HUASHI_SHOP_PROMPT_TEXTS = ["购买次数不足", "月度商会支援礼包", "商会支援礼包", "前往购买"]
FATIGUE_HUASHI_NOTICE_TEXTS = ["本次消耗", "桦石", "恢复", "疲劳"]
FATIGUE_HUASHI_CANCEL_TARGET = (345, 503)
FATIGUE_DRINK_INFO_ANCHOR_TEXTS = ["前往休息区", "REST AREA", "RESTAREA", "休息区"]
FATIGUE_DRINK_INFO_DISMISS_TARGET = (640, 650)
FATIGUE_DRINK_INFO_TEXTS = ["剩余次数", "剩余", "次数", "今日", "每日", "喝酒", "饮酒", r"\d+\s*/\s*\d+"]
FATIGUE_DRINK_INFO_COUNT_KEYWORDS = ["银枝气泡水", "气泡水", "免材料次数", "材料次数", "免费次数", "剩余次数", "休息区"]
FATIGUE_DRINK_INFO_RATIO_RE = re.compile(r"(\d{1,2})\s*[/／|｜丨\\lI]\s*(\d{1,2})")
FATIGUE_DRINK_SKIP_CONFIRM_CHECKBOX_TARGET = (562, 670)
FATIGUE_DRINK_SKIP_CONFIRM_BUTTON_TARGET = (963, 505)
FATIGUE_DRINK_REPEAT_CONFIRM_CHECKBOX_TARGET = (580, 672)
FATIGUE_DRINK_REPEAT_CONFIRM_BUTTON_TARGET = (963, 505)
MANUAL_TWO_CITY_TRAVEL_STALL_SECONDS = 75.0
MANUAL_TWO_CITY_TRAVEL_STALL_MIN_HITS = 8
MANUAL_TWO_CITY_TRAVEL_STALL_MAX_RESTARTS = 1
TRAVEL_ROUTE_EVENT_TEXTS = ["护卫队迎击", "敌方等级", "诱饵气球", "立即返航", "应对方式", "请选择"]
TRAVEL_HUD_TEXTS = ["目的地", "剩余行程", "巡航"]
FATIGUE_DRINK_OCR_EXPECTED = list(
    dict.fromkeys(
        FATIGUE_DRINK_ACTION_TEXTS
        + FATIGUE_DRINK_SELECT_TEXTS
        + FATIGUE_DRINK_REST_AREA_TEXTS
        + FATIGUE_DRINK_CONFIRM_TEXTS
        + FATIGUE_DRINK_SKIP_TEXTS
        + FATIGUE_DRINK_SKIP_CONFIRM_TEXTS
        + FATIGUE_DRINK_REPEAT_CONFIRM_TEXTS
        + FATIGUE_DRINK_COST_CONFIRM_TEXTS
        + FATIGUE_DRINK_RESULT_TEXTS
        + FATIGUE_DRINK_UNAVAILABLE_TEXTS
        + FATIGUE_NO_REMIND_TEXTS
        + FATIGUE_STRENGTH_PAGE_TEXTS
        + ["跳过演出"]
    )
)
CREW_SCROLL_STALE_LIMIT = 2
CREW_SCAN_PAGE_COUNT = 24
CITY_UNLOCK_TARGETS = (
    "7号自由港",
    "武林源",
    "阿妮塔战备工厂",
    "阿妮塔能源研究所",
    "阿妮塔发射中心",
    "汇流塔",
    "海角城",
    "远星大桥",
    "贡露城",
    "澄明数据中心",
    "修格里城",
    "铁盟哨站",
    "曼德矿场",
    "淘金乐园",
    "荒原站",
    "云岫桥基地",
    "栖羽站",
    "岚心城",
)
CITY_UNLOCK_STATUS_LABELS = {
    "available": "开放",
    "unavailable": "未开放",
    "unknown": "未知",
}

_PRESTIGE_STATE: dict[str, Any] = {}
_CITY_UNLOCK_STATE: dict[str, Any] = {}
_ROLE_RESONANCE_STATE: dict[str, Any] = {}
_CARGO_STATE: dict[str, Any] = {}
_MANUAL_TWO_CITY_STATE: dict[str, Any] = {}
_FATIGUE_RECOVERY_STATE: dict[str, Any] = {}
_STATE_RECOVERY_STATE: dict[str, Any] = {}
_FATIGUE_DRINK_LOG_TASK_ENTRY = MANUAL_TWO_CITY_TASK_ENTRY
_PROFILE_UID = ""
_STDOUT_LOG_TASK_HEADERS: set[str] = set()

_TASK_STDOUT_LABELS = {
    TASK_ENTRY: "读取账号配置",
    CITY_UNLOCK_TASK_ENTRY: "城市开放读取",
    ROLE_RESONANCE_TASK_ENTRY: "乘员共振读取",
    CARGO_TASK_ENTRY: "货仓大小读取",
    ACCOUNT_PROFILE_TASK_ENTRY: "账号配置读取",
    LAUNCH_GAME_TASK_ENTRY: "启动游戏",
    MANUAL_TWO_CITY_TASK_ENTRY: "手动双城跑商",
    AUTO_TWO_CITY_TASK_ENTRY: "自动双城跑商",
}


def _append_debug_payload(event: str, payload: dict[str, Any]) -> None:
    if event != "profile_city_unlock_move_to_city":
        return
    try:
        debug_dir = PROJECT_ROOT / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        record = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **payload}
        with (debug_dir / "city_unlock_move_debug.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str))
            handle.write("\n")
    except Exception:
        pass


def _json_payload(event: str, payload: dict[str, Any]) -> None:
    _append_debug_payload(event, payload)
    if _env_truthy("MAA_RESONANCE_DEBUG_STDOUT_JSON"):
        print(json.dumps({"event": event, **payload}, ensure_ascii=False, default=str), flush=True)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_truthy_default(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _stdout_user_log(task_entry: str, level: str, message: str) -> None:
    if os.environ.get("MAA_RESONANCE_LOG_STDOUT", "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    style = os.environ.get("MAA_RESONANCE_LOG_STDOUT_STYLE", "compact").strip().lower()
    if style == "full":
        print(f"[MaaResonance][{task_entry}][{level}] {message}", flush=True)
        return
    if style == "message":
        print(message, flush=True)
        return
    if task_entry not in _STDOUT_LOG_TASK_HEADERS:
        print(f"--- {_TASK_STDOUT_LABELS.get(task_entry, task_entry)} ---", flush=True)
        _STDOUT_LOG_TASK_HEADERS.add(task_entry)
    print(f"[{level}] {message}", flush=True)


def _task_dir(task_entry: str) -> Path:
    return PROJECT_ROOT / "config" / "tasks" / task_entry


def _task_log_jsonl_path(task_entry: str) -> Path:
    return _task_dir(task_entry) / "run_log.jsonl"


def _task_log_text_path(task_entry: str) -> Path:
    return _task_dir(task_entry) / "run_log.txt"


def _reset_user_log(task_entry: str) -> None:
    _STDOUT_LOG_TASK_HEADERS.discard(task_entry)
    log_dir = _task_dir(task_entry)
    log_dir.mkdir(parents=True, exist_ok=True)
    _task_log_jsonl_path(task_entry).write_text("", encoding="utf-8")
    _task_log_text_path(task_entry).write_text("", encoding="utf-8")


def _append_user_log(
    task_entry: str,
    message: str,
    *,
    run_id: str = "",
    level: str = "info",
    event: str = "task_log",
    data: dict[str, Any] | None = None,
) -> None:
    try:
        log_dir = _task_dir(task_entry)
        log_dir.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "event": event,
            "task_entry": task_entry,
            "message": message,
        }
        if run_id:
            record["run_id"] = run_id
        if data:
            record["data"] = data
        with _task_log_jsonl_path(task_entry).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str))
            handle.write("\n")
        with _task_log_text_path(task_entry).open("a", encoding="utf-8") as handle:
            handle.write(f"[{record['time']}] {message}\n")
        _stdout_user_log(task_entry, level, message)
    except Exception:
        pass


def _start_user_log(task_entry: str, run_id: str, message: str) -> None:
    _reset_user_log(task_entry)
    _append_user_log(task_entry, message, run_id=run_id, event="task_started")


@AgentServer.custom_action("launch_game_start")
class LaunchGameStartAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        run_id = f"launch-{int(time.time())}"
        _start_user_log(LAUNCH_GAME_TASK_ENTRY, run_id, "启动游戏：正在检查游戏是否已在前台运行。")
        _json_payload("launch_game_start", {"ok": True, "run_id": run_id})
        return True


@AgentServer.custom_action("launch_game_already_running")
class LaunchGameAlreadyRunningAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        source = str(params.get("source") or "unknown").strip()
        if source.startswith("travel"):
            message = "启动游戏：检测到游戏已在行车途中，跳过启动应用。"
        else:
            message = "启动游戏：检测到游戏已在运行，跳过启动应用，直接进入状态恢复。"
        _append_user_log(
            LAUNCH_GAME_TASK_ENTRY,
            message,
            event="launch_game_already_running",
            data={"source": source, "texts": _ocr_texts(argv)[:30]},
        )
        _json_payload("launch_game_already_running", {"ok": True, "source": source})
        return True


@AgentServer.custom_action("launch_game_start_app")
class LaunchGameStartAppAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        _append_user_log(
            LAUNCH_GAME_TASK_ENTRY,
            "启动游戏：未检测到现有游戏界面，正在打开应用。",
            event="launch_game_start_app",
        )
        _json_payload("launch_game_start_app", {"ok": True})
        return True


@AgentServer.custom_action("launch_game_complete")
class LaunchGameCompleteAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        _append_user_log(
            LAUNCH_GAME_TASK_ENTRY,
            "启动游戏完成：已确认游戏处于可识别运行状态。",
            event="launch_game_complete",
        )
        _json_payload("launch_game_complete", {"ok": True})
        return True


@AgentServer.custom_action("launch_game_failed")
class LaunchGameFailedAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        _append_user_log(
            LAUNCH_GAME_TASK_ENTRY,
            "启动游戏失败：未能在限定流程内到达主界面。",
            level="error",
            event="launch_game_failed",
        )
        _json_payload("launch_game_failed", {"ok": False})
        return False


@AgentServer.custom_action("state_recovery_travel_detected")
class StateRecoveryTravelDetectedAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        global _STATE_RECOVERY_STATE
        params = _argv_param(argv)
        kind = str(params.get("kind") or "unknown").strip()
        texts = _ocr_texts(argv)
        _STATE_RECOVERY_STATE["travel_detected"] = {
            "kind": kind,
            "texts": texts[:30],
            "time": time.time(),
        }
        _json_payload("state_recovery_travel_detected", {"ok": True, "kind": kind, "texts": texts[:30]})
        return True


@AgentServer.custom_action("account_profile_read_failed")
class AccountProfileReadFailedAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        travel_detected = _STATE_RECOVERY_STATE.pop("travel_detected", None)
        if travel_detected:
            message = "读取账号配置失败：当前处于行车途中或行车事件界面，无法从主界面开始读取。"
            data = {"reason": "travel_detected", **travel_detected}
        else:
            message = "读取账号配置失败：状态恢复未能回到主界面。"
            data = None
        _append_user_log(
            ACCOUNT_PROFILE_TASK_ENTRY,
            message,
            level="error",
            event="account_profile_read_failed",
            data=data,
        )
        _json_payload("account_profile_read_failed", {"ok": False, "travel_detected": bool(travel_detected)})
        return False


def _json_param_from_attr(argv: Any, attr_name: str) -> dict[str, Any]:
    raw = getattr(argv, attr_name, None)
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _argv_param(argv: CustomAction.RunArg) -> dict[str, Any]:
    return _json_param_from_attr(argv, "custom_action_param")


def _custom_recognition_param(argv: CustomRecognition.AnalyzeArg) -> dict[str, Any]:
    return _json_param_from_attr(argv, "custom_recognition_param")


def _box_xywh(box: Any) -> tuple[int, int, int, int] | None:
    if box is None:
        return None
    if isinstance(box, dict):
        try:
            return (
                int(box.get("x", box.get(0, 0)) or 0),
                int(box.get("y", box.get(1, 0)) or 0),
                int(box.get("w", box.get("width", box.get(2, 0))) or 0),
                int(box.get("h", box.get("height", box.get(3, 0))) or 0),
            )
        except (TypeError, ValueError):
            return None
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        try:
            return int(box[0]), int(box[1]), int(box[2]), int(box[3])
        except (TypeError, ValueError):
            return None
    try:
        return (
            int(getattr(box, "x")),
            int(getattr(box, "y")),
            int(getattr(box, "w")),
            int(getattr(box, "h")),
        )
    except (TypeError, ValueError, AttributeError):
        return None


def _collect_ocr_result_objects(detail: Any) -> list[Any]:
    if detail is None:
        return []
    results: list[Any] = []
    for attr in ("all_results", "filtered_results"):
        results.extend(getattr(detail, attr, None) or [])
    best = getattr(detail, "best_result", None)
    if best is not None:
        results.append(best)
    raw_sources = []
    if isinstance(detail, dict):
        raw_sources.extend([detail, detail.get("detail"), detail.get("raw_detail")])
    else:
        raw_sources.extend([getattr(detail, "detail", None), getattr(detail, "raw_detail", None)])
    for raw in raw_sources:
        if not isinstance(raw, dict):
            continue
        results.extend(raw.get("all") or [])
        results.extend(raw.get("filtered") or [])
        raw_best = raw.get("best")
        if raw_best:
            results.append(raw_best)
    return results


def _ocr_texts_from_detail(detail: Any) -> list[str]:
    texts: list[str] = []

    def visit(value: Any) -> None:
        if value is None:
            return
        text = getattr(value, "text", None)
        if text is None and isinstance(value, dict):
            text = value.get("text")
        if text is not None:
            normalized = str(text).strip()
            if normalized:
                texts.append(normalized)
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    for result in _collect_ocr_result_objects(detail):
        visit(result)
    return list(dict.fromkeys(texts))


def _ocr_texts(argv: CustomAction.RunArg) -> list[str]:
    return _ocr_texts_from_detail(getattr(argv, "reco_detail", None))


def _texts_contain_any(texts: list[str], expected: list[str]) -> bool:
    cleaned = [clean_text(text) for text in texts if str(text).strip()]
    return any(clean_text(item) and clean_text(item) in text for item in expected for text in cleaned)


def _ocr_entries_from_detail(detail: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int, int, int]] = set()

    def add_result(result: Any) -> None:
        text = getattr(result, "text", None)
        if text is None and isinstance(result, dict):
            text = result.get("text")
        if text is None:
            return
        box = getattr(result, "box", None)
        if box is None and isinstance(result, dict):
            box = result.get("box")
        position = result.get("position") if isinstance(result, dict) else None
        xywh = _box_xywh(box)
        if xywh is None and isinstance(position, list) and position:
            points = [
                (float(point[0] or 0), float(point[1] or 0))
                for point in position
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ]
            if points:
                xs = [point[0] for point in points]
                ys = [point[1] for point in points]
                xywh = (int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys)))
        if xywh is None:
            return
        x, y, w, h = xywh
        item = {
            "text": str(text),
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "center_x": x + w / 2,
            "center_y": y + h / 2,
        }
        key = (item["text"], x, y, w, h)
        if key not in seen:
            seen.add(key)
            entries.append(item)

    def visit(value: Any) -> None:
        if value is None:
            return
        if getattr(value, "text", None) is not None or (isinstance(value, dict) and "text" in value):
            add_result(value)
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    for result in _collect_ocr_result_objects(detail):
        visit(result)
    return entries


def _ocr_entries(argv: CustomAction.RunArg) -> list[dict[str, Any]]:
    return _ocr_entries_from_detail(getattr(argv, "reco_detail", None))


def _int_param(params: dict[str, Any], key: str, default: int, *, minimum: int | None = None) -> int:
    try:
        value = int(params.get(key) if params.get(key) not in (None, "") else default)
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        return max(minimum, value)
    return value


def _initial_state() -> dict[str, Any]:
    return {
        "ok": False,
        "task_entry": TASK_ENTRY,
        "uid": _current_profile_uid(),
        "profile_read_run_id": time.strftime("%Y%m%d_%H%M%S"),
        "completed_parts": [],
        "prestige_by_city": {},
        "prestige_value_by_city": {},
        "prestige_texts": [],
        "prestige_pages": [],
    }


def _state_for_page(page_index: int) -> dict[str, Any]:
    global _PRESTIGE_STATE
    if page_index <= 1 or not _PRESTIGE_STATE:
        _PRESTIGE_STATE = _initial_state()
        _start_user_log(
            TASK_ENTRY,
            str(_PRESTIGE_STATE["profile_read_run_id"]),
            "开始读取账号配置-城市声望",
        )
    return _PRESTIGE_STATE


def _initial_cargo_state() -> dict[str, Any]:
    return {
        "ok": False,
        "task_entry": CARGO_TASK_ENTRY,
        "uid": _current_profile_uid(),
        "profile_read_run_id": time.strftime("%Y%m%d_%H%M%S"),
        "completed_parts": [],
        "cargo_capacity": None,
        "cargo_texts": [],
    }


def _cargo_state(*, reset: bool = False) -> dict[str, Any]:
    global _CARGO_STATE
    if reset or not _CARGO_STATE:
        _CARGO_STATE = _initial_cargo_state()
        _start_user_log(
            CARGO_TASK_ENTRY,
            str(_CARGO_STATE["profile_read_run_id"]),
            "开始读取账号配置-货仓大小",
        )
    return _CARGO_STATE


def _record_profile_uid(texts: list[str]) -> dict[str, Any]:
    global _PROFILE_UID
    uid = parse_account_uid(texts)
    if uid:
        _PROFILE_UID = uid
    state = {
        "ok": bool(uid),
        "task_entry": ACCOUNT_PROFILE_TASK_ENTRY,
        "uid": _current_profile_uid(),
        "uid_texts": texts[:20],
        "profile_read_run_id": time.strftime("%Y%m%d_%H%M%S"),
        "completed_parts": ["read_uid"],
    }
    path = _save_profile_result(copy.deepcopy(state), task_entry=ACCOUNT_PROFILE_TASK_ENTRY)
    level = "info" if uid else "warning"
    _append_user_log(
        ACCOUNT_PROFILE_TASK_ENTRY,
        f"账号 UID 识别{'完成' if uid else '失败'}：{_current_profile_uid()}",
        run_id=str(state["profile_read_run_id"]),
        level=level,
        event="account_profile_uid_read",
        data={"uid": _current_profile_uid(), "config_path": path, "texts": texts[:8]},
    )
    return {"ok": bool(uid), "uid": _current_profile_uid(), "config_path": path, "texts": texts[:12]}


def _record_cargo_capacity(texts: list[str]) -> dict[str, Any]:
    state = _cargo_state(reset=not _CARGO_STATE)
    run_id = str(state.get("profile_read_run_id") or "")
    capacity = parse_cargo_capacity(texts)
    state["uid"] = _current_profile_uid()
    state["cargo_capacity"] = capacity
    state["cargo_texts"] = texts[:20]
    state["ok"] = capacity is not None
    completed = state.setdefault("completed_parts", [])
    if "read_cargo" not in completed:
        completed.append("read_cargo")
    config_path = _save_profile_result(copy.deepcopy(state), task_entry=CARGO_TASK_ENTRY)
    level = "info" if capacity is not None else "warning"
    _append_user_log(
        CARGO_TASK_ENTRY,
        f"货仓大小读取{'完成' if capacity is not None else '失败'}：{capacity if capacity is not None else '未识别'}",
        run_id=run_id,
        level=level,
        event="cargo_capacity_read",
        data={"cargo_capacity": capacity, "config_path": config_path, "texts": texts[:12]},
    )
    return {
        "ok": capacity is not None,
        "cargo_capacity": capacity,
        "config_path": config_path,
        "texts": texts[:12],
    }


def _task_config_path(task_entry: str) -> Path:
    return _task_dir(task_entry) / "account_profile.json"


def _safe_account_uid(uid: Any) -> str:
    text = str(uid or "").strip()
    match = re.search(r"\d{4,}", text)
    return match.group(0) if match else "unknown"


def _account_config_path(uid: Any) -> Path:
    return PROJECT_ROOT / "config" / "accounts" / f"{_safe_account_uid(uid)}.json"


def _is_real_account_config_path(path: Path) -> bool:
    name = path.name.lower()
    if name == "unknown.json":
        return False
    if name.endswith(".product_status_report.json"):
        return False
    if name.endswith(".corrupted_report_backup.json"):
        return False
    return path.suffix.lower() == ".json"


def _current_profile_uid() -> str:
    return _safe_account_uid(_PROFILE_UID)


def _load_profile_result(task_entry: str) -> dict[str, Any]:
    config_path = _task_config_path(task_entry)
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    result = payload.get("profile_read_result") if isinstance(payload, dict) else {}
    return result if isinstance(result, dict) else {}


def _load_account_config(uid: Any) -> dict[str, Any]:
    path = _account_config_path(uid)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_json_file(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


_TRADE_PRODUCTS_BY_CITY_CACHE: dict[str, list[str]] | None = None


def _all_buy_goods_by_city() -> dict[str, list[str]]:
    global _TRADE_PRODUCTS_BY_CITY_CACHE
    if _TRADE_PRODUCTS_BY_CITY_CACHE is not None:
        return {city: list(goods) for city, goods in _TRADE_PRODUCTS_BY_CITY_CACHE.items()}
    trade_data = _read_json_file(COLUMBA_TRADE_DATA_PATH, {})
    products = trade_data.get("products") if isinstance(trade_data, dict) else []
    by_city: dict[str, list[str]] = {}
    for product in (products if isinstance(products, list) else []):
        if not isinstance(product, dict):
            continue
        name = str(product.get("name") or "").strip()
        buy_prices = product.get("buyPrices") if isinstance(product.get("buyPrices"), dict) else {}
        if not name:
            continue
        for city in buy_prices:
            city_name = normalize_city_name(str(city or "").strip())
            if not city_name:
                continue
            goods = by_city.setdefault(city_name, [])
            if name not in goods:
                goods.append(name)
    _TRADE_PRODUCTS_BY_CITY_CACHE = {
        city: sorted(goods)
        for city, goods in sorted(by_city.items())
        if goods
    }
    return {city: list(goods) for city, goods in _TRADE_PRODUCTS_BY_CITY_CACHE.items()}


def _normalize_product_status(value: Any) -> str:
    if isinstance(value, bool):
        return PRODUCT_STATUS_NORMAL if value else PRODUCT_STATUS_LOCKED
    if isinstance(value, (int, float)):
        return PRODUCT_STATUS_NORMAL if int(value) else PRODUCT_STATUS_LOCKED
    text = str(value or "").strip()
    if text in PRODUCT_STATUSES:
        return text
    normalized = PRODUCT_STATUS_ALIASES.get(text.lower()) or PRODUCT_STATUS_ALIASES.get(clean_text(text))
    if normalized:
        return normalized
    return PRODUCT_STATUS_NEVER_SCANNED


def _product_status_by_city(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for city, goods in value.items():
        city_name = normalize_city_name(str(city or "").strip())
        if not city_name or not isinstance(goods, dict):
            continue
        city_status: dict[str, str] = {}
        for good, status in goods.items():
            good_name = str(good or "").strip()
            if not good_name:
                continue
            city_status[good_name] = _normalize_product_status(status)
        if city_status:
            result[city_name] = city_status
    return result


def _complete_product_status_by_city(value: Any) -> dict[str, dict[str, str]]:
    merged = _product_status_by_city(value)
    full: dict[str, dict[str, str]] = {
        city: {good: PRODUCT_STATUS_NEVER_SCANNED for good in goods}
        for city, goods in _all_buy_goods_by_city().items()
    }
    for city, goods in merged.items():
        city_status = full.setdefault(city, {})
        for good, status in goods.items():
            city_status[good] = status
    return {
        city: {good: status for good, status in sorted(goods.items())}
        for city, goods in sorted(full.items())
        if goods
    }


def _merge_product_status_by_city(*values: Any, include_defaults: bool = False) -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for value in values:
        for city, goods in _product_status_by_city(value).items():
            city_status = merged.setdefault(city, {})
            for good, status in goods.items():
                normalized = _normalize_product_status(status)
                previous = city_status.get(good)
                if previous and previous != PRODUCT_STATUS_NEVER_SCANNED and normalized == PRODUCT_STATUS_NEVER_SCANNED:
                    continue
                city_status[good] = normalized
    if include_defaults:
        return _complete_product_status_by_city(merged)
    return {
        city: {good: status for good, status in sorted(goods.items())}
        for city, goods in sorted(merged.items())
        if goods
    }


def _product_unlock_status_by_city(value: Any) -> dict[str, dict[str, bool]]:
    status = _product_status_by_city(value)
    return {
        city: {good: status_text not in PRODUCT_PLANNER_BLOCKED_STATUSES for good, status_text in goods.items()}
        for city, goods in status.items()
        if goods
    }


def _locked_product_status_by_city(value: Any) -> dict[str, dict[str, bool]]:
    status = _product_status_by_city(value)
    return {
        city: {good: False for good, status_text in goods.items() if status_text in PRODUCT_PLANNER_BLOCKED_STATUSES}
        for city, goods in status.items()
        if any(status_text in PRODUCT_PLANNER_BLOCKED_STATUSES for status_text in goods.values())
    }


def _merge_product_unlock_status_by_city(*values: Any) -> dict[str, dict[str, bool]]:
    return _locked_product_status_by_city(
        _merge_product_status_by_city(*values)
    )


def _profile_result_from_account_config(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    trade = payload.get("trade") if isinstance(payload.get("trade"), dict) else {}
    planner = payload.get("planner") if isinstance(payload.get("planner"), dict) else {}
    result: dict[str, Any] = {
        "uid": payload.get("uid"),
        "completed_parts": list(payload.get("completed_parts") or []),
    }
    if isinstance(payload.get("account_profile_read"), dict):
        result["account_profile_read"] = copy.deepcopy(payload.get("account_profile_read") or {})
    if trade.get("cargo_capacity") is not None:
        result["cargo_capacity"] = trade.get("cargo_capacity")
    if isinstance(trade.get("prestige_by_city"), dict):
        result["prestige_by_city"] = dict(trade.get("prestige_by_city") or {})
    if isinstance(trade.get("role_resonance"), dict):
        result["role_resonance"] = dict(trade.get("role_resonance") or {})
    if isinstance(trade.get("available_cities"), list):
        result["available_cities"] = list(trade.get("available_cities") or [])
    if isinstance(trade.get("unavailable_cities"), list):
        result["unavailable_cities"] = list(trade.get("unavailable_cities") or [])
    if isinstance(trade.get("unknown_cities"), list):
        result["unknown_cities"] = list(trade.get("unknown_cities") or [])
    product_status_by_city = _merge_product_status_by_city(
        trade.get("product_status_by_city"),
        planner.get("product_status_by_city"),
        trade.get("product_unlock_status_by_city"),
        planner.get("product_unlock_status_by_city"),
        include_defaults=True,
    )
    if product_status_by_city:
        result["product_status_by_city"] = product_status_by_city
        result["product_unlock_status_by_city"] = _locked_product_status_by_city(product_status_by_city)
    return result


def _planner_overrides(result: dict[str, Any]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    try:
        cargo_capacity = int(result.get("cargo_capacity") or 0)
    except (TypeError, ValueError):
        cargo_capacity = 0
    if cargo_capacity > 0:
        overrides["max_goods_num"] = cargo_capacity
    prestige = result.get("prestige_by_city") or {}
    if prestige:
        overrides["prestige_by_city"] = prestige
    unavailable = result.get("unavailable_cities") or []
    if unavailable:
        overrides["exclude_cities"] = unavailable
    role_resonance = result.get("role_resonance") or {}
    if role_resonance:
        overrides["roles"] = {
            str(role): {"resonance": planner_role_resonance_level(level)}
            for role, level in role_resonance.items()
            if str(role).strip()
        }
    product_unlock_status_by_city = _locked_product_status_by_city(
        result.get("product_status_by_city") or result.get("product_unlock_status_by_city")
    )
    if product_unlock_status_by_city:
        overrides["product_unlock_status_by_city"] = product_unlock_status_by_city
    return overrides


def _merge_profile_result(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(previous or {})
    completed = set(current.get("completed_parts") or [])
    if "read_uid" in completed:
        for key in ("uid", "uid_texts"):
            if key in current:
                merged[key] = copy.deepcopy(current[key])
    if "read_cargo" in completed:
        for key in ("cargo_capacity", "cargo_texts"):
            if key in current:
                merged[key] = copy.deepcopy(current[key])
    if "read_prestige" in completed:
        for key in ("prestige_by_city", "prestige_value_by_city"):
            if key in current:
                merged[key] = copy.deepcopy(current[key])
    if "read_unavailable_cities" in completed:
        for key in ("available_cities", "unavailable_cities", "unknown_cities", "city_unlock_probe"):
            if key in current:
                merged[key] = copy.deepcopy(current[key])
    if "read_role_resonance" in completed:
        for key in ("role_resonance",):
            if key in current:
                merged[key] = copy.deepcopy(current[key])
    if "read_product_status" in completed or "read_product_unlock_status" in completed:
        merged["product_status_by_city"] = _complete_product_status_by_city(
            _merge_product_status_by_city(
                merged.get("product_status_by_city"),
                merged.get("product_unlock_status_by_city"),
                current.get("product_status_by_city"),
                current.get("product_unlock_status_by_city"),
            )
        )
        merged["product_unlock_status_by_city"] = _locked_product_status_by_city(merged["product_status_by_city"])
    if isinstance(current.get("account_profile_read"), dict):
        merged["account_profile_read"] = copy.deepcopy(current.get("account_profile_read") or {})
    elif isinstance(merged.get("account_profile_read"), dict):
        merged["account_profile_read"] = copy.deepcopy(merged.get("account_profile_read") or {})
    merged["completed_parts"] = sorted(set(merged.get("completed_parts") or []) | completed)
    merged["profile_read_run_id"] = current.get("profile_read_run_id") or merged.get("profile_read_run_id")
    return merged


def _compact_account_profile(result: dict[str, Any], *, uid: str) -> dict[str, Any]:
    prestige = {
        str(city): int(level)
        for city, level in (result.get("prestige_by_city") or {}).items()
        if str(city).strip()
    }
    role_resonance = {
        str(role): normalize_role_resonance_level(level)
        for role, level in (result.get("role_resonance") or {}).items()
        if str(role).strip()
    }
    unavailable = sorted(str(city) for city in (result.get("unavailable_cities") or []) if str(city).strip())
    unknown = sorted(str(city) for city in (result.get("unknown_cities") or []) if str(city).strip())
    available = sorted(str(city) for city in (result.get("available_cities") or []) if str(city).strip())
    product_status_by_city = _complete_product_status_by_city(
        _merge_product_status_by_city(
            result.get("product_status_by_city"),
            result.get("product_unlock_status_by_city"),
        )
    )
    product_unlock_status_by_city = _locked_product_status_by_city(product_status_by_city)
    cargo_capacity = result.get("cargo_capacity")
    try:
        cargo_capacity = int(cargo_capacity) if cargo_capacity is not None else None
    except (TypeError, ValueError):
        cargo_capacity = None
    planner = {
        "max_goods_num": cargo_capacity,
        "prestige_by_city": prestige,
        "exclude_cities": unavailable,
        "roles": {role: {"resonance": level} for role, level in role_resonance.items()},
        "product_status_by_city": product_status_by_city,
        "product_unlock_status_by_city": product_unlock_status_by_city,
    }
    planner = {
        key: value
        for key, value in planner.items()
        if value not in ({}, [], None)
    }
    payload = {
        "version": 1,
        "uid": uid,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "completed_parts": list(result.get("completed_parts") or []),
        "trade": {
            "cargo_capacity": cargo_capacity,
            "prestige_by_city": prestige,
            "available_cities": available,
            "unavailable_cities": unavailable,
            "unknown_cities": unknown,
            "role_resonance": role_resonance,
            "product_status_by_city": product_status_by_city,
            "product_unlock_status_by_city": product_unlock_status_by_city,
        },
        "planner": planner,
    }
    if isinstance(result.get("account_profile_read"), dict):
        payload["account_profile_read"] = copy.deepcopy(result.get("account_profile_read") or {})
    return payload


def _save_unified_account_profile(partial_result: dict[str, Any], *, task_entry: str) -> str:
    uid = _safe_account_uid(partial_result.get("uid") or _PROFILE_UID)
    previous_config = _load_account_config(uid)
    previous_result = _profile_result_from_account_config(previous_config)
    merged_result = _merge_profile_result(previous_result, partial_result)
    uid = _safe_account_uid(merged_result.get("uid") or uid)
    path = _account_config_path(uid)
    payload = _compact_account_profile(merged_result, uid=uid)
    payload["_source"] = {
        "last_task_entry": task_entry,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return str(path)


def _save_profile_result(result: dict[str, Any], *, task_entry: str = TASK_ENTRY) -> str:
    config_path = _task_config_path(task_entry)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    unified_path = _save_unified_account_profile(result, task_entry=task_entry)
    payload = {
        "version": 1,
        "task_entry": task_entry,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "profile_read_result": result,
        "planner_overrides": _planner_overrides(result),
        "account_profile_path": unified_path,
    }
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return str(config_path)


def _record_prestige_page(page_index: int, values: dict[str, int], texts: list[str]) -> dict[str, Any]:
    state = _state_for_page(page_index)
    run_id = str(state.get("profile_read_run_id") or "")
    stored_texts = state.setdefault("prestige_texts", [])
    for text in texts[:80]:
        if text not in stored_texts:
            stored_texts.append(text)

    stored_values = state.setdefault("prestige_value_by_city", {})
    before = dict(stored_values)
    stored_values.update(values)
    new_count = len(set(stored_values) - set(before))
    levels = prestige_values_to_levels({city: int(value) for city, value in stored_values.items()})
    state["prestige_by_city"] = levels
    state["ok"] = bool(levels)
    completed = state.setdefault("completed_parts", [])
    if "read_prestige" not in completed:
        completed.append("read_prestige")
    expected_cities = list(load_city_names())
    missing_cities = [city for city in expected_cities if city not in levels]
    state.setdefault("prestige_pages", []).append(
        {
            "page_index": page_index,
            "value_count": len(values),
            "new_count": new_count,
            "texts": texts[:24],
        }
    )
    config_path = _save_profile_result(copy.deepcopy(state))
    level = "info" if values else "warning"
    _append_user_log(
        TASK_ENTRY,
        f"城市声望第 {page_index} 页识别完成：本页 {len(values)} 个，新增 {new_count} 个，累计 {len(levels)} 个",
        run_id=run_id,
        level=level,
        event="prestige_page_read",
        data={
            "page_index": page_index,
            "page_value_count": len(values),
            "new_count": new_count,
            "city_count": len(levels),
            "missing_count": len(missing_cities),
        },
    )
    return {
        "ok": bool(values),
        "page_index": page_index,
        "page_value_count": len(values),
        "city_count": len(levels),
        "expected_city_count": len(expected_cities),
        "missing_cities": missing_cities,
        "prestige_value_by_city": dict(stored_values),
        "prestige_by_city": levels,
        "config_path": config_path,
        "texts": texts[:20],
    }


def _complete_prestige_read() -> dict[str, Any]:
    state = _PRESTIGE_STATE or _initial_state()
    levels = dict(state.get("prestige_by_city") or {})
    values = dict(state.get("prestige_value_by_city") or {})
    expected_cities = list(load_city_names())
    missing_cities = [city for city in expected_cities if city not in levels]
    state["ok"] = bool(levels)
    state["status"] = "PrestigePipelineSucceeded" if state["ok"] else "PrestigePipelineIncomplete"
    config_path = _save_profile_result(copy.deepcopy(state))
    run_id = str(state.get("profile_read_run_id") or "")
    level = "info" if state["ok"] else "warning"
    _append_user_log(
        TASK_ENTRY,
        f"城市声望读取完成：识别 {len(levels)}/{len(expected_cities)} 个城市，缺失 {len(missing_cities)} 个",
        run_id=run_id,
        level=level,
        event="prestige_completed",
        data={
            "status": state["status"],
            "city_count": len(levels),
            "expected_city_count": len(expected_cities),
            "missing_cities": missing_cities,
            "config_path": config_path,
        },
    )
    return {
        "ok": state["ok"],
        "status": state["status"],
        "city_count": len(levels),
        "value_count": len(values),
        "expected_city_count": len(expected_cities),
        "missing_cities": missing_cities,
        "config_path": config_path,
        "run_log_path": str(_task_log_text_path(TASK_ENTRY)),
    }


def _initial_city_unlock_state() -> dict[str, Any]:
    return {
        "ok": False,
        "task_entry": CITY_UNLOCK_TASK_ENTRY,
        "uid": _current_profile_uid(),
        "profile_read_run_id": time.strftime("%Y%m%d_%H%M%S"),
        "completed_parts": [],
        "available_cities": [],
        "unavailable_cities": [],
        "unknown_cities": [],
        "city_unlock_probe": {},
        "unavailable_city_texts": [],
    }


def _initial_city_unlock_state_from_saved() -> dict[str, Any]:
    state = _initial_city_unlock_state()
    saved = _load_profile_result(CITY_UNLOCK_TASK_ENTRY)
    probes = saved.get("city_unlock_probe") if isinstance(saved.get("city_unlock_probe"), dict) else {}
    for city, item in probes.items():
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip()
        if status:
            state.setdefault("city_unlock_probe", {})[str(city)] = {
                "status": status,
                "texts": item.get("texts") if isinstance(item.get("texts"), list) else [],
            }
    _update_city_unlock_lists(state)
    return state


def _city_unlock_state(*, reset: bool = False) -> dict[str, Any]:
    global _CITY_UNLOCK_STATE
    if reset or not _CITY_UNLOCK_STATE:
        _CITY_UNLOCK_STATE = _initial_city_unlock_state()
        _start_user_log(
            CITY_UNLOCK_TASK_ENTRY,
            str(_CITY_UNLOCK_STATE["profile_read_run_id"]),
            "开始读取账号配置-城市开放",
        )
    return _CITY_UNLOCK_STATE


def _city_unlock_missing_state(*, reset: bool = False) -> dict[str, Any]:
    global _CITY_UNLOCK_STATE
    if reset or not _CITY_UNLOCK_STATE:
        _CITY_UNLOCK_STATE = _initial_city_unlock_state_from_saved()
        _start_user_log(
            CITY_UNLOCK_TASK_ENTRY,
            str(_CITY_UNLOCK_STATE["profile_read_run_id"]),
            "开始读取账号配置-城市开放（仅缺失/未知）",
        )
    return _CITY_UNLOCK_STATE


def _update_city_unlock_lists(state: dict[str, Any]) -> None:
    probes = state.get("city_unlock_probe") or {}
    state["available_cities"] = sorted(
        city for city, item in probes.items() if (item or {}).get("status") == "available"
    )
    state["unavailable_cities"] = sorted(
        city for city, item in probes.items() if (item or {}).get("status") == "unavailable"
    )
    state["unknown_cities"] = sorted(
        city for city, item in probes.items() if (item or {}).get("status") == "unknown"
    )


def _city_unlock_should_probe(city: str, *, reset: bool = False, probe_mode: str = "missing_unknown") -> dict[str, Any]:
    state = _city_unlock_missing_state(reset=reset)
    run_id = str(state.get("profile_read_run_id") or "")
    city_name = str(city or "").strip()
    current = (state.get("city_unlock_probe") or {}).get(city_name) or {}
    status = str(current.get("status") or "").strip()
    if probe_mode == "unavailable_missing":
        should_probe = status != "available"
    else:
        should_probe = status not in {"available", "unavailable"}
    reason = "missing" if not status else f"status_{status}"
    if should_probe:
        try:
            city_index = CITY_UNLOCK_TARGETS.index(city_name) + 1
        except ValueError:
            city_index = 0
        _append_user_log(
            CITY_UNLOCK_TASK_ENTRY,
            f"城市开放增量扫描：{city_name} 需要识别（{reason}）",
            run_id=run_id,
            event="city_unlock_increment_probe_needed",
            data={"city": city_name, "city_index": city_index, "status": status, "reason": reason},
        )
    else:
        _append_user_log(
            CITY_UNLOCK_TASK_ENTRY,
            f"城市开放增量扫描：跳过 {city_name}（已有 {CITY_UNLOCK_STATUS_LABELS.get(status, status)}）",
            run_id=run_id,
            event="city_unlock_increment_probe_skipped",
            data={"city": city_name, "status": status},
        )
    return {
        "ok": should_probe,
        "city": city_name,
        "status": status,
        "reason": reason,
        "probe_count": len(state.get("city_unlock_probe") or {}),
    }


def _record_city_unlock_probe(city: str, texts: list[str], *, reset: bool = False) -> dict[str, Any]:
    state = _city_unlock_state(reset=reset)
    run_id = str(state.get("profile_read_run_id") or "")
    city_name = str(city or "").strip()
    status = classify_city_unlock_probe(texts)
    probe_key = city_name or f"probe_{len(state.get('city_unlock_probe') or {}) + 1}"
    previous = (state.get("city_unlock_probe") or {}).get(probe_key) or {}
    previous_status = str(previous.get("status") or "").strip()
    effective_status = status
    if status == "unknown" and previous_status in {"available", "unavailable"}:
        effective_status = previous_status
    state.setdefault("city_unlock_probe", {})[probe_key] = {
        "status": effective_status,
        "texts": texts[:20],
    }
    stored_texts = state.setdefault("unavailable_city_texts", [])
    for text in texts[:20]:
        if text not in stored_texts:
            stored_texts.append(text)
    _update_city_unlock_lists(state)
    state["ok"] = bool(state.get("city_unlock_probe"))
    config_path = _save_profile_result(copy.deepcopy(state), task_entry=CITY_UNLOCK_TASK_ENTRY)
    missing_cities = [
        city
        for city in CITY_UNLOCK_TARGETS
        if city not in (state.get("city_unlock_probe") or {})
    ]
    status_label = CITY_UNLOCK_STATUS_LABELS.get(effective_status, effective_status)
    level = "warning" if status == "unknown" and effective_status == "unknown" else "info"
    if status == "unknown" and effective_status != status:
        message = f"城市开放识别：{probe_key} 本轮未确认，保留已有 {status_label}"
    else:
        message = (
            f"城市开放识别：{probe_key} -> {status_label} "
            f"({len(state.get('city_unlock_probe') or {})}/{len(CITY_UNLOCK_TARGETS)})"
        )
    _append_user_log(
        CITY_UNLOCK_TASK_ENTRY,
        message,
        run_id=run_id,
        level=level,
        event="city_unlock_probe",
        data={
            "city": probe_key,
            "status": effective_status,
            "raw_status": status,
            "probe_count": len(state.get("city_unlock_probe") or {}),
            "target_count": len(CITY_UNLOCK_TARGETS),
            "missing_count": len(missing_cities),
        },
    )
    return {
        "ok": True,
        "city": probe_key,
        "status": effective_status,
        "raw_status": status,
        "probe_count": len(state.get("city_unlock_probe") or {}),
        "target_count": len(CITY_UNLOCK_TARGETS),
        "missing_cities": missing_cities,
        "available_cities": list(state.get("available_cities") or []),
        "unavailable_cities": list(state.get("unavailable_cities") or []),
        "unknown_cities": list(state.get("unknown_cities") or []),
        "config_path": config_path,
        "texts": texts[:12],
    }


def _complete_city_unlock_read() -> dict[str, Any]:
    state = _city_unlock_state()
    run_id = str(state.get("profile_read_run_id") or "")
    completed = state.setdefault("completed_parts", [])
    if "read_unavailable_cities" not in completed:
        completed.append("read_unavailable_cities")
    _update_city_unlock_lists(state)
    missing_cities = [
        city
        for city in CITY_UNLOCK_TARGETS
        if city not in (state.get("city_unlock_probe") or {})
    ]
    unknown_cities = list(state.get("unknown_cities") or [])
    state["ok"] = not missing_cities and not unknown_cities and bool(state.get("city_unlock_probe"))
    state["status"] = "CityUnlockPipelineSucceeded" if state["ok"] else "CityUnlockPipelineIncomplete"
    config_path = _save_profile_result(copy.deepcopy(state), task_entry=CITY_UNLOCK_TASK_ENTRY)
    auto_exclude_sync = _sync_auto_two_city_exclude_cities_from_unavailable(
        state.get("unavailable_cities") or [],
        run_id=run_id,
    )
    level = "info" if state["ok"] else "warning"
    _append_user_log(
        CITY_UNLOCK_TASK_ENTRY,
        (
            "城市开放读取完成："
            f"开放 {len(state.get('available_cities') or [])}，"
            f"未开放 {len(state.get('unavailable_cities') or [])}，"
            f"未知 {len(unknown_cities)}，"
            f"缺失 {len(missing_cities)}"
        ),
        run_id=run_id,
        level=level,
        event="city_unlock_completed",
        data={
            "status": state["status"],
            "probe_count": len(state.get("city_unlock_probe") or {}),
            "target_count": len(CITY_UNLOCK_TARGETS),
            "missing_cities": missing_cities,
            "unknown_cities": unknown_cities,
            "config_path": config_path,
            "auto_two_city_exclude_sync": auto_exclude_sync,
        },
    )
    return {
        "ok": state["ok"],
        "status": state["status"],
        "probe_count": len(state.get("city_unlock_probe") or {}),
        "target_count": len(CITY_UNLOCK_TARGETS),
        "missing_cities": missing_cities,
        "available_cities": list(state.get("available_cities") or []),
        "unavailable_cities": list(state.get("unavailable_cities") or []),
        "unknown_cities": unknown_cities,
        "config_path": config_path,
        "auto_two_city_exclude_sync": auto_exclude_sync,
        "run_log_path": str(_task_log_text_path(CITY_UNLOCK_TASK_ENTRY)),
    }


def _role_targets_from_params(params: dict[str, Any] | None = None) -> tuple[str, ...]:
    params = params or {}
    raw = params.get("role_targets") or params.get("role_resonance_targets")
    requested: list[str] = []
    if isinstance(raw, str):
        requested = [part.strip() for part in re.split(r"[,，;；\n]+", raw) if part.strip()]
    elif isinstance(raw, (list, tuple, set)):
        requested = [str(part).strip() for part in raw if str(part).strip()]
    all_roles = load_role_names()
    if not requested:
        return all_roles
    valid = set(all_roles)
    result: list[str] = []
    for role in requested:
        if role in valid and role not in result:
            result.append(role)
    return tuple(result or requested)


def _configured_role_resonance_roles(uid: Any) -> set[str]:
    payload = _load_account_config(uid)
    trade = payload.get("trade") if isinstance(payload.get("trade"), dict) else {}
    raw = trade.get("role_resonance") if isinstance(trade.get("role_resonance"), dict) else {}
    configured: set[str] = set()
    for role, level in raw.items():
        role_name = str(role or "").strip()
        if not role_name:
            continue
        if level is None or level == "":
            continue
        configured.add(role_name)
    return configured


def _initial_role_resonance_state() -> dict[str, Any]:
    return {
        "ok": False,
        "task_entry": ROLE_RESONANCE_TASK_ENTRY,
        "uid": _current_profile_uid(),
        "profile_read_run_id": time.strftime("%Y%m%d_%H%M%S"),
        "completed_parts": [],
        "role_resonance": {},
        "role_resonance_votes": {},
        "role_resonance_seen_roles": [],
        "role_resonance_page_signatures": [],
        "role_resonance_texts": [],
        "role_resonance_pages": [],
        "role_resonance_sort_state": {},
        "role_resonance_scan_mode": "full",
    }


def _role_resonance_state(*, reset: bool = False) -> dict[str, Any]:
    global _ROLE_RESONANCE_STATE
    if reset or not _ROLE_RESONANCE_STATE:
        _ROLE_RESONANCE_STATE = _initial_role_resonance_state()
        _start_user_log(
            ROLE_RESONANCE_TASK_ENTRY,
            str(_ROLE_RESONANCE_STATE["profile_read_run_id"]),
            "开始读取账号配置-角色共振",
        )
    return _ROLE_RESONANCE_STATE


def _resolve_role_resonance_votes(votes: dict[str, Any]) -> dict[str, int]:
    resolved: dict[str, int] = {}
    for role, role_votes in votes.items():
        if not isinstance(role_votes, list):
            continue
        level = resolve_resonance_votes(role_votes)
        if level is not None:
            resolved[role] = level
    return resolved


def _parse_role_resonance_page(
    *,
    page_index: int,
    role_names: tuple[str, ...],
    texts: list[str],
    entries: list[dict[str, Any]],
    image: Any = None,
) -> dict[str, Any]:
    visible_roles = visible_role_names_from_entries(entries, role_names)
    page_roles = parse_role_resonance_from_entries(entries, role_names, weighted=True)

    badge_roles: dict[str, Any] = {}
    if image is not None and entries:
        try:
            badge_roles = parse_role_badges_from_image(image, entries, role_names, weighted=True)
        except Exception as exc:
            _append_user_log(
                ROLE_RESONANCE_TASK_ENTRY,
                f"角色共振模板识别跳过：{type(exc).__name__}: {exc}",
                run_id=str(_role_resonance_state().get("profile_read_run_id") or ""),
                level="warning",
                event="role_resonance_badge_scan_skipped",
            )

    for role, level in badge_roles.items():
        current = page_roles.get(role)
        badge_weight = level[1] if isinstance(level, tuple) else 1
        current_weight = current[1] if isinstance(current, tuple) else (1 if current is not None else 0)
        if current is None or badge_weight >= current_weight:
            page_roles[role] = level

    text_roles: dict[str, Any] = {}
    text_fallback_needed = not page_roles or bool(visible_roles - set(page_roles))
    if text_fallback_needed:
        text_roles = {
            role: (level, 1)
            for role, level in parse_role_resonance_texts(texts, role_names).items()
        }
        if not page_roles:
            page_roles = dict(text_roles)
        else:
            for role, level in text_roles.items():
                page_roles.setdefault(role, level)

    if visible_roles:
        allowed_roles = set(visible_roles) | set(text_roles)
        page_roles = {role: level for role, level in page_roles.items() if role in allowed_roles}
        badge_roles = {role: level for role, level in badge_roles.items() if role in visible_roles}
    signature = crew_page_signature(entries, role_names)
    missing_visible_roles = sorted(role for role in visible_roles if role not in page_roles)
    debug_crop_paths: list[str] = []
    save_missing_crops = _env_truthy_default(
        "MAA_RESONANCE_ROLE_MISSING_CROP_DEBUG",
        _env_truthy_default("MAA_RESONANCE_ROLE_CROP_DEBUG", False),
    )
    if image is not None and entries and missing_visible_roles and save_missing_crops:
        try:
            debug_crop_paths = save_role_badge_debug_crops(
                image,
                entries,
                role_names,
                roles=missing_visible_roles,
                page_index=page_index,
                run_id=str(_role_resonance_state().get("profile_read_run_id") or ""),
            )
        except Exception as exc:
            _append_user_log(
                ROLE_RESONANCE_TASK_ENTRY,
                f"角色共振诊断裁剪保存失败：{type(exc).__name__}: {exc}",
                run_id=str(_role_resonance_state().get("profile_read_run_id") or ""),
                level="warning",
                event="role_resonance_debug_crop_failed",
            )
    return _record_role_resonance_page(
        page_index,
        page_roles,
        badge_roles,
        visible_roles,
        signature,
        texts,
        debug_crop_paths=debug_crop_paths,
    )


def _image_size(image: Any) -> int:
    try:
        return int(getattr(image, "size", 0) or 0)
    except Exception:
        return 0


def _role_page_image_from_context(context: Context, page_index: int, detail: Any, run_id: str) -> Any:
    image = None
    if detail is not None:
        try:
            image = getattr(detail, "raw_image", None)
        except Exception as exc:
            _append_user_log(
                ROLE_RESONANCE_TASK_ENTRY,
                f"角色共振第 {page_index} 页 reco_detail 截图读取失败：{type(exc).__name__}: {exc}",
                run_id=run_id,
                level="warning",
                event="role_resonance_detail_image_failed",
                data={"page_index": page_index},
            )
    if _image_size(image) > 0:
        return image

    try:
        image = context.tasker.controller.cached_image
        if _image_size(image) > 0:
            return image
    except Exception as exc:
        _append_user_log(
            ROLE_RESONANCE_TASK_ENTRY,
            f"角色共振第 {page_index} 页读取控制器缓存截图失败：{type(exc).__name__}: {exc}",
            run_id=run_id,
            level="warning",
            event="role_resonance_cached_image_failed",
            data={"page_index": page_index},
        )

    try:
        image = context.tasker.controller.post_screencap().wait().result
        if _image_size(image) > 0:
            return image
    except Exception as exc:
        _append_user_log(
            ROLE_RESONANCE_TASK_ENTRY,
            f"角色共振第 {page_index} 页主动截图失败：{type(exc).__name__}: {exc}",
            run_id=run_id,
            level="warning",
            event="role_resonance_screencap_failed",
            data={"page_index": page_index},
        )

    node_name = f"AccountProfileRoleResonancePageOcr{page_index:03d}"
    try:
        node_detail = context.tasker.get_latest_node(node_name)
        recognition = getattr(node_detail, "recognition", None) if node_detail is not None else None
        image = getattr(recognition, "raw_image", None) if recognition is not None else None
        if _image_size(image) > 0:
            return image
        _append_user_log(
            ROLE_RESONANCE_TASK_ENTRY,
            f"角色共振第 {page_index} 页未取得截图，模板识别将跳过",
            run_id=run_id,
            level="warning",
            event="role_resonance_page_image_missing",
            data={
                "page_index": page_index,
                "node_name": node_name,
                "has_node_detail": node_detail is not None,
                "has_recognition": recognition is not None,
            },
        )
    except Exception as exc:
        _append_user_log(
            ROLE_RESONANCE_TASK_ENTRY,
            f"角色共振第 {page_index} 页回查截图失败：{type(exc).__name__}: {exc}",
            run_id=run_id,
            level="warning",
            event="role_resonance_context_image_failed",
            data={"page_index": page_index, "node_name": node_name, "traceback": traceback.format_exc()},
        )
    return None


def _record_crew_warehouse_ready(readiness: dict[str, Any]) -> dict[str, Any]:
    state = _role_resonance_state(reset=True)
    run_id = str(state.get("profile_read_run_id") or "")
    ready = bool(readiness.get("ready"))
    level = "info" if ready else "warning"
    message = (
        "已打开乘员仓库，准备扫描角色共振"
        if ready
        else "乘员仓库确认失败：未识别到足够的标题或角色信息"
    )
    _append_user_log(
        ROLE_RESONANCE_TASK_ENTRY,
        message,
        run_id=run_id,
        level=level,
        event="role_resonance_warehouse_ready",
        data={
            "ready": ready,
            "header_hits": readiness.get("header_hits"),
            "role_hit_count": readiness.get("role_hit_count"),
            "lv_hits": readiness.get("lv_hits"),
            "star_hits": readiness.get("star_hits"),
        },
    )
    return {"ok": ready, **readiness}


def _record_crew_sort_ready(
    *,
    attempt: int,
    max_attempts: int,
    clicked: bool,
    arrow_down: bool | None,
    tap_point: tuple[int, int] | None,
    reason: str,
    error: str = "",
) -> dict[str, Any]:
    state = _role_resonance_state()
    run_id = str(state.get("profile_read_run_id") or "")
    ok = bool(arrow_down is True or (not clicked and reason in {"arrow_unconfirmed_skip", "sort_entry_missing"}))
    sort_state = {
        "ok": ok,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "clicked": clicked,
        "arrow_down": arrow_down,
        "tap_point": list(tap_point) if tap_point else None,
        "reason": reason,
    }
    if error:
        sort_state["error"] = error
    state["role_resonance_sort_state"] = sort_state

    if arrow_down is True:
        message = "乘员仓库排序确认：获取时间降序"
        level = "info"
    elif clicked:
        message = "乘员仓库排序未就绪，已点击获取时间排序控件后复查"
        level = "info"
    else:
        message = f"乘员仓库排序未能确认：{reason}，按当前排序继续"
        level = "warning"
    _append_user_log(
        ROLE_RESONANCE_TASK_ENTRY,
        message,
        run_id=run_id,
        level=level,
        event="role_resonance_sort_ready",
        data=sort_state,
    )
    return sort_state


def _record_role_resonance_page(
    page_index: int,
    page_roles: dict[str, Any],
    badge_roles: dict[str, Any],
    visible_roles: set[str],
    signature: tuple[str, ...],
    texts: list[str],
    *,
    debug_crop_paths: list[str] | None = None,
) -> dict[str, Any]:
    state = _role_resonance_state()
    run_id = str(state.get("profile_read_run_id") or "")
    stored_texts = state.setdefault("role_resonance_texts", [])
    for text in texts[:80]:
        if text not in stored_texts:
            stored_texts.append(text)

    seen_roles = state.setdefault("role_resonance_seen_roles", [])
    for role in sorted(set(visible_roles) | set(page_roles)):
        if role not in seen_roles:
            seen_roles.append(role)

    signatures = state.setdefault("role_resonance_page_signatures", [])
    if signature:
        signatures.append(list(signature))

    votes = state.setdefault("role_resonance_votes", {})
    for role, vote in page_roles.items():
        votes.setdefault(role, []).append(list(vote) if isinstance(vote, tuple) else vote)

    resolved = _resolve_role_resonance_votes(votes)
    state["role_resonance"] = resolved
    state["ok"] = bool(resolved or seen_roles)
    missing_visible_roles = sorted(role for role in visible_roles if role not in page_roles)
    debug_crop_paths = debug_crop_paths or []
    state.setdefault("role_resonance_pages", []).append(
        {
            "page_index": page_index,
            "page_role_count": len(page_roles),
            "badge_role_count": len(badge_roles),
            "visible_role_count": len(visible_roles),
            "missing_visible_count": len(missing_visible_roles),
            "resolved_count": len(resolved),
            "page_roles": page_roles,
            "badge_roles": badge_roles,
            "visible_roles": sorted(visible_roles),
            "missing_visible_roles": missing_visible_roles,
            "debug_crop_count": len(debug_crop_paths),
            "debug_crop_paths": debug_crop_paths[:40],
            "signature": list(signature),
            "texts": texts[:24],
        }
    )
    log_level = "info" if page_roles or visible_roles else "warning"
    _append_user_log(
        ROLE_RESONANCE_TASK_ENTRY,
        (
            f"角色共振第 {page_index} 页扫描完成："
            f"模板 {len(badge_roles)} 个，合并解析 {len(page_roles)} 个，"
            f"看到 {len(visible_roles)} 个，累计解析 {len(resolved)} 个"
            + (f"，诊断裁剪 {len(debug_crop_paths)} 个" if debug_crop_paths else "")
        ),
        run_id=run_id,
        level=log_level,
        event="role_resonance_page_read",
        data={
            "page_index": page_index,
            "page_role_count": len(page_roles),
            "badge_role_count": len(badge_roles),
            "visible_role_count": len(visible_roles),
            "missing_visible_count": len(missing_visible_roles),
            "missing_visible_roles": missing_visible_roles[:12],
            "debug_crop_count": len(debug_crop_paths),
            "resolved_count": len(resolved),
            "signature_count": len(signature),
        },
    )
    return {
        "ok": True,
        "page_index": page_index,
        "page_role_count": len(page_roles),
        "badge_role_count": len(badge_roles),
        "visible_role_count": len(visible_roles),
        "resolved_count": len(resolved),
        "visible_roles": sorted(visible_roles)[:20],
        "page_roles": page_roles,
        "badge_roles": badge_roles,
        "role_resonance": resolved,
        "debug_crop_count": len(debug_crop_paths),
        "config_path": "",
        "texts": texts[:12],
    }


def _role_resonance_continue_state(
    page_index: int,
    *,
    role_names: tuple[str, ...],
    stale_limit: int,
    max_pages: int,
    scan_mode: str = "full",
) -> dict[str, Any]:
    state = _role_resonance_state()
    run_id = str(state.get("profile_read_run_id") or "")
    scan_mode = str(scan_mode or state.get("role_resonance_scan_mode") or "full").strip()
    if scan_mode:
        state["role_resonance_scan_mode"] = scan_mode
    resonance = state.get("role_resonance") or {}
    unresolved = [role for role in role_names if role not in resonance]
    pages = state.get("role_resonance_pages") or []
    last_page = pages[-1] if pages else {}
    current_page_roles = sorted(
        set(last_page.get("visible_roles") or [])
        | set((last_page.get("page_roles") or {}).keys())
        | set((last_page.get("badge_roles") or {}).keys())
    )
    configured_roles = _configured_role_resonance_roles(state.get("uid") or _current_profile_uid())
    missing_config_roles_on_page = [
        role for role in current_page_roles if role and role not in configured_roles
    ]
    signatures = state.get("role_resonance_page_signatures") or []
    current_signature = signatures[-1] if signatures else []
    same_signature_count = 0
    if current_signature:
        for signature in reversed(signatures):
            if signature == current_signature:
                same_signature_count += 1
            else:
                break

    if scan_mode == "missing_roles":
        if missing_config_roles_on_page:
            should_continue = page_index < max_pages
            reason = "missing_config_roles_on_page" if should_continue else "max_pages_reached"
        else:
            should_continue = False
            reason = "no_missing_config_roles_on_page"
    elif role_names and not unresolved:
        should_continue = False
        reason = "all_targets_resolved"
    elif current_signature and len(current_signature) >= 2 and same_signature_count >= stale_limit:
        should_continue = False
        reason = "stale_page_signature"
    elif page_index >= max_pages:
        should_continue = False
        reason = "max_pages_reached"
    else:
        should_continue = True
        reason = "continue_scan"

    level = "info" if should_continue else "warning"
    message = (
        f"角色共振继续扫描：第 {page_index} 页后继续"
        if should_continue
        else f"角色共振停止扫描：{reason}"
    )
    _append_user_log(
        ROLE_RESONANCE_TASK_ENTRY,
        message,
        run_id=run_id,
        level=level,
        event="role_resonance_continue",
        data={
            "page_index": page_index,
            "should_continue": should_continue,
            "reason": reason,
            "resolved_count": len(resonance),
            "target_count": len(role_names),
            "same_signature_count": same_signature_count,
            "scan_mode": scan_mode,
            "current_page_roles": current_page_roles[:20],
            "configured_role_count": len(configured_roles),
            "missing_config_roles_on_page": missing_config_roles_on_page[:20],
        },
    )
    state["role_resonance_continue_state"] = {
        "page_index": page_index,
        "should_continue": should_continue,
        "reason": reason,
        "resolved_count": len(resonance),
        "target_count": len(role_names),
        "same_signature_count": same_signature_count,
        "current_signature": current_signature,
        "scan_mode": scan_mode,
        "current_page_roles": current_page_roles[:20],
        "configured_role_count": len(configured_roles),
        "missing_config_roles_on_page": missing_config_roles_on_page[:20],
    }
    return {
        "ok": should_continue,
        **state["role_resonance_continue_state"],
        "unresolved": unresolved[:20],
    }


def _complete_role_resonance_read(role_names: tuple[str, ...], *, scan_mode: str = "full") -> dict[str, Any]:
    state = _role_resonance_state()
    run_id = str(state.get("profile_read_run_id") or "")
    scan_mode = str(scan_mode or state.get("role_resonance_scan_mode") or "full").strip()
    votes = state.setdefault("role_resonance_votes", {})
    resonance = _resolve_role_resonance_votes(votes)
    seen_roles = set(state.get("role_resonance_seen_roles") or [])
    if scan_mode == "missing_roles":
        unresolved_roles = sorted(role for role in seen_roles if role not in resonance)
    else:
        unresolved_roles = sorted(role for role in role_names if role not in resonance)
    if seen_roles:
        for role in unresolved_roles:
            resonance[role] = -1
    state["role_resonance"] = resonance
    completed = state.setdefault("completed_parts", [])
    if "read_role_resonance" not in completed:
        completed.append("read_role_resonance")
    missing_seen_roles = sorted(role for role in seen_roles if role not in votes)
    missing_roles = sorted(set(missing_seen_roles) | set(unresolved_roles))
    state["missing_role_resonance"] = missing_roles
    state["unresolved_role_resonance"] = unresolved_roles
    state["ok"] = bool(resonance or seen_roles) and not missing_roles
    state["status"] = "RoleResonancePipelineSucceeded" if state["ok"] else "RoleResonancePipelineIncomplete"
    config_path = _save_profile_result(copy.deepcopy(state), task_entry=ROLE_RESONANCE_TASK_ENTRY)
    log_level = "info" if state["ok"] else "warning"
    _append_user_log(
        ROLE_RESONANCE_TASK_ENTRY,
        (
            f"角色共振读取完成：记录 {len(resonance)} 名角色，扫描到 {len(seen_roles)} 名角色，"
            f"缺少 {len(missing_roles)} 名角色共振"
        ),
        run_id=run_id,
        level=log_level,
        event="role_resonance_completed",
        data={
            "status": state["status"],
            "role_count": len(resonance),
            "seen_count": len(seen_roles),
            "missing_count": len(missing_roles),
            "missing_role_resonance": missing_roles,
            "unresolved_role_resonance": unresolved_roles,
            "target_count": len(role_names),
            "scan_mode": scan_mode,
            "config_path": config_path,
        },
    )
    return {
        "ok": state["ok"],
        "status": state["status"],
        "role_count": len(resonance),
        "seen_count": len(seen_roles),
        "missing_count": len(missing_roles),
        "missing_role_resonance": missing_roles,
        "unresolved_role_resonance": unresolved_roles,
        "target_count": len(role_names),
        "role_resonance": resonance,
        "scan_mode": scan_mode,
        "config_path": config_path,
        "run_log_path": str(_task_log_text_path(ROLE_RESONANCE_TASK_ENTRY)),
    }


@AgentServer.custom_action("profile_prestige_read")
class ProfilePrestigeReadAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        try:
            page_index = int(params.get("page_index") or 1)
        except (TypeError, ValueError):
            page_index = 1
        texts = _ocr_texts(argv)
        entries = _ocr_entries(argv)
        values = parse_city_prestige_values_from_entries(entries)
        if not values:
            values = parse_city_prestige_values(texts)
        payload = _record_prestige_page(page_index, values, texts)
        _json_payload("profile_prestige_read", payload)
        return True


@AgentServer.custom_action("profile_uid_read")
class ProfileUidReadAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        payload = _record_profile_uid(_ocr_texts(argv))
        _json_payload("profile_uid_read", payload)
        return True


@AgentServer.custom_action("profile_cargo_read")
class ProfileCargoReadAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        payload = _record_cargo_capacity(_ocr_texts(argv))
        _json_payload("profile_cargo_read", payload)
        return True


@AgentServer.custom_action("profile_cargo_start")
class ProfileCargoStartAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _cargo_state(reset=True)
        payload = {
            "ok": True,
            "uid": _current_profile_uid(),
            "run_id": state.get("profile_read_run_id"),
        }
        _json_payload("profile_cargo_start", payload)
        return True


@AgentServer.custom_action("profile_prestige_complete")
class ProfilePrestigeCompleteAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        payload = _complete_prestige_read()
        _json_payload("profile_prestige_complete", payload)
        return True


@AgentServer.custom_action("profile_crew_warehouse_ready")
class ProfileCrewWarehouseReadyAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        texts = _ocr_texts(argv)
        readiness = crew_warehouse_readiness(texts, load_role_names())
        payload = _record_crew_warehouse_ready(readiness)
        _json_payload("profile_crew_warehouse_ready", payload)
        return bool(payload.get("ok"))


@AgentServer.custom_action("profile_crew_sort_ready")
class ProfileCrewSortReadyAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        attempt = _int_param(params, "attempt", 1, minimum=1)
        max_attempts = _int_param(params, "max_attempts", 3, minimum=1)
        detail = getattr(argv, "reco_detail", None)
        entries = _ocr_entries_from_detail(detail)
        entry = crew_sort_entry(entries)
        image = getattr(getattr(context.tasker, "controller", None), "cached_image", None)
        if image is None and detail is not None:
            image = getattr(detail, "raw_image", None)

        clicked = False
        tap_point: tuple[int, int] | None = None
        arrow_down: bool | None = None
        reason = "sort_entry_missing"
        error = ""

        if entry is not None:
            arrow_down = crew_sort_arrow_down(image, entry)
            if arrow_down is True:
                reason = "already_descending"
            else:
                tap_point = crew_sort_tap_point(image, entry)
                should_click = arrow_down is False or (arrow_down is None and attempt == 1)
                if should_click and tap_point:
                    try:
                        context.tasker.controller.post_click(int(tap_point[0]), int(tap_point[1])).wait()
                        clicked = True
                        reason = "clicked_to_descending" if arrow_down is False else "clicked_to_select_time"
                    except Exception as exc:
                        reason = "click_failed"
                        error = f"{type(exc).__name__}: {exc}"
                elif tap_point is None:
                    reason = "tap_point_unavailable"
                else:
                    reason = "arrow_unconfirmed_skip"

        payload = _record_crew_sort_ready(
            attempt=attempt,
            max_attempts=max_attempts,
            clicked=clicked,
            arrow_down=arrow_down,
            tap_point=tap_point,
            reason=reason,
            error=error,
        )
        _json_payload("profile_crew_sort_ready", payload)
        return not (clicked and attempt < max_attempts)


@AgentServer.custom_action("profile_role_resonance_page_read")
class ProfileRoleResonancePageReadAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        page_index = _int_param(params, "page_index", 1, minimum=1)
        role_names = _role_targets_from_params(params)
        state = _role_resonance_state()
        run_id = str(state.get("profile_read_run_id") or "")
        started_at = time.perf_counter()
        _append_user_log(
            ROLE_RESONANCE_TASK_ENTRY,
            f"角色共振第 {page_index} 页开始解析",
            run_id=run_id,
            level="info",
            event="role_resonance_page_read_started",
            data={"page_index": page_index},
        )
        try:
            detail = getattr(argv, "reco_detail", None)
            texts = _ocr_texts_from_detail(detail)
            entries = _ocr_entries_from_detail(detail)
            image = _role_page_image_from_context(context, page_index, detail, run_id) if entries else None
            payload = _parse_role_resonance_page(
                page_index=page_index,
                role_names=role_names,
                texts=texts,
                entries=entries,
                image=image,
            )
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            payload["elapsed_ms"] = elapsed_ms
            _json_payload("profile_role_resonance_page_read", payload)
            if elapsed_ms >= 1800:
                _append_user_log(
                    ROLE_RESONANCE_TASK_ENTRY,
                    f"角色共振第 {page_index} 页解析耗时 {elapsed_ms}ms，Agent 超时过低时可能跳页",
                    run_id=run_id,
                    level="warning",
                    event="role_resonance_page_read_slow",
                    data={"page_index": page_index, "elapsed_ms": elapsed_ms},
                )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            payload = {
                "ok": False,
                "page_index": page_index,
                "elapsed_ms": elapsed_ms,
                "error": f"{type(exc).__name__}: {exc}",
            }
            _append_user_log(
                ROLE_RESONANCE_TASK_ENTRY,
                f"角色共振第 {page_index} 页解析异常：{payload['error']}",
                run_id=run_id,
                level="error",
                event="role_resonance_page_read_failed",
                data={"page_index": page_index, "elapsed_ms": elapsed_ms, "traceback": traceback.format_exc()},
            )
            _json_payload("profile_role_resonance_page_read_failed", payload)
        return True


@AgentServer.custom_action("profile_role_resonance_should_continue")
class ProfileRoleResonanceShouldContinueAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        try:
            page_index = int(params.get("page_index") or 1)
        except (TypeError, ValueError):
            page_index = 1
        try:
            stale_limit = max(1, int(params.get("stale_limit") or CREW_SCROLL_STALE_LIMIT))
        except (TypeError, ValueError):
            stale_limit = CREW_SCROLL_STALE_LIMIT
        try:
            max_pages = max(1, int(params.get("max_pages") or CREW_SCAN_PAGE_COUNT))
        except (TypeError, ValueError):
            max_pages = CREW_SCAN_PAGE_COUNT
        scan_mode = str(params.get("scan_mode") or "").strip()
        role_names = _role_targets_from_params(params)
        payload = _role_resonance_continue_state(
            page_index,
            role_names=role_names,
            stale_limit=stale_limit,
            max_pages=max_pages,
            scan_mode=scan_mode,
        )
        _json_payload("profile_role_resonance_should_continue", payload)
        return bool(payload.get("ok"))


@AgentServer.custom_action("profile_role_resonance_complete")
class ProfileRoleResonanceCompleteAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        try:
            params = _argv_param(argv)
            role_names = _role_targets_from_params(params)
            scan_mode = str(params.get("scan_mode") or "").strip()
            payload = _complete_role_resonance_read(role_names, scan_mode=scan_mode)
            _json_payload("profile_role_resonance_complete", payload)
            return True
        except Exception as exc:
            run_id = str(_role_resonance_state().get("profile_read_run_id") or "")
            _append_user_log(
                ROLE_RESONANCE_TASK_ENTRY,
                f"角色共振收尾异常：{type(exc).__name__}: {exc}",
                run_id=run_id,
                level="warning",
                event="role_resonance_complete_failed",
                data={"traceback": traceback.format_exc(limit=8)},
            )
            return False


@AgentServer.custom_action("profile_city_unlock_probe")
class ProfileCityUnlockProbeAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        city = str(params.get("city") or "").strip()
        reset = bool(params.get("reset"))
        texts = _ocr_texts(argv)
        payload = _record_city_unlock_probe(city, texts, reset=reset)
        _json_payload("profile_city_unlock_probe", payload)
        return True


@AgentServer.custom_action("profile_city_unlock_should_probe")
class ProfileCityUnlockShouldProbeAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        city = str(params.get("city") or "").strip()
        probe_mode = str(params.get("probe_mode") or "missing_unknown").strip()
        payload = _city_unlock_should_probe(city, reset=bool(params.get("reset")), probe_mode=probe_mode)
        _json_payload("profile_city_unlock_should_probe", payload)
        return bool(payload.get("ok"))


@AgentServer.custom_action("profile_city_unlock_move_to_city")
class ProfileCityUnlockMoveToCityAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        city = str(params.get("city") or params.get("destination_city") or "").strip()
        state = _city_unlock_state(reset=bool(params.get("reset")))
        run_id = str(state.get("profile_read_run_id") or "")
        try:
            city_index = CITY_UNLOCK_TARGETS.index(city) + 1
        except ValueError:
            city_index = len(state.get("city_unlock_probe") or {}) + 1
        if city:
            _append_user_log(
                CITY_UNLOCK_TASK_ENTRY,
                f"正在定位城市：{city} ({city_index}/{len(CITY_UNLOCK_TARGETS)})",
                run_id=run_id,
                event="city_unlock_locating",
                data={"city": city, "city_index": city_index, "target_count": len(CITY_UNLOCK_TARGETS)},
            )
        try:
            payload = destination_map_vicinity_probe(context, {**params, "destination_city": city})
        except Exception as exc:
            payload = {
                "ok": False,
                "city": city,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=6),
            }
        if city:
            if payload.get("ok"):
                _append_user_log(
                    CITY_UNLOCK_TASK_ENTRY,
                    f"已打开城市面板：{city}",
                    run_id=run_id,
                    event="city_unlock_panel_opened",
                    data={"city": city, "reason": payload.get("reason")},
                )
            else:
                _append_user_log(
                    CITY_UNLOCK_TASK_ENTRY,
                    f"城市定位未确认：{city}，将继续进入识别兜底",
                    run_id=run_id,
                    level="warning",
                    event="city_unlock_locate_unconfirmed",
                    data={"city": city, "reason": payload.get("reason"), "error": payload.get("error")},
                )
        _json_payload("profile_city_unlock_move_to_city", payload)
        return True


@AgentServer.custom_action("profile_city_unlock_complete")
class ProfileCityUnlockCompleteAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        payload = _complete_city_unlock_read()
        _json_payload("profile_city_unlock_complete", payload)
        return True


@AgentServer.custom_action("manual_two_city_business_calculate")
class ManualTwoCityBusinessCalculateAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = {**_manual_two_city_state(), **_argv_param(argv)}
        run_id = f"manual-two-city-{int(time.time())}"
        start_city = str(params.get("manual_start_city") or params.get("start_city") or "").strip()
        target_city = str(params.get("manual_target_city") or params.get("target_city") or "").strip()
        uid = str(params.get("uid") or "").strip()
        start_book = _int_param(params, "start_book", 4, minimum=0)
        target_book = _int_param(params, "target_book", 0, minimum=0)
        start_bargain_percent = _int_param(
            params,
            "start_bargain_percent",
            _int_param(params, "start_haggle_percent", 20, minimum=0),
            minimum=0,
        )
        start_raise_percent = _int_param(
            params,
            "start_raise_percent",
            _int_param(params, "start_haggle_percent", 20, minimum=0),
            minimum=0,
        )
        target_bargain_percent = _int_param(
            params,
            "target_bargain_percent",
            _int_param(params, "target_haggle_percent", 0, minimum=0),
            minimum=0,
        )
        target_raise_percent = _int_param(
            params,
            "target_raise_percent",
            _int_param(params, "target_haggle_percent", 0, minimum=0),
            minimum=0,
        )
        run_mode = _manual_two_city_run_mode(params.get("run_mode"))
        account_read_mode = _manual_two_city_account_read_mode(params.get("account_profile_read_mode"))
        smart_scan_interval = _manual_two_city_smart_scan_interval(params.get("account_profile_smart_scan_interval"))
        run_mode_label = "跑到疲劳耗尽" if run_mode == MANUAL_TWO_CITY_RUN_MODE_UNTIL_FATIGUE_EXHAUSTED else "跑 1 轮"
        account_read_mode_label = {
            MANUAL_TWO_CITY_ACCOUNT_READ_SMART: "智能读取",
            MANUAL_TWO_CITY_ACCOUNT_READ_FULL: "全部读取",
            MANUAL_TWO_CITY_ACCOUNT_READ_NONE: "不读取",
        }.get(account_read_mode, "智能读取")
        smart_scan_interval_label = _manual_two_city_smart_scan_interval_label(smart_scan_interval)
        manual_params = {
            "start_city": start_city,
            "target_city": target_city,
            "uid": uid,
            "start_book": start_book,
            "target_book": target_book,
            "start_bargain_percent": start_bargain_percent,
            "start_raise_percent": start_raise_percent,
            "target_bargain_percent": target_bargain_percent,
            "target_raise_percent": target_raise_percent,
        }

        _start_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            run_id,
            (
                f"开始计算手动双城跑商（{run_mode_label}，账号配置{account_read_mode_label}）：{start_city or '-'} "
                f"(书 {start_book}，砍价 {start_bargain_percent}%，抬价 {start_raise_percent}%) -> "
                f"{target_city or '-'} (书 {target_book}，砍价 {target_bargain_percent}%，抬价 {target_raise_percent}%)"
            ),
        )
        try:
            result = calculate_manual_two_city_trade(
                start_city=start_city,
                target_city=target_city,
                uid=uid,
                start_book=start_book,
                target_book=target_book,
                start_bargain_percent=start_bargain_percent,
                start_raise_percent=start_raise_percent,
                target_bargain_percent=target_bargain_percent,
                target_raise_percent=target_raise_percent,
                allow_default_account=True,
            )
            state = _manual_two_city_state()
            state["task_entry"] = MANUAL_TWO_CITY_TASK_ENTRY
            state["auto_route_enabled"] = False
            state["auto_route_params"] = {}
            state["result"] = result
            state["active_leg_index"] = 0
            state["selected_buy_goods"] = []
            state["manual_params"] = manual_params
            state["run_id"] = run_id
            state["run_mode"] = run_mode
            state["account_profile_read_mode"] = account_read_mode
            state["account_profile_smart_scan_interval"] = smart_scan_interval
            state["completed_rounds"] = 0
            state["strength_recovery_stop_pending"] = False
            state["product_scan_completed_cities"] = []
            state["transient_product_status_by_city"] = {}
            _manual_two_city_reset_travel_stall_state(state, reset_restart_count=True)
            output_path = save_manual_two_city_result(result, task_entry=MANUAL_TWO_CITY_TASK_ENTRY)
            summary = result.get("summary") or {}
            profit = summary.get("profit")
            reference_profit = summary.get("reference_profit")
            tired = summary.get("tired")
            restock = summary.get("restock")
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                (
                    f"手动双城预期收益：利润 {profit}，参考利润 {reference_profit}，"
                    f"疲劳 {tired}，进货书 {restock}"
                ),
                run_id=run_id,
                event="manual_two_city_business_calculated",
                data={
                    "uid": result.get("uid"),
                    "start_city": result.get("start_city"),
                    "target_city": result.get("target_city"),
                    "output_path": str(output_path),
                    "summary": summary,
                },
            )
            if result.get("used_default_account_config"):
                suffix = "回到主界面后会读取真实账号配置并重算。" if account_read_mode != MANUAL_TWO_CITY_ACCOUNT_READ_NONE else "本轮已选择不读取账号配置，将继续使用默认配置。"
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    f"未找到账号配置，先使用默认配置临时计算：货仓 1016、城市商品全开、乘员共振按满级处理；{suffix}",
                    run_id=run_id,
                    level="warning",
                    event="manual_two_city_business_default_account_used",
                    data={
                        "default_account_cargo_capacity": result.get("default_account_cargo_capacity"),
                        "account_profile_read_mode": account_read_mode,
                        "account_profile_smart_scan_interval": smart_scan_interval,
                    },
                )
            if account_read_mode == MANUAL_TWO_CITY_ACCOUNT_READ_SMART:
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    f"账号配置智能读取间隔：{smart_scan_interval_label}。",
                    run_id=run_id,
                    event="manual_two_city_account_profile_smart_scan_interval",
                    data={"interval": smart_scan_interval},
                )
            for index, leg in enumerate(summary.get("legs") or [], start=1):
                goods = "、".join(str(item) for item in leg.get("goods") or [])
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    (
                        f"第 {index} 段 {leg.get('buy_city')} -> {leg.get('sell_city')}："
                        f"利润 {leg.get('profit')}，货物 {goods or '-'}"
                    ),
                    run_id=run_id,
                    event="manual_two_city_business_leg",
                    data={"leg": leg},
                )
            _json_payload("manual_two_city_business_calculate", {"ok": True, "output_path": str(output_path)})
            return True
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"手动双城跑商计算失败：{error}",
                run_id=run_id,
                level="error",
                event="manual_two_city_business_failed",
                data={"params": params, "traceback": traceback.format_exc(limit=8)},
            )
            _json_payload("manual_two_city_business_calculate_failed", {"ok": False, "error": error})
            return False


@AgentServer.custom_action("auto_two_city_business_calculate")
class AutoTwoCityBusinessCalculateAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = {**_manual_two_city_state(), **_argv_param(argv)}
        run_id = f"auto-two-city-{int(time.time())}"
        uid = str(params.get("uid") or "").strip()
        priority_cities = _manual_two_city_collect_city_options(params, "priority_city_", "priority_cities")
        exclude_cities = _manual_two_city_collect_city_options(params, "exclude_city_", "exclude_cities")
        max_restock = _int_param(params, "max_restock", 6, minimum=0)
        wulinyuan_priority = str(params.get("wulinyuan_priority") or "total").strip() or "total"
        run_mode = _manual_two_city_run_mode(params.get("run_mode"))
        account_read_mode = _manual_two_city_account_read_mode(params.get("account_profile_read_mode"))
        smart_scan_interval = _manual_two_city_smart_scan_interval(params.get("account_profile_smart_scan_interval"))
        run_mode_label = "跑到疲劳耗尽" if run_mode == MANUAL_TWO_CITY_RUN_MODE_UNTIL_FATIGUE_EXHAUSTED else "跑 1 轮"
        account_read_mode_label = {
            MANUAL_TWO_CITY_ACCOUNT_READ_SMART: "智能读取",
            MANUAL_TWO_CITY_ACCOUNT_READ_FULL: "全部读取",
            MANUAL_TWO_CITY_ACCOUNT_READ_NONE: "不读取",
        }.get(account_read_mode, "智能读取")
        smart_scan_interval_label = _manual_two_city_smart_scan_interval_label(smart_scan_interval)
        auto_params = {
            "uid": uid,
            "priority_cities": priority_cities,
            "exclude_cities": exclude_cities,
            "max_restock": max_restock,
            "wulinyuan_priority": wulinyuan_priority,
        }

        _start_user_log(
            AUTO_TWO_CITY_TASK_ENTRY,
            run_id,
            (
                f"开始计算自动双城跑商（{run_mode_label}，账号配置{account_read_mode_label}）："
                f"优先城市 {('、'.join(priority_cities) if priority_cities else '无')}，"
                f"排除城市 {('、'.join(exclude_cities) if exclude_cities else '无')}，"
                f"全程进货书上限 {max_restock}，武林源优先级 {wulinyuan_priority}。"
            ),
        )
        try:
            result = calculate_auto_two_city_trade(
                uid=uid,
                priority_cities=priority_cities,
                exclude_cities=exclude_cities,
                max_restock=max_restock,
                wulinyuan_priority=wulinyuan_priority,
                allow_default_account=True,
            )
            state = _manual_two_city_state()
            state["task_entry"] = AUTO_TWO_CITY_TASK_ENTRY
            state["auto_route_enabled"] = True
            state["auto_route_params"] = auto_params
            state["result"] = result
            state["active_leg_index"] = 0
            state["selected_buy_goods"] = []
            state["manual_params"] = {
                "start_city": result.get("start_city"),
                "target_city": result.get("target_city"),
                "uid": result.get("uid") or uid,
                "start_book": result.get("start_book", 0),
                "target_book": result.get("target_book", 0),
                "start_bargain_percent": result.get("start_bargain_percent", 0),
                "start_raise_percent": result.get("start_raise_percent", 0),
                "target_bargain_percent": result.get("target_bargain_percent", 0),
                "target_raise_percent": result.get("target_raise_percent", 0),
            }
            state["manual_start_city"] = result.get("start_city")
            state["manual_target_city"] = result.get("target_city")
            state["start_book"] = result.get("start_book", 0)
            state["target_book"] = result.get("target_book", 0)
            state["start_bargain_percent"] = result.get("start_bargain_percent", 0)
            state["start_raise_percent"] = result.get("start_raise_percent", 0)
            state["target_bargain_percent"] = result.get("target_bargain_percent", 0)
            state["target_raise_percent"] = result.get("target_raise_percent", 0)
            state["run_id"] = run_id
            state["run_mode"] = run_mode
            state["account_profile_read_mode"] = account_read_mode
            state["account_profile_smart_scan_interval"] = smart_scan_interval
            state["completed_rounds"] = 0
            state["strength_recovery_stop_pending"] = False
            state["product_scan_completed_cities"] = []
            state["transient_product_status_by_city"] = {}
            _manual_two_city_reset_travel_stall_state(state, reset_restart_count=True)
            output_path = save_manual_two_city_result(result, task_entry=AUTO_TWO_CITY_TASK_ENTRY)
            summary = result.get("summary") or {}
            _append_user_log(
                AUTO_TWO_CITY_TASK_ENTRY,
                (
                    f"自动双城规划完成：{result.get('start_city')} <-> {result.get('target_city')}，"
                    f"利润 {summary.get('profit')}，参考利润 {summary.get('reference_profit')}，"
                    f"疲劳 {summary.get('tired')}，进货书 {summary.get('restock')}。"
                ),
                run_id=run_id,
                event="auto_two_city_business_calculated",
                data={
                    "uid": result.get("uid"),
                    "output_path": str(output_path),
                    "auto_params": auto_params,
                    "summary": summary,
                },
            )
            if result.get("used_default_account_config"):
                suffix = "回到主界面后会读取真实账号配置并重新自动规划。" if account_read_mode != MANUAL_TWO_CITY_ACCOUNT_READ_NONE else "本轮已选择不读取账号配置，将继续使用默认配置。"
                _append_user_log(
                    AUTO_TWO_CITY_TASK_ENTRY,
                    f"未找到账号配置，先使用默认配置临时规划：货仓 1016、城市商品全开、乘员共振按满级处理；{suffix}",
                    run_id=run_id,
                    level="warning",
                    event="auto_two_city_business_default_account_used",
                    data={
                        "default_account_cargo_capacity": result.get("default_account_cargo_capacity"),
                        "account_profile_read_mode": account_read_mode,
                        "account_profile_smart_scan_interval": smart_scan_interval,
                    },
                )
            if account_read_mode == MANUAL_TWO_CITY_ACCOUNT_READ_SMART:
                _append_user_log(
                    AUTO_TWO_CITY_TASK_ENTRY,
                    f"账号配置智能读取间隔：{smart_scan_interval_label}。",
                    run_id=run_id,
                    event="manual_two_city_account_profile_smart_scan_interval",
                    data={"interval": smart_scan_interval},
                )
            for index, leg in enumerate(summary.get("legs") or [], start=1):
                goods = "、".join(str(item) for item in leg.get("goods") or [])
                _append_user_log(
                    AUTO_TWO_CITY_TASK_ENTRY,
                    (
                        f"规划第 {index} 段 {leg.get('buy_city')} -> {leg.get('sell_city')}："
                        f"书 {leg.get('restock')}，砍/抬价 {'开' if leg.get('uses_haggle') else '关'}，"
                        f"利润 {leg.get('profit')}，货物 {goods or '-'}"
                    ),
                    run_id=run_id,
                    event="auto_two_city_business_leg",
                    data={"leg": leg},
                )
            _json_payload("auto_two_city_business_calculate", {"ok": True, "output_path": str(output_path)})
            return True
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            _append_user_log(
                AUTO_TWO_CITY_TASK_ENTRY,
                f"自动双城跑商规划失败：{error}",
                run_id=run_id,
                level="error",
                event="auto_two_city_business_failed",
                data={"params": params, "traceback": traceback.format_exc(limit=8)},
            )
            _json_payload("auto_two_city_business_calculate_failed", {"ok": False, "error": error})
            return False


def _fatigue_recovery_defaults() -> dict[str, Any]:
    return {
        "use_drink": False,
        "use_bento": False,
        "use_fatigue_medicine": False,
        "lollipop_use_limit": 0,
        "gum_use_limit": 0,
        "cactus_candy_use_limit": 0,
        "huashi_use_limit": 0,
        "used": {},
        "unavailable": {},
        "pending": {},
        "skip_logged": {},
        "huashi_total_cost": 0,
        "huashi_unknown_cost_count": 0,
        "run_id": "",
    }


def _fatigue_recovery_state(reset: bool = False) -> dict[str, Any]:
    global _FATIGUE_RECOVERY_STATE
    if reset or not _FATIGUE_RECOVERY_STATE:
        _FATIGUE_RECOVERY_STATE = _fatigue_recovery_defaults()
    return _FATIGUE_RECOVERY_STATE


def _fatigue_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enable", "enabled", "启用", "开启", "是", "使用"}:
        return True
    if text in {"0", "false", "no", "off", "disable", "disabled", "禁用", "关闭", "否", "不使用"}:
        return False
    return default


def _fatigue_int(value: Any, default: int = 0) -> int:
    try:
        return int(value if value is not None and value != "" else default)
    except (TypeError, ValueError):
        return default


def _fatigue_normalize_limit(value: Any, *, huashi: bool = False) -> int:
    limit = _fatigue_int(value, 0)
    if limit < 0:
        return -1
    if huashi:
        return min(max(0, limit), HUASHI_MAX_USE_LIMIT)
    return max(0, limit)


def _fatigue_resource_used_count(state: dict[str, Any], resource: str) -> int:
    used = state.setdefault("used", {})
    return int(used.get(resource) or 0)


def _fatigue_resource_limit(state: dict[str, Any], resource: str, resource_type: str) -> int:
    if resource_type == "huashi":
        return _fatigue_normalize_limit(state.get("huashi_use_limit"), huashi=True)
    key = FATIGUE_MEDICINE_RESOURCES.get(resource, {}).get("limit_key")
    if key:
        return _fatigue_normalize_limit(state.get(key))
    return -1


def _fatigue_resource_maybe_allowed(state: dict[str, Any], resource: str, resource_type: str) -> bool:
    if resource_type in {"medicine", "huashi"}:
        if not state.get("use_fatigue_medicine"):
            return False
        if state.setdefault("unavailable", {}).get(resource):
            return False
        limit = _fatigue_resource_limit(state, resource, resource_type)
        used = _fatigue_resource_used_count(state, resource)
        if limit == 0:
            return False
        if resource_type == "huashi" and used >= HUASHI_MAX_USE_LIMIT:
            return False
        if limit > 0 and used >= limit:
            return False
        return True
    return False


def _fatigue_limit_text(limit: int, *, huashi: bool = False) -> str:
    if limit < 0:
        return "不限" if not huashi else f"不限（最高 {HUASHI_MAX_USE_LIMIT} 次）"
    if limit == 0:
        return "不使用"
    return f"{limit} 次"


def _fatigue_log_skip_once(state: dict[str, Any], resource: str, reason: str) -> None:
    skip_logged = state.setdefault("skip_logged", {})
    key = f"{resource}:{reason}"
    if skip_logged.get(key):
        return
    skip_logged[key] = True
    _append_user_log(
        _manual_two_city_current_task_entry(),
        f"跳过 {resource}：{reason}",
        event="fatigue_recovery_resource_skipped",
        data={"resource": resource, "reason": reason},
    )


def _fatigue_option_config_paths() -> list[Path]:
    option_paths: list[Path] = []
    for path in (
        PROJECT_ROOT / "config" / "mxu-MaaResonance.json",
        PROJECT_ROOT / "install" / "config" / "mxu-MaaResonance.json",
        PROJECT_ROOT.parent / "install" / "config" / "mxu-MaaResonance.json",
    ):
        if path not in option_paths:
            option_paths.append(path)
    return option_paths


def _mxu_config_api_ports() -> list[int]:
    ports: list[int] = []
    for option_path in _fatigue_option_config_paths():
        if not option_path.exists():
            continue
        try:
            data = json.loads(option_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        settings = data.get("settings", {}) if isinstance(data, dict) else {}
        try:
            port = int(settings.get("webServerPort") or 0)
        except (TypeError, ValueError):
            port = 0
        if port > 0 and port not in ports:
            ports.append(port)
    for offset in range(MXU_WEB_API_MAX_PORT_ATTEMPTS):
        port = MXU_WEB_API_DEFAULT_PORT + offset
        if port not in ports:
            ports.append(port)
    return ports


def _mxu_http_json(
    url: str,
    *,
    method: str = "GET",
    payload: Any | None = None,
    timeout: float = 0.8,
) -> Any:
    headers = {"Accept": "application/json"}
    data: bytes | None = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _mxu_project_paths() -> set[str]:
    paths: set[str] = set()
    for path in (
        PROJECT_ROOT,
        PROJECT_ROOT / "install",
        PROJECT_ROOT.parent / "install",
    ):
        try:
            if path.exists():
                paths.add(str(path.resolve()).lower())
        except Exception:
            paths.add(str(path).lower())
    return paths


def _mxu_interface_matches_project(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    interface = payload.get("interface")
    project_name = interface.get("name") if isinstance(interface, dict) else ""
    if str(project_name or "").strip() != "MaaResonance":
        return False
    base_path = str(payload.get("basePath") or payload.get("dataPath") or "").strip()
    if not base_path:
        return True
    try:
        normalized = str(Path(base_path).resolve()).lower()
    except Exception:
        normalized = base_path.lower()
    project_paths = _mxu_project_paths()
    if not project_paths:
        return True
    return (
        normalized in project_paths
        or normalized.endswith("\\maaresonance\\install")
        or normalized.endswith("/maaresonance/install")
    )


def _mxu_find_config_api() -> tuple[str | None, dict[str, Any]]:
    global _MXU_CONFIG_API_BASE_URL
    errors: list[dict[str, Any]] = []
    candidate_bases: list[str] = []
    if _MXU_CONFIG_API_BASE_URL:
        candidate_bases.append(_MXU_CONFIG_API_BASE_URL)
    for port in _mxu_config_api_ports():
        base_url = f"http://127.0.0.1:{port}/api"
        if base_url not in candidate_bases:
            candidate_bases.append(base_url)

    for base_url in candidate_bases:
        try:
            payload = _mxu_http_json(f"{base_url}/interface", timeout=0.6)
        except Exception as exc:
            errors.append({"base_url": base_url, "error": f"{type(exc).__name__}: {exc}"})
            if base_url == _MXU_CONFIG_API_BASE_URL:
                _MXU_CONFIG_API_BASE_URL = None
            continue
        if _mxu_interface_matches_project(payload):
            _MXU_CONFIG_API_BASE_URL = base_url
            return base_url, {
                "available": True,
                "base_url": base_url,
                "interface": {
                    "basePath": payload.get("basePath") if isinstance(payload, dict) else "",
                    "dataPath": payload.get("dataPath") if isinstance(payload, dict) else "",
                    "project": ((payload.get("interface") or {}).get("name") if isinstance(payload, dict) else ""),
                },
                "errors": errors,
            }
        errors.append({"base_url": base_url, "error": "project_mismatch", "payload": payload})
    return None, {"available": False, "errors": errors}


def _fatigue_read_option_config_values_from_payload(
    data: Any,
    *,
    task_name: str,
    option_name: str,
    path_label: str,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    instances = data.get("instances", []) if isinstance(data, dict) else []
    for instance in instances:
        tasks = instance.get("tasks", []) if isinstance(instance, dict) else []
        for task in tasks:
            if not isinstance(task, dict) or task.get("taskName") != task_name:
                continue
            option_values = task.get("optionValues", {})
            option = option_values.get(option_name, {}) if isinstance(option_values, dict) else {}
            values = option.get("values", {}) if isinstance(option, dict) else {}
            if isinstance(values, dict):
                snapshots.append({"path": path_label, "values": dict(values)})
    return snapshots


def _fatigue_read_option_config_values_via_mxu_api(
    *,
    task_name: str,
    option_name: str,
) -> dict[str, Any]:
    base_url, api_info = _mxu_find_config_api()
    if not base_url:
        return {
            "available": False,
            "paths": [],
            "snapshots": [],
            "errors": api_info.get("errors", []),
        }
    endpoint = f"{base_url}/config"
    try:
        data = _mxu_http_json(endpoint, timeout=0.8)
    except Exception as exc:
        return {
            "available": False,
            "paths": [endpoint],
            "snapshots": [],
            "errors": [{"path": endpoint, "error": f"{type(exc).__name__}: {exc}"}],
            "api": api_info,
        }
    return {
        "available": True,
        "via": "mxu_api",
        "paths": [endpoint],
        "snapshots": _fatigue_read_option_config_values_from_payload(
            data,
            task_name=task_name,
            option_name=option_name,
            path_label=endpoint,
        ),
        "errors": [],
        "api": api_info,
    }


def _fatigue_decrement_option_config_limit_via_mxu_api(
    resource: str,
    resource_type: str,
    count: int,
    *,
    task_name: str,
    option_name: str,
) -> dict[str, Any]:
    key = _fatigue_limit_key_for_resource(resource, resource_type)
    decrement = max(1, int(count or 1))
    base_url, api_info = _mxu_find_config_api()
    if not base_url:
        return {
            "available": False,
            "updated": False,
            "reason": "mxu_api_unavailable",
            "resource": resource,
            "resource_type": resource_type,
            "count": decrement,
            "key": key,
            "paths": [],
            "updates": [],
            "observations": [],
            "errors": api_info.get("errors", []),
        }
    endpoint = f"{base_url}/config"
    if not key:
        return {
            "available": True,
            "via": "mxu_api",
            "updated": False,
            "reason": "no_limit_key",
            "resource": resource,
            "resource_type": resource_type,
            "count": decrement,
            "paths": [endpoint],
            "updates": [],
            "observations": [],
            "errors": [],
            "api": api_info,
        }
    try:
        data = _mxu_http_json(endpoint, timeout=0.8)
    except Exception as exc:
        return {
            "available": False,
            "updated": False,
            "resource": resource,
            "resource_type": resource_type,
            "count": decrement,
            "key": key,
            "paths": [endpoint],
            "updates": [],
            "observations": [],
            "errors": [{"path": endpoint, "error": f"{type(exc).__name__}: {exc}"}],
            "api": api_info,
        }

    changed = False
    updates: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    instances = data.get("instances", []) if isinstance(data, dict) else []
    for instance in instances:
        tasks = instance.get("tasks", []) if isinstance(instance, dict) else []
        for task in tasks:
            if not isinstance(task, dict) or task.get("taskName") != task_name:
                continue
            option_values = task.get("optionValues", {})
            option = option_values.get(option_name, {}) if isinstance(option_values, dict) else {}
            values = option.get("values", {}) if isinstance(option, dict) else {}
            if not isinstance(values, dict) or key not in values:
                continue
            raw_value = str(values.get(key, "")).strip()
            try:
                current = int(raw_value)
            except ValueError:
                observations.append({"path": endpoint, "key": key, "value": raw_value, "reason": "not_int"})
                continue
            if current <= 0:
                observations.append({"path": endpoint, "key": key, "value": current, "reason": "unlimited_or_disabled"})
                continue
            new_value = max(0, current - decrement)
            if new_value != current:
                values[key] = str(new_value)
                changed = True
                updates.append(
                    {
                        "path": endpoint,
                        "task_name": task_name,
                        "option_name": option_name,
                        "key": key,
                        "old_value": current,
                        "new_value": new_value,
                    }
                )
    errors: list[dict[str, str]] = []
    if changed:
        try:
            _mxu_http_json(endpoint, method="PUT", payload=data, timeout=1.2)
        except Exception as exc:
            errors.append({"path": endpoint, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "available": True,
        "via": "mxu_api",
        "updated": bool(updates) and not errors,
        "resource": resource,
        "resource_type": resource_type,
        "count": decrement,
        "key": key,
        "paths": [endpoint],
        "updates": [] if errors else updates,
        "pending_updates": updates if errors else [],
        "observations": observations,
        "errors": errors,
        "api": api_info,
    }


def _fatigue_write_option_config_values_via_mxu_api(
    *,
    task_name: str,
    option_name: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    normalized_values = {
        str(key): str(value)
        for key, value in (values or {}).items()
        if str(key).strip()
    }
    base_url, api_info = _mxu_find_config_api()
    if not base_url:
        return {
            "available": False,
            "updated": False,
            "reason": "mxu_api_unavailable",
            "paths": [],
            "updates": [],
            "observations": [],
            "errors": api_info.get("errors", []),
        }
    endpoint = f"{base_url}/config"
    if not normalized_values:
        return {
            "available": True,
            "via": "mxu_api",
            "updated": False,
            "reason": "empty_values",
            "paths": [endpoint],
            "updates": [],
            "observations": [],
            "errors": [],
            "api": api_info,
        }
    try:
        data = _mxu_http_json(endpoint, timeout=0.8)
    except Exception as exc:
        return {
            "available": False,
            "updated": False,
            "paths": [endpoint],
            "updates": [],
            "observations": [],
            "errors": [{"path": endpoint, "error": f"{type(exc).__name__}: {exc}"}],
            "api": api_info,
        }

    changed = False
    matched = False
    updates: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    instances = data.get("instances", []) if isinstance(data, dict) else []
    for instance in instances:
        tasks = instance.get("tasks", []) if isinstance(instance, dict) else []
        for task in tasks:
            if not isinstance(task, dict) or task.get("taskName") != task_name:
                continue
            option_values = task.get("optionValues", {})
            option = option_values.get(option_name, {}) if isinstance(option_values, dict) else {}
            current_values = option.get("values", {}) if isinstance(option, dict) else {}
            if not isinstance(current_values, dict):
                continue
            matched = True
            for key, value in normalized_values.items():
                if key not in current_values:
                    observations.append({"path": endpoint, "key": key, "reason": "missing_key"})
                    continue
                old_value = str(current_values.get(key, "")).strip()
                if old_value == value:
                    continue
                current_values[key] = value
                changed = True
                updates.append(
                    {
                        "path": endpoint,
                        "task_name": task_name,
                        "option_name": option_name,
                        "key": key,
                        "old_value": old_value,
                        "new_value": value,
                    }
                )
    if not matched:
        observations.append({"path": endpoint, "option_name": option_name, "reason": "missing_option"})
    errors: list[dict[str, str]] = []
    if changed:
        try:
            _mxu_http_json(endpoint, method="PUT", payload=data, timeout=1.2)
        except Exception as exc:
            errors.append({"path": endpoint, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "available": True,
        "via": "mxu_api",
        "updated": bool(updates) and not errors,
        "paths": [endpoint],
        "updates": [] if errors else updates,
        "pending_updates": updates if errors else [],
        "observations": observations,
        "errors": errors,
        "api": api_info,
    }


def _fatigue_write_option_config_values_to_files(
    *,
    task_name: str,
    option_name: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    normalized_values = {
        str(key): str(value)
        for key, value in (values or {}).items()
        if str(key).strip()
    }
    existing_paths = [path for path in _fatigue_option_config_paths() if path.exists()]
    updates: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    if not normalized_values:
        return {
            "updated": False,
            "reason": "empty_values",
            "paths": [str(path) for path in existing_paths],
            "updates": updates,
            "observations": observations,
            "errors": errors,
        }

    for option_path in existing_paths:
        try:
            data = json.loads(option_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append({"path": str(option_path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        changed = False
        matched = False
        for instance in data.get("instances", []):
            tasks = instance.get("tasks", []) if isinstance(instance, dict) else []
            for task in tasks:
                if not isinstance(task, dict) or task.get("taskName") != task_name:
                    continue
                option_values = task.get("optionValues", {})
                option = option_values.get(option_name, {}) if isinstance(option_values, dict) else {}
                current_values = option.get("values", {}) if isinstance(option, dict) else {}
                if not isinstance(current_values, dict):
                    continue
                matched = True
                for key, value in normalized_values.items():
                    if key not in current_values:
                        observations.append({"path": str(option_path), "key": key, "reason": "missing_key"})
                        continue
                    old_value = str(current_values.get(key, "")).strip()
                    if old_value == value:
                        continue
                    current_values[key] = value
                    changed = True
                    updates.append(
                        {
                            "path": str(option_path),
                            "task_name": task_name,
                            "option_name": option_name,
                            "key": key,
                            "old_value": old_value,
                            "new_value": value,
                        }
                    )
        if not matched:
            observations.append({"path": str(option_path), "option_name": option_name, "reason": "missing_option"})
        if changed:
            try:
                option_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                errors.append({"path": str(option_path), "error": f"{type(exc).__name__}: {exc}"})
    return {
        "updated": bool(updates),
        "paths": [str(path) for path in existing_paths],
        "updates": updates,
        "observations": observations,
        "errors": errors,
    }


def _auto_two_city_normalize_city_cases(cities: Any) -> list[str]:
    valid_cities = set(load_city_names())
    normalized: list[str] = []
    for city in cities or []:
        name = normalize_city_name(str(city or "").strip())
        if not name or name not in valid_cities or name in normalized:
            continue
        normalized.append(name)
    return normalized


def _merge_checkbox_case_names(option: dict[str, Any], case_names: list[str]) -> tuple[list[str], list[str]]:
    current = option.get("caseNames") if isinstance(option, dict) else []
    merged: list[str] = []
    if isinstance(current, list):
        for name in current:
            text = str(name or "").strip()
            if text and text not in merged:
                merged.append(text)
    before = list(merged)
    for name in case_names:
        if name not in merged:
            merged.append(name)
    return before, merged


def _sync_auto_two_city_exclude_cities_in_config_payload(
    data: Any,
    case_names: list[str],
    *,
    path_label: str,
) -> tuple[bool, list[dict[str, Any]], list[dict[str, Any]]]:
    changed = False
    matched = False
    updates: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    instances = data.get("instances", []) if isinstance(data, dict) else []
    for instance in instances:
        tasks = instance.get("tasks", []) if isinstance(instance, dict) else []
        for task in tasks:
            if not isinstance(task, dict) or task.get("taskName") != AUTO_TWO_CITY_TASK_ENTRY:
                continue
            matched = True
            option_values = task.get("optionValues")
            if not isinstance(option_values, dict):
                option_values = {}
                task["optionValues"] = option_values
            option = option_values.get(AUTO_TWO_CITY_EXCLUDE_OPTION)
            if not isinstance(option, dict):
                option = {"type": "checkbox", "caseNames": []}
                option_values[AUTO_TWO_CITY_EXCLUDE_OPTION] = option
            option["type"] = "checkbox"
            before, merged = _merge_checkbox_case_names(option, case_names)
            if merged != before:
                option["caseNames"] = merged
                changed = True
                updates.append(
                    {
                        "path": path_label,
                        "task_name": AUTO_TWO_CITY_TASK_ENTRY,
                        "option_name": AUTO_TWO_CITY_EXCLUDE_OPTION,
                        "old_case_names": before,
                        "new_case_names": merged,
                        "added_case_names": [name for name in case_names if name not in before],
                    }
                )
    if not matched:
        observations.append({"path": path_label, "task_name": AUTO_TWO_CITY_TASK_ENTRY, "reason": "missing_task"})
    return changed, updates, observations


def _sync_auto_two_city_exclude_cities_via_mxu_api(case_names: list[str]) -> dict[str, Any]:
    base_url, api_info = _mxu_find_config_api()
    if not base_url:
        return {
            "available": False,
            "updated": False,
            "reason": "mxu_api_unavailable",
            "paths": [],
            "updates": [],
            "observations": [],
            "errors": api_info.get("errors", []),
        }
    endpoint = f"{base_url}/config"
    try:
        data = _mxu_http_json(endpoint, timeout=0.8)
    except Exception as exc:
        return {
            "available": False,
            "updated": False,
            "paths": [endpoint],
            "updates": [],
            "observations": [],
            "errors": [{"path": endpoint, "error": f"{type(exc).__name__}: {exc}"}],
            "api": api_info,
        }

    changed, updates, observations = _sync_auto_two_city_exclude_cities_in_config_payload(
        data,
        case_names,
        path_label=endpoint,
    )
    errors: list[dict[str, str]] = []
    if changed:
        try:
            _mxu_http_json(endpoint, method="PUT", payload=data, timeout=1.2)
        except Exception as exc:
            errors.append({"path": endpoint, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "available": True,
        "via": "mxu_api",
        "updated": bool(updates) and not errors,
        "paths": [endpoint],
        "updates": [] if errors else updates,
        "pending_updates": updates if errors else [],
        "observations": observations,
        "errors": errors,
        "api": api_info,
    }


def _sync_auto_two_city_exclude_cities(case_names: list[str]) -> dict[str, Any]:
    api_result = _sync_auto_two_city_exclude_cities_via_mxu_api(case_names)
    if api_result.get("available"):
        return api_result

    existing_paths = [path for path in _fatigue_option_config_paths() if path.exists()]
    updates: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for option_path in existing_paths:
        try:
            data = json.loads(option_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append({"path": str(option_path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        changed, path_updates, path_observations = _sync_auto_two_city_exclude_cities_in_config_payload(
            data,
            case_names,
            path_label=str(option_path),
        )
        updates.extend(path_updates)
        observations.extend(path_observations)
        if changed:
            try:
                option_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                errors.append({"path": str(option_path), "error": f"{type(exc).__name__}: {exc}"})
    return {
        "available": bool(existing_paths),
        "via": "config_file",
        "updated": bool(updates) and not errors,
        "paths": [str(path) for path in existing_paths],
        "updates": updates,
        "observations": observations,
        "errors": errors,
        "api_result": api_result,
    }


def _sync_auto_two_city_exclude_cities_from_unavailable(
    unavailable_cities: Any,
    *,
    run_id: str = "",
) -> dict[str, Any]:
    case_names = _auto_two_city_normalize_city_cases(unavailable_cities)
    if not case_names:
        return {"updated": False, "reason": "empty_unavailable_cities", "case_names": []}
    result = _sync_auto_two_city_exclude_cities(case_names)
    result["case_names"] = case_names
    added: list[str] = []
    for item in result.get("updates") or []:
        for name in item.get("added_case_names") or []:
            if name not in added:
                added.append(name)
    if added:
        _append_user_log(
            CITY_UNLOCK_TASK_ENTRY,
            f"城市开放读取：已同步 {len(added)} 个未开放城市到自动双城跑商排除城市：{'、'.join(added)}",
            run_id=run_id,
            level="info",
            event="auto_two_city_exclude_cities_synced",
            data={"added_cities": added, "sync_result": result},
        )
    elif result.get("errors"):
        _append_user_log(
            CITY_UNLOCK_TASK_ENTRY,
            "城市开放读取：同步未开放城市到自动双城跑商配置失败。",
            run_id=run_id,
            level="warning",
            event="auto_two_city_exclude_cities_sync_failed",
            data={"sync_result": result},
        )
    return result


def _fatigue_limit_key_for_resource(resource: str, resource_type: str) -> str:
    if resource_type == "huashi":
        return "huashi_use_limit"
    if resource_type == "medicine":
        return str(FATIGUE_MEDICINE_RESOURCES.get(resource, {}).get("limit_key") or "")
    return ""


def _fatigue_decrement_option_config_limit(
    resource: str,
    resource_type: str,
    count: int,
    *,
    task_name: str,
    option_name: str,
) -> dict[str, Any]:
    api_result = _fatigue_decrement_option_config_limit_via_mxu_api(
        resource,
        resource_type,
        count,
        task_name=task_name,
        option_name=option_name,
    )
    if api_result.get("available"):
        exact_values: dict[str, Any] = {}
        for update in (api_result.get("updates") or api_result.get("pending_updates") or []):
            if isinstance(update, dict) and update.get("key"):
                exact_values[str(update["key"])] = update.get("new_value")
        if exact_values:
            api_result["file_sync"] = _fatigue_write_option_config_values_to_files(
                task_name=task_name,
                option_name=option_name,
                values=exact_values,
            )
        return api_result

    key = _fatigue_limit_key_for_resource(resource, resource_type)
    decrement = max(1, int(count or 1))
    existing_paths = [path for path in _fatigue_option_config_paths() if path.exists()]
    if not key:
        return {
            "updated": False,
            "reason": "no_limit_key",
            "resource": resource,
            "resource_type": resource_type,
            "count": decrement,
            "paths": [str(path) for path in existing_paths],
        }

    updates: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for option_path in existing_paths:
        try:
            data = json.loads(option_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append({"path": str(option_path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        changed = False
        for instance in data.get("instances", []):
            tasks = instance.get("tasks", []) if isinstance(instance, dict) else []
            for task in tasks:
                if not isinstance(task, dict) or task.get("taskName") != task_name:
                    continue
                option_values = task.get("optionValues", {})
                option = option_values.get(option_name, {}) if isinstance(option_values, dict) else {}
                values = option.get("values", {}) if isinstance(option, dict) else {}
                if not isinstance(values, dict) or key not in values:
                    continue
                raw_value = str(values.get(key, "")).strip()
                try:
                    current = int(raw_value)
                except ValueError:
                    observations.append({"path": str(option_path), "key": key, "value": raw_value, "reason": "not_int"})
                    continue
                if current <= 0:
                    observations.append({"path": str(option_path), "key": key, "value": current, "reason": "unlimited_or_disabled"})
                    continue
                new_value = max(0, current - decrement)
                if new_value != current:
                    values[key] = str(new_value)
                    changed = True
                    updates.append(
                        {
                            "path": str(option_path),
                            "task_name": task_name,
                            "option_name": option_name,
                            "key": key,
                            "old_value": current,
                            "new_value": new_value,
                        }
                    )
        if changed:
            try:
                option_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                errors.append({"path": str(option_path), "error": f"{type(exc).__name__}: {exc}"})
    return {
        "updated": bool(updates),
        "resource": resource,
        "resource_type": resource_type,
        "count": decrement,
        "key": key,
        "paths": [str(path) for path in existing_paths],
        "updates": updates,
        "observations": observations,
        "errors": errors,
        "api_result": api_result,
    }


def _fatigue_config_decrement_note(result: dict[str, Any]) -> str:
    updates = result.get("updates") if isinstance(result.get("updates"), list) else []
    if not updates:
        return ""
    new_values: list[int] = []
    for item in updates:
        try:
            value = int(item.get("new_value"))
        except (TypeError, ValueError):
            continue
        if value not in new_values:
            new_values.append(value)
    if len(new_values) == 1:
        return f"，配置剩余 {new_values[0]} 次"
    return "，已同步递减配置"


def _fatigue_read_option_config_values(
    *,
    task_name: str,
    option_name: str,
) -> dict[str, Any]:
    api_result = _fatigue_read_option_config_values_via_mxu_api(
        task_name=task_name,
        option_name=option_name,
    )
    if api_result.get("available"):
        return api_result

    existing_paths = [path for path in _fatigue_option_config_paths() if path.exists()]
    snapshots: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for option_path in existing_paths:
        try:
            data = json.loads(option_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append({"path": str(option_path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        for instance in data.get("instances", []):
            tasks = instance.get("tasks", []) if isinstance(instance, dict) else []
            for task in tasks:
                if not isinstance(task, dict) or task.get("taskName") != task_name:
                    continue
                option_values = task.get("optionValues", {})
                option = option_values.get(option_name, {}) if isinstance(option_values, dict) else {}
                values = option.get("values", {}) if isinstance(option, dict) else {}
                if isinstance(values, dict):
                    snapshots.append({"path": str(option_path), "values": dict(values)})
    return {
        "paths": [str(path) for path in existing_paths],
        "snapshots": snapshots,
        "errors": errors,
        "api_result": api_result,
    }


def _fatigue_write_option_config_values(
    *,
    task_name: str,
    option_name: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    normalized_values = {
        str(key): str(value)
        for key, value in (values or {}).items()
        if str(key).strip()
    }
    api_result = _fatigue_write_option_config_values_via_mxu_api(
        task_name=task_name,
        option_name=option_name,
        values=normalized_values,
    )
    if api_result.get("available"):
        api_result["file_sync"] = _fatigue_write_option_config_values_to_files(
            task_name=task_name,
            option_name=option_name,
            values=normalized_values,
        )
        return api_result

    file_result = _fatigue_write_option_config_values_to_files(
        task_name=task_name,
        option_name=option_name,
        values=normalized_values,
    )
    file_result["api_result"] = api_result
    return file_result


def _fatigue_schedule_delayed_option_config_write(
    *,
    task_name: str,
    option_name: str,
    values: dict[str, Any],
    delays: list[float] | None = None,
) -> dict[str, Any]:
    normalized_values = {
        str(key): str(value)
        for key, value in (values or {}).items()
        if str(key).strip()
    }
    existing_paths = [path for path in _fatigue_option_config_paths() if path.exists()]
    if not normalized_values or not existing_paths:
        return {
            "scheduled": False,
            "reason": "empty_values_or_paths",
            "paths": [str(path) for path in existing_paths],
            "values": normalized_values,
        }
    payload = {
        "paths": [str(path) for path in existing_paths],
        "task_name": task_name,
        "option_name": option_name,
        "values": normalized_values,
        "delays": delays or [1.5, 4.0, 8.0],
    }
    code = (
        "import json,sys,time,pathlib;"
        "p=json.loads(sys.argv[1]);"
        "last=0;"
        "delays=p.get('delays') or [1.5,4,8];"
        "\nfor d in delays:"
        "\n    time.sleep(max(0,float(d)-last)); last=float(d)"
        "\n    for path_text in p.get('paths') or []:"
        "\n        path=pathlib.Path(path_text)"
        "\n        try:"
        "\n            data=json.loads(path.read_text(encoding='utf-8'))"
        "\n        except Exception:"
        "\n            continue"
        "\n        changed=False"
        "\n        for inst in data.get('instances',[]):"
        "\n            tasks=inst.get('tasks',[]) if isinstance(inst,dict) else []"
        "\n            for task in tasks:"
        "\n                if not isinstance(task,dict) or task.get('taskName')!=p.get('task_name'): continue"
        "\n                option_values=task.get('optionValues',{})"
        "\n                option=option_values.get(p.get('option_name'),{}) if isinstance(option_values,dict) else {}"
        "\n                values=option.get('values',{}) if isinstance(option,dict) else {}"
        "\n                if not isinstance(values,dict): continue"
        "\n                for key,value in (p.get('values') or {}).items():"
        "\n                    if key in values and str(values.get(key,''))!=str(value):"
        "\n                        values[key]=str(value); changed=True"
        "\n        if changed:"
        "\n            path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')"
    )
    try:
        popen_kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            creationflags = 0
            for flag_name in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS", "CREATE_BREAKAWAY_FROM_JOB"):
                creationflags |= int(getattr(subprocess, flag_name, 0) or 0)
            if creationflags:
                popen_kwargs["creationflags"] = creationflags
        process = subprocess.Popen(
            [sys.executable, "-c", code, json.dumps(payload, ensure_ascii=True)],
            **popen_kwargs,
        )
    except Exception as exc:
        if os.name == "nt" and popen_kwargs.get("creationflags"):
            try:
                process = subprocess.Popen(
                    [sys.executable, "-c", code, json.dumps(payload, ensure_ascii=True)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
            except Exception as fallback_exc:
                return {
                    "scheduled": False,
                    "error": f"{type(exc).__name__}: {exc}; fallback {type(fallback_exc).__name__}: {fallback_exc}",
                    "paths": [str(path) for path in existing_paths],
                    "values": normalized_values,
                }
        else:
            return {
                "scheduled": False,
                "error": f"{type(exc).__name__}: {exc}",
                "paths": [str(path) for path in existing_paths],
                "values": normalized_values,
            }
    try:
        pid = process.pid
    except Exception:
        pid = None
    return {
        "scheduled": True,
        "pid": pid,
        "paths": [str(path) for path in existing_paths],
        "values": normalized_values,
        "delays": delays or [1.5, 4.0, 8.0],
    }


def _fatigue_rewrite_option_config_values_with_retry(
    *,
    task_name: str,
    option_name: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    immediate = _fatigue_write_option_config_values(
        task_name=task_name,
        option_name=option_name,
        values=values,
    )
    if immediate.get("via") == "mxu_api" and immediate.get("available"):
        delayed = _fatigue_schedule_delayed_option_config_write(
            task_name=task_name,
            option_name=option_name,
            values=values,
            delays=[2.0, 8.0, 30.0, 120.0, 300.0, 900.0],
        )
        return {
            "immediate": immediate,
            "delayed": delayed,
        }
    delayed = _fatigue_schedule_delayed_option_config_write(
        task_name=task_name,
        option_name=option_name,
        values=values,
        delays=[2.0, 8.0, 30.0, 120.0, 300.0, 900.0],
    )
    return {"immediate": immediate, "delayed": delayed}


def _manual_two_city_reset_account_read_mode_to_smart() -> dict[str, Any]:
    task_entry = _manual_two_city_current_task_entry()
    existing_paths = [path for path in _fatigue_option_config_paths() if path.exists()]
    updates: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for option_path in existing_paths:
        try:
            data = json.loads(option_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append({"path": str(option_path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        changed = False
        for instance in data.get("instances", []):
            tasks = instance.get("tasks", []) if isinstance(instance, dict) else []
            for task in tasks:
                if not isinstance(task, dict) or task.get("taskName") != task_entry:
                    continue
                option_values = task.get("optionValues", {})
                if not isinstance(option_values, dict):
                    option_values = {}
                    task["optionValues"] = option_values
                option = option_values.get("ManualTwoCityAccountProfileReadMode")
                if not isinstance(option, dict):
                    option = {}
                    option_values["ManualTwoCityAccountProfileReadMode"] = option
                old_case = str(option.get("caseName") or "").strip()
                if old_case == MANUAL_TWO_CITY_ACCOUNT_READ_SMART:
                    observations.append({"path": str(option_path), "reason": "already_smart"})
                    continue
                option["type"] = "select"
                option["caseName"] = MANUAL_TWO_CITY_ACCOUNT_READ_SMART
                changed = True
                updates.append(
                    {
                        "path": str(option_path),
                        "task_name": task_entry,
                        "option_name": "ManualTwoCityAccountProfileReadMode",
                        "old_case": old_case,
                        "new_case": MANUAL_TWO_CITY_ACCOUNT_READ_SMART,
                    }
                )
        if changed:
            try:
                option_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                errors.append({"path": str(option_path), "error": f"{type(exc).__name__}: {exc}"})
    return {
        "updated": bool(updates),
        "paths": [str(path) for path in existing_paths],
        "updates": updates,
        "observations": observations,
        "errors": errors,
    }


def _manual_two_city_defaults() -> dict[str, Any]:
    return {
        "task_entry": MANUAL_TWO_CITY_TASK_ENTRY,
        "auto_route_enabled": False,
        "auto_route_params": {},
        "manual_start_city": "修格里城",
        "manual_target_city": "7号自由港",
        "account_profile_read_mode": MANUAL_TWO_CITY_ACCOUNT_READ_SMART,
        "account_profile_smart_scan_interval": MANUAL_TWO_CITY_SMART_SCAN_DAILY,
        "run_mode": MANUAL_TWO_CITY_RUN_MODE_ONE_ROUND,
        "start_book": 4,
        "target_book": 0,
        "start_bargain_percent": 20,
        "start_raise_percent": 20,
        "target_bargain_percent": 0,
        "target_raise_percent": 0,
        "trade_phase": "buy",
        "terminal_status": "",
        "terminal_reason": "",
        "recovery_target": "",
        "recovery_reason": "",
        "recovery_source": "",
        "recovery_attempt_counts": {},
        "auto_drink": False,
        "drink_fatigue_threshold": 300,
        "drink_unavailable": False,
        "drink_used_count": 0,
        "auto_use_impact_drill": False,
        "auto_use_speed_projectile": False,
        "use_bento": False,
        "use_fatigue_medicine": False,
        "lollipop_use_limit": 0,
        "gum_use_limit": 0,
        "cactus_candy_use_limit": 0,
        "huashi_use_limit": 0,
        "completed_rounds": 0,
        "strength_recovery_unavailable": False,
        "strength_recovery_unavailable_logged": False,
        "strength_recovery_stop_pending": False,
        "strength_recovery": {
            "used": {},
            "unavailable": {},
            "skip_logged": {},
            "pending": {},
            "huashi_total_cost": 0,
            "huashi_unknown_cost_count": 0,
        },
    }


def _manual_two_city_state(reset: bool = False) -> dict[str, Any]:
    global _MANUAL_TWO_CITY_STATE
    if reset or not _MANUAL_TWO_CITY_STATE:
        _MANUAL_TWO_CITY_STATE = _manual_two_city_defaults()
    return _MANUAL_TWO_CITY_STATE


def _manual_two_city_current_task_entry(state: dict[str, Any] | None = None) -> str:
    current_state = state or _manual_two_city_state()
    task_entry = str(current_state.get("task_entry") or "").strip()
    return task_entry or MANUAL_TWO_CITY_TASK_ENTRY


def _manual_two_city_log_label(state: dict[str, Any] | None = None) -> str:
    return "自动双城跑商" if _manual_two_city_current_task_entry(state) == AUTO_TWO_CITY_TASK_ENTRY else "手动双城跑商"


def _manual_two_city_collect_city_options(params: dict[str, Any], prefix: str, fallback_key: str) -> list[str]:
    cities: list[str] = []
    raw = params.get(fallback_key)
    if isinstance(raw, str):
        cities.extend(item.strip() for item in raw.replace("，", ",").split(","))
    elif isinstance(raw, (list, tuple, set)):
        cities.extend(str(item).strip() for item in raw)
    for key, value in params.items():
        if not str(key).startswith(prefix):
            continue
        if isinstance(value, bool) and not value:
            continue
        if value in (None, "", False):
            continue
        city = str(value if not isinstance(value, bool) else str(key)[len(prefix):]).strip()
        if city:
            cities.append(city)
    return list(dict.fromkeys(city for city in cities if city))


def _manual_two_city_calculate_params_from_state() -> dict[str, Any]:
    state = _manual_two_city_state()
    params = dict(state.get("manual_params") or {})
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    if not params:
        params = {
            "start_city": result.get("start_city") or state.get("manual_start_city"),
            "target_city": result.get("target_city") or state.get("manual_target_city"),
            "uid": result.get("uid") or state.get("uid"),
            "start_book": result.get("start_book", state.get("start_book", 0)),
            "target_book": result.get("target_book", state.get("target_book", 0)),
            "start_bargain_percent": result.get("start_bargain_percent", state.get("start_bargain_percent", 0)),
            "start_raise_percent": result.get("start_raise_percent", state.get("start_raise_percent", 0)),
            "target_bargain_percent": result.get("target_bargain_percent", state.get("target_bargain_percent", 0)),
            "target_raise_percent": result.get("target_raise_percent", state.get("target_raise_percent", 0)),
        }
    return params


def _manual_two_city_recalculate_after_account_profile() -> bool:
    state = _manual_two_city_state()
    task_entry = _manual_two_city_current_task_entry(state)
    task_label = _manual_two_city_log_label(state)
    params = _manual_two_city_calculate_params_from_state()
    old_index = int(state.get("active_leg_index") or 0)
    phase = str(state.get("trade_phase") or "buy").strip().lower()
    current_city = normalize_city_name(str(state.get("current_city") or state.get("travel_arrived_city") or "").strip())
    recalc_started_at = time.perf_counter()
    _append_user_log(
        task_entry,
        f"账号配置已读取，开始按真实配置重算{task_label}收益。",
        run_id=str(state.get("run_id") or ""),
        event="manual_two_city_account_profile_recalculate_started",
        data={
            "auto_route_enabled": bool(state.get("auto_route_enabled")),
            "current_city": current_city,
            "phase": phase,
        },
    )
    try:
        transient_status = state.get("transient_product_status_by_city")
        if state.get("auto_route_enabled"):
            params = dict(state.get("auto_route_params") or {})
            if isinstance(transient_status, dict) and transient_status:
                params["transient_product_status_by_city"] = transient_status
            params["allow_default_account"] = False
            new_result = calculate_auto_two_city_trade(**params)
            state["manual_params"] = {
                "start_city": new_result.get("start_city"),
                "target_city": new_result.get("target_city"),
                "uid": new_result.get("uid") or params.get("uid"),
                "start_book": new_result.get("start_book", 0),
                "target_book": new_result.get("target_book", 0),
                "start_bargain_percent": new_result.get("start_bargain_percent", 0),
                "start_raise_percent": new_result.get("start_raise_percent", 0),
                "target_bargain_percent": new_result.get("target_bargain_percent", 0),
                "target_raise_percent": new_result.get("target_raise_percent", 0),
            }
        else:
            if isinstance(transient_status, dict) and transient_status:
                params["transient_product_status_by_city"] = transient_status
            params["allow_default_account"] = False
            new_result = calculate_manual_two_city_trade(**params)
        state["result"] = new_result
        state["manual_start_city"] = new_result.get("start_city")
        state["manual_target_city"] = new_result.get("target_city")
        legs = (new_result.get("summary") or {}).get("legs") or []
        active_index = old_index if 0 <= old_index < len(legs) else 0
        if current_city:
            for index, leg in enumerate(legs):
                if not isinstance(leg, dict):
                    continue
                city_key = "sell_city" if phase == "sell" else "buy_city"
                if normalize_city_name(str(leg.get(city_key) or "").strip()) == current_city:
                    active_index = index
                    break
        state["active_leg_index"] = active_index
        if phase == "buy":
            state["selected_buy_goods"] = []
        output_path = save_manual_two_city_result(new_result, task_entry=task_entry)
        summary = new_result.get("summary") or {}
        elapsed_ms = int((time.perf_counter() - recalc_started_at) * 1000)
        _append_user_log(
            task_entry,
            (
                f"账号配置读取完成，已按真实配置重算{task_label}收益："
                f"利润 {summary.get('profit')}，参考利润 {summary.get('reference_profit')}，"
                f"疲劳 {summary.get('tired')}，耗时 {elapsed_ms}ms。"
            ),
            run_id=str(state.get("run_id") or ""),
            event="manual_two_city_account_profile_recalculated",
            data={
                "active_leg_index": active_index,
                "current_city": current_city,
                "phase": phase,
                "summary": summary,
                "output_path": str(output_path),
                "elapsed_ms": elapsed_ms,
            },
        )
        return True
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - recalc_started_at) * 1000)
        _append_user_log(
            task_entry,
            f"账号配置读取后重算{task_label}失败：{type(exc).__name__}: {exc}，耗时 {elapsed_ms}ms",
            run_id=str(state.get("run_id") or ""),
            level="error",
            event="manual_two_city_account_profile_recalculate_failed",
            data={"params": params, "elapsed_ms": elapsed_ms, "traceback": traceback.format_exc(limit=8)},
        )
        return False


@AgentServer.custom_action("manual_two_city_business_config")
class ManualTwoCityBusinessConfigAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        state = _manual_two_city_state(reset=bool(params.get("reset")))
        for key in (
            "task_entry",
            "auto_route_enabled",
            "auto_route_params",
            "priority_cities",
            "exclude_cities",
            "max_restock",
            "wulinyuan_priority",
            "manual_start_city",
            "manual_target_city",
            "account_profile_read_mode",
            "account_profile_smart_scan_interval",
            "run_mode",
            "start_book",
            "target_book",
            "start_haggle_percent",
            "target_haggle_percent",
            "start_bargain_percent",
            "start_raise_percent",
            "target_bargain_percent",
            "target_raise_percent",
            "auto_drink",
            "drink_fatigue_threshold",
            "auto_use_impact_drill",
            "auto_use_speed_projectile",
            "use_bento",
            "use_fatigue_medicine",
            "lollipop_use_limit",
            "gum_use_limit",
            "cactus_candy_use_limit",
            "huashi_use_limit",
        ):
            if key in params:
                if key == "run_mode":
                    state[key] = _manual_two_city_run_mode(params[key])
                elif key == "account_profile_read_mode":
                    state[key] = _manual_two_city_account_read_mode(params[key])
                elif key == "account_profile_smart_scan_interval":
                    state[key] = _manual_two_city_smart_scan_interval(params[key])
                else:
                    state[key] = params[key]
        for key, value in params.items():
            if str(key).startswith("priority_city_") or str(key).startswith("exclude_city_"):
                state[str(key)] = value
        _json_payload("manual_two_city_business_config", {"ok": True, "state": dict(state)})
        return True


@AgentServer.custom_action("manual_two_city_business_account_profile_warmup_start")
class ManualTwoCityBusinessAccountProfileWarmupStartAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        state = _manual_two_city_state()
        task_entry = _manual_two_city_current_task_entry(state)
        if state.get("account_profile_warmup_done"):
            _json_payload("manual_two_city_business_account_profile_warmup_start", {"ok": False, "reason": "already_done"})
            return False
        mode = _manual_two_city_account_read_mode(state.get("account_profile_read_mode"))
        interval = _manual_two_city_smart_scan_interval(state.get("account_profile_smart_scan_interval"))
        result = state.get("result") if isinstance(state.get("result"), dict) else {}
        if mode == MANUAL_TWO_CITY_ACCOUNT_READ_NONE:
            state["account_profile_warmup_done"] = True
            _append_user_log(
                task_entry,
                "账号配置读取模式为不读取：跳过本轮内置读取，继续使用本地已有配置；若本地缺失则继续使用默认配置。",
                run_id=str(state.get("run_id") or ""),
                event="manual_two_city_account_profile_warmup_skipped_none",
            )
            _json_payload("manual_two_city_business_account_profile_warmup_start", {"ok": False, "reason": "mode_none"})
            return False
        if mode == MANUAL_TWO_CITY_ACCOUNT_READ_SMART:
            scan_status = _manual_two_city_smart_scan_status(state, interval)
            if not scan_status.get("due"):
                state["account_profile_warmup_pending"] = False
                state["account_profile_warmup_done"] = True
                _append_user_log(
                    task_entry,
                    (
                        "账号配置智能读取：上次智能扫描仍在间隔内，"
                        f"本轮跳过扫描（上次 {scan_status.get('last_smart_scan_date')}，"
                        f"下次 {scan_status.get('next_smart_scan_date')}）。"
                    ),
                    run_id=str(state.get("run_id") or ""),
                    event="manual_two_city_account_profile_warmup_skipped_interval",
                    data=scan_status,
                )
                _json_payload(
                    "manual_two_city_business_account_profile_warmup_start",
                    {"ok": False, "reason": "smart_scan_interval_not_elapsed", "scan_status": scan_status},
                )
                return False
            state["account_profile_smart_scan_status"] = scan_status
        state["account_profile_warmup_pending"] = True
        state["account_profile_warmup_started_at"] = time.time()
        if mode == MANUAL_TWO_CITY_ACCOUNT_READ_FULL:
            mode_label = "全部读取"
            mode_detail = "会全量读取账号配置，完成后自动改回智能读取。"
        else:
            mode_label = "智能读取"
            mode_detail = f"间隔为{_manual_two_city_smart_scan_interval_label(interval)}，会在个人信息页读取货仓容量，并只检查未解锁/缺失城市与缺失乘员。"
        source = str(params.get("source") or "").strip()
        location_label = "已到主界面" if source == "main_map" else "账号配置读取"
        _append_user_log(
            task_entry,
            f"{location_label}：账号配置{mode_label}启动，{mode_detail}读取完成后会重算跑商收益再继续。",
            run_id=str(state.get("run_id") or ""),
            level="info",
            event="manual_two_city_account_profile_warmup_start",
            data={
                "account_profile_read_mode": mode,
                "account_profile_smart_scan_interval": interval,
                "used_default_account_config": bool(result.get("used_default_account_config")),
            },
        )
        _json_payload("manual_two_city_business_account_profile_warmup_start", {"ok": True})
        return True


@AgentServer.custom_action("manual_two_city_business_account_profile_warmup_fast_path_ready")
class ManualTwoCityBusinessAccountProfileWarmupFastPathReadyAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        mode = _manual_two_city_account_read_mode(state.get("account_profile_read_mode"))
        result = state.get("result") if isinstance(state.get("result"), dict) else {}
        path, account, uid, has_context = _manual_two_city_known_account_context(result)
        current_city = normalize_city_name(str(state.get("current_city") or "").strip())
        _json_payload(
            "manual_two_city_business_account_profile_warmup_fast_path_ready",
            {
                "ok": False,
                "mode": mode,
                "uid": uid,
                "current_city": current_city,
                "account_config": str(path),
                "has_context": has_context,
                "reason": "cargo_capacity_is_read_from_profile_panel",
            },
        )
        return False


@AgentServer.custom_action("manual_two_city_business_state_recovery_complete_dispatch")
class ManualTwoCityBusinessStateRecoveryCompleteDispatchAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        pending = bool(state.get("account_profile_warmup_pending"))
        _json_payload("manual_two_city_business_state_recovery_complete_dispatch", {"ok": pending})
        return pending


@AgentServer.custom_action("manual_two_city_business_request_recovery")
class ManualTwoCityBusinessRequestRecoveryAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        state = _manual_two_city_state()
        task_entry = _manual_two_city_current_task_entry(state)
        target = str(params.get("target") or "trade_page").strip()
        if target not in MANUAL_TWO_CITY_RECOVERY_TARGET_LABELS:
            target = "trade_page"
        max_attempts = _int_param(
            params,
            "max_attempts",
            MANUAL_TWO_CITY_RECOVERY_DEFAULT_MAX_ATTEMPTS,
            minimum=1,
        )
        counts = state.setdefault("recovery_attempt_counts", {})
        if not isinstance(counts, dict):
            counts = {}
            state["recovery_attempt_counts"] = counts
        attempt = int(counts.get(target) or 0) + 1
        label = MANUAL_TWO_CITY_RECOVERY_TARGET_LABELS.get(target, target)
        reason = str(params.get("reason") or "识别失败，准备状态恢复后重试。").strip()
        source = str(params.get("source") or getattr(argv, "node_name", "") or "").strip()
        if target == "buy_page":
            state["trade_phase"] = "buy"
        elif target == "sell_page":
            state["trade_phase"] = "sell"

        if attempt > max_attempts:
            state["recovery_target"] = ""
            state["recovery_resumed_target"] = target
            state["recovery_reason"] = reason
            state["recovery_source"] = source
            state["terminal_status"] = MANUAL_TWO_CITY_TERMINAL_FAILED
            state["terminal_reason"] = f"状态恢复到{label}超过 {max_attempts} 次仍失败"
            _append_user_log(
                task_entry,
                f"状态恢复：尝试回到{label}已超过 {max_attempts} 次，停止以避免循环。",
                run_id=str(state.get("run_id") or ""),
                level="error",
                event="manual_two_city_recovery_attempt_exhausted",
                data={"target": target, "label": label, "attempt": attempt, "max_attempts": max_attempts, "reason": reason, "source": source},
            )
            _json_payload(
                "manual_two_city_business_request_recovery",
                {"ok": False, "target": target, "attempt": attempt, "max_attempts": max_attempts, "reason": reason},
            )
            return False

        counts[target] = attempt
        state["recovery_target"] = target
        state["recovery_reason"] = reason
        state["recovery_source"] = source
        state["recovery_requested_at"] = time.time()
        _append_user_log(
            task_entry,
            f"状态恢复：{reason} 将先回到主界面，再尝试恢复到{label}（第 {attempt}/{max_attempts} 次）。",
            run_id=str(state.get("run_id") or ""),
            level="warning",
            event="manual_two_city_recovery_requested",
            data={"target": target, "label": label, "attempt": attempt, "max_attempts": max_attempts, "source": source},
        )
        _json_payload(
            "manual_two_city_business_request_recovery",
            {"ok": True, "target": target, "attempt": attempt, "max_attempts": max_attempts, "reason": reason, "source": source},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_recovery_resume")
class ManualTwoCityBusinessRecoveryResumeAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        state = _manual_two_city_state()
        task_entry = _manual_two_city_current_task_entry(state)
        target = str(params.get("target") or state.get("recovery_target") or "").strip()
        if not target:
            _json_payload("manual_two_city_business_recovery_resume", {"ok": False, "reason": "no_target"})
            return False
        label = MANUAL_TWO_CITY_RECOVERY_TARGET_LABELS.get(target, target)
        reason = str(state.get("recovery_reason") or "").strip()
        state["recovery_target"] = ""
        state["recovery_resumed_target"] = target
        state["recovery_resumed_at"] = time.time()
        if target == "buy_page":
            state["trade_phase"] = "buy"
        elif target == "sell_page":
            state["trade_phase"] = "sell"
        _append_user_log(
            task_entry,
            f"状态恢复：已回到主界面，准备重新进入{label}。",
            run_id=str(state.get("run_id") or ""),
            event="manual_two_city_recovery_resume",
            data={"target": target, "label": label, "reason": reason, "source": state.get("recovery_source")},
        )
        _json_payload("manual_two_city_business_recovery_resume", {"ok": True, "target": target, "label": label})
        return True


@AgentServer.custom_action("manual_two_city_business_recovery_failed")
class ManualTwoCityBusinessRecoveryFailedAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        task_entry = _manual_two_city_current_task_entry(state)
        target = str(state.get("recovery_target") or state.get("recovery_resumed_target") or "").strip()
        label = MANUAL_TWO_CITY_RECOVERY_TARGET_LABELS.get(target, target or "目标页面")
        reason = str(state.get("recovery_reason") or "状态恢复失败").strip()
        state["recovery_target"] = ""
        state["terminal_status"] = MANUAL_TWO_CITY_TERMINAL_FAILED
        state["terminal_reason"] = f"状态恢复到{label}失败：{reason}"
        _append_user_log(
            task_entry,
            f"状态恢复：未能回到主界面或恢复到{label}，已停止本轮跑商。",
            run_id=str(state.get("run_id") or ""),
            level="error",
            event="manual_two_city_recovery_failed",
            data={"target": target, "label": label, "reason": reason, "source": state.get("recovery_source")},
        )
        _json_payload("manual_two_city_business_recovery_failed", {"ok": True, "target": target, "label": label, "reason": reason})
        return True


@AgentServer.custom_action("manual_two_city_business_trade_outlet_open_done_dispatch")
class ManualTwoCityBusinessTradeOutletOpenDoneDispatchAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        _json_payload(
            "manual_two_city_business_trade_outlet_open_done_dispatch",
            {"ok": False, "reason": "cargo_capacity_is_read_from_profile_panel"},
        )
        return False


@AgentServer.custom_action("manual_two_city_business_trade_outlet_open_failed_dispatch")
class ManualTwoCityBusinessTradeOutletOpenFailedDispatchAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        _json_payload(
            "manual_two_city_business_trade_outlet_open_failed_dispatch",
            {"ok": False, "reason": "cargo_capacity_is_read_from_profile_panel"},
        )
        return False


@AgentServer.custom_action("manual_two_city_business_account_profile_warmup_done")
class ManualTwoCityBusinessAccountProfileWarmupDoneAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        task_entry = _manual_two_city_current_task_entry(state)
        mode = _manual_two_city_account_read_mode(state.get("account_profile_read_mode"))
        interval = _manual_two_city_smart_scan_interval(state.get("account_profile_smart_scan_interval"))
        state["account_profile_warmup_pending"] = False
        state["account_profile_warmup_done"] = True
        ok = _manual_two_city_recalculate_after_account_profile()
        config_update: dict[str, Any] | None = None
        read_meta_update: dict[str, Any] | None = None
        if ok:
            read_meta_update = _manual_two_city_mark_account_profile_read_completed(mode, interval)
            if read_meta_update.get("updated"):
                _append_user_log(
                    task_entry,
                    "账号配置读取日期已写入账号配置。",
                    run_id=str(state.get("run_id") or ""),
                    event="manual_two_city_account_profile_read_date_saved",
                    data={"read_meta_update": read_meta_update},
                )
        if mode == MANUAL_TWO_CITY_ACCOUNT_READ_FULL:
            config_update = _manual_two_city_reset_account_read_mode_to_smart()
            state["account_profile_read_mode"] = MANUAL_TWO_CITY_ACCOUNT_READ_SMART
            if config_update.get("updated"):
                _append_user_log(
                    task_entry,
                    "账号配置全部读取已完成，已将跑商任务读取模式自动改回智能读取。",
                    run_id=str(state.get("run_id") or ""),
                    event="manual_two_city_account_profile_full_reset_to_smart",
                    data={"config_update": config_update},
                )
            else:
                _append_user_log(
                    task_entry,
                    "账号配置全部读取已完成；未找到需要写回的前端配置项，本轮内已切回智能读取。",
                    run_id=str(state.get("run_id") or ""),
                    event="manual_two_city_account_profile_full_reset_to_smart_noop",
                    data={"config_update": config_update},
                )
        _json_payload(
            "manual_two_city_business_account_profile_warmup_done",
            {"ok": ok, "config_update": config_update, "read_meta_update": read_meta_update},
        )
        return ok


@AgentServer.custom_action("manual_two_city_business_stage")
class ManualTwoCityBusinessStageAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        stage = str(params.get("stage") or "手动双城跑商").strip()
        detail = str(params.get("detail") or "").strip()
        should_fail = bool(params.get("fail"))
        terminal_status = str(params.get("terminal_status") or "").strip()
        state = _manual_two_city_state()
        if (
            "道中事件面板" in detail
            and _manual_two_city_bool(state.get("auto_use_impact_drill"), False)
        ):
            texts = _ocr_texts(argv)
            if _texts_contain_any(texts, ["撞击脱离", "撞击准备", "疲劳度+0"]) or (
                _texts_contain_any(texts, ["请选择", "应对方式"])
                and not _texts_contain_any(texts, ["敌方等级", "护卫队迎击"])
            ):
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    "行车事件：检测到撞击脱离轮盘，跳过通用事件点击，改由撞击钻头节点处理。",
                    level="info",
                    event="manual_two_city_skip_generic_event_for_impact_drill",
                    data={"texts": texts[:30]},
                )
                _json_payload(
                    "manual_two_city_business_stage",
                    {"ok": False, "stage": stage, "detail": detail, "reason": "impact_drill_wheel"},
                )
                return False
        if terminal_status:
            state["terminal_status"] = terminal_status
            state["terminal_reason"] = detail or stage
        elif should_fail:
            state["terminal_status"] = MANUAL_TWO_CITY_TERMINAL_FAILED
            state["terminal_reason"] = detail or stage
        message = f"{stage}：{detail}" if detail else stage
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            message,
            level=str(params.get("level") or ("error" if should_fail else "info")),
            event="manual_two_city_business_stage",
            data={"stage": stage, "detail": detail},
        )
        _json_payload("manual_two_city_business_stage", {"ok": not should_fail, "stage": stage, "detail": detail})
        return not should_fail


def _manual_two_city_route_item_key(item: str) -> str | None:
    return {
        "impact_drill": "auto_use_impact_drill",
        "speed_projectile": "auto_use_speed_projectile",
    }.get(item)


def _manual_two_city_route_item_enabled(item: str) -> tuple[bool, str | None]:
    key = _manual_two_city_route_item_key(item)
    state = _manual_two_city_state()
    return bool(key and _manual_two_city_bool(state.get(key), False)), key


def _manual_two_city_reco_box(detail: Any, expected: list[str] | None = None) -> tuple[int, int, int, int] | None:
    xywh = _box_xywh(getattr(detail, "box", None))
    if xywh is not None:
        return xywh
    if expected:
        for entry in _ocr_entries_from_detail(detail):
            if _manual_two_city_entry_matches(entry, expected):
                return int(entry["x"]), int(entry["y"]), int(entry["w"]), int(entry["h"])
    for result in _collect_ocr_result_objects(detail):
        xywh = _box_xywh(getattr(result, "box", None))
        if xywh is None and isinstance(result, dict):
            xywh = _box_xywh(result.get("box"))
        if xywh is not None:
            return xywh
    return None


MANUAL_TWO_CITY_DAILY_CHECKIN_TEXTS = [
    "每日签到奖励",
    "DAILY CHECK-IN CALENDAR",
    "本月累计签到",
    "今日奖励",
]


@AgentServer.custom_recognition("manual_two_city_business_recovery_target")
class ManualTwoCityBusinessRecoveryTargetRecognition(CustomRecognition):
    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        params = _custom_recognition_param(argv)
        raw_targets = params.get("targets", params.get("target"))
        if isinstance(raw_targets, str):
            targets = {raw_targets.strip()}
        elif isinstance(raw_targets, (list, tuple, set)):
            targets = {str(item).strip() for item in raw_targets}
        else:
            targets = set()
        targets.discard("")

        state = _manual_two_city_state()
        target = str(state.get("recovery_target") or "").strip()
        if not target:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"ok": False, "reason": "no_recovery_target"},
            )
        if targets and target not in targets:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"ok": False, "reason": "target_mismatch", "target": target, "expected": sorted(targets)},
            )
        return CustomRecognition.AnalyzeResult(
            box=(0, 0, 1280, 720),
            detail={
                "ok": True,
                "target": target,
                "reason": state.get("recovery_reason"),
                "source": state.get("recovery_source"),
            },
        )


@AgentServer.custom_recognition("manual_two_city_business_daily_checkin_popup")
class ManualTwoCityBusinessDailyCheckinPopupRecognition(CustomRecognition):
    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        image = getattr(argv, "image", None)
        if image is None:
            image = _manual_two_city_screencap(context)
        if image is None:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"ok": False, "reason": "no_image"},
            )
        try:
            detail = context.run_recognition(
                f"{argv.node_name}DailyCheckinProbe",
                image,
                {
                    f"{argv.node_name}DailyCheckinProbe": {
                        "recognition": "OCR",
                        "expected": "",
                        "roi": [120, 40, 1040, 640],
                        "action": "DoNothing",
                    }
                },
            )
        except Exception as exc:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"ok": False, "reason": "probe_error", "error": str(exc)},
            )
        texts = _ocr_texts_from_detail(detail)
        joined = " ".join(clean_text(text) for text in texts)
        hit = any(text in joined for text in MANUAL_TWO_CITY_DAILY_CHECKIN_TEXTS)
        if not hit:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"ok": False, "reason": "not_daily_checkin", "texts": texts[:20]},
            )
        return CustomRecognition.AnalyzeResult(
            box=(610, 690, 60, 30),
            detail={"ok": True, "reason": "daily_checkin_popup", "texts": texts[:30]},
        )


@AgentServer.custom_recognition("manual_two_city_business_route_item_available")
class ManualTwoCityBusinessRouteItemAvailableRecognition(CustomRecognition):
    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        params = _custom_recognition_param(argv)
        item = str(params.get("item") or "").strip()
        enabled, key = _manual_two_city_route_item_enabled(item)
        if not enabled:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"ok": False, "reason": "disabled", "item": item, "key": key},
            )

        probe_name = f"{argv.node_name}Probe"
        expected: list[str] | None = None
        fallback_box: tuple[int, int, int, int] | None = None
        if item == "impact_drill":
            expected = ["撞击脱离", "撞击准备"]
            fallback_box = (820, 250, 460, 300)
            node: dict[str, Any] = {
                "recognition": "OCR",
                "expected": expected,
                "roi": list(fallback_box),
                "action": "DoNothing",
            }
        elif item == "speed_projectile":
            fallback_box = (0, 540, 1280, 180)
            node = {
                "recognition": "TemplateMatch",
                "template": "stations/speed_up.png",
                "threshold": 0.82,
                "roi": list(fallback_box),
                "action": "DoNothing",
            }
        else:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"ok": False, "reason": "unknown_item", "item": item, "key": key},
            )

        try:
            detail = context.run_recognition(probe_name, argv.image, {probe_name: node})
        except Exception as exc:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"ok": False, "reason": "probe_error", "item": item, "error": str(exc)},
            )

        hit = bool(getattr(detail, "hit", False))
        box = _manual_two_city_reco_box(detail, expected)
        if not hit or box is None:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={
                    "ok": False,
                    "reason": "not_found",
                    "item": item,
                    "texts": _ocr_texts_from_detail(detail),
                },
            )
        return CustomRecognition.AnalyzeResult(
            box=box or fallback_box,
            detail={"ok": True, "item": item, "key": key, "box": list(box), "click_box": list(box or fallback_box)},
        )


@AgentServer.custom_recognition("manual_two_city_business_fight_active")
class ManualTwoCityBusinessFightActiveRecognition(CustomRecognition):
    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        image = getattr(argv, "image", None)
        if image is None:
            image = _manual_two_city_screencap(context)
        if image is None:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"ok": False, "reason": "no_image"},
            )

        top_detail = None
        bottom_detail = None
        try:
            top_detail = context.run_recognition(
                f"{argv.node_name}TopProbe",
                image,
                {
                    f"{argv.node_name}TopProbe": {
                        "recognition": "OCR",
                        "expected": ["00:", "01:", "02:", "1/1", "1/2", "2/2", "1/3", "2/3", "3/3"],
                        "roi": [500, 0, 260, 60],
                        "action": "DoNothing",
                    }
                },
            )
        except Exception:
            top_detail = None
        try:
            bottom_detail = context.run_recognition(
                f"{argv.node_name}BottomProbe",
                image,
                {
                    f"{argv.node_name}BottomProbe": {
                        "recognition": "OCR",
                        "expected": ["COST不足", "COST", "费用", "弃牌", "MAX"],
                        "roi": [0, 420, 1280, 300],
                        "action": "DoNothing",
                    }
                },
            )
        except Exception:
            bottom_detail = None

        top_texts = _ocr_texts_from_detail(top_detail)
        bottom_texts = _ocr_texts_from_detail(bottom_detail)
        joined_top = " ".join(top_texts)
        joined_bottom = " ".join(bottom_texts)
        has_timer = bool(re.search(r"\b\d{1,2}\s*:\s*\d{2}\b", joined_top))
        has_wave = bool(re.search(r"\b[1-9]\s*/\s*[1-9]\b", joined_top))
        has_card_ui = _texts_contain_any(bottom_texts, ["COST不足", "COST", "弃牌", "MAX"])
        if (has_timer and has_wave) or (has_card_ui and (has_timer or has_wave)):
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 1280, 720],
                detail={
                    "ok": True,
                    "reason": "fight_active",
                    "top_texts": top_texts[:12],
                    "bottom_texts": bottom_texts[:12],
                    "has_timer": has_timer,
                    "has_wave": has_wave,
                    "has_card_ui": has_card_ui,
                },
            )
        return CustomRecognition.AnalyzeResult(
            box=None,
            detail={
                "ok": False,
                "reason": "not_fight_active",
                "top_texts": top_texts[:12],
                "bottom_texts": bottom_texts[:12],
                "has_timer": has_timer,
                "has_wave": has_wave,
                "has_card_ui": has_card_ui,
            },
        )


@AgentServer.custom_recognition("manual_two_city_business_strength_stop_pending")
class ManualTwoCityBusinessStrengthStopPendingRecognition(CustomRecognition):
    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        state = _manual_two_city_state()
        if not state.get("strength_recovery_stop_pending"):
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"ok": False, "reason": "not_pending"},
            )
        return CustomRecognition.AnalyzeResult(
            box=(0, 0, 1, 1),
            detail={
                "ok": True,
                "reason": "stop_pending",
                "phase": state.get("strength_recovery_stop_phase") or state.get("trade_phase"),
                "status": state.get("strength_recovery_stop_status"),
                "required": state.get("strength_recovery_stop_required"),
            },
        )


CITY_TRADE_OUTLET_WULIN_MARKET_ROI = [0, 80, 1100, 560]
CITY_TRADE_OUTLET_WULIN_CLICK_Y_OFFSET = 65


@AgentServer.custom_recognition("city_trade_outlet_wulin_market")
class CityTradeOutletWulinMarketRecognition(CustomRecognition):
    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        _hit, entries, texts = _manual_two_city_ocr_entries(
            context,
            "CityTradeOutletWulinMarket",
            ["交易所", "武林市集", "武林市"],
            roi=CITY_TRADE_OUTLET_WULIN_MARKET_ROI,
        )
        market_entries: list[dict[str, Any]] = []
        trade_entries: list[dict[str, Any]] = []
        for entry in entries:
            text = clean_text(entry.get("text"))
            if "武林市集" in text or "武林市" in text or ("武林" in text and "市集" in text):
                market_entries.append(entry)
            if "交易所" in text:
                trade_entries.append(entry)

        if not market_entries:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"ok": False, "reason": "market_missing", "texts": texts[:20]},
            )

        def entry_float(entry: dict[str, Any], key: str, fallback: float = 0.0) -> float:
            try:
                return float(entry.get(key) or fallback)
            except (TypeError, ValueError):
                return fallback

        market = min(market_entries, key=lambda item: entry_float(item, "y"))
        market_text = clean_text(market.get("text"))
        market_x = entry_float(market, "x")
        market_y = entry_float(market, "y")
        market_w = entry_float(market, "w")
        market_h = entry_float(market, "h")
        market_cx = entry_float(market, "center_x", market_x + market_w / 2)
        market_cy = entry_float(market, "center_y", market_y + market_h / 2)
        target_x = market_cx
        target_y = market_cy + CITY_TRADE_OUTLET_WULIN_CLICK_Y_OFFSET
        reason = "market_text"

        if "交易所" not in market_text:
            same_row_trade = [
                entry
                for entry in trade_entries
                if abs(entry_float(entry, "center_y") - market_cy) <= 38
            ]
            if same_row_trade:
                trade = min(same_row_trade, key=lambda item: abs(entry_float(item, "center_y") - market_cy))
                left = min(entry_float(trade, "x"), market_x)
                right = max(entry_float(trade, "x") + entry_float(trade, "w"), market_x + market_w)
                target_x = (left + right) / 2
                target_y = (
                    entry_float(trade, "center_y", entry_float(trade, "y") + entry_float(trade, "h") / 2)
                    + market_cy
                ) / 2 + CITY_TRADE_OUTLET_WULIN_CLICK_Y_OFFSET
                reason = "trade_and_market_text"
            else:
                target_x = market_cx - max(36.0, min(90.0, market_w * 0.55))
                reason = "market_text_estimated_prefix"
        else:
            reason = "full_text"

        target_x = max(20.0, min(1080.0, target_x))
        target_y = max(100.0, min(660.0, target_y))
        x = int(round(target_x)) - 6
        y = int(round(target_y)) - 6
        return CustomRecognition.AnalyzeResult(
            box=(x, y, 12, 12),
            detail={
                "ok": True,
                "reason": reason,
                "target": [int(round(target_x)), int(round(target_y))],
                "market_text": market.get("text"),
                "texts": texts[:20],
            },
        )


@AgentServer.custom_action("manual_two_city_business_route_item_enabled")
class ManualTwoCityBusinessRouteItemEnabledAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        item = str(params.get("item") or "").strip()
        enabled, key = _manual_two_city_route_item_enabled(item)
        _json_payload("manual_two_city_business_route_item_enabled", {"ok": enabled, "item": item, "key": key})
        return enabled


def _manual_two_city_route_item_still_visible(context: Context, item: str) -> bool | None:
    image = _manual_two_city_screencap(context)
    if image is None:
        return None
    probe_name = "ManualTwoCityBusinessRouteItemAfterClickProbe"
    if item == "impact_drill":
        node = {
            "recognition": "OCR",
            "expected": ["撞击脱离", "撞击准备"],
            "roi": [820, 250, 460, 300],
            "action": "DoNothing",
        }
    elif item == "speed_projectile":
        node = {
            "recognition": "TemplateMatch",
            "template": "stations/speed_up.png",
            "threshold": 0.82,
            "roi": [0, 540, 1280, 180],
            "action": "DoNothing",
        }
    else:
        return None
    try:
        detail = context.run_recognition(probe_name, image, {probe_name: node})
    except Exception:
        return None
    return bool(getattr(detail, "hit", False))


@AgentServer.custom_action("manual_two_city_business_route_item_used")
class ManualTwoCityBusinessRouteItemUsedAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        item = str(params.get("item") or "").strip()
        label = {
            "impact_drill": "撞击钻头",
            "speed_projectile": "加速弹丸",
        }.get(item, item or "行车道具")
        if item == "impact_drill":
            still_visible = _manual_two_city_route_item_still_visible(context, item)
            if still_visible is True:
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    "行车道具：已点击撞击钻头，但撞击轮盘仍可见，稍后重试。",
                    level="warning",
                    event="manual_two_city_route_item_click_unconfirmed",
                    data={"item": item, "label": label, "leg": _manual_two_city_active_leg()},
                )
                _json_payload("manual_two_city_business_route_item_used", {"ok": False, "item": item, "label": label, "reason": "still_visible"})
                return False
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"行车道具：已自动使用{label}。",
            event="manual_two_city_route_item_used",
            data={"item": item, "label": label, "leg": _manual_two_city_active_leg()},
        )
        _json_payload("manual_two_city_business_route_item_used", {"ok": True, "item": item, "label": label})
        return True


def _manual_two_city_active_leg() -> dict[str, Any]:
    state = _manual_two_city_state()
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    legs = summary.get("legs") if isinstance(summary.get("legs"), list) else []
    try:
        index = int(state.get("active_leg_index") or 0)
    except (TypeError, ValueError):
        index = 0
    if 0 <= index < len(legs) and isinstance(legs[index], dict):
        return legs[index]
    return {}


def _manual_two_city_legs() -> list[dict[str, Any]]:
    state = _manual_two_city_state()
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    legs = summary.get("legs") if isinstance(summary.get("legs"), list) else []
    return [leg for leg in legs if isinstance(leg, dict)]


def _manual_two_city_detect_current_city(texts: list[str], legs: list[dict[str, Any]]) -> str:
    cleaned_texts = [clean_text(text) for text in texts if str(text).strip()]
    candidates: list[str] = []
    for leg in legs:
        for key in ("buy_city", "sell_city"):
            city = str(leg.get(key) or "").strip()
            if city and city not in candidates:
                candidates.append(city)
    for city in list(load_city_names()) + list(_all_buy_goods_by_city().keys()):
        city_name = normalize_city_name(str(city or "").strip())
        if city_name and city_name not in candidates:
            candidates.append(city_name)
    for city in candidates:
        city_text = clean_text(city)
        if any(city_text and city_text in text for text in cleaned_texts):
            return city
    return ""


def _manual_two_city_set_active_leg_by_city(city: str) -> dict[str, Any]:
    state = _manual_two_city_state()
    legs = _manual_two_city_legs()
    for index, leg in enumerate(legs):
        if str(leg.get("buy_city") or "").strip() == city:
            if state.get("active_leg_index") != index:
                state["selected_buy_goods"] = []
            state["active_leg_index"] = index
            state["current_city"] = city
            return leg
    return _manual_two_city_active_leg()


def _manual_two_city_endpoint_cities() -> tuple[str, str]:
    state = _manual_two_city_state()
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    start_city = normalize_city_name(str(result.get("start_city") or state.get("manual_start_city") or "").strip())
    target_city = normalize_city_name(str(result.get("target_city") or state.get("manual_target_city") or "").strip())
    return start_city, target_city


def _manual_two_city_route_required_fatigue(from_city: Any, to_city: Any) -> tuple[int, bool]:
    source = normalize_city_name(str(from_city or "").strip())
    target = normalize_city_name(str(to_city or "").strip())
    if not source or not target or source == target:
        return 0, False
    tired_map = load_default_tired_data()
    value = tired_map.get(f"{source}-{target}") or tired_map.get(f"{target}-{source}")
    if value is not None:
        try:
            return max(1, int(value)), False
        except (TypeError, ValueError):
            pass
    coords = load_station_world_coords()
    if source in coords and target in coords:
        ax, ay = coords[source]
        bx, by = coords[target]
        return max(1, int(round(((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 / 40.0))), True
    return 999, True


def _manual_two_city_choose_initial_transfer_destination(current_city: str) -> dict[str, Any]:
    start_city, target_city = _manual_two_city_endpoint_cities()
    options: list[dict[str, Any]] = []
    for endpoint in (start_city, target_city):
        if not endpoint:
            continue
        fatigue, estimated = _manual_two_city_route_required_fatigue(current_city, endpoint)
        options.append({"city": endpoint, "fatigue": fatigue, "estimated": estimated})
    if not options:
        return {}
    options.sort(key=lambda item: (int(item.get("fatigue") or 999), 0 if item.get("city") == start_city else 1))
    return {**options[0], "options": options, "start_city": start_city, "target_city": target_city}


def _manual_two_city_known_city_names() -> list[str]:
    names: list[str] = []
    for city in list(load_city_names()) + list(_all_buy_goods_by_city().keys()):
        city_name = normalize_city_name(str(city or "").strip())
        if city_name and city_name not in names:
            names.append(city_name)
    return sorted(names, key=len, reverse=True)


def _manual_two_city_city_from_texts(texts: list[str], *, preferred_keywords: tuple[str, ...] = ()) -> str:
    cleaned = [clean_text(text) for text in texts if str(text).strip()]
    preferred = [
        text
        for text in cleaned
        if preferred_keywords and any(clean_text(keyword) in text for keyword in preferred_keywords)
    ]
    pools = [preferred, cleaned] if preferred else [cleaned]
    for pool in pools:
        for text in pool:
            for city in _manual_two_city_known_city_names():
                if clean_text(city) in text:
                    return city
    return ""


def _manual_two_city_startup_travel_destination(texts: list[str], status: dict[str, Any]) -> str:
    raw_destination = str(status.get("destination") or "").strip()
    if raw_destination:
        city = _manual_two_city_city_from_texts([raw_destination])
        if city:
            return city
        normalized = normalize_city_name(raw_destination)
        if normalized in _manual_two_city_known_city_names():
            return normalized
    return _manual_two_city_city_from_texts(texts, preferred_keywords=("目的地",))


def _manual_two_city_return_city_from_popup_texts(texts: list[str]) -> str:
    return (
        _manual_two_city_city_from_texts(texts, preferred_keywords=("回到", "返航"))
        or _manual_two_city_city_from_texts(texts)
    )


def _manual_two_city_distance_to_route_endpoint(city: str) -> dict[str, Any]:
    start_city, target_city = _manual_two_city_endpoint_cities()
    city = normalize_city_name(str(city or "").strip())
    options: list[dict[str, Any]] = []
    for endpoint in (start_city, target_city):
        if not city or not endpoint:
            continue
        fatigue, estimated = _manual_two_city_route_required_fatigue(city, endpoint)
        options.append({"endpoint": endpoint, "fatigue": fatigue, "estimated": estimated})
    if not options:
        return {"city": city, "endpoint": "", "fatigue": 999, "estimated": True, "options": []}
    options.sort(key=lambda item: int(item.get("fatigue") or 999))
    return {**options[0], "city": city, "options": options}


def _manual_two_city_choose_startup_travel_direction(destination_city: str, return_city: str) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for direction, city in (("continue", destination_city), ("return", return_city)):
        city_name = normalize_city_name(str(city or "").strip())
        if not city_name:
            continue
        score = _manual_two_city_distance_to_route_endpoint(city_name)
        candidates.append(
            {
                "direction": direction,
                "city": city_name,
                "nearest_endpoint": score.get("endpoint") or "",
                "fatigue": int(score.get("fatigue") or 999),
                "estimated": bool(score.get("estimated")),
                "options": score.get("options") or [],
            }
        )
    if not candidates:
        return {}
    # Equal distance prefers continuing forward, because an already-correct route should not be undone.
    candidates.sort(key=lambda item: (int(item.get("fatigue") or 999), 0 if item.get("direction") == "continue" else 1))
    return {**candidates[0], "candidates": candidates}


def _manual_two_city_prepare_startup_travel_monitor(
    destination: str,
    *,
    return_city: str = "",
    choice: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = _manual_two_city_state()
    destination = normalize_city_name(str(destination or "").strip())
    return_city = normalize_city_name(str(return_city or "").strip())
    choice = dict(choice or {})
    chosen_direction = str(choice.get("direction") or "continue")
    chosen_city = normalize_city_name(str(choice.get("city") or destination).strip())
    state["startup_travel_pending"] = False
    state["startup_travel_in_progress"] = True
    state["startup_travel_destination_city"] = destination
    state["startup_travel_return_city"] = return_city
    state["startup_travel_direction"] = chosen_direction
    state["startup_travel_target_city"] = chosen_city
    state["startup_travel_decision"] = choice or {"direction": chosen_direction, "city": chosen_city}
    state["travel_arrived_city"] = ""
    state["trade_phase"] = "travel"
    return {
        "destination": destination,
        "return_city": return_city,
        "direction": chosen_direction,
        "target_city": chosen_city,
        "choice": state["startup_travel_decision"],
    }


def _manual_two_city_travel_target_city() -> str:
    state = _manual_two_city_state()
    if state.get("startup_travel_in_progress"):
        destination = str(state.get("startup_travel_target_city") or "").strip()
        if destination:
            return destination
    if state.get("initial_transfer_in_progress"):
        destination = str(state.get("initial_transfer_destination_city") or "").strip()
        if destination:
            return destination
    leg = _manual_two_city_active_leg()
    return str(leg.get("sell_city") or "").strip()


def _manual_two_city_buy_bargain_percent(leg: dict[str, Any]) -> int:
    state = _manual_two_city_state()
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    try:
        index = int(state.get("active_leg_index") or 0)
    except (TypeError, ValueError):
        index = 0
    if index <= 0:
        return _manual_two_city_haggle_count(result.get("start_bargain_percent", result.get("start_haggle_percent")))
    return _manual_two_city_haggle_count(result.get("target_bargain_percent", result.get("target_haggle_percent")))


def _manual_two_city_sell_raise_percent(leg: dict[str, Any]) -> int:
    state = _manual_two_city_state()
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    try:
        index = int(state.get("active_leg_index") or 0)
    except (TypeError, ValueError):
        index = 0
    if index <= 0:
        return _manual_two_city_haggle_count(result.get("start_raise_percent", result.get("start_haggle_percent")))
    return _manual_two_city_haggle_count(result.get("target_raise_percent", result.get("target_haggle_percent")))


def _manual_two_city_next_leg_after_current() -> tuple[int, dict[str, Any]]:
    state = _manual_two_city_state()
    legs = _manual_two_city_legs()
    try:
        next_index = int(state.get("active_leg_index") or 0) + 1
    except (TypeError, ValueError):
        next_index = 1
    if 0 <= next_index < len(legs):
        return next_index, legs[next_index]
    return -1, {}


def _manual_two_city_run_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {
        MANUAL_TWO_CITY_RUN_MODE_UNTIL_FATIGUE_EXHAUSTED,
        "until_fatigue",
        "fatigue",
        "loop",
        "repeat",
        "continuous",
        "跑到疲劳耗尽",
        "疲劳耗尽",
        "一直跑",
    }:
        return MANUAL_TWO_CITY_RUN_MODE_UNTIL_FATIGUE_EXHAUSTED
    return MANUAL_TWO_CITY_RUN_MODE_ONE_ROUND


def _manual_two_city_account_read_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"none", "skip", "no", "off", "不读取", "跳过读取"}:
        return MANUAL_TWO_CITY_ACCOUNT_READ_NONE
    if text in {"full", "all", "force", "全部读取", "全量读取"}:
        return MANUAL_TWO_CITY_ACCOUNT_READ_FULL
    return MANUAL_TWO_CITY_ACCOUNT_READ_SMART


def _manual_two_city_smart_scan_interval(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        MANUAL_TWO_CITY_SMART_SCAN_DAILY: MANUAL_TWO_CITY_SMART_SCAN_DAILY,
        "day": MANUAL_TWO_CITY_SMART_SCAN_DAILY,
        "daily": MANUAL_TWO_CITY_SMART_SCAN_DAILY,
        "every_day": MANUAL_TWO_CITY_SMART_SCAN_DAILY,
        "每天": MANUAL_TWO_CITY_SMART_SCAN_DAILY,
        "每日": MANUAL_TWO_CITY_SMART_SCAN_DAILY,
        MANUAL_TWO_CITY_SMART_SCAN_EVERY_3_DAYS: MANUAL_TWO_CITY_SMART_SCAN_EVERY_3_DAYS,
        "3_days": MANUAL_TWO_CITY_SMART_SCAN_EVERY_3_DAYS,
        "three_days": MANUAL_TWO_CITY_SMART_SCAN_EVERY_3_DAYS,
        "every3days": MANUAL_TWO_CITY_SMART_SCAN_EVERY_3_DAYS,
        "每3天": MANUAL_TWO_CITY_SMART_SCAN_EVERY_3_DAYS,
        "每 3 天": MANUAL_TWO_CITY_SMART_SCAN_EVERY_3_DAYS,
        "三天": MANUAL_TWO_CITY_SMART_SCAN_EVERY_3_DAYS,
        MANUAL_TWO_CITY_SMART_SCAN_WEEKLY: MANUAL_TWO_CITY_SMART_SCAN_WEEKLY,
        "week": MANUAL_TWO_CITY_SMART_SCAN_WEEKLY,
        "every_week": MANUAL_TWO_CITY_SMART_SCAN_WEEKLY,
        "每周": MANUAL_TWO_CITY_SMART_SCAN_WEEKLY,
        "每星期": MANUAL_TWO_CITY_SMART_SCAN_WEEKLY,
        MANUAL_TWO_CITY_SMART_SCAN_MONTHLY: MANUAL_TWO_CITY_SMART_SCAN_MONTHLY,
        "month": MANUAL_TWO_CITY_SMART_SCAN_MONTHLY,
        "every_month": MANUAL_TWO_CITY_SMART_SCAN_MONTHLY,
        "每月": MANUAL_TWO_CITY_SMART_SCAN_MONTHLY,
    }
    return aliases.get(text, MANUAL_TWO_CITY_SMART_SCAN_DAILY)


def _manual_two_city_smart_scan_interval_label(value: Any) -> str:
    interval = _manual_two_city_smart_scan_interval(value)
    return MANUAL_TWO_CITY_SMART_SCAN_INTERVAL_LABELS.get(interval, "每天")


def _parse_profile_read_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return None


def _manual_two_city_smart_scan_next_date(last_date: date, interval: Any) -> date:
    interval_key = _manual_two_city_smart_scan_interval(interval)
    if interval_key == MANUAL_TWO_CITY_SMART_SCAN_MONTHLY:
        month = last_date.month + 1
        year = last_date.year
        if month > 12:
            month = 1
            year += 1
        day = min(last_date.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    days = MANUAL_TWO_CITY_SMART_SCAN_INTERVAL_DAYS.get(interval_key, 1)
    return last_date + timedelta(days=days)


def _manual_two_city_account_profile_read_meta(account: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(account, dict):
        return {}
    for key in ("account_profile_read", "profile_read", "scan_meta"):
        meta = account.get(key)
        if isinstance(meta, dict):
            return meta
    return {}


def _manual_two_city_smart_scan_status(state: dict[str, Any], interval: Any) -> dict[str, Any]:
    interval_key = _manual_two_city_smart_scan_interval(interval)
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    path, account, uid, has_context = _manual_two_city_known_account_context(result)
    if result.get("used_default_account_config"):
        return {
            "due": True,
            "reason": "default_account_config",
            "interval": interval_key,
            "uid": uid,
            "account_config": str(path),
        }
    if not has_context:
        return {
            "due": True,
            "reason": "missing_account_config",
            "interval": interval_key,
            "uid": uid,
            "account_config": str(path),
        }
    meta = _manual_two_city_account_profile_read_meta(account)
    last_date = _parse_profile_read_date(
        meta.get("last_smart_scan_date")
        or meta.get("last_smart_scan_at")
        or meta.get("last_smart_read_date")
        or meta.get("last_smart_read_at")
    )
    if last_date is None:
        return {
            "due": True,
            "reason": "missing_last_smart_scan_date",
            "interval": interval_key,
            "uid": uid,
            "account_config": str(path),
        }
    today = date.today()
    next_date = _manual_two_city_smart_scan_next_date(last_date, interval_key)
    return {
        "due": today >= next_date,
        "reason": "interval_elapsed" if today >= next_date else "interval_not_elapsed",
        "interval": interval_key,
        "uid": uid,
        "account_config": str(path),
        "last_smart_scan_date": last_date.isoformat(),
        "next_smart_scan_date": next_date.isoformat(),
        "today": today.isoformat(),
    }


def _manual_two_city_mark_account_profile_read_completed(mode: Any, interval: Any) -> dict[str, Any]:
    state = _manual_two_city_state()
    task_entry = _manual_two_city_current_task_entry(state)
    interval_key = _manual_two_city_smart_scan_interval(interval)
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    path, account, uid, has_context = _manual_two_city_known_account_context(result)
    if not has_context:
        return {
            "updated": False,
            "reason": "missing_account_config",
            "uid": uid,
            "account_config": str(path),
        }
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    today = date.today().isoformat()
    meta = account.setdefault("account_profile_read", {})
    if not isinstance(meta, dict):
        meta = {}
        account["account_profile_read"] = meta
    read_mode = _manual_two_city_account_read_mode(mode)
    meta["last_read_at"] = now
    meta["last_read_date"] = today
    meta["last_read_mode"] = read_mode
    meta["smart_scan_interval"] = interval_key
    if read_mode == MANUAL_TWO_CITY_ACCOUNT_READ_SMART:
        meta["last_smart_scan_at"] = now
        meta["last_smart_scan_date"] = today
    elif read_mode == MANUAL_TWO_CITY_ACCOUNT_READ_FULL:
        meta["last_full_read_at"] = now
        meta["last_full_read_date"] = today
    account["updated_at"] = now
    source = account.setdefault("_source", {})
    if isinstance(source, dict):
        source["last_task_entry"] = task_entry
        source["last_account_profile_read_task_entry"] = task_entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(account, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {
        "updated": True,
        "uid": uid,
        "account_config": str(path),
        "mode": read_mode,
        "interval": interval_key,
        "last_read_date": today,
    }


def _manual_two_city_drink_allowed_cities() -> set[str]:
    return {
        normalize_city_name(city)
        for city in load_city_names()
        if normalize_city_name(city) and normalize_city_name(city) != "武林源"
    }


def _manual_two_city_drink_city(state: dict[str, Any], phase: str, leg: dict[str, Any]) -> str:
    current_city = normalize_city_name(
        str(state.get("current_city") or state.get("travel_arrived_city") or "").strip()
    )
    if current_city:
        return current_city
    leg_key = "sell_city" if phase == "sell" else "buy_city"
    return normalize_city_name(str(leg.get(leg_key) or "").strip())


def _manual_two_city_until_fatigue_exhausted(state: dict[str, Any] | None = None) -> bool:
    current_state = state or _manual_two_city_state()
    return _manual_two_city_run_mode(current_state.get("run_mode")) == MANUAL_TWO_CITY_RUN_MODE_UNTIL_FATIGUE_EXHAUSTED


def _manual_two_city_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enable", "enabled", "启用", "开启", "是"}:
        return True
    if text in {"0", "false", "no", "off", "disable", "disabled", "禁用", "关闭", "否"}:
        return False
    return default


def _manual_two_city_drink_remaining_from_texts(texts: list[str]) -> dict[str, Any] | None:
    normalized_texts = [
        clean_text(text)
        .translate(str.maketrans("０１２３４５６７８９Ｏｏ", "012345678900"))
        .replace("O", "0")
        .replace("o", "0")
        for text in texts
        if str(text).strip()
    ]
    joined = " ".join(normalized_texts)
    if not joined:
        return None

    candidates: list[tuple[int, int, int, int, str]] = []
    for match in FATIGUE_DRINK_INFO_RATIO_RE.finditer(joined):
        remaining = int(match.group(1))
        total = int(match.group(2))
        if total <= 0 or remaining < 0 or remaining > total:
            continue
        if total > FATIGUE_DRINK_MAX_ATTEMPTS:
            continue
        context = joined[max(0, match.start() - 28) : match.end() + 28]
        priority = 0 if any(keyword in context for keyword in FATIGUE_DRINK_INFO_COUNT_KEYWORDS) else 1
        candidates.append((priority, match.start(), remaining, total, context))
    if candidates:
        _, _, remaining, total, context = sorted(candidates, key=lambda item: (item[0], item[1]))[0]
        return {"remaining": remaining, "total": total, "texts": texts[:30], "context": context}

    if any(keyword in joined for keyword in ("次数不足", "次数已用完", "没有可用次数", "今日次数已用完", "每日次数已用完")):
        return {"remaining": 0, "total": None, "texts": texts[:30]}
    return None


def _manual_two_city_drink_info_target_from_entries(entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    candidates: list[tuple[int, int, int]] = []
    for entry in entries:
        text = clean_text(entry.get("text"))
        if not text:
            continue
        cx = float(entry.get("center_x") or 0)
        cy = float(entry.get("center_y") or 0)
        if cx <= 0 or cy <= 0:
            continue
        if "前往休息区" in text:
            candidates.append((0, int(cx + 45), int(cy - 60)))
        elif "RESTAREA" in text or "休息区" in text:
            candidates.append((1, int(cx + 45), int(cy + 28)))
        elif "REST" in text or "AREA" in text:
            candidates.append((2, int(cx + 55), int(cy + 24)))
    if not candidates:
        return None
    _, x, y = sorted(candidates, key=lambda item: item[0])[0]
    return max(1020, min(1238, x)), max(150, min(430, y))


def _manual_two_city_leg_required_fatigue(leg: dict[str, Any]) -> int:
    if not isinstance(leg, dict):
        return 0
    for key in ("tired", "fatigue", "required_fatigue"):
        value = _fatigue_int(leg.get(key), 0)
        if value > 0:
            return value
    required, _ = _manual_two_city_route_required_fatigue(leg.get("buy_city"), leg.get("sell_city"))
    return required


def _manual_two_city_required_fatigue_with_buffer(required: int) -> int:
    required = _fatigue_int(required, 0)
    if required <= 0:
        return 0
    return required + MANUAL_TWO_CITY_FATIGUE_SAFETY_BUFFER


def _manual_two_city_next_required_fatigue(
    state: dict[str, Any] | None = None,
    *,
    phase: str | None = None,
) -> int:
    current_state = state or _manual_two_city_state()
    override = _fatigue_int(current_state.get("strength_recovery_required"), 0)
    if override > 0:
        return override
    result = current_state.get("result") if isinstance(current_state.get("result"), dict) else {}
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    legs = summary.get("legs") if isinstance(summary.get("legs"), list) else []
    legs = [leg for leg in legs if isinstance(leg, dict)]
    if not legs:
        return 0
    try:
        active_index = int(current_state.get("active_leg_index") or 0)
    except (TypeError, ValueError):
        active_index = 0
    active_index = min(max(active_index, 0), len(legs) - 1)
    current_phase = str(phase or current_state.get("trade_phase") or "buy").strip().lower()
    if current_phase == "sell":
        next_index = active_index + 1
        if next_index >= len(legs):
            if not _manual_two_city_until_fatigue_exhausted(current_state):
                return 0
            next_index = 0
        return _manual_two_city_required_fatigue_with_buffer(_manual_two_city_leg_required_fatigue(legs[next_index]))
    return _manual_two_city_required_fatigue_with_buffer(_manual_two_city_leg_required_fatigue(legs[active_index]))


def _manual_two_city_sell_haggle_required_fatigue(target_percent: Any) -> int:
    target = _manual_two_city_haggle_count(target_percent)
    if target <= 0:
        return 0
    return int(math.ceil(target / 10)) * 8 + 16


def _manual_two_city_pre_buy_cleanup_required_fatigue(
    state: dict[str, Any],
    leg: dict[str, Any],
    raise_percent: Any,
) -> int:
    route_required = _manual_two_city_next_required_fatigue(state, phase="buy")
    if route_required <= 0:
        route_required = _manual_two_city_required_fatigue_with_buffer(_manual_two_city_leg_required_fatigue(leg))
    haggle_required = _manual_two_city_sell_haggle_required_fatigue(raise_percent)
    if route_required <= 0 and haggle_required > 0:
        haggle_required += MANUAL_TWO_CITY_FATIGUE_SAFETY_BUFFER
    return max(route_required, haggle_required)


def _manual_two_city_required_fatigue_for_strength_check(
    state: dict[str, Any],
    *,
    phase: str,
) -> int:
    current_phase = str(phase or state.get("trade_phase") or "buy").strip().lower()
    if current_phase == "sell" and state.get("pre_buy_cleanup"):
        required = _fatigue_int(state.get("pre_buy_cleanup_strength_required"), 0)
        if required > 0:
            return required
        return _manual_two_city_pre_buy_cleanup_required_fatigue(
            state,
            _manual_two_city_active_leg(),
            state.get("pre_buy_cleanup_raise_percent"),
        )
    return _manual_two_city_next_required_fatigue(state, phase=current_phase)


def _manual_two_city_strength_recovery_state(state: dict[str, Any] | None = None) -> dict[str, Any]:
    current_state = state or _manual_two_city_state()
    recovery = current_state.setdefault("strength_recovery", {})
    if not isinstance(recovery, dict):
        recovery = {}
        current_state["strength_recovery"] = recovery
    recovery.setdefault("used", {})
    recovery.setdefault("unavailable", {})
    recovery.setdefault("skip_logged", {})
    recovery.setdefault("pending", {})
    recovery.setdefault("huashi_total_cost", 0)
    recovery.setdefault("huashi_unknown_cost_count", 0)
    return recovery


def _manual_two_city_recovery_used_count(recovery: dict[str, Any], resource: str) -> int:
    used = recovery.setdefault("used", {})
    try:
        return int(used.get(resource) or 0)
    except (TypeError, ValueError):
        return 0


def _manual_two_city_recovery_mark_unavailable(recovery: dict[str, Any], resource: str, reason: str) -> None:
    recovery.setdefault("unavailable", {})[resource] = reason


def _manual_two_city_recovery_log_skip_once(
    state: dict[str, Any],
    resource: str,
    reason: str,
    *,
    level: str = "info",
) -> None:
    recovery = _manual_two_city_strength_recovery_state(state)
    skip_logged = recovery.setdefault("skip_logged", {})
    key = f"{resource}:{reason}"
    if skip_logged.get(key):
        return
    skip_logged[key] = True
    _append_user_log(
        MANUAL_TWO_CITY_TASK_ENTRY,
        f"跑商补疲劳：跳过 {resource}，{reason}。",
        level=level,
        event="manual_two_city_strength_resource_skipped",
        data={"resource": resource, "reason": reason},
    )


def _manual_two_city_medicine_limit_state(
    state: dict[str, Any],
    resource: str,
    *,
    huashi: bool = False,
) -> tuple[bool, str, int, int]:
    if not _fatigue_bool(state.get("use_fatigue_medicine"), False):
        return False, "疲劳药/桦石选项关闭", 0, 0
    recovery = _manual_two_city_strength_recovery_state(state)
    used = _manual_two_city_recovery_used_count(recovery, resource)
    if recovery.setdefault("unavailable", {}).get(resource):
        return False, "本轮已判定不可用", -1, used
    if huashi:
        limit = _fatigue_normalize_limit(state.get("huashi_use_limit"), huashi=True)
        if used >= HUASHI_MAX_USE_LIMIT:
            return False, f"已达最高 {HUASHI_MAX_USE_LIMIT} 次", limit, used
    else:
        key = FATIGUE_MEDICINE_RESOURCES.get(resource, {}).get("limit_key")
        limit = _fatigue_normalize_limit(state.get(key))
    if limit == 0:
        return False, "配置为不使用", limit, used
    return True, "", limit, used


def _manual_two_city_strength_recovery_methods(state: dict[str, Any]) -> list[str]:
    methods: list[str] = []
    if _fatigue_bool(state.get("use_bento"), False):
        methods.append("便当")
    if _fatigue_bool(state.get("use_fatigue_medicine"), False):
        methods.extend(["体力药", "桦石"])
    return methods


def _manual_two_city_strength_gap(status: dict[str, int] | None, required: int) -> tuple[int, int]:
    remaining = int(status.get("remaining") or 0) if isinstance(status, dict) else 0
    return remaining, max(0, int(required or 0) - remaining)


def _manual_two_city_resource_restore(resource: str, resource_type: str) -> int:
    if resource_type == "huashi":
        return HUASHI_RESTORE_DEFAULT
    return int(FATIGUE_MEDICINE_RESOURCES.get(resource, {}).get("restore") or 0)


def _manual_two_city_medicine_target_count(
    state: dict[str, Any],
    resource: str,
    *,
    required: int,
    status: dict[str, int] | None,
    inventory: int | None,
    limit: int,
    used: int,
) -> dict[str, Any]:
    restore = max(1, _manual_two_city_resource_restore(resource, "medicine"))
    remaining, gap = _manual_two_city_strength_gap(status, required)
    if gap > 0:
        target = int(math.ceil(gap / restore))
        reason = "gap"
    elif isinstance(status, dict):
        target = 0
        reason = "enough"
    else:
        target = 1
        reason = "unknown_status"

    remaining_limit: int | None
    if limit < 0:
        remaining_limit = None
    else:
        # The in-memory task option is decremented after each use, so a positive
        # finite limit is already the remaining use count for this run.
        remaining_limit = max(0, limit)
        target = min(target, remaining_limit)
    if inventory is not None:
        target = min(target, max(0, inventory))
    if target > FATIGUE_MEDICINE_POPUP_MAX_STEPS:
        target = FATIGUE_MEDICINE_POPUP_MAX_STEPS

    use_max = bool(
        target > 1
        and inventory is not None
        and target >= inventory
        and (remaining_limit is None or target <= remaining_limit)
    )
    return {
        "target_count": max(0, int(target)),
        "restore": restore,
        "remaining": remaining,
        "gap": gap,
        "reason": reason,
        "remaining_limit": remaining_limit,
        "inventory": inventory,
        "use_max": use_max,
    }


def _manual_two_city_config_remaining_count(
    state: dict[str, Any],
    resource: str,
    resource_type: str,
) -> tuple[int, dict[str, Any]]:
    huashi = resource_type == "huashi"
    allowed, skip_reason, limit, used = _manual_two_city_medicine_limit_state(state, resource, huashi=huashi)
    payload = {
        "resource": resource,
        "resource_type": resource_type,
        "allowed": allowed,
        "skip_reason": skip_reason,
        "limit": limit,
        "used": used,
        "count": 0,
    }
    if not allowed:
        return 0, payload
    if huashi:
        max_left = max(0, HUASHI_MAX_USE_LIMIT - used)
        count = max_left if limit < 0 else min(max_left, max(0, limit))
    elif limit < 0:
        # 无限配置只代表脚本不限制次数；理论预算按“足以补齐一次单程”处理。
        count = 999
    else:
        count = max(0, limit)
    payload["count"] = count
    return count, payload


def _manual_two_city_theoretical_medicine_restore_budget(
    state: dict[str, Any],
    *,
    gap: int,
) -> dict[str, Any]:
    total_restore = 0
    details: list[dict[str, Any]] = []
    for resource in FATIGUE_MEDICINE_RESOURCES:
        count, payload = _manual_two_city_config_remaining_count(state, resource, "medicine")
        restore = _manual_two_city_resource_restore(resource, "medicine")
        if count >= 999 and gap > 0 and restore > 0:
            count = max(1, math.ceil(gap / restore))
            payload["count_for_budget"] = count
        total_restore += count * restore
        payload["restore"] = restore
        payload["restore_budget"] = count * restore
        details.append(payload)
    count, payload = _manual_two_city_config_remaining_count(state, "桦石", "huashi")
    restore = _manual_two_city_resource_restore("桦石", "huashi")
    total_restore += count * restore
    payload["restore"] = restore
    payload["restore_budget"] = count * restore
    details.append(payload)
    return {"restore_budget": total_restore, "details": details}


def _manual_two_city_mark_recovery_budget_insufficient(
    state: dict[str, Any],
    *,
    phase: str,
    status: dict[str, int] | None,
    required: int,
    budget: dict[str, Any],
    reason: str,
) -> None:
    recovery = _manual_two_city_strength_recovery_state(state)
    state["strength_recovery_unavailable"] = True
    state["strength_recovery_unavailable_logged"] = True
    recovery.setdefault("unavailable", {})["体力药/桦石"] = reason
    remaining, gap = _manual_two_city_strength_gap(status, required)
    _append_user_log(
        _manual_two_city_current_task_entry(state),
        (
            f"跑商补疲劳：剩余疲劳 {remaining}，安全需求还差 {gap}，"
            f"体力药/桦石可补 {int(budget.get('restore_budget') or 0)}，不足以完成下一段，停止消耗恢复资源。"
        ),
        level="warning",
        event="manual_two_city_strength_recovery_budget_insufficient",
        data={
            "phase": phase,
            "status": status,
            "required": required,
            "remaining": remaining,
            "gap": gap,
            "reason": reason,
            "budget": budget,
            "recovery": _manual_two_city_strength_recovery_state(state),
        },
    )
    _manual_two_city_mark_strength_stop(
        state,
        phase=phase,
        status=status,
        required=required,
        reason=reason,
        leg=_manual_two_city_active_leg(),
    )


def _manual_two_city_probe_medicine_actual_budget(
    context: Context,
    state: dict[str, Any],
    *,
    status: dict[str, int] | None,
    required: int,
    phase: str,
) -> bool:
    remaining, gap = _manual_two_city_strength_gap(status, required)
    if gap <= 0:
        return True

    theoretical = _manual_two_city_theoretical_medicine_restore_budget(state, gap=gap)
    if int(theoretical.get("restore_budget") or 0) < gap:
        _manual_two_city_mark_recovery_budget_insufficient(
            state,
            phase=phase,
            status=status,
            required=required,
            budget={**theoretical, "kind": "configured"},
            reason="configured_budget_insufficient",
        )
        return False

    actual_restore = 0
    actual_details: list[dict[str, Any]] = []
    recovery = _manual_two_city_strength_recovery_state(state)
    medicine_count_rois = {
        "提神棒棒糖": [690, 248, 75, 75],
        "提神口香糖": [930, 248, 85, 75],
        "仙人掌提神跳糖": [690, 508, 75, 75],
    }

    def read_int_from_roi(name: str, roi: list[int]) -> tuple[int | None, list[str]]:
        _, _, texts = _manual_two_city_ocr_entries(
            context,
            name,
            r"\d{1,4}",
            roi=roi,
        )
        values: list[int] = []
        for text in texts:
            for match in re.finditer(r"\d{1,4}", clean_text(text).replace("O", "0").replace("o", "0")):
                values.append(int(match.group()))
        return (values[0] if values else None), texts

    for resource in FATIGUE_MEDICINE_RESOURCES:
        allowed, skip_reason, limit, used = _manual_two_city_medicine_limit_state(state, resource)
        restore = _manual_two_city_resource_restore(resource, "medicine")
        detail = {
            "resource": resource,
            "resource_type": "medicine",
            "allowed": allowed,
            "skip_reason": skip_reason,
            "limit": limit,
            "used": used,
            "restore": restore,
            "inventory": None,
            "actual_count": 0,
            "restore_budget": 0,
        }
        if not allowed:
            actual_details.append(detail)
            continue

        resource_key = {
            "提神棒棒糖": "Lollipop",
            "提神口香糖": "Gum",
            "仙人掌提神跳糖": "CactusCandy",
        }.get(resource, "Medicine")
        inventory, inventory_texts = read_int_from_roi(
            f"ManualTwoCityStrengthBudget{resource_key}Count",
            medicine_count_rois.get(resource, [0, 0, 0, 0]),
        )
        detail["inventory"] = inventory
        detail["texts"] = inventory_texts[:20]
        card_unavailable, card_texts = _manual_two_city_medicine_card_unavailable(context, resource, resource_key)
        detail["card_texts"] = card_texts[:20]
        if card_unavailable:
            reason = "卡片不可用"
            _manual_two_city_recovery_mark_unavailable(recovery, resource, reason)
            detail["reason"] = reason
            actual_details.append(detail)
            continue
        if inventory is None or inventory <= 0:
            reason = "页面数量为 0" if inventory == 0 else "未识别页面数量"
            if inventory == 0:
                _manual_two_city_recovery_mark_unavailable(recovery, resource, reason)
            detail["reason"] = reason
            actual_details.append(detail)
            continue

        config_count, config_payload = _manual_two_city_config_remaining_count(state, resource, "medicine")
        if inventory is None:
            actual_count = config_count if config_count < 999 else max(1, math.ceil(gap / restore))
        else:
            actual_count = min(config_count, max(0, inventory))
        if config_count >= 999 and inventory is not None:
            actual_count = max(0, inventory)
        restore_budget = max(0, actual_count) * restore
        actual_restore += restore_budget
        detail.update(
            {
                "actual_count": actual_count,
                "restore_budget": restore_budget,
                "config": config_payload,
            }
        )
        actual_details.append(detail)

    allowed, skip_reason, limit, used = _manual_two_city_medicine_limit_state(state, "桦石", huashi=True)
    restore = HUASHI_RESTORE_DEFAULT
    detail = {
        "resource": "桦石",
        "resource_type": "huashi",
        "allowed": allowed,
        "skip_reason": skip_reason,
        "limit": limit,
        "used": used,
        "restore": restore,
        "daily_remaining": None,
        "actual_count": 0,
        "restore_budget": 0,
    }
    if allowed:
        _, _, daily_texts = _manual_two_city_ocr_entries(
            context,
            "ManualTwoCityStrengthBudgetHuashiDaily",
            ["每日限购", "限购", r"\d+\s*/\s*8"],
            roi=[790, 385, 230, 90],
        )
        daily_remaining = huashi_daily_remaining(daily_texts) if daily_texts else None
        detail["daily_remaining"] = daily_remaining
        detail["daily_texts"] = daily_texts[:20]
        if daily_remaining is None:
            detail["reason"] = "daily_remaining_missing"
        elif daily_remaining <= 0:
            _manual_two_city_recovery_mark_unavailable(recovery, "桦石", "次数不足")
            detail["reason"] = "exhausted"
        else:
            config_count, config_payload = _manual_two_city_config_remaining_count(state, "桦石", "huashi")
            actual_count = min(config_count, max(0, daily_remaining))
            restore_budget = max(0, actual_count) * restore
            actual_restore += restore_budget
            detail.update(
                {
                    "actual_count": actual_count,
                    "restore_budget": restore_budget,
                    "config": config_payload,
                }
            )
    actual_details.append(detail)

    actual_budget = {
        "kind": "actual",
        "remaining": remaining,
        "gap": gap,
        "restore_budget": actual_restore,
        "details": actual_details,
        "theoretical": theoretical,
    }
    if actual_restore < gap:
        unknown_resources = [
            str(detail.get("resource"))
            for detail in actual_details
            if detail.get("allowed")
            and (
                (
                    str(detail.get("resource_type") or "") == "medicine"
                    and detail.get("inventory") is None
                )
                or (
                    str(detail.get("resource_type") or "") == "huashi"
                    and detail.get("daily_remaining") is None
                )
                or str(detail.get("reason") or "") in {"未识别页面数量", "daily_remaining_missing"}
            )
        ]
        if unknown_resources:
            _append_user_log(
                _manual_two_city_current_task_entry(state),
                (
                    "跑商补疲劳：疲劳药/桦石页面次数未完全读到，"
                    "不按 0 次处理，继续逐个尝试可用恢复资源。"
                ),
                level="warning",
                event="manual_two_city_strength_recovery_budget_unknown",
                data={
                    "phase": phase,
                    "status": status,
                    "required": required,
                    "unknown_resources": unknown_resources,
                    "budget": actual_budget,
                },
            )
            return True
        _manual_two_city_mark_recovery_budget_insufficient(
            state,
            phase=phase,
            status=status,
            required=required,
            budget=actual_budget,
            reason="actual_budget_insufficient",
        )
        return False

    _append_user_log(
        _manual_two_city_current_task_entry(state),
        f"跑商补疲劳：实际库存/次数预算可补 {actual_restore}，足够补齐安全需求缺口 {gap}，开始使用恢复资源。",
        event="manual_two_city_strength_recovery_budget_enough",
        data={"phase": phase, "status": status, "required": required, "budget": actual_budget},
    )
    return True


def _manual_two_city_resource_used(
    state: dict[str, Any],
    resource: str,
    resource_type: str,
    *,
    count: int = 1,
    pending: dict[str, Any] | None = None,
) -> None:
    recovery = _manual_two_city_strength_recovery_state(state)
    task_entry = _manual_two_city_current_task_entry(state)
    state["strength_recovery_unavailable"] = False
    state["strength_recovery_unavailable_logged"] = False
    used = recovery.setdefault("used", {})
    actual_count = max(1, int(count or 1))
    used[resource] = int(used.get(resource) or 0) + actual_count
    config_update = _fatigue_decrement_option_config_limit(
        resource,
        resource_type,
        actual_count,
        task_name=task_entry,
        option_name="ManualTwoCityMedicineLimits",
    )
    state_limit_update: dict[str, Any] | None = None
    limit_key = _fatigue_limit_key_for_resource(resource, resource_type)
    if limit_key and limit_key in state:
        current_limit = _fatigue_int(state.get(limit_key), 0)
        if current_limit > 0:
            new_limit = max(0, current_limit - actual_count)
            state[limit_key] = new_limit
            state_limit_update = {"key": limit_key, "old_value": current_limit, "new_value": new_limit}
            pending_values = state.setdefault("pending_medicine_option_values", {})
            if isinstance(pending_values, dict):
                pending_values[limit_key] = new_limit
    config_note = _fatigue_config_decrement_note(config_update)
    delayed_config_update: dict[str, Any] | None = None
    forced_config_rewrite: dict[str, Any] | None = None
    pending_option_values = state.get("pending_medicine_option_values")
    if isinstance(pending_option_values, dict) and pending_option_values:
        forced_config_rewrite = _fatigue_rewrite_option_config_values_with_retry(
            task_name=task_entry,
            option_name="ManualTwoCityMedicineLimits",
            values=pending_option_values,
        )
        delayed_config_update = forced_config_rewrite.get("delayed")
        if not isinstance(delayed_config_update, dict):
            delayed_config_update = _fatigue_schedule_delayed_option_config_write(
                task_name=task_entry,
                option_name="ManualTwoCityMedicineLimits",
                values=pending_option_values,
                delays=[3.0, 30.0, 180.0, 600.0],
            )
    if resource_type == "huashi":
        notice = pending or {}
        cost = notice.get("cost")
        if isinstance(cost, int):
            recovery["huashi_total_cost"] = int(recovery.get("huashi_total_cost") or 0) + cost
            suffix = f"，本次消耗 {cost}，累计消耗 {recovery['huashi_total_cost']} 桦石"
        else:
            recovery["huashi_unknown_cost_count"] = int(recovery.get("huashi_unknown_cost_count") or 0) + 1
            suffix = "，本次消耗未能精确读取"
    elif resource_type == "medicine":
        suffix = f" {actual_count} 次，本轮累计 {used[resource]} 次"
    else:
        suffix = f"，本轮累计 {used[resource]} 次"
    if config_note:
        suffix += config_note
    _append_user_log(
        task_entry,
        f"跑商补疲劳：已使用 {resource}{suffix}。",
        event="manual_two_city_strength_resource_used",
        data={
            "resource": resource,
            "resource_type": resource_type,
            "count": actual_count,
            "used": dict(used),
            "pending": pending or {},
            "config_update": config_update,
            "forced_config_rewrite": forced_config_rewrite,
            "delayed_config_update": delayed_config_update,
            "state_limit_update": state_limit_update,
        },
    )


def _manual_two_city_read_strength_status(context: Context, name: str) -> tuple[dict[str, int] | None, list[str]]:
    _, _, texts = _manual_two_city_ocr_entries(
        context,
        name,
        TRADE_STRENGTH_STATUS_TEXT,
        roi=TRADE_STRENGTH_STATUS_ROI,
    )
    status = strength_status_from_texts(texts)
    if status:
        return status, texts
    _, _, fallback_texts = _manual_two_city_ocr_entries(
        context,
        f"{name}Full",
        ["疲劳值", TRADE_STRENGTH_STATUS_TEXT],
        roi=[780, 0, 500, 95],
    )
    status = strength_status_from_texts(fallback_texts)
    if status:
        return status, fallback_texts
    _, _, fatigue_page_texts = _manual_two_city_ocr_entries(
        context,
        f"{name}FatiguePage",
        ["列车长疲劳值", "疲劳值", TRADE_STRENGTH_STATUS_TEXT],
        roi=[20, 480, 430, 220],
    )
    return strength_status_from_texts(fatigue_page_texts), fatigue_page_texts or fallback_texts or texts


def _manual_two_city_read_strength_status_with_retry(
    context: Context,
    name: str,
    *,
    attempts: int = 3,
    delay: float = 0.45,
) -> tuple[dict[str, int] | None, list[str]]:
    all_texts: list[str] = []
    for index in range(max(1, attempts)):
        if index > 0:
            time.sleep(max(0.0, delay))
        status, texts = _manual_two_city_read_strength_status(context, f"{name}{index + 1:03d}")
        all_texts.extend(texts)
        if status:
            return status, list(dict.fromkeys(all_texts))
    return None, list(dict.fromkeys(all_texts))


def _manual_two_city_strength_enough(status: dict[str, int] | None, required: int) -> bool:
    return bool(status and required > 0 and int(status.get("remaining") or 0) >= required)


def _manual_two_city_parse_buy_page_cargo_load(
    entries: list[dict[str, Any]],
    *,
    roi: list[int] | None = None,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    roi_x, roi_y, roi_w, roi_h = roi or BUY_PAGE_CARGO_LOAD_ROI

    def add_candidate(used: int, capacity: int, raw_text: str, normalized_text: str, entry: dict[str, Any]) -> None:
        if capacity <= 0 or used < 0:
            return
        if used > capacity * 2:
            return
        x = int(float(entry.get("x") or 0))
        y = int(float(entry.get("y") or 0))
        candidates.append(
            {
                "used": used,
                "capacity": capacity,
                "ratio": used / capacity,
                "text": raw_text,
                "normalized_text": normalized_text,
                "box": [x, y, int(entry.get("w") or 0), int(entry.get("h") or 0)],
            }
        )

    for entry in entries:
        try:
            x = float(entry.get("x") or 0)
            y = float(entry.get("y") or 0)
        except (TypeError, ValueError):
            continue
        if not (roi_x <= x <= roi_x + roi_w and roi_y <= y <= roi_y + roi_h):
            continue
        raw_text = str(entry.get("text") or "")
        text = clean_text(raw_text)
        text_variants = {
            text,
            text.replace(".", "").replace("·", "").replace("。", ""),
            text.replace("／", "/").replace("|", "/").replace("I", "/").replace("l", "/"),
        }
        for candidate_text in text_variants:
            for match in re.finditer(r"(\d{1,5})\s*/\s*[^\d]{0,3}(\d{1,5})\+?", candidate_text):
                used = int(match.group(1))
                capacity = int(match.group(2))
                add_candidate(used, capacity, raw_text, candidate_text, entry)
            digits = re.sub(r"\D+", "", candidate_text)
            if len(digits) < 4 or "%" in candidate_text:
                continue
            for split in range(1, len(digits)):
                used = int(digits[:split])
                capacity = int(digits[split:])
                if 100 <= capacity <= 9999:
                    add_candidate(used, capacity, raw_text, f"{digits[:split]}/{digits[split:]}", entry)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["capacity"], item["used"]))


def _manual_two_city_read_buy_page_cargo_load(
    context: Context,
    entries: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[str], bool]:
    cargo_load = _manual_two_city_parse_buy_page_cargo_load(entries)
    if cargo_load is not None:
        return cargo_load, [], False
    _hit, probe_entries, probe_texts = _manual_two_city_ocr_entries(
        context,
        "ManualTwoCityBuyPageCargoLoadProbe",
        r"\d{1,5}\s*/\s*\d{1,5}",
        roi=BUY_PAGE_CARGO_LOAD_PROBE_ROI,
    )
    cargo_load = _manual_two_city_parse_buy_page_cargo_load(probe_entries, roi=BUY_PAGE_CARGO_LOAD_PROBE_ROI)
    return cargo_load, probe_texts, True


def _manual_two_city_planned_goods_total(leg: dict[str, Any] | None) -> int:
    if not isinstance(leg, dict):
        return 0
    total = 0
    for item in leg.get("goods_detail") or []:
        if not isinstance(item, dict):
            continue
        try:
            total += max(0, int(item.get("num") or item.get("buyLot") or 0))
        except (TypeError, ValueError):
            continue
    return total


def _manual_two_city_probe_buy_page_cargo_load(
    context: Context,
    name: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    all_texts: list[str] = []
    for index, roi in enumerate((BUY_PAGE_CARGO_LOAD_PROBE_ROI, BUY_PAGE_CARGO_LOAD_ROI), start=1):
        _hit, entries, texts = _manual_two_city_ocr_entries(
            context,
            f"{name}{index:03d}",
            r".+",
            roi=roi,
        )
        all_texts.extend(texts)
        cargo_load = _manual_two_city_parse_buy_page_cargo_load(entries, roi=roi)
        if cargo_load is not None:
            return cargo_load, all_texts
    return None, all_texts


def _known_buy_goods_for_city(city_name: Any) -> list[str]:
    city = normalize_city_name(str(city_name or "").strip())
    if not city:
        return []
    return _all_buy_goods_by_city().get(city, [])


def _manual_two_city_product_status_by_city_for_account(account: dict[str, Any]) -> dict[str, dict[str, str]]:
    trade = account.get("trade") if isinstance(account.get("trade"), dict) else {}
    planner = account.get("planner") if isinstance(account.get("planner"), dict) else {}
    return _merge_product_status_by_city(
        trade.get("product_status_by_city"),
        planner.get("product_status_by_city"),
        trade.get("product_unlock_status_by_city"),
        planner.get("product_unlock_status_by_city"),
        include_defaults=True,
    )


def _manual_two_city_persist_account_product_status_defaults(path: Path, account: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(account, dict) or not account:
        return account if isinstance(account, dict) else {}
    trade = account.setdefault("trade", {})
    if not isinstance(trade, dict):
        trade = {}
        account["trade"] = trade
    planner = account.setdefault("planner", {})
    if not isinstance(planner, dict):
        planner = {}
        account["planner"] = planner
    status_by_city = _manual_two_city_product_status_by_city_for_account(account)
    locked_only = _locked_product_status_by_city(status_by_city)
    if (
        trade.get("product_status_by_city") == status_by_city
        and planner.get("product_status_by_city") == status_by_city
        and trade.get("product_unlock_status_by_city") == locked_only
        and planner.get("product_unlock_status_by_city") == locked_only
    ):
        return account
    trade["product_status_by_city"] = copy.deepcopy(status_by_city)
    trade["product_unlock_status_by_city"] = copy.deepcopy(locked_only)
    planner["product_status_by_city"] = copy.deepcopy(status_by_city)
    planner["product_unlock_status_by_city"] = copy.deepcopy(locked_only)
    completed_parts = set(account.get("completed_parts") or [])
    completed_parts.add("read_product_status")
    account["completed_parts"] = sorted(completed_parts)
    account["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    account.setdefault("_source", {})["product_status_migrated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(account, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass
    return account


def _manual_two_city_product_status_for_city(city_name: Any) -> dict[str, str]:
    state = _manual_two_city_state()
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    account = _manual_two_city_load_account_config_for_result(result)[1]
    city = normalize_city_name(str(city_name or "").strip())
    return (_manual_two_city_product_status_by_city_for_account(account).get(city) or {}) if city else {}


PRODUCT_STATUS_LABELS = {
    PRODUCT_STATUS_NORMAL: "正常",
    PRODUCT_STATUS_LOCKED: "未解锁",
    PRODUCT_STATUS_MISSING: "未扫描到",
    PRODUCT_STATUS_NEVER_SCANNED: "未扫描过",
}


def _latest_account_config() -> tuple[Path | None, dict[str, Any]]:
    accounts_dir = PROJECT_ROOT / "config" / "accounts"
    if not accounts_dir.exists():
        return None, {}
    candidates = [
        path
        for path in accounts_dir.glob("*.json")
        if path.is_file() and _is_real_account_config_path(path)
    ]
    if not candidates:
        candidates = [
            path
            for path in accounts_dir.glob("*.json")
            if path.is_file() and _is_real_account_config_path(path)
        ]
    if not candidates:
        return None, {}
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return path, {}
    account = payload if isinstance(payload, dict) else {}
    if account:
        account = _manual_two_city_persist_account_product_status_defaults(path, account)
    return path, account


def _product_status_counts(status_by_city: dict[str, dict[str, str]]) -> dict[str, int]:
    counts = {status: 0 for status in PRODUCT_STATUSES}
    for goods in status_by_city.values():
        for status in goods.values():
            counts[_normalize_product_status(status)] = counts.get(_normalize_product_status(status), 0) + 1
    return counts


def _product_status_city_summary(status_by_city: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for city, goods in status_by_city.items():
        counts = {status: 0 for status in PRODUCT_STATUSES}
        for status in goods.values():
            counts[_normalize_product_status(status)] = counts.get(_normalize_product_status(status), 0) + 1
        summary.append(
            {
                "city": city,
                "total": len(goods),
                "normal": counts.get(PRODUCT_STATUS_NORMAL, 0),
                "locked": counts.get(PRODUCT_STATUS_LOCKED, 0),
                "missing": counts.get(PRODUCT_STATUS_MISSING, 0),
                "never_scanned": counts.get(PRODUCT_STATUS_NEVER_SCANNED, 0),
                "abnormal": (
                    counts.get(PRODUCT_STATUS_LOCKED, 0)
                    + counts.get(PRODUCT_STATUS_MISSING, 0)
                    + counts.get(PRODUCT_STATUS_NEVER_SCANNED, 0)
                ),
            }
        )
    return sorted(summary, key=lambda item: (-int(item["abnormal"]), str(item["city"])))


def _write_product_status_report(
    account_path: Path,
    account: dict[str, Any],
    *,
    operation: str,
    changed_count: int = 0,
    city_filter: str = "",
) -> dict[str, Any]:
    uid = _safe_account_uid(account.get("uid") or account_path.stem)
    status_by_city = _manual_two_city_product_status_by_city_for_account(account)
    counts = _product_status_counts(status_by_city)
    city_summary = _product_status_city_summary(status_by_city)
    markdown_path = account_path.with_name(f"{account_path.stem}.product_status_report.md")
    json_path = account_path.with_name(f"{account_path.stem}.product_status_report.json")
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# 商品状态报告",
        "",
        f"- UID: {uid}",
        f"- 配置文件: {account_path}",
        f"- 生成时间: {generated_at}",
        f"- 操作: {operation}",
        f"- 本次修改: {changed_count}",
    ]
    if city_filter:
        lines.append(f"- 城市筛选: {city_filter}")
    lines.extend(
        [
            "",
            "## 汇总",
            "",
            "| 状态 | 数量 |",
            "| --- | ---: |",
            f"| 正常 | {counts.get(PRODUCT_STATUS_NORMAL, 0)} |",
            f"| 未解锁 | {counts.get(PRODUCT_STATUS_LOCKED, 0)} |",
            f"| 未扫描到 | {counts.get(PRODUCT_STATUS_MISSING, 0)} |",
            f"| 未扫描过 | {counts.get(PRODUCT_STATUS_NEVER_SCANNED, 0)} |",
            "",
            "## 城市概览",
            "",
            "| 城市 | 正常 | 未解锁 | 未扫描到 | 未扫描过 | 总数 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in city_summary:
        lines.append(
            f"| {item['city']} | {item['normal']} | {item['locked']} | "
            f"{item['missing']} | {item['never_scanned']} | {item['total']} |"
        )

    lines.extend(["", "## 异常明细", ""])
    for city, goods in status_by_city.items():
        abnormal = {
            PRODUCT_STATUS_LOCKED: [],
            PRODUCT_STATUS_MISSING: [],
            PRODUCT_STATUS_NEVER_SCANNED: [],
        }
        for good, status in goods.items():
            normalized = _normalize_product_status(status)
            if normalized in abnormal:
                abnormal[normalized].append(good)
        if not any(abnormal.values()):
            continue
        lines.append(f"### {city}")
        for status in (PRODUCT_STATUS_LOCKED, PRODUCT_STATUS_MISSING, PRODUCT_STATUS_NEVER_SCANNED):
            goods_text = "、".join(abnormal[status]) if abnormal[status] else "-"
            lines.append(f"- {PRODUCT_STATUS_LABELS[status]}: {goods_text}")
        lines.append("")

    payload = {
        "uid": uid,
        "account_config": str(account_path),
        "generated_at": generated_at,
        "operation": operation,
        "changed_count": changed_count,
        "city_filter": city_filter,
        "counts": counts,
        "city_summary": city_summary,
        "status_by_city": status_by_city,
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
    }
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload


def _manual_two_city_configured_locked_goods(city_name: Any) -> list[str]:
    city = normalize_city_name(str(city_name or "").strip())
    city_status = _manual_two_city_product_status_for_city(city)
    known = set(_known_buy_goods_for_city(city))
    goods = [
        str(good)
        for good, status in city_status.items()
        if status in PRODUCT_PLANNER_BLOCKED_STATUSES
    ]
    return sorted(goods, key=lambda good: (good not in known, good))


def _manual_two_city_load_account_config_for_result(result: dict[str, Any] | None = None) -> tuple[Path, dict[str, Any]]:
    current_result = result if isinstance(result, dict) else {}
    account_path_text = str(current_result.get("account_config") or "").strip()
    if account_path_text:
        account_path = Path(account_path_text)
        if _is_real_account_config_path(account_path):
            try:
                account = json.loads(account_path.read_text(encoding="utf-8"))
                if isinstance(account, dict) and account:
                    return account_path, _manual_two_city_persist_account_product_status_defaults(account_path, account)
            except (OSError, json.JSONDecodeError):
                pass
    uid = _safe_account_uid(current_result.get("uid") or _PROFILE_UID)
    path = _account_config_path(uid)
    account = _load_account_config(uid)
    if account:
        account = _manual_two_city_persist_account_product_status_defaults(path, account)
    return path, account


def _manual_two_city_known_account_context(result: dict[str, Any] | None = None) -> tuple[Path, dict[str, Any], str, bool]:
    current_result = result if isinstance(result, dict) else {}
    path, account = _manual_two_city_load_account_config_for_result(current_result)
    account_uid = account.get("uid") if isinstance(account, dict) else None
    uid = _safe_account_uid(account_uid or current_result.get("uid") or _PROFILE_UID or path.stem)
    has_context = bool(account) and uid != "unknown" and _is_real_account_config_path(path)
    return path, account, uid, has_context


def _manual_two_city_update_product_status(
    city_name: Any,
    good_name: Any,
    status: Any,
    *,
    reason: str,
) -> dict[str, Any]:
    city = normalize_city_name(str(city_name or "").strip())
    good = str(good_name or "").strip()
    product_status = _normalize_product_status(status)
    if not city or not good:
        return {"changed": False, "reason": "missing_city_or_good"}
    state = _manual_two_city_state()
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    path, account = _manual_two_city_load_account_config_for_result(result)
    uid = _safe_account_uid(account.get("uid") or result.get("uid") or _PROFILE_UID)
    if not account:
        return {"changed": False, "reason": "missing_account_config", "uid": uid}

    trade = account.setdefault("trade", {})
    if not isinstance(trade, dict):
        trade = {}
        account["trade"] = trade
    planner = account.setdefault("planner", {})
    if not isinstance(planner, dict):
        planner = {}
        account["planner"] = planner

    status_by_city = _manual_two_city_product_status_by_city_for_account(account)
    before = copy.deepcopy(status_by_city)
    city_status = status_by_city.setdefault(city, {})
    city_status[good] = product_status

    status_by_city = _complete_product_status_by_city(status_by_city)
    locked_only = _locked_product_status_by_city(status_by_city)
    changed = status_by_city != _complete_product_status_by_city(before)
    if not changed:
        return {
            "changed": False,
            "city": city,
            "good": good,
            "status": product_status,
            "reason": reason,
        }

    trade["product_status_by_city"] = copy.deepcopy(status_by_city)
    trade["product_unlock_status_by_city"] = copy.deepcopy(locked_only)
    planner["product_status_by_city"] = copy.deepcopy(status_by_city)
    planner["product_unlock_status_by_city"] = copy.deepcopy(locked_only)
    completed_parts = set(account.get("completed_parts") or [])
    completed_parts.add("read_product_status")
    account["completed_parts"] = sorted(completed_parts)
    account["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    account.setdefault("_source", {})["last_task_entry"] = MANUAL_TWO_CITY_TASK_ENTRY

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(account, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    state_text = {
        PRODUCT_STATUS_NORMAL: "正常/已出现",
        PRODUCT_STATUS_LOCKED: "未解锁",
        PRODUCT_STATUS_MISSING: "已扫描但未出现",
        PRODUCT_STATUS_NEVER_SCANNED: "未扫描过",
    }.get(product_status, product_status)
    _append_user_log(
        MANUAL_TWO_CITY_TASK_ENTRY,
        f"交易品配置更新：{city}/{good} -> {state_text}（{reason}）。",
        level="info" if product_status == PRODUCT_STATUS_NORMAL else "warning",
        event="manual_two_city_product_status_updated",
        data={
            "uid": uid,
            "city": city,
            "good": good,
            "status": product_status,
            "reason": reason,
            "account_config": str(path),
            "product_status_by_city": status_by_city,
            "product_unlock_status_by_city": locked_only,
        },
    )
    state["product_status_changed"] = True
    return {
        "changed": True,
        "uid": uid,
        "city": city,
        "good": good,
        "status": product_status,
        "account_config": str(path),
    }


def _manual_two_city_update_product_unlock_state(
    city_name: Any,
    good_name: Any,
    unlocked: bool,
    *,
    reason: str,
) -> dict[str, Any]:
    return _manual_two_city_update_product_status(
        city_name,
        good_name,
        PRODUCT_STATUS_NORMAL if unlocked else PRODUCT_STATUS_LOCKED,
        reason=reason,
    )


def _manual_two_city_update_city_product_statuses(
    city_name: Any,
    statuses: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    city = normalize_city_name(str(city_name or "").strip())
    updates = {
        str(good or "").strip(): _normalize_product_status(status)
        for good, status in (statuses or {}).items()
        if str(good or "").strip()
    }
    if not city or not updates:
        return {"changed": False, "reason": "missing_city_or_statuses"}
    state = _manual_two_city_state()
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    path, account = _manual_two_city_load_account_config_for_result(result)
    uid = _safe_account_uid(account.get("uid") or result.get("uid") or _PROFILE_UID)
    if not account:
        return {"changed": False, "reason": "missing_account_config", "uid": uid}

    trade = account.setdefault("trade", {})
    if not isinstance(trade, dict):
        trade = {}
        account["trade"] = trade
    planner = account.setdefault("planner", {})
    if not isinstance(planner, dict):
        planner = {}
        account["planner"] = planner

    status_by_city = _manual_two_city_product_status_by_city_for_account(account)
    before = copy.deepcopy(status_by_city)
    city_status = status_by_city.setdefault(city, {})
    city_status.update(updates)
    status_by_city = _complete_product_status_by_city(status_by_city)
    locked_only = _locked_product_status_by_city(status_by_city)
    changed = status_by_city != _complete_product_status_by_city(before)
    if not changed:
        return {"changed": False, "city": city, "updates": updates, "reason": reason}

    trade["product_status_by_city"] = copy.deepcopy(status_by_city)
    trade["product_unlock_status_by_city"] = copy.deepcopy(locked_only)
    planner["product_status_by_city"] = copy.deepcopy(status_by_city)
    planner["product_unlock_status_by_city"] = copy.deepcopy(locked_only)
    completed_parts = set(account.get("completed_parts") or [])
    completed_parts.add("read_product_status")
    account["completed_parts"] = sorted(completed_parts)
    account["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    account.setdefault("_source", {})["last_task_entry"] = MANUAL_TWO_CITY_TASK_ENTRY

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(account, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    counts = {
        status: sum(1 for value in updates.values() if value == status)
        for status in PRODUCT_STATUSES
    }
    _append_user_log(
        MANUAL_TWO_CITY_TASK_ENTRY,
        (
            f"交易品配置更新：{city} 扫描写入 {len(updates)} 个，"
            f"正常 {counts.get(PRODUCT_STATUS_NORMAL, 0)}，"
            f"未解锁 {counts.get(PRODUCT_STATUS_LOCKED, 0)}，"
            f"未出现 {counts.get(PRODUCT_STATUS_MISSING, 0)}。"
        ),
        level="warning" if counts.get(PRODUCT_STATUS_LOCKED, 0) or counts.get(PRODUCT_STATUS_MISSING, 0) else "info",
        event="manual_two_city_city_product_statuses_updated",
        data={
            "uid": uid,
            "city": city,
            "updates": updates,
            "reason": reason,
            "account_config": str(path),
            "counts": counts,
            "product_unlock_status_by_city": locked_only,
        },
    )
    state["product_status_changed"] = True
    return {
        "changed": True,
        "uid": uid,
        "city": city,
        "updates": updates,
        "account_config": str(path),
        "counts": counts,
    }


def _manual_two_city_product_locked_after_click(
    context: Context,
    name: str,
    *,
    center_y: int | None = None,
) -> tuple[bool, list[str]]:
    roi = TRADE_PRODUCT_LOCK_CHECK_ROI
    if center_y is not None:
        top = max(90, int(center_y) - 48)
        bottom = min(620, int(center_y) + 64)
        roi = [500, top, 360, max(42, bottom - top)]
    hit, _, texts = _manual_two_city_ocr_entries(
        context,
        name,
        TRADE_PRODUCT_LOCK_TEXTS,
        roi=roi,
    )
    return bool(hit), texts


def _manual_two_city_close_product_detail_if_needed(context: Context) -> None:
    try:
        _manual_two_city_click(context, TRADE_PRODUCT_DETAIL_CLOSE_TARGET, 0.25)
    except Exception:
        pass


def _manual_two_city_log_travel_progress(status: dict[str, Any], leg: dict[str, Any]) -> None:
    state = _manual_two_city_state()
    now = time.monotonic()
    last = float(state.get("travel_progress_last_log_at") or 0.0)
    if now - last < 15:
        return
    state["travel_progress_last_log_at"] = now
    remaining = status.get("remaining_km")
    destination = status.get("destination") or leg.get("sell_city") or ""
    if remaining is not None:
        message = f"行车中：前往 {destination}，剩余 {remaining} km。"
    else:
        message = f"行车中：前往 {destination or '目标城市'}。"
    _append_user_log(
        MANUAL_TWO_CITY_TASK_ENTRY,
        message,
        event="manual_two_city_travel_progress",
        data={"status": status, "leg": leg},
    )


def _manual_two_city_reset_travel_stall_state(state: dict[str, Any], *, reset_restart_count: bool = False) -> None:
    for key in (
        "travel_stall_remaining_km",
        "travel_stall_destination",
        "travel_stall_since",
        "travel_stall_hit_count",
        "travel_stall_failed_pending",
        "travel_stall_restart_pending",
    ):
        state.pop(key, None)
    if reset_restart_count:
        state["travel_stall_restart_count"] = 0


def _manual_two_city_travel_stall_watchdog(context: Context) -> tuple[bool, dict[str, Any]]:
    state = _manual_two_city_state()
    _hit, _entries, texts = _manual_two_city_ocr_entries(
        context,
        "ManualTwoCityBusinessTravelStallWatchdogProbe",
        ["目的地", "剩余行程", "巡航"],
        roi=[460, 16, 380, 145],
    )
    status = travel_status_from_texts(texts)
    remaining = status.get("remaining_km")
    if not isinstance(remaining, int):
        event_hit, _event_entries, event_texts = _manual_two_city_ocr_entries(
            context,
            "ManualTwoCityBusinessTravelStallRouteEventProbe",
            TRAVEL_ROUTE_EVENT_TEXTS,
        )
        if event_hit or _texts_contain_any(event_texts, TRAVEL_ROUTE_EVENT_TEXTS):
            _manual_two_city_reset_travel_stall_state(state)
            return False, {"reason": "route_event_visible", "texts": event_texts[:20]}
        _manual_two_city_reset_travel_stall_state(state)
        return False, {"reason": "no_remaining", "status": status, "texts": texts[:20]}

    now = time.monotonic()
    destination = str(status.get("destination") or _manual_two_city_travel_target_city() or "").strip()
    last_remaining = state.get("travel_stall_remaining_km")
    if last_remaining != remaining:
        state["travel_stall_remaining_km"] = remaining
        state["travel_stall_destination"] = destination
        state["travel_stall_since"] = now
        state["travel_stall_hit_count"] = 1
        return False, {
            "reason": "progress_changed",
            "remaining_km": remaining,
            "destination": destination,
            "status": status,
            "texts": texts[:20],
        }

    since = float(state.get("travel_stall_since") or now)
    hit_count = int(state.get("travel_stall_hit_count") or 0) + 1
    state["travel_stall_hit_count"] = hit_count
    elapsed = now - since
    payload = {
        "remaining_km": remaining,
        "destination": destination,
        "elapsed": elapsed,
        "hit_count": hit_count,
        "status": status,
        "texts": texts[:20],
    }
    if elapsed < MANUAL_TWO_CITY_TRAVEL_STALL_SECONDS or hit_count < MANUAL_TWO_CITY_TRAVEL_STALL_MIN_HITS:
        payload["reason"] = "below_threshold"
        return False, payload

    restart_count = int(state.get("travel_stall_restart_count") or 0)
    if restart_count >= MANUAL_TWO_CITY_TRAVEL_STALL_MAX_RESTARTS:
        state["travel_stall_failed_pending"] = True
        state["terminal_status"] = MANUAL_TWO_CITY_TERMINAL_FAILED
        state["terminal_reason"] = (
            f"行车状态停滞：剩余 {remaining} km 已持续 {int(elapsed)} 秒，"
            "重启后仍未恢复"
        )
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"行车异常：剩余 {remaining} km 已停滞 {int(elapsed)} 秒，且本段已重启过，判定任务失败。",
            level="error",
            event="manual_two_city_travel_stall_failed",
            data={**payload, "restart_count": restart_count},
        )
        return True, {**payload, "reason": "restart_limit_reached", "restart_count": restart_count}

    state["travel_stall_restart_count"] = restart_count + 1
    state["travel_stall_restart_pending"] = True
    state["travel_recovering_from_stall"] = True
    state["startup_travel_pending"] = False
    state["startup_travel_in_progress"] = False
    state["trade_phase"] = "travel"
    _append_user_log(
        MANUAL_TWO_CITY_TASK_ENTRY,
        f"行车异常：剩余 {remaining} km 已停滞 {int(elapsed)} 秒，准备重启游戏后重新判断行车状态。",
        level="warning",
        event="manual_two_city_travel_stall_restart_needed",
        data={**payload, "restart_count": restart_count + 1},
    )
    return True, {**payload, "reason": "restart_needed", "restart_count": restart_count + 1}


def _manual_two_city_set_active_leg_by_visible_goods(entries: list[dict[str, Any]]) -> dict[str, Any]:
    state = _manual_two_city_state()
    legs = _manual_two_city_legs()
    best_index = -1
    best_score = 0
    for index, leg in enumerate(legs):
        goods = [str(item) for item in (leg.get("goods") or []) if str(item).strip()]
        matched = {
            match_trade_good(entry.get("text"), goods)
            for entry in entries
        }
        score = len({good for good in matched if good})
        if score > best_score:
            best_score = score
            best_index = index
    if best_index >= 0 and best_score > 0:
        if state.get("active_leg_index") != best_index:
            state["selected_buy_goods"] = []
        state["active_leg_index"] = best_index
        return legs[best_index]
    return _manual_two_city_active_leg()


def _manual_two_city_book_batches(count: Any) -> list[int]:
    try:
        remaining = max(0, int(count or 0))
    except (TypeError, ValueError):
        return []
    batches: list[int] = []
    while remaining > 0:
        batch = min(remaining, BUY_BOOK_MAX_PER_BATCH)
        batches.append(batch)
        remaining -= batch
    return batches


def _manual_two_city_haggle_count(value: Any) -> int:
    try:
        count = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return min(max(count, 0), 20)


def _manual_two_city_read_percent_from_texts(texts: list[str]) -> float | None:
    for text in texts:
        normalized = str(text or "").replace("O", "0").replace("o", "0")
        match = re.search(r"\d{1,3}(?:\.\d+)?", normalized)
        if not match:
            continue
        value = float(match.group())
        if 0 <= value <= 100:
            return value
    return None


def _manual_two_city_read_buy_haggle_percent(context: Context) -> float | None:
    _, _, texts = _manual_two_city_ocr_entries(
        context,
        "ManualTwoCityReadBuyHagglePercent",
        "",
        roi=BUY_HAGGLE_PERCENT_ROI,
    )
    return _manual_two_city_read_percent_from_texts(texts)


def _manual_two_city_format_percent(value: float | int | None) -> str:
    if value is None:
        return "未识别"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}".rstrip("0").rstrip(".")


def _manual_two_city_confirm_buy_haggle_book_popup(
    context: Context,
    *,
    leg: dict[str, Any],
    target_percent: int,
    current_percent: float | None,
    click_count: int,
    probe_name: str,
    allow_confirm: bool = True,
) -> bool:
    popup_hit, _, popup_texts = _manual_two_city_ocr_entries(
        context,
        probe_name,
        BUY_HAGGLE_BOOK_POPUP_TEXTS,
        roi=BUY_HAGGLE_BOOK_POPUP_ROI,
    )
    if not popup_hit:
        return False
    if not allow_confirm:
        raise RuntimeError(f"haggle book limit reached: popup={popup_texts[:12]}")

    confirmed, confirm_texts = _manual_two_city_click_ocr_text(
        context,
        f"{probe_name}Confirm",
        ["确认", "确定"],
        roi=BUY_HAGGLE_BOOK_CONFIRM_ROI,
        fallback=BUY_HAGGLE_BOOK_CONFIRM_TARGET,
        delay=1.8,
    )
    if not confirmed:
        raise RuntimeError(f"haggle book confirm not found: popup={popup_texts[:12]}, confirm={confirm_texts[:12]}")

    _append_user_log(
        MANUAL_TWO_CITY_TASK_ENTRY,
        f"议价：检测到重新议价请求书弹窗，已确认使用，继续尝试达到 {target_percent}%。",
        event="manual_two_city_buy_haggle_book_used",
        data={
            "target_percent": target_percent,
            "current_percent": current_percent,
            "click_count": click_count,
            "popup_texts": popup_texts[:20],
            "leg": leg,
        },
    )
    return True


def _manual_two_city_click(context: Context, target: tuple[int, int], delay: float = 0.35) -> None:
    context.tasker.controller.post_click(int(target[0]), int(target[1])).wait()
    if delay > 0:
        time.sleep(delay)


def _manual_two_city_screencap(context: Context) -> Any:
    try:
        job = context.tasker.controller.post_screencap().wait()
        image = getattr(job, "result", None)
        if image is not None:
            return image
    except Exception:
        pass
    return getattr(context.tasker.controller, "cached_image", None)


def _manual_two_city_ocr_detail(
    context: Context,
    name: str,
    expected: str | list[str],
    *,
    roi: list[int] | None = None,
) -> Any:
    image = _manual_two_city_screencap(context)
    if image is None:
        return None
    node: dict[str, Any] = {
        "recognition": "OCR",
        "expected": expected,
        "action": "DoNothing",
    }
    if roi is not None:
        node["roi"] = roi
    try:
        return context.run_recognition(name, image, {name: node})
    except Exception:
        return None


def _manual_two_city_ocr_entries(
    context: Context,
    name: str,
    expected: str | list[str],
    *,
    roi: list[int] | None = None,
) -> tuple[bool, list[dict[str, Any]], list[str]]:
    detail = _manual_two_city_ocr_detail(context, name, expected, roi=roi)
    entries = _ocr_entries_from_detail(detail)
    texts = _ocr_texts_from_detail(detail)
    return bool(getattr(detail, "hit", False)), entries, texts


def _manual_two_city_entry_matches(entry: dict[str, Any], expected: list[str]) -> bool:
    text = clean_text(entry.get("text"))
    return any(clean_text(item) and clean_text(item) in text for item in expected)


def _manual_two_city_texts_contain(texts: list[str], expected: list[str]) -> bool:
    cleaned = [clean_text(text) for text in texts if clean_text(text)]
    return any(clean_text(item) and clean_text(item) in text for item in expected for text in cleaned)


def _manual_two_city_medicine_card_unavailable(
    context: Context,
    resource: str,
    resource_key: str,
) -> tuple[bool, list[str]]:
    roi = FATIGUE_MEDICINE_CARD_ROIS.get(resource)
    if not roi:
        return False, []
    hit, _, texts = _manual_two_city_ocr_entries(
        context,
        f"ManualTwoCityStrength{resource_key}CardUnavailable",
        FATIGUE_MEDICINE_CARD_UNAVAILABLE_TEXTS,
        roi=roi,
    )
    return bool(hit or _manual_two_city_texts_contain(texts, FATIGUE_MEDICINE_CARD_UNAVAILABLE_TEXTS)), texts


def _manual_two_city_adjust_medicine_popup_count(
    context: Context,
    resource_key: str,
    target_count: int,
    *,
    use_max: bool,
) -> dict[str, Any]:
    target_count = max(1, int(target_count or 1))
    if use_max:
        clicked, texts = _manual_two_city_click_ocr_text(
            context,
            f"ManualTwoCityStrength{resource_key}UseMax",
            FATIGUE_MEDICINE_MAX_TEXTS,
            roi=[560, 430, 390, 110],
            fallback=FATIGUE_MEDICINE_MAX_TARGET,
            delay=0.25,
        )
        return {
            "method": "max",
            "clicked": clicked,
            "target_count": target_count,
            "plus_clicks": 0,
            "texts": texts[:20],
        }

    plus_clicks = max(0, min(FATIGUE_MEDICINE_POPUP_MAX_STEPS, target_count) - 1)
    for index in range(plus_clicks):
        if index and index % 8 == 0:
            popup_hit, _, popup_texts = _manual_two_city_ocr_entries(
                context,
                f"ManualTwoCityStrength{resource_key}PopupStillOpen{index:03d}",
                FATIGUE_MEDICINE_POPUP_TEXTS,
                roi=FATIGUE_MEDICINE_POPUP_ROI,
            )
            if not popup_hit:
                return {
                    "method": "plus",
                    "clicked": False,
                    "target_count": target_count,
                    "plus_clicks": index,
                    "reason": "popup_lost",
                    "texts": popup_texts[:20],
                }
        _manual_two_city_click(context, FATIGUE_MEDICINE_PLUS_TARGET, 0.12)
    return {
        "method": "plus",
        "clicked": True,
        "target_count": target_count,
        "plus_clicks": plus_clicks,
    }


def _manual_two_city_click_ocr_text(
    context: Context,
    name: str,
    expected: list[str],
    *,
    roi: list[int] | None = None,
    fallback: tuple[int, int] | None = None,
    offset: tuple[int, int] = (0, 0),
    delay: float = 0.65,
) -> tuple[bool, list[str]]:
    hit, entries, texts = _manual_two_city_ocr_entries(context, name, expected, roi=roi)
    for entry in entries:
        if not _manual_two_city_entry_matches(entry, expected):
            continue
        x = int(float(entry.get("center_x") or 0)) + int(offset[0])
        y = int(float(entry.get("center_y") or 0)) + int(offset[1])
        _manual_two_city_click(context, (x, y), delay)
        return True, texts
    if fallback is not None:
        _manual_two_city_click(context, fallback, delay)
        return True, texts
    return False, texts


def _manual_two_city_settlement_report_visible(context: Context, name: str) -> tuple[bool, list[str]]:
    hit, _entries, texts = _manual_two_city_ocr_entries(
        context,
        name,
        SETTLEMENT_REPORT_TEXTS,
        roi=[0, 120, 1280, 600],
    )
    return hit, texts


def _manual_two_city_close_settlement_report(context: Context, *, probe_prefix: str) -> tuple[bool, list[str]]:
    visible, texts = _manual_two_city_settlement_report_visible(context, f"{probe_prefix}Before")
    if not visible:
        return True, texts
    last_texts = texts
    for index, target in enumerate(SETTLEMENT_REPORT_CLOSE_TARGETS, start=1):
        _manual_two_city_click(context, target, 0.75)
        visible, last_texts = _manual_two_city_settlement_report_visible(
            context,
            f"{probe_prefix}AfterTap{index:03d}",
        )
        if not visible:
            return True, last_texts
    return False, last_texts


def _manual_two_city_try_bento_recovery(
    context: Context,
    state: dict[str, Any],
    *,
    required: int,
    phase: str,
) -> dict[str, Any]:
    recovery = _manual_two_city_strength_recovery_state(state)
    if not _fatigue_bool(state.get("use_bento"), False):
        reason = "便当选项关闭"
        _manual_two_city_recovery_log_skip_once(state, "便当", reason)
        return {"used": False, "resource": "便当", "reason": "disabled"}
    if recovery.setdefault("unavailable", {}).get("便当"):
        return {"used": False, "resource": "便当", "reason": "unavailable"}

    pre_shortage_hit, _, pre_shortage_texts = _manual_two_city_ocr_entries(
        context,
        "ManualTwoCityStrengthBentoShortageBeforeEntry",
        FATIGUE_BENTO_SHORTAGE_TEXTS,
        roi=[980, 360, 270, 120],
    )
    if pre_shortage_hit or _manual_two_city_texts_contain(pre_shortage_texts, FATIGUE_BENTO_SHORTAGE_TEXTS):
        _manual_two_city_recovery_mark_unavailable(recovery, "便当", "余量不足")
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "跑商补疲劳：当前便当余量不足，继续尝试体力药。",
            level="warning",
            event="manual_two_city_strength_bento_shortage_before_entry",
            data={"phase": phase, "texts": pre_shortage_texts[:20]},
        )
        return {"used": False, "resource": "便当", "reason": "shortage"}

    clicked, entry_texts = _manual_two_city_click_ocr_text(
        context,
        "ManualTwoCityStrengthBentoEntry",
        FATIGUE_BENTO_ENTRY_TEXTS,
        roi=FATIGUE_BENTO_ENTRY_ROI,
        delay=0.9,
    )
    if not clicked:
        _manual_two_city_recovery_mark_unavailable(recovery, "便当", "未识别入口")
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "跑商补疲劳：未识别到便当柜入口，跳过便当。",
            level="warning",
            event="manual_two_city_strength_bento_entry_missing",
            data={"phase": phase, "texts": entry_texts[:20]},
        )
        return {"used": False, "resource": "便当", "reason": "entry_missing"}

    shortage_hit, _, shortage_texts = _manual_two_city_ocr_entries(
        context,
        "ManualTwoCityStrengthBentoShortage",
        FATIGUE_BENTO_SHORTAGE_TEXTS,
    )
    if shortage_hit or _manual_two_city_texts_contain(shortage_texts, FATIGUE_BENTO_SHORTAGE_TEXTS):
        _manual_two_city_recovery_mark_unavailable(recovery, "便当", "余量不足")
        _manual_two_city_click(context, (640, 510), 0.8)
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "跑商补疲劳：便当余量不足，继续尝试体力药。",
            level="warning",
            event="manual_two_city_strength_bento_shortage",
            data={"phase": phase, "texts": shortage_texts[:20]},
        )
        return {"used": False, "resource": "便当", "reason": "shortage"}

    page_hit, _, page_texts = _manual_two_city_ocr_entries(
        context,
        "ManualTwoCityStrengthBentoPageReady",
        FATIGUE_BENTO_PAGE_TEXTS,
    )
    if not page_hit:
        _manual_two_city_recovery_mark_unavailable(recovery, "便当", "未进入便当页")
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "跑商补疲劳：点击便当柜后未识别到便当页，跳过便当。",
            level="warning",
            event="manual_two_city_strength_bento_page_missing",
            data={"phase": phase, "texts": page_texts[:20]},
        )
        return {"used": False, "resource": "便当", "reason": "page_missing"}

    clicked_all, all_texts = _manual_two_city_click_ocr_text(
        context,
        "ManualTwoCityStrengthBentoUseAll",
        FATIGUE_BENTO_ALL_TEXTS,
        roi=FATIGUE_BENTO_ALL_ROI,
        fallback=(1000, 421),
        delay=1.0,
    )
    if not clicked_all:
        _manual_two_city_recovery_mark_unavailable(recovery, "便当", "未识别全部使用")
        _manual_two_city_click(context, RECOVERY_PAGE_BACK_TARGET, 0.8)
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "跑商补疲劳：未能点击便当全部使用，已返回疲劳页继续后续资源。",
            level="warning",
            event="manual_two_city_strength_bento_use_all_missing",
            data={"phase": phase, "texts": all_texts[:20]},
        )
        return {"used": False, "resource": "便当", "reason": "use_all_missing"}

    for index in range(3):
        success_hit, _, success_texts = _manual_two_city_ocr_entries(
            context,
            f"ManualTwoCityStrengthBentoSuccess{index + 1:03d}",
            FATIGUE_BENTO_SUCCESS_TEXTS,
        )
        if success_hit:
            _manual_two_city_click(context, (640, 510), 0.9)
            break
        confirm_clicked, confirm_texts = _manual_two_city_click_ocr_text(
            context,
            f"ManualTwoCityStrengthBentoConfirm{index + 1:03d}",
            FATIGUE_BENTO_CONFIRM_TEXTS,
            roi=[880, 450, 240, 190],
            delay=0.8,
        )
        if confirm_clicked:
            continue
        prompt_clicked, prompt_texts = _manual_two_city_click_ocr_text(
            context,
            f"ManualTwoCityStrengthBentoPrompt{index + 1:03d}",
            FATIGUE_BENTO_CONFIRM_PROMPT_TEXTS,
            roi=[820, 430, 360, 220],
            delay=0.8,
        )
        if prompt_clicked:
            continue
        if success_texts or confirm_texts or prompt_texts:
            time.sleep(0.35)
            continue
        break

    _manual_two_city_resource_used(state, "便当", "bento")
    _manual_two_city_recovery_mark_unavailable(recovery, "便当", "已全部使用")
    status, status_texts = _manual_two_city_read_strength_status(context, "ManualTwoCityStrengthBentoStatus")
    if isinstance(status, dict):
        state["strength_recovery_last_status"] = status
    if _manual_two_city_strength_enough(status, required):
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            (
                f"跑商补疲劳：便当页确认剩余疲劳 {status['remaining']}，"
                f"已满足安全需求 {required}，返回交易页。"
            ),
            event="manual_two_city_strength_bento_enough",
            data={"phase": phase, "status": status, "required": required, "texts": status_texts[:20]},
        )
        _manual_two_city_click(context, RECOVERY_PAGE_BACK_TARGET, 0.8)
        _manual_two_city_click(context, RECOVERY_PAGE_BACK_TARGET, 0.8)
        state["skip_next_drink_check"] = True
        return {"used": True, "resource": "便当", "enough": True, "return_trade": True, "status": status}

    if status:
        message = f"跑商补疲劳：便当页确认剩余疲劳 {status['remaining']}，仍低于安全需求 {required}，继续尝试体力药。"
    else:
        message = "跑商补疲劳：便当页未读到疲劳值，继续尝试体力药。"
    _append_user_log(
        MANUAL_TWO_CITY_TASK_ENTRY,
        message,
        level="warning",
        event="manual_two_city_strength_bento_not_enough",
        data={"phase": phase, "status": status, "required": required, "texts": status_texts[:20]},
    )
    _manual_two_city_click(context, RECOVERY_PAGE_BACK_TARGET, 0.8)
    return {"used": True, "resource": "便当", "enough": False, "return_trade": False, "status": status}


def _manual_two_city_try_medicine_recovery(
    context: Context,
    state: dict[str, Any],
    resource: str,
    *,
    required: int,
    status: dict[str, int] | None,
    phase: str,
) -> dict[str, Any]:
    recovery = _manual_two_city_strength_recovery_state(state)
    allowed, skip_reason, limit, used = _manual_two_city_medicine_limit_state(state, resource)
    if not allowed:
        _manual_two_city_recovery_log_skip_once(state, resource, skip_reason)
        return {
            "used": False,
            "resource": resource,
            "reason": "not_allowed",
            "limit": limit,
            "used_count": used,
        }
    resource_key = {
        "提神棒棒糖": "Lollipop",
        "提神口香糖": "Gum",
        "仙人掌提神跳糖": "CactusCandy",
    }.get(resource, "Medicine")
    card_unavailable, card_texts = _manual_two_city_medicine_card_unavailable(context, resource, resource_key)
    if card_unavailable:
        _manual_two_city_recovery_mark_unavailable(recovery, resource, "卡片不可用")
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"跑商补疲劳：{resource} 卡片不可用，跳过。",
            level="warning",
            event="manual_two_city_strength_medicine_card_unavailable",
            data={"phase": phase, "resource": resource, "texts": card_texts[:20]},
        )
        return {"used": False, "resource": resource, "reason": "card_unavailable"}

    clicked, click_texts = _manual_two_city_click_ocr_text(
        context,
        f"ManualTwoCityStrengthTap{resource_key}",
        [resource],
        roi=FATIGUE_MEDICINE_POPUP_ROI,
        fallback=FATIGUE_MEDICINE_FALLBACK_TARGETS.get(resource),
        delay=0.8,
    )
    if not clicked:
        _manual_two_city_recovery_mark_unavailable(recovery, resource, "未识别入口")
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"跑商补疲劳：未识别到 {resource}，跳过。",
            level="warning",
            event="manual_two_city_strength_medicine_entry_missing",
            data={"phase": phase, "resource": resource, "texts": click_texts[:20]},
        )
        return {"used": False, "resource": resource, "reason": "entry_missing"}

    popup_hit, _, popup_texts = _manual_two_city_ocr_entries(
        context,
        f"ManualTwoCityStrength{resource_key}Popup",
        FATIGUE_MEDICINE_POPUP_TEXTS + ["库存不足", "数量不足", "无库存", "没有可用"],
        roi=FATIGUE_MEDICINE_POPUP_ROI,
    )
    inventory = medicine_inventory_count(popup_texts)
    if not popup_hit or medicine_no_inventory_seen(popup_texts) or inventory == 0:
        reason = "库存不足" if medicine_no_inventory_seen(popup_texts) or inventory == 0 else "未识别弹窗"
        _manual_two_city_recovery_mark_unavailable(recovery, resource, reason)
        cancel_clicked = False
        popup_visible = bool(
            popup_hit
            or inventory is not None
            or medicine_no_inventory_seen(popup_texts)
            or _manual_two_city_texts_contain(popup_texts, FATIGUE_MEDICINE_POPUP_TEXTS + ["取消", "确定", "确认"])
        )
        if popup_visible:
            _manual_two_city_click(context, FATIGUE_MEDICINE_CANCEL_TARGET, 0.8)
            cancel_clicked = True
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"跑商补疲劳：{resource} {reason}，继续尝试下一种资源。",
            level="warning",
            event="manual_two_city_strength_medicine_unavailable",
            data={
                "phase": phase,
                "resource": resource,
                "inventory": inventory,
                "cancel_clicked": cancel_clicked,
                "texts": popup_texts[:20],
            },
        )
        return {"used": False, "resource": resource, "reason": reason}

    use_plan = _manual_two_city_medicine_target_count(
        state,
        resource,
        required=required,
        status=status,
        inventory=inventory,
        limit=limit,
        used=used,
    )
    target_count = int(use_plan.get("target_count") or 0)
    if target_count <= 0:
        _manual_two_city_click(context, FATIGUE_MEDICINE_CANCEL_TARGET, 0.8)
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"跑商补疲劳：{resource} 本次无需使用，取消弹窗并继续检查。",
            level="warning",
            event="manual_two_city_strength_medicine_no_need",
            data={"phase": phase, "resource": resource, "use_plan": use_plan, "status": status, "required": required},
        )
        return {"used": False, "resource": resource, "reason": "target_count_zero", "use_plan": use_plan}

    adjust_result = _manual_two_city_adjust_medicine_popup_count(
        context,
        resource_key,
        target_count,
        use_max=bool(use_plan.get("use_max")),
    )
    if not adjust_result.get("clicked"):
        _manual_two_city_click(context, FATIGUE_MEDICINE_CANCEL_TARGET, 0.8)
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"跑商补疲劳：{resource} 调整使用数量失败，取消弹窗并尝试下一种资源。",
            level="warning",
            event="manual_two_city_strength_medicine_adjust_failed",
            data={
                "phase": phase,
                "resource": resource,
                "use_plan": use_plan,
                "adjust_result": adjust_result,
                "status": status,
                "required": required,
            },
        )
        return {"used": False, "resource": resource, "reason": "adjust_failed", "use_plan": use_plan}

    _manual_two_city_click(context, FATIGUE_MEDICINE_CONFIRM_TARGET, 1.2)
    _manual_two_city_resource_used(
        state,
        resource,
        "medicine",
        count=target_count,
        pending={"inventory_count": inventory, "use_plan": use_plan, "adjust_result": adjust_result},
    )
    state["skip_next_drink_check"] = True
    return {
        "used": True,
        "resource": resource,
        "return_trade": True,
        "inventory_count": inventory,
        "count": target_count,
        "use_plan": use_plan,
        "adjust_result": adjust_result,
    }


def _manual_two_city_try_huashi_recovery(
    context: Context,
    state: dict[str, Any],
    *,
    phase: str,
) -> dict[str, Any]:
    recovery = _manual_two_city_strength_recovery_state(state)
    resource = "桦石"
    allowed, skip_reason, limit, used = _manual_two_city_medicine_limit_state(state, resource, huashi=True)
    if not allowed:
        if "最高" in skip_reason:
            _manual_two_city_recovery_mark_unavailable(recovery, resource, skip_reason)
        _manual_two_city_recovery_log_skip_once(state, resource, skip_reason)
        return {
            "used": False,
            "resource": resource,
            "reason": "not_allowed",
            "limit": limit,
            "used_count": used,
        }

    clicked, click_texts = _manual_two_city_click_ocr_text(
        context,
        "ManualTwoCityStrengthTapHuashi",
        [resource],
        roi=FATIGUE_HUASHI_ROI,
        fallback=FATIGUE_HUASHI_FALLBACK_TARGET,
        delay=1.0,
    )
    if not clicked:
        _manual_two_city_recovery_mark_unavailable(recovery, resource, "未识别入口")
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "跑商补疲劳：未识别到桦石入口，停止补疲劳。",
            level="warning",
            event="manual_two_city_strength_huashi_entry_missing",
            data={"phase": phase, "texts": click_texts[:20]},
        )
        return {"used": False, "resource": resource, "reason": "entry_missing"}

    shop_hit, _, shop_texts = _manual_two_city_ocr_entries(
        context,
        "ManualTwoCityStrengthHuashiShopPrompt",
        FATIGUE_HUASHI_SHOP_PROMPT_TEXTS,
    )
    if shop_hit:
        _manual_two_city_recovery_mark_unavailable(recovery, resource, "购买次数不足")
        _manual_two_city_click(context, FATIGUE_HUASHI_CANCEL_TARGET, 0.8)
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "跑商补疲劳：桦石购买次数不足，停止补疲劳。",
            level="warning",
            event="manual_two_city_strength_huashi_shop_prompt",
            data={"phase": phase, "texts": shop_texts[:20]},
        )
        return {"used": False, "resource": resource, "reason": "shop_prompt"}

    notice_hit, _, notice_texts = _manual_two_city_ocr_entries(
        context,
        "ManualTwoCityStrengthHuashiNotice",
        FATIGUE_HUASHI_NOTICE_TEXTS,
    )
    if huashi_exhausted_seen(notice_texts):
        _manual_two_city_recovery_mark_unavailable(recovery, resource, "次数不足")
        _manual_two_city_click(context, FATIGUE_HUASHI_CANCEL_TARGET, 0.8)
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "跑商补疲劳：桦石今日次数不足或已达上限。",
            level="warning",
            event="manual_two_city_strength_huashi_exhausted",
            data={"phase": phase, "texts": notice_texts[:20]},
        )
        return {"used": False, "resource": resource, "reason": "exhausted"}
    notice = huashi_notice_from_texts(notice_texts)
    if not notice_hit or not notice:
        _manual_two_city_recovery_mark_unavailable(recovery, resource, "未识别确认弹窗")
        _manual_two_city_click(context, FATIGUE_HUASHI_CANCEL_TARGET, 0.8)
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "跑商补疲劳：未识别到桦石确认弹窗，停止补疲劳。",
            level="warning",
            event="manual_two_city_strength_huashi_notice_missing",
            data={"phase": phase, "texts": notice_texts[:20]},
        )
        return {"used": False, "resource": resource, "reason": "notice_missing"}

    _manual_two_city_click(context, FATIGUE_MEDICINE_CONFIRM_TARGET, 1.2)
    _manual_two_city_resource_used(state, resource, "huashi", pending=notice)
    state["skip_next_drink_check"] = True
    return {"used": True, "resource": resource, "return_trade": True, "notice": notice}


def _fatigue_clean_texts(texts: list[str]) -> list[str]:
    return [clean_text(text) for text in texts if str(text).strip()]


def _fatigue_has_any_text(texts: list[str], expected: list[str]) -> bool:
    cleaned = _fatigue_clean_texts(texts)
    return any(clean_text(item) and clean_text(item) in text for item in expected for text in cleaned)


def _fatigue_drink_task_entry() -> str:
    return _FATIGUE_DRINK_LOG_TASK_ENTRY or _manual_two_city_current_task_entry()


def _fatigue_drink_ocr(
    context: Context,
    name: str,
    *,
    roi: list[int] | None = None,
) -> tuple[bool, list[dict[str, Any]], list[str]]:
    return _manual_two_city_ocr_entries(context, name, FATIGUE_DRINK_OCR_EXPECTED, roi=roi)


def _fatigue_drink_texts(context: Context, name: str = "FatigueDrinkProbe") -> list[str]:
    _, _, texts = _fatigue_drink_ocr(context, name)
    return texts


def _fatigue_is_no_remind_text(text: Any) -> bool:
    compact = clean_text(text)
    if any(clean_text(keyword) in compact for keyword in FATIGUE_NO_REMIND_TEXTS):
        return True
    return "不再" in compact and any(keyword in compact for keyword in ("提示", "提醒", "弹", "显示", "跳过"))


def _fatigue_tap_no_remind_if_present(context: Context, name: str = "FatigueDrinkNoRemind") -> bool:
    _, entries, texts = _fatigue_drink_ocr(context, name, roi=[0, 300, 1280, 390])
    for entry in entries:
        if not _fatigue_is_no_remind_text(entry.get("text")):
            continue
        x = int(float(entry.get("x") or entry.get("center_x") or 0))
        y = int(float(entry.get("center_y") or 0))
        if y <= 0:
            continue
        target = (max(24, x - 52), y)
        _manual_two_city_click(context, target, 0.25)
        _append_user_log(
            _fatigue_drink_task_entry(),
            f"喝酒弹窗：已勾选 {entry.get('text')}",
            event="fatigue_drink_no_remind_checked",
            data={"text": entry.get("text"), "target": target, "texts": texts[:20]},
        )
        return True
    return False


def _fatigue_click_drink_text(
    context: Context,
    name: str,
    expected: list[str],
    *,
    roi: list[int] | None = None,
    fallback: tuple[int, int] | None = None,
    delay: float = 0.75,
) -> tuple[bool, list[str]]:
    return _manual_two_city_click_ocr_text(context, name, expected, roi=roi, fallback=fallback, delay=delay)


def _fatigue_dismiss_drink_cost_confirm(context: Context, texts: list[str] | None = None) -> bool:
    current_texts = texts if texts is not None else _fatigue_drink_texts(context, "FatigueDrinkCostConfirmProbe")
    joined = "".join(_fatigue_clean_texts(current_texts))
    if not (
        any(clean_text(keyword) in joined for keyword in FATIGUE_DRINK_COST_CONFIRM_TEXTS)
        or ("银枝气泡水" in joined and "使用" in joined)
    ):
        return False
    clicked, confirm_texts = _fatigue_click_drink_text(
        context,
        "FatigueDrinkCancelCostConfirm",
        ["取消", "关闭"],
        roi=[160, 410, 420, 260],
        fallback=(320, 503),
        delay=0.8,
    )
    _append_user_log(
        _fatigue_drink_task_entry(),
        "喝酒：检测到使用银枝提示，已停止免费喝酒循环并取消弹窗。",
        event="fatigue_drink_cost_confirm_seen",
        data={"clicked": clicked, "texts": current_texts[:30], "confirm_texts": confirm_texts[:20]},
    )
    return True


def _fatigue_handle_drink_repeat_confirm(context: Context, *, attempt: int) -> bool:
    checked = _fatigue_tap_no_remind_if_present(context, f"FatigueDrinkRepeatNoRemind{attempt:03d}")
    if not checked:
        _manual_two_city_click(context, FATIGUE_DRINK_REPEAT_CONFIRM_CHECKBOX_TARGET, 0.2)
    _manual_two_city_click(context, FATIGUE_DRINK_REPEAT_CONFIRM_BUTTON_TARGET, 0.9)
    texts = _fatigue_drink_texts(context, f"FatigueDrinkRepeatConfirmAfterClick{attempt:03d}")
    if _fatigue_has_any_text(texts, FATIGUE_DRINK_REPEAT_CONFIRM_TEXTS):
        _manual_two_city_click(context, FATIGUE_DRINK_REPEAT_CONFIRM_BUTTON_TARGET, 0.9)
        texts = _fatigue_drink_texts(context, f"FatigueDrinkRepeatConfirmAfterRetry{attempt:03d}")
    handled = not _fatigue_has_any_text(texts, FATIGUE_DRINK_REPEAT_CONFIRM_TEXTS)
    _append_user_log(
        _fatigue_drink_task_entry(),
        "喝酒：已处理再喝一杯确认弹窗。" if handled else "喝酒：再喝一杯确认弹窗仍未关闭。",
        level="info" if handled else "warning",
        event="fatigue_drink_repeat_confirm",
        data={"attempt": attempt, "handled": handled, "checked_by_ocr": checked, "texts": texts[:30]},
    )
    return handled


def _fatigue_checkbox_looks_checked(context: Context, target: tuple[int, int]) -> bool:
    try:
        import numpy as np
    except Exception:
        return False
    image = _manual_two_city_screencap(context)
    if image is None:
        return False
    try:
        array = np.asarray(image)
    except Exception:
        return False
    if array.ndim < 2 or getattr(array, "size", 0) <= 0:
        return False
    height, width = array.shape[:2]
    if width <= 0 or height <= 0:
        return False
    x = int(round(float(target[0]) * width / 1280.0))
    y = int(round(float(target[1]) * height / 720.0))
    x1, x2 = max(0, x - 10), min(width, x + 11)
    y1, y2 = max(0, y - 10), min(height, y + 11)
    crop = array[y1:y2, x1:x2]
    if crop.ndim < 3 or crop.shape[0] < 12 or crop.shape[1] < 12:
        return False
    inner = crop[5:-5, 5:-5, :3].astype("float32")
    bright_ratio = float((inner.mean(axis=2) > 185.0).mean())
    return bright_ratio >= 0.08


def _fatigue_handle_drink_skip_confirm(context: Context, *, attempt: int) -> bool:
    state = _fatigue_recovery_state()
    checked_now = False
    if not state.get("drink_skip_no_remind_attempted"):
        already_checked = _fatigue_checkbox_looks_checked(context, FATIGUE_DRINK_SKIP_CONFIRM_CHECKBOX_TARGET)
        if not already_checked:
            _manual_two_city_click(context, FATIGUE_DRINK_SKIP_CONFIRM_CHECKBOX_TARGET, 0.2)
            checked_now = True
        state["drink_skip_no_remind_attempted"] = True
    else:
        already_checked = None
    _manual_two_city_click(context, FATIGUE_DRINK_SKIP_CONFIRM_BUTTON_TARGET, 0.9)
    texts = _fatigue_drink_texts(context, f"FatigueDrinkSkipConfirmAfterClick{attempt:03d}")
    if _fatigue_has_any_text(texts, FATIGUE_DRINK_SKIP_CONFIRM_TEXTS):
        _manual_two_city_click(context, FATIGUE_DRINK_SKIP_CONFIRM_BUTTON_TARGET, 0.9)
        texts = _fatigue_drink_texts(context, f"FatigueDrinkSkipConfirmAfterRetry{attempt:03d}")
    handled = not _fatigue_has_any_text(texts, FATIGUE_DRINK_SKIP_CONFIRM_TEXTS)
    _append_user_log(
        _fatigue_drink_task_entry(),
        "喝酒：已处理跳过演出确认弹窗。" if handled else "喝酒：跳过演出确认弹窗仍未关闭。",
        level="info" if handled else "warning",
        event="fatigue_drink_skip_confirm",
        data={
            "attempt": attempt,
            "handled": handled,
            "checked_now": checked_now,
            "already_checked": already_checked,
            "texts": texts[:30],
        },
    )
    return handled


def _fatigue_drink_page_kind(texts: list[str]) -> str:
    joined = "".join(_fatigue_clean_texts(texts))
    if _fatigue_has_any_text(texts, FATIGUE_DRINK_COST_CONFIRM_TEXTS) or (
        "银枝气泡水" in joined and "使用" in joined
    ):
        return "cost_confirm"
    if _fatigue_has_any_text(texts, FATIGUE_DRINK_UNAVAILABLE_TEXTS):
        return "unavailable"
    if _fatigue_has_any_text(texts, FATIGUE_DRINK_SKIP_CONFIRM_TEXTS):
        return "skip_confirm"
    if _fatigue_has_any_text(texts, FATIGUE_DRINK_REPEAT_CONFIRM_TEXTS) or (
        "再喝一杯" in joined and any(keyword in joined for keyword in ("取消", "当前生效", "失效时间", "剩余", "当天不再"))
    ):
        return "repeat_confirm"
    if _fatigue_has_any_text(texts, FATIGUE_DRINK_RESULT_TEXTS):
        return "result_popup"
    if "银枝气泡水" in joined or "本次免费" in joined or ("喝一杯吗" in joined and "再喝一杯" not in joined):
        return "drink_select"
    if "休息区" in joined or "所有城市合计每日提供" in joined:
        return "rest_area"
    if _fatigue_has_any_text(texts, FATIGUE_STRENGTH_PAGE_TEXTS):
        return "strength_page"
    if _fatigue_has_any_text(texts, FATIGUE_DRINK_SKIP_TEXTS):
        return "skip"
    if _fatigue_has_any_text(texts, FATIGUE_DRINK_CONFIRM_TEXTS) or _fatigue_has_any_text(texts, FATIGUE_NO_REMIND_TEXTS):
        return "confirm_popup"
    return "unknown"


def _fatigue_finish_one_drink(context: Context, *, attempt: int, timeout: float = 16.0) -> str:
    start = time.monotonic()
    skip_fallback_clicked = False
    confirm_clicked = False
    saw_progress = True
    while time.monotonic() - start < timeout:
        texts = _fatigue_drink_texts(context, f"FatigueDrinkFinishProbe{attempt:03d}")
        if _fatigue_dismiss_drink_cost_confirm(context, texts):
            return "cost_confirm"
        if _fatigue_has_any_text(texts, FATIGUE_DRINK_UNAVAILABLE_TEXTS):
            return "unavailable"
        kind = _fatigue_drink_page_kind(texts)
        if saw_progress and time.monotonic() - start > 1.2 and kind in {"drink_select", "rest_area", "strength_page"}:
            return "done"
        if kind == "result_popup" and time.monotonic() - start > 0.8:
            return "done"
        if kind == "repeat_confirm":
            if not _fatigue_handle_drink_repeat_confirm(context, attempt=attempt):
                return "repeat_confirm_stuck"
            saw_progress = True
            continue
        if kind == "skip_confirm":
            if not _fatigue_handle_drink_skip_confirm(context, attempt=attempt):
                return "skip_confirm_stuck"
            saw_progress = True
            continue
        if kind == "skip":
            clicked, _ = _fatigue_click_drink_text(
                context,
                f"FatigueDrinkTapSkip{attempt:03d}",
                FATIGUE_DRINK_SKIP_TEXTS,
                roi=[1040, 0, 240, 120],
                fallback=(1218, 42),
                delay=0.8,
            )
            saw_progress = saw_progress or clicked
            continue
        if kind == "confirm_popup":
            _fatigue_tap_no_remind_if_present(context, f"FatigueDrinkConfirmNoRemind{attempt:03d}")
            clicked, _ = _fatigue_click_drink_text(
                context,
                f"FatigueDrinkConfirmPopup{attempt:03d}",
                FATIGUE_DRINK_CONFIRM_TEXTS + FATIGUE_DRINK_SKIP_TEXTS,
                roi=[540, 340, 720, 350],
                fallback=(1000, 585),
                delay=0.9,
            )
            confirm_clicked = confirm_clicked or clicked
            saw_progress = saw_progress or clicked
            continue
        if not skip_fallback_clicked and time.monotonic() - start > 2.0:
            _manual_two_city_click(context, (1218, 42), 0.8)
            skip_fallback_clicked = True
            saw_progress = True
            continue
        if confirm_clicked and kind in {"unknown", "confirm_popup"}:
            time.sleep(0.45)
            continue
        time.sleep(0.45)
    return "timeout"


def _fatigue_record_drink_used(state: dict[str, Any], count: int) -> None:
    if count <= 0:
        return
    used = state.setdefault("used", {})
    used["喝酒"] = int(used.get("喝酒") or 0) + count


def _run_fatigue_drink_until_cost(
    context: Context,
    *,
    state: dict[str, Any],
    task_entry: str,
    max_attempts: int,
) -> int:
    global _FATIGUE_DRINK_LOG_TASK_ENTRY
    previous_task_entry = _FATIGUE_DRINK_LOG_TASK_ENTRY
    _FATIGUE_DRINK_LOG_TASK_ENTRY = task_entry
    drank_count = 0
    stop_reason = "max_attempts"
    probe_step = 0
    max_probe_steps = max(max_attempts * 6, max_attempts + 8)
    result_popup_logged = False
    try:
        _append_user_log(
            task_entry,
            "喝酒：开始循环选择银枝气泡水，遇到使用银枝提示即停止。",
            event="fatigue_drink_loop_started",
            data={"max_attempts": max_attempts, "max_probe_steps": max_probe_steps},
        )
        attempt = 1
        while attempt <= max_attempts and probe_step < max_probe_steps:
            probe_step += 1
            texts = _fatigue_drink_texts(context, f"FatigueDrinkLoopProbe{attempt:03d}")
            kind = _fatigue_drink_page_kind(texts)
            if kind == "cost_confirm":
                _fatigue_dismiss_drink_cost_confirm(context, texts)
                stop_reason = "cost_confirm"
                break
            if kind == "unavailable":
                state.setdefault("unavailable", {})["喝酒"] = "次数或城市条件不可用"
                _append_user_log(
                    task_entry,
                    "喝酒：页面提示次数或城市条件不可用，停止喝酒循环。",
                    level="warning",
                    event="fatigue_drink_unavailable",
                    data={"texts": texts[:30]},
                )
                stop_reason = "unavailable"
                break
            if kind == "result_popup":
                if not result_popup_logged:
                    _append_user_log(
                        task_entry,
                        "喝酒：检测到恢复结果浮层，等待关闭后继续喝下一杯。",
                        event="fatigue_drink_result_popup_seen",
                        data={"attempt": attempt, "drank_count": drank_count, "texts": texts[:30]},
                    )
                    result_popup_logged = True
                _manual_two_city_click(context, (640, 500), 0.8)
                continue
            if kind == "strength_page":
                clicked, _ = _fatigue_click_drink_text(
                    context,
                    f"FatigueDrinkTapEntry{attempt:03d}",
                    FATIGUE_DRINK_ACTION_TEXTS,
                    roi=[1010, 150, 240, 495],
                    fallback=(1112, 343),
                    delay=1.0,
                )
                if not clicked:
                    stop_reason = "entry_click_failed"
                    break
                continue
            if kind == "rest_area":
                clicked, _ = _fatigue_click_drink_text(
                    context,
                    f"FatigueDrinkTapRestArea{attempt:03d}",
                    ["喝一杯"],
                    roi=[720, 260, 490, 115],
                    fallback=(1162, 325),
                    delay=1.0,
                )
                if not clicked:
                    stop_reason = "rest_area_click_failed"
                    break
                continue
            if kind == "confirm_popup":
                _fatigue_tap_no_remind_if_present(context, f"FatigueDrinkOuterConfirmNoRemind{attempt:03d}")
                _fatigue_click_drink_text(
                    context,
                    f"FatigueDrinkOuterConfirm{attempt:03d}",
                    FATIGUE_DRINK_CONFIRM_TEXTS + FATIGUE_DRINK_SKIP_TEXTS,
                    roi=[540, 340, 720, 350],
                    fallback=(1000, 585),
                    delay=0.9,
                )
                result = _fatigue_finish_one_drink(context, attempt=attempt)
            elif kind == "repeat_confirm":
                if not _fatigue_handle_drink_repeat_confirm(context, attempt=attempt):
                    result = "repeat_confirm_stuck"
                else:
                    result = _fatigue_finish_one_drink(context, attempt=attempt)
            elif kind == "skip_confirm":
                result = _fatigue_finish_one_drink(context, attempt=attempt)
            else:
                if kind != "drink_select":
                    clicked, _ = _fatigue_click_drink_text(
                        context,
                        f"FatigueDrinkEnsureEntry{attempt:03d}",
                        FATIGUE_DRINK_ACTION_TEXTS,
                        roi=[1010, 150, 240, 495],
                        fallback=(1112, 343),
                        delay=1.0,
                    )
                    if not clicked:
                        stop_reason = "ensure_entry_failed"
                        break
                    continue
                clicked, _ = _fatigue_click_drink_text(
                    context,
                    f"FatigueDrinkTapSilverSoda{attempt:03d}",
                    ["银枝气泡水"],
                    roi=[700, 330, 520, 170],
                    fallback=(1162, 421),
                    delay=0.9,
                )
                if not clicked:
                    stop_reason = "drink_select_click_failed"
                    break
                result = _fatigue_finish_one_drink(context, attempt=attempt)
            if result == "done":
                drank_count += 1
                result_popup_logged = False
                _fatigue_record_drink_used(state, 1)
                _append_user_log(
                    task_entry,
                    f"喝酒：已完成第 {drank_count} 杯。",
                    event="fatigue_drink_one_done",
                    data={"attempt": attempt, "drank_count": drank_count},
                )
                attempt += 1
                continue
            if result == "cost_confirm":
                stop_reason = "cost_confirm"
                break
            if result == "unavailable":
                state.setdefault("unavailable", {})["喝酒"] = "次数或城市条件不可用"
                stop_reason = "unavailable"
                break
            stop_reason = result
            _append_user_log(
                task_entry,
                f"喝酒：第 {attempt} 杯等待结果异常（{result}），停止喝酒循环。",
                level="warning",
                event="fatigue_drink_loop_interrupted",
                data={"attempt": attempt, "result": result},
            )
            break
        if attempt > max_attempts and stop_reason == "max_attempts":
            stop_reason = "target_reached"
        if probe_step >= max_probe_steps and attempt <= max_attempts:
            stop_reason = "probe_step_limit"
            _append_user_log(
                task_entry,
                f"喝酒：页面状态连续检查 {probe_step} 次仍未完成目标，停止喝酒循环。",
                level="warning",
                event="fatigue_drink_probe_step_limit",
                data={"attempt": attempt, "drank_count": drank_count, "max_attempts": max_attempts},
            )
        _append_user_log(
            task_entry,
            f"喝酒：循环结束，本次完成 {drank_count}/{max_attempts} 杯，停止原因 {stop_reason}。",
            event="fatigue_drink_loop_finished",
            data={"drank_count": drank_count, "max_attempts": max_attempts, "stop_reason": stop_reason, "used": dict(state.get("used") or {})},
        )
        state["stop_reason"] = stop_reason
        return drank_count
    finally:
        _FATIGUE_DRINK_LOG_TASK_ENTRY = previous_task_entry


@AgentServer.custom_action("manual_two_city_business_current_city_ready")
class ManualTwoCityBusinessCurrentCityReadyAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        source = str(params.get("source") or "unknown").strip()
        texts = _ocr_texts(argv)
        legs = _manual_two_city_legs()
        current_city = _manual_two_city_detect_current_city(texts, legs)
        state = _manual_two_city_state()
        if current_city:
            state["current_city"] = current_city
        leg = _manual_two_city_set_active_leg_by_city(current_city) if current_city else _manual_two_city_active_leg()
        if current_city:
            message = (
                f"当前位置识别（{source}）：{current_city}，"
                f"执行 {leg.get('buy_city') or '-'} -> {leg.get('sell_city') or '-'}"
            )
        else:
            message = (
                f"当前位置识别（{source}）：未识别，"
                f"沿用 {leg.get('buy_city') or '-'} -> {leg.get('sell_city') or '-'}"
            )
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            message,
            event="manual_two_city_current_city_ready",
            data={
                "source": source,
                "current_city": current_city,
                "active_leg_index": _manual_two_city_state().get("active_leg_index"),
                "leg": leg,
                "texts": texts[:40],
            },
        )
        _json_payload(
            "manual_two_city_business_current_city_ready",
            {"ok": True, "source": source, "current_city": current_city, "leg": leg},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_should_read_city_page")
class ManualTwoCityBusinessShouldReadCityPageAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        current_city = normalize_city_name(str(state.get("current_city") or "").strip())
        should_read = not bool(current_city)
        if not should_read:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"当前位置已在主界面识别为 {current_city}，跳过城市页重复识别。",
                event="manual_two_city_skip_city_page_current_city_read",
                data={"current_city": current_city},
            )
        _json_payload(
            "manual_two_city_business_should_read_city_page",
            {"ok": should_read, "current_city": current_city},
        )
        return should_read


@AgentServer.custom_action("manual_two_city_business_use_buy_books")
class ManualTwoCityBusinessUseBuyBooksAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        leg = _manual_two_city_active_leg()
        restock_count = leg.get("restock")
        batches = _manual_two_city_book_batches(restock_count)
        if not batches:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"进货书：{leg.get('buy_city') or '当前城市'} 本段无需使用进货书。",
                event="manual_two_city_buy_books_skipped",
                data={"leg": leg},
            )
            _json_payload("manual_two_city_business_use_buy_books", {"ok": True, "restock": 0})
            return True

        try:
            for batch_index, batch in enumerate(batches, start=1):
                buy_page_hit, _, buy_page_texts = _manual_two_city_ocr_entries(
                    context,
                    f"ManualTwoCityBuyPageBeforeBook{batch_index:03d}",
                    BUY_PAGE_READY_TEXTS,
                )
                if not buy_page_hit:
                    raise RuntimeError(f"not on buy page before using book: {buy_page_texts[:12]}")

                opened, tool_texts = _manual_two_city_click_ocr_text(
                    context,
                    f"ManualTwoCityOpenBookTool{batch_index:03d}",
                    ["使用道具"],
                    roi=BUY_BOOK_TOOL_ROI,
                    fallback=BUY_BOOK_TOOL_TARGET,
                    delay=1.05,
                )
                if not opened:
                    raise RuntimeError(f"cannot open item tool: {tool_texts[:12]}")

                menu_hit, menu_entries, menu_texts = _manual_two_city_ocr_entries(
                    context,
                    f"ManualTwoCityBookMenu{batch_index:03d}",
                    BUY_BOOK_MENU_TEXTS,
                    roi=BUY_BOOK_MENU_PANEL_ROI,
                )
                if not menu_hit:
                    raise RuntimeError(f"cannot find buy book menu item: {menu_texts[:12]}")

                clicked_menu = False
                for entry in menu_entries:
                    if not _manual_two_city_entry_matches(entry, BUY_BOOK_MENU_TEXTS):
                        continue
                    x = BUY_BOOK_MENU_USE_BUTTON_X
                    y = int(float(entry.get("center_y") or 0))
                    _manual_two_city_click(context, (x, y), 1.0)
                    clicked_menu = True
                    break
                if not clicked_menu:
                    for fallback_target in BUY_BOOK_MENU_FALLBACK_TARGETS:
                        _manual_two_city_click(context, fallback_target, 0.7)
                        popup_hit, _, _ = _manual_two_city_ocr_entries(
                            context,
                            f"ManualTwoCityBookPopupFallback{batch_index:03d}",
                            BUY_BOOK_POPUP_TEXTS,
                            roi=BUY_BOOK_POPUP_ROI,
                        )
                        if popup_hit:
                            break

                popup_hit, _, popup_texts = _manual_two_city_ocr_entries(
                    context,
                    f"ManualTwoCityBookPopup{batch_index:03d}",
                    BUY_BOOK_POPUP_TEXTS,
                    roi=BUY_BOOK_POPUP_ROI,
                )
                if not popup_hit:
                    raise RuntimeError(f"buy book popup did not open: {popup_texts[:12]}")

                for _ in range(max(0, batch - 1)):
                    _manual_two_city_click(context, BUY_BOOK_INCREMENT_TARGET, 0.35)

                confirmed, confirm_texts = _manual_two_city_click_ocr_text(
                    context,
                    f"ManualTwoCityConfirmBook{batch_index:03d}",
                    ["确认"],
                    roi=BUY_BOOK_CONFIRM_ROI,
                    fallback=BUY_BOOK_CONFIRM_TARGET,
                    delay=1.6,
                )
                if not confirmed:
                    raise RuntimeError(f"cannot confirm buy book use: {confirm_texts[:12]}")

                after_hit, _, after_texts = _manual_two_city_ocr_entries(
                    context,
                    f"ManualTwoCityBuyPageAfterBook{batch_index:03d}",
                    BUY_PAGE_READY_TEXTS,
                )
                if not after_hit:
                    raise RuntimeError(f"buy page not ready after using book: {after_texts[:12]}")

                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    f"进货书：第 {batch_index} 批使用 {batch} 本。",
                    event="manual_two_city_buy_book_batch",
                    data={"batch_index": batch_index, "batch": batch, "leg": leg},
                )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"进货书使用失败：{error}",
                level="error",
                event="manual_two_city_buy_books_failed",
                data={"leg": leg, "batches": batches, "traceback": traceback.format_exc(limit=6)},
            )
            _json_payload("manual_two_city_business_use_buy_books_failed", {"ok": False, "error": error})
            return False

        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"进货书：已使用 {sum(batches)} 本，继续选择计划商品。",
            event="manual_two_city_buy_books_done",
            data={"restock": sum(batches), "batches": batches, "leg": leg},
        )
        _json_payload(
            "manual_two_city_business_use_buy_books",
            {"ok": True, "restock": sum(batches), "batches": batches},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_apply_buy_haggle")
class ManualTwoCityBusinessApplyBuyHaggleAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        leg = _manual_two_city_active_leg()
        target_percent = _manual_two_city_buy_bargain_percent(leg)
        if target_percent <= 0:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"砍价：{leg.get('buy_city') or '当前城市'} 本段无需砍价。",
                event="manual_two_city_buy_haggle_skipped",
                data={"leg": leg},
            )
            _json_payload("manual_two_city_business_apply_buy_haggle", {"ok": True, "target_percent": 0})
            return True

        try:
            click_count = 0
            haggle_book_used = False
            current_percent: float | None = None
            final_percent: float | None = None
            start_time = time.perf_counter()
            while time.perf_counter() - start_time < 30.0:
                if _manual_two_city_confirm_buy_haggle_book_popup(
                    context,
                    leg=leg,
                    target_percent=target_percent,
                    current_percent=current_percent,
                    click_count=click_count,
                    probe_name=f"ManualTwoCityBuyHaggleBookBeforeRead{click_count + 1:03d}",
                    allow_confirm=not haggle_book_used,
                ):
                    haggle_book_used = True
                    continue

                current_percent = _manual_two_city_read_buy_haggle_percent(context)
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    f"砍价：当前 {_manual_two_city_format_percent(current_percent)}%，目标 {target_percent}%。",
                    event="manual_two_city_buy_haggle_progress",
                    data={"current_percent": current_percent, "target_percent": target_percent, "click_count": click_count, "leg": leg},
                )
                if current_percent is not None and current_percent >= target_percent:
                    break

                clicked, button_texts = _manual_two_city_click_ocr_text(
                    context,
                    f"ManualTwoCityBuyHaggleButton{click_count + 1:03d}",
                    BUY_HAGGLE_BUTTON_TEXTS,
                    roi=BUY_HAGGLE_BUTTON_ROI,
                    fallback=BUY_HAGGLE_BUTTON_TARGET,
                    delay=1.65,
                )
                if not clicked:
                    raise RuntimeError(f"cannot find haggle button: {button_texts[:12]}")
                click_count += 1

                if _manual_two_city_confirm_buy_haggle_book_popup(
                    context,
                    leg=leg,
                    target_percent=target_percent,
                    current_percent=current_percent,
                    click_count=click_count,
                    probe_name=f"ManualTwoCityBuyHaggleBookAfterClick{click_count:03d}",
                    allow_confirm=not haggle_book_used,
                ):
                    haggle_book_used = True
                    continue

                unavailable_hit, _, unavailable_texts = _manual_two_city_ocr_entries(
                    context,
                    f"ManualTwoCityBuyHaggleUnavailable{click_count:03d}",
                    BUY_HAGGLE_UNAVAILABLE_TEXTS,
                )
                if unavailable_hit:
                    _append_user_log(
                        MANUAL_TWO_CITY_TASK_ENTRY,
                        f"砍价：识别到次数不足提示，但没有发现请求书确认弹窗，当前 {_manual_two_city_format_percent(current_percent)}%。",
                        level="warning",
                        event="manual_two_city_buy_haggle_unavailable_without_book_popup",
                        data={
                            "target_percent": target_percent,
                            "current_percent": current_percent,
                            "click_count": click_count,
                            "texts": unavailable_texts[:20],
                            "leg": leg,
                        },
                    )
                    break

                time.sleep(0.35)
            else:
                raise RuntimeError(f"haggle target timeout: current={current_percent}, target={target_percent}")

            final_percent = _manual_two_city_read_buy_haggle_percent(context)
            if final_percent is not None and final_percent < target_percent:
                raise RuntimeError(f"haggle target not reached: current={final_percent}, target={target_percent}")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"砍价操作失败：{error}",
                level="error",
                event="manual_two_city_buy_haggle_failed",
                data={"leg": leg, "target_percent": target_percent, "traceback": traceback.format_exc(limit=6)},
            )
            _json_payload("manual_two_city_business_apply_buy_haggle_failed", {"ok": False, "error": error})
            return False

        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"砍价：已达到 {_manual_two_city_format_percent(final_percent if final_percent is not None else target_percent)}%（目标 {target_percent}%），继续全部买入。",
            event="manual_two_city_buy_haggle_done",
            data={"target_percent": target_percent, "final_percent": final_percent, "click_count": click_count, "leg": leg},
        )
        _json_payload(
            "manual_two_city_business_apply_buy_haggle",
            {"ok": True, "target_percent": target_percent, "final_percent": final_percent, "click_count": click_count, "leg": leg},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_buy_page_ready")
class ManualTwoCityBusinessBuyPageReadyAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        texts = _ocr_texts(argv)
        entries = _ocr_entries(argv)
        legs = _manual_two_city_legs()
        current_city = _manual_two_city_detect_current_city(texts, legs)
        state = _manual_two_city_state()
        if current_city:
            state["current_city"] = current_city
        leg = _manual_two_city_set_active_leg_by_city(current_city) if current_city else _manual_two_city_active_leg()
        planned_goods = [str(item) for item in (leg.get("goods") or []) if str(item).strip()]
        cargo_load, cargo_probe_texts, cargo_probe_used = _manual_two_city_read_buy_page_cargo_load(context, entries)
        cleanup_signature = None
        if cargo_load is not None:
            cleanup_signature = (
                f"{state.get('active_leg_index')}|{current_city or leg.get('buy_city') or ''}|"
                f"{cargo_load.get('used')}|{cargo_load.get('capacity')}"
            )
        if cargo_load is not None and cargo_load["ratio"] > PRE_BUY_CLEANUP_WARN_RATIO:
            if cleanup_signature and state.get("pre_buy_cleanup_skip_signature") == cleanup_signature:
                if cargo_load["ratio"] >= PRE_BUY_SKIP_BUY_FULL_RATIO:
                    state.pop("pre_buy_cleanup", None)
                    state.pop("pre_buy_cleanup_raise_percent", None)
                    state.pop("pre_buy_cleanup_cargo", None)
                    state.pop("pre_buy_cleanup_strength_required", None)
                    state.pop("pre_buy_cleanup_signature", None)
                    state.pop("pre_buy_cleanup_skip_signature", None)
                    state["selected_buy_goods"] = []
                    state["skip_buy_due_full_cargo"] = True
                    state["skip_buy_due_full_cargo_load"] = cargo_load
                    state["skip_buy_due_full_cargo_leg"] = leg
                    state["trade_phase"] = "travel"
                    _append_user_log(
                        MANUAL_TWO_CITY_TASK_ENTRY,
                        (
                            f"买入前清仓：货仓 {cargo_load['used']}/{cargo_load['capacity']} "
                            f"({cargo_load['ratio']:.1%})，卖出页已确认无法继续卖出。"
                            "本段视为已带货，跳过买入并直接前往卖出城市。"
                        ),
                        level="warning",
                        event="manual_two_city_pre_buy_cleanup_full_cargo_skip_buy",
                        data={
                            "current_city": current_city,
                            "active_leg_index": state.get("active_leg_index"),
                            "leg": leg,
                            "cargo_load": cargo_load,
                            "cleanup_signature": cleanup_signature,
                        },
                    )
                    _json_payload(
                        "manual_two_city_business_buy_page_ready",
                        {
                            "ok": True,
                            "reason": "skip_buy_due_full_cargo",
                            "current_city": current_city,
                            "leg": leg,
                            "cargo_load": cargo_load,
                        },
                    )
                    return True
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    (
                        f"买入前清仓：货仓 {cargo_load['used']}/{cargo_load['capacity']} "
                        "已确认主要为本地货，本轮跳过清仓并继续买入。"
                    ),
                    level="warning",
                    event="manual_two_city_pre_buy_cleanup_skipped_after_local_goods",
                    data={
                        "current_city": current_city,
                        "active_leg_index": state.get("active_leg_index"),
                        "leg": leg,
                        "cargo_load": cargo_load,
                        "cleanup_signature": cleanup_signature,
                    },
                )
                state.pop("pre_buy_cleanup", None)
                state.pop("pre_buy_cleanup_raise_percent", None)
                state.pop("pre_buy_cleanup_cargo", None)
                state.pop("pre_buy_cleanup_strength_required", None)
                state.pop("pre_buy_cleanup_signature", None)
            else:
                raise_percent = PRE_BUY_CLEANUP_RAISE_PERCENT if cargo_load["ratio"] > PRE_BUY_CLEANUP_RAISE_RATIO else 0
                cleanup_required = _manual_two_city_pre_buy_cleanup_required_fatigue(state, leg, raise_percent)
                state["pre_buy_cleanup"] = True
                state["pre_buy_cleanup_raise_percent"] = raise_percent
                state["pre_buy_cleanup_cargo"] = cargo_load
                state["pre_buy_cleanup_strength_required"] = cleanup_required
                if cleanup_signature:
                    state["pre_buy_cleanup_signature"] = cleanup_signature
                state["selected_buy_goods"] = []
                try:
                    clicked, switch_texts = _manual_two_city_click_ocr_text(
                        context,
                        "ManualTwoCityPreBuySwitchToSell",
                        ["我要卖"],
                        roi=TRADE_SWITCH_TO_SELL_ROI,
                        fallback=TRADE_SWITCH_TO_SELL_TARGET,
                        delay=1.0,
                    )
                except Exception as exc:
                    _append_user_log(
                        MANUAL_TWO_CITY_TASK_ENTRY,
                        f"买入前清仓：切换卖出页失败：{type(exc).__name__}: {exc}",
                        level="error",
                        event="manual_two_city_pre_buy_cleanup_switch_failed",
                        data={
                            "current_city": current_city,
                            "active_leg_index": state.get("active_leg_index"),
                            "leg": leg,
                            "cargo_load": cargo_load,
                            "traceback": traceback.format_exc(limit=6),
                        },
                    )
                    _json_payload(
                        "manual_two_city_business_buy_page_ready",
                        {"ok": False, "reason": "pre_buy_cleanup_switch_failed", "cargo_load": cargo_load, "error": str(exc)},
                    )
                    return False
                if not clicked:
                    _json_payload(
                        "manual_two_city_business_buy_page_ready",
                        {"ok": False, "reason": "pre_buy_cleanup_switch_not_clicked", "cargo_load": cargo_load},
                    )
                    return False
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    (
                        f"买入前清仓：货仓 {cargo_load['used']}/{cargo_load['capacity']} "
                        f"({cargo_load['ratio']:.1%})，已切换卖出页，"
                        f"{'将抬价 20% 后卖出' if raise_percent else '将不抬价直接卖出'}。"
                    ),
                    level="warning",
                    event="manual_two_city_pre_buy_cleanup_needed",
                    data={
                        "current_city": current_city,
                        "active_leg_index": state.get("active_leg_index"),
                        "leg": leg,
                        "cargo_load": cargo_load,
                        "raise_percent": raise_percent,
                        "strength_required": cleanup_required,
                        "switch_texts": switch_texts[:20],
                    },
                )
                _json_payload(
                    "manual_two_city_business_buy_page_ready",
                    {
                        "ok": True,
                        "current_city": current_city,
                        "leg": leg,
                        "pre_buy_cleanup": True,
                        "cargo_load": cargo_load,
                        "raise_percent": raise_percent,
                        "strength_required": cleanup_required,
                    },
                )
                return True

        state.pop("pre_buy_cleanup", None)
        state.pop("pre_buy_cleanup_raise_percent", None)
        state.pop("pre_buy_cleanup_cargo", None)
        state.pop("pre_buy_cleanup_strength_required", None)
        state.pop("pre_buy_cleanup_signature", None)
        cargo_note = (
            f"，货仓 {cargo_load['used']}/{cargo_load['capacity']} ({cargo_load['ratio']:.1%})"
            if cargo_load is not None
            else "，货仓载量读取失败"
        )
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            (
                f"买入页：当前城市 {current_city or '未识别'}，"
                f"执行 {leg.get('buy_city') or '-'} -> {leg.get('sell_city') or '-'}，"
                f"计划商品 {len(planned_goods)} 个{cargo_note}"
            ),
            event="manual_two_city_buy_page_ready",
            data={
                "current_city": current_city,
                "active_leg_index": state.get("active_leg_index"),
                "leg": leg,
                "cargo_load": cargo_load,
                "cargo_probe_used": cargo_probe_used,
                "cargo_probe_texts": cargo_probe_texts[:12],
                "texts": texts[:40],
            },
        )
        _json_payload(
            "manual_two_city_business_buy_page_ready",
            {"ok": True, "current_city": current_city, "leg": leg, "cargo_load": cargo_load},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_skip_buy_due_full_cargo")
class ManualTwoCityBusinessSkipBuyDueFullCargoAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        if not state.pop("skip_buy_due_full_cargo", False):
            _json_payload("manual_two_city_business_skip_buy_due_full_cargo", {"ok": False, "reason": "not_pending"})
            return False
        cargo_load = state.pop("skip_buy_due_full_cargo_load", None)
        leg = state.pop("skip_buy_due_full_cargo_leg", None) or _manual_two_city_active_leg()
        state["selected_buy_goods"] = []
        state["trade_phase"] = "travel"
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            (
                f"满仓跳过买入：当前货仓 "
                f"{cargo_load.get('used') if isinstance(cargo_load, dict) else '-'}/"
                f"{cargo_load.get('capacity') if isinstance(cargo_load, dict) else '-'}，"
                f"直接前往 {leg.get('sell_city') or '目标城市'}。"
            ),
            level="warning",
            event="manual_two_city_skip_buy_due_full_cargo",
            data={"cargo_load": cargo_load, "leg": leg, "active_leg_index": state.get("active_leg_index")},
        )
        _json_payload(
            "manual_two_city_business_skip_buy_due_full_cargo",
            {"ok": True, "cargo_load": cargo_load, "leg": leg, "active_leg_index": state.get("active_leg_index")},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_startup_travel_check")
class ManualTwoCityBusinessStartupTravelCheckAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        texts = _ocr_texts(argv)
        if not texts:
            _hit, _entries, texts = _manual_two_city_ocr_entries(
                context,
                "ManualTwoCityStartupTravelCheck",
                ["目的地", "剩余行程", "巡航"],
                roi=[460, 16, 380, 145],
            )
        status = travel_status_from_texts(texts)
        destination = _manual_two_city_startup_travel_destination(texts, status)
        if not destination:
            _json_payload(
                "manual_two_city_business_startup_travel_check",
                {"ok": False, "reason": "destination_unknown", "status": status, "texts": texts[:30]},
            )
            return False

        state["startup_travel_pending"] = True
        state["startup_travel_detected_destination_city"] = destination
        state["startup_travel_detected_status"] = status
        state["trade_phase"] = "travel"
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"开局检测：当前已在行车途中，目的地 {destination}，准备判断继续前往或立刻返航。",
            level="warning",
            event="manual_two_city_startup_travel_detected",
            data={"destination": destination, "status": status, "texts": texts[:30]},
        )
        _json_payload(
            "manual_two_city_business_startup_travel_check",
            {"ok": True, "destination": destination, "status": status, "texts": texts[:30]},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_startup_travel_fallback_recovery")
class ManualTwoCityBusinessStartupTravelFallbackRecoveryAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        restart_count = int(state.get("travel_stall_restart_count") or 0)
        if restart_count >= MANUAL_TWO_CITY_TRAVEL_STALL_MAX_RESTARTS or state.get("travel_recovering_from_stall"):
            state["terminal_status"] = MANUAL_TWO_CITY_TERMINAL_FAILED
            state["terminal_reason"] = "行车异常重启后仍未能识别当前界面"
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                "行车异常：已重启过一次，但仍未识别当前行车/遇怪/到站状态，停止任务以避免反复重启。",
                level="error",
                event="manual_two_city_startup_travel_recovery_limit_reached",
                data={"restart_count": restart_count, "texts": _ocr_texts(argv)[:30]},
            )
            _json_payload(
                "manual_two_city_business_startup_travel_fallback_recovery",
                {"ok": False, "reason": "restart_limit_reached", "restart_count": restart_count},
            )
            return False

        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "开局检测：未识别到行车 HUD 或行车事件，转入状态恢复兜底。",
            level="warning",
            event="manual_two_city_startup_travel_fallback_recovery",
            data={"texts": _ocr_texts(argv)[:30]},
        )
        _json_payload(
            "manual_two_city_business_startup_travel_fallback_recovery",
            {"ok": True, "restart_count": restart_count},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_startup_travel_resolve_direction")
class ManualTwoCityBusinessStartupTravelResolveDirectionAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        destination = normalize_city_name(str(state.get("startup_travel_detected_destination_city") or "").strip())
        if not state.get("startup_travel_pending") or not destination:
            _json_payload(
                "manual_two_city_business_startup_travel_resolve_direction",
                {"ok": False, "reason": "no_pending_startup_travel", "destination": destination},
            )
            return False

        start_city, target_city = _manual_two_city_endpoint_cities()
        if destination in {start_city, target_city}:
            decision = _manual_two_city_prepare_startup_travel_monitor(
                destination,
                choice={
                    "direction": "continue",
                    "city": destination,
                    "nearest_endpoint": destination,
                    "fatigue": 0,
                    "estimated": False,
                    "reason": "destination_is_route_endpoint",
                },
            )
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"开局行车决策：目的地 {destination} 已是配置路线城市，继续前往并监听行车状态。",
                level="warning",
                event="manual_two_city_startup_travel_continue_endpoint",
                data={"destination": destination, "start_city": start_city, "target_city": target_city, "decision": decision},
            )
            _json_payload(
                "manual_two_city_business_startup_travel_resolve_direction",
                {"ok": True, **decision},
            )
            return True

        popup_texts: list[str] = []
        return_city = ""
        immediate_return_hit = False
        for target in ((1010, 455), (1000, 570)):
            _manual_two_city_click(context, target, 0.45)
            immediate_return_hit, menu_texts = _manual_two_city_click_ocr_text(
                context,
                "ManualTwoCityStartupTravelImmediateReturn",
                ["立刻返航"],
                roi=[360, 230, 560, 270],
                fallback=None,
                delay=0.75,
            )
            if immediate_return_hit:
                popup_texts = menu_texts
                break
        if not immediate_return_hit:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                "开局行车：未直接识别到“立刻返航”，尝试点击屏幕中心打开返航确认。",
                level="warning",
                event="manual_two_city_startup_travel_return_menu_fallback",
                data={"destination": destination},
            )
            _manual_two_city_click(context, (640, 360), 0.75)

        for _ in range(4):
            _hit, _entries, popup_texts = _manual_two_city_ocr_entries(
                context,
                "ManualTwoCityStartupTravelReturnPopup",
                ["是否立刻返航", "立刻返航", "回到"],
                roi=[180, 120, 940, 520],
            )
            return_city = _manual_two_city_return_city_from_popup_texts(popup_texts)
            if return_city:
                break
            time.sleep(0.35)

        if not return_city:
            _manual_two_city_click_ocr_text(
                context,
                "ManualTwoCityStartupTravelCancelUnknownPopup",
                ["取消"],
                roi=[120, 430, 560, 170],
                fallback=(360, 540),
                delay=0.45,
            )
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"开局行车：未能识别返航城市，但目的地 {destination} 已知，取消返航弹窗后继续监听行车状态。",
                level="warning",
                event="manual_two_city_startup_travel_return_city_unknown",
                data={"destination": destination, "popup_texts": popup_texts[:30]},
            )
            decision = _manual_two_city_prepare_startup_travel_monitor(
                destination,
                choice={
                    "direction": "continue",
                    "city": destination,
                    "nearest_endpoint": "",
                    "fatigue": 999,
                    "estimated": True,
                    "reason": "return_city_unknown_continue_known_destination",
                },
            )
            _json_payload(
                "manual_two_city_business_startup_travel_resolve_direction",
                {"ok": True, **decision, "popup_texts": popup_texts[:30]},
            )
            return True

        choice = _manual_two_city_choose_startup_travel_direction(destination, return_city)
        chosen_direction = str(choice.get("direction") or "continue")
        chosen_city = normalize_city_name(str(choice.get("city") or destination).strip())
        decision = _manual_two_city_prepare_startup_travel_monitor(destination, return_city=return_city, choice=choice)

        if chosen_direction == "return":
            clicked, _texts = _manual_two_city_click_ocr_text(
                context,
                "ManualTwoCityStartupTravelConfirmReturn",
                ["确认", "确定"],
                roi=[640, 430, 560, 170],
                fallback=(915, 540),
                delay=1.0,
            )
            action_label = "确认立刻返航"
            if not clicked:
                _json_payload(
                    "manual_two_city_business_startup_travel_resolve_direction",
                    {"ok": False, "reason": "confirm_return_failed", "destination": destination, "return_city": return_city, "choice": choice},
                )
                return False
        else:
            _manual_two_city_click_ocr_text(
                context,
                "ManualTwoCityStartupTravelCancelReturn",
                ["取消"],
                roi=[120, 430, 560, 170],
                fallback=(360, 540),
                delay=0.55,
            )
            _manual_two_city_click(context, (1115, 330), 0.8)
            action_label = "取消返航并切回前进"

        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            (
                f"开局行车决策：当前目的地 {destination}，返航回到 {return_city}。"
                f"按到起点/目标最近距离选择 {chosen_city}，已{action_label}。"
            ),
            level="warning",
            event="manual_two_city_startup_travel_direction_resolved",
            data={"destination": destination, "return_city": return_city, "choice": choice, "popup_texts": popup_texts[:30]},
        )
        _json_payload(
            "manual_two_city_business_startup_travel_resolve_direction",
            {"ok": True, **decision},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_startup_travel_started")
class ManualTwoCityBusinessStartupTravelStartedAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        leg = _manual_two_city_active_leg()
        target_city = str(state.get("startup_travel_target_city") or "").strip()
        direction = str(state.get("startup_travel_direction") or "continue")
        state["travel_started_at"] = time.monotonic()
        state["travel_last_status"] = state.get("startup_travel_detected_status") or {}
        state["travel_progress_last_log_at"] = 0.0
        recovering_from_stall = bool(state.pop("travel_recovering_from_stall", False))
        _manual_two_city_reset_travel_stall_state(state, reset_restart_count=not recovering_from_stall)
        state["trade_phase"] = "travel"
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"开局行车：已接管当前路线（{'返航' if direction == 'return' else '前往'} {target_city or '目标城市'}），开始监听行车状态。",
            level="warning",
            event="manual_two_city_startup_travel_started",
            data={"target_city": target_city, "direction": direction, "leg": leg, "decision": state.get("startup_travel_decision")},
        )
        _json_payload(
            "manual_two_city_business_startup_travel_started",
            {"ok": True, "target_city": target_city, "direction": direction, "leg": leg},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_initial_transfer_needed")
class ManualTwoCityBusinessInitialTransferNeededAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        if state.get("initial_transfer_done") or state.get("initial_transfer_in_progress"):
            _json_payload("manual_two_city_business_initial_transfer_needed", {"ok": False, "reason": "already_handled"})
            return False

        texts = _ocr_texts(argv)
        current_city = _manual_two_city_detect_current_city(texts, _manual_two_city_legs()) or str(state.get("current_city") or "").strip()
        current_city = normalize_city_name(current_city)
        start_city, target_city = _manual_two_city_endpoint_cities()
        if current_city:
            state["current_city"] = current_city
        if not current_city:
            _json_payload("manual_two_city_business_initial_transfer_needed", {"ok": False, "reason": "current_city_unknown"})
            return False
        if current_city in {start_city, target_city}:
            _manual_two_city_set_active_leg_by_city(current_city)
            _json_payload(
                "manual_two_city_business_initial_transfer_needed",
                {"ok": False, "reason": "already_endpoint", "current_city": current_city, "start_city": start_city, "target_city": target_city},
            )
            return False

        transfer = _manual_two_city_choose_initial_transfer_destination(current_city)
        destination = str(transfer.get("city") or "").strip()
        base_required = _fatigue_int(transfer.get("fatigue"), 0)
        required = _manual_two_city_required_fatigue_with_buffer(base_required)
        if not destination or base_required <= 0:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"异地开局：当前城市 {current_city} 不是起点/终点，但无法计算最近端点，跳过中转分支。",
                level="warning",
                event="manual_two_city_initial_transfer_no_destination",
                data={"current_city": current_city, "transfer": transfer, "texts": texts[:40]},
            )
            _json_payload("manual_two_city_business_initial_transfer_needed", {"ok": False, "reason": "no_destination", "current_city": current_city})
            return False

        state["initial_transfer_pending"] = True
        state["initial_transfer_source_city"] = current_city
        state["initial_transfer_destination_city"] = destination
        state["initial_transfer_required_fatigue"] = required
        state["initial_transfer_base_required_fatigue"] = base_required
        state["initial_transfer_required_estimated"] = bool(transfer.get("estimated"))
        state["initial_transfer_needs_recovery"] = False
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            (
                f"异地开局：当前在 {current_city}，不是起点 {start_city} 或目标 {target_city}。"
                f"将先全买本城商品，再前往最近端点 {destination}"
                f"（预计疲劳 {base_required}，安全需求 {required}）。"
            ),
            level="warning",
            event="manual_two_city_initial_transfer_needed",
            data={
                "current_city": current_city,
                "destination": destination,
                "base_required": base_required,
                "required": required,
                "safety_buffer": MANUAL_TWO_CITY_FATIGUE_SAFETY_BUFFER,
                "transfer": transfer,
                "texts": texts[:40],
            },
        )
        _json_payload(
            "manual_two_city_business_initial_transfer_needed",
            {
                "ok": True,
                "current_city": current_city,
                "destination_city": destination,
                "base_required_fatigue": base_required,
                "required_fatigue": required,
                "safety_buffer": MANUAL_TWO_CITY_FATIGUE_SAFETY_BUFFER,
            },
        )
        return True


@AgentServer.custom_action("manual_two_city_business_initial_transfer_strength_check")
class ManualTwoCityBusinessInitialTransferStrengthCheckAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        source = str(state.get("initial_transfer_source_city") or state.get("current_city") or "").strip()
        destination = str(state.get("initial_transfer_destination_city") or "").strip()
        required = _fatigue_int(state.get("initial_transfer_required_fatigue"), 0)
        texts = _ocr_texts(argv)
        status = strength_status_from_texts(texts)
        state["initial_transfer_needs_recovery"] = False
        if not state.get("initial_transfer_pending") or not source or not destination or required <= 0:
            _json_payload("manual_two_city_business_initial_transfer_strength_check", {"ok": False, "reason": "no_pending_transfer"})
            return False
        if not status:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                "异地开局：未能读取交易所疲劳值，停止中转买入，避免买完后无法发车。",
                level="error",
                event="manual_two_city_initial_transfer_strength_unknown",
                data={"source": source, "destination": destination, "required": required, "texts": texts[:30]},
            )
            _json_payload("manual_two_city_business_initial_transfer_strength_check", {"ok": False, "reason": "strength_unknown"})
            return False
        if _manual_two_city_strength_enough(status, required):
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"异地开局疲劳检查：剩余 {status['remaining']}，足够前往 {destination}（安全需求 {required}）。",
                event="manual_two_city_initial_transfer_strength_enough",
                data={
                    "source": source,
                    "destination": destination,
                    "required": required,
                    "base_required": state.get("initial_transfer_base_required_fatigue"),
                    "safety_buffer": MANUAL_TWO_CITY_FATIGUE_SAFETY_BUFFER,
                    "status": status,
                },
            )
            _json_payload(
                "manual_two_city_business_initial_transfer_strength_check",
                {"ok": True, "needs_recovery": False, "status": status, "required": required},
            )
            return True

        methods = _manual_two_city_strength_recovery_methods(state)
        if not methods:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                (
                    f"异地开局疲劳不足：剩余 {status['remaining']}，前往 {destination} 安全需求 {required}，"
                    "且未开启便当/疲劳药/桦石，已停止。"
                ),
                level="error",
                event="manual_two_city_initial_transfer_strength_blocked",
                data={
                    "source": source,
                    "destination": destination,
                    "required": required,
                    "base_required": state.get("initial_transfer_base_required_fatigue"),
                    "safety_buffer": MANUAL_TWO_CITY_FATIGUE_SAFETY_BUFFER,
                    "status": status,
                },
            )
            _json_payload(
                "manual_two_city_business_initial_transfer_strength_check",
                {"ok": False, "reason": "strength_not_enough_and_recovery_disabled", "status": status, "required": required},
            )
            return False

        state["initial_transfer_needs_recovery"] = True
        state["strength_recovery_phase"] = "buy"
        state["trade_phase"] = "buy"
        state["strength_recovery_required"] = required
        state["strength_recovery_last_status"] = status
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            (
                f"异地开局疲劳不足：剩余 {status['remaining']}，前往 {destination} 安全需求 {required}，"
                f"准备先使用{'、'.join(methods)}。"
            ),
            event="manual_two_city_initial_transfer_strength_recovery_needed",
            data={
                "source": source,
                "destination": destination,
                "required": required,
                "base_required": state.get("initial_transfer_base_required_fatigue"),
                "safety_buffer": MANUAL_TWO_CITY_FATIGUE_SAFETY_BUFFER,
                "status": status,
                "methods": methods,
            },
        )
        _json_payload(
            "manual_two_city_business_initial_transfer_strength_check",
            {"ok": True, "needs_recovery": True, "status": status, "required": required},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_initial_transfer_strength_recovery_needed")
class ManualTwoCityBusinessInitialTransferStrengthRecoveryNeededAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        needed = bool(state.get("initial_transfer_needs_recovery"))
        _json_payload("manual_two_city_business_initial_transfer_strength_recovery_needed", {"ok": needed})
        return needed


@AgentServer.custom_action("manual_two_city_business_initial_transfer_skip_sold_out_buy")
class ManualTwoCityBusinessInitialTransferSkipSoldOutBuyAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        if not state.get("initial_transfer_pending"):
            _json_payload(
                "manual_two_city_business_initial_transfer_skip_sold_out_buy",
                {"ok": False, "reason": "no_pending_transfer"},
            )
            return False

        texts = _ocr_texts(argv)
        entries = _ocr_entries(argv)
        source = str(state.get("initial_transfer_source_city") or state.get("current_city") or "").strip()
        destination = str(state.get("initial_transfer_destination_city") or "").strip()
        required = _fatigue_int(state.get("initial_transfer_required_fatigue"), 0)
        cargo_load, cargo_probe_texts, cargo_probe_used = _manual_two_city_read_buy_page_cargo_load(context, entries)
        state["initial_transfer_pending"] = False
        state["initial_transfer_in_progress"] = True
        state["initial_transfer_buy_skipped_reason"] = "sold_out_or_no_selectable_goods"
        state["trade_phase"] = "transfer"
        state["selected_buy_goods"] = []
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            (
                f"异地开局：{source or '当前城市'} 商品已买空或没有可选商品，"
                f"跳过本城买入，返回主界面前往最近端点 {destination or '-'}（安全需求 {required}）。"
            ),
            level="warning",
            event="manual_two_city_initial_transfer_skip_sold_out_buy",
            data={
                "source": source,
                "destination": destination,
                "required": required,
                "base_required": state.get("initial_transfer_base_required_fatigue"),
                "safety_buffer": MANUAL_TWO_CITY_FATIGUE_SAFETY_BUFFER,
                "cargo_load": cargo_load,
                "cargo_probe_used": cargo_probe_used,
                "cargo_probe_texts": cargo_probe_texts[:12],
                "texts": texts[:40],
            },
        )
        _json_payload(
            "manual_two_city_business_initial_transfer_skip_sold_out_buy",
            {
                "ok": True,
                "source": source,
                "destination": destination,
                "required": required,
                "cargo_load": cargo_load,
            },
        )
        return True


def _manual_two_city_product_scan_required_goods(city_name: Any) -> list[str]:
    city = normalize_city_name(str(city_name or "").strip())
    if not city:
        return []
    status = _manual_two_city_product_status_for_city(city)
    goods = _known_buy_goods_for_city(city)
    return [
        good
        for good in goods
        if status.get(good, PRODUCT_STATUS_NEVER_SCANNED) in PRODUCT_SCAN_REQUIRED_STATUSES
    ]


def _manual_two_city_recalculate_after_product_scan(city_name: Any) -> bool:
    state = _manual_two_city_state()
    task_entry = _manual_two_city_current_task_entry(state)
    task_label = _manual_two_city_log_label(state)
    params = dict(state.get("manual_params") or {})
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    if not params:
        params = {
            "start_city": result.get("start_city"),
            "target_city": result.get("target_city"),
            "uid": result.get("uid"),
            "start_book": result.get("start_book", 0),
            "target_book": result.get("target_book", 0),
            "start_bargain_percent": result.get("start_bargain_percent", result.get("start_haggle_percent", 0)),
            "start_raise_percent": result.get("start_raise_percent", result.get("start_haggle_percent", 0)),
            "target_bargain_percent": result.get("target_bargain_percent", result.get("target_haggle_percent", 0)),
            "target_raise_percent": result.get("target_raise_percent", result.get("target_haggle_percent", 0)),
        }
    city = normalize_city_name(str(city_name or "").strip())
    try:
        transient_status = state.get("transient_product_status_by_city")
        if state.get("auto_route_enabled"):
            params = dict(state.get("auto_route_params") or {})
            if isinstance(transient_status, dict) and transient_status:
                params["transient_product_status_by_city"] = transient_status
            params["allow_default_account"] = True
            new_result = calculate_auto_two_city_trade(**params)
            state["manual_params"] = {
                "start_city": new_result.get("start_city"),
                "target_city": new_result.get("target_city"),
                "uid": new_result.get("uid") or params.get("uid"),
                "start_book": new_result.get("start_book", 0),
                "target_book": new_result.get("target_book", 0),
                "start_bargain_percent": new_result.get("start_bargain_percent", 0),
                "start_raise_percent": new_result.get("start_raise_percent", 0),
                "target_bargain_percent": new_result.get("target_bargain_percent", 0),
                "target_raise_percent": new_result.get("target_raise_percent", 0),
            }
        else:
            if isinstance(transient_status, dict) and transient_status:
                params["transient_product_status_by_city"] = transient_status
            params["allow_default_account"] = True
            new_result = calculate_manual_two_city_trade(**params)
        state["result"] = new_result
        state["manual_start_city"] = new_result.get("start_city")
        state["manual_target_city"] = new_result.get("target_city")
        state["selected_buy_goods"] = []
        legs = (new_result.get("summary") or {}).get("legs") or []
        active_index = 0
        for index, leg in enumerate(legs):
            if isinstance(leg, dict) and str(leg.get("buy_city") or "").strip() == city:
                active_index = index
                break
        state["active_leg_index"] = active_index
        output_path = save_manual_two_city_result(new_result, task_entry=task_entry)
        summary = new_result.get("summary") or {}
        _append_user_log(
            task_entry,
            (
                f"{city or '当前城市'} 商品状态扫描后已重新计算{task_label}收益："
                f"利润 {summary.get('profit')}，参考利润 {summary.get('reference_profit')}。"
            ),
            run_id=str(state.get("run_id") or ""),
            event="manual_two_city_business_recalculated_after_product_scan",
            data={
                "city": city,
                "active_leg_index": active_index,
                "summary": summary,
                "output_path": str(output_path),
            },
        )
        for index, leg in enumerate(legs, start=1):
            goods = "、".join(str(item) for item in (leg.get("goods") or [])) if isinstance(leg, dict) else ""
            if isinstance(leg, dict):
                _append_user_log(
                    task_entry,
                    (
                        f"重算第 {index} 段 {leg.get('buy_city')} -> {leg.get('sell_city')}："
                        f"利润 {leg.get('profit')}，货物 {goods or '-'}"
                    ),
                    run_id=str(state.get("run_id") or ""),
                    event="manual_two_city_business_recalculated_leg",
                    data={"leg": leg},
                )
        return True
    except Exception as exc:
        _append_user_log(
            task_entry,
            f"{city or '当前城市'} 商品状态扫描后重算{task_label}失败：{type(exc).__name__}: {exc}",
            run_id=str(state.get("run_id") or ""),
            level="error",
            event="manual_two_city_business_recalculate_after_product_scan_failed",
            data={"params": params, "city": city, "traceback": traceback.format_exc(limit=8)},
        )
        return False


def _manual_two_city_mark_buy_selection_replan_needed(
    state: dict[str, Any],
    *,
    city: str,
    missing: list[str],
    locked: list[str],
) -> None:
    retry_counts = state.setdefault("buy_selection_replan_retry_counts", {})
    retry_key = normalize_city_name(str(city or "").strip()) or str(city or "").strip()
    retry_count = int(retry_counts.get(retry_key, 0)) if isinstance(retry_counts, dict) else 0
    state["buy_selection_replan_pending"] = True
    state["buy_selection_replan_city"] = retry_key
    state["buy_selection_replan_missing"] = list(dict.fromkeys(str(item) for item in missing if str(item).strip()))
    state["buy_selection_replan_locked"] = list(dict.fromkeys(str(item) for item in locked if str(item).strip()))
    state["buy_selection_replan_retry_count"] = retry_count


@AgentServer.custom_action("manual_two_city_business_product_scan_needed")
class ManualTwoCityBusinessProductScanNeededAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        texts = _ocr_texts(argv)
        legs = _manual_two_city_legs()
        current_city = _manual_two_city_detect_current_city(texts, legs)
        state = _manual_two_city_state()
        if current_city:
            state["current_city"] = current_city
        leg = _manual_two_city_set_active_leg_by_city(current_city) if current_city else _manual_two_city_active_leg()
        city = normalize_city_name(str((leg or {}).get("buy_city") or current_city or "").strip())
        state_city = normalize_city_name(str(state.get("current_city") or "").strip())
        if state_city and city and state_city != city:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"商品状态扫描：当前交易所是 {state_city}，不是计划买入城市 {city}，跳过扫描以避免写错配置。",
                run_id=str(state.get("run_id") or ""),
                level="warning",
                event="manual_two_city_product_scan_wrong_city_skipped",
                data={"current_city": state_city, "planned_city": city, "leg": leg, "texts": texts[:40]},
            )
            _json_payload(
                "manual_two_city_business_product_scan_needed",
                {"ok": False, "reason": "wrong_city", "current_city": state_city, "planned_city": city},
            )
            return False
        completed = {
            normalize_city_name(str(item or "").strip())
            for item in (state.get("product_scan_completed_cities") or [])
            if str(item or "").strip()
        }
        required_goods = _manual_two_city_product_scan_required_goods(city)
        if not city or city in completed or not required_goods:
            _json_payload(
                "manual_two_city_business_product_scan_needed",
                {"ok": False, "city": city, "completed": sorted(completed), "required_goods": required_goods},
            )
            return False

        targets = _known_buy_goods_for_city(city)
        status_by_good = _manual_two_city_product_status_for_city(city)
        required_counts = {
            PRODUCT_STATUS_LOCKED: 0,
            PRODUCT_STATUS_MISSING: 0,
            PRODUCT_STATUS_NEVER_SCANNED: 0,
        }
        required_statuses = {}
        for good in required_goods:
            status = status_by_good.get(good, PRODUCT_STATUS_NEVER_SCANNED)
            required_statuses[good] = status
            if status in required_counts:
                required_counts[status] += 1
        state["product_scan_city"] = city
        state["product_scan_targets"] = targets
        state["product_scan_statuses"] = {}
        state["product_scan_pages"] = []
        state["product_scan_page_signatures"] = []
        state["product_scan_good_signatures"] = []
        state["product_scan_stop_reason"] = ""
        state["selected_buy_goods"] = []
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            (
                f"{city} 存在 {len(required_goods)} 个待复核交易品"
                f"（未解锁 {required_counts[PRODUCT_STATUS_LOCKED]}，"
                f"未出现 {required_counts[PRODUCT_STATUS_MISSING]}，"
                f"未扫描过 {required_counts[PRODUCT_STATUS_NEVER_SCANNED]}），"
                "进店后先扫描商品状态再重新计算。"
            ),
            run_id=str(state.get("run_id") or ""),
            level="warning",
            event="manual_two_city_product_scan_needed",
            data={
                "city": city,
                "required_goods": required_goods,
                "required_statuses": required_statuses,
                "required_counts": required_counts,
                "targets": targets,
                "leg": leg,
            },
        )
        _json_payload(
            "manual_two_city_business_product_scan_needed",
            {"ok": True, "city": city, "required_goods": required_goods, "targets": targets},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_product_scan_page")
class ManualTwoCityBusinessProductScanPageAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        page_index = _int_param(params, "page_index", 1, minimum=1)
        state = _manual_two_city_state()
        city = normalize_city_name(str(state.get("product_scan_city") or "").strip())
        targets = [str(item) for item in (state.get("product_scan_targets") or []) if str(item).strip()]
        entries = _ocr_entries(argv)
        texts = _ocr_texts(argv)
        visible = visible_product_unlock_status(entries, targets) or visible_product_unlock_status_from_texts(texts, targets)
        statuses = state.setdefault("product_scan_statuses", {})
        records: list[dict[str, Any]] = []
        for good, item in visible.items():
            status = PRODUCT_STATUS_LOCKED if item.get("locked") else PRODUCT_STATUS_NORMAL
            # 锁定状态优先，避免后续 OCR 把同一商品误覆盖成正常。
            if statuses.get(good) != PRODUCT_STATUS_LOCKED:
                statuses[good] = status
            records.append(
                {
                    "good": good,
                    "status": statuses.get(good),
                    "texts": item.get("texts") or [],
                    "center_y": item.get("center_y"),
                    "locked": bool(item.get("locked")),
                    "out_of_stock": bool(item.get("out_of_stock")),
                }
            )

        records.sort(key=lambda item: (float(item.get("center_y") or 0), str(item.get("good") or "")))
        page_updates = {
            str(item.get("good") or ""): _normalize_product_status(item.get("status"))
            for item in records
            if str(item.get("good") or "").strip() and item.get("status")
        }
        page_write_result: dict[str, Any] = {"changed": False, "reason": "no_visible_goods"}
        if city and page_updates:
            page_write_result = _manual_two_city_update_city_product_statuses(
                city,
                page_updates,
                reason=f"交易所买入页第 {page_index} 屏即时扫描",
            )
        good_signature = [
            f"{item.get('good')}:{item.get('status')}"
            for item in records
            if item.get("good") and item.get("status")
        ]
        good_signatures = state.setdefault("product_scan_good_signatures", [])
        good_signature_repeated = bool(good_signature and good_signatures and good_signatures[-1] == good_signature)
        if good_signature:
            good_signatures.append(good_signature)
            if len(good_signatures) > 24:
                del good_signatures[:-24]

        signature = trade_list_page_signature(entries) or trade_list_text_signature(texts)
        signatures = state.setdefault("product_scan_page_signatures", [])
        repeated = bool(signature and signatures and signatures[-1] == signature)
        if signature:
            signatures.append(signature)
            if len(signatures) > 24:
                del signatures[:-24]
        seen = set(statuses)
        all_seen = bool(targets and set(targets).issubset(seen))
        stop_reason = ""
        if all_seen:
            stop_reason = "all_targets_observed"
        elif good_signature_repeated:
            stop_reason = "same_goods_after_scroll"
        elif repeated:
            stop_reason = "same_page_after_scroll"
        elif page_index >= PRODUCT_SCAN_MAX_PAGES:
            stop_reason = "max_pages"
        state["product_scan_stop_reason"] = stop_reason
        state.setdefault("product_scan_pages", []).append(
            {
                "page_index": page_index,
                "records": records,
                "entry_count": len(entries),
                "signature_repeated": repeated,
                "good_signature": good_signature,
                "good_signature_repeated": good_signature_repeated,
                "stop_reason": stop_reason,
            }
        )
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            (
                f"{city} 商品状态扫描第 {page_index} 屏："
                f"看到 {len(records)} 个，累计 {len(seen)}/{len(targets)}。"
            ),
            run_id=str(state.get("run_id") or ""),
            event="manual_two_city_product_scan_page",
            data={
                "city": city,
                "page_index": page_index,
                "records": records,
                "seen": sorted(seen),
                "targets": targets,
                "good_signature": good_signature,
                "good_signature_repeated": good_signature_repeated,
                "stop_reason": stop_reason,
                "page_write_result": page_write_result,
            },
        )
        _json_payload(
            "manual_two_city_business_product_scan_page",
            {
                "ok": True,
                "city": city,
                "page_index": page_index,
                "records": records,
                "stop_reason": stop_reason,
                "page_write_result": page_write_result,
            },
        )
        return True


@AgentServer.custom_action("manual_two_city_business_product_scan_should_continue")
class ManualTwoCityBusinessProductScanShouldContinueAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        page_index = _int_param(params, "page_index", 1, minimum=1)
        state = _manual_two_city_state()
        stop_reason = str(state.get("product_scan_stop_reason") or "").strip()
        ok = not stop_reason and page_index < PRODUCT_SCAN_MAX_PAGES
        _json_payload(
            "manual_two_city_business_product_scan_should_continue",
            {"ok": ok, "page_index": page_index, "stop_reason": stop_reason},
        )
        return ok


@AgentServer.custom_action("manual_two_city_business_product_scan_complete")
class ManualTwoCityBusinessProductScanCompleteAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        city = normalize_city_name(str(state.get("product_scan_city") or "").strip())
        targets = [str(item) for item in (state.get("product_scan_targets") or []) if str(item).strip()]
        statuses = {
            str(good): _normalize_product_status(status)
            for good, status in (state.get("product_scan_statuses") or {}).items()
            if str(good).strip()
        }
        updates = {
            good: statuses.get(good, PRODUCT_STATUS_MISSING)
            for good in targets
        }
        result = _manual_two_city_update_city_product_statuses(
            city,
            updates,
            reason="交易所买入页预扫描",
        )
        completed = list(state.get("product_scan_completed_cities") or [])
        if city and city not in completed:
            completed.append(city)
        state["product_scan_completed_cities"] = completed
        missing = [good for good, status in updates.items() if status == PRODUCT_STATUS_MISSING]
        locked = [good for good, status in updates.items() if status == PRODUCT_STATUS_LOCKED]
        normal = [good for good, status in updates.items() if status == PRODUCT_STATUS_NORMAL]
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            (
                f"{city} 商品状态扫描完成：正常 {len(normal)}，"
                f"未解锁 {len(locked)}，未出现 {len(missing)}，准备重算。"
            ),
            run_id=str(state.get("run_id") or ""),
            level="warning" if locked or missing else "info",
            event="manual_two_city_product_scan_complete",
            data={
                "city": city,
                "normal": normal,
                "locked": locked,
                "missing": missing,
                "updates": updates,
                "write_result": result,
                "pages": state.get("product_scan_pages") or [],
                "stop_reason": state.get("product_scan_stop_reason") or "",
            },
        )
        ok = _manual_two_city_recalculate_after_product_scan(city)
        _json_payload(
            "manual_two_city_business_product_scan_complete",
            {"ok": ok, "city": city, "normal": normal, "locked": locked, "missing": missing},
        )
        return ok


@AgentServer.custom_action("manual_two_city_business_should_open_sell")
class ManualTwoCityBusinessShouldOpenSellAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        phase = str(state.get("trade_phase") or "buy").strip().lower()
        leg = _manual_two_city_active_leg()
        open_sell = phase == "sell"
        target = (960, 410) if open_sell else (960, 323)
        try:
            _manual_two_city_click(context, target, 0.2)
        except Exception as exc:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"交易所：点击{'卖出' if open_sell else '买入'}入口失败：{type(exc).__name__}: {exc}",
                level="warning",
                event="manual_two_city_trade_outlet_dispatch_failed",
                data={"phase": phase, "open_sell": open_sell, "leg": leg, "target": target},
            )
            _json_payload(
                "manual_two_city_business_should_open_sell",
                {"ok": False, "phase": phase, "open_sell": open_sell, "leg": leg, "target": target, "error": str(exc)},
            )
            return False
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"交易所：已打开菜单，点击进入{'卖出' if open_sell else '买入'}页。",
            event="manual_two_city_trade_outlet_ready",
            data={"phase": phase, "open_sell": open_sell, "leg": leg, "target": target},
        )
        _json_payload(
            "manual_two_city_business_should_open_sell",
            {"ok": True, "phase": phase, "open_sell": open_sell, "leg": leg, "target": target},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_should_drink")
class ManualTwoCityBusinessShouldDrinkAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        state = _manual_two_city_state()
        phase = str(params.get("phase") or state.get("trade_phase") or "buy").strip().lower()
        threshold = _int_param(state, "drink_fatigue_threshold", 300, minimum=0)
        leg = _manual_two_city_active_leg()
        status = strength_status_from_texts(_ocr_texts(argv))
        if not _manual_two_city_bool(state.get("auto_drink"), False):
            _json_payload("manual_two_city_business_should_drink", {"ok": False, "reason": "disabled", "phase": phase})
            return False
        if state.get("drink_unavailable"):
            _json_payload("manual_two_city_business_should_drink", {"ok": False, "reason": "drink_unavailable", "phase": phase})
            return False
        if state.pop("skip_next_drink_check", False):
            _json_payload("manual_two_city_business_should_drink", {"ok": False, "reason": "skip_once", "phase": phase})
            return False
        drink_city = _manual_two_city_drink_city(state, phase, leg)
        allowed_cities = _manual_two_city_drink_allowed_cities()
        if drink_city not in allowed_cities:
            skip_key = f"{phase}:{drink_city or '-'}"
            logged = state.setdefault("drink_city_skip_logged", {})
            if isinstance(logged, dict) and not logged.get(skip_key):
                logged[skip_key] = True
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    f"跑商喝酒预检：当前城市 {drink_city or '未识别'} 不是可喝酒的主声望城市，跳过喝酒。",
                    event="manual_two_city_drink_city_not_allowed",
                    data={
                        "phase": phase,
                        "city": drink_city,
                        "leg": leg,
                        "allowed_cities": sorted(allowed_cities),
                    },
                )
            _json_payload(
                "manual_two_city_business_should_drink",
                {
                    "ok": False,
                    "reason": "city_not_allowed",
                    "phase": phase,
                    "city": drink_city,
                    "allowed_cities": sorted(allowed_cities),
                },
            )
            return False
        if not status:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                "跑商喝酒预检：未识别到交易页疲劳值，本次不喝酒并继续流程。",
                level="warning",
                event="manual_two_city_drink_precheck_no_status",
                data={"phase": phase, "leg": leg, "texts": _ocr_texts(argv)[:20]},
            )
            _json_payload("manual_two_city_business_should_drink", {"ok": False, "reason": "no_status", "phase": phase})
            return False
        current = int(status.get("current") or 0)
        if current <= threshold:
            _json_payload(
                "manual_two_city_business_should_drink",
                {"ok": False, "reason": "below_threshold", "phase": phase, "status": status, "threshold": threshold},
            )
            return False
        state["drink_resume_phase"] = phase
        state["trade_phase"] = phase
        state["drink_last_status"] = status
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"跑商喝酒预检：当前疲劳 {current}/{status.get('total')} > {threshold}，准备进入疲劳页并按本轮成功喝酒次数控制循环。",
            event="manual_two_city_drink_precheck_needed",
            data={"phase": phase, "status": status, "threshold": threshold, "leg": leg},
        )
        _json_payload(
            "manual_two_city_business_should_drink",
            {"ok": True, "phase": phase, "status": status, "threshold": threshold, "leg": leg},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_tap_drink_info")
class ManualTwoCityBusinessTapDrinkInfoAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        hit, entries, texts = _manual_two_city_ocr_entries(
            context,
            "ManualTwoCityDrinkInfoAnchor",
            FATIGUE_DRINK_INFO_ANCHOR_TEXTS,
            roi=[980, 120, 290, 520],
        )
        target = _manual_two_city_drink_info_target_from_entries(entries)
        if target is None:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                "跑商喝酒：未识别到休息区次数提示入口，本次跳过喝酒。",
                level="warning",
                event="manual_two_city_drink_info_anchor_missing",
                data={"hit": hit, "texts": texts[:30], "entries": entries[:10]},
            )
            _json_payload(
                "manual_two_city_business_tap_drink_info",
                {"ok": False, "reason": "anchor_missing", "hit": hit, "texts": texts[:30]},
            )
            return False
        _manual_two_city_click(context, target, 0.6)
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "跑商喝酒：已识别休息区次数提示入口并点击。",
            event="manual_two_city_drink_info_tapped",
            data={"target": target, "texts": texts[:30], "entries": entries[:10]},
        )
        _json_payload(
            "manual_two_city_business_tap_drink_info",
            {"ok": True, "target": target, "hit": hit, "texts": texts[:30]},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_drink_info_ready")
class ManualTwoCityBusinessDrinkInfoReadyAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        texts = _ocr_texts(argv)
        remaining = _manual_two_city_drink_remaining_from_texts(texts)
        if remaining:
            state["drink_info_observed"] = remaining
            remain_count = _fatigue_int(remaining.get("remaining"), 0)
            if remain_count <= 0:
                state["drink_unavailable"] = True
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    "跑商喝酒：次数提示显示剩余 0 次，本轮跳过喝酒。",
                    level="warning",
                    event="manual_two_city_drink_remaining_empty",
                    data={"remaining": remaining},
                )
                _json_payload("manual_two_city_business_drink_info_ready", {"ok": False, "remaining": remaining, "texts": texts[:30]})
                return False
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                (
                    f"跑商喝酒：观察到次数提示 {remaining.get('remaining')}/{remaining.get('total')}，"
                    "继续进入休息区喝酒流程。"
                ),
                event="manual_two_city_drink_remaining_ready",
                data={"remaining": remaining},
            )
        else:
            state.pop("drink_info_observed", None)
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                "跑商喝酒：未读到次数提示，本次不进入喝酒界面。",
                level="warning",
                event="manual_two_city_drink_remaining_unknown",
                data={"texts": texts[:30]},
            )
            _json_payload("manual_two_city_business_drink_info_ready", {"ok": False, "remaining": remaining, "texts": texts[:30]})
            return False
        _json_payload("manual_two_city_business_drink_info_ready", {"ok": True, "remaining": remaining, "texts": texts[:30]})
        return True


@AgentServer.custom_action("manual_two_city_business_drink_until_cost")
class ManualTwoCityBusinessDrinkUntilCostAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        state = _manual_two_city_state()
        configured_max = max(1, min(FATIGUE_DRINK_MAX_ATTEMPTS, _fatigue_int(params.get("max_attempts"), FATIGUE_DRINK_MAX_ATTEMPTS)))
        already_used = max(0, _fatigue_int(state.get("drink_used_count"), 0))
        remaining_round_attempts = max(0, FATIGUE_DRINK_MAX_ATTEMPTS - already_used)
        if remaining_round_attempts <= 0:
            state["drink_unavailable"] = True
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"跑商喝酒：本轮已成功喝酒 {already_used} 杯，达到本轮上限 {FATIGUE_DRINK_MAX_ATTEMPTS} 杯，后续不再尝试喝酒。",
                level="warning",
                event="manual_two_city_drink_round_limit_reached",
                data={"used_total": already_used, "round_limit": FATIGUE_DRINK_MAX_ATTEMPTS},
            )
            _json_payload(
                "manual_two_city_business_drink_until_cost",
                {"ok": False, "drank_count": 0, "reason": "round_limit_reached", "used_total": already_used},
            )
            return False
        max_attempts = min(configured_max, remaining_round_attempts)
        drink_state = {"used": {}, "unavailable": {}}
        drank_count = _run_fatigue_drink_until_cost(
            context,
            state=drink_state,
            task_entry=MANUAL_TWO_CITY_TASK_ENTRY,
            max_attempts=max_attempts,
        )
        if drink_state.get("unavailable", {}).get("喝酒"):
            state["drink_unavailable"] = True
        stop_reason = str(drink_state.get("stop_reason") or "").strip()
        if drank_count > 0:
            state["drink_used_count"] = int(state.get("drink_used_count") or 0) + drank_count
            state["skip_next_drink_check"] = True
            if drank_count < max_attempts and stop_reason not in {"cost_confirm", "unavailable"}:
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    f"跑商喝酒：本轮本次最多尝试 {max_attempts} 杯，实际完成 {drank_count} 杯，停止原因 {stop_reason or '-'}。",
                    level="warning",
                    event="manual_two_city_drink_partial",
                    data={
                        "drank_count": drank_count,
                        "max_attempts": max_attempts,
                        "configured_max": configured_max,
                        "already_used": already_used,
                        "round_limit": FATIGUE_DRINK_MAX_ATTEMPTS,
                        "stop_reason": stop_reason,
                    },
                )
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"跑商喝酒：本次完成 {drank_count} 杯，准备返回城市界面重新进入交易所续跑。",
                event="manual_two_city_drink_done",
                data={
                    "drank_count": drank_count,
                    "phase": state.get("drink_resume_phase"),
                    "used_total": state.get("drink_used_count"),
                    "max_attempts": max_attempts,
                    "already_used_before": already_used,
                    "round_limit": FATIGUE_DRINK_MAX_ATTEMPTS,
                    "stop_reason": stop_reason,
                },
            )
            _json_payload("manual_two_city_business_drink_until_cost", {"ok": True, "drank_count": drank_count})
            return True
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "跑商喝酒：未成功喝酒，本轮将不再尝试喝酒并返回交易页继续流程。",
            level="warning",
            event="manual_two_city_drink_not_used",
            data={"phase": state.get("drink_resume_phase"), "unavailable": drink_state.get("unavailable")},
        )
        state["drink_unavailable"] = True
        _json_payload("manual_two_city_business_drink_until_cost", {"ok": False, "drank_count": 0, "unavailable": drink_state.get("unavailable")})
        return False


@AgentServer.custom_action("manual_two_city_business_after_drink_return_city")
class ManualTwoCityBusinessAfterDrinkReturnCityAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        phase = str(state.get("drink_resume_phase") or state.get("trade_phase") or "buy").strip().lower()
        state["trade_phase"] = "sell" if phase == "sell" else "buy"
        state["skip_next_drink_check"] = True
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "跑商喝酒：已离开喝酒界面，准备确认当前在主界面还是城市界面，并继续原买卖步骤。",
            event="manual_two_city_after_drink_return_city",
            data={"phase": state.get("trade_phase"), "leg": _manual_two_city_active_leg()},
        )
        _json_payload("manual_two_city_business_after_drink_return_city", {"ok": True, "phase": state.get("trade_phase")})
        return True


@AgentServer.custom_action("manual_two_city_business_drink_skipped")
class ManualTwoCityBusinessDrinkSkippedAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        phase = str(state.get("drink_resume_phase") or state.get("trade_phase") or "buy").strip().lower()
        state["trade_phase"] = "sell" if phase == "sell" else "buy"
        state["drink_unavailable"] = True
        state["skip_next_drink_check"] = True
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "跑商喝酒：本轮不可喝酒，已通过左上角返回交易所，继续原流程。",
            level="warning",
            event="manual_two_city_drink_skipped",
            data={"phase": state.get("trade_phase"), "leg": _manual_two_city_active_leg()},
        )
        _json_payload("manual_two_city_business_drink_skipped", {"ok": True, "phase": state.get("trade_phase")})
        return True


def _manual_two_city_mark_strength_stop(
    state: dict[str, Any],
    *,
    phase: str,
    status: dict[str, int] | None,
    required: int,
    reason: str,
    leg: dict[str, Any] | None = None,
) -> None:
    remaining = int(status.get("remaining") or 0) if isinstance(status, dict) else 0
    until_fatigue = _manual_two_city_until_fatigue_exhausted(state)
    state["strength_recovery_stop_pending"] = True
    state["strength_recovery_stop_reason"] = reason
    state["strength_recovery_stop_status"] = status
    state["strength_recovery_stop_required"] = required
    state["strength_recovery_stop_phase"] = phase
    if until_fatigue:
        state["strength_recovery_stop_terminal_status"] = MANUAL_TWO_CITY_TERMINAL_FATIGUE_EXHAUSTED
        state["strength_recovery_stop_terminal_reason"] = "恢复手段已不可用且剩余疲劳不足下一段安全需求"
        level = "warning"
        message = (
            f"跑到疲劳耗尽：剩余疲劳 {remaining} 低于安全需求 {required}，"
            "且恢复手段已不可用，停止继续买入。"
        )
        event = "manual_two_city_strength_recovery_exhausted_stop_ready"
    else:
        state["strength_recovery_stop_terminal_status"] = MANUAL_TWO_CITY_TERMINAL_FAILED
        state["strength_recovery_stop_terminal_reason"] = "跑 1 轮模式下剩余疲劳不足下一段安全需求且恢复手段不可用"
        level = "error"
        message = (
            f"跑 1 轮失败：剩余疲劳 {remaining} 低于安全需求 {required}，"
            "且恢复手段不可用，已阻止本次买入/抬砍。"
        )
        event = "manual_two_city_strength_recovery_unavailable_fail_ready"
    _append_user_log(
        _manual_two_city_current_task_entry(state),
        message,
        level=level,
        event=event,
        data={
            "phase": phase,
            "status": status,
            "required": required,
            "reason": reason,
            "leg": leg,
            "recovery": _manual_two_city_strength_recovery_state(state),
        },
    )


@AgentServer.custom_action("manual_two_city_business_should_recover_strength")
class ManualTwoCityBusinessShouldRecoverStrengthAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        state = _manual_two_city_state()
        phase = str(params.get("phase") or state.get("trade_phase") or "buy").strip().lower()
        pre_buy_cleanup = bool(state.get("pre_buy_cleanup"))
        state["strength_recovery_stop_pending"] = False
        required_phase = "buy" if phase == "sell" and pre_buy_cleanup else phase
        required = _manual_two_city_required_fatigue_for_strength_check(state, phase=phase)
        texts = _ocr_texts(argv)
        status = strength_status_from_texts(texts)
        if not status:
            status, texts = _manual_two_city_read_strength_status_with_retry(
                context,
                f"ManualTwoCity{phase.capitalize()}StrengthRecoveryCheck",
            )
        leg = _manual_two_city_active_leg()
        if required <= 0:
            _json_payload(
                "manual_two_city_business_should_recover_strength",
                {"ok": False, "reason": "no_required_fatigue", "phase": phase, "status": status},
            )
            return False
        if not status:
            state["strength_recovery_stop_pending"] = True
            state["strength_recovery_stop_reason"] = "strength_status_unknown"
            state["strength_recovery_stop_status"] = None
            state["strength_recovery_stop_required"] = required
            state["strength_recovery_stop_phase"] = phase
            state["strength_recovery_stop_terminal_status"] = MANUAL_TWO_CITY_TERMINAL_FAILED
            state["strength_recovery_stop_terminal_reason"] = "交易所页未能识别疲劳值，已停止继续买入/卖出/抬砍"
            _append_user_log(
                _manual_two_city_current_task_entry(state),
                "跑商补疲劳预检：交易所页连续未识别到疲劳值，已阻止继续买入/卖出/抬砍。",
                level="error",
                event="manual_two_city_strength_precheck_status_unknown_stop",
                data={"phase": phase, "required": required, "leg": leg, "texts": texts[:20]},
            )
            _json_payload(
                "manual_two_city_business_should_recover_strength",
                {"ok": True, "reason": "strength_status_unknown_stop", "phase": phase, "required": required},
            )
            return True
        remaining = int(status.get("remaining") or 0)
        if remaining >= required:
            state["strength_recovery_unavailable"] = False
            state["strength_recovery_unavailable_logged"] = False
            state.pop("strength_recovery_required", None)
            _json_payload(
                "manual_two_city_business_should_recover_strength",
                {"ok": False, "reason": "enough", "phase": phase, "status": status, "required": required},
            )
            return False
        if phase == "sell" and not pre_buy_cleanup:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                (
                    f"卖出页疲劳预检：剩余疲劳 {remaining} 低于下一段安全需求 {required}，"
                    "先卖出当前货物，卖完后再决定恢复或结束。"
                ),
                level="warning",
                event="manual_two_city_strength_sell_first",
                data={"phase": phase, "status": status, "required": required, "leg": leg},
            )
            _json_payload(
                "manual_two_city_business_should_recover_strength",
                {"ok": False, "reason": "sell_goods_first", "phase": phase, "status": status, "required": required},
            )
            return False
        if phase == "sell" and pre_buy_cleanup:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                (
                    f"买入前清仓疲劳预检：剩余疲劳 {remaining} 低于当前单程安全需求 {required}，"
                    "先恢复疲劳，避免清仓抬价时弹出疲劳不足。"
                ),
                level="warning",
                event="manual_two_city_pre_buy_cleanup_strength_needed",
                data={"phase": phase, "required_phase": required_phase, "status": status, "required": required, "leg": leg},
            )
        if state.get("strength_recovery_unavailable"):
            _manual_two_city_mark_strength_stop(
                state,
                phase=phase,
                status=status,
                required=required,
                reason="recovery_unavailable",
                leg=leg,
            )
            _json_payload(
                "manual_two_city_business_should_recover_strength",
                {"ok": True, "reason": "stop_recovery_unavailable", "phase": phase, "status": status, "required": required},
            )
            return True

        methods = _manual_two_city_strength_recovery_methods(state)
        if not methods:
            state["strength_recovery_unavailable"] = True
            state["strength_recovery_unavailable_logged"] = True
            _manual_two_city_mark_strength_stop(
                state,
                phase=phase,
                status=status,
                required=required,
                reason="recovery_disabled",
                leg=leg,
            )
            _json_payload(
                "manual_two_city_business_should_recover_strength",
                {"ok": True, "reason": "stop_recovery_disabled", "phase": phase, "status": status, "required": required},
            )
            return True

        state["strength_recovery_phase"] = "sell" if phase == "sell" else "buy"
        state["trade_phase"] = state["strength_recovery_phase"]
        state["strength_recovery_required"] = required
        state["strength_recovery_last_status"] = status
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            (
                f"跑商补疲劳预检：剩余疲劳 {remaining} < 安全需求 {required}，"
                f"准备按顺序使用{'、'.join(methods)}。"
            ),
            event="manual_two_city_strength_precheck_needed",
            data={"phase": phase, "status": status, "required": required, "leg": leg, "methods": methods},
        )
        _json_payload(
            "manual_two_city_business_should_recover_strength",
            {"ok": True, "phase": phase, "status": status, "required": required, "leg": leg},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_stop_if_fatigue_exhausted")
class ManualTwoCityBusinessStopIfFatigueExhaustedAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        if not state.get("strength_recovery_stop_pending"):
            _json_payload("manual_two_city_business_stop_if_fatigue_exhausted", {"ok": False, "reason": "not_pending"})
            return False
        state["strength_recovery_stop_pending"] = False
        state["trade_phase"] = "done"
        terminal_status = str(
            state.get("strength_recovery_stop_terminal_status") or MANUAL_TWO_CITY_TERMINAL_FATIGUE_EXHAUSTED
        ).strip()
        if terminal_status not in {MANUAL_TWO_CITY_TERMINAL_FATIGUE_EXHAUSTED, MANUAL_TWO_CITY_TERMINAL_FAILED}:
            terminal_status = MANUAL_TWO_CITY_TERMINAL_FATIGUE_EXHAUSTED
        state["terminal_status"] = terminal_status
        state["terminal_reason"] = str(
            state.get("strength_recovery_stop_terminal_reason")
            or "恢复手段已不可用且剩余疲劳不足下一段安全需求"
        ).strip()
        status = state.get("strength_recovery_stop_status")
        required = _fatigue_int(state.get("strength_recovery_stop_required"), 0)
        phase = str(state.get("strength_recovery_stop_phase") or state.get("trade_phase") or "").strip()
        reason = str(state.get("strength_recovery_stop_reason") or "").strip()
        recovery = _manual_two_city_strength_recovery_state(state)
        if isinstance(status, dict):
            status_text = f"当前疲劳 {status.get('current')}/{status.get('total')}，剩余 {status.get('remaining')}"
        else:
            status_text = "当前疲劳未识别"
        is_fatigue_exhausted = terminal_status == MANUAL_TWO_CITY_TERMINAL_FATIGUE_EXHAUSTED
        if reason == "strength_status_unknown":
            message = f"跑商失败：交易所页未能识别疲劳值，安全需求 {required}，已停止继续买入/卖出/抬砍。"
        elif is_fatigue_exhausted:
            message = f"跑到疲劳耗尽：{status_text}，安全需求 {required}，恢复手段已不可用，结束跑商。"
        else:
            message = f"跑商失败：{status_text}，安全需求 {required}，恢复手段不可用，已停止继续买入。"
        _append_user_log(
            _manual_two_city_current_task_entry(state),
            message,
            level="warning" if is_fatigue_exhausted else "error",
            event="manual_two_city_fatigue_exhausted_stop" if is_fatigue_exhausted else "manual_two_city_strength_stop_failed",
            data={
                "phase": phase,
                "reason": reason,
                "status": status,
                "required": required,
                "recovery": recovery,
                "completed_rounds": state.get("completed_rounds"),
                "active_leg_index": state.get("active_leg_index"),
                "leg": _manual_two_city_active_leg(),
                "terminal_status": terminal_status,
                "terminal_reason": state.get("terminal_reason"),
            },
        )
        _json_payload(
            "manual_two_city_business_stop_if_fatigue_exhausted",
            {
                "ok": True,
                "phase": phase,
                "reason": reason,
                "status": status,
                "required": required,
                "terminal_status": terminal_status,
                "terminal_reason": state.get("terminal_reason"),
            },
        )
        return True


@AgentServer.custom_action("manual_two_city_business_recover_strength_once")
class ManualTwoCityBusinessRecoverStrengthOnceAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        state = _manual_two_city_state()
        phase = str(params.get("phase") or state.get("strength_recovery_phase") or state.get("trade_phase") or "buy").strip().lower()
        phase = "sell" if phase == "sell" else "buy"
        state["trade_phase"] = phase
        required = _manual_two_city_required_fatigue_for_strength_check(state, phase=phase)
        recovery = _manual_two_city_strength_recovery_state(state)
        status = state.get("strength_recovery_last_status")
        status = dict(status) if isinstance(status, dict) else None
        status_texts: list[str] = []
        if required <= 0:
            _json_payload(
                "manual_two_city_business_recover_strength_once",
                {"ok": False, "reason": "no_required_fatigue", "phase": phase, "status": status},
            )
            return False
        if _manual_two_city_strength_enough(status, required):
            state.pop("strength_recovery_required", None)
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"跑商补疲劳：交易页预检剩余 {status['remaining']}，已满足需求 {required}，返回交易页。",
                event="manual_two_city_strength_recovery_precheck_already_enough",
                data={"phase": phase, "status": status, "required": required},
            )
            _manual_two_city_click(context, RECOVERY_PAGE_BACK_TARGET, 0.9)
            state["skip_next_drink_check"] = True
            return True

        bento_result = _manual_two_city_try_bento_recovery(context, state, required=required, phase=phase)
        if bento_result.get("return_trade"):
            state["strength_recovery_last_resource"] = "便当"
            _json_payload(
                "manual_two_city_business_recover_strength_once",
                {"ok": True, "phase": phase, "required": required, "result": bento_result},
            )
            return True
        if isinstance(bento_result.get("status"), dict):
            status = bento_result.get("status")
            status_texts = []

        if not _manual_two_city_probe_medicine_actual_budget(
            context,
            state,
            status=status,
            required=required,
            phase=phase,
        ):
            _manual_two_city_click(context, RECOVERY_PAGE_BACK_TARGET, 0.9)
            state["skip_next_drink_check"] = True
            _json_payload(
                "manual_two_city_business_recover_strength_once",
                {
                    "ok": True,
                    "phase": phase,
                    "required": required,
                    "status": status,
                    "reason": "recovery_budget_insufficient",
                    "stop_pending": bool(state.get("strength_recovery_stop_pending")),
                    "used": dict(recovery.get("used") or {}),
                    "unavailable": dict(recovery.get("unavailable") or {}),
                },
            )
            return True

        for resource in FATIGUE_MEDICINE_RESOURCES:
            result = _manual_two_city_try_medicine_recovery(
                context,
                state,
                resource,
                required=required,
                status=status,
                phase=phase,
            )
            if result.get("used"):
                state["strength_recovery_last_resource"] = resource
                _json_payload(
                    "manual_two_city_business_recover_strength_once",
                    {"ok": True, "phase": phase, "required": required, "result": result},
                )
                return True

        huashi_result = _manual_two_city_try_huashi_recovery(context, state, phase=phase)
        if huashi_result.get("used"):
            state["strength_recovery_last_resource"] = "桦石"
            _json_payload(
                "manual_two_city_business_recover_strength_once",
                {"ok": True, "phase": phase, "required": required, "result": huashi_result},
            )
            return True

        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            (
                f"跑商补疲劳：当前剩余疲劳不足安全需求 {required}，"
                "但便当、体力药和桦石都未能使用，将返回交易页重新预检；若仍不足则停止买入。"
            ),
            level="warning",
            event="manual_two_city_strength_recovery_unavailable",
            data={
                "phase": phase,
                "required": required,
                "status": status,
                "texts": status_texts[:20],
                "used": dict(recovery.get("used") or {}),
                "unavailable": dict(recovery.get("unavailable") or {}),
            },
        )
        state["strength_recovery_unavailable"] = True
        _json_payload(
            "manual_two_city_business_recover_strength_once",
            {
                "ok": False,
                "phase": phase,
                "required": required,
                "status": status,
                "used": dict(recovery.get("used") or {}),
                "unavailable": dict(recovery.get("unavailable") or {}),
            },
        )
        return False


@AgentServer.custom_action("manual_two_city_business_after_strength_recovery")
class ManualTwoCityBusinessAfterStrengthRecoveryAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        phase = str(state.get("strength_recovery_phase") or state.get("trade_phase") or "buy").strip().lower()
        state["trade_phase"] = "sell" if phase == "sell" else "buy"
        state["skip_next_drink_check"] = True
        if state.get("strength_recovery_stop_pending"):
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                "跑商补疲劳：恢复资源不足，转入停止流程，不再继续原买卖流程。",
                level="warning",
                event="manual_two_city_after_strength_recovery_stop_pending",
                data={"phase": state.get("trade_phase"), "leg": _manual_two_city_active_leg()},
            )
            _json_payload(
                "manual_two_city_business_after_strength_recovery",
                {"ok": True, "phase": state.get("trade_phase"), "stop_pending": True},
            )
            return True
        resource = str(state.get("strength_recovery_last_resource") or "恢复资源")
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"跑商补疲劳：{resource} 使用流程结束，返回交易页后重新读取疲劳。",
            event="manual_two_city_after_strength_recovery",
            data={"phase": state.get("trade_phase"), "resource": resource, "leg": _manual_two_city_active_leg()},
        )
        _json_payload("manual_two_city_business_after_strength_recovery", {"ok": True, "phase": state.get("trade_phase"), "resource": resource})
        return True


@AgentServer.custom_action("manual_two_city_business_strength_recovery_resume")
class ManualTwoCityBusinessStrengthRecoveryResumeAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        phase = str(state.get("strength_recovery_phase") or state.get("trade_phase") or "buy").strip().lower()
        state["trade_phase"] = "sell" if phase == "sell" else "buy"
        state["skip_next_drink_check"] = True
        if state.get("strength_recovery_stop_pending"):
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                "跑商补疲劳：检测到终止标记，转入停止流程，不再继续原买卖流程。",
                level="warning",
                event="manual_two_city_strength_recovery_resume_stop_pending",
                data={"phase": state.get("trade_phase"), "leg": _manual_two_city_active_leg()},
            )
            _json_payload(
                "manual_two_city_business_strength_recovery_resume",
                {"ok": True, "phase": state.get("trade_phase"), "stop_pending": True},
            )
            return True
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "跑商补疲劳：准备确认交易页并继续原买卖流程。",
            level="warning",
            event="manual_two_city_strength_recovery_resume",
            data={"phase": state.get("trade_phase"), "leg": _manual_two_city_active_leg()},
        )
        _json_payload("manual_two_city_business_strength_recovery_resume", {"ok": True, "phase": state.get("trade_phase")})
        return True


@AgentServer.custom_action("manual_two_city_business_select_buy_goods")
class ManualTwoCityBusinessSelectBuyGoodsAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        page_index = _int_param(params, "page_index", 1, minimum=1)
        state = _manual_two_city_state()
        entries = _ocr_entries(argv)
        leg = _manual_two_city_set_active_leg_by_visible_goods(entries)
        buy_city = str(leg.get("buy_city") or "").strip()
        planned_goods = [str(item) for item in (leg.get("goods") or []) if str(item).strip()]
        locked_config_goods = _manual_two_city_configured_locked_goods(buy_city)
        scan_targets = list(dict.fromkeys(planned_goods))
        selected = {
            str(item)
            for item in (state.get("selected_buy_goods") or [])
            if str(item).strip()
        }
        if page_index <= 1:
            state["buy_selection_locked_goods"] = []
        cumulative_locked = {
            str(item)
            for item in (state.get("buy_selection_locked_goods") or [])
            if str(item).strip()
        }
        clicked: list[str] = []
        locked: list[str] = []
        restored: list[str] = []
        for entry in sorted(entries, key=lambda item: (float(item.get("center_y") or 0), float(item.get("center_x") or 0))):
            good = match_trade_good(entry.get("text"), scan_targets)
            if not good:
                continue
            is_planned = good in planned_goods
            if is_planned and good in selected:
                continue
            if not is_planned:
                continue
            x = int(float(entry.get("center_x") or 0))
            y = int(float(entry.get("center_y") or 0))
            if not (450 <= x <= 980 and 90 <= y <= 710):
                continue
            row_texts = trade_good_row_texts(entries, float(entry.get("center_y") or 0))
            row_locked = any(
                any(keyword in clean_text(text) for keyword in TRADE_PRODUCT_LOCK_TEXTS)
                for text in row_texts
            )
            try:
                if row_locked:
                    locked.append(good)
                    cumulative_locked.add(good)
                    transient_status = state.setdefault("transient_product_status_by_city", {})
                    if isinstance(transient_status, dict):
                        city_status = transient_status.setdefault(buy_city, {})
                        if isinstance(city_status, dict):
                            city_status[good] = PRODUCT_STATUS_LOCKED
                    _append_user_log(
                        MANUAL_TWO_CITY_TASK_ENTRY,
                        (
                            f"买入页计划商品本行显示未解锁：{buy_city}/{good}，"
                            "本轮先跳过，不写入账号配置，等待交易所扫描复核。"
                        ),
                        level="warning",
                        event="manual_two_city_buy_good_row_locked_transient",
                        data={"city": buy_city, "good": good, "texts": row_texts[:20]},
                    )
                    continue
                context.tasker.controller.post_click(x, y).wait()
                time.sleep(0.25)
                is_locked, lock_texts = _manual_two_city_product_locked_after_click(
                    context,
                    f"ManualTwoCityProductLockCheck{page_index:03d}_{len(clicked) + len(locked) + len(restored) + 1:03d}",
                    center_y=y,
                )
                if is_locked:
                    locked.append(good)
                    cumulative_locked.add(good)
                    transient_status = state.setdefault("transient_product_status_by_city", {})
                    if isinstance(transient_status, dict):
                        city_status = transient_status.setdefault(buy_city, {})
                        if isinstance(city_status, dict):
                            city_status[good] = PRODUCT_STATUS_LOCKED
                    _append_user_log(
                        MANUAL_TWO_CITY_TASK_ENTRY,
                        (
                            f"买入页点击计划商品后当前行仍显示未解锁：{buy_city}/{good}，"
                            "本轮先跳过，不写入账号配置，等待交易所扫描复核。"
                        ),
                        level="warning",
                        event="manual_two_city_buy_good_click_locked_transient",
                        data={"city": buy_city, "good": good, "texts": lock_texts[:20]},
                    )
                    _manual_two_city_close_product_detail_if_needed(context)
                    continue

                _manual_two_city_update_product_status(
                    buy_city,
                    good,
                    PRODUCT_STATUS_NORMAL,
                    reason="交易所买入页扫描发现商品可点击",
                )
                if is_planned:
                    selected.add(good)
                    clicked.append(good)
            except Exception as exc:
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    f"点击计划商品失败：{good} ({type(exc).__name__}: {exc})",
                    level="warning",
                    event="manual_two_city_buy_good_click_failed",
                    data={"good": good, "entry": entry},
                )

        state["selected_buy_goods"] = list(selected)
        state["buy_selection_locked_goods"] = sorted(cumulative_locked)
        missing = [good for good in planned_goods if good not in selected and good not in cumulative_locked]
        needs_replan = bool((missing or cumulative_locked) and page_index >= 4)
        if needs_replan:
            for good in missing:
                _manual_two_city_update_product_status(
                    buy_city,
                    good,
                    PRODUCT_STATUS_MISSING,
                    reason="交易所买入页 4 屏扫描未找到计划商品",
                )
            _manual_two_city_mark_buy_selection_replan_needed(
                state,
                city=buy_city,
                missing=missing,
                locked=sorted(cumulative_locked),
            )
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            (
                f"买入页第 {page_index} 屏：命中 {len(clicked)} 个，"
                f"已选 {len(selected)}/{len(planned_goods)}，"
                f"本页未解锁 {len(locked)} 个，累计未解锁 {len(cumulative_locked)} 个，"
                f"恢复 {len(restored)} 个"
            ),
            event="manual_two_city_buy_goods_page",
            data={
                "page_index": page_index,
                "buy_city": buy_city,
                "sell_city": leg.get("sell_city"),
                "planned_goods": planned_goods,
                "locked_config_goods": locked_config_goods,
                "clicked": clicked,
                "locked": locked,
                "cumulative_locked": sorted(cumulative_locked),
                "restored": restored,
                "selected": list(selected),
                "missing": missing,
                "needs_replan": needs_replan,
            },
        )
        _json_payload(
            "manual_two_city_business_select_buy_goods",
            {
                "ok": set(planned_goods).issubset(selected),
                "clicked": clicked,
                "locked": locked,
                "cumulative_locked": sorted(cumulative_locked),
                "restored": restored,
                "selected": list(selected),
                "missing": missing,
                "needs_replan": needs_replan,
            },
        )
        return set(planned_goods).issubset(selected)


@AgentServer.custom_action("manual_two_city_business_buy_goods_missing")
class ManualTwoCityBusinessBuyGoodsMissingAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        city = normalize_city_name(str(state.get("buy_selection_replan_city") or "").strip())
        missing = [str(item) for item in (state.get("buy_selection_replan_missing") or []) if str(item).strip()]
        locked = [str(item) for item in (state.get("buy_selection_replan_locked") or []) if str(item).strip()]
        retry_count = int(state.get("buy_selection_replan_retry_count") or 0)
        if not state.get("buy_selection_replan_pending") or not city or retry_count >= 2:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                "计划商品未找齐：买入页 4 屏内没有找齐计划商品，已停止，避免误买。",
                event="manual_two_city_business_buy_goods_missing_stop",
                data={
                    "city": city,
                    "missing": missing,
                    "locked": locked,
                    "retry_count": retry_count,
                    "selected": state.get("selected_buy_goods") or [],
                },
            )
            _json_payload(
                "manual_two_city_business_buy_goods_missing",
                {"ok": False, "reason": "stop", "city": city, "missing": missing, "locked": locked, "retry_count": retry_count},
            )
            return False

        selected = [str(item) for item in (state.get("selected_buy_goods") or []) if str(item).strip()]
        if selected:
            clicked, texts = _manual_two_city_click_ocr_text(
                context,
                "ManualTwoCityBuyGoodsMissingClearSelection",
                ["全部取消"],
                roi=BUY_CART_SELECTED_ROI,
                delay=0.8,
            )
            if not clicked:
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    "计划商品未找齐：需要重算，但未能点击全部取消清空已选商品，已停止以避免误买。",
                    level="error",
                    event="manual_two_city_buy_goods_missing_clear_selection_failed",
                    data={"city": city, "missing": missing, "locked": locked, "selected": selected, "texts": texts[:20]},
                )
                _json_payload(
                    "manual_two_city_business_buy_goods_missing",
                    {"ok": False, "reason": "clear_selection_failed", "city": city, "selected": selected},
                )
                return False

        retry_counts = state.setdefault("buy_selection_replan_retry_counts", {})
        if isinstance(retry_counts, dict):
            retry_counts[city] = retry_count + 1
        state["selected_buy_goods"] = []
        state["buy_selection_replan_pending"] = False
        ok = _manual_two_city_recalculate_after_product_scan(city)
        if not ok:
            _json_payload(
                "manual_two_city_business_buy_goods_missing",
                {"ok": False, "reason": "recalculate_failed", "city": city, "missing": missing, "locked": locked},
            )
            return False
        new_leg = _manual_two_city_active_leg()
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            (
                f"{city} 计划商品发生变化：已清空选择并重算，"
                f"准备按新计划重新选择商品。"
            ),
            level="warning",
            event="manual_two_city_buy_goods_missing_replanned",
            data={
                "city": city,
                "missing": missing,
                "locked": locked,
                "retry_count": retry_count + 1,
                "new_leg": new_leg,
            },
        )
        _json_payload(
            "manual_two_city_business_buy_goods_missing",
            {"ok": True, "city": city, "retry_count": retry_count + 1, "new_leg": new_leg},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_buy_report_ready")
class ManualTwoCityBusinessBuyReportReadyAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        leg = _manual_two_city_active_leg()
        if state.get("initial_transfer_pending"):
            source = str(state.get("initial_transfer_source_city") or state.get("current_city") or "").strip()
            destination = str(state.get("initial_transfer_destination_city") or "").strip()
            required = _fatigue_int(state.get("initial_transfer_required_fatigue"), 0)
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"异地开局：{source or '当前城市'} 商品全买完成，准备前往最近端点 {destination or '-'}（安全需求 {required}）。",
                event="manual_two_city_initial_transfer_buy_report_ready",
                data={
                    "source": source,
                    "destination": destination,
                    "required": required,
                    "base_required": state.get("initial_transfer_base_required_fatigue"),
                    "safety_buffer": MANUAL_TWO_CITY_FATIGUE_SAFETY_BUFFER,
                    "texts": _ocr_texts(argv)[:40],
                },
            )
            _json_payload(
                "manual_two_city_business_buy_report_ready",
                {"ok": True, "initial_transfer": True, "source": source, "destination": destination, "required": required},
            )
            return True
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"{leg.get('buy_city') or ''} 买入完成，准备关闭结算报告并前往 {leg.get('sell_city') or ''}。",
            event="manual_two_city_buy_report_ready",
            data={"leg": leg},
        )
        _json_payload("manual_two_city_business_buy_report_ready", {"ok": True, "leg": leg})
        return True


@AgentServer.custom_action("manual_two_city_business_close_buy_report")
class ManualTwoCityBusinessCloseBuyReportAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        leg = _manual_two_city_active_leg()
        try:
            closed, close_texts = _manual_two_city_close_settlement_report(
                context,
                probe_prefix="ManualTwoCityCloseBuyReport",
            )
        except Exception as exc:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"关闭买入结算报告失败：{type(exc).__name__}: {exc}",
                level="warning",
                event="manual_two_city_close_buy_report_failed",
                data={"leg": leg, "traceback": traceback.format_exc(limit=6)},
            )
            _json_payload("manual_two_city_business_close_buy_report", {"ok": False, "leg": leg, "error": str(exc)})
            return False
        if not closed:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                "关闭买入结算报告：多次点击后仍检测到结算报告，继续后续流程并交给入口兜底处理。",
                level="warning",
                event="manual_two_city_close_buy_report_still_visible",
                data={"leg": leg, "texts": close_texts[:20]},
            )
        if state.get("initial_transfer_pending"):
            state["initial_transfer_pending"] = False
            state["initial_transfer_in_progress"] = True
            state["trade_phase"] = "transfer"
            destination = str(state.get("initial_transfer_destination_city") or "").strip()
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"异地开局：已关闭买入报告，准备返回主界面打开路线图前往 {destination or '-'}。",
                event="manual_two_city_initial_transfer_close_buy_report",
                data={
                    "source": state.get("initial_transfer_source_city"),
                    "destination": destination,
                    "required": state.get("initial_transfer_required_fatigue"),
                },
            )
            _json_payload(
                "manual_two_city_business_close_buy_report",
                {"ok": True, "initial_transfer": True, "destination": destination},
            )
            return True
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "已关闭买入结算报告，准备返回主界面打开路线图。",
            event="manual_two_city_close_buy_report",
            data={"leg": leg, "closed": closed},
        )
        _json_payload("manual_two_city_business_close_buy_report", {"ok": True, "leg": leg, "closed": closed})
        return True


@AgentServer.custom_action("manual_two_city_business_verify_cargo_after_buy")
class ManualTwoCityBusinessVerifyCargoAfterBuyAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        leg = _manual_two_city_active_leg()
        if state.get("initial_transfer_in_progress"):
            _json_payload(
                "manual_two_city_business_verify_cargo_after_buy",
                {"ok": True, "reason": "initial_transfer_skip", "leg": leg},
            )
            return True

        cargo_load, texts = _manual_two_city_probe_buy_page_cargo_load(
            context,
            "ManualTwoCityVerifyCargoAfterBuy",
        )
        planned_total = _manual_two_city_planned_goods_total(leg)
        if cargo_load is None:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                "买入后货仓复核：未能读取货仓载量，继续发车；若肉眼发现未满，请保留日志继续定位。",
                level="warning",
                event="manual_two_city_post_buy_cargo_unreadable",
                data={"leg": leg, "planned_total": planned_total, "texts": texts[:20]},
            )
            _json_payload(
                "manual_two_city_business_verify_cargo_after_buy",
                {"ok": True, "reason": "cargo_unreadable", "leg": leg, "planned_total": planned_total, "texts": texts[:20]},
            )
            return True

        capacity = int(cargo_load.get("capacity") or 0)
        used = int(cargo_load.get("used") or 0)
        planned_ratio = planned_total / capacity if capacity > 0 else 0
        actual_ratio = used / capacity if capacity > 0 else 0
        strict = capacity > 0 and planned_ratio >= POST_BUY_CARGO_VERIFY_PLANNED_RATIO
        passed = (not strict) or actual_ratio >= POST_BUY_CARGO_VERIFY_PASS_RATIO
        level = "info" if passed else "error"
        message = (
            f"买入后货仓复核：实际 {used}/{capacity}，计划 {planned_total}/{capacity}。"
            if capacity > 0
            else f"买入后货仓复核：实际 {used}/-，计划 {planned_total}/-。"
        )
        if not passed:
            message += "计划应接近满载但实际未满，停止发车以避免半仓跑商。"
        else:
            message += "复核通过，继续发车。"
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            message,
            level=level,
            event="manual_two_city_post_buy_cargo_verified" if passed else "manual_two_city_post_buy_cargo_insufficient",
            data={
                "leg": leg,
                "cargo_load": cargo_load,
                "planned_total": planned_total,
                "planned_ratio": planned_ratio,
                "actual_ratio": actual_ratio,
                "strict": strict,
                "texts": texts[:20],
            },
        )
        _json_payload(
            "manual_two_city_business_verify_cargo_after_buy",
            {
                "ok": passed,
                "leg": leg,
                "cargo_load": cargo_load,
                "planned_total": planned_total,
                "planned_ratio": planned_ratio,
                "actual_ratio": actual_ratio,
                "strict": strict,
            },
        )
        return passed


@AgentServer.custom_action("manual_two_city_business_sell_page_ready")
class ManualTwoCityBusinessSellPageReadyAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        texts = _ocr_texts(argv)
        leg = _manual_two_city_active_leg()
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            (
                f"卖出页：当前执行 {leg.get('buy_city') or '-'} -> {leg.get('sell_city') or '-'}，"
                "准备全选货仓商品。"
            ),
            event="manual_two_city_sell_page_ready",
            data={
                "active_leg_index": _manual_two_city_state().get("active_leg_index"),
                "leg": leg,
                "texts": texts[:40],
            },
        )
        _json_payload("manual_two_city_business_sell_page_ready", {"ok": True, "leg": leg})
        return True


@AgentServer.custom_action("manual_two_city_business_apply_sell_haggle")
class ManualTwoCityBusinessApplySellHaggleAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        leg = _manual_two_city_active_leg()
        cleanup = bool(state.get("pre_buy_cleanup"))
        if cleanup:
            target_percent = _manual_two_city_haggle_count(state.get("pre_buy_cleanup_raise_percent"))
        else:
            target_percent = _manual_two_city_sell_raise_percent(leg)
        if target_percent <= 0:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                (
                    "买入前清仓：货仓残留未超过 50%，不抬价直接卖出。"
                    if cleanup
                    else f"抬价：{leg.get('sell_city') or '当前城市'} 本段无需抬价。"
                ),
                event="manual_two_city_sell_haggle_skipped",
                data={"leg": leg, "pre_buy_cleanup": cleanup, "cargo_load": state.get("pre_buy_cleanup_cargo")},
            )
            _json_payload("manual_two_city_business_apply_sell_haggle", {"ok": True, "target_percent": 0})
            return True

        try:
            click_count = 0
            haggle_book_used = False
            current_percent: float | None = None
            final_percent: float | None = None
            start_time = time.perf_counter()
            while time.perf_counter() - start_time < 30.0:
                if _manual_two_city_confirm_buy_haggle_book_popup(
                    context,
                    leg=leg,
                    target_percent=target_percent,
                    current_percent=current_percent,
                    click_count=click_count,
                    probe_name=f"ManualTwoCitySellHaggleBookBeforeRead{click_count + 1:03d}",
                    allow_confirm=not haggle_book_used,
                ):
                    haggle_book_used = True
                    continue

                current_percent = _manual_two_city_read_buy_haggle_percent(context)
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    f"抬价：当前 {_manual_two_city_format_percent(current_percent)}%，目标 {target_percent}%。",
                    event="manual_two_city_sell_haggle_progress",
                    data={"current_percent": current_percent, "target_percent": target_percent, "click_count": click_count, "leg": leg},
                )
                if current_percent is not None and current_percent >= target_percent:
                    break

                clicked, button_texts = _manual_two_city_click_ocr_text(
                    context,
                    f"ManualTwoCitySellHaggleButton{click_count + 1:03d}",
                    BUY_HAGGLE_BUTTON_TEXTS,
                    roi=BUY_HAGGLE_BUTTON_ROI,
                    fallback=BUY_HAGGLE_BUTTON_TARGET,
                    delay=1.65,
                )
                if not clicked:
                    raise RuntimeError(f"cannot find sell haggle button: {button_texts[:12]}")
                click_count += 1

                if _manual_two_city_confirm_buy_haggle_book_popup(
                    context,
                    leg=leg,
                    target_percent=target_percent,
                    current_percent=current_percent,
                    click_count=click_count,
                    probe_name=f"ManualTwoCitySellHaggleBookAfterClick{click_count:03d}",
                    allow_confirm=not haggle_book_used,
                ):
                    haggle_book_used = True
                    continue

                unavailable_hit, _, unavailable_texts = _manual_two_city_ocr_entries(
                    context,
                    f"ManualTwoCitySellHaggleUnavailable{click_count:03d}",
                    BUY_HAGGLE_UNAVAILABLE_TEXTS,
                )
                if unavailable_hit:
                    _append_user_log(
                        MANUAL_TWO_CITY_TASK_ENTRY,
                        f"抬价：识别到次数不足提示，但没有发现请求书确认弹窗，当前 {_manual_two_city_format_percent(current_percent)}%。",
                        level="warning",
                        event="manual_two_city_sell_haggle_unavailable_without_book_popup",
                        data={
                            "target_percent": target_percent,
                            "current_percent": current_percent,
                            "click_count": click_count,
                            "texts": unavailable_texts[:20],
                            "leg": leg,
                        },
                    )
                    break

                time.sleep(0.35)
            else:
                raise RuntimeError(f"sell haggle target timeout: current={current_percent}, target={target_percent}")

            final_percent = _manual_two_city_read_buy_haggle_percent(context)
            if final_percent is not None and final_percent < target_percent:
                raise RuntimeError(f"sell haggle target not reached: current={final_percent}, target={target_percent}")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"抬价操作失败：{error}",
                level="error",
                event="manual_two_city_sell_haggle_failed",
                data={"leg": leg, "target_percent": target_percent, "traceback": traceback.format_exc(limit=6)},
            )
            _json_payload("manual_two_city_business_apply_sell_haggle_failed", {"ok": False, "error": error})
            return False

        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"抬价：已达到 {_manual_two_city_format_percent(final_percent if final_percent is not None else target_percent)}%（目标 {target_percent}%），继续全部卖出。",
            event="manual_two_city_sell_haggle_done",
            data={"target_percent": target_percent, "final_percent": final_percent, "click_count": click_count, "leg": leg},
        )
        _json_payload(
            "manual_two_city_business_apply_sell_haggle",
            {"ok": True, "target_percent": target_percent, "final_percent": final_percent, "click_count": click_count, "leg": leg},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_sell_report_ready")
class ManualTwoCityBusinessSellReportReadyAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        leg = _manual_two_city_active_leg()
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"{leg.get('buy_city') or ''} -> {leg.get('sell_city') or ''} 卖出完成，准备关闭结算报告。",
            event="manual_two_city_sell_report_ready",
            data={"leg": leg, "texts": _ocr_texts(argv)[:40]},
        )
        _json_payload("manual_two_city_business_sell_report_ready", {"ok": True, "leg": leg})
        return True


@AgentServer.custom_action("manual_two_city_business_close_sell_report")
class ManualTwoCityBusinessCloseSellReportAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        leg = _manual_two_city_active_leg()
        try:
            closed, close_texts = _manual_two_city_close_settlement_report(
                context,
                probe_prefix="ManualTwoCityCloseSellReport",
            )
        except Exception as exc:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"关闭卖出结算报告失败：{type(exc).__name__}: {exc}",
                level="warning",
                event="manual_two_city_close_sell_report_failed",
                data={"leg": leg, "traceback": traceback.format_exc(limit=6)},
            )
            _json_payload("manual_two_city_business_close_sell_report", {"ok": False, "leg": leg, "error": str(exc)})
            return False
        if not closed:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                "关闭卖出结算报告：多次点击后仍检测到结算报告，继续后续流程并交给入口兜底处理。",
                level="warning",
                event="manual_two_city_close_sell_report_still_visible",
                data={"leg": leg, "texts": close_texts[:20]},
            )
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "已关闭卖出结算报告，准备判断是否进入下一段跑商。",
            event="manual_two_city_close_sell_report",
            data={"leg": leg, "closed": closed},
        )
        _json_payload("manual_two_city_business_close_sell_report", {"ok": True, "leg": leg, "closed": closed})
        return True


@AgentServer.custom_action("manual_two_city_business_sell_goods_missing")
class ManualTwoCityBusinessSellGoodsMissingAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        leg = _manual_two_city_active_leg()
        if state.get("pre_buy_cleanup"):
            cargo_load = state.pop("pre_buy_cleanup_cargo", None)
            cleanup_signature = state.pop("pre_buy_cleanup_signature", None)
            state.pop("pre_buy_cleanup", None)
            state.pop("pre_buy_cleanup_raise_percent", None)
            state.pop("pre_buy_cleanup_strength_required", None)
            if cleanup_signature:
                state["pre_buy_cleanup_skip_signature"] = cleanup_signature
            state["selected_buy_goods"] = []
            state["trade_phase"] = "buy"
            try:
                clicked, switch_texts = _manual_two_city_click_ocr_text(
                    context,
                    "ManualTwoCityPreBuyCleanupLocalGoodsSwitchToBuy",
                    ["我要买"],
                    roi=TRADE_SWITCH_TO_BUY_ROI,
                    fallback=TRADE_SWITCH_TO_BUY_TARGET,
                    delay=1.0,
                )
            except Exception as exc:
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    f"买入前清仓：本地货无法卖出，切回买入页失败：{type(exc).__name__}: {exc}",
                    level="error",
                    event="manual_two_city_pre_buy_cleanup_local_goods_switch_failed",
                    data={
                        "active_leg_index": state.get("active_leg_index"),
                        "leg": leg,
                        "cargo_load": cargo_load,
                        "traceback": traceback.format_exc(limit=6),
                    },
                )
                _json_payload(
                    "manual_two_city_business_sell_goods_missing",
                    {"ok": False, "reason": "switch_to_buy_failed", "error": str(exc), "pre_buy_cleanup": True},
                )
                return False
            if not clicked:
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    "买入前清仓：卖出页全是本地货，准备跳过卖出，但未能切回买入页。",
                    level="error",
                    event="manual_two_city_pre_buy_cleanup_local_goods_switch_not_clicked",
                    data={"active_leg_index": state.get("active_leg_index"), "leg": leg, "cargo_load": cargo_load},
                )
                _json_payload(
                    "manual_two_city_business_sell_goods_missing",
                    {"ok": False, "reason": "switch_to_buy_not_clicked", "pre_buy_cleanup": True},
                )
                return False
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                "买入前清仓：卖出页全是本地货，全部卖出未选中，跳过卖出并切回买入页继续补货。",
                level="warning",
                event="manual_two_city_pre_buy_cleanup_local_goods_skip_sell",
                data={
                    "active_leg_index": state.get("active_leg_index"),
                    "leg": leg,
                    "cargo_load": cargo_load,
                    "switch_texts": switch_texts[:20],
                },
            )
            _json_payload(
                "manual_two_city_business_sell_goods_missing",
                {"ok": True, "reason": "local_goods_skip_sell", "pre_buy_cleanup": True, "leg": leg},
            )
            return True

        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "卖出商品未选中：卖出页没有成功全选货仓商品，已停止，避免误操作。",
            level="error",
            event="manual_two_city_sell_goods_missing",
            data={"active_leg_index": state.get("active_leg_index"), "leg": leg},
        )
        _json_payload(
            "manual_two_city_business_sell_goods_missing",
            {"ok": False, "reason": "sell_goods_not_selected", "leg": leg},
        )
        return False


@AgentServer.custom_action("manual_two_city_business_after_sell")
class ManualTwoCityBusinessAfterSellAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        current_leg = _manual_two_city_active_leg()
        if state.get("pre_buy_cleanup"):
            cargo_load = state.pop("pre_buy_cleanup_cargo", None)
            state.pop("pre_buy_cleanup_signature", None)
            state.pop("pre_buy_cleanup_skip_signature", None)
            state.pop("pre_buy_cleanup", None)
            state.pop("pre_buy_cleanup_raise_percent", None)
            state.pop("pre_buy_cleanup_strength_required", None)
            state["selected_buy_goods"] = []
            state["trade_phase"] = "buy"
            try:
                clicked, switch_texts = _manual_two_city_click_ocr_text(
                    context,
                    "ManualTwoCityPreBuyCleanupSwitchToBuy",
                    ["我要买"],
                    roi=TRADE_SWITCH_TO_BUY_ROI,
                    fallback=TRADE_SWITCH_TO_BUY_TARGET,
                    delay=1.0,
                )
            except Exception as exc:
                _append_user_log(
                    MANUAL_TWO_CITY_TASK_ENTRY,
                    f"买入前清仓完成后切回买入页失败：{type(exc).__name__}: {exc}",
                    level="error",
                    event="manual_two_city_pre_buy_cleanup_switch_to_buy_failed",
                    data={
                        "active_leg_index": state.get("active_leg_index"),
                        "leg": current_leg,
                        "cargo_load": cargo_load,
                        "traceback": traceback.format_exc(limit=6),
                    },
                )
                _json_payload(
                    "manual_two_city_business_after_sell",
                    {"ok": False, "pre_buy_cleanup": True, "reason": "switch_to_buy_failed", "error": str(exc)},
                )
                return False
            if not clicked:
                _json_payload(
                    "manual_two_city_business_after_sell",
                    {"ok": False, "pre_buy_cleanup": True, "reason": "switch_to_buy_not_clicked"},
                )
                return False
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                (
                    "买入前清仓完成：已从卖出页切回买入页，继续本段买入。"
                ),
                event="manual_two_city_pre_buy_cleanup_done",
                data={
                    "active_leg_index": state.get("active_leg_index"),
                    "leg": current_leg,
                    "cargo_load": cargo_load,
                    "switch_texts": switch_texts[:20],
                },
            )
            _json_payload(
                "manual_two_city_business_after_sell",
                {
                    "ok": True,
                    "pre_buy_cleanup": True,
                    "active_leg_index": state.get("active_leg_index"),
                    "leg": current_leg,
                },
            )
            return True

        next_index, next_leg = _manual_two_city_next_leg_after_current()
        if next_leg:
            state["active_leg_index"] = next_index
            state["selected_buy_goods"] = []
            state["trade_phase"] = "buy"
            state["current_city"] = str(next_leg.get("buy_city") or current_leg.get("sell_city") or "")
            state.pop("strength_recovery_required", None)
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                (
                    f"下一段：准备在 {next_leg.get('buy_city') or '-'} 买入，"
                    f"前往 {next_leg.get('sell_city') or '-'}。"
                ),
                event="manual_two_city_next_leg_ready",
                data={"active_leg_index": next_index, "current_leg": current_leg, "next_leg": next_leg},
            )
            _json_payload("manual_two_city_business_after_sell", {"ok": True, "next_leg": next_leg, "active_leg_index": next_index})
            return True

        legs = _manual_two_city_legs()
        if _manual_two_city_until_fatigue_exhausted(state) and legs:
            completed_rounds = int(state.get("completed_rounds") or 0) + 1
            next_leg = legs[0]
            state["completed_rounds"] = completed_rounds
            state["active_leg_index"] = 0
            state["selected_buy_goods"] = []
            state["trade_phase"] = "buy"
            state["current_city"] = str(current_leg.get("sell_city") or next_leg.get("buy_city") or "")
            state.pop("strength_recovery_required", None)
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                (
                    f"跑到疲劳耗尽：第 {completed_rounds} 轮已完成，"
                    f"继续下一轮 {next_leg.get('buy_city') or '-'} -> {next_leg.get('sell_city') or '-'}。"
                ),
                event="manual_two_city_loop_next_round_ready",
                data={"completed_rounds": completed_rounds, "last_leg": current_leg, "next_leg": next_leg},
            )
            _json_payload(
                "manual_two_city_business_after_sell",
                {
                    "ok": True,
                    "loop_next_round": True,
                    "completed_rounds": completed_rounds,
                    "next_leg": next_leg,
                    "active_leg_index": 0,
                },
            )
            return True

        state["trade_phase"] = "done"
        state["terminal_status"] = MANUAL_TWO_CITY_TERMINAL_ONE_ROUND_COMPLETE
        state["terminal_reason"] = "所有买入、行车和卖出段已执行"
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "手动双城跑商完成：所有买入、行车和卖出段已执行。",
            event="manual_two_city_business_complete",
            data={"last_leg": current_leg},
        )
        _json_payload("manual_two_city_business_after_sell", {"ok": False, "reason": "all_legs_complete", "last_leg": current_leg})
        return False


@AgentServer.custom_action("manual_two_city_business_done")
class ManualTwoCityBusinessDoneAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        task_entry = _manual_two_city_current_task_entry(state)
        task_label = _manual_two_city_log_label(state)
        recovery = _manual_two_city_strength_recovery_state(state)
        config_result = _fatigue_read_option_config_values(
            task_name=task_entry,
            option_name="ManualTwoCityMedicineLimits",
        )
        used = dict(recovery.get("used") or {})
        terminal_status = str(state.get("terminal_status") or "").strip()
        terminal_reason = str(state.get("terminal_reason") or "").strip()
        run_mode = _manual_two_city_run_mode(state.get("run_mode"))
        is_success = (
            terminal_status == MANUAL_TWO_CITY_TERMINAL_ONE_ROUND_COMPLETE
            and run_mode == MANUAL_TWO_CITY_RUN_MODE_ONE_ROUND
        ) or (
            terminal_status == MANUAL_TWO_CITY_TERMINAL_FATIGUE_EXHAUSTED
            and run_mode == MANUAL_TWO_CITY_RUN_MODE_UNTIL_FATIGUE_EXHAUSTED
        )
        pending_option_values = state.get("pending_medicine_option_values")
        final_config_write: dict[str, Any] | None = None
        final_delayed_config_write: dict[str, Any] | None = None
        if isinstance(pending_option_values, dict) and pending_option_values:
            final_config_write = _fatigue_rewrite_option_config_values_with_retry(
                task_name=task_entry,
                option_name="ManualTwoCityMedicineLimits",
                values=pending_option_values,
            )
            final_delayed_config_write = final_config_write.get("delayed")
            if not isinstance(final_delayed_config_write, dict):
                final_delayed_config_write = _fatigue_schedule_delayed_option_config_write(
                    task_name=task_entry,
                    option_name="ManualTwoCityMedicineLimits",
                    values=pending_option_values,
                    delays=[2.0, 5.0, 10.0],
                )
        if is_success:
            result_note = terminal_reason or "已按跑商执行方式正常完成"
            level = "info"
        else:
            result_note = terminal_reason or f"未按跑商执行方式完成，当前阶段 {state.get('trade_phase') or '-'}"
            level = "error"
        result_note = str(result_note).strip().rstrip("。.!！?？")
        _append_user_log(
            task_entry,
            f"{task_label}收尾：{result_note}。",
            level=level,
            event="manual_two_city_business_done",
            data={
                "used": used,
                "huashi_total_cost": recovery.get("huashi_total_cost"),
                "huashi_unknown_cost_count": recovery.get("huashi_unknown_cost_count"),
                "config_result": config_result,
                "trade_phase": state.get("trade_phase"),
                "run_mode": run_mode,
                "terminal_status": terminal_status,
                "terminal_reason": terminal_reason,
                "success": is_success,
                "pending_option_values": pending_option_values if isinstance(pending_option_values, dict) else {},
                "final_config_write": final_config_write,
                "final_delayed_config_write": final_delayed_config_write,
            },
        )
        _json_payload(
            "manual_two_city_business_done",
            {
                "ok": is_success,
                "used": used,
                "config_result": config_result,
                "trade_phase": state.get("trade_phase"),
                "run_mode": run_mode,
                "terminal_status": terminal_status,
                "terminal_reason": terminal_reason,
                "pending_option_values": pending_option_values if isinstance(pending_option_values, dict) else {},
            },
        )
        return is_success


@AgentServer.custom_action("manual_two_city_business_close_sell_page_for_next_leg")
class ManualTwoCityBusinessCloseSellPageForNextLegAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        leg = _manual_two_city_active_leg()
        try:
            _manual_two_city_click(context, (83, 36), 0.75)
        except Exception as exc:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"关闭卖出页失败：{type(exc).__name__}: {exc}",
                level="warning",
                event="manual_two_city_close_sell_page_for_next_leg_failed",
                data={
                    "leg": leg,
                    "active_leg_index": state.get("active_leg_index"),
                    "traceback": traceback.format_exc(limit=6),
                },
            )
            _json_payload(
                "manual_two_city_business_close_sell_page_for_next_leg",
                {"ok": False, "leg": leg, "error": str(exc)},
            )
            return False
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"已关闭卖出页，准备在 {leg.get('buy_city') or '当前城市'} 继续买入。",
            event="manual_two_city_close_sell_page_for_next_leg",
            data={"leg": leg, "active_leg_index": state.get("active_leg_index")},
        )
        _json_payload("manual_two_city_business_close_sell_page_for_next_leg", {"ok": True, "leg": leg})
        return True


@AgentServer.custom_action("manual_two_city_business_move_to_destination")
class ManualTwoCityBusinessMoveToDestinationAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _argv_param(argv)
        state = _manual_two_city_state()
        leg = _manual_two_city_active_leg()
        destination_city = str(
            params.get("destination_city")
            or (state.get("initial_transfer_destination_city") if state.get("initial_transfer_in_progress") else "")
            or leg.get("sell_city")
            or ""
        ).strip()
        if not destination_city:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                "路线图定位失败：当前买卖段没有目标城市。",
                level="warning",
                event="manual_two_city_destination_missing",
                data={"leg": leg},
            )
            _json_payload("manual_two_city_business_move_to_destination", {"ok": False, "reason": "missing_destination_city", "leg": leg})
            return False
        if state.get("initial_transfer_in_progress"):
            message = f"异地开局：正在路线图定位最近端点 {destination_city}"
            event = "manual_two_city_initial_transfer_destination_locating"
        else:
            message = f"正在路线图定位目标城市：{destination_city}"
            event = "manual_two_city_destination_locating"
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            message,
            event=event,
            data={"leg": leg, "destination_city": destination_city},
        )
        try:
            payload = destination_map_coordinate_probe(
                context,
                {
                    **params,
                    "destination_city": destination_city,
                    "max_steps": params.get("max_steps") or 6,
                    "drag_distance": params.get("drag_distance") or 520,
                },
            )
        except Exception as exc:
            payload = {
                "ok": False,
                "destination_city": destination_city,
                "reason": "exception",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=8),
            }
        if payload.get("ok"):
            ready_event = (
                "manual_two_city_initial_transfer_destination_ready"
                if state.get("initial_transfer_in_progress")
                else "manual_two_city_destination_ready"
            )
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"已打开目标城市面板：{destination_city}",
                event=ready_event,
                data={"leg": leg, "payload": payload},
            )
        else:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"路线图定位目标城市失败：{destination_city} ({payload.get('reason') or 'unknown'})",
                level="warning",
                event="manual_two_city_destination_failed",
                data={"leg": leg, "payload": payload},
            )
        _json_payload("manual_two_city_business_move_to_destination", {**payload, "leg": leg})
        return bool(payload.get("ok"))


@AgentServer.custom_action("manual_two_city_business_travel_started")
class ManualTwoCityBusinessTravelStartedAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        leg = _manual_two_city_active_leg()
        texts = _ocr_texts(argv)
        status = travel_status_from_texts(texts)
        destination = _manual_two_city_travel_target_city()
        state["travel_started_at"] = time.monotonic()
        state["travel_last_status"] = status
        state["travel_progress_last_log_at"] = 0.0
        state.pop("travel_recovering_from_stall", None)
        _manual_two_city_reset_travel_stall_state(state, reset_restart_count=True)
        if state.get("initial_transfer_in_progress"):
            message = f"异地开局：已出发前往最近端点 {destination or '-'}，开始监听行车状态。"
            event = "manual_two_city_initial_transfer_travel_started"
        else:
            message = f"已出发：{leg.get('buy_city') or '-'} -> {leg.get('sell_city') or '-'}，开始监听行车状态。"
            event = "manual_two_city_travel_started"
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            message,
            event=event,
            data={"leg": leg, "destination": destination, "status": status, "texts": texts[:30]},
        )
        _json_payload("manual_two_city_business_travel_started", {"ok": True, "leg": leg, "status": status})
        return True


@AgentServer.custom_action("manual_two_city_business_depart_fatigue_popup")
class ManualTwoCityBusinessDepartFatiguePopupAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        leg = _manual_two_city_active_leg()
        state["trade_phase"] = "done"
        if _manual_two_city_until_fatigue_exhausted(state):
            state["terminal_status"] = MANUAL_TWO_CITY_TERMINAL_FATIGUE_EXHAUSTED
            state["terminal_reason"] = "出发时触发疲劳不足提示"
            level = "warning"
            message = "跑到疲劳耗尽：出发时识别到疲劳不足/恢复疲劳提示，结束本次跑商。"
        else:
            state["terminal_status"] = MANUAL_TWO_CITY_TERMINAL_FAILED
            state["terminal_reason"] = "跑 1 轮模式下出发前疲劳不足"
            level = "error"
            message = "跑 1 轮失败：出发时识别到疲劳不足/恢复疲劳提示，未完成本轮跑商。"
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            message,
            level=level,
            event="manual_two_city_depart_fatigue_popup",
            data={
                "leg": leg,
                "completed_rounds": state.get("completed_rounds"),
                "run_mode": state.get("run_mode"),
                "texts": _ocr_texts(argv)[:40],
            },
        )
        _json_payload("manual_two_city_business_depart_fatigue_popup", {"ok": True, "leg": leg})
        return True


@AgentServer.custom_action("manual_two_city_business_travel_continue_if_needed")
class ManualTwoCityBusinessTravelContinueIfNeededAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        leg = _manual_two_city_active_leg()
        texts = _ocr_texts(argv)
        status = travel_status_from_texts(texts)
        state["travel_last_status"] = status
        state["travel_last_status_at"] = time.monotonic()
        _manual_two_city_log_travel_progress(status, leg)
        should_tap = bool(
            not status.get("cruising")
            and (status.get("destination") is not None or status.get("remaining_km") is not None)
        )
        if should_tap:
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                "行车：HUD 未处于巡航，准备点击继续前进。",
                event="manual_two_city_travel_continue_needed",
                data={"leg": leg, "status": status, "texts": texts[:20]},
            )
        _json_payload(
            "manual_two_city_business_travel_continue_if_needed",
            {"ok": should_tap, "should_tap": should_tap, "leg": leg, "status": status},
        )
        return should_tap


@AgentServer.custom_action("manual_two_city_business_travel_stall_watchdog")
class ManualTwoCityBusinessTravelStallWatchdogAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        stalled, payload = _manual_two_city_travel_stall_watchdog(context)
        _json_payload(
            "manual_two_city_business_travel_stall_watchdog",
            {"ok": stalled, **payload},
        )
        return stalled


@AgentServer.custom_action("manual_two_city_business_travel_stall_dispatch")
class ManualTwoCityBusinessTravelStallDispatchAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        if state.pop("travel_stall_failed_pending", False):
            _json_payload(
                "manual_two_city_business_travel_stall_dispatch",
                {"ok": False, "reason": "restart_limit_reached", "terminal_reason": state.get("terminal_reason")},
            )
            return False
        pending = bool(state.pop("travel_stall_restart_pending", False))
        _json_payload(
            "manual_two_city_business_travel_stall_dispatch",
            {"ok": pending, "reason": "restart_pending" if pending else "not_pending"},
        )
        return pending


@AgentServer.custom_action("manual_two_city_business_travel_stuck_restart_done")
class ManualTwoCityBusinessTravelStuckRestartDoneAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        state["trade_phase"] = "travel"
        _manual_two_city_reset_travel_stall_state(state, reset_restart_count=False)
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            "行车异常：游戏已重启，准备重新识别当前是否仍在行车途中。",
            level="warning",
            event="manual_two_city_travel_stuck_restart_done",
            data={"restart_count": state.get("travel_stall_restart_count")},
        )
        _json_payload(
            "manual_two_city_business_travel_stuck_restart_done",
            {"ok": True, "restart_count": state.get("travel_stall_restart_count")},
        )
        return True


@AgentServer.custom_action("manual_two_city_business_travel_arrived")
class ManualTwoCityBusinessTravelArrivedAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        state = _manual_two_city_state()
        leg = _manual_two_city_active_leg()
        texts = _ocr_texts(argv)
        status = travel_status_from_texts(texts)
        remaining = status.get("remaining_km")
        if status.get("cruising") or (isinstance(remaining, int) and remaining > 3):
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                f"行车：检测到仍在路上（剩余 {remaining if remaining is not None else '-'} km），忽略本次到站识别。",
                level="warning",
                event="manual_two_city_travel_arrival_rejected",
                data={"leg": leg, "status": status, "texts": texts[:40]},
            )
            _json_payload(
                "manual_two_city_business_travel_arrived",
                {"ok": False, "reason": "travel_hud_still_active", "leg": leg, "status": status, "texts": texts[:40]},
            )
            return False
        current_city = _manual_two_city_detect_current_city(texts, _manual_two_city_legs()) or _manual_two_city_travel_target_city()
        if current_city:
            state["current_city"] = current_city
            state["travel_arrived_city"] = current_city
        if state.get("startup_travel_in_progress"):
            target_city = normalize_city_name(str(state.get("startup_travel_target_city") or current_city or "").strip())
            arrived_city = normalize_city_name(str(current_city or target_city).strip())
            start_city, target_endpoint = _manual_two_city_endpoint_cities()
            endpoint_cities = {city for city in (start_city, target_endpoint) if city}
            next_leg = _manual_two_city_active_leg()
            state["startup_travel_in_progress"] = False
            state["startup_travel_done"] = True
            state["startup_travel_arrived_city"] = arrived_city
            state.pop("strength_recovery_required", None)
            state["trade_phase"] = "buy"
            if arrived_city in endpoint_cities:
                next_leg = _manual_two_city_set_active_leg_by_city(arrived_city)
                state["initial_transfer_pending"] = False
                state["initial_transfer_in_progress"] = False
                state["initial_transfer_needs_recovery"] = False
                message = (
                    f"开局行车到站：已到达端点 {arrived_city}，"
                    f"准备进入交易所开始 {next_leg.get('buy_city') or '-'} -> {next_leg.get('sell_city') or '-'}。"
                )
                event = "manual_two_city_startup_travel_arrived_endpoint"
            else:
                state["current_city"] = arrived_city
                state["initial_transfer_done"] = False
                state["initial_transfer_pending"] = False
                state["initial_transfer_in_progress"] = False
                state["initial_transfer_needs_recovery"] = False
                message = (
                    f"开局行车到站：已到达 {arrived_city or target_city or '未知城市'}，"
                    "不是设定的起点/目标，进入交易所后继续执行异地开局处理。"
                )
                event = "manual_two_city_startup_travel_arrived_non_endpoint"
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                message,
                level="warning",
                event=event,
                data={
                    "target_city": target_city,
                    "arrived_city": arrived_city,
                    "start_city": start_city,
                    "target_endpoint": target_endpoint,
                    "next_leg": next_leg,
                    "status": status,
                    "texts": texts[:40],
                },
            )
            _json_payload(
                "manual_two_city_business_travel_arrived",
                {
                    "ok": True,
                    "startup_travel": True,
                    "current_city": arrived_city,
                    "target_city": target_city,
                    "leg": next_leg,
                    "status": status,
                    "texts": texts[:40],
                },
            )
            return True
        if state.get("initial_transfer_in_progress"):
            destination = str(state.get("initial_transfer_destination_city") or current_city or "").strip()
            endpoint_city = current_city or destination
            next_leg = _manual_two_city_set_active_leg_by_city(endpoint_city) if endpoint_city else _manual_two_city_active_leg()
            state["initial_transfer_in_progress"] = False
            state["initial_transfer_done"] = True
            state["initial_transfer_needs_recovery"] = False
            state.pop("strength_recovery_required", None)
            state["trade_phase"] = "buy"
            _append_user_log(
                MANUAL_TWO_CITY_TASK_ENTRY,
                (
                    f"异地开局中转到站：已到达 {endpoint_city or destination or '最近端点'}，"
                    f"准备进入交易所开始 {next_leg.get('buy_city') or '-'} -> {next_leg.get('sell_city') or '-'}。"
                ),
                event="manual_two_city_initial_transfer_arrived",
                data={
                    "source": state.get("initial_transfer_source_city"),
                    "destination": destination,
                    "current_city": current_city,
                    "next_leg": next_leg,
                    "status": status,
                    "texts": texts[:40],
                },
            )
            _json_payload(
                "manual_two_city_business_travel_arrived",
                {"ok": True, "initial_transfer": True, "current_city": endpoint_city, "leg": next_leg, "status": status, "texts": texts[:40]},
            )
            return True
        state["trade_phase"] = "sell"
        state.pop("strength_recovery_required", None)
        _append_user_log(
            MANUAL_TWO_CITY_TASK_ENTRY,
            f"行车到站：已到达 {current_city or leg.get('sell_city') or '目标城市'}，准备进入交易所卖出。",
            event="manual_two_city_travel_arrived",
            data={"leg": leg, "current_city": current_city, "status": status, "texts": texts[:40]},
        )
        _json_payload(
            "manual_two_city_business_travel_arrived",
            {"ok": True, "leg": leg, "current_city": current_city, "status": status, "texts": texts[:40]},
        )
        return True

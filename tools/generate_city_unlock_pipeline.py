from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PATH = (
    PROJECT_ROOT
    / "assets"
    / "resource"
    / "base"
    / "pipeline"
    / "business"
    / "profile"
    / "account_profile_city_unlock.json"
)


CITY_ORDER = [
    {"city": "7号自由港", "template": "qhzyg.png", "aliases": ["7号自由港"]},
    {"city": "武林源", "aliases": ["武林源"]},
    {
        "city": "阿妮塔战备工厂",
        "template": "antzbgc.png",
        "aliases": ["阿妮塔战备工厂", "战备工厂", "阿妮塔战备"],
    },
    {
        "city": "阿妮塔能源研究所",
        "template": "antnyyjs.png",
        "aliases": ["阿妮塔能源研究所", "能源研究所", "阿妮塔能源"],
    },
    {
        "city": "阿妮塔发射中心",
        "template": "antfszx.png",
        "aliases": ["阿妮塔发射中心", "发射中心", "阿妮塔发射"],
    },
    {"city": "汇流塔", "template": "hlt.png", "aliases": ["汇流塔"]},
    {"city": "海角城", "template": "hjc.png", "aliases": ["海角城"]},
    {"city": "远星大桥", "template": "yxdq.png", "aliases": ["远星大桥"]},
    {"city": "贡露城", "template": "glc.png", "aliases": ["贡露城"]},
    {
        "city": "澄明数据中心",
        "template": "cmsjzx.png",
        "aliases": ["澄明数据中心", "澄明数据", "数据中心", "澄明", "澄明数"],
    },
    {"city": "修格里城", "template": "xglc.png", "aliases": ["修格里城"]},
    {"city": "铁盟哨站", "template": "tmsz.png", "aliases": ["铁盟哨站"]},
    {"city": "曼德矿场", "template": "mdkc.png", "aliases": ["曼德矿场"]},
    {"city": "淘金乐园", "template": "tjly.png", "aliases": ["淘金乐园"]},
    {"city": "荒原站", "template": "hyz.png", "aliases": ["荒原站"]},
    {
        "city": "云岫桥基地",
        "template": "yxqjd.png",
        "aliases": ["云岫桥基地", "云桥基地", "岫桥基地", "云岫桥"],
    },
    {"city": "栖羽站", "template": "xyz.png", "aliases": ["栖羽站"]},
    {"city": "岚心城", "template": "lxc.png", "aliases": ["岚心城"]},
]

ROUTE_MAP_TEXTS = ["路线图", "前往目的地", "当前站点", "当前城市", "图示", "导航至", "主线任务车站"]
PANEL_TEXTS = [
    "前往目的地",
    "立即出发",
    "访问城市",
    "进入城市",
    "当前站点",
    "当前城市",
    "列车所在站",
    "路程",
    "发展度",
    "声望",
    "交易品",
    "推荐等级",
    "未开放",
    "暂未开放",
    "未解锁",
    "无法前往",
    "前往条件",
    "尚未开放",
]


def reco(node_type: str, param: dict[str, Any] | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"type": node_type}
    if param is not None:
        node["param"] = param
    return node


def action(node_type: str, param: dict[str, Any] | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"type": node_type}
    if param is not None:
        node["param"] = param
    return node


def custom_action(name: str, param: dict[str, Any] | None = None) -> dict[str, Any]:
    custom_param: dict[str, Any] = {"custom_action": name}
    if param is not None:
        custom_param["custom_action_param"] = param
    return action("Custom", custom_param)


def node(
    recognition: dict[str, Any],
    action_node: dict[str, Any],
    *,
    next_node: str | list[str] | None = None,
    on_error: str | list[str] | None = None,
    post_delay: int | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "recognition": recognition,
        "action": action_node,
    }
    if post_delay is not None:
        result["post_delay"] = post_delay
    if timeout is not None:
        result["timeout"] = timeout
    if next_node is not None:
        result["next"] = next_node
    if on_error is not None:
        result["on_error"] = on_error
    return result


def generate_pipeline() -> dict[str, Any]:
    pipeline: dict[str, Any] = {}
    pipeline["AccountProfileCityUnlockStart"] = node(
        reco("OCR", {"expected": ["启程", "START ENGINE", "STARTENGINE"]}),
        action("Click"),
        post_delay=200,
        next_node="AccountProfileCityUnlockMapReady",
        on_error="StateRecoveryStart",
    )
    pipeline["AccountProfileCityUnlockMapReady"] = node(
        reco("OCR", {"expected": [*ROUTE_MAP_TEXTS, *[item["city"] for item in CITY_ORDER]]}),
        action("DoNothing"),
        next_node="AccountProfileCityUnlockZoomOut001",
    )
    pipeline["AccountProfileCityUnlockZoomOut001"] = node(
        reco("DirectHit"),
        action("Click", {"target": [1152, 584]}),
        post_delay=500,
        next_node="AccountProfileCityUnlockProbe001MoveToCity",
    )

    for index, item in enumerate(CITY_ORDER, start=1):
        city = str(item["city"])
        prefix = f"AccountProfileCityUnlockProbe{index:03d}"
        next_prefix = (
            f"AccountProfileCityUnlockProbe{index + 1:03d}"
            if index < len(CITY_ORDER)
            else "AccountProfileCityUnlockComplete"
        )
        next_move = next_prefix if next_prefix == "AccountProfileCityUnlockComplete" else f"{next_prefix}MoveToCity"
        record_param: dict[str, Any] = {"city": city}
        move_param: dict[str, Any] = {
            "city": city,
            "max_steps": 4,
            "drag_distance": 520,
            "drag_duration": 900,
            "drag_delay": 200,
            "click_count": 3,
            "click_delay": 200,
            "panel_settle_delay": 400,
        }
        if index == 1:
            move_param["reset"] = True
        move_on_error = next_move if city == "武林源" else None

        pipeline[f"{prefix}MoveToCity"] = node(
            reco("DirectHit"),
            custom_action(
                "profile_city_unlock_move_to_city",
                move_param,
            ),
            next_node=[
                f"{prefix}ExistingPanelTitle",
                f"{prefix}PanelOcr",
                *([f"{prefix}SelectByTemplate"] if item.get("template") else []),
                f"{prefix}SelectByText",
                f"{prefix}Unknown",
            ],
            on_error=move_on_error,
        )
        pipeline[f"{prefix}ExistingPanelTitle"] = node(
            reco("OCR", {"expected": item["aliases"], "roi": [690, 80, 560, 95]}),
            action("DoNothing"),
            next_node=f"{prefix}PanelOcr",
            on_error=f"{prefix}PanelUnknown",
            timeout=1200,
        )
        if item.get("template"):
            pipeline[f"{prefix}SelectByTemplate"] = node(
                reco(
                    "TemplateMatch",
                    {
                        "template": f"stations/{item['template']}",
                        "threshold": 0.82,
                        "roi": [80, 100, 1040, 500],
                        "order_by": "Score",
                    },
                ),
                action("Click", {"target_offset": [0, -18, 0, 0]}),
                post_delay=200,
                next_node=[f"{prefix}PanelTitle", f"{prefix}PanelOcr", f"{prefix}Unknown"],
                on_error=f"{prefix}SelectByText",
                timeout=1200,
            )
        pipeline[f"{prefix}SelectByText"] = node(
            reco("OCR", {"expected": item["aliases"], "roi": [0, 80, 1280, 520], "order_by": "Expected"}),
            action("Click", {"target_offset": [0, -18, 0, 0]}),
            post_delay=200,
            next_node=[f"{prefix}PanelTitle", f"{prefix}PanelOcr", f"{prefix}Unknown"],
            on_error=f"{prefix}Unknown",
            timeout=1200,
        )
        pipeline[f"{prefix}PanelTitle"] = node(
            reco("OCR", {"expected": item["aliases"], "roi": [690, 80, 560, 95]}),
            action("DoNothing"),
            next_node=f"{prefix}PanelOcr",
            on_error=f"{prefix}PanelUnknown",
            timeout=1200,
        )
        pipeline[f"{prefix}PanelOcr"] = node(
            reco("OCR", {"expected": PANEL_TEXTS, "roi": [680, 80, 580, 620]}),
            custom_action("profile_city_unlock_probe", record_param),
            next_node=f"{prefix}CloseDetail",
            on_error=f"{prefix}PanelUnknown",
        )
        pipeline[f"{prefix}PanelUnknown"] = node(
            reco("DirectHit"),
            custom_action("profile_city_unlock_probe", record_param),
            next_node=f"{prefix}CloseDetail",
        )
        pipeline[f"{prefix}CloseDetail"] = node(
            reco("DirectHit"),
            action("Click", {"target": [80, 360]}),
            post_delay=400,
            next_node=next_move,
        )
        pipeline[f"{prefix}Unknown"] = node(
            reco("DirectHit"),
            custom_action("profile_city_unlock_probe", record_param),
            next_node=next_move,
        )

    pipeline["AccountProfileCityUnlockComplete"] = node(
        reco("DirectHit"),
        custom_action("profile_city_unlock_complete"),
        next_node="AccountProfileCityUnlockReturnHome",
    )
    pipeline["AccountProfileCityUnlockReturnHome"] = node(
        reco("TemplateMatch", {"template": "go_home.png", "roi": [154, 9, 89, 58], "threshold": 0.90}),
        action("Click"),
        post_delay=1000,
        next_node="AccountProfileCityUnlockMainMapReady",
        on_error="AccountProfileCityUnlockReturnBack",
    )
    pipeline["AccountProfileCityUnlockReturnBack"] = node(
        reco("TemplateMatch", {"template": "page_back.png", "roi": [0, 0, 170, 80], "threshold": 0.90}),
        action("Click"),
        post_delay=900,
        next_node="AccountProfileCityUnlockMainMapReady",
        on_error="AccountProfileCityUnlockDone",
    )
    pipeline["AccountProfileCityUnlockMainMapReady"] = node(
        reco("TemplateMatch", {"template": "main_map.png", "threshold": 0.96}),
        action("DoNothing"),
        next_node="AccountProfileCityUnlockDone",
        on_error="AccountProfileCityUnlockDone",
    )
    pipeline["AccountProfileCityUnlockDone"] = node(
        reco("DirectHit"),
        action("DoNothing"),
    )
    return pipeline


def main() -> None:
    pipeline = generate_pipeline()
    PIPELINE_PATH.write_text(
        json.dumps(pipeline, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {PIPELINE_PATH} ({len(pipeline)} nodes)")


if __name__ == "__main__":
    main()

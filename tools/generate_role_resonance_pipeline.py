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
    / "account_profile_role_resonance.json"
)

CREW_WAREHOUSE_ENTRY_TARGET = [1225, 58]
CREW_WAREHOUSE_TEXTS = ["乘员仓库", "获取时间", "稀有度", "共振", "等级", "筛选"]
CREW_SORT_ROI = [0, 0, 1260, 140]
CREW_LIST_ROI = [0, 80, 1260, 615]
CREW_SCROLL_START = [920, 620]
CREW_SCROLL_END = [920, 500]
CREW_SCROLL_DURATION = 520
CREW_SCROLL_POST_DELAY = 500
CREW_SCAN_PAGE_COUNT = 24
CREW_STALE_PAGE_LIMIT = 2


def load_role_names() -> list[str]:
    path = PROJECT_ROOT / "resources" / "goods" / "RoleCatalog2026.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    roles = data.get("roles") if isinstance(data, dict) else []
    if not isinstance(roles, list):
        return []
    return [str(role).strip() for role in roles if str(role).strip()]


def recognition(kind: str, param: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"recognition": kind}
    if param:
        data.update(param)
    return data


def action(kind: str, param: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"action": kind}
    if param:
        data.update(param)
    return data


def node(
    recognition_type: str | None,
    action_type: str | None,
    *,
    recognition_param: dict[str, Any] | None = None,
    action_param: dict[str, Any] | None = None,
    next_node: str | list[str] | None = None,
    on_error: str | list[str] | None = None,
    post_delay: int | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if recognition_type is not None:
        data.update(recognition(recognition_type, recognition_param))
    if action_type is not None:
        data.update(action(action_type, action_param))
    if post_delay is not None:
        data["post_delay"] = post_delay
    if timeout is not None:
        data["timeout"] = timeout
    if next_node is not None:
        data["next"] = next_node if isinstance(next_node, list) else [next_node]
    if on_error is not None:
        data["on_error"] = on_error if isinstance(on_error, list) else [on_error]
    return data


def custom_action(name: str, param: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"custom_action": name}
    if param:
        data["custom_action_param"] = param
    return data


def generate_pipeline() -> dict[str, Any]:
    pipeline: dict[str, Any] = {}
    pipeline["AccountProfileRoleResonanceStart"] = node(
        "TemplateMatch",
        "Click",
        recognition_param={"template": "main_map.png", "threshold": 0.96},
        action_param={"target": CREW_WAREHOUSE_ENTRY_TARGET},
        post_delay=600,
        next_node="AccountProfileRoleResonanceWarehouseReady",
    )
    pipeline["AccountProfileRoleResonanceWarehouseReady"] = node(
        "OCR",
        "Custom",
        recognition_param={"expected": CREW_WAREHOUSE_TEXTS},
        action_param=custom_action("profile_crew_warehouse_ready"),
        next_node="AccountProfileRoleResonanceSortReady001",
        on_error="AccountProfileRoleResonanceConfirmPopup",
    )
    pipeline["AccountProfileRoleResonanceConfirmPopup"] = node(
        "OCR",
        "Click",
        recognition_param={"expected": ["确认", "确定"], "roi": [300, 240, 680, 320]},
        post_delay=400,
        next_node="AccountProfileRoleResonanceWarehouseReadyAfterConfirm",
    )
    pipeline["AccountProfileRoleResonanceWarehouseReadyAfterConfirm"] = node(
        "OCR",
        "Custom",
        recognition_param={"expected": CREW_WAREHOUSE_TEXTS},
        action_param=custom_action("profile_crew_warehouse_ready"),
        next_node="AccountProfileRoleResonanceSortReady001",
    )

    for attempt in range(1, 4):
        sort_node = f"AccountProfileRoleResonanceSortReady{attempt:03d}"
        wait_node = f"AccountProfileRoleResonanceSortWait{attempt:03d}"
        next_sort_node = f"AccountProfileRoleResonanceSortReady{attempt + 1:03d}"
        fallback_node = next_sort_node if attempt < 3 else "AccountProfileRoleResonancePageOcr001"
        pipeline[sort_node] = node(
            "OCR",
            "Custom",
            recognition_param={"expected": ["获取时间"], "roi": CREW_SORT_ROI},
            action_param=custom_action(
                "profile_crew_sort_ready",
                {
                    "attempt": attempt,
                    "max_attempts": 3,
                },
            ),
            post_delay=500,
            next_node="AccountProfileRoleResonancePageOcr001",
            on_error=wait_node if attempt < 3 else "AccountProfileRoleResonancePageOcr001",
        )
        if attempt < 3:
            pipeline[wait_node] = node(
                "DirectHit",
                "DoNothing",
                post_delay=700,
                next_node=fallback_node,
            )

    for index in range(1, CREW_SCAN_PAGE_COUNT + 1):
        page_node = f"AccountProfileRoleResonancePageOcr{index:03d}"
        continue_node = f"AccountProfileRoleResonanceContinue{index:03d}"
        scroll_node = f"AccountProfileRoleResonanceScroll{index:03d}"
        next_page_node = f"AccountProfileRoleResonancePageOcr{index + 1:03d}"
        is_last_page = index >= CREW_SCAN_PAGE_COUNT
        next_after_page = "AccountProfileRoleResonanceComplete" if is_last_page else continue_node
        pipeline[page_node] = node(
            "OCR",
            "Custom",
            recognition_param={
                "expected": "",
                "roi": CREW_LIST_ROI,
            },
            action_param=custom_action(
                "profile_role_resonance_page_read",
                {
                    "page_index": index,
                    "role_targets": [],
                },
            ),
            next_node=next_after_page,
            on_error=next_after_page,
            timeout=10000,
        )
        if not is_last_page:
            pipeline[continue_node] = node(
                "DirectHit",
                "Custom",
                action_param=custom_action(
                    "profile_role_resonance_should_continue",
                    {
                        "page_index": index,
                        "role_targets": [],
                        "stale_limit": CREW_STALE_PAGE_LIMIT,
                        "max_pages": CREW_SCAN_PAGE_COUNT,
                    },
                ),
                next_node=scroll_node,
                on_error="AccountProfileRoleResonanceComplete",
            )
            pipeline[scroll_node] = node(
                "DirectHit",
                "Swipe",
                action_param={
                    "begin": CREW_SCROLL_START,
                    "end": CREW_SCROLL_END,
                    "duration": CREW_SCROLL_DURATION,
                },
                post_delay=CREW_SCROLL_POST_DELAY,
                next_node=next_page_node,
            )

    pipeline["AccountProfileRoleResonanceComplete"] = node(
        "DirectHit",
        "Custom",
        action_param=custom_action("profile_role_resonance_complete", {"role_targets": []}),
        next_node="AccountProfileRoleResonanceReturnHome",
    )
    pipeline["AccountProfileRoleResonanceReturnHome"] = node(
        "TemplateMatch",
        "Click",
        recognition_param={"template": "go_home.png", "roi": [154, 9, 89, 58], "threshold": 0.90},
        post_delay=300,
        next_node="AccountProfileRoleResonanceMainMapReady",
        on_error="AccountProfileRoleResonanceDone",
    )
    pipeline["AccountProfileRoleResonanceMainMapReady"] = node(
        "TemplateMatch",
        "DoNothing",
        recognition_param={"template": "main_map.png", "threshold": 0.96},
        next_node="AccountProfileRoleResonanceDone",
        on_error="AccountProfileRoleResonanceDone",
    )
    pipeline["AccountProfileRoleResonanceDone"] = node("DirectHit", "DoNothing")
    return pipeline


def main() -> None:
    pipeline = generate_pipeline()
    PIPELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PIPELINE_PATH.write_text(json.dumps(pipeline, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    print(f"wrote {PIPELINE_PATH} ({len(pipeline)} nodes)")


if __name__ == "__main__":
    main()

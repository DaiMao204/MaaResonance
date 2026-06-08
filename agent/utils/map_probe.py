from __future__ import annotations

import os
import re
import time
import traceback
from math import hypot
from typing import Any

from maa.context import Context

from maa_resonance.logic.map_locator import destination_text_match_score
from maa_resonance.logic.map_locator import detect_station_icon_candidate_types
from maa_resonance.logic.map_locator import is_navigation_target_safe
from maa_resonance.logic.map_locator import is_valid_map_point
from maa_resonance.logic.map_locator import label_probe_points_from_box
from maa_resonance.logic.map_locator import locate_map_view
from maa_resonance.logic.map_locator import locate_map_view_from_candidates
from maa_resonance.logic.map_locator import map_probe_offsets
from maa_resonance.logic.map_locator import navigation_target_near_safe
from maa_resonance.logic.map_locator import project_station
from maa_resonance.logic.map_locator import projected_target_drag_plan
from maa_resonance.logic.map_locator import rounded_point
from maa_resonance.logic.map_locator import station_icon_kind
from maa_resonance.logic.map_locator import station_by_name

from .recognition import _box_center_point
from .recognition import _box_xywh
from .recognition import _recognition_result_items
from .recognition import _recognition_score
from .recognition import _recognition_text


DESTINATION_TITLE_ALIASES = {
    "澄明数据中心": ["澄明数据中心", "澄明数据", "数据中心", "澄明"],
    "云岫桥基地": ["云岫桥基地", "云桥基地", "岫桥基地", "云岫桥"],
    "阿妮塔能源研究所": ["阿妮塔能源研究所", "能源研究所", "阿妮塔能源"],
    "阿妮塔战备工厂": ["阿妮塔战备工厂", "战备工厂", "阿妮塔战备"],
    "阿妮塔发射中心": ["阿妮塔发射中心", "发射中心", "阿妮塔发射"],
}


def _int_param(params: dict[str, Any], key: str, default: int) -> int:
    try:
        value = params.get(key)
        if value not in (None, ""):
            return int(value)
    except (TypeError, ValueError):
        pass
    return default


def controller_screencap_image(context: Context) -> Any | None:
    try:
        job = context.tasker.controller.post_screencap().wait()
        if not getattr(job, "succeeded", False):
            return None
        return job.get()
    except Exception:
        return getattr(context.tasker.controller, "cached_image", None)


def _slow_drag_duration(distance: int, duration: int) -> int:
    return max(duration, min(1200, max(750, int(round(distance * 4.0)))))


def _route_map_brake_tap(
    context: Context,
    main_begin: tuple[int, int],
    main_end: tuple[int, int],
) -> dict[str, Any] | None:
    dx = main_end[0] - main_begin[0]
    dy = main_end[1] - main_begin[1]
    if not dx and not dy:
        return None

    time.sleep(0.08)
    point = (640, 360)
    context.tasker.controller.post_click(point[0], point[1]).wait()
    time.sleep(0.16)
    return {"point": list(point)}


def swipe_route_map_direction(context: Context, direction: str, distance: int, duration: int = 900) -> dict[str, Any]:
    duration = _slow_drag_duration(distance, duration)
    if direction == "east":
        begin, end = (900, 360), (900 - distance, 360)
    elif direction == "west":
        begin, end = (360, 360), (360 + distance, 360)
    elif direction == "south":
        begin, end = (640, 520), (640, 520 - distance)
    elif direction == "north":
        begin, end = (640, 220), (640, 220 + distance)
    else:
        raise ValueError(f"Unsupported map drag direction: {direction}")
    context.tasker.controller.post_swipe(begin[0], begin[1], end[0], end[1], duration).wait()
    return {
        "begin": list(begin),
        "end": list(end),
        "distance": distance,
        "duration": duration,
        "brake": _route_map_brake_tap(context, begin, end),
    }


def destination_panel_title_hit(context: Context, image: Any, destination_city: str) -> bool:
    if image is None:
        return False
    expected = DESTINATION_TITLE_ALIASES.get(destination_city, [destination_city])
    detail = context.run_recognition(
        "DestinationCoordinatePanelVerify",
        image,
        {
            "DestinationCoordinatePanelVerify": {
                "recognition": "OCR",
                "expected": [re.escape(item) for item in expected],
                "roi": [690, 80, 560, 95],
                "action": "DoNothing",
            }
        },
    )
    return bool(detail and detail.hit)


def destination_detail_panel_hit(context: Context, image: Any) -> bool:
    if image is None:
        return False
    detail = context.run_recognition(
        "DestinationCoordinatePanelPresence",
        image,
        {
            "DestinationCoordinatePanelPresence": {
                "recognition": "OCR",
                "expected": ["发展度", "声望", "推荐等级", "交易品", "路程"],
                "roi": [680, 80, 580, 540],
                "action": "DoNothing",
            }
        },
    )
    return bool(detail and detail.hit)


def close_destination_detail_panel(context: Context, image: Any) -> bool:
    if not destination_detail_panel_hit(context, image):
        return False
    context.tasker.controller.post_click(80, 360).wait()
    time.sleep(0.55)
    return True


def destination_visible_text_probe(
    context: Context,
    image: Any,
    destination_city: str,
    limit: int = 4,
) -> dict[str, Any]:
    """坐标投影点未确认时，复用 Maa OCR 在当前视口补扫目标文字。"""
    result: dict[str, Any] = {"ok": False, "candidates": []}
    if image is None or not destination_city:
        result["reason"] = "missing_image_or_destination"
        return result

    detail = context.run_recognition(
        "DestinationCoordinateVisibleTextProbe",
        image,
        {
            "DestinationCoordinateVisibleTextProbe": {
                "recognition": "OCR",
                "expected": "",
                "roi": [0, 80, 1280, 520],
                "action": "DoNothing",
            }
        },
    )
    entries: list[dict[str, Any]] = []
    for item in _recognition_result_items(detail):
        text = _recognition_text(item)
        box = getattr(item, "box", None)
        if box is None and isinstance(item, dict):
            box = item.get("box")
        xywh = _box_xywh(box)
        if not text or not xywh:
            continue
        score = destination_text_match_score(text, destination_city)
        if score < 0.62:
            continue
        x, y, width, height = xywh
        if not (0 <= x < 1280 and 80 <= y <= 620):
            continue
        entries.append(
            {
                "text": text,
                "score": round(score, 3),
                "ocr_score": round(_recognition_score(item), 3),
                "box": [x, y, width, height],
                "points": [list(point) for point in label_probe_points_from_box(box)],
            }
        )

    entries.sort(key=lambda item: (-float(item["score"]), -float(item["ocr_score"]), item["box"][1], item["box"][0]))
    result["candidates"] = entries[:limit]
    if not entries:
        result["reason"] = "target_text_not_visible"
        return result

    for entry in entries[:limit]:
        probe_results: list[dict[str, Any]] = []
        entry["probes"] = probe_results
        for point_value in entry.get("points") or []:
            probe_point = (int(point_value[0]), int(point_value[1]))
            if not is_valid_map_point(probe_point):
                continue
            context.tasker.controller.post_click(probe_point[0], probe_point[1]).wait()
            time.sleep(0.65)
            verify_image = controller_screencap_image(context)
            verified = destination_panel_title_hit(context, verify_image, destination_city)
            panel_closed = False
            if not verified:
                panel_closed = close_destination_detail_panel(context, verify_image)
            probe_results.append(
                {
                    "point": list(probe_point),
                    "verified": verified,
                    "panel_closed": panel_closed,
                }
            )
            if verified:
                result.update(
                    {
                        "ok": True,
                        "reason": "visible_text_verified",
                        "text": entry["text"],
                        "click": list(probe_point),
                    }
                )
                return result

    result["reason"] = "visible_text_not_verified"
    return result


def _dedupe_points(points: list[tuple[int, int]], min_distance: int = 10) -> list[tuple[int, int]]:
    unique: list[tuple[int, int]] = []
    for point in points:
        if all(abs(point[0] - old[0]) > min_distance or abs(point[1] - old[1]) > min_distance for old in unique):
            unique.append(point)
    return unique


def _typed_candidate_probe_points(
    station: Any,
    target_point: tuple[int, int],
    candidates: list[tuple[int, int]],
    candidate_types: dict[tuple[int, int], str],
    *,
    max_distance: int = 120,
    limit: int = 3,
) -> list[tuple[int, int]]:
    station_kind = station_icon_kind(station)
    if not station_kind:
        return []
    ranked: list[tuple[float, tuple[int, int]]] = []
    for candidate in candidates:
        if candidate_types.get(candidate) != station_kind:
            continue
        distance = hypot(candidate[0] - target_point[0], candidate[1] - target_point[1])
        if distance <= max_distance:
            ranked.append((distance, candidate))
    ranked.sort(key=lambda item: item[0])

    points: list[tuple[int, int]] = []
    for _, candidate in ranked[:limit]:
        points.extend(
            [
                candidate,
                (candidate[0], candidate[1] - 18),
                (candidate[0], candidate[1] + 18),
            ]
        )
    return [point for point in _dedupe_points(points) if is_valid_map_point(point)]


def _projected_fallback_probe_points(point: tuple[int, int]) -> list[tuple[int, int]]:
    return [probe_point for probe_point in map_probe_offsets(point)[:2] if is_valid_map_point(probe_point)]


def _near_typed_candidates(
    station: Any,
    target_point: tuple[int, int],
    candidates: list[tuple[int, int]],
    candidate_types: dict[tuple[int, int], str],
    *,
    max_distance: int = 420,
    limit: int = 8,
) -> list[dict[str, Any]]:
    station_kind = station_icon_kind(station)
    if not station_kind:
        return []
    ranked: list[tuple[float, tuple[int, int]]] = []
    for candidate in candidates:
        if candidate_types.get(candidate) != station_kind:
            continue
        distance = hypot(candidate[0] - target_point[0], candidate[1] - target_point[1])
        if distance <= max_distance:
            ranked.append((distance, candidate))
    ranked.sort(key=lambda item: item[0])
    return [
        {"point": [point[0], point[1]], "distance": round(distance, 1)}
        for distance, point in ranked[:limit]
    ]


def maa_color_station_candidates(
    context: Context,
    image: Any,
) -> tuple[list[tuple[int, int]], dict[tuple[int, int], str], list[dict[str, Any]]]:
    """用 Maa ColorMatch 提取地图站点图标候选点，再交给坐标拟合。"""
    if image is None:
        return [], {}, []
    color_ranges = [
        ("gold", "gold", [15, 185, 150], [35, 255, 255], 45, 260, 7, 28),
        ("cyan", "cyan", [82, 150, 125], [125, 255, 255], 45, 260, 7, 28),
        ("red_low", "red", [0, 170, 135], [8, 255, 255], 25, 160, 6, 20),
        ("red_high", "red", [172, 170, 135], [179, 255, 255], 25, 160, 6, 20),
    ]
    candidates: list[tuple[int, int]] = []
    candidate_types: dict[tuple[int, int], str] = {}
    stats: list[dict[str, Any]] = []
    for name, candidate_kind, lower, upper, min_count, max_count, min_size, max_size in color_ranges:
        detail = context.run_recognition(
            f"DestinationCoordinateStationIcon{name}",
            image,
            {
                f"DestinationCoordinateStationIcon{name}": {
                    "recognition": "ColorMatch",
                    "method": 40,
                    "roi": [0, 90, 1280, 615],
                    "lower": [lower],
                    "upper": [upper],
                    "count": min_count,
                    "connected": True,
                    "order_by": "Area",
                    "action": "DoNothing",
                }
            },
        )
        if not detail:
            stats.append({"name": name, "detail": False, "hit": False, "result_count": 0, "accepted": 0})
            continue
        results = _recognition_result_items(detail)
        accepted = 0
        sample_results: list[dict[str, Any]] = []
        for item in results:
            box = getattr(item, "box", None)
            count = int(getattr(item, "count", 0) or 0)
            if isinstance(item, dict):
                box = item.get("box", box)
                count = int(item.get("count", count) or 0)
            if not box:
                continue
            xywh = _box_xywh(box)
            if not xywh:
                continue
            x, y, width, height = xywh
            if len(sample_results) < 8:
                sample_results.append(
                    {
                        "box": [x, y, width, height],
                        "count": count,
                    }
                )
            if not (min_count <= count <= max_count and min_size <= width <= max_size and min_size <= height <= max_size):
                continue
            point = _box_center_point(box)
            if not is_valid_map_point(point):
                continue
            if all(abs(point[0] - old[0]) > 18 or abs(point[1] - old[1]) > 18 for old in candidates):
                candidates.append(point)
                candidate_types[point] = candidate_kind
                accepted += 1
        stats.append(
            {
                "name": name,
                "detail": True,
                "hit": bool(getattr(detail, "hit", False)),
                "result_count": len(results),
                "accepted": accepted,
                "samples": sample_results,
            }
        )
    candidates = sorted(candidates, key=lambda point: (point[1], point[0]))
    return candidates, candidate_types, stats


def map_station_candidates(
    context: Context,
    image: Any,
    array: Any,
    station: Any,
) -> dict[str, Any]:
    """优先用本地像素候选拟合地图，必要时回退到 Maa ColorMatch。"""
    local_candidates, local_candidate_types = detect_station_icon_candidate_types(array)
    local_location = locate_map_view_from_candidates(
        local_candidates,
        candidate_types=local_candidate_types,
        target_station=station,
    )

    maa_candidates: list[tuple[int, int]] = []
    maa_candidate_types: dict[tuple[int, int], str] = {}
    maa_color_stats: list[dict[str, Any]] = []
    need_maa = local_location is None or os.environ.get("MAA_RESONANCE_USE_MAA_COLOR") == "1"
    if need_maa:
        maa_candidates, maa_candidate_types, maa_color_stats = maa_color_station_candidates(context, image)
        maa_location = locate_map_view_from_candidates(
            maa_candidates,
            candidate_types=maa_candidate_types,
            target_station=station,
        )
        if maa_location is not None:
            return {
                "source": "maa_color",
                "candidates": maa_candidates,
                "candidate_types": maa_candidate_types,
                "location": maa_location,
                "local_candidate_count": len(local_candidates),
                "maa_candidate_count": len(maa_candidates),
                "maa_color_stats": maa_color_stats,
                "fallback_candidates": [],
            }

    fallback_candidates: list[list[int]] = []
    if local_location is None:
        fallback_location = locate_map_view(array)
        if fallback_location is not None:
            local_location = fallback_location
            fallback_candidates = [list(point) for point in fallback_location.candidates[:16]]

    return {
        "source": "local_numpy" if fallback_candidates == [] else "local_numpy_untyped",
        "candidates": local_candidates,
        "candidate_types": local_candidate_types,
        "location": local_location,
        "local_candidate_count": len(local_candidates),
        "maa_candidate_count": len(maa_candidates),
        "maa_color_stats": maa_color_stats,
        "fallback_candidates": fallback_candidates,
    }


def destination_map_vicinity_probe(context: Context, params: dict[str, Any]) -> dict[str, Any]:
    """把路线图拖到目标城市附近，并验证性地点选目标城市。"""
    destination_city = str(params.get("destination_city") or params.get("city") or "").strip()
    max_steps = max(1, _int_param(params, "max_steps", 3))
    drag_distance = max(120, _int_param(params, "drag_distance", 520))
    drag_duration = max(120, _int_param(params, "drag_duration", 500))
    drag_delay = max(0, _int_param(params, "drag_delay", 200)) / 1000
    click_count = max(1, min(8, _int_param(params, "click_count", 5)))
    click_delay = max(0, _int_param(params, "click_delay", 200)) / 1000
    panel_settle_delay = max(click_delay, _int_param(params, "panel_settle_delay", 500) / 1000)
    attempts: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "ok": False,
        "destination_city": destination_city,
        "mode": "vicinity",
        "max_steps": max_steps,
        "drag_distance": drag_distance,
        "attempts": attempts,
    }
    if not destination_city:
        result["reason"] = "missing_destination_city"
        return result

    try:
        import numpy as np

        station = station_by_name(destination_city)
        if station is None:
            result["reason"] = "station_without_world_coordinate"
            return result

        last_target_point: tuple[int, int] | None = None
        for step in range(1, max_steps + 1):
            image = controller_screencap_image(context)
            if image is None:
                result["reason"] = "screencap_failed"
                return result
            array = np.ascontiguousarray(np.asarray(image)[:, :, :3])
            if array.ndim != 3 or array.shape[2] < 3:
                result["reason"] = "invalid_screenshot"
                result["shape"] = list(array.shape)
                return result

            location_data = map_station_candidates(context, array, array, station)
            station_candidates = location_data["candidates"]
            candidate_types = location_data["candidate_types"]
            location = location_data["location"]
            fallback_candidates = location_data["fallback_candidates"]

            attempt: dict[str, Any] = {
                "step": step,
                "candidate_count": len(station_candidates) or len(fallback_candidates),
                "candidate_source": location_data["source"],
                "local_color_candidate_count": location_data["local_candidate_count"],
                "maa_color_candidate_count": location_data["maa_candidate_count"],
                "match_count": 0,
                "numpy_fallback_candidate_count": len(fallback_candidates),
                "numpy_fallback_candidates": fallback_candidates,
            }
            if os.environ.get("MAA_RESONANCE_MAP_LOCATE_DEBUG") == "1" or (not station_candidates and location is None):
                attempt["color_stats"] = location_data["maa_color_stats"]
            if location is None:
                attempt["reason"] = "locate_map_failed"
                attempts.append(attempt)
                result["reason"] = "locate_map_failed"
                return result

            target_point = rounded_point(project_station(station, location))
            safe = is_navigation_target_safe(target_point)
            attempt.update(
                {
                    "target_point": list(target_point),
                    "safe": safe,
                    "station_kind": station_icon_kind(station),
                    "typed_candidates_near_target": _near_typed_candidates(
                        station,
                        target_point,
                        station_candidates,
                        candidate_types,
                    ),
                    "candidate_count": len(location.candidates),
                    "match_count": location.match_count,
                    "mean_error": location.mean_error,
                    "scale": location.scale,
                    "matches": [match.name for match in location.matches[:8]],
                }
            )

            typed_probe_points = _typed_candidate_probe_points(station, target_point, station_candidates, candidate_types)
            can_probe_target = safe or bool(typed_probe_points)
            if can_probe_target:
                clicked_points: list[list[int]] = []
                probe_results: list[dict[str, Any]] = []
                probe_points = _dedupe_points(
                    [
                        *typed_probe_points,
                        *(_projected_fallback_probe_points(target_point) if safe else []),
                    ]
                )
                attempt["probe_source"] = "typed_candidate" if not safe else "projected_or_typed"
                for probe_point in probe_points:
                    if len(clicked_points) >= click_count:
                        break
                    if not is_valid_map_point(probe_point):
                        continue
                    context.tasker.controller.post_click(probe_point[0], probe_point[1]).wait()
                    clicked_points.append([probe_point[0], probe_point[1]])
                    time.sleep(panel_settle_delay)
                    verify_image = controller_screencap_image(context)
                    verified = destination_panel_title_hit(context, verify_image, destination_city)
                    panel_closed = False
                    if not verified:
                        panel_closed = close_destination_detail_panel(context, verify_image)
                    probe_results.append(
                        {
                            "point": [probe_point[0], probe_point[1]],
                            "verified": verified,
                            "panel_closed": panel_closed,
                        }
                    )
                    if verified:
                        attempt["reason"] = "target_visible_verified"
                        attempt["clicked_points"] = clicked_points
                        attempt["probe_results"] = probe_results
                        attempts.append(attempt)
                        result.update(
                            {
                                "ok": True,
                                "reason": "target_visible_verified",
                                "target_point": list(target_point),
                                "clicked_points": clicked_points,
                                "verified_click": [probe_point[0], probe_point[1]],
                            }
                        )
                        return result

                attempt["reason"] = "target_visible_not_verified"
                attempt["clicked_points"] = clicked_points
                attempt["probe_results"] = probe_results
                visible_probe = destination_visible_text_probe(
                    context,
                    controller_screencap_image(context),
                    destination_city,
                )
                attempt["visible_text_probe"] = visible_probe
                attempts.append(attempt)
                if visible_probe.get("ok"):
                    result.update(
                        {
                            "ok": True,
                            "reason": "visible_text_after_projected_probe",
                            "target_point": list(target_point),
                            "clicked_points": clicked_points,
                            "click": visible_probe.get("click"),
                        }
                    )
                    return result
                result["reason"] = "target_visible_not_verified"
                result["target_point"] = list(target_point)
                result["clicked_points"] = clicked_points
                return result

            if last_target_point is not None:
                movement = ((target_point[0] - last_target_point[0]) ** 2 + (target_point[1] - last_target_point[1]) ** 2) ** 0.5
                attempt["movement"] = round(movement, 2)
                if movement < 18:
                    attempt["reason"] = "map_drag_stalled"
                    attempts.append(attempt)
                    result["reason"] = "map_drag_stalled"
                    result["target_point"] = list(target_point)
                    return result
            last_target_point = target_point

            plan = projected_target_drag_plan(target_point, drag_distance=drag_distance)
            if not plan:
                attempt["reason"] = "drag_plan_unavailable"
                attempts.append(attempt)
                result["reason"] = "drag_plan_unavailable"
                result["target_point"] = list(target_point)
                return result

            direction, distance = plan
            attempt["drag"] = {"direction": direction, "distance": distance}
            attempts.append(attempt)
            attempt["drag"]["swipe"] = swipe_route_map_direction(
                context,
                direction,
                distance,
                duration=drag_duration,
            )
            time.sleep(drag_delay)

        result["reason"] = "max_steps_reached"
        if last_target_point is not None:
            result["target_point"] = list(last_target_point)
        return result
    except Exception as exc:
        result["reason"] = "exception"
        result["error"] = str(exc)
        result["traceback"] = traceback.format_exc(limit=8)
        return result


def destination_map_coordinate_probe(context: Context, params: dict[str, Any]) -> dict[str, Any]:
    """用旧项目的地图坐标拟合逻辑，先尝试一步到位选中目的地。"""
    destination_city = str(params.get("destination_city") or params.get("city") or "").strip()
    max_steps = max(1, _int_param(params, "max_steps", 6))
    drag_distance = max(120, _int_param(params, "drag_distance", 520))
    attempts: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "ok": False,
        "destination_city": destination_city,
        "max_steps": max_steps,
        "drag_distance": drag_distance,
        "attempts": attempts,
    }
    if not destination_city:
        result["reason"] = "missing_destination_city"
        return result

    try:
        import numpy as np

        station = station_by_name(destination_city)
        if station is None:
            result["reason"] = "station_without_world_coordinate"
            return result

        last_target_point: tuple[int, int] | None = None
        stalled_steps = 0
        for step in range(1, max_steps + 1):
            image = controller_screencap_image(context)
            if image is None:
                result["reason"] = "screencap_failed"
                return result
            if destination_panel_title_hit(context, image, destination_city):
                result.update(
                    {
                        "ok": True,
                        "reason": "existing_target_panel",
                    }
                )
                return result
            if close_destination_detail_panel(context, image):
                image = controller_screencap_image(context)
                if image is None:
                    result["reason"] = "screencap_failed_after_close_panel"
                    return result
            visible_probe = destination_visible_text_probe(context, image, destination_city)
            if visible_probe.get("ok"):
                result.update(
                    {
                        "ok": True,
                        "reason": "visible_text_before_projected_probe",
                        "click": visible_probe.get("click"),
                    }
                )
                return result
            array = np.ascontiguousarray(np.asarray(image)[:, :, :3])
            if array.ndim != 3 or array.shape[2] < 3:
                result["reason"] = "invalid_screenshot"
                result["shape"] = list(array.shape)
                return result

            location_data = map_station_candidates(context, array, array, station)
            station_candidates = location_data["candidates"]
            candidate_types = location_data["candidate_types"]
            location = location_data["location"]
            fallback_candidates = location_data["fallback_candidates"]
            attempt: dict[str, Any] = {
                "step": step,
                "candidate_count": len(station_candidates) or len(fallback_candidates),
                "candidate_source": location_data["source"],
                "local_color_candidate_count": location_data["local_candidate_count"],
                "maa_color_candidate_count": location_data["maa_candidate_count"],
                "match_count": 0,
                "numpy_fallback_candidate_count": len(fallback_candidates),
                "numpy_fallback_candidates": fallback_candidates,
            }
            if os.environ.get("MAA_RESONANCE_MAP_LOCATE_DEBUG") == "1" or (not station_candidates and location is None):
                attempt["color_stats"] = location_data["maa_color_stats"]
            if location is None:
                attempt["reason"] = "locate_map_failed"
                if last_target_point and navigation_target_near_safe(last_target_point):
                    visible_probe = destination_visible_text_probe(context, image, destination_city)
                    attempt["visible_text_probe"] = visible_probe
                    if visible_probe.get("ok"):
                        attempts.append(attempt)
                        result.update(
                            {
                                "ok": True,
                                "reason": "visible_text_after_locate_lost",
                                "click": visible_probe.get("click"),
                            }
                        )
                        return result
                attempts.append(attempt)
                result["reason"] = "locate_map_failed"
                return result

            target_point = rounded_point(project_station(station, location))
            safe = is_navigation_target_safe(target_point)
            attempt.update(
                {
                    "target_point": list(target_point),
                    "safe": safe,
                    "candidate_count": len(location.candidates),
                    "match_count": location.match_count,
                    "mean_error": location.mean_error,
                    "scale": location.scale,
                    "matches": [match.name for match in location.matches[:8]],
                }
            )

            if last_target_point is not None:
                movement = ((target_point[0] - last_target_point[0]) ** 2 + (target_point[1] - last_target_point[1]) ** 2) ** 0.5
                attempt["movement"] = round(movement, 2)
                if movement < 24 and not safe:
                    stalled_steps += 1
                else:
                    stalled_steps = 0
                if stalled_steps >= 2:
                    attempt["reason"] = "map_drag_stalled"
                    attempts.append(attempt)
                    result["reason"] = "map_drag_stalled"
                    return result
            last_target_point = target_point

            if safe:
                typed_probe_points = _typed_candidate_probe_points(
                    station,
                    target_point,
                    station_candidates,
                    candidate_types,
                    max_distance=110,
                    limit=2,
                )
                target_kind = station_icon_kind(station)
                same_kind_candidates = [
                    candidate for candidate in station_candidates if candidate_types.get(candidate) == target_kind
                ] if target_kind else []
                if typed_probe_points:
                    probe_points = typed_probe_points
                    attempt["probe_source"] = "typed_candidate"
                elif target_kind and same_kind_candidates:
                    visible_probe = destination_visible_text_probe(context, image, destination_city)
                    attempt["visible_text_probe"] = visible_probe
                    attempt["near_typed_candidates"] = _near_typed_candidates(
                        station,
                        target_point,
                        station_candidates,
                        candidate_types,
                    )
                    if visible_probe.get("ok"):
                        attempts.append(attempt)
                        result.update(
                            {
                                "ok": True,
                                "reason": "visible_text_without_near_typed_candidate",
                                "click": visible_probe.get("click"),
                            }
                        )
                        return result
                    attempt["reason"] = "target_kind_candidate_not_near_projected_point"
                    attempts.append(attempt)
                    result["reason"] = "target_kind_candidate_not_near_projected_point"
                    return result
                else:
                    probe_points = _projected_fallback_probe_points(target_point)
                    attempt["probe_source"] = "projected_fallback"
                attempt["typed_probe_points"] = [list(point) for point in typed_probe_points]
                probe_results: list[dict[str, Any]] = []
                attempt["probes"] = probe_results
                for probe_point in probe_points:
                    context.tasker.controller.post_click(probe_point[0], probe_point[1]).wait()
                    time.sleep(0.75)
                    verify_image = controller_screencap_image(context)
                    verified = destination_panel_title_hit(context, verify_image, destination_city)
                    panel_closed = False
                    if not verified:
                        panel_closed = close_destination_detail_panel(context, verify_image)
                    probe_results.append(
                        {
                            "point": list(probe_point),
                            "verified": verified,
                            "panel_closed": panel_closed,
                        }
                    )
                    if verified:
                        attempt["clicked"] = True
                        attempt["verified"] = True
                        attempts.append(attempt)
                        result.update(
                            {
                                "ok": True,
                                "reason": "verified_projected_station",
                                "click": list(probe_point),
                            }
                        )
                        return result

                attempt["clicked"] = True
                attempt["verified"] = False
                visible_probe = destination_visible_text_probe(context, controller_screencap_image(context), destination_city)
                attempt["visible_text_probe"] = visible_probe
                if visible_probe.get("ok"):
                    attempts.append(attempt)
                    result.update(
                        {
                            "ok": True,
                            "reason": "visible_text_after_projected_probe",
                            "click": visible_probe.get("click"),
                        }
                    )
                    return result
                attempt["reason"] = "projected_station_not_verified"
                attempts.append(attempt)
                result["reason"] = "projected_station_not_verified"
                return result

            plan = projected_target_drag_plan(target_point, drag_distance=drag_distance)
            if not plan:
                attempt["reason"] = "drag_plan_unavailable"
                attempts.append(attempt)
                result["reason"] = "drag_plan_unavailable"
                return result

            direction, distance = plan
            attempt["drag"] = {"direction": direction, "distance": distance}
            attempts.append(attempt)
            attempt["drag"]["swipe"] = swipe_route_map_direction(context, direction, distance)
            time.sleep(0.7)

        result["reason"] = "max_steps_reached"
        if last_target_point and navigation_target_near_safe(last_target_point):
            visible_probe = destination_visible_text_probe(context, controller_screencap_image(context), destination_city)
            result["visible_text_probe"] = visible_probe
            if visible_probe.get("ok"):
                result.update(
                    {
                        "ok": True,
                        "reason": "visible_text_after_max_steps",
                        "click": visible_probe.get("click"),
                    }
                )
                return result
        return result
    except Exception as exc:
        result["reason"] = "exception"
        result["error"] = str(exc)
        result["traceback"] = traceback.format_exc(limit=8)
        return result

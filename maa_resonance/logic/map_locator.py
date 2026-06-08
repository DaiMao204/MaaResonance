from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from .paths import RESOURCES_PATH, read_json
from .profile_parser import clean_text


WORLD_PATH = RESOURCES_PATH / "map" / "CityWorld2026.json"
MAP_TOP = 90
MAP_BOTTOM = 705
SCREEN_WIDTH = 1280
ZOOM_X_MIN = 1120
ZOOM_X_MAX = 1185
ZOOM_Y_MIN = 320
MAIN_QUEST_X_MIN = 850
MAIN_QUEST_X_MAX = 1225
MAIN_QUEST_Y_MIN = 625
MAIN_QUEST_Y_MAX = 705

CALIBRATED_MAP_SCALE = 0.3325
ICON_KIND_BY_PATH = {
    "UI/MainUI/map_icon_station1": "gold",
    "UI/MainUI/map_icon_station2": "cyan",
    "UI/MainUI/map_icon_station3": "red",
}
CITY_ICON_AREA_MIN = 45
CITY_ICON_AREA_MAX = 220
CITY_ICON_SIZE_MIN = 7
CITY_ICON_SIZE_MAX = 24
NAV_TARGET_X_MIN = 140
NAV_TARGET_X_MAX = 1040
NAV_TARGET_Y_MIN = 140
NAV_TARGET_Y_MAX = 585
NAV_TARGET_CENTER_X = (NAV_TARGET_X_MIN + NAV_TARGET_X_MAX) // 2
NAV_TARGET_CENTER_Y = (NAV_TARGET_Y_MIN + NAV_TARGET_Y_MAX) // 2
MIN_COORDINATE_DRAG_DISTANCE = 120
MAX_COORDINATE_DRAG_DISTANCE = 240


@dataclass(frozen=True)
class WorldStation:
    id: int
    name: str
    x: float
    y: float
    map_icon_path: str
    attached_to_city: int
    is_open: bool
    is_ban_stop: bool


@dataclass(frozen=True)
class MapMatch:
    name: str
    world: tuple[float, float]
    projected: tuple[float, float]
    candidate: tuple[int, int]
    distance: float


@dataclass(frozen=True)
class MapLocateResult:
    scale: float
    tx: float
    ty: float
    score: float
    mean_error: float
    matches: tuple[MapMatch, ...]
    candidates: tuple[tuple[int, int], ...]

    @property
    def match_count(self) -> int:
        return len(self.matches)


@lru_cache(maxsize=1)
def load_world_stations() -> tuple[WorldStation, ...]:
    """读取地图世界坐标，坐标来自游戏 HomeStationFactory。"""
    data = read_json(WORLD_PATH, {})
    stations: list[WorldStation] = []
    for item in data.get("stations", []):
        stations.append(
            WorldStation(
                id=int(item["id"]),
                name=str(item["name"]),
                x=float(item["x"]),
                y=float(item["y"]),
                map_icon_path=str(item.get("map_icon_path", "")),
                attached_to_city=int(item.get("attached_to_city", -1)),
                is_open=bool(item.get("is_open")),
                is_ban_stop=bool(item.get("is_ban_stop")),
            )
        )
    return tuple(stations)


def station_by_name(name: str) -> WorldStation | None:
    for station in load_world_stations():
        if station.name == name:
            return station
    return None


def station_icon_kind(station: WorldStation) -> str | None:
    return ICON_KIND_BY_PATH.get(station.map_icon_path)


def project_world_point(x: float, y: float, scale: float, tx: float, ty: float) -> tuple[float, float]:
    return scale * x + tx, -scale * y + ty


def project_station(station: WorldStation, result: MapLocateResult) -> tuple[float, float]:
    return project_world_point(station.x, station.y, result.scale, result.tx, result.ty)


def rounded_point(point: tuple[float, float]) -> tuple[int, int]:
    return int(round(point[0])), int(round(point[1]))


def is_right_zoom_control(point: tuple[int, int]) -> bool:
    x, y = point
    return ZOOM_X_MIN <= x <= ZOOM_X_MAX and ZOOM_Y_MIN <= y <= MAP_BOTTOM


def is_main_quest_prompt(point: tuple[int, int]) -> bool:
    x, y = point
    return MAIN_QUEST_X_MIN <= x <= MAIN_QUEST_X_MAX and MAIN_QUEST_Y_MIN <= y <= MAIN_QUEST_Y_MAX


def is_valid_map_point(point: tuple[int, int]) -> bool:
    x, y = point
    return 0 <= x < SCREEN_WIDTH and MAP_TOP <= y <= MAP_BOTTOM and not is_right_zoom_control(point) and not is_main_quest_prompt(point)


def is_navigation_target_safe(point: tuple[int, int]) -> bool:
    x, y = point
    return NAV_TARGET_X_MIN <= x <= NAV_TARGET_X_MAX and NAV_TARGET_Y_MIN <= y <= NAV_TARGET_Y_MAX and is_valid_map_point(point)


def map_probe_offsets(point: tuple[int, int]) -> list[tuple[int, int]]:
    offsets = [(0, 0), (0, -28), (-24, -18), (24, -18), (-28, 0), (28, 0), (0, 24)]
    return [(point[0] + dx, point[1] + dy) for dx, dy in offsets]


def clamp_route_map_point(point: tuple[int, int]) -> tuple[int, int]:
    x, y = point
    return max(8, min(1272, int(x))), max(96, min(699, int(y)))


def dedupe_probe_points(points: list[tuple[int, int]], min_distance: int = 10) -> list[tuple[int, int]]:
    unique: list[tuple[int, int]] = []
    for point in points:
        if all(abs(point[0] - old[0]) > min_distance or abs(point[1] - old[1]) > min_distance for old in unique):
            unique.append(point)
    return unique


def destination_text_match_score(text: str, destination_city: str) -> float:
    raw = clean_text(text).replace(" ", "")
    target = clean_text(destination_city).replace(" ", "")
    if not raw or not target or not re.search(r"[\u4e00-\u9fff]", raw):
        return 0.0
    if raw == target:
        return 1.0
    if target in raw and len(raw) <= len(target) + 4:
        return 0.9
    if raw in target and len(raw) >= 2:
        return 0.75
    return difflib.SequenceMatcher(None, raw, target).ratio()


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


def label_probe_points_from_box(box: Any) -> list[tuple[int, int]]:
    x, y, width, height = _box_xywh(box) or (0, 0, 0, 0)
    center = (int(round(x + width / 2)), int(round(y + height / 2)))
    points: list[tuple[int, int]] = []
    for dx in (0, -12, 12):
        for dy in (-50, -38, -26, -14, -4):
            points.append(clamp_route_map_point((center[0] + dx, center[1] + dy)))
    return dedupe_probe_points(points)


def navigation_target_near_safe(point: tuple[int, int], margin: int = 320) -> bool:
    x, y = point
    return NAV_TARGET_X_MIN - margin <= x <= NAV_TARGET_X_MAX + margin and NAV_TARGET_Y_MIN - margin <= y <= NAV_TARGET_Y_MAX + margin


def _bgr_to_hsv(image: np.ndarray) -> np.ndarray:
    bgr = np.asarray(image)[:, :, :3].astype(np.float32) / 255.0
    b = bgr[:, :, 0]
    g = bgr[:, :, 1]
    r = bgr[:, :, 2]
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin

    hue = np.zeros_like(cmax)
    nonzero = delta > 1e-6
    r_max = nonzero & (cmax == r)
    g_max = nonzero & (cmax == g)
    b_max = nonzero & (cmax == b)
    hue[r_max] = ((g[r_max] - b[r_max]) / delta[r_max]) % 6
    hue[g_max] = ((b[g_max] - r[g_max]) / delta[g_max]) + 2
    hue[b_max] = ((r[b_max] - g[b_max]) / delta[b_max]) + 4

    saturation = np.zeros_like(cmax)
    positive = cmax > 1e-6
    saturation[positive] = delta[positive] / cmax[positive]

    hsv = np.empty_like(bgr, dtype=np.uint8)
    hsv[:, :, 0] = np.clip(np.rint(hue * 30), 0, 179).astype(np.uint8)
    hsv[:, :, 1] = np.clip(np.rint(saturation * 255), 0, 255).astype(np.uint8)
    hsv[:, :, 2] = np.clip(np.rint(cmax * 255), 0, 255).astype(np.uint8)
    return hsv


def _stable_map_mask(shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), dtype=bool)
    mask[MAP_TOP:MAP_BOTTOM, :] = True
    mask[ZOOM_Y_MIN:MAP_BOTTOM, ZOOM_X_MIN:ZOOM_X_MAX] = False
    mask[MAIN_QUEST_Y_MIN:MAIN_QUEST_Y_MAX, MAIN_QUEST_X_MIN:MAIN_QUEST_X_MAX] = False
    return mask


def _component_centers(
    mask: np.ndarray,
    *,
    area_min: int,
    area_max: int,
    size_min: int,
    size_max: int,
) -> list[tuple[int, int]]:
    height, width = mask.shape
    visited = np.zeros(mask.shape, dtype=bool)
    points: list[tuple[int, int]] = []
    ys, xs = np.nonzero(mask)
    for start_y, start_x in zip(ys.tolist(), xs.tolist()):
        if visited[start_y, start_x]:
            continue
        stack = [(start_x, start_y)]
        visited[start_y, start_x] = True
        area = 0
        sum_x = 0
        sum_y = 0
        min_x = max_x = start_x
        min_y = max_y = start_y
        while stack:
            x, y = stack.pop()
            area += 1
            sum_x += x
            sum_y += y
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height and mask[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    stack.append((nx, ny))
        comp_width = max_x - min_x + 1
        comp_height = max_y - min_y + 1
        if area_min <= area <= area_max and size_min <= comp_width <= size_max and size_min <= comp_height <= size_max:
            point = (int(round(sum_x / area)), int(round(sum_y / area)))
            if is_valid_map_point(point):
                points.append(point)
    return points


def detect_station_icon_candidate_types(image: np.ndarray) -> tuple[list[tuple[int, int]], dict[tuple[int, int], str]]:
    hsv = _bgr_to_hsv(image)
    stable = _stable_map_mask(hsv.shape[:2])
    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    masks = [
        ("gold", stable & (15 <= h) & (h <= 35) & (s >= 185) & (v >= 150), CITY_ICON_AREA_MIN, CITY_ICON_AREA_MAX, CITY_ICON_SIZE_MIN, CITY_ICON_SIZE_MAX),
        ("cyan", stable & (82 <= h) & (h <= 125) & (s >= 150) & (v >= 125), CITY_ICON_AREA_MIN, CITY_ICON_AREA_MAX, CITY_ICON_SIZE_MIN, CITY_ICON_SIZE_MAX),
        (
            "red",
            stable & ((h <= 8) | (h >= 172)) & (s >= 170) & (v >= 135),
            25,
            140,
            6,
            18,
        ),
    ]
    candidates: list[tuple[int, int]] = []
    candidate_types: dict[tuple[int, int], str] = {}
    for kind, mask, area_min, area_max, size_min, size_max in masks:
        for point in _component_centers(mask, area_min=area_min, area_max=area_max, size_min=size_min, size_max=size_max):
            if all(abs(point[0] - old[0]) > 18 or abs(point[1] - old[1]) > 18 for old in candidates):
                candidates.append(point)
                candidate_types[point] = kind
    sorted_candidates = sorted(candidates, key=lambda point: (point[1], point[0]))
    return sorted_candidates, {point: candidate_types[point] for point in sorted_candidates}


def detect_station_icon_candidates(image: np.ndarray) -> list[tuple[int, int]]:
    candidates, _ = detect_station_icon_candidate_types(image)
    return candidates


def nearest_candidate(point: tuple[float, float], candidates: list[tuple[int, int]]) -> tuple[tuple[int, int], float] | None:
    if not candidates:
        return None
    px, py = point
    best = min(candidates, key=lambda item: (item[0] - px) ** 2 + (item[1] - py) ** 2)
    return best, math.hypot(best[0] - px, best[1] - py)


def score_transform(
    stations: tuple[WorldStation, ...],
    candidates: list[tuple[int, int]],
    scale: float,
    tx: float,
    ty: float,
    threshold: float,
    candidate_types: dict[tuple[int, int], str] | None = None,
    target_station: WorldStation | None = None,
) -> tuple[float, list[MapMatch]]:
    used_candidates: set[tuple[int, int]] = set()
    matches: list[MapMatch] = []
    for station in stations:
        typed_candidates = candidates
        if candidate_types is not None:
            station_kind = station_icon_kind(station)
            if not station_kind:
                continue
            typed_candidates = [
                candidate for candidate in candidates if candidate_types.get(candidate) == station_kind
            ]
            if not typed_candidates:
                continue
        sx, sy = project_world_point(station.x, station.y, scale, tx, ty)
        if sx < -60 or sx > 1340 or sy < 40 or sy > 760:
            continue
        nearest = nearest_candidate((sx, sy), typed_candidates)
        if not nearest:
            continue
        candidate, distance = nearest
        if distance > threshold or candidate in used_candidates:
            continue
        used_candidates.add(candidate)
        matches.append(
            MapMatch(
                name=station.name,
                world=(station.x, station.y),
                projected=(round(sx, 2), round(sy, 2)),
                candidate=candidate,
                distance=round(distance, 2),
            )
        )

    if not matches:
        return -1e9, matches

    mean_error = sum(match.distance for match in matches) / len(matches)
    score = len(matches) * 100 - mean_error * 3
    if len(matches) >= 3:
        score += 80
    if len(matches) >= 5:
        score += 160
    score -= abs(scale - CALIBRATED_MAP_SCALE) * 1000

    if target_station is not None and candidate_types is not None:
        target_kind = station_icon_kind(target_station)
        typed_candidates = [
            candidate for candidate in candidates if candidate_types.get(candidate) == target_kind
        ]
        if target_kind and typed_candidates:
            target_point = project_station(
                target_station,
                MapLocateResult(
                    scale=scale,
                    tx=tx,
                    ty=ty,
                    score=0,
                    mean_error=0,
                    matches=(),
                    candidates=(),
                ),
            )
            nearest = nearest_candidate(target_point, typed_candidates)
            if nearest is not None:
                _, target_distance = nearest
                if target_distance <= 90:
                    score += 260 - target_distance * 2
                else:
                    rounded = rounded_point(target_point)
                    if is_valid_map_point(rounded):
                        score -= min(220, target_distance * 0.6)
    return score, matches


def locate_candidates(
    candidates: list[tuple[int, int]],
    *,
    stations: tuple[WorldStation, ...] | None = None,
    candidate_types: dict[tuple[int, int], str] | None = None,
    target_station: WorldStation | None = None,
    scale_min: float = 0.325,
    scale_max: float = 0.34,
    scale_step: float = 0.0025,
    threshold: float = 28.0,
) -> MapLocateResult | None:
    stations = stations or load_world_stations()
    best: MapLocateResult | None = None
    scales = np.arange(scale_min, scale_max + scale_step / 2, scale_step)
    for candidate in candidates:
        cx, cy = candidate
        for station in stations:
            for scale in scales:
                scale = float(scale)
                tx = cx - scale * station.x
                ty = cy + scale * station.y
                score, matches = score_transform(
                    stations,
                    candidates,
                    scale,
                    tx,
                    ty,
                    threshold,
                    candidate_types=candidate_types,
                    target_station=target_station,
                )
                if not matches:
                    continue
                mean_error = sum(match.distance for match in matches) / len(matches)
                result = MapLocateResult(
                    scale=round(scale, 5),
                    tx=round(float(tx), 3),
                    ty=round(float(ty), 3),
                    score=round(score, 3),
                    mean_error=round(mean_error, 3),
                    matches=tuple(matches),
                    candidates=tuple(candidates),
                )
                if best is None or result.score > best.score:
                    best = result

    if not best:
        return None
    candidate_xs = [match.candidate[0] for match in best.matches]
    candidate_ys = [match.candidate[1] for match in best.matches]
    has_stable_spread = max(candidate_xs) - min(candidate_xs) >= 180 and max(candidate_ys) - min(candidate_ys) >= 80
    reliable = (
        (best.match_count >= 5 and best.mean_error <= 6.0)
        or (best.match_count >= 4 and best.mean_error <= 3.0)
        or (best.match_count >= 3 and best.mean_error <= 1.2 and has_stable_spread)
    )
    if not reliable:
        return None
    return best


def locate_map_view_from_candidates(
    candidates: list[tuple[int, int]],
    *,
    candidate_types: dict[tuple[int, int], str] | None = None,
    target_station: WorldStation | None = None,
) -> MapLocateResult | None:
    """用 Maa ColorMatch 得到的站点候选点拟合地图视口。"""
    return locate_candidates(candidates, candidate_types=candidate_types, target_station=target_station)


def locate_map_view(image: np.ndarray) -> MapLocateResult | None:
    """用纯 numpy 候选提取兜底拟合地图视口，不额外依赖 OpenCV。"""
    return locate_candidates(detect_station_icon_candidates(image))


def clamp_drag_distance(distance: float, drag_distance: int) -> int:
    max_distance = min(drag_distance, MAX_COORDINATE_DRAG_DISTANCE)
    return int(max(MIN_COORDINATE_DRAG_DISTANCE, min(max_distance, round(distance))))


def projected_target_drag_plan(point: tuple[int, int], drag_distance: int = 520) -> tuple[str, int] | None:
    x, y = point
    x_delta = 0
    y_delta = 0
    if x > NAV_TARGET_X_MAX or x < NAV_TARGET_X_MIN:
        x_delta = x - NAV_TARGET_CENTER_X
    if y > NAV_TARGET_Y_MAX or y < NAV_TARGET_Y_MIN:
        y_delta = y - NAV_TARGET_CENTER_Y

    if not x_delta and not y_delta:
        return None

    x_weight = abs(x_delta) / (NAV_TARGET_X_MAX - NAV_TARGET_X_MIN)
    y_weight = abs(y_delta) / (NAV_TARGET_Y_MAX - NAV_TARGET_Y_MIN)
    if x_weight >= y_weight:
        direction = "east" if x_delta > 0 else "west"
        distance = clamp_drag_distance(abs(x_delta) * 0.38, drag_distance)
    else:
        direction = "south" if y_delta > 0 else "north"
        distance = clamp_drag_distance(abs(y_delta) * 0.65, drag_distance)
    return direction, distance

from __future__ import annotations

from typing import Any


def _recognition_text(item: Any) -> str:
    text = getattr(item, "text", None)
    if text is None and isinstance(item, dict):
        text = item.get("text")
    return str(text or "").strip()


def _recognition_score(item: Any) -> float:
    value = getattr(item, "score", None)
    if value is None and isinstance(item, dict):
        value = item.get("score")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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


def _box_center_point(box: Any) -> tuple[int, int]:
    x, y, width, height = _box_xywh(box) or (0, 0, 0, 0)
    return int(round(x + width / 2)), int(round(y + height / 2))


def _recognition_result_items(detail: Any) -> list[Any]:
    """兼容 Maa dataclass 与 Agent 反向调用中的原始 dict 结果。"""
    if detail is None:
        return []

    items: list[Any] = []
    for attr in ("filtered_results", "all_results"):
        items.extend(getattr(detail, attr, None) or [])
    best = getattr(detail, "best_result", None)
    if best is not None:
        items.append(best)

    raw_sources: list[Any] = []
    if isinstance(detail, dict):
        raw_sources.extend([detail, detail.get("detail"), detail.get("raw_detail")])
    else:
        raw_sources.extend([getattr(detail, "raw_detail", None), getattr(detail, "detail", None)])
    for raw in raw_sources:
        if not isinstance(raw, dict):
            continue
        items.extend(raw.get("filtered") or [])
        items.extend(raw.get("all") or [])
        raw_best = raw.get("best")
        if raw_best:
            items.append(raw_best)

    unique: list[Any] = []
    seen: set[tuple[int, int, int, int, int]] = set()
    for item in items:
        box = getattr(item, "box", None)
        count = getattr(item, "count", None)
        if isinstance(item, dict):
            box = item.get("box", box)
            count = item.get("count", count)
        xywh = _box_xywh(box)
        try:
            count_key = int(count or 0)
        except (TypeError, ValueError):
            count_key = 0
        key = (*(xywh or (-1, -1, -1, -1)), count_key)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _ocr_texts(argv: Any) -> list[str]:
    """从 Maa OCR 识别详情中取出文字，供账号配置和交易页解析使用。"""
    detail = getattr(argv, "reco_detail", None)
    results = []
    if detail is not None:
        results.extend(getattr(detail, "all_results", None) or [])
        results.extend(getattr(detail, "filtered_results", None) or [])
        best = getattr(detail, "best_result", None)
        if best is not None:
            results.append(best)

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

    for result in results:
        visit(result)
    return list(dict.fromkeys(texts))


def _ocr_entries(argv: Any) -> list[dict[str, Any]]:
    """保留 Maa OCR 的文字和位置，供声望列表这类横向解析使用。"""
    detail = getattr(argv, "reco_detail", None)
    results = []
    if detail is not None:
        results.extend(getattr(detail, "all_results", None) or [])
        results.extend(getattr(detail, "filtered_results", None) or [])
        best = getattr(detail, "best_result", None)
        if best is not None:
            results.append(best)

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
        x = y = w = h = None
        if isinstance(box, dict):
            x, y, w, h = box.get("x"), box.get("y"), box.get("w"), box.get("h")
        elif box is not None:
            if isinstance(box, (list, tuple)) and len(box) >= 4:
                x, y, w, h = box[:4]
            else:
                x = getattr(box, "x", None)
                y = getattr(box, "y", None)
                w = getattr(box, "w", None)
                h = getattr(box, "h", None)
        elif isinstance(result, dict) and all(key in result for key in ("x", "y", "w", "h")):
            x, y, w, h = result.get("x"), result.get("y"), result.get("w"), result.get("h")
        elif isinstance(position, list) and position:
            points = [
                (float(point[0] or 0), float(point[1] or 0))
                for point in position
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ]
            if points:
                xs = [point[0] for point in points]
                ys = [point[1] for point in points]
                x = min(xs)
                y = min(ys)
                w = max(xs) - min(xs)
                h = max(ys) - min(ys)
        if x is None or y is None or w is None or h is None:
            return
        try:
            ix, iy, iw, ih = int(float(x)), int(float(y)), int(float(w)), int(float(h))
        except (TypeError, ValueError):
            return
        item = {
            "text": str(text),
            "x": ix,
            "y": iy,
            "w": iw,
            "h": ih,
            "center_x": ix + iw / 2,
            "center_y": iy + ih / 2,
        }
        key = (item["text"], ix, iy, iw, ih)
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

    for result in results:
        visit(result)
    return entries

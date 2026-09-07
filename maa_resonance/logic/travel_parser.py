from __future__ import annotations

import re
from typing import Any

from .profile_parser import clean_text


def travel_status_from_texts(texts: list[str]) -> dict[str, Any]:
    """Parse one travel HUD OCR result, allowing a split distance label/value."""
    cleaned = [clean_text(text) for text in texts if str(text).strip()]
    destination = None
    remaining = None
    cruising = False
    labeled_distances: set[int] = set()
    for text in cleaned:
        if "目的地" in text:
            # A bare OCR label is not a destination. D-gear recovery requires
            # an actual destination as well as a positive remaining distance.
            value = text.split("目的地", 1)[1].lstrip(":：")
            destination = value or destination
        if "巡航" in text:
            cruising = True
        for match in re.finditer(r"剩余行程[:：]?(\d+)\s*km(?![a-z/])", text, re.I):
            labeled_distances.add(int(match.group(1)))
    if len(labeled_distances) == 1:
        remaining = next(iter(labeled_distances))
    elif not labeled_distances and any(re.fullmatch(r"剩余行程[:：]?", text) for text in cleaned):
        # OCR order is not reading order: the label and 605km can have other
        # HUD fragments between them. Only accept one distinct standalone
        # distance in this result. Never join all text or fall back to a speed,
        # bare number, stale frame, or an ambiguous distance.
        distances = {
            int(match.group(1))
            for text in cleaned
            if (match := re.fullmatch(r"(\d+)\s*km", text, re.I))
        }
        if len(distances) == 1:
            remaining = next(iter(distances))
    return {
        "destination": destination,
        "remaining_km": remaining,
        "cruising": cruising,
        "texts": cleaned,
    }

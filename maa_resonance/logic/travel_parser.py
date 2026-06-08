from __future__ import annotations

import re
from typing import Any

from .profile_parser import clean_text


def travel_status_from_texts(texts: list[str]) -> dict[str, Any]:
    """Parse travel HUD OCR texts for route monitoring."""
    cleaned = [clean_text(text) for text in texts if str(text).strip()]
    destination = None
    remaining = None
    cruising = False
    for text in cleaned:
        if "目的地" in text:
            destination = re.split(r"[:：]", text, maxsplit=1)[-1] or destination
        if "巡航" in text:
            cruising = True
        match = re.search(r"剩余行程[:：]?(\d+)\s*km", text, re.I)
        if match:
            remaining = int(match.group(1))
    return {
        "destination": destination,
        "remaining_km": remaining,
        "cruising": cruising,
        "texts": cleaned,
    }

from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any

from maa_resonance.logic.profile_parser import (
    CREW_CARD_BASE_LEFTS,
    CREW_CARD_BASE_WIDTH,
    clean_text,
    load_role_names,
    normalize_role_text,
)

DEFAULT_TEAM_ROLES: tuple[str, ...] = ()

QUICK_TEAM_ROW_NAME_Y_MIN = 250
QUICK_TEAM_ROW_NAME_Y_MAX = 345
QUICK_TEAM_BADGE_Y_MIN = 175
QUICK_TEAM_BADGE_Y_MAX = 270
QUICK_TEAM_CARD_CLICK_Y = 205
QUICK_TEAM_MAX_COLUMNS = 7


def parse_target_roles(raw_roles: Any) -> list[str]:
    """Parse user-configured target role names from a string or sequence."""
    if raw_roles is None:
        return []
    if isinstance(raw_roles, (list, tuple)):
        tokens = [str(item).strip() for item in raw_roles]
    else:
        tokens = re.split(r"[,，、;；\n\r\t]+", str(raw_roles))

    result: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        cleaned = token.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def build_role_candidates(
    target_roles: list[str] | tuple[str, ...] = (),
    extra_roles: list[str] | tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Combine configured targets with the built-in role catalog."""
    ordered: list[str] = []
    seen: set[str] = set()
    for source in (target_roles, extra_roles, load_role_names()):
        for name in source:
            role = str(name or "").strip()
            if not role or role in seen:
                continue
            seen.add(role)
            ordered.append(role)
    return tuple(ordered)


def _canonical_role_keys(role: str) -> tuple[str, ...]:
    raw_clean = clean_text(role)
    normalized = normalize_role_text(role)
    return tuple(key for key in dict.fromkeys((raw_clean, normalized)) if key)


def _has_variant_suffix_conflict(role_a: str, role_b: str) -> bool:
    key_a = normalize_role_text(role_a)
    key_b = normalize_role_text(role_b)
    if not key_a or not key_b or key_a == key_b:
        return False
    return key_a.startswith(key_b) or key_b.startswith(key_a)


def match_formation_role(
    text: str,
    target_roles: list[str] | tuple[str, ...] = (),
    extra_roles: list[str] | tuple[str, ...] = (),
) -> str | None:
    """Match an OCR text snippet against role names without cross-variant confusion."""
    cleaned = clean_text(text)
    normalized = normalize_role_text(text)
    if not cleaned:
        return None
    if any(ch.isdigit() for ch in cleaned) and len(cleaned) <= 5:
        return None

    candidates = build_role_candidates(target_roles, extra_roles)

    for role in candidates:
        keys = _canonical_role_keys(role)
        if cleaned in keys or normalized in keys:
            return role

    best_role: str | None = None
    best_score = 0.0
    for role in candidates:
        keys = _canonical_role_keys(role)
        for key in keys:
            if len(key) < 2:
                continue
            if key in cleaned or key in normalized:
                score = 2.0 + len(key) * 0.02
            elif abs(len(key) - len(normalized)) <= 1:
                ratio = SequenceMatcher(None, normalized, key).ratio()
                if ratio < 0.80:
                    continue
                # Avoid matching base variant to alt variant like 静流 vs 静流·逐夏
                if len(normalized) != len(key) and any(
                    _has_variant_suffix_conflict(role, other)
                    for other in candidates
                    if other != role
                ):
                    continue
                score = ratio
            else:
                continue

            if score > best_score:
                best_score = score
                best_role = role

    return best_role


def _entry_box_xywh(entry: dict[str, Any]) -> tuple[int, int, int, int]:
    box = entry.get("box")
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        return int(box[0]), int(box[1]), int(box[2]), int(box[3])
    return (
        int(entry.get("x", 0) or 0),
        int(entry.get("y", 0) or 0),
        int(entry.get("w", 0) or 0),
        int(entry.get("h", 0) or 0),
    )


def _column_index_for_x(center_x: float) -> int | None:
    for idx, left in enumerate(CREW_CARD_BASE_LEFTS):
        right = left + CREW_CARD_BASE_WIDTH
        if left - 10 <= center_x <= right + 10:
            return idx
    nearest_idx = min(
        range(len(CREW_CARD_BASE_LEFTS)),
        key=lambda i: abs(center_x - (CREW_CARD_BASE_LEFTS[i] + CREW_CARD_BASE_WIDTH / 2)),
    )
    col_center = CREW_CARD_BASE_LEFTS[nearest_idx] + CREW_CARD_BASE_WIDTH / 2
    if abs(center_x - col_center) <= CREW_CARD_BASE_WIDTH * 0.65:
        return nearest_idx
    return None


def _column_center_x(col_idx: int) -> int:
    return int(round(CREW_CARD_BASE_LEFTS[col_idx] + CREW_CARD_BASE_WIDTH / 2))


def extract_quick_team_cards(
    entries: list[dict[str, Any]],
    target_roles: list[str] | tuple[str, ...] = (),
    extra_roles: list[str] | tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Extract top-row cards with role name, selection state, and click center."""
    role_by_col: dict[int, tuple[str, int]] = {}
    badge_by_col: dict[int, str] = {}

    for entry in entries:
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        x, y, w, h = _entry_box_xywh(entry)
        cx = x + w / 2.0
        cy = y + h / 2.0
        col_idx = _column_index_for_x(cx)
        if col_idx is None:
            continue

        if QUICK_TEAM_BADGE_Y_MIN <= cy <= QUICK_TEAM_BADGE_Y_MAX:
            if "剧情" in text:
                badge_by_col[col_idx] = "story_locked"
                continue
            if "已上阵" in text or "上阵" in text:
                if badge_by_col.get(col_idx) != "story_locked":
                    badge_by_col[col_idx] = "selected"
                continue

        if QUICK_TEAM_ROW_NAME_Y_MIN <= cy <= QUICK_TEAM_ROW_NAME_Y_MAX:
            role = match_formation_role(text, target_roles=target_roles, extra_roles=extra_roles)
            if role:
                prev = role_by_col.get(col_idx)
                if prev is None or len(role) > len(prev[0]):
                    role_by_col[col_idx] = (role, int(round(cy)))

    cards: list[dict[str, Any]] = []
    for col_idx in sorted(role_by_col):
        role, name_y = role_by_col[col_idx]
        state = badge_by_col.get(col_idx, "unselected")
        cards.append(
            {
                "column": col_idx,
                "role": role,
                "state": state,
                "center": (_column_center_x(col_idx), QUICK_TEAM_CARD_CLICK_Y),
                "name_y": name_y,
            }
        )
    return cards


def quick_team_page_signature(cards: list[dict[str, Any]]) -> tuple[str, ...]:
    """Build a stable signature for visible quick-team cards to detect scroll end."""
    return tuple(f"{card['column']}:{card['role']}:{card['state']}" for card in cards)


def resolve_desired_roles(
    target_roles: list[str] | tuple[str, ...],
    story_locked_roles: set[str] | list[str] | tuple[str, ...] = (),
    *,
    max_team_size: int = 5,
) -> list[str]:
    """Compute final desired roster keeping story-locked characters and filling remaining slots."""
    locked = [str(r) for r in story_locked_roles if str(r).strip()]
    desired: list[str] = list(dict.fromkeys(locked))
    for role in target_roles:
        if len(desired) >= max_team_size:
            break
        if role not in desired:
            desired.append(role)
    return desired[:max_team_size]


def choose_next_quick_team_step(
    cards: list[dict[str, Any]],
    target_roles: list[str] | tuple[str, ...],
    *,
    known_story_roles: set[str] | None = None,
    confirmed_selected: set[str] | None = None,
    max_team_size: int = 5,
    fill_empty_only: bool = False,
) -> dict[str, Any]:
    """Decide the next single action on the visible quick-team row.

    Returns a dict with ``action`` in ``{"click", "scroll", "confirm"}``.
    """
    story_roles = set(known_story_roles or ())
    for card in cards:
        if card["state"] == "story_locked":
            story_roles.add(card["role"])

    visible_selected = {
        card["role"] for card in cards if card["state"] in {"selected", "story_locked"}
    }
    active_selected = set(confirmed_selected or ())
    if not fill_empty_only:
        active_selected.difference_update(card["role"] for card in cards if card["state"] == "unselected")
    active_selected.update(visible_selected)

    if not target_roles:
        return {
            "action": "confirm",
            "reason": "no_target_roles_configured",
            "desired_roles": [],
            "story_roles": sorted(story_roles),
            "active_selected": sorted(active_selected),
        }

    protected_roles = active_selected | story_roles if fill_empty_only else story_roles
    desired = resolve_desired_roles(target_roles, protected_roles, max_team_size=max_team_size)
    desired_set = set(desired)

    # 1. Remove any non-locked selected character on the current page that is not in desired_set.
    for card in cards:
        if not fill_empty_only and card["state"] == "selected" and card["role"] not in desired_set:
            return {
                "action": "click",
                "reason": "deselect_unwanted",
                "role": card["role"],
                "point": card["center"],
                "desired_roles": desired,
                "story_roles": sorted(story_roles),
                "active_selected": sorted(active_selected),
            }

    # 2. If all desired roles are already accounted for as selected, confirm.
    if desired_set and desired_set.issubset(active_selected):
        return {
            "action": "confirm",
            "reason": "all_targets_selected",
            "desired_roles": desired,
            "story_roles": sorted(story_roles),
            "active_selected": sorted(active_selected),
        }

    # 3. Select any desired character visible and currently unselected if team has free slots.
    if len(active_selected) < max_team_size:
        for role in desired:
            if fill_empty_only and role in active_selected:
                continue
            for card in cards:
                if card["role"] == role and card["state"] == "unselected":
                    return {
                        "action": "click",
                        "reason": "select_target",
                        "role": card["role"],
                        "point": card["center"],
                        "desired_roles": desired,
                        "story_roles": sorted(story_roles),
                        "active_selected": sorted(active_selected),
                    }

    # 4. Otherwise scroll to inspect remaining rows.
    return {
        "action": "scroll",
        "reason": "need_more_rows",
        "desired_roles": desired,
        "story_roles": sorted(story_roles),
        "active_selected": sorted(active_selected),
    }


def is_main_formation_needs_update(
    name_entries: list[dict[str, Any]],
    empty_entries: list[dict[str, Any]],
    target_roles: list[str] | tuple[str, ...],
    *,
    strict_match: bool = False,
    has_story_lock: bool = False,
) -> bool:
    """Decide on the formation main screen whether quick-team selection should run.

    In default (empty-only) mode, triggers only when at least one empty '+' slot is detected.
    In strict mode, triggers when empty slots exist OR visible non-empty roles diverge from target_roles.
    """
    if not target_roles:
        return False

    for entry in empty_entries:
        text = str(entry.get("text") or "").strip().upper()
        if "添加" in text or "EMPTY" in text:
            return True

    if not strict_match:
        return False

    visible_roles: list[str] = []
    for entry in name_entries:
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        role = match_formation_role(text, target_roles=target_roles)
        if role and role not in visible_roles:
            visible_roles.append(role)

    if len(visible_roles) < min(5, len(target_roles)):
        return True

    expected_set = set(list(target_roles)[:5])
    mismatch_count = sum(1 for role in visible_roles if role not in expected_set)
    if has_story_lock:
        # In story-locked lineups, 1+ forced story role outside target_roles is expected.
        return mismatch_count > 1
    return mismatch_count > 0


"""Update role recognition and trade effects from decoded game Factory JSON.

Only purchase-quantity and tax skills are projected into the route planner.
Patrol, crafting, battle, etc. never create extra trading bonuses. Each stored
resonance tier is a cumulative snapshot, not an amount to add to earlier tiers.
"""
from __future__ import annotations

import argparse
import copy
from datetime import date
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRADE_TYPES = {"AddQty", "AddQtyNum", "AddTypeQty", "AddSpecQty", "TaxCuts"}
RARITIES = {"twoStar": "N", "threeStar": "R", "fourStar": "SR", "FiveStar": "SSR"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_skill_city(skill, stations):
    city = stations[int(skill["city"])]["name"]
    # User-requested temporary exception: Jess & Simon's tax description says
    # Gonglu, while the source ID points to Anita Launch Center. Keep it narrow
    # so unrelated skills and future descriptions still use their configured ID.
    if (skill["id"] == 83900294 and skill["homeSkillType"] == "TaxCuts"
            and "贡露城" in skill.get("desc", "")):
        return "贡露城"
    return city


def trade_effects(unit, level, skills, goods, stations):
    out = {}

    def add(kind, axis, key, value):
        target = out.setdefault(kind, {})
        if axis:
            target = target.setdefault(axis, {})
        target[key] = round(target.get(key, 0) + value, 6)

    for unlock in unit.get("homeSkillList", []):
        if int(unlock["resonanceLv"]) > level:
            continue
        skill = skills[unlock["id"]]
        kind = skill["homeSkillType"]
        if kind not in TRADE_TYPES:
            continue
        value, city = float(skill["param"]), int(skill.get("city", -1))
        if kind in {"TaxCuts", "AddSpecQty"}:
            city_name = resolve_skill_city(skill, stations)
            if kind == "TaxCuts":
                add("taxCut", "city", city_name, value)
            else:
                add("buyMore", "city", city_name, value * 100)
            continue
        if city != -1:
            raise ValueError(f"Unsupported city-scoped goods skill: {skill['id']}")
        if kind == "AddTypeQty":
            names = {row["name"] for row in goods.values() if row.get("goodsType") == skill["tagId"]}
            if not names:
                # Some existing skills target categories with no configured goods.
                # Report them below, without turning an empty category into all goods.
                continue
        else:
            names = {goods[row["id"]]["name"] for row in skill.get("goodsList", [])}
        if kind == "AddQtyNum":
            if not value.is_integer() or not names:
                raise ValueError(f"Invalid flat purchase amount: {skill['id']}")
            for name in sorted(names):
                add("buyMoreFlat", "product", name, int(value))
        elif names:
            for name in sorted(names):
                add("buyMore", "product", name, value * 100)
        else:
            add("buyMore", None, "all", value * 100)
    return out


def effective_snapshot(tiers, level):
    eligible = [int(key) for key in tiers if str(key).isdigit() and 0 < int(key) <= level]
    return tiers[str(max(eligible))] if eligible else {}


def refresh(source_dir, catalog, trade, updated_at):
    catalog, trade = copy.deepcopy(catalog), copy.deepcopy(trade)
    source_hashes, factories = {}, {}
    for name in ("BookFactory", "UnitFactory", "HomeSkillFactory", "HomeGoodsFactory", "HomeStationFactory"):
        path = source_dir / f"{name}.json"
        source_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        factories[name] = {row["id"]: row for row in read_json(path)}
    units, skills = factories["UnitFactory"], factories["HomeSkillFactory"]
    goods, stations = factories["HomeGoodsFactory"], factories["HomeStationFactory"]
    book = factories["BookFactory"][80900001]["unitList"]
    report = {"source_hashes": source_hashes, "added_roles": [], "updated_trade_roles": [],
              "source_conflicts": [], "unmapped_goods_tags": [], "role_skill_projection": []}
    for item in book:
        unit = units[item["id"]]
        name, quality = unit["name"], unit["quality"]
        rarity = RARITIES[quality]
        max_level = 4 if rarity in {"N", "R"} else 5
        if name not in catalog["roles"]:
            catalog["roles"].append(name)
            report["added_roles"].append({"name": name, "id": unit["id"]})
        catalog["quality_by_role"][name] = quality
        catalog["rarity_by_role"][name] = rarity
        catalog["resonance_max_by_role"][name] = max_level
        snapshots, previous = {}, {}
        for level in range(1, max_level + 1):
            snapshot = trade_effects(unit, level, skills, goods, stations)
            if snapshot != previous:
                snapshots[str(level)] = snapshot
            previous = snapshot
        old = trade["resonance_skills"].get(name, {})
        if any(effective_snapshot(old, level) != effective_snapshot(snapshots, level)
               for level in range(1, max_level + 1)):
            report["updated_trade_roles"].append({"name": name, "before": old, "after": snapshots})
            trade["resonance_skills"][name] = snapshots
        if snapshots:
            for defaults in (trade["default_roles"], trade["default_player_config"]["roles"],
                             trade["default_player_config_no_return_bargain"]["roles"]):
                defaults.setdefault(name, {"resonance": max_level})
        projection = {"name": name, "id": unit["id"], "skills": [], "trade_snapshots": snapshots}
        for unlock in unit.get("homeSkillList", []):
            skill = skills[unlock["id"]]
            unmapped = skill["homeSkillType"] == "AddTypeQty" and not any(
                row.get("goodsType") == skill["tagId"] for row in goods.values())
            projection["skills"].append({"id": skill["id"], "resonance": unlock["resonanceLv"],
                                         "type": skill["homeSkillType"], "description": skill["desc"],
                                         "included_in_trade_snapshots": skill["homeSkillType"] in TRADE_TYPES and not unmapped,
                                         "separate_runtime_effect": "driving_fatigue" if name == "波克士" and
                                         skill["homeSkillType"] == "ReduceDriveCost" else None})
            if unmapped:
                report["unmapped_goods_tags"].append({"role": name, "skill_id": skill["id"],
                                                     "tag_id": skill["tagId"], "description": skill["desc"]})
            if skill["homeSkillType"] in {"TaxCuts", "AddSpecQty"}:
                city = stations[skill["city"]]["name"]
                mentioned = [row["name"] for row in stations.values()
                             if row["name"] and row["name"] in skill["desc"]]
                if mentioned and city not in mentioned:
                    applied_city = resolve_skill_city(skill, stations)
                    conflict = {"role": name, "skill_id": skill["id"], "city_id": skill["city"],
                                "source_city": city, "applied_city": applied_city, "description": skill["desc"],
                                "resolution": ("User-requested temporary override: use the city in this skill's description."
                                               if applied_city != city else
                                               "Use the configured city ID; do not infer a replacement from text.")}
                    if conflict not in report["source_conflicts"]:
                        report["source_conflicts"].append(conflict)
        report["role_skill_projection"].append(projection)
    catalog["source"].update(updated_at=updated_at, source_hashes={
        name: source_hashes[name] for name in ("BookFactory.json", "UnitFactory.json")})
    trade["source"]["role_life_skills"] = {
        "updated_at": updated_at, "source": "decoded game BinaryConfig Factory JSON",
        "source_hashes": source_hashes, "tier_semantics": "cumulative snapshots at trade-effect changes",
        "source_conflicts": report["source_conflicts"],
        "unmapped_goods_tags": report["unmapped_goods_tags"],
    }
    report["catalog_count"] = len(catalog["roles"])
    report["trade_role_count"] = len(trade["resonance_skills"])
    return catalog, trade, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--updated-at", default=date.today().isoformat())
    parser.add_argument("--write", action="store_true", help="Apply resource updates; otherwise only audit")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    catalog_path = ROOT / "resources/goods/RoleCatalog2026.json"
    trade_path = ROOT / "resources/goods/ColumbaTradeData2026.json"
    catalog, trade, report = refresh(args.source_dir, read_json(catalog_path), read_json(trade_path), args.updated_at)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.write:
        for path, data in ((catalog_path, catalog), (trade_path, trade)):
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("added_roles", "updated_trade_roles", "source_conflicts",
                                                    "catalog_count", "trade_role_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build store- and model-level privacy-safe premiumisation intelligence."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

from build_premium_summary import (
    COL_RE,
    NS,
    SHEET_RE,
    digest_row,
    iso_date,
    load_strings,
    number,
    product_family,
    resolve,
    row_channel,
)


MIN_CUSTOMERS = 10
IPHONE_HERO_BY_YEAR = {
    2022: "iPhone 14",
    2023: "iPhone 15",
    2024: "iPhone 16",
    2025: "iPhone 17",
}


def clean_text(*values: str) -> str:
    return " ".join(" ".join(values).upper().replace("-", " ").split())


def model_name(family: str, category: str, lob: str, item_name: str) -> str:
    text = clean_text(category, lob, item_name)
    if family == "iPhone":
        if "IPHONE SE" in text:
            return "iPhone SE"
        match = re.search(r"IPHONE\s*(\d{1,2})(E)?\b", text)
        if not match:
            return "iPhone (generation unavailable)"
        generation = match.group(1)
        if match.group(2):
            return f"iPhone {generation}e"
        suffix = ""
        for token, label in (
            ("PRO MAX", " Pro Max"),
            ("PRO", " Pro"),
            ("PLUS", " Plus"),
            ("MINI", " mini"),
            ("AIR", " Air"),
            ("E", "e"),
        ):
            if re.search(rf"\b{token}\b", text):
                suffix = label
                break
        return f"iPhone {generation}{suffix}"
    if family == "Mac":
        line = next((label for token, label in (
            ("MACBOOK AIR", "MacBook Air"),
            ("MACBOOK PRO", "MacBook Pro"),
            ("MAC STUDIO", "Mac Studio"),
            ("MAC MINI", "Mac mini"),
            ("IMAC", "iMac"),
            ("MAC PRO", "Mac Pro"),
        ) if token in text), "Mac (other observed models)")
        chip = re.search(r"\bM([1-9])(?:\s*(MAX|PRO|ULTRA))?\b", text)
        if chip and line not in {"Mac Pro", "Mac (other observed models)"}:
            suffix = f" M{chip.group(1)}" + (f" {chip.group(2).title()}" if chip.group(2) else "")
            return line + suffix
        return line
    if family == "iPad":
        if "IPAD PRO" in text:
            return "iPad Pro"
        if "IPAD AIR" in text:
            return "iPad Air"
        if "IPAD MINI" in text:
            return "iPad mini"
        generation = re.search(r"\b(\d{1,2})(?:ST|ND|RD|TH)\s+GEN", text)
        return f"iPad {generation.group(1)}th Gen" if generation else "iPad"
    if family == "Watch":
        if "HERMES" in text or "HERMÈS" in text:
            return "Watch Hermès"
        ultra = re.search(r"\bULTRA\s*(\d+)?", text)
        if ultra:
            return "Watch Ultra" + (f" {ultra.group(1)}" if ultra.group(1) else "")
        if "EDITION" in text:
            return "Watch Edition"
        if re.search(r"\b(SE|SERIES SE)\b", text):
            return "Watch SE"
        series = re.search(r"\bSERIES\s*(\d{1,2})\b", text)
        return f"Watch Series {series.group(1)}" if series else "Watch (other observed series)"
    if family == "AirPods":
        if "MAX" in text:
            return "AirPods Max"
        if "PRO" in text:
            generation = re.search(r"\b(1ST|2ND|3RD)\s+GEN", text)
            return "AirPods Pro" + (f" {generation.group(1).title()} Gen" if generation else "")
        generation = re.search(r"\b(1ST|2ND|3RD|4TH)\s+GEN", text)
        return "AirPods" + (f" {generation.group(1).title()} Gen" if generation else "")
    return f"{family} (model unavailable)"


def premium_model(family: str, model: str) -> bool:
    if family == "iPhone":
        return model.endswith(" Pro") or model.endswith(" Pro Max")
    if family == "Mac":
        return model.startswith(("MacBook Pro", "Mac Studio", "Mac Pro"))
    if family == "iPad":
        return model == "iPad Pro"
    if family == "Watch":
        return model.startswith(("Watch Ultra", "Watch Hermès", "Watch Edition"))
    if family == "AirPods":
        return model == "AirPods Max"
    return False


def new_bucket():
    return {"units": 0.0, "value": 0.0, "customers": set()}


def add(bucket, code_hash: bytes, units: float, value: float):
    bucket["units"] += units
    bucket["value"] += value
    bucket["customers"].add(code_hash)


def merge(target, source):
    target["units"] += source["units"]
    target["value"] += source["value"]
    target["customers"].update(source["customers"])


def serialize(prefix, segment: str, bucket):
    return [*prefix, segment, round(bucket["units"], 3), round(bucket["value"], 2), len(bucket["customers"])]


def main(output: Path, source_args: list[str]):
    if len(source_args) != 6:
        raise SystemExit("usage: build_premium_model_summary.py OUTPUT.js 2022-H1 2022-H2 2023-H1 2023-H2 2024 2025")
    specs = (
        (2022, source_args[0], "2022-01-01", "2022-06-30"),
        (2022, source_args[1], "2022-07-01", "2022-12-31"),
        (2023, source_args[2], "2023-01-01", "2023-06-30"),
        (2023, source_args[3], "2023-07-01", "2023-12-31"),
        (2024, source_args[4], "2024-01-01", "2024-12-31"),
        (2025, source_args[5], "2025-01-01", "2025-12-31"),
    )
    started = time.time()
    seen_by_year = defaultdict(set)
    national = {}
    stores = {}
    stats = defaultdict(lambda: defaultdict(float))

    for year, source_arg, start_date, end_date in specs:
        source = Path(source_arg)
        seen = seen_by_year[year]
        with ZipFile(source) as book:
            strings = load_strings(book)
            print(f"{year}: {source.name}", flush=True)
            for sheet in sorted(name for name in book.namelist() if SHEET_RE.fullmatch(name)):
                with book.open(sheet) as stream:
                    row_number = 0
                    for _, row in etree.iterparse(stream, events=("end",), tag=NS + "row"):
                        row_number += 1
                        cells = {}
                        for cell in row.findall(NS + "c"):
                            match = COL_RE.match(cell.get("r", ""))
                            if match:
                                node = cell.find(NS + "v")
                                cells[match.group(0)] = (cell.get("t"), "" if node is None or node.text is None else node.text)
                        row.clear()
                        while row.getprevious() is not None:
                            del row.getparent()[0]
                        if row_number == 1:
                            continue
                        stats[year]["raw_rows"] += 1
                        date = iso_date(str(resolve(cells.get("D", (None, "")), strings)).strip())
                        if not date or date < start_date or date > end_date:
                            stats[year]["outside_authoritative_period"] += 1
                            continue
                        status = str(resolve(cells.get("G", (None, "")), strings)).strip().casefold()
                        if status in {"cancelled", "canceled", "cancel"}:
                            stats[year]["cancelled_rows"] += 1
                            continue
                        digest = digest_row(cells)
                        if digest in seen:
                            stats[year]["duplicate_rows"] += 1
                            continue
                        seen.add(digest)
                        txn_type = str(resolve(cells.get("C", (None, "")), strings)).strip().casefold()
                        if txn_type not in {"sale", "sales", "pos"}:
                            stats[year]["non_pos_rows"] += 1
                            continue
                        code = str(resolve(cells.get("J", (None, "")), strings)).strip()
                        units = number(resolve(cells.get("AL", (None, "0")), strings))
                        value = number(resolve(cells.get("AY", (None, "0")), strings))
                        if not code or units <= 0 or value <= 0:
                            stats[year]["ineligible_pos_rows"] += 1
                            continue
                        business_unit = str(resolve(cells.get("Y", (None, "")), strings)).strip()
                        category = str(resolve(cells.get("AA", (None, "")), strings)).strip()
                        lob = str(resolve(cells.get("AB", (None, "")), strings)).strip()
                        family = product_family(business_unit, category, lob)
                        if family is None:
                            stats[year]["non_core_rows"] += 1
                            continue
                        item_name = str(resolve(cells.get("W", (None, "")), strings)).strip()
                        model = model_name(family, category, lob, item_name)
                        store = str(resolve(cells.get("A", (None, "")), strings)).strip() or "Store unavailable"
                        city = str(resolve(cells.get("B", (None, "")), strings)).strip() or "City unavailable"
                        executive = str(resolve(cells.get("N", (None, "")), strings)).strip()
                        channel = row_channel(store, executive)
                        code_hash = hashlib.blake2b(code.encode(), digest_size=12).digest()
                        add(national.setdefault((year, channel, family, model), new_bucket()), code_hash, units, value)
                        add(stores.setdefault((year, store, city, channel, family, model), new_bucket()), code_hash, units, value)
                        stats[year]["eligible_model_rows"] += 1
                        stats[year]["eligible_units"] += units
                        stats[year]["eligible_value"] += value
                        if int(stats[year]["raw_rows"]) % 100_000 == 0:
                            print(f"{year}: {int(stats[year]['raw_rows']):,} rows", flush=True)

    observed_hero = {}
    for (year, _channel, family, model), bucket in national.items():
        if premium_model(family, model):
            continue
        key = (year, family)
        current = observed_hero.get(key)
        if current is None or bucket["units"] > current[1]:
            observed_hero[key] = (model, bucket["units"])
    hero_map = {}
    for year in range(2022, 2026):
        for family in ("iPhone", "Mac", "iPad", "Watch", "AirPods"):
            candidate = IPHONE_HERO_BY_YEAR.get(year) if family == "iPhone" else None
            exists = candidate and any(k[0] == year and k[2] == family and k[3] == candidate for k in national)
            hero_map[f"{year}|{family}"] = candidate if exists else observed_hero.get((year, family), (None, 0))[0]

    def segment(year: int, family: str, model: str) -> str:
        if premium_model(family, model):
            return "Premium Flagship"
        if hero_map.get(f"{year}|{family}") == model:
            return "Consumer Hero"
        return "Other Observed Model"

    def publish(source, store_level: bool):
        rows, rollups = [], {}
        for key, bucket in source.items():
            if len(bucket["customers"]) >= MIN_CUSTOMERS:
                if store_level:
                    year, store, city, channel, family, model = key
                    rows.append(serialize([year, store, city, channel, family, model], segment(year, family, model), bucket))
                else:
                    year, channel, family, model = key
                    rows.append(serialize([year, channel, family, model], segment(year, family, model), bucket))
                continue
            if store_level:
                year, store, city, channel, family, _model = key
                roll_key = (year, store, city, channel, family, "Other low-volume models (aggregated)")
            else:
                year, channel, family, _model = key
                roll_key = (year, channel, family, "Other low-volume models (aggregated)")
            merge(rollups.setdefault(roll_key, new_bucket()), bucket)
        suppressed = new_bucket()
        for key, bucket in rollups.items():
            if len(bucket["customers"]) >= MIN_CUSTOMERS:
                rows.append(serialize(list(key), "Other Models (aggregated)", bucket))
            else:
                merge(suppressed, bucket)
        rows.sort(key=lambda row: tuple(str(value) for value in row[:-3]))
        return rows, suppressed

    national_rows, national_suppressed = publish(national, False)
    store_rows, store_suppressed = publish(stores, True)
    total_value = sum(s["eligible_value"] for s in stats.values())
    store_published_value = sum(row[-2] for row in store_rows)
    payload = {
        "meta": {
            "coverage_start": "2022-01-01",
            "coverage_end": "2025-12-31",
            "generated_on": "2026-08-27",
            "privacy_mode": "aggregate_only",
            "minimum_customer_threshold": MIN_CUSTOMERS,
            "scope": "Valid de-duplicated positive-quantity, positive-value POS sales for observed core Apple device models; sale returns excluded.",
            "iphone_consumer_hero_by_year": {str(k): v for k, v in IPHONE_HERO_BY_YEAR.items()},
            "hero_rule_other_families": "Highest-unit observed non-premium model within each calendar year and product family.",
            "source_stats": {str(y): {k: round(v, 2) for k, v in s.items()} for y, s in stats.items()},
            "hero_map": hero_map,
            "national_suppressed_units": round(national_suppressed["units"], 3),
            "national_suppressed_value": round(national_suppressed["value"], 2),
            "store_suppressed_units": round(store_suppressed["units"], 3),
            "store_suppressed_value": round(store_suppressed["value"], 2),
            "store_value_coverage_pct": round(store_published_value / total_value * 100, 4) if total_value else 0,
        },
        "national_columns": ["year", "channel", "family", "model", "segment", "units", "value", "customers"],
        "national_rows": national_rows,
        "store_columns": ["year", "store", "city", "channel", "family", "model", "segment", "units", "value", "customers"],
        "store_rows": store_rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("window.LG_PREMIUM_MODELS=" + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";", encoding="utf-8")
    print(json.dumps({
        "national_rows": len(national_rows),
        "store_rows": len(store_rows),
        "store_value_coverage_pct": payload["meta"]["store_value_coverage_pct"],
        "hero_map": hero_map,
        "file_mb": round(output.stat().st_size / 1_000_000, 2),
        "elapsed_seconds": round(time.time() - started, 1),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2:])

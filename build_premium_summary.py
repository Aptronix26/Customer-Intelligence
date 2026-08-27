#!/usr/bin/env python3
"""Build a privacy-safe 2022-2025 premiumisation aggregate for GitHub Pages."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

from lxml import etree


NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
COL_RE = re.compile(r"[A-Z]+")
SHEET_RE = re.compile(r"xl/worksheets/sheet\d+\.xml")
MIN_CUSTOMERS = 10
CANONICAL_COLUMNS = tuple(chr(ord("A") + i) for i in range(26)) + tuple(
    "A" + chr(ord("A") + i) for i in range(26)
)


def load_strings(book: ZipFile) -> list[str]:
    values: list[str] = []
    if "xl/sharedStrings.xml" not in book.namelist():
        return values
    with book.open("xl/sharedStrings.xml") as stream:
        for _, elem in etree.iterparse(stream, events=("end",), tag=NS + "si"):
            values.append("".join(elem.itertext()))
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]
    return values


def resolve(pair, strings):
    kind, raw = pair
    if kind == "s" and raw:
        return strings[int(raw)]
    return raw


def number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def iso_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%d-%m-%Y").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def digest_row(cells) -> bytes:
    digest = hashlib.blake2b(digest_size=16)
    for col in CANONICAL_COLUMNS:
        kind, raw = cells.get(col, (None, ""))
        digest.update(col.encode()); digest.update(b"\0")
        digest.update((kind or "").encode()); digest.update(b"\0")
        digest.update(raw.encode()); digest.update(b"\1")
    return digest.digest()


def row_channel(branch: str, executive: str) -> str:
    branch_key = branch.strip().casefold()
    executive_key = executive.strip().casefold()
    if "warehouse" in branch_key:
        return "Warehouse"
    if branch_key.startswith("smb"):
        return "SMB"
    if branch_key.startswith("corporate"):
        return "Corporate"
    if branch_key.startswith("ecom") or "e-commerce" in branch_key:
        return "E-commerce"
    if executive_key == "online executive":
        return "Online Executive"
    return "Retail Stores"


def product_family(business_unit: str, category: str, lob: str) -> str | None:
    if business_unit.strip().casefold() != "apple":
        return None
    text = f"{category} {lob}".upper()
    for needle, label in (
        ("IPHONE", "iPhone"), ("AIRPOD", "AirPods"), ("IPAD", "iPad"),
        ("WATCH", "Watch"), ("MAC", "Mac"),
    ):
        if needle in text:
            return label
    return None


def premium_flag(family: str, category: str, lob: str, item_name: str) -> bool:
    text = " ".join(f"{category} {lob} {item_name}".upper().split())
    if family == "iPhone":
        return re.search(r"\bPRO(?:\s+MAX)?\b", text) is not None
    if family == "Mac":
        return any(label in text for label in ("MACBOOK PRO", "MAC PRO", "MAC STUDIO"))
    if family == "iPad":
        return "IPAD PRO" in text
    if family == "Watch":
        return any(label in text for label in ("ULTRA", "HERMES", "HERMÈS", "EDITION"))
    if family == "AirPods":
        return "AIRPODS MAX" in text or "AIRPOD MAX" in text
    return False


def new_bucket():
    return {
        "total_units": 0.0, "total_value": 0.0,
        "premium_units": 0.0, "premium_value": 0.0,
        "customers": set(), "premium_customers": set(),
    }


def add_to(bucket, code_hash, units, value, premium):
    bucket["total_units"] += units
    bucket["total_value"] += value
    bucket["customers"].add(code_hash)
    if premium:
        bucket["premium_units"] += units
        bucket["premium_value"] += value
        bucket["premium_customers"].add(code_hash)


def merge_into(target, source):
    for key in ("total_units", "total_value", "premium_units", "premium_value"):
        target[key] += source[key]
    target["customers"].update(source["customers"])
    target["premium_customers"].update(source["premium_customers"])


def serialize_bucket(prefix, bucket):
    return [
        *prefix,
        round(bucket["total_units"], 3), round(bucket["total_value"], 2),
        round(bucket["premium_units"], 3), round(bucket["premium_value"], 2),
    ]


def main(output: Path, source_args: list[str]):
    if len(source_args) != 6:
        raise SystemExit("usage: build_premium_summary.py OUTPUT.js 2022-H1 2022-H2 2023-H1 2023-H2 2024 2025")
    specs = (
        (2022, source_args[0], "2022-01-01", "2022-06-30"),
        (2022, source_args[1], "2022-07-01", "2022-12-31"),
        (2023, source_args[2], "2023-01-01", "2023-06-30"),
        (2023, source_args[3], "2023-07-01", "2023-12-31"),
        (2024, source_args[4], "2024-01-01", "2024-12-31"),
        (2025, source_args[5], "2025-01-01", "2025-12-31"),
    )
    started = time.time()
    national = {}
    detail = {}
    seen_by_year = defaultdict(set)
    stats = defaultdict(lambda: defaultdict(float))

    for year, source_arg, start_date, end_date in specs:
        source = Path(source_arg)
        seen = seen_by_year[year]
        with ZipFile(source) as book:
            strings = load_strings(book)
            sheets = sorted(name for name in book.namelist() if SHEET_RE.fullmatch(name))
            print(f"{year}: {source.name}", flush=True)
            for sheet in sheets:
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
                        if not code or units <= 0 or value < 0:
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
                        is_premium = premium_flag(family, category, lob, item_name)
                        city = str(resolve(cells.get("B", (None, "")), strings)).strip() or "City unavailable"
                        branch = str(resolve(cells.get("A", (None, "")), strings)).strip()
                        executive = str(resolve(cells.get("N", (None, "")), strings)).strip()
                        channel = row_channel(branch, executive)
                        code_hash = hashlib.blake2b(code.encode(), digest_size=12).digest()
                        national_bucket = national.setdefault((year, channel, family), new_bucket())
                        detail_bucket = detail.setdefault((year, city, channel, family), new_bucket())
                        add_to(national_bucket, code_hash, units, value, is_premium)
                        add_to(detail_bucket, code_hash, units, value, is_premium)
                        stats[year]["eligible_core_rows"] += 1
                        stats[year]["eligible_core_units"] += units
                        stats[year]["eligible_core_value"] += value
                        if is_premium:
                            stats[year]["premium_rows"] += 1
                            stats[year]["premium_units"] += units
                            stats[year]["premium_value"] += value
                        if int(stats[year]["raw_rows"]) % 100_000 == 0:
                            print(f"{year}: {int(stats[year]['raw_rows']):,} rows", flush=True)

    national_rows = [serialize_bucket(list(key), bucket) for key, bucket in national.items()]
    national_rows.sort(key=lambda row: tuple(str(value) for value in row[:3]))

    published_rows = []
    rollups = {}
    suppressed = new_bucket()
    for key, bucket in detail.items():
        premium_customers = len(bucket["premium_customers"])
        total_customers = len(bucket["customers"])
        if total_customers >= MIN_CUSTOMERS and (premium_customers == 0 or premium_customers >= MIN_CUSTOMERS):
            published_rows.append(serialize_bucket(list(key), bucket))
            continue
        year, _city, channel, family = key
        rollup = rollups.setdefault((year, "Low-volume cities (aggregated)", channel, family), new_bucket())
        merge_into(rollup, bucket)
    for key, bucket in rollups.items():
        if len(bucket["customers"]) >= MIN_CUSTOMERS and len(bucket["premium_customers"]) >= MIN_CUSTOMERS:
            published_rows.append(serialize_bucket(list(key), bucket))
        else:
            merge_into(suppressed, bucket)
    published_rows.sort(key=lambda row: tuple(str(value) for value in row[:4]))

    total_value = sum(row[4] for row in national_rows)
    published_value = sum(row[5] for row in published_rows)
    payload = {
        "meta": {
            "coverage_start": "2022-01-01",
            "coverage_end": "2025-12-31",
            "generated_on": "2026-08-27",
            "privacy_mode": "aggregate_only",
            "minimum_customer_threshold": MIN_CUSTOMERS,
            "scope": "Valid de-duplicated positive-quantity POS sales for core Apple device families; sale returns excluded from gross product-mix KPIs.",
            "premium_definition": {
                "iPhone": "Pro and Pro Max",
                "Mac": "MacBook Pro, Mac Pro and Mac Studio",
                "iPad": "iPad Pro",
                "Watch": "Ultra, Hermes/Hermès and Edition",
                "AirPods": "AirPods Max",
            },
            "source_stats": {str(y): {k: round(v, 2) for k, v in s.items()} for y, s in stats.items()},
            "published_detail_rows": len(published_rows),
            "suppressed_low_volume_units": round(suppressed["total_units"], 3),
            "suppressed_low_volume_value": round(suppressed["total_value"], 2),
            "detail_value_coverage_pct": round(published_value / total_value * 100, 4) if total_value else 0,
        },
        "national_columns": ["year", "channel", "family", "total_units", "total_value", "premium_units", "premium_value"],
        "national_rows": national_rows,
        "detail_columns": ["year", "city", "channel", "family", "total_units", "total_value", "premium_units", "premium_value"],
        "detail_rows": published_rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("window.LG_PREMIUM=" + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";", encoding="utf-8")
    print(json.dumps({
        "national_rows": len(national_rows),
        "detail_rows": len(published_rows),
        "detail_value_coverage_pct": payload["meta"]["detail_value_coverage_pct"],
        "file_mb": round(output.stat().st_size / 1_000_000, 2),
        "elapsed_seconds": round(time.time() - started, 1),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2:])

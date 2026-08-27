#!/usr/bin/env python3
"""Build a privacy-safe, filterable multi-period export cube for GitHub Pages."""

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


def load_strings(book: ZipFile) -> list[str]:
    values = []
    if "xl/sharedStrings.xml" not in book.namelist():
        return values
    with book.open("xl/sharedStrings.xml") as stream:
        for _, elem in etree.iterparse(stream, events=("end",), tag=NS + "si"):
            values.append("".join(elem.itertext()))
            elem.clear()
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


def iso_date(text: str) -> str:
    try:
        return datetime.strptime(text, "%d-%m-%Y").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


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


def product_family(business_unit: str, category: str, lob: str) -> str:
    if business_unit.strip().casefold() != "apple":
        return "Non-Apple / Services"
    text = f"{category} {lob}".upper()
    for needle, label in (
        ("IPHONE", "iPhone"), ("AIRPOD", "AirPods"), ("IPAD", "iPad"),
        ("WATCH", "Watch"), ("MAC", "Mac"),
    ):
        if needle in text:
            return label
    return "Other Apple"


def main(output: Path, source_args: list[str]) -> None:
    if len(source_args) != 6:
        raise SystemExit("usage: build_export_aggregate.py OUTPUT.js 2022-H1 2022-H2 2023-H1 2023-H2 2024 2025")
    started = time.time()
    groups = {}
    source_stats = defaultdict(lambda: defaultdict(float))
    seen_rows_by_year = defaultdict(set)
    specs = (
        (2022, source_args[0], "2022-01-01", "2022-06-30"),
        (2022, source_args[1], "2022-07-01", "2022-12-31"),
        (2023, source_args[2], "2023-01-01", "2023-06-30"),
        (2023, source_args[3], "2023-07-01", "2023-12-31"),
        (2024, source_args[4], "2024-01-01", "2024-12-31"),
        (2025, source_args[5], "2025-01-01", "2025-12-31"),
    )

    for year, source_arg, start_date, end_date in specs:
        source = Path(source_arg)
        seen_rows = seen_rows_by_year[year]
        stats = source_stats[str(year)]
        with ZipFile(source) as book:
            strings = load_strings(book)
            sheets = sorted(name for name in book.namelist() if SHEET_RE.fullmatch(name))
            print(f"{year}: {len(sheets)} sheet(s), {len(strings):,} shared strings", flush=True)
            for sheet in sheets:
                with book.open(sheet) as stream:
                    row_number = 0
                    for _, row in etree.iterparse(stream, events=("end",), tag=NS + "row"):
                        row_number += 1
                        cells = {}
                        row_digest = hashlib.blake2b(digest_size=16)
                        for cell in row.findall(NS + "c"):
                            match = COL_RE.match(cell.get("r", ""))
                            if not match:
                                continue
                            col = match.group(0)
                            value_node = cell.find(NS + "v")
                            raw = "" if value_node is None or value_node.text is None else value_node.text
                            kind = cell.get("t")
                            cells[col] = (kind, raw)
                            row_digest.update(col.encode()); row_digest.update(b"\0")
                            row_digest.update((kind or "").encode()); row_digest.update(b"\0")
                            row_digest.update(raw.encode()); row_digest.update(b"\1")
                        row.clear()
                        while row.getprevious() is not None:
                            del row.getparent()[0]
                        if row_number == 1:
                            continue
                        stats["raw_rows"] += 1
                        status = str(resolve(cells.get("G", (None, "")), strings)).strip().casefold()
                        if status in {"cancelled", "canceled", "cancel"}:
                            stats["cancelled_rows"] += 1
                            continue
                        digest = row_digest.digest()
                        if digest in seen_rows:
                            stats["duplicate_rows"] += 1
                            continue
                        seen_rows.add(digest)
                        code = str(resolve(cells.get("J", (None, "")), strings)).strip()
                        date = iso_date(str(resolve(cells.get("D", (None, "")), strings)).strip())
                        if not date or date < start_date or date > end_date:
                            stats["rows_outside_authoritative_period"] += 1
                            continue
                        if not code or not date:
                            stats["unlinked_or_undated_rows"] += 1
                            continue
                        branch = str(resolve(cells.get("A", (None, "")), strings)).strip() or "Store unavailable"
                        city = str(resolve(cells.get("B", (None, "")), strings)).strip() or "City unavailable"
                        executive = str(resolve(cells.get("N", (None, "")), strings)).strip()
                        channel = row_channel(branch, executive)
                        business_unit = str(resolve(cells.get("Y", (None, "")), strings)).strip()
                        category = str(resolve(cells.get("AA", (None, "")), strings)).strip()
                        lob = str(resolve(cells.get("AB", (None, "")), strings)).strip()
                        family = product_family(business_unit, category, lob)
                        txn_type = str(resolve(cells.get("C", (None, "")), strings)).strip()
                        invoice = str(resolve(cells.get("E", (None, "")), strings)).strip()
                        quantity = number(resolve(cells.get("AL", (None, "0")), strings))
                        value = number(resolve(cells.get("AY", (None, "0")), strings))
                        key = (date, city, branch, channel, family)
                        bucket = groups.get(key)
                        if bucket is None:
                            bucket = groups[key] = {
                                "lines": 0, "units": 0.0, "value": 0.0,
                                "customers": set(), "invoices": set(),
                            }
                        bucket["lines"] += 1
                        bucket["units"] += quantity
                        bucket["value"] += value
                        bucket["customers"].add(hashlib.blake2b(code.encode(), digest_size=12).digest())
                        if invoice:
                            invoice_key = f"{txn_type}\0{invoice}".encode()
                            bucket["invoices"].add(hashlib.blake2b(invoice_key, digest_size=12).digest())
                        stats["eligible_rows"] += 1
                        stats["eligible_units"] += quantity
                        stats["eligible_value"] += value
                        if int(stats["raw_rows"]) % 100_000 == 0:
                            print(f"{year}: processed {int(stats['raw_rows']):,} rows; groups={len(groups):,}", flush=True)
    source_stats = {
        year: {key: round(value, 2) for key, value in stats.items()}
        for year, stats in source_stats.items()
    }

    rows = []
    suppressed = {"groups": 0, "lines": 0, "units": 0.0, "value": 0.0}
    published = {"groups": 0, "lines": 0, "units": 0.0, "value": 0.0}
    city_rollups = {}

    def merge_bucket(target, bucket):
        target["lines"] += bucket["lines"]
        target["units"] += bucket["units"]
        target["value"] += bucket["value"]
        target["customers"].update(bucket["customers"])
        target["invoices"].update(bucket["invoices"])

    def new_bucket():
        return {"lines": 0, "units": 0.0, "value": 0.0, "customers": set(), "invoices": set()}

    def publish(key, bucket):
        date, city, branch, channel, family = key
        rows.append([
            date, city, branch, channel, family, bucket["lines"],
            len(bucket["invoices"]), len(bucket["customers"]),
            round(bucket["units"], 3), round(bucket["value"], 2),
        ])
        published["groups"] += 1
        published["lines"] += bucket["lines"]
        published["units"] += bucket["units"]
        published["value"] += bucket["value"]

    for key, bucket in groups.items():
        customer_count = len(bucket["customers"])
        if customer_count < MIN_CUSTOMERS:
            date, city, _branch, channel, family = key
            rollup = city_rollups.setdefault((date, city, "Low-volume stores (aggregated)", channel, family), new_bucket())
            merge_bucket(rollup, bucket)
            continue
        publish(key, bucket)

    national_rollups = {}
    for key, bucket in city_rollups.items():
        if len(bucket["customers"]) >= MIN_CUSTOMERS:
            publish(key, bucket)
            continue
        date, _city, _branch, channel, family = key
        national_key = (date, "Low-volume cities (aggregated)", "Low-volume locations (aggregated)", channel, family)
        rollup = national_rollups.setdefault(national_key, new_bucket())
        merge_bucket(rollup, bucket)

    for key, bucket in national_rollups.items():
        if len(bucket["customers"]) >= MIN_CUSTOMERS:
            publish(key, bucket)
            continue
        suppressed["groups"] += 1
        suppressed["lines"] += bucket["lines"]
        suppressed["units"] += bucket["units"]
        suppressed["value"] += bucket["value"]

    rows.sort(key=lambda row: tuple(str(x) for x in row[:5]))
    eligible_value = sum(stats.get("eligible_value", 0) for stats in source_stats.values())
    payload = {
        "meta": {
            "privacy_mode": "aggregate_only",
            "minimum_customer_threshold": MIN_CUSTOMERS,
            "coverage_start": rows[0][0] if rows else None,
            "coverage_end": max((row[0] for row in rows), default=None),
            "grain": "date × city × store × channel × product family, with privacy rollups from store to city to national level",
            "currency": "INR",
            "timezone": "Asia/Kolkata",
            "generated_on": "2026-08-27",
            "source_files": [Path(path).name for path in source_args],
            "source_stats": source_stats,
            "published": {k: round(v, 2) for k, v in published.items()},
            "suppressed": {k: round(v, 2) for k, v in suppressed.items()},
            "published_value_coverage_pct": round(published["value"] / eligible_value * 100, 4) if eligible_value else 0,
            "metric_notes": {
                "transaction_lines": "Valid de-duplicated customer-linked source rows after cancelled rows are excluded.",
                "invoice_interactions": "Distinct transaction-type and invoice combinations within each published aggregate cell; not additive across cells.",
                "customer_interactions": "Distinct Customer Codes within each published aggregate cell; not additive across cells.",
                "net_units": "Additive signed quantity, including returns.",
                "net_value": "Additive signed source net value in INR, including returns.",
            },
        },
        "columns": ["date", "city", "store", "channel", "product_family", "transaction_lines", "invoice_interactions", "customer_interactions", "net_units", "net_value_inr"],
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("window.LG_EXPORT=" + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";", encoding="utf-8")
    print(json.dumps({
        "rows": len(rows), "file_mb": round(output.stat().st_size / 1_000_000, 2),
        "published": payload["meta"]["published"], "suppressed": payload["meta"]["suppressed"],
        "published_value_coverage_pct": payload["meta"]["published_value_coverage_pct"],
        "elapsed_seconds": round(time.time() - started, 1),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2:])

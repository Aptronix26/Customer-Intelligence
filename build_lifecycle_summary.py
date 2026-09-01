#!/usr/bin/env python3
"""Build a privacy-safe 2022-2025 customer lifecycle cohort model."""

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
CORES = ["iPhone", "Mac", "iPad", "Watch", "AirPods"]
MIN_CUSTOMERS = 10


def load_strings(book):
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


def number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def iso_date(value):
    try:
        return datetime.strptime(value, "%d-%m-%Y").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def channel_for(branch, executive):
    b, e = branch.casefold(), executive.casefold()
    if "warehouse" in b:
        return "Warehouse"
    if b.startswith("smb"):
        return "SMB"
    if b.startswith("corporate"):
        return "Corporate"
    if b.startswith("ecom") or "e-commerce" in b:
        return "E-commerce"
    if e == "online executive":
        return "Online Executive"
    return "Retail Stores"


def core_lob(business_unit, category, lob):
    if business_unit.casefold() != "apple":
        return None
    text = f"{category} {lob}".upper()
    for needle, label in (("IPHONE", "iPhone"), ("AIRPOD", "AirPods"), ("IPAD", "iPad"), ("WATCH", "Watch"), ("MAC", "Mac")):
        if needle in text:
            return label
    return None


def new_customer():
    return {"first_date": "", "first_lobs": set(), "first_store": "", "first_channel": "", "mask": 0,
            "invoices": set(), "net": 0.0, "last_date": ""}


def merge_bucket(target, source):
    for key in ("customers", "repeat", "net"):
        target[key] += source[key]
    target["first_min"] = min(x for x in (target["first_min"], source["first_min"]) if x)
    target["last_max"] = max(target["last_max"], source["last_max"])


def main(output, sources):
    if len(sources) != 6:
        raise SystemExit("usage: build_lifecycle_summary.py OUTPUT.js 2022-H1 2022-H2 2023-H1 2023-H2 2024 2025")
    specs = (
        (2022, sources[0], "2022-01-01", "2022-06-30"), (2022, sources[1], "2022-07-01", "2022-12-31"),
        (2023, sources[2], "2023-01-01", "2023-06-30"), (2023, sources[3], "2023-07-01", "2023-12-31"),
        (2024, sources[4], "2024-01-01", "2024-12-31"), (2025, sources[5], "2025-01-01", "2025-12-31"),
    )
    started = time.time(); customers = {}; seen_by_year = defaultdict(set); stats = defaultdict(int)
    for year, source_arg, start, end in specs:
        source = Path(source_arg); seen = seen_by_year[year]
        with ZipFile(source) as book:
            strings = load_strings(book)
            for sheet in sorted(x for x in book.namelist() if SHEET_RE.fullmatch(x)):
                with book.open(sheet) as stream:
                    row_number = 0
                    for _, row in etree.iterparse(stream, events=("end",), tag=NS + "row"):
                        row_number += 1; cells = {}; digest = hashlib.blake2b(digest_size=16)
                        for cell in row.findall(NS + "c"):
                            match = COL_RE.match(cell.get("r", ""))
                            if not match: continue
                            col = match.group(0); node = cell.find(NS + "v"); raw = "" if node is None or node.text is None else node.text; kind = cell.get("t")
                            cells[col] = (kind, raw); digest.update(col.encode()); digest.update(b"\0"); digest.update((kind or "").encode()); digest.update(b"\0"); digest.update(raw.encode()); digest.update(b"\1")
                        row.clear()
                        while row.getprevious() is not None: del row.getparent()[0]
                        if row_number == 1: continue
                        stats["raw_rows"] += 1
                        date = iso_date(str(resolve(cells.get("D", (None, "")), strings)).strip())
                        if not date or date < start or date > end: continue
                        status = str(resolve(cells.get("G", (None, "")), strings)).strip().casefold()
                        if status in {"cancelled", "canceled", "cancel"}: stats["cancelled"] += 1; continue
                        row_key = digest.digest()
                        if row_key in seen: stats["duplicates"] += 1; continue
                        seen.add(row_key)
                        code = str(resolve(cells.get("J", (None, "")), strings)).strip()
                        if not code: continue
                        txn = str(resolve(cells.get("C", (None, "")), strings)).strip().casefold()
                        invoice = str(resolve(cells.get("E", (None, "")), strings)).strip()
                        branch = str(resolve(cells.get("A", (None, "")), strings)).strip() or "Store unavailable"
                        executive = str(resolve(cells.get("N", (None, "")), strings)).strip()
                        core = core_lob(str(resolve(cells.get("Y", (None, "")), strings)).strip(), str(resolve(cells.get("AA", (None, "")), strings)).strip(), str(resolve(cells.get("AB", (None, "")), strings)).strip())
                        qty = number(resolve(cells.get("AL", (None, "0")), strings)); value = number(resolve(cells.get("AY", (None, "0")), strings))
                        customer = customers.setdefault(code, new_customer()); customer["net"] += value; customer["last_date"] = max(customer["last_date"], date)
                        if txn in {"pos", "sale", "sales"} and invoice and len(customer["invoices"]) < 2:
                            customer["invoices"].add(f"{year}\0{invoice}")
                        if txn in {"pos", "sale", "sales"} and core and qty > 0:
                            customer["mask"] |= 1 << CORES.index(core)
                            if not customer["first_date"] or date < customer["first_date"]:
                                customer.update(first_date=date, first_lobs={core}, first_store=branch, first_channel=channel_for(branch, executive))
                            elif date == customer["first_date"]:
                                customer["first_lobs"].add(core)
                                if branch != customer["first_store"]: customer["first_store"] = "Multiple locations"
                        if stats["raw_rows"] % 250000 == 0:
                            print(f"processed {stats['raw_rows']:,} rows; lifecycle customers={len(customers):,}", flush=True)

    buckets = {}
    for c in customers.values():
        if not c["first_date"]: continue
        first_lob = next(iter(c["first_lobs"])) if len(c["first_lobs"]) == 1 else "Multi-LOB first purchase"
        key = (c["first_channel"], c["first_store"], int(c["first_date"][:4]), first_lob, c["mask"])
        b = buckets.setdefault(key, {"customers": 0, "repeat": 0, "net": 0.0, "first_min": c["first_date"], "last_max": c["last_date"]})
        b["customers"] += 1; b["repeat"] += len(c["invoices"]) >= 2; b["net"] += c["net"]
        b["first_min"] = min(b["first_min"], c["first_date"]); b["last_max"] = max(b["last_max"], c["last_date"])

    national = {}
    for (channel, store, year, first_lob, mask), b in buckets.items():
        key = (channel, "All stores / selling points", year, first_lob, mask)
        n = national.setdefault(key, {"customers": 0, "repeat": 0, "net": 0.0, "first_min": b["first_min"], "last_max": b["last_max"]})
        merge_bucket(n, b)
    detailed, low = [], {}
    for key, b in buckets.items():
        if b["customers"] >= MIN_CUSTOMERS: detailed.append((key, b)); continue
        channel, _store, year, first_lob, mask = key; roll_key = (channel, "Low-volume stores (aggregated)", year, first_lob, mask)
        r = low.setdefault(roll_key, {"customers": 0, "repeat": 0, "net": 0.0, "first_min": b["first_min"], "last_max": b["last_max"]}); merge_bucket(r, b)
    detailed.extend((k, b) for k, b in low.items() if b["customers"] >= MIN_CUSTOMERS)

    def row(item):
        (channel, store, year, first_lob, mask), b = item
        return [channel, store, year, first_lob, mask, b["customers"], b["repeat"], round(b["net"], 2), b["first_min"], b["last_max"]]
    national_rows = [row(x) for x in national.items() if x[1]["customers"] >= MIN_CUSTOMERS]
    store_rows = [row(x) for x in detailed]
    national_rows.sort(); store_rows.sort()
    payload = {"meta": {"coverage_start": "2022-01-01", "coverage_end": "2025-12-31", "privacy_mode": "aggregate_only", "minimum_customer_threshold": MIN_CUSTOMERS, "grain": "channel × first-purchase store × first year × first LOB × observed ecosystem mask", "core_lobs": CORES, "eligible_lifecycle_customers": sum(b["customers"] for b in national.values()), "generated_on": "2026-09-01", "source_files": [Path(x).name for x in sources], "audit": dict(stats)}, "national_rows": national_rows, "store_rows": store_rows}
    Path(output).write_text("window.LG_LIFECYCLE=" + json.dumps(payload, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(json.dumps({"national_rows": len(national_rows), "store_rows": len(store_rows), "eligible_customers": payload["meta"]["eligible_lifecycle_customers"], "elapsed_seconds": round(time.time()-started, 1)}, indent=2), flush=True)


if __name__ == "__main__": main(sys.argv[1], sys.argv[2:])

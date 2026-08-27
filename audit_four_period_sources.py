#!/usr/bin/env python3
"""Audit 2022-2025 sources with explicit handling of the June 2023 overlap."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

from lxml import etree


NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
COL_RE = re.compile(r"[A-Z]+")
SHEET_RE = re.compile(r"xl/worksheets/sheet\d+\.xml")
CANONICAL_COLUMNS = tuple(
    chr(ord("A") + i) for i in range(26)
) + tuple("A" + chr(ord("A") + i) for i in range(26))


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
    if kind == "b":
        return raw == "1"
    return raw


def number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parsed_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%d-%m-%Y")
    except (TypeError, ValueError):
        return None


def canonical_digest(cells) -> bytes:
    digest = hashlib.blake2b(digest_size=16)
    for col in CANONICAL_COLUMNS:
        kind, raw = cells.get(col, (None, ""))
        digest.update(col.encode()); digest.update(b"\0")
        digest.update((kind or "").encode()); digest.update(b"\0")
        digest.update(raw.encode()); digest.update(b"\1")
    return digest.digest()


def audit_period(year: int, sources: list[tuple[Path, datetime | None, datetime | None]]):
    started = time.time()
    seen_rows: set[bytes] = set()
    customers: set[str] = set()
    names: dict[str, str] = {}
    invoices: set[str] = set()
    stats = Counter()
    statuses = Counter()
    txn_types = Counter()
    min_date = max_date = None

    for source, start, end in sources:
        with ZipFile(source) as book:
            strings = load_strings(book)
            sheets = sorted(name for name in book.namelist() if SHEET_RE.fullmatch(name))
            print(f"{year}: {source.name} — {len(sheets)} sheet(s)", flush=True)
            for sheet in sheets:
                with book.open(sheet) as stream:
                    row_number = 0
                    for _, row in etree.iterparse(stream, events=("end",), tag=NS + "row"):
                        row_number += 1
                        cells = {}
                        for cell in row.findall(NS + "c"):
                            match = COL_RE.match(cell.get("r", ""))
                            if not match:
                                continue
                            node = cell.find(NS + "v")
                            cells[match.group(0)] = (cell.get("t"), "" if node is None or node.text is None else node.text)
                        row.clear()
                        while row.getprevious() is not None:
                            del row.getparent()[0]
                        if row_number == 1:
                            continue
                        stats["raw_rows_in_files"] += 1
                        date = parsed_date(str(resolve(cells.get("D", (None, "")), strings)).strip())
                        if date is None or (start and date < start) or (end and date > end):
                            stats["rows_outside_authoritative_period"] += 1
                            continue
                        stats["raw_rows_in_period"] += 1
                        status = str(resolve(cells.get("G", (None, "")), strings)).strip()
                        txn_type = str(resolve(cells.get("C", (None, "")), strings)).strip()
                        statuses[status or "<blank>"] += 1
                        txn_types[txn_type or "<blank>"] += 1
                        if status.casefold() in {"cancelled", "canceled", "cancel"}:
                            stats["cancelled_rows"] += 1
                            continue
                        digest = canonical_digest(cells)
                        if digest in seen_rows:
                            stats["duplicate_rows_removed"] += 1
                            continue
                        seen_rows.add(digest)
                        stats["valid_deduplicated_rows"] += 1
                        if txn_type.casefold() in {"sale", "sales", "pos"}:
                            stats["pos_rows"] += 1
                            invoice = str(resolve(cells.get("E", (None, "")), strings)).strip()
                            if invoice:
                                invoices.add(invoice)
                        elif "return" in txn_type.casefold():
                            stats["return_rows"] += 1
                        code = str(resolve(cells.get("J", (None, "")), strings)).strip()
                        name = str(resolve(cells.get("K", (None, "")), strings)).strip()
                        if code:
                            customers.add(code)
                            if name and code not in names:
                                names[code] = " ".join(name.upper().split())
                            stats["net_customer_linked_value"] += number(resolve(cells.get("AY", (None, "0")), strings))
                        else:
                            stats["blank_customer_rows"] += 1
                        min_date = date if min_date is None else min(min_date, date)
                        max_date = date if max_date is None else max(max_date, date)
                        if stats["raw_rows_in_files"] % 100_000 == 0:
                            print(f"{year}: {stats['raw_rows_in_files']:,} source rows", flush=True)

    result = {
        "year": year,
        "source_files": [str(source) for source, _, _ in sources],
        **{key: value for key, value in stats.items() if key != "net_customer_linked_value"},
        "distinct_valid_sales_invoices": len(invoices),
        "identifiable_customer_codes": len(customers),
        "net_customer_linked_value": stats["net_customer_linked_value"],
        "statuses": dict(statuses),
        "transaction_types": dict(txn_types),
        "min_date_text": min_date.strftime("%d-%m-%Y") if min_date else None,
        "max_date_text": max_date.strftime("%d-%m-%Y") if max_date else None,
        "elapsed_seconds": round(time.time() - started, 1),
    }
    print(f"{year}: complete — {len(customers):,} codes in {result['elapsed_seconds']}s", flush=True)
    return result, customers, names


def overlap_qa(first_half: Path, prior_partial: Path):
    start, end = datetime(2023, 6, 25), datetime(2023, 6, 30)
    sets = []
    invoice_sets = []
    for source in (first_half, prior_partial):
        rows, invoices = set(), set()
        with ZipFile(source) as book:
            strings = load_strings(book)
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
                        date = parsed_date(str(resolve(cells.get("D", (None, "")), strings)).strip())
                        if not date or date < start or date > end:
                            continue
                        status = str(resolve(cells.get("G", (None, "")), strings)).strip().casefold()
                        if status in {"cancelled", "canceled", "cancel"}:
                            continue
                        rows.add(canonical_digest(cells))
                        invoice = str(resolve(cells.get("E", (None, "")), strings)).strip()
                        txn_type = str(resolve(cells.get("C", (None, "")), strings)).strip()
                        if invoice:
                            invoices.add((txn_type, invoice))
        sets.append(rows); invoice_sets.append(invoices)
    return {
        "overlap_period": "25-06-2023 to 30-06-2023",
        "jan_jun_valid_unique_rows": len(sets[0]),
        "prior_partial_valid_unique_rows": len(sets[1]),
        "exact_row_matches": len(sets[0] & sets[1]),
        "jan_jun_invoice_interactions": len(invoice_sets[0]),
        "prior_partial_invoice_interactions": len(invoice_sets[1]),
        "matching_invoice_interactions": len(invoice_sets[0] & invoice_sets[1]),
        "authoritative_rule": "Use Jan-Jun source through 30 Jun 2023; use prior partial source from 1 Jul 2023 onward.",
    }


def main(args: list[str]):
    if len(args) != 6:
        raise SystemExit("usage: audit_four_period_sources.py 2022-H1 2022-H2 2023-H1 2023-H2 2024 2025")
    p22a, p22b, p23a, p23b, p24, p25 = map(Path, args)
    periods = []
    customer_sets = {}
    name_maps = {}
    specs = {
        2022: [(p22a, datetime(2022, 1, 1), datetime(2022, 6, 30)), (p22b, datetime(2022, 7, 1), datetime(2022, 12, 31))],
        2023: [(p23a, datetime(2023, 1, 1), datetime(2023, 6, 30)), (p23b, datetime(2023, 7, 1), datetime(2023, 12, 31))],
        2024: [(p24, datetime(2024, 1, 1), datetime(2024, 12, 31))],
        2025: [(p25, datetime(2025, 1, 1), datetime(2025, 12, 31))],
    }
    for year, sources in specs.items():
        result, customers, names = audit_period(year, sources)
        periods.append(result); customer_sets[year] = customers; name_maps[year] = names
    union = set().union(*customer_sets.values())
    patterns = Counter()
    for code in union:
        pattern = "_".join(str(year) for year in specs if code in customer_sets[year])
        patterns[pattern] += 1
    overlaps = {}
    for left, right in zip(specs, list(specs)[1:]):
        match = customer_sets[left] & customer_sets[right]
        overlaps[f"overlap_{left}_{right}"] = len(match)
        overlaps[f"{left}_seen_in_{right}_rate"] = len(match) / len(customer_sets[left]) if customer_sets[left] else 0
    all_four = set.intersection(*customer_sets.values())
    report = {
        "coverage_note": "Full calendar years 2022, 2023, 2024 and 2025.",
        "periods": periods,
        "cross_period": {
            "distinct_codes": len(union),
            "exact_code_overlap_all_four": len(all_four),
            **overlaps,
            "cohorts_by_year_presence": dict(sorted(patterns.items())),
            "cohort_total": sum(patterns.values()),
            "matching_normalized_names_all_four": sum(
                1 for code in all_four if len({name_maps[y].get(code) for y in specs if name_maps[y].get(code)}) == 1
            ),
        },
        "overlap_qa": overlap_qa(p23a, p23b),
    }
    Path("raw_audit_2022_2025.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"cross_period": report["cross_period"], "overlap_qa": report["overlap_qa"]}, indent=2), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])

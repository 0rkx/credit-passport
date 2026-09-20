#!/usr/bin/env python3
"""Validate the fictional multi-source demo CSV packs.

This deliberately mirrors the public CSV contract rather than importing the
FastAPI application. It can therefore run before the backend is installed or
running and catches the common demo mistakes: missing columns, malformed dates,
ambiguous directions, unsupported event labels and accidental duplicate rows.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any


SOURCE_TYPES = {
    "bank-statement",
    "payroll",
    "rent",
    "utility",
    "remittance",
    "wallet",
    "platform-earnings",
    "asset-repayment",
    "insurance",
    "merchant-sales",
    "other",
}

EVENT_ALIASES = {
    "salary": "salary",
    "payroll": "salary",
    "wages": "salary",
    "gig_income": "gig_income",
    "gig earnings": "gig_income",
    "platform_earnings": "gig_income",
    "platform earnings": "gig_income",
    "business_income": "business_income",
    "merchant_sales": "merchant_sales",
    "stipend": "stipend",
    "scholarship": "stipend",
    "pension": "pension",
    "rent": "rent",
    "rent_payment": "rent",
    "utility": "utility",
    "utility_payment": "utility",
    "bill": "bill",
    "loan_payment": "loan_payment",
    "credit_card_payment": "credit_card_payment",
    "asset_repayment": "asset_repayment",
    "paygo": "asset_repayment",
    "insurance": "insurance",
    "insurance_premium": "insurance",
    "remittance": "remittance",
    "family_remittance": "remittance",
    "international_transfer": "international_transfer",
    "savings": "savings",
    "reserve_transfer": "savings",
    "deposit": "deposit",
    "other": "other",
}

INCOME_TYPES = {"salary", "gig_income", "business_income", "merchant_sales", "stipend", "pension"}
COMMITMENT_TYPES = {"rent", "utility", "bill", "loan_payment", "credit_card_payment", "asset_repayment", "insurance"}
DEBIT_TYPES = COMMITMENT_TYPES | {"savings"}
DATE_COLUMNS = ("date", "occurred_on", "transaction_date", "posted_date")
AMOUNT_COLUMNS = ("amount", "value", "transaction_amount")


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.strip().lower())


def _columns(fieldnames: list[str]) -> dict[str, str]:
    return {_key(name): name for name in fieldnames if name}


def _column(columns: dict[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        if _key(name) in columns:
            return columns[_key(name)]
    return None


def _amount(value: str) -> float:
    cleaned = value.strip().replace(",", "")
    if not cleaned:
        raise ValueError("amount is empty")
    number = float(re.sub(r"[^0-9.\-]", "", cleaned))
    if number < 0:
        raise ValueError("amount must be non-negative; use direction=debit")
    return abs(number)


def _iso_date(value: str, label: str) -> date:
    text = value.strip()[:10]
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date (YYYY-MM-DD)") from exc
    if parsed.isoformat() != text:
        raise ValueError(f"{label} must use YYYY-MM-DD")
    return parsed


def validate(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent
    as_of = _iso_date(str(manifest["as_of"]), "manifest.as_of")
    accepted = set(manifest.get("accepted_event_types", []))
    if not accepted:
        raise ValueError("manifest.accepted_event_types must not be empty")

    errors: list[str] = []
    checked_files = 0
    checked_rows = 0
    fingerprints: dict[tuple[str, str, float, str, str], str] = {}
    seen_file_refs: set[str] = set()
    cases_report: list[dict[str, Any]] = []

    for case in manifest.get("cases", []):
        case_id = str(case.get("case_id", "<missing-case-id>"))
        source_report: list[dict[str, Any]] = []
        for source in case.get("sources", []):
            file_ref = str(source.get("file", ""))
            if not file_ref:
                errors.append(f"{case_id}: source file is missing")
                continue
            if file_ref in seen_file_refs:
                errors.append(f"{case_id}: source file is listed more than once: {file_ref}")
            seen_file_refs.add(file_ref)
            source_type = str(source.get("source_type", ""))
            if source_type not in SOURCE_TYPES:
                errors.append(f"{case_id}/{file_ref}: unsupported source_type {source_type!r}")
            path = root / "inputs" / file_ref
            if not path.is_file():
                errors.append(f"{case_id}/{file_ref}: file does not exist")
                continue
            checked_files += 1
            try:
                with path.open(newline="", encoding="utf-8-sig") as stream:
                    reader = csv.DictReader(stream)
                    if not reader.fieldnames:
                        raise ValueError("CSV must include a header row")
                    columns = _columns(reader.fieldnames)
                    date_column = _column(columns, DATE_COLUMNS)
                    amount_column = _column(columns, AMOUNT_COLUMNS)
                    direction_column = _column(columns, ("direction", "type", "credit_debit"))
                    event_column = _column(columns, ("event_type", "category", "transaction_type"))
                    if date_column is None:
                        raise ValueError("CSV is missing a date/occurred_on column")
                    if amount_column is None:
                        raise ValueError("CSV is missing an amount column")
                    if direction_column is None:
                        raise ValueError("demo CSVs must include direction explicitly")
                    if event_column is None:
                        raise ValueError("demo CSVs must include event_type explicitly")

                    rows = 0
                    first_date: date | None = None
                    last_date: date | None = None
                    local_fingerprints: set[tuple[str, str, float, str, str]] = set()
                    for row_number, row in enumerate(reader, start=2):
                        rows += 1
                        checked_rows += 1
                        occurred_on = _iso_date(str(row.get(date_column, "")), f"row {row_number} date")
                        if occurred_on > as_of:
                            raise ValueError(f"row {row_number} date {occurred_on} is after manifest.as_of {as_of}")
                        amount = _amount(str(row.get(amount_column, "")))
                        direction = str(row.get(direction_column, "")).strip().lower()
                        if direction not in {"credit", "debit"}:
                            raise ValueError(f"row {row_number} direction must be credit or debit")
                        raw_event = str(row.get(event_column, "")).strip().lower().replace("-", "_")
                        event_type = EVENT_ALIASES.get(re.sub(r"\s+", " ", raw_event), raw_event)
                        if event_type not in accepted:
                            raise ValueError(f"row {row_number} event_type {event_type!r} is not in manifest.accepted_event_types")
                        if event_type in INCOME_TYPES and direction != "credit":
                            raise ValueError(f"row {row_number} income event {event_type} must be credit")
                        if event_type in DEBIT_TYPES and direction != "debit":
                            raise ValueError(f"row {row_number} commitment/reserve event {event_type} must be debit")
                        if event_type == "deposit" and direction != "credit":
                            raise ValueError(f"row {row_number} deposit must be credit")
                        currency_column = _column(columns, ("currency", "ccy"))
                        currency = str(row.get(currency_column, "INR") if currency_column else "INR").strip().upper() or "INR"
                        fingerprint = (occurred_on.isoformat(), event_type, amount, currency, direction)
                        if fingerprint in local_fingerprints:
                            raise ValueError(f"row {row_number} duplicates an earlier row in this file")
                        local_fingerprints.add(fingerprint)
                        prior_file = fingerprints.get(fingerprint)
                        if prior_file:
                            raise ValueError(f"row {row_number} exactly duplicates {prior_file}; cross-source evidence must be unique")
                        fingerprints[fingerprint] = file_ref
                        first_date = occurred_on if first_date is None or occurred_on < first_date else first_date
                        last_date = occurred_on if last_date is None or occurred_on > last_date else last_date
                        due_column = _column(columns, ("due_on", "due_date"))
                        paid_column = _column(columns, ("paid_on", "paid_date"))
                        if due_column and str(row.get(due_column, "")).strip():
                            due = _iso_date(str(row[due_column]), f"row {row_number} due_on")
                            if due > as_of:
                                raise ValueError(f"row {row_number} due_on {due} is after manifest.as_of {as_of}")
                        if paid_column and str(row.get(paid_column, "")).strip():
                            paid = _iso_date(str(row[paid_column]), f"row {row_number} paid_on")
                            if paid > as_of:
                                raise ValueError(f"row {row_number} paid_on {paid} is after manifest.as_of {as_of}")
                    expected_rows = source.get("rows")
                    if expected_rows is not None and rows != int(expected_rows):
                        raise ValueError(f"manifest says {expected_rows} rows but CSV has {rows}")
                    if rows == 0:
                        raise ValueError("CSV contains no transaction rows")
                    source_report.append({"file": file_ref, "rows": rows, "period_start": first_date.isoformat(), "period_end": last_date.isoformat()})
            except (OSError, UnicodeDecodeError, csv.Error, ValueError) as exc:
                errors.append(f"{case_id}/{file_ref}: {exc}")
        cases_report.append({"case_id": case_id, "sources": source_report})

    report = {
        "manifest": str(manifest_path),
        "as_of": as_of.isoformat(),
        "status": "passed" if not errors else "failed",
        "checked_files": checked_files,
        "checked_rows": checked_rows,
        "cases": cases_report,
        "errors": errors,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("manifest.json"))
    parser.add_argument("--json", action="store_true", help="print the validation report as JSON")
    args = parser.parse_args()
    try:
        report = validate(args.manifest.resolve())
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        report = {"status": "failed", "errors": [str(exc)]}
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Demo input validation: {report['status']}")
        print(f"Checked {report.get('checked_files', 0)} files and {report.get('checked_rows', 0)} rows")
        for error in report.get("errors", []):
            print(f"- {error}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Build editable-contract PDF counterparts for the Anika update files."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfgen import canvas


OUTPUT_DIR = Path("/Users/owaiskhan/Desktop/Credit Passport Upload Files/Anika Updates/PDF")
HEADERS = [
    "date",
    "event_type",
    "amount",
    "currency",
    "direction",
    "reference",
    "description",
    "balance_after",
    "due_on",
    "paid_on",
    "status",
    "days_past_due",
]


def record(
    date: str,
    event_type: str,
    amount: int,
    direction: str,
    reference: str,
    description: str,
    balance_after: int,
    due_on: str = "",
    paid_on: str = "",
    status: str = "",
    days_past_due: int | str = "",
) -> list[str | int]:
    return [date, event_type, amount, "INR", direction, reference, description, balance_after, due_on, paid_on, status, days_past_due]


def positive_rows() -> list[list[str | int]]:
    rows: list[list[str | int]] = []
    days = ["28", "29", "30"]
    for index in range(24):
        cycle = index // 6
        day = days[index % 3]
        date = f"2026-06-{day}"
        event = ["salary", "platform_earnings", "deposit", "rent", "remittance", "insurance"][index % 6]
        amounts = {
            "salary": 220000 + cycle * 5000,
            "platform_earnings": 20000 + cycle * 1000,
            "deposit": 30000 + cycle * 2000,
            "rent": 42000 + cycle * 1000,
            "remittance": 45000 + cycle * 2000,
            "insurance": 4500 + cycle * 100,
        }
        credit = event in {"salary", "platform_earnings", "deposit", "remittance"}
        descriptions = {
            "salary": "Salary credit",
            "platform_earnings": "Platform earnings received",
            "deposit": "Reserve deposit",
            "rent": "Rent paid on time",
            "remittance": "Inbound remittance received",
            "insurance": "Protection premium paid on time",
        }
        scheduled = event in {"rent", "insurance"}
        rows.append(
            record(
                date,
                event,
                amounts[event],
                "credit" if credit else "debit",
                f"ANIKA-POS-{index + 1:02d}",
                descriptions[event],
                800000 + index * 15000,
                date if scheduled else "",
                date if scheduled else "",
                "reserve-built" if event == "deposit" else "received" if credit else "paid-on-time",
                0 if scheduled else "",
            )
        )
    return rows


def adverse_rows() -> list[list[str | int]]:
    rows: list[list[str | int]] = []
    salaries = [60000, 55000, 50000, 45000, 40000, 35000]
    for index in range(24):
        cycle = index // 4
        day = ["28", "29", "30"][index % 3]
        date = f"2026-06-{day}"
        event = ["salary", "rent", "utility", "loan_payment"][index % 4]
        amounts = {"salary": salaries[cycle], "rent": 140000 + cycle * 4000, "utility": 80000 + cycle * 3000, "loan_payment": 120000 + cycle * 5000}
        salary = event == "salary"
        description = "Reduced contract pay" if salary else {"rent": "Rent paid late", "utility": "Utility paid late", "loan_payment": "Loan payment paid late"}[event]
        rows.append(
            record(
                date,
                event,
                amounts[event],
                "credit" if salary else "debit",
                f"ANIKA-ADV-{index + 1:02d}",
                description,
                -100000 - index * 25000,
                "" if salary else "2026-06-27",
                "" if salary else date,
                "income-reduced" if salary else "late",
                "" if salary else 1 + index % 3,
            )
        )
    return rows


def mixed_rows() -> list[list[str | int]]:
    rows: list[list[str | int]] = []
    days = ["28", "29", "30"]
    for index in range(24):
        cycle = index // 6
        day = days[index % 3]
        date = f"2026-06-{day}"
        event = ["salary", "platform_earnings", "deposit", "rent", "remittance", "utility"][index % 6]
        amounts = {"salary": 180000 + cycle * 3000, "platform_earnings": 15000 + cycle * 1000, "deposit": 8000 + cycle * 500, "rent": 60000 + cycle * 2500, "remittance": 25000 + cycle * 1500, "utility": 12000 + cycle * 500}
        credit = event in {"salary", "platform_earnings", "deposit", "remittance"}
        scheduled = event in {"rent", "utility"}
        late = scheduled and cycle % 2 == 0
        if event == "salary":
            description = "Salary credit"
        elif event == "platform_earnings":
            description = "Variable platform earnings"
        elif event == "deposit":
            description = "Small reserve deposit"
        elif event == "remittance":
            description = "Inbound remittance received"
        else:
            description = f"{'Rent' if event == 'rent' else 'Utility'} paid {'late' if late else 'on time'}"
        rows.append(
            record(
                date,
                event,
                amounts[event],
                "credit" if credit else "debit",
                f"ANIKA-MIX-{index + 1:02d}",
                description,
                600000 - index * 6000,
                "2026-06-27" if late else date if scheduled else "",
                date if scheduled else "",
                "received" if credit else "late" if late else "paid",
                "" if not scheduled else 1 + cycle if late else 0,
            )
        )
    return rows


VARIANTS = [
    ("Anika-positive-update.pdf", "Anika Mehta - Positive financial update", "Recent records with stable income, reserves, cross-border support and on-time commitments.", positive_rows(), colors.HexColor("#087f5b")),
    ("Anika-adverse-update.pdf", "Anika Mehta - Adverse financial update", "Recent records with reduced income, late obligations and negative balances.", adverse_rows(), colors.HexColor("#b42318")),
    ("Anika-mixed-update.pdf", "Anika Mehta - Mixed financial update", "Recent records with variable income, small reserves and a mix of on-time and late payments.", mixed_rows(), colors.HexColor("#a15c00")),
]


def build_pdf(filename: str, title: str, subtitle: str, rows: list[list[str | int]], accent: colors.Color) -> None:
    page = landscape(A3)
    output = OUTPUT_DIR / filename
    width, height = page
    pdf = canvas.Canvas(str(output), pagesize=page)
    pdf.setTitle(title)
    pdf.setFillColor(colors.HexColor("#182b3a"))
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(28, height - 32, title)
    pdf.setFillColor(colors.HexColor("#52657a"))
    pdf.setFont("Helvetica", 9)
    pdf.drawString(28, height - 48, subtitle)

    # A pipe-delimited text table is intentional: it stays readable on screen
    # and remains machine-readable by the same text-based PDF parser as a bank
    # statement export. Keep descriptions short enough to remain one line.
    def line(values: list[str | int]) -> str:
        cleaned = []
        for value in values:
            text = str(value or "").replace("|", "/").replace("\n", " ")
            cleaned.append(text[:30])
        return " | ".join(cleaned)

    x = 28
    header_y = height - 76
    line_height = 16
    pdf.setFillColor(accent)
    pdf.rect(x - 4, header_y - 5, width - 56, 16, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Courier-Bold", 6.5)
    pdf.drawString(x, header_y, line(HEADERS))
    pdf.setFont("Courier", 6.4)
    for index, item in enumerate(rows):
        y = header_y - line_height * (index + 1)
        if index % 2:
            pdf.setFillColor(colors.HexColor("#eef7fa"))
            pdf.rect(x - 4, y - 5, width - 56, 16, fill=1, stroke=0)
        pdf.setFillColor(colors.HexColor("#22313f"))
        pdf.drawString(x, y, line(item))
    pdf.setStrokeColor(colors.HexColor("#d7e0e8"))
    pdf.line(x - 4, header_y - 7, width - 28, header_y - 7)
    pdf.setFillColor(colors.HexColor("#718198"))
    pdf.setFont("Helvetica-Oblique", 8)
    pdf.drawString(28, 24, "The workbook counterpart is editable; this PDF contains the same transaction fields for text-based ingestion.")
    pdf.save()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for args in VARIANTS:
        build_pdf(*args)
    print("\n".join(str(OUTPUT_DIR / name) for name, *_ in VARIANTS))


if __name__ == "__main__":
    main()

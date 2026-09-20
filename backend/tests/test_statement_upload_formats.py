from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.config import Settings
from app.main import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                db_path=str(tmp_path / "credit-passport.db"),
                cors_origins=("http://localhost:5173",),
                max_upload_bytes=1024 * 1024,
                model_metrics_path=str(tmp_path / "missing-metrics.json"),
            )
        )
    )


def _applicant(client: TestClient) -> str:
    response = client.post(
        "/api/v1/applicants",
        json={"name": "Workbook Applicant", "corridor": "UAE → India", "product": "personal-loan", "currency": "AED"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _xlsx(headers: list[str], rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _upload(client: TestClient, applicant_id: str, filename: str, content: bytes):
    return client.post(
        f"/api/v1/applicants/{applicant_id}/statements",
        files={"file": (filename, content, "application/octet-stream")},
        data={"source_type": "bank-statement", "provider": "Editable statement", "currency": "AED", "consent": "true"},
    )


def _strong_rows() -> list[list[object]]:
    rows: list[list[object]] = []
    for month in range(1, 7):
        rows.append([f"2026-{month:02d}-01", "salary", 20000, "AED", "credit", f"SAL-{month}", "Salary", 30000, "", "", "", ""])
        rows.append(
            [
                f"2026-{month:02d}-03",
                "rent",
                5000,
                "AED",
                "debit",
                f"RENT-{month}",
                "Rent",
                25000,
                f"2026-{month:02d}-03",
                f"2026-{month:02d}-03",
                "paid",
                0,
            ]
        )
    return rows


def test_xlsx_adverse_rows_reduce_and_positive_rows_recover_score(tmp_path: Path):
    client = _client(tmp_path)
    applicant_id = _applicant(client)
    headers = [
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

    strong = _upload(client, applicant_id, "strong.xlsx", _xlsx(headers, _strong_rows()))
    assert strong.status_code == 201, strong.text
    before = client.get(f"/api/v1/applicants/{applicant_id}/score?product=personal-loan").json()
    assert before["score"] == strong.json()["score"]["score"]

    adverse = _upload(
        client,
        applicant_id,
        "adverse.xlsx",
        _xlsx(
            headers,
            [["2026-07-03", "rent", 19000, "AED", "debit", "RENT-7", "Rent missed 90 days past due", -1000, "", "", "missed", 90]],
        ),
    )
    assert adverse.status_code == 201, adverse.text
    after_adverse = client.get(f"/api/v1/applicants/{applicant_id}/score?product=personal-loan").json()
    assert after_adverse["score"] < before["score"]
    assert any(reason["code"] == "COMMITMENT_ON_TIME" for reason in after_adverse["reason_codes"])
    assert after_adverse["assertion_count"] == before["assertion_count"] + 1

    positive = _upload(
        client,
        applicant_id,
        "positive.xlsx",
        _xlsx(
            headers,
            [
                ["2026-07-01", "salary", 20000, "AED", "credit", "SAL-7", "Salary", 19000, "", "", "", ""],
                ["2026-07-05", "rent", 5000, "AED", "debit", "RENT-8", "Rent", 14000, "2026-07-05", "2026-07-05", "paid", 0],
            ],
        ),
    )
    assert positive.status_code == 201, positive.text
    after_positive = client.get(f"/api/v1/applicants/{applicant_id}/score?product=personal-loan").json()
    assert after_positive["score"] > after_adverse["score"]


def test_xlsx_uses_signed_amounts_and_ignores_uploaded_score(tmp_path: Path):
    client = _client(tmp_path)
    applicant_id = _applicant(client)
    content = _xlsx(
        ["date", "amount", "description", "score", "balance"],
        [
            ["2026-08-01", 18500, "Salary", 1, 22000],
            ["2026-08-02", -5000, "Rent", 99, 17000],
        ],
    )
    response = _upload(client, applicant_id, "signed.xlsx", content)
    assert response.status_code == 201, response.text
    events = client.get(f"/api/v1/applicants/{applicant_id}/evidence").json()["events"]
    assert {event["direction"] for event in events} == {"credit", "debit"}
    assert {event["event_type"] for event in events} == {"salary", "rent"}
    assert response.json()["score"]["score"] != 1


def _text_pdf(lines: list[str]) -> bytes:
    """Build a tiny Helvetica PDF without adding a PDF-generation dependency."""

    def object_bytes(number: int, value: str) -> bytes:
        return f"{number} 0 obj\n{value}\nendobj\n".encode()

    stream = "BT\n/F1 10 Tf\n50 750 Td\n" + "".join(f"({line}) Tj\n0 -16 Td\n" for line in lines) + "ET\n"
    objects = [
        object_bytes(1, "<< /Type /Catalog /Pages 2 0 R >>"),
        object_bytes(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        object_bytes(3, "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"),
        object_bytes(4, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
        f"5 0 obj\n<< /Length {len(stream.encode())} >>\nstream\n".encode() + stream.encode() + b"endstream\nendobj\n",
    ]
    payload = b"%PDF-1.4\n"
    offsets = [0]
    for item in objects:
        offsets.append(len(payload))
        payload += item
    xref = len(payload)
    payload += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    payload += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    payload += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return payload


def test_pdf_statement_uses_same_event_mapping_and_rejects_unreadable_pdf(tmp_path: Path):
    client = _client(tmp_path)
    applicant_id = _applicant(client)
    pdf = _text_pdf(
        [
            "Date Description Amount Direction Balance",
            "2026-08-01 Salary 18,500 CR 22,000",
            "2026-08-02 Rent 5,000 DR 17,000",
        ]
    )
    response = _upload(client, applicant_id, "statement.pdf", pdf)
    assert response.status_code == 201, response.text
    assert response.json()["parsed_rows"] == 2
    assert client.get(f"/api/v1/applicants/{applicant_id}/evidence").json()["unique_event_count"] == 2

    unreadable = _upload(client, applicant_id, "scan.pdf", b"not a pdf")
    assert unreadable.status_code == 422
    assert "PDF" in unreadable.json()["detail"]


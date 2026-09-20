from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings(
        db_path=str(tmp_path / "credit-passport.db"),
        cors_origins=("http://localhost:5173",),
        max_upload_bytes=1024 * 1024,
        model_metrics_path=str(tmp_path / "missing-metrics.json"),
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def create_applicant(client: TestClient) -> str:
    response = client.post(
        "/api/v1/applicants",
        json={
            "name": "Test Applicant",
            "corridor": "UAE → India",
            "product": "personal-loan",
            "requested_amount": 600000,
            "currency": "INR",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def statement_payload() -> dict:
    return {
        "source_type": "bank-statement",
        "provider": "Applicant bank",
        "currency": "AED",
        "period_start": "2026-06-01",
        "period_end": "2026-09-30",
        "consent": True,
        "records": [
            {"occurred_on": "2026-06-01", "event_type": "salary", "amount": 18000, "currency": "AED", "direction": "credit"},
            {"occurred_on": "2026-06-02", "event_type": "rent", "amount": 8000, "currency": "AED", "direction": "debit", "due_on": "2026-06-02", "paid_on": "2026-06-02"},
            {"occurred_on": "2026-07-01", "event_type": "salary", "amount": 18000, "currency": "AED", "direction": "credit"},
            {"occurred_on": "2026-07-02", "event_type": "rent", "amount": 8000, "currency": "AED", "direction": "debit", "due_on": "2026-07-02", "paid_on": "2026-07-02"},
            {"occurred_on": "2026-08-01", "event_type": "salary", "amount": 18500, "currency": "AED", "direction": "credit"},
            {"occurred_on": "2026-08-02", "event_type": "rent", "amount": 8000, "currency": "AED", "direction": "debit", "due_on": "2026-08-02", "paid_on": "2026-08-02"},
        ],
    }


def test_health_config_and_empty_state(client: TestClient):
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["database"] == "ok"
    assert client.get("/api/v1/health").json()["status"] == "ok"

    config = client.get("/api/v1/config")
    assert config.status_code == 200
    assert {item["product"] for item in config.json()["products"]} == {"credit-card", "personal-loan", "student-loan"}
    assert len(config.json()["domains"]) == 7

    applicants = client.get("/api/v1/applicants")
    assert applicants.status_code == 200
    assert applicants.json() == []

    model = client.get("/api/v1/model/validation")
    assert model.status_code == 200
    assert model.json()["status"] == "unavailable"


def test_product_policies_are_distinct_and_sum_to_100(client: TestClient):
    products = {item["product"]: item["weights"] for item in client.get("/api/v1/config").json()["products"]}

    assert all(sum(weights.values()) == 100 for weights in products.values())
    assert products["credit-card"]["commitment"] > products["personal-loan"]["commitment"]
    assert products["credit-card"]["liquidity"] > products["personal-loan"]["liquidity"]
    assert products["personal-loan"]["income"] > products["credit-card"]["income"]
    assert products["personal-loan"]["capacity"] > products["credit-card"]["capacity"]
    assert products["student-loan"]["shock"] > products["personal-loan"]["shock"]
    assert products["student-loan"]["cross_border"] > products["personal-loan"]["cross_border"]


def test_structured_ingestion_deduplicates_and_scores(client: TestClient):
    applicant_id = create_applicant(client)
    response = client.post(f"/api/v1/applicants/{applicant_id}/evidence", json=statement_payload())
    assert response.status_code == 201, response.text
    assert response.json()["assertion_count"] == 6

    # A payroll assertion matching the first salary corroborates it rather than
    # creating a second scored event.
    corroboration = {
        "source_type": "payroll",
        "provider": "Employer payroll",
        "currency": "AED",
        "period_start": "2026-06-01",
        "period_end": "2026-06-01",
        "consent": True,
        "records": [
            {"occurred_on": "2026-06-01", "event_type": "payroll", "amount": 18000, "currency": "AED", "direction": "credit"}
        ],
    }
    assert client.post(f"/api/v1/applicants/{applicant_id}/evidence", json=corroboration).status_code == 201

    evidence = client.get(f"/api/v1/applicants/{applicant_id}/evidence")
    assert evidence.status_code == 200
    assert evidence.json()["assertion_count"] == 7
    assert evidence.json()["unique_event_count"] == 6
    assert evidence.json()["corroborated_count"] == 1
    assert any(event["status"] == "corroborated" for event in evidence.json()["events"])

    personal = client.get(f"/api/v1/applicants/{applicant_id}/score?product=personal-loan")
    card = client.get(f"/api/v1/applicants/{applicant_id}/score?product=credit-card")
    student = client.get(f"/api/v1/applicants/{applicant_id}/score?product=student-loan")
    assert personal.status_code == card.status_code == 200
    assert student.status_code == 200
    assert len(personal.json()["domains"]) == 7
    assert sum(domain["weight"] for domain in personal.json()["domains"]) == 100
    assert personal.json()["unique_event_count"] == 6
    assert personal.json()["reliability"] > 0
    assert personal.json()["reason_codes"]
    assert personal.json()["domains"] != card.json()["domains"]
    assert personal.json()["score"] != card.json()["score"]
    # Product weights are applied to the same observed events, so a profile
    # with uneven capacity and income should not collapse to one universal
    # score after rounding.
    assert len({personal.json()["score"], card.json()["score"], student.json()["score"]}) >= 2


def test_csv_statement_upload_persists_upload_and_recomputes_score(client: TestClient):
    applicant_id = create_applicant(client)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=["date", "amount", "direction", "description", "balance"])
    writer.writeheader()
    writer.writerow({"date": "2026-08-01", "amount": "18500", "direction": "credit", "description": "Salary", "balance": "22000"})
    writer.writerow({"date": "2026-08-02", "amount": "5000", "direction": "debit", "description": "Rent", "balance": "17000"})
    response = client.post(
        f"/api/v1/applicants/{applicant_id}/statements",
        files={"file": ("statement.csv", stream.getvalue().encode(), "text/csv")},
        data={"source_type": "bank-statement", "provider": "CSV Bank", "currency": "AED", "consent": "true"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["parsed_rows"] == 2
    assert response.json()["score"]["assertion_count"] == 2
    assert client.get(f"/api/v1/applicants/{applicant_id}/evidence").json()["unique_event_count"] == 2
    score = response.json()["score"]
    commitment_reason = next(reason for reason in score["reason_codes"] if reason["domain"] == "commitment")
    assert commitment_reason["code"] == "COMMITMENT_PAYMENTS_OBSERVED"
    assert "timeliness was not inferred" in commitment_reason["message"]

    unsupported = client.post(
        f"/api/v1/applicants/{applicant_id}/statements",
        files={"file": ("statement.xlsx", b"not parsed", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"source_type": "bank-statement", "provider": "CSV Bank", "currency": "AED", "consent": "true"},
    )
    assert unsupported.status_code == 422
    assert "XLSX" in unsupported.json()["detail"]


def test_capacity_is_neutral_when_income_cannot_be_classified(client: TestClient):
    applicant_id = create_applicant(client)
    response = client.post(
        f"/api/v1/applicants/{applicant_id}/evidence",
        json={
            "source_type": "bank-statement",
            "provider": "Applicant bank",
            "currency": "INR",
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "consent": True,
            "records": [
                {"occurred_on": "2026-01-05", "event_type": "loan_payment", "amount": 8000, "currency": "INR", "direction": "debit"},
                {"occurred_on": "2026-02-05", "event_type": "loan_payment", "amount": 8000, "currency": "INR", "direction": "debit"},
                {"occurred_on": "2026-03-05", "event_type": "loan_payment", "amount": 8000, "currency": "INR", "direction": "debit"},
            ],
        },
    )
    assert response.status_code == 201
    score = client.get(f"/api/v1/applicants/{applicant_id}/score").json()
    capacity = next(domain for domain in score["domains"] if domain["key"] == "capacity")
    assert capacity["observed"] == 50
    assert capacity["reason_codes"][0]["code"] == "CAPACITY_INCOME_UNCLASSIFIED"
    assert "capacity remained neutral" in capacity["reason_codes"][0]["message"]


def test_transition_is_persisted_and_score_neutral(client: TestClient):
    applicant_id = create_applicant(client)
    before = client.get(f"/api/v1/applicants/{applicant_id}/score").json()
    response = client.put(
        f"/api/v1/applicants/{applicant_id}/transition",
        json={"event": "returning-india", "country_from": "UAE", "country_to": "India", "facts": {"days_in_india": 190}},
    )
    assert response.status_code == 200
    assert len(response.json()["tasks"]) >= 3
    assert all(task["score_effect"] == "none" for task in response.json()["tasks"])
    saved = client.get(f"/api/v1/applicants/{applicant_id}/transition")
    assert saved.status_code == 200
    assert saved.json()["event"] == "returning-india"
    after = client.get(f"/api/v1/applicants/{applicant_id}/score").json()
    assert after["score"] == before["score"]


def test_empty_applicant_has_no_display_score(client: TestClient):
    applicant_id = create_applicant(client)
    applicant = client.get(f"/api/v1/applicants/{applicant_id}")
    assert applicant.status_code == 200
    assert applicant.json()["score"] is None
    assert applicant.json()["reliability"] == 0


def test_bad_consent_and_empty_csv_are_rejected(client: TestClient):
    applicant_id = create_applicant(client)
    response = client.post(
        f"/api/v1/applicants/{applicant_id}/statements",
        files={"file": ("statement.csv", b"date,amount\n2026-01-01,10\n", "text/csv")},
        data={"source_type": "bank-statement", "provider": "CSV Bank", "currency": "INR", "consent": "false"},
    )
    assert response.status_code == 400

    missing = client.post(
        f"/api/v1/applicants/{applicant_id}/statements",
        files={"file": ("statement.csv", b"description\nSalary\n", "text/csv")},
        data={"source_type": "bank-statement", "provider": "CSV Bank", "currency": "INR", "consent": "true"},
    )
    assert missing.status_code == 422


def test_model_validation_includes_real_secondary_artifact(tmp_path: Path):
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps({"pipeline_version": "test", "classification": {"metrics": {"roc_auc": 0.7}}}))
    metrics_path.with_name("secondary_heloc_metrics.json").write_text(
        json.dumps({"task": "bureau_score_regression", "metrics": {"r2": 0.8}})
    )
    settings = Settings(
        db_path=str(tmp_path / "credit-passport.db"),
        cors_origins=("http://localhost:5173",),
        max_upload_bytes=1024 * 1024,
        model_metrics_path=str(metrics_path),
    )
    with TestClient(create_app(settings)) as test_client:
        response = test_client.get("/api/v1/model/validation")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["metrics"]["secondary_benchmarks"]["heloc_external_risk"]["metrics"]["r2"] == 0.8

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _settings(tmp_path: Path, artifact_path: str) -> Settings:
    return Settings(
        db_path=str(tmp_path / "credit-passport.db"),
        cors_origins=("http://localhost:5173",),
        max_upload_bytes=1024 * 1024,
        model_metrics_path=str(tmp_path / "missing-metrics.json"),
        challenger_model_artifact_path=artifact_path,
    )


def _artifact(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "artifact_version": "icp-challenger-test-v1",
                "model_name": "icp-adverse-risk-test",
                "task": "adverse_outcome_probability",
                "feature_names": ["unique_event_count", "income_total", "commitment_total"],
                "coefficients": {
                    "unique_event_count": -0.1,
                    "income_total": -0.00001,
                    "commitment_total": 0.00001,
                },
                "intercept": 0.2,
                "blend_weight": 0.2,
                "risk_thresholds": {"low_max": 0.2, "high_min": 0.45},
                "validation_summary": {
                    "status": "research_only",
                    "dataset": "test-contract-data",
                    "metrics": {"roc_auc": 0.61},
                },
                "provenance": {
                    "synthetic": True,
                    "training_data": "test-contract-data",
                    "note": "Contract test artifact; not a lending decision model.",
                },
            }
        ),
        encoding="utf-8",
    )


def _create_applicant(client: TestClient) -> str:
    response = client.post(
        "/api/v1/applicants",
        json={
            "name": "Contract Applicant",
            "corridor": "UAE → India",
            "product": "personal-loan",
            "requested_amount": 600000,
            "currency": "INR",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _add_evidence(client: TestClient, applicant_id: str) -> None:
    response = client.post(
        f"/api/v1/applicants/{applicant_id}/evidence",
        json={
            "source_type": "bank-statement",
            "provider": "Applicant bank",
            "currency": "AED",
            "period_start": "2026-06-01",
            "period_end": "2026-08-02",
            "consent": True,
            "records": [
                {"occurred_on": "2026-06-01", "event_type": "salary", "amount": 18000, "currency": "AED", "direction": "credit"},
                {"occurred_on": "2026-06-02", "event_type": "rent", "amount": 5000, "currency": "AED", "direction": "debit", "due_on": "2026-06-02", "paid_on": "2026-06-02"},
                {"occurred_on": "2026-07-01", "event_type": "salary", "amount": 18000, "currency": "AED", "direction": "credit"},
                {"occurred_on": "2026-07-02", "event_type": "rent", "amount": 5000, "currency": "AED", "direction": "debit", "due_on": "2026-07-02", "paid_on": "2026-07-02"},
            ],
        },
    )
    assert response.status_code == 201, response.text


def test_challenger_returns_probability_features_and_blend(tmp_path: Path) -> None:
    artifact = tmp_path / "icp-challenger.json"
    _artifact(artifact)
    with TestClient(create_app(_settings(tmp_path, str(artifact)))) as client:
        applicant_id = _create_applicant(client)
        _add_evidence(client, applicant_id)
        response = client.get(f"/api/v1/applicants/{applicant_id}/challenger-score?product=personal-loan")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applicant_id"] == applicant_id
    assert body["task"] == "adverse_outcome_probability"
    assert 0 <= body["probability"] <= 1
    assert body["risk_band"] in {"low", "medium", "high"}
    assert set(body["feature_values"]) == {"unique_event_count", "income_total", "commitment_total"}
    assert body["artifact_version"] == "icp-challenger-test-v1"
    assert body["validation_summary"]["dataset"] == "test-contract-data"
    assert body["provenance"]["synthetic"] is True
    assert body["blend"]["decision_use"] == "research-only"
    assert body["blend"]["model_weight"] == 0.2
    assert 0 <= body["blend"]["blended_score"] <= 100


def test_challenger_fails_explicitly_when_artifact_is_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing-icp-challenger.json"
    with TestClient(create_app(_settings(tmp_path, str(missing)))) as client:
        applicant_id = _create_applicant(client)
        _add_evidence(client, applicant_id)
        response = client.get(f"/api/v1/applicants/{applicant_id}/challenger-score")

    assert response.status_code == 503
    assert "challenger artifact was not found" in response.json()["detail"]


def test_challenger_does_not_guess_for_empty_evidence(tmp_path: Path) -> None:
    artifact = tmp_path / "icp-challenger.json"
    _artifact(artifact)
    with TestClient(create_app(_settings(tmp_path, str(artifact)))) as client:
        applicant_id = _create_applicant(client)
        response = client.get(f"/api/v1/applicants/{applicant_id}/challenger-score")

    assert response.status_code == 422
    assert "at least one ingested evidence event" in response.json()["detail"]

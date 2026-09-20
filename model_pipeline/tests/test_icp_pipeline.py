"""Tests for the synthetic ICP event-native model track."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from credit_passport_model.synthetic import (
    EVENT_FEATURES,
    MODEL_FEATURES,
    PERSON_ID_COLUMN,
    QUALITY_FEATURES,
    TARGET_COLUMN,
    TIME_COLUMN,
    chronological_person_disjoint_split,
    eligible_for_inference,
    feature_contract,
    generate_synthetic_cohort,
)


def test_synthetic_cohort_is_reproducible_and_covers_requested_segments() -> None:
    first = generate_synthetic_cohort(rows=1_200, random_state=20260920)
    second = generate_synthetic_cohort(rows=1_200, random_state=20260920)
    pd.testing.assert_frame_equal(first, second)
    assert set(first["product_type"]) == {"credit-card", "personal-loan", "student-loan"}
    assert set(first["worker_profile"]) == {"migrant-professional", "gig-worker", "student"}
    assert set(first["corridor"]) == {"corridor-a", "corridor-b", "corridor-c"}
    assert set(first[TARGET_COLUMN]) == {0, 1}
    assert first[PERSON_ID_COLUMN].is_unique
    assert first[list(MODEL_FEATURES)].notna().sum(axis=1).min() >= 12


def test_split_is_time_forward_and_person_disjoint() -> None:
    frame = generate_synthetic_cohort(rows=1_200, random_state=7)
    train, calibration, test = chronological_person_disjoint_split(frame)
    train_people = set(train[PERSON_ID_COLUMN])
    calibration_people = set(calibration[PERSON_ID_COLUMN])
    test_people = set(test[PERSON_ID_COLUMN])
    assert train_people.isdisjoint(calibration_people)
    assert train_people.isdisjoint(test_people)
    assert calibration_people.isdisjoint(test_people)
    assert train[TIME_COLUMN].max() < calibration[TIME_COLUMN].min()
    assert calibration[TIME_COLUMN].max() < test[TIME_COLUMN].min()
    assert len(train) + len(calibration) + len(test) == len(frame)


def test_contract_excludes_quality_and_sensitive_feature_families() -> None:
    contract = feature_contract()
    assert contract["feature_order"] == list(MODEL_FEATURES)
    assert set(QUALITY_FEATURES).isdisjoint(MODEL_FEATURES)
    assert set(MODEL_FEATURES).issubset(EVENT_FEATURES)
    serialised = json.dumps(
        {
            "feature_order": contract["feature_order"],
            "features": contract["features"],
        }
    ).lower()
    for forbidden in ("fico", "age", "sex", "nationality", "employer", "school", "gps", "contacts", "social"):
        assert forbidden not in serialised


def test_training_exports_a_loadable_calibrated_model(tmp_path: Path) -> None:
    # Import the script as a module so tests exercise the same exporter as the
    # reproducible CLI without relying on a pre-existing local artifact.
    from train_icp_model import export_icp_artifacts

    result = export_icp_artifacts(output_dir=tmp_path, rows=900, random_state=20260920)
    model_path = tmp_path / "icp_challenger.joblib"
    metrics_path = tmp_path / "icp_metrics.json"
    contract_path = tmp_path / "icp_feature_contract.json"
    sidecar_path = tmp_path / "icp_challenger.json"
    assert model_path.exists()
    assert metrics_path.exists()
    assert contract_path.exists()
    assert sidecar_path.exists()
    payload = joblib.load(model_path)
    assert payload["feature_names"] == list(MODEL_FEATURES)
    model = payload["model"]
    frame = generate_synthetic_cohort(rows=30, random_state=88)
    probabilities = model.predict_proba(frame.loc[:, list(MODEL_FEATURES)])
    assert probabilities.shape == (30, 2)
    assert np.isfinite(probabilities).all()
    assert np.allclose(probabilities.sum(axis=1), 1.0)
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics["synthetic"] is True
    assert metrics["metrics"]["roc_auc"] > 0.5
    assert metrics["metrics"]["pr_auc_average_precision"] > metrics["baseline_constant_prevalence"]["pr_auc_average_precision"]
    assert metrics["metrics"]["brier"] < metrics["baseline_constant_prevalence"]["brier"]
    assert result["contract"]["feature_order"] == list(MODEL_FEATURES)


def test_model_coverage_gate_abstains_on_sparse_input(tmp_path: Path) -> None:
    from train_icp_model import export_icp_artifacts

    export_icp_artifacts(output_dir=tmp_path, rows=600, random_state=20260920)
    model = joblib.load(tmp_path / "icp_challenger.joblib")["model"]
    frame = generate_synthetic_cohort(rows=30, random_state=123).loc[:, list(MODEL_FEATURES)].copy().iloc[:3].copy()
    frame.iloc[0, 1:10] = np.nan
    probabilities, abstain = model.predict_with_abstention(frame)
    assert abstain.tolist() == [True, False, False]
    assert np.isnan(probabilities[0]).all()
    assert np.isfinite(probabilities[1:]).all()
    assert eligible_for_inference(frame, minimum_domains=12).tolist() == [False, True, True]

"""Integration tests that require the checked public-data run.

These tests intentionally do not use fabricated rows or fixtures. If a fresh
checkout has no raw data/artifacts, the failure points to the exact reproducible
commands needed to create them.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd

from credit_passport_model.data import DATASETS, RAW_DIR, ARTIFACT_DIR, sha256_file


ROOT = Path(__file__).resolve().parents[1]
METRICS_PATH = ARTIFACT_DIR / "metrics.json"
SECONDARY_METRICS_PATH = ARTIFACT_DIR / "secondary_heloc_metrics.json"


def _require_file(path: Path) -> Path:
    assert path.exists(), f"missing real-data artifact {path}; run the documented pipeline first"
    return path


def test_lendingclub_source_is_exact_pinned_public_file() -> None:
    path = _require_file(RAW_DIR / DATASETS["lendingclub"].filename)
    assert sha256_file(path) == DATASETS["lendingclub"].sha256
    sample = pd.read_csv(path, nrows=4)
    assert sample.shape == (4, 15)
    assert set(["fico_n", "Default", "revenue", "dti_n"]).issubset(sample.columns)


def test_primary_metrics_are_held_out_and_baselined() -> None:
    metrics = json.loads(_require_file(METRICS_PATH).read_text(encoding="utf-8"))
    assert metrics["regression"]["rows"] == {
        "total": 1_347_681,
        "train": 808_608,
        "calibration": 269_536,
        "test": 269_537,
    }
    assert metrics["classification"]["rows"] == metrics["regression"]["rows"]
    assert metrics["regression"]["metrics"]["mae"] < metrics["regression"]["baseline_mean_predictor"]["mae"]
    assert metrics["classification"]["metrics"]["roc_auc"] > 0.5
    assert metrics["classification"]["metrics"]["brier"] < metrics["classification"]["baseline_constant_prevalence"]["brier"]
    assert metrics["classification"]["metrics"]["expected_calibration_error_10_bins"] < 0.02


def test_primary_feature_policy_excludes_sensitive_or_leaky_fields() -> None:
    metrics = json.loads(_require_file(METRICS_PATH).read_text(encoding="utf-8"))
    forbidden = {
        "id",
        "issue_d",
        "zip_code",
        "addr_state",
        "title",
        "desc",
        "SEX",
        "AGE",
        "EDUCATION",
        "MARRIAGE",
    }
    for task in ("regression", "classification"):
        assert forbidden.isdisjoint(metrics[task]["features"])
    assert "fico_n" not in metrics["regression"]["features"]
    assert "Default" not in metrics["regression"]["features"]


def test_exported_artifacts_load_and_score_real_rows() -> None:
    metrics = json.loads(_require_file(METRICS_PATH).read_text(encoding="utf-8"))
    sample = pd.read_csv(RAW_DIR / DATASETS["lendingclub"].filename, nrows=3)
    regressor = joblib.load(_require_file(ARTIFACT_DIR / "lendingclub_fico_regressor.joblib"))
    classifier = joblib.load(
        _require_file(ARTIFACT_DIR / "lendingclub_default_classifier_calibrated.joblib")
    )
    reg_features = metrics["regression"]["features"]
    cls_features = metrics["classification"]["features"]
    regression_output = regressor.predict(sample[reg_features])
    class_output = classifier.predict_proba(sample[cls_features])
    assert len(regression_output) == 3
    assert class_output.shape == (3, 2)
    assert ((class_output >= 0) & (class_output <= 1)).all()
    assert (class_output.sum(axis=1) > 0.999).all()


def test_secondary_heloc_metric_excludes_invalid_targets() -> None:
    metrics = json.loads(_require_file(SECONDARY_METRICS_PATH).read_text(encoding="utf-8"))
    rows = metrics["rows"]
    assert rows["source_total"] == 10_459
    assert rows["target_valid_retained"] == 9_861
    assert rows["target_invalid_excluded"] == 598
    assert 0 <= metrics["target_summary"]["min"] <= metrics["target_summary"]["max"] <= 100
    assert metrics["metrics"]["r2"] > metrics["baseline_mean_predictor"]["r2"]

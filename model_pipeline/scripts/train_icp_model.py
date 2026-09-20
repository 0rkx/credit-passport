#!/usr/bin/env python3
"""Train and export the synthetic ICP event-native adverse-risk model.

The script creates a deterministic synthetic cohort, performs a chronological
person-disjoint split, fits a nonlinear classifier, calibrates it on the middle
time block, evaluates only on the latest untouched block, and exports the
artifact plus its contract and validation evidence.  The resulting model is a
research/serving integration artifact, not a production underwriting model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit_passport_model.data import ARTIFACT_DIR  # noqa: E402
from credit_passport_model.model import ICPCalibratedClassifier  # noqa: E402
from credit_passport_model.synthetic import (  # noqa: E402
    MODEL_FEATURES,
    RANDOM_STATE,
    SYNTHETIC_DATASET_VERSION,
    TARGET_COLUMN,
    cohort_coverage,
    chronological_person_disjoint_split,
    eligible_for_inference,
    feature_contract,
    generate_synthetic_cohort,
)


MINIMUM_POPULATED_FEATURES = len(MODEL_FEATURES) - 8
ARTIFACT_VERSION = "icp-challenger-2026.09.20"
MODEL_NAME = "icp_event_native_adverse_risk"
TASK = "adverse_outcome_probability"


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def expected_calibration_error(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    bins: int = 10,
) -> float:
    """Calculate weighted absolute calibration error in fixed probability bins."""

    edges = np.linspace(0.0, 1.0, bins + 1)
    ece = 0.0
    for lower, upper in zip(edges[:-1], edges[1:], strict=True):
        mask = (probabilities >= lower) & (
            probabilities < upper if upper < 1.0 else probabilities <= upper
        )
        if not np.any(mask):
            continue
        ece += float(np.mean(mask)) * abs(
            float(np.mean(probabilities[mask])) - float(np.mean(y_true[mask]))
        )
    return ece


def _base_classifier(random_state: int) -> Pipeline:
    return Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(strategy="median", add_indicator=True),
            ),
            (
                "classifier",
                HistGradientBoostingClassifier(
                    max_iter=220,
                    learning_rate=0.045,
                    max_leaf_nodes=21,
                    min_samples_leaf=35,
                    l2_regularization=1.25,
                    random_state=random_state,
                ),
            ),
        ]
    )


def _metric_bundle(y_true: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    fraction_of_positives, mean_predicted_value = calibration_curve(
        y_true,
        probabilities,
        n_bins=10,
        strategy="uniform",
    )
    return {
        "roc_auc": float(roc_auc_score(y_true, probabilities)),
        "pr_auc_average_precision": float(average_precision_score(y_true, probabilities)),
        "brier": float(brier_score_loss(y_true, probabilities)),
        "expected_calibration_error_10_bins": float(
            expected_calibration_error(y_true, probabilities, bins=10)
        ),
        "calibration_curve_10_uniform_bins": {
            "fraction_of_positives": fraction_of_positives,
            "mean_predicted_value": mean_predicted_value,
        },
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def train_icp_model(
    frame: pd.DataFrame | None = None,
    *,
    rows: int = 12_000,
    random_state: int = RANDOM_STATE,
) -> tuple[ICPCalibratedClassifier, dict[str, Any], dict[str, object]]:
    """Train the calibrated classifier and return it with metrics/contract."""

    cohort = frame.copy() if frame is not None else generate_synthetic_cohort(
        rows=rows,
        random_state=random_state,
    )
    missing = set(MODEL_FEATURES + (TARGET_COLUMN,)) - set(cohort.columns)
    if missing:
        raise ValueError(f"synthetic cohort is missing required columns: {sorted(missing)}")
    train, calibration, test = chronological_person_disjoint_split(cohort)
    x_train = train.loc[:, list(MODEL_FEATURES)]
    x_calibration = calibration.loc[:, list(MODEL_FEATURES)]
    x_test = test.loc[:, list(MODEL_FEATURES)]
    y_train = train[TARGET_COLUMN].astype("int64").to_numpy()
    y_calibration = calibration[TARGET_COLUMN].astype("int64").to_numpy()
    y_test = test[TARGET_COLUMN].astype("int64").to_numpy()

    base = _base_classifier(random_state)
    base.fit(x_train, y_train)
    calibration_eligible = eligible_for_inference(
        calibration,
        minimum_domains=MINIMUM_POPULATED_FEATURES,
    )
    calibration_scores = np.asarray(base.decision_function(x_calibration)).reshape(-1)
    calibration_scores = calibration_scores[calibration_eligible]
    calibration_labels = y_calibration[calibration_eligible]
    if len(np.unique(calibration_labels)) < 2:
        raise ValueError("calibration partition must contain both outcome classes")
    calibrator = LogisticRegression(
        solver="lbfgs",
        max_iter=1000,
        random_state=random_state,
    )
    calibrator.fit(calibration_scores.reshape(-1, 1), calibration_labels)
    classifier = ICPCalibratedClassifier(
        base_estimator=base,
        calibrator=calibrator,
        feature_order=MODEL_FEATURES,
        minimum_populated_features=MINIMUM_POPULATED_FEATURES,
    )

    test_probabilities = classifier.predict_proba(x_test)[:, 1]
    test_abstain = classifier.abstain_mask(x_test)
    evaluation_mask = ~test_abstain
    if evaluation_mask.sum() < 100 or len(np.unique(y_test[evaluation_mask])) < 2:
        raise ValueError("latest test partition has insufficient eligible class coverage")
    eligible_y = y_test[evaluation_mask]
    eligible_probabilities = test_probabilities[evaluation_mask]
    baseline_probability = float(y_train.mean())
    baseline_probabilities = np.full(len(eligible_y), baseline_probability)
    metrics = {
        "pipeline_version": "0.2.0",
        "artifact_version": ARTIFACT_VERSION,
        "model_name": MODEL_NAME,
        "task": TASK,
        "dataset": SYNTHETIC_DATASET_VERSION,
        "synthetic": True,
        "random_state": random_state,
        "target": {
            "name": TARGET_COLUMN,
            "positive_class": "1 = >=30 days past due or adverse restructure within 90 days",
            "negative_class": "0 = current or paid as agreed through 90 days",
        },
        "features": list(MODEL_FEATURES),
        "rows": {
            "total": len(cohort),
            "train": len(train),
            "calibration": len(calibration),
            "test": len(test),
            "calibration_eligible": int(calibration_eligible.sum()),
            "test_eligible": int(evaluation_mask.sum()),
            "test_abstained": int(test_abstain.sum()),
        },
        "metrics": _metric_bundle(eligible_y, eligible_probabilities),
        "baseline_constant_prevalence": _metric_bundle(eligible_y, baseline_probabilities),
        "test_prevalence": float(np.mean(eligible_y)),
        "coverage": {
            "test_eligible_rate": float(np.mean(evaluation_mask)),
            "minimum_populated_model_features": MINIMUM_POPULATED_FEATURES,
            "abstention_rule": "abstain when requested_amount is null or fewer than 12 of 20 model features are populated",
        },
        "split": {
            "method": "chronological 60/20/20 by first application month",
            "person_disjoint": True,
            "calibration": "Platt sigmoid fitted only on the middle time partition",
            "test_untouched_until_final_evaluation": True,
        },
        "cohort": cohort_coverage(cohort),
        "limitations": [
            "All rows are algorithmically generated synthetic data; no real person or source record is represented.",
            "Synthetic metrics do not establish performance in India, any migration corridor, or any lending portfolio.",
            "A calibrated probability is not an approval, pricing, eligibility, or adverse-action decision.",
            "Production use requires real consented validation data, subgroup checks, drift monitoring, governance, and human review.",
        ],
    }
    contract = feature_contract()
    contract = {
        **contract,
        "artifact_version": ARTIFACT_VERSION,
        "model_name": MODEL_NAME,
        "task": TASK,
        "feature_order": list(MODEL_FEATURES),
    }
    return classifier, _json_safe(metrics), contract


def export_icp_artifacts(
    *,
    output_dir: Path = ARTIFACT_DIR,
    rows: int = 12_000,
    random_state: int = RANDOM_STATE,
) -> dict[str, Any]:
    """Train and write the joblib artifact, sidecar metadata, metrics and contract."""

    output_dir.mkdir(parents=True, exist_ok=True)
    classifier, metrics, contract = train_icp_model(
        rows=rows,
        random_state=random_state,
    )
    metrics = dict(metrics)
    artifact_path = output_dir / "icp_challenger.joblib"
    sidecar_path = output_dir / "icp_challenger.json"
    metrics_path = output_dir / "icp_metrics.json"
    contract_path = output_dir / "icp_feature_contract.json"
    validation_summary = {
        "metrics": metrics["metrics"],
        "baseline_constant_prevalence": metrics["baseline_constant_prevalence"],
        "rows": metrics["rows"],
        "coverage": metrics["coverage"],
        "split": metrics["split"],
        "synthetic": True,
    }
    provenance = {
        "synthetic": True,
        "dataset": SYNTHETIC_DATASET_VERSION,
        "generator": "credit_passport_model.synthetic.generate_synthetic_cohort",
        "random_state": random_state,
        "rows": rows,
        "target_definition": ">=30 days past due or adverse restructure within 90 days",
        "model_features_are_event_native": True,
        "quality_fields_are_not_model_features": True,
        "notice": "Research/integration artifact only; synthetic-to-real transfer is unvalidated.",
    }
    metadata = {
        "artifact_version": ARTIFACT_VERSION,
        "model_name": MODEL_NAME,
        "task": TASK,
        "feature_names": list(MODEL_FEATURES),
        "blend_weight": 0.35,
        "risk_thresholds": {"low_max": 0.20, "high_min": 0.40},
        "validation_summary": validation_summary,
        "provenance": provenance,
        "feature_contract": str(contract_path),
        "metrics_artifact": str(metrics_path),
        "model_artifact": str(artifact_path),
    }
    joblib.dump({**metadata, "model": classifier}, artifact_path, compress=3)
    sidecar_path.write_text(json.dumps(_json_safe(metadata), indent=2) + "\n", encoding="utf-8")
    metrics["artifacts"] = {
        "model": str(artifact_path),
        "metadata": str(sidecar_path),
        "metrics": str(metrics_path),
        "feature_contract": str(contract_path),
        "model_sha256": _sha256(artifact_path),
    }
    metrics_path.write_text(json.dumps(_json_safe(metrics), indent=2) + "\n", encoding="utf-8")
    contract_path.write_text(json.dumps(_json_safe(contract), indent=2) + "\n", encoding="utf-8")
    return _json_safe({"metrics": metrics, "contract": contract})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=12_000)
    parser.add_argument("--random-state", type=int, default=RANDOM_STATE)
    parser.add_argument("--output-dir", type=Path, default=ARTIFACT_DIR)
    args = parser.parse_args()
    try:
        result = export_icp_artifacts(
            output_dir=args.output_dir,
            rows=args.rows,
            random_state=args.random_state,
        )
    except Exception as exc:  # noqa: BLE001 - CLI reports exact failure
        print(f"ICP training failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Train, calibrate, evaluate, and export the two real-data models."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit_passport_model.data import (  # noqa: E402
    ARTIFACT_DIR,
    DATASETS,
    download_dataset,
    load_lendingclub,
    write_data_manifest,
)
from credit_passport_model.model import PlattCalibratedClassifier  # noqa: E402


RANDOM_STATE = 20260920


def _split_indices(
    frame: pd.DataFrame,
    target: pd.Series,
    stratify: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.DataFrame, pd.DataFrame]:
    """Return fixed 60/20/20 train/calibration/test partitions."""

    train, holdout, y_train, y_holdout = train_test_split(
        frame,
        target,
        test_size=0.4,
        random_state=RANDOM_STATE,
        stratify=stratify,
    )
    holdout_stratify = y_holdout if stratify is not None else None
    calibration, test, y_calibration, y_test = train_test_split(
        holdout,
        y_holdout,
        test_size=0.5,
        random_state=RANDOM_STATE,
        stratify=holdout_stratify,
    )
    return train, calibration, y_train, y_calibration, test, y_test


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def train_heloc_regressor(heloc: pd.DataFrame) -> tuple[Pipeline, dict[str, Any]]:
    """Predict x1/ExternalRiskEstimate from x2..x23, with no score leakage."""

    target_column = "x1"
    feature_columns = [f"x{i}" for i in range(2, 24)]
    raw_rows = len(heloc)
    valid_target = heloc[target_column].between(0, 100)
    if not valid_target.any():
        raise ValueError("HELOC has no valid ExternalRiskEstimate targets")
    heloc = heloc.loc[valid_target].copy()
    x = heloc.loc[:, feature_columns].copy(deep=True)
    x = x.mask(x.isin([-7, -8, -9]))
    y = heloc[target_column]
    x_train, x_cal, y_train, y_cal, x_test, y_test = _split_indices(x, y)
    # The calibration partition is retained for symmetry and future conformal
    # interval work; regression metrics remain on the untouched test partition.
    model = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            (
                "regressor",
                HistGradientBoostingRegressor(
                    max_iter=300,
                    learning_rate=0.05,
                    max_leaf_nodes=15,
                    l2_regularization=1.0,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)
    baseline_prediction = float(y_train.mean())
    baseline_predictions = np.full(len(y_test), baseline_prediction)
    metrics = {
        "task": "bureau_score_regression",
        "dataset": "FICO HELOC challenge data",
        "target": "ExternalRiskEstimate (x1)",
        "features": feature_columns,
        "rows": {
            "source_total": raw_rows,
            "target_valid_retained": len(heloc),
            "target_invalid_excluded": raw_rows - len(heloc),
            "train": len(x_train),
            "calibration_reserved": len(x_cal),
            "test": len(x_test),
        },
        "metrics": {
            "mae": mean_absolute_error(y_test, predictions),
            "rmse": float(np.sqrt(mean_squared_error(y_test, predictions))),
            "r2": r2_score(y_test, predictions),
        },
        "baseline_mean_predictor": {
            "mae": mean_absolute_error(y_test, baseline_predictions),
            "rmse": float(np.sqrt(mean_squared_error(y_test, baseline_predictions))),
            "r2": r2_score(y_test, baseline_predictions),
        },
        "target_summary": {
            "min": y.min(),
            "max": y.max(),
            "mean": y.mean(),
            "test_mean": y_test.mean(),
        },
        "missing_value_codes_treated_as_missing": [-7, -8, -9],
        "target_valid_range": "0 <= ExternalRiskEstimate <= 100",
        "split": "random 60/20/20; seed 20260920",
        "limitations": [
            "An anonymised US HELOC cohort, not India or migrant financial evidence.",
            "x1 is a bureau-like benchmark field, not an approved lending decision target.",
        ],
    }
    return model, _json_safe(metrics)


def _uci_classifier_pipeline() -> Pipeline:
    categorical = ["SEX", "EDUCATION", "MARRIAGE"]
    numeric = [
        "LIMIT_BAL",
        "AGE",
        "PAY_0",
        "PAY_2",
        "PAY_3",
        "PAY_4",
        "PAY_5",
        "PAY_6",
        "BILL_AMT1",
        "BILL_AMT2",
        "BILL_AMT3",
        "BILL_AMT4",
        "BILL_AMT5",
        "BILL_AMT6",
        "PAY_AMT1",
        "PAY_AMT2",
        "PAY_AMT3",
        "PAY_AMT4",
        "PAY_AMT5",
        "PAY_AMT6",
    ]
    preprocessor = ColumnTransformer(
        transformers=[
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical,
            ),
            (
                "numeric",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric,
            ),
        ],
        remainder="drop",
    )
    return Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            (
                "classifier",
                LogisticRegression(
                    C=0.5,
                    max_iter=3000,
                    solver="lbfgs",
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def _expected_calibration_error(y_true: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    ece = 0.0
    for lower, upper in zip(edges[:-1], edges[1:]):
        mask = (probabilities >= lower) & (
            probabilities < upper if upper < 1.0 else probabilities <= upper
        )
        if not np.any(mask):
            continue
        ece += float(np.mean(mask)) * abs(float(np.mean(probabilities[mask])) - float(np.mean(y_true[mask])))
    return ece


def train_uci_classifier(uci: pd.DataFrame) -> tuple[CalibratedClassifierCV, dict[str, Any]]:
    target = "default_next_month"
    feature_columns = [column for column in uci.columns if column not in {"ID", target}]
    x = uci[feature_columns]
    y = uci[target].astype("int64")
    x_train, x_cal, y_train, y_cal, x_test, y_test = _split_indices(x, y, stratify=y)
    # Keep the calibration partition size in the report; calibrated metrics are
    # evaluated only on x_test.
    base = _uci_classifier_pipeline()
    # Five-fold sigmoid calibration is fitted only inside the training partition;
    # x_test remains untouched until final evaluation.
    calibrated = CalibratedClassifierCV(base, method="sigmoid", cv=5, n_jobs=-1)
    calibrated.fit(x_train, y_train)
    probabilities = calibrated.predict_proba(x_test)[:, 1]
    predicted = (probabilities >= 0.5).astype("int64")
    fraction_of_positives, mean_predicted_value = calibration_curve(
        y_test, probabilities, n_bins=10, strategy="uniform"
    )
    metrics = {
        "task": "repayment_default_classification",
        "dataset": "UCI Default of Credit Card Clients",
        "target": "default payment next month",
        "positive_class": "1 = default",
        "features": feature_columns,
        "rows": {"total": len(uci), "train": len(x_train), "calibration_reserved": len(x_cal), "test": len(x_test)},
        "metrics": {
            "roc_auc": roc_auc_score(y_test, probabilities),
            "pr_auc_average_precision": average_precision_score(y_test, probabilities),
            "brier": brier_score_loss(y_test, probabilities),
            "expected_calibration_error_10_bins": _expected_calibration_error(
                y_test.to_numpy(), probabilities, bins=10
            ),
        },
        "test_prevalence": float(np.mean(y_test)),
        "calibration_curve_10_uniform_bins": {
            "fraction_of_positives": fraction_of_positives,
            "mean_predicted_value": mean_predicted_value,
        },
        "split": "stratified random 60/20/20; seed 20260920; sigmoid 5-fold calibration on training only",
        "limitations": [
            "Taiwan credit-card cohort from 2005, not India or a migrant cohort.",
            "Published benchmark fields include demographic variables; governance review is required before any use.",
            "A benchmark probability is not a policy threshold or an approval recommendation.",
        ],
    }
    return calibrated, _json_safe(metrics)


def _lendingclub_partitions(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Create a chronological 60/20/20 split using application month."""

    ordered = frame.copy()
    ordered["_issue_date"] = pd.to_datetime(ordered["issue_d"], format="%b-%Y", errors="raise")
    ordered = ordered.sort_values(["_issue_date", "id"], kind="mergesort").drop(columns="_issue_date")
    first = int(len(ordered) * 0.60)
    second = int(len(ordered) * 0.80)
    return ordered.iloc[:first].copy(), ordered.iloc[first:second].copy(), ordered.iloc[second:].copy()


def _lendingclub_preprocessor(feature_columns: list[str]) -> ColumnTransformer:
    numeric = [
        column
        for column in ["revenue", "dti_n", "loan_amnt", "fico_n", "experience_c"]
        if column in feature_columns
    ]
    categorical = [
        column
        for column in ["emp_length", "purpose", "home_ownership_n", "addr_state"]
        if column in feature_columns
    ]
    transformers: list[tuple[str, Pipeline, list[str]]] = []
    if numeric:
        transformers.append(
            (
                "numeric",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric,
            )
        )
    if categorical:
        transformers.append(
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=True)),
                    ]
                ),
                categorical,
            )
        )
    return ColumnTransformer(transformers=transformers, remainder="drop")


def train_lendingclub_models(
    loans: pd.DataFrame,
) -> tuple[Pipeline, PlattCalibratedClassifier, dict[str, Any]]:
    """Train paired models on the Zenodo LendingClub granting dataset.

    The chronological split approximates deployment: earlier applications are
    used for fitting, the next period is reserved for sigmoid calibration, and
    the latest period is an untouched test set.
    """

    train, calibration, test = _lendingclub_partitions(loans)
    regression_features = [
        "revenue",
        "dti_n",
        "loan_amnt",
        "experience_c",
        "emp_length",
        "purpose",
        "home_ownership_n",
    ]
    classification_features = [
        "revenue",
        "dti_n",
        "loan_amnt",
        "fico_n",
        "experience_c",
        "emp_length",
        "purpose",
        "home_ownership_n",
    ]
    if any(column not in loans.columns for column in regression_features + classification_features):
        raise ValueError("LendingClub schema does not contain the declared application features")

    # Regression: bureau/FICO field from non-score applicant metrics only.
    regression_preprocessor = ColumnTransformer(
        transformers=[
            (
                "numeric",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
                    ]
                ),
                ["revenue", "dti_n", "loan_amnt", "experience_c"],
            ),
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        (
                            "ordinal",
                            OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
                        ),
                    ]
                ),
                ["emp_length", "purpose", "home_ownership_n"],
            ),
        ],
        remainder="drop",
    )
    regressor = Pipeline(
        steps=[
            ("preprocessor", regression_preprocessor),
            (
                "regressor",
                HistGradientBoostingRegressor(
                    max_iter=160,
                    learning_rate=0.05,
                    max_leaf_nodes=31,
                    l2_regularization=1.0,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )
    regressor.fit(train[regression_features], train["fico_n"])
    regression_predictions = regressor.predict(test[regression_features])
    regression_baseline_prediction = float(train["fico_n"].mean())
    regression_baseline_predictions = np.full(len(test), regression_baseline_prediction)

    # Classification: application-time features, including the observed FICO
    # field, predict final Default. No post-origination variables are present
    # in this Zenodo granting-model extract.
    base_classifier = Pipeline(
        steps=[
            ("preprocessor", _lendingclub_preprocessor(classification_features)),
            (
                "classifier",
                SGDClassifier(
                    loss="log_loss",
                    alpha=1e-6,
                    max_iter=40,
                    tol=1e-3,
                    average=True,
                    random_state=RANDOM_STATE,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    base_classifier.fit(train[classification_features], train["Default"])
    calibration_scores = base_classifier.decision_function(calibration[classification_features])
    platt = LogisticRegression(solver="lbfgs", max_iter=1000, random_state=RANDOM_STATE)
    platt.fit(np.asarray(calibration_scores).reshape(-1, 1), calibration["Default"])
    classifier = PlattCalibratedClassifier(base_classifier, platt)

    test_probabilities = classifier.predict_proba(test[classification_features])[:, 1]
    classification_baseline_probability = float(train["Default"].mean())
    classification_baseline_probabilities = np.full(len(test), classification_baseline_probability)
    fraction_of_positives, mean_predicted_value = calibration_curve(
        test["Default"], test_probabilities, n_bins=10, strategy="uniform"
    )
    regression_metrics = {
        "task": "bureau_score_regression",
        "dataset": "Lending Club loan dataset for granting models",
        "target": "fico_n",
        "features": regression_features,
        "rows": {
            "total": len(loans),
            "train": len(train),
            "calibration": len(calibration),
            "test": len(test),
        },
        "metrics": {
            "mae": mean_absolute_error(test["fico_n"], regression_predictions),
            "rmse": float(np.sqrt(mean_squared_error(test["fico_n"], regression_predictions))),
            "r2": r2_score(test["fico_n"], regression_predictions),
        },
        "baseline_mean_predictor": {
            "mae": mean_absolute_error(test["fico_n"], regression_baseline_predictions),
            "rmse": float(np.sqrt(mean_squared_error(test["fico_n"], regression_baseline_predictions))),
            "r2": r2_score(test["fico_n"], regression_baseline_predictions),
        },
        "test_target_summary": {
            "min": test["fico_n"].min(),
            "max": test["fico_n"].max(),
            "mean": test["fico_n"].mean(),
        },
        "split": "chronological 60/20/20 by issue_d; calibration reserved for classifier only",
        "limitations": [
            "FICO is a US credit-bureau variable; it is not a portable Credit Passport score.",
            "Regression excludes geography, identifiers and free text to keep the reconstruction test auditable.",
        ],
    }
    classification_metrics = {
        "task": "repayment_default_classification",
        "dataset": "Lending Club loan dataset for granting models",
        "target": "Default (1 = default/charged off, 0 = fully paid)",
        "features": classification_features,
        "rows": {
            "total": len(loans),
            "train": len(train),
            "calibration": len(calibration),
            "test": len(test),
        },
        "metrics": {
            "roc_auc": roc_auc_score(test["Default"], test_probabilities),
            "pr_auc_average_precision": average_precision_score(test["Default"], test_probabilities),
            "brier": brier_score_loss(test["Default"], test_probabilities),
            "expected_calibration_error_10_bins": _expected_calibration_error(
                test["Default"].to_numpy(), test_probabilities, bins=10
            ),
        },
        "baseline_constant_prevalence": {
            "roc_auc": 0.5,
            "pr_auc_average_precision": average_precision_score(
                test["Default"], classification_baseline_probabilities
            ),
            "brier": brier_score_loss(test["Default"], classification_baseline_probabilities),
            "expected_calibration_error_10_bins": _expected_calibration_error(
                test["Default"].to_numpy(), classification_baseline_probabilities, bins=10
            ),
        },
        "test_prevalence": float(test["Default"].mean()),
        "calibration_curve_10_uniform_bins": {
            "fraction_of_positives": fraction_of_positives,
            "mean_predicted_value": mean_predicted_value,
        },
        "split": "chronological 60/20/20 by issue_d; Platt sigmoid fitted only on calibration partition",
        "limitations": [
            "US LendingClub borrowers and 2007–2018 origination policy; not India or a migrant corridor.",
            "Final outcomes are charged-off versus fully-paid, not a short-horizon default forecast.",
            "The model is not calibrated for any production approval threshold.",
        ],
    }
    return regressor, classifier, _json_safe(
        {"regression": regression_metrics, "classification": classification_metrics}
    )


def train_and_export(force_download: bool = False) -> dict[str, Any]:
    lendingclub_path = download_dataset("lendingclub", force=force_download)
    paths = {"lendingclub": lendingclub_path}
    manifest_path = write_data_manifest(paths)
    loans = load_lendingclub(lendingclub_path)
    regressor, classifier, paired_metrics = train_lendingclub_models(loans)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    regressor_path = ARTIFACT_DIR / "lendingclub_fico_regressor.joblib"
    classifier_path = ARTIFACT_DIR / "lendingclub_default_classifier_calibrated.joblib"
    joblib.dump(regressor, regressor_path, compress=3)
    joblib.dump(classifier, classifier_path, compress=3)
    metrics = {
        "pipeline_version": "0.1.0",
        "random_state": RANDOM_STATE,
        "data_manifest": str(manifest_path),
        "artifacts": {
            "bureau_score_regressor": str(regressor_path),
            "repayment_classifier": str(classifier_path),
        },
        **paired_metrics,
    }
    metrics_path = ARTIFACT_DIR / "metrics.json"
    metrics_path.write_text(json.dumps(_json_safe(metrics), indent=2) + "\n", encoding="utf-8")
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-download", action="store_true")
    args = parser.parse_args()
    try:
        metrics = train_and_export(force_download=args.force_download)
    except Exception as exc:  # noqa: BLE001 - CLI reports exact data/model failure
        print(f"training failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

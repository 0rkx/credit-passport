#!/usr/bin/env python3
"""Stress-test product weight policies against a broad domain-profile cohort.

This is a policy-sensitivity check, not outcome calibration.  It reuses the
pipeline's correlated seven-domain profile generator, fills an unavailable
domain with the scorecard's neutral value (50), and expands the observed
spread so the configured red/amber/green thresholds are exercised.  No
repayment label is read or optimised against.

Run from the repository root with the model environment:

    model_pipeline/.venv/bin/python model_pipeline/scripts/analyze_product_policies.py

The JSON output is deliberately checked in so a reviewer can reproduce the
weight selection and compare a later policy revision against this baseline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "model_pipeline" / "src"))

from credit_passport_model.synthetic import DOMAIN_KEYS, generate_synthetic_cohort  # noqa: E402


PRODUCT_ORDER = ("credit-card", "personal-loan", "student-loan")
DOMAIN_ORDER = tuple(DOMAIN_KEYS)
PROFILE_ROWS = 12_000
PROFILE_RANDOM_STATE = 20260920
PROFILE_SPREAD = 1.80
NEUTRAL_DOMAIN_SCORE = 50.0

# Each vector is ordered as commitment, income, capacity, liquidity, shock,
# momentum and cross-border robustness.
CANDIDATES: dict[str, dict[str, list[int]]] = {
    "v1": {
        "credit-card": [30, 15, 20, 15, 10, 5, 5],
        "personal-loan": [25, 20, 25, 10, 10, 5, 5],
        "student-loan": [15, 15, 20, 10, 10, 20, 10],
    },
    "selected-v2": {
        "credit-card": [35, 10, 15, 25, 5, 5, 5],
        "personal-loan": [20, 25, 30, 10, 5, 5, 5],
        "student-loan": [15, 15, 25, 10, 15, 10, 10],
    },
    "separation-heavy": {
        "credit-card": [40, 10, 10, 25, 5, 5, 5],
        "personal-loan": [15, 30, 30, 10, 5, 5, 5],
        "student-loan": [15, 15, 25, 10, 15, 10, 10],
    },
}
SELECTED_CANDIDATE = "selected-v2"


def _validate_weights(weight_set: dict[str, list[int]]) -> None:
    for product in PRODUCT_ORDER:
        weights = weight_set[product]
        if len(weights) != len(DOMAIN_ORDER) or any(weight < 0 for weight in weights):
            raise ValueError(f"{product} must contain seven non-negative weights")
        if sum(weights) != 100:
            raise ValueError(f"{product} weights must sum to 100; got {sum(weights)}")


def profile_population() -> np.ndarray:
    """Return bounded, correlated profiles with a fixed reproducible seed."""

    frame = generate_synthetic_cohort(rows=PROFILE_ROWS, random_state=PROFILE_RANDOM_STATE)
    columns = [f"{domain}_observed" for domain in DOMAIN_ORDER]
    values = frame[columns].to_numpy(dtype="float64")
    # The scorecard treats a domain with no usable evidence as neutral.  Keep
    # that serving behaviour in the sensitivity population before broadening
    # the profile spread around neutral.
    values = np.where(np.isfinite(values), values, NEUTRAL_DOMAIN_SCORE)
    values = NEUTRAL_DOMAIN_SCORE + (values - NEUTRAL_DOMAIN_SCORE) * PROFILE_SPREAD
    return np.clip(values, 0.0, 100.0)


def _band_percentages(scores: np.ndarray) -> dict[str, float]:
    return {
        "red_below_60": float(np.mean(scores < 60.0)),
        "amber_60_to_74": float(np.mean((scores >= 60.0) & (scores < 75.0))),
        "green_75_or_more": float(np.mean(scores >= 75.0)),
    }


def _score_stats(scores: np.ndarray) -> dict[str, Any]:
    integer_scores = np.rint(scores).astype(int)
    p10, p25, p50, p75, p90 = np.percentile(scores, [10, 25, 50, 75, 90])
    return {
        "n": int(scores.size),
        "mean": round(float(np.mean(scores)), 3),
        "sd": round(float(np.std(scores)), 3),
        "p10": round(float(p10), 3),
        "p25": round(float(p25), 3),
        "p50": round(float(p50), 3),
        "p75": round(float(p75), 3),
        "p90": round(float(p90), 3),
        "min": round(float(np.min(scores)), 3),
        "max": round(float(np.max(scores)), 3),
        "integer_unique_scores": int(np.unique(integer_scores).size),
        "integer_floor_rate": float(np.mean(integer_scores <= 1)),
        "integer_ceiling_rate": float(np.mean(integer_scores >= 99)),
        # The UI and API expose an integer score, so band percentages use the
        # displayed integer rather than an unrounded hidden value.
        "bands": {key: round(value, 6) for key, value in _band_percentages(integer_scores).items()},
    }


def _evaluate(weight_set: dict[str, list[int]], profiles: np.ndarray) -> dict[str, Any]:
    _validate_weights(weight_set)
    scores: dict[str, np.ndarray] = {}
    stats: dict[str, Any] = {}
    for product in PRODUCT_ORDER:
        vector = np.asarray(weight_set[product], dtype="float64")
        scores[product] = profiles @ vector / 100.0
        stats[product] = _score_stats(scores[product])

    pairwise: dict[str, Any] = {}
    for left, right in (("personal-loan", "credit-card"), ("personal-loan", "student-loan"), ("credit-card", "student-loan")):
        left_integer = np.rint(scores[left]).astype(int)
        right_integer = np.rint(scores[right]).astype(int)
        difference = np.abs(left_integer - right_integer)
        pairwise[f"{left}_vs_{right}"] = {
            "integer_difference_rate": round(float(np.mean(left_integer != right_integer)), 6),
            "absolute_difference_mean": round(float(np.mean(difference)), 3),
            "absolute_difference_at_least_3_rate": round(float(np.mean(difference >= 3)), 6),
        }

    # Every policy weight is non-negative, so improving one domain cannot lower
    # a score. Check that property numerically on the same profile population.
    monotonicity: dict[str, float] = {}
    for product in PRODUCT_ORDER:
        vector = np.asarray(weight_set[product], dtype="float64")
        violations = 0
        checks = 0
        for domain_index in range(len(DOMAIN_ORDER)):
            improved = profiles.copy()
            improved[:, domain_index] = np.minimum(100.0, improved[:, domain_index] + 1.0)
            before = np.rint(profiles @ vector / 100.0).astype(int)
            after = np.rint(improved @ vector / 100.0).astype(int)
            violations += int(np.sum(after < before))
            checks += len(profiles)
        monotonicity[product] = round(1.0 - violations / max(1, checks), 6)

    return {"products": stats, "pairwise": pairwise, "monotonicity_rate": monotonicity}


def run() -> dict[str, Any]:
    profiles = profile_population()
    return {
        "analysis_version": "product-policy-sensitivity-v1",
        "source": {
            "generator": "credit_passport_model.synthetic.generate_synthetic_cohort",
            "rows": PROFILE_ROWS,
            "random_state": PROFILE_RANDOM_STATE,
            "neutral_domain_score": NEUTRAL_DOMAIN_SCORE,
            "profile_spread_multiplier": PROFILE_SPREAD,
            "domain_order": list(DOMAIN_ORDER),
            "thresholds": {"red": "<60", "amber": "60-74", "green": ">=75"},
            "labels_used": False,
            "purpose": "internal policy sensitivity only; not outcome calibration",
        },
        "selected_candidate": SELECTED_CANDIDATE,
        "candidates": {name: _evaluate(weights, profiles) for name, weights in CANDIDATES.items()},
        "weights": CANDIDATES,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "model_pipeline" / "product_policy_sensitivity.json",
    )
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["candidates"][SELECTED_CANDIDATE], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

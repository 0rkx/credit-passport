"""Synthetic ICP cohort and serving-contract helpers.

The cohort in this module is intentionally generated from a small latent
financial-behaviour model instead of being copied from a benchmark.  It is
useful for wiring and model-shape experiments only: it is not evidence of
production performance or of any individual's repayment behaviour.

The generated rows represent one application per synthetic person.  Every
person has a product, a worker context and an anonymised corridor so the
training split can be both chronological and person-disjoint.  Worker context
and corridor are metadata used to check coverage; neither is a model feature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Iterable

import numpy as np
import pandas as pd


RANDOM_STATE: Final[int] = 20260920
SYNTHETIC_DATASET_VERSION: Final[str] = "icp_synthetic_cohort_v1"

PRODUCT_VALUES: Final[tuple[str, ...]] = (
    "credit-card",
    "personal-loan",
    "student-loan",
)
WORKER_PROFILE_VALUES: Final[tuple[str, ...]] = (
    "migrant-professional",
    "gig-worker",
    "student",
)
CORRIDOR_VALUES: Final[tuple[str, ...]] = (
    "corridor-a",
    "corridor-b",
    "corridor-c",
)

# This mirrors the event-native contract in ``backend/app/challenger.py``.
# The four evidence-volume fields are deliberately kept out of MODEL_FEATURES:
# they are quality/coverage diagnostics, not causal repayment inputs.
EVENT_FEATURES: Final[tuple[str, ...]] = (
    "requested_amount",
    "assertion_count",
    "unique_event_count",
    "corroborated_count",
    "source_count",
    "active_month_count",
    "observed_span_days",
    "income_event_count",
    "commitment_event_count",
    "income_total",
    "commitment_total",
    "net_flow_total",
    "obligation_to_income_ratio",
    "income_month_count",
    "commitment_month_count",
    "income_regularity",
    "commitment_on_time_rate",
    "balance_observation_count",
    "balance_min",
    "balance_median",
    "balance_last",
    "cross_border_event_count",
    "remittance_event_count",
    "currency_count",
)
QUALITY_FEATURES: Final[tuple[str, ...]] = (
    "assertion_count",
    "unique_event_count",
    "corroborated_count",
    "source_count",
)

# This is the only feature vector consumed by the exported model.  It is
# wholly derivable from Applicant + reconciled economic-event aggregates and
# has no bureau score, identity, geography, prestige or surveillance field.
MODEL_FEATURES: Final[tuple[str, ...]] = tuple(
    feature for feature in EVENT_FEATURES if feature not in QUALITY_FEATURES
)

DOMAIN_KEYS: Final[tuple[str, ...]] = (
    "commitment",
    "income",
    "capacity",
    "liquidity",
    "shock",
    "momentum",
    "cross_border",
)
DOMAIN_FEATURES: Final[tuple[str, ...]] = tuple(
    f"{domain}_observed" for domain in DOMAIN_KEYS
)

PERSON_ID_COLUMN: Final[str] = "person_id"
TIME_COLUMN: Final[str] = "application_month"
WORKER_PROFILE_COLUMN: Final[str] = "worker_profile"
CORRIDOR_COLUMN: Final[str] = "corridor"
TARGET_COLUMN: Final[str] = "adverse_90d"
OUTCOME_REASON_COLUMN: Final[str] = "outcome_reason"

METADATA_COLUMNS: Final[tuple[str, ...]] = (
    PERSON_ID_COLUMN,
    TIME_COLUMN,
    WORKER_PROFILE_COLUMN,
    CORRIDOR_COLUMN,
    OUTCOME_REASON_COLUMN,
)


@dataclass(frozen=True)
class SyntheticCohortConfig:
    """Controls for deterministic generation of a synthetic applicant cohort."""

    rows: int = 12_000
    random_state: int = RANDOM_STATE
    start_month: str = "2022-01-01"
    months: int = 30


def _sigmoid(value: np.ndarray) -> np.ndarray:
    # Clipping avoids overflow warnings for deliberately extreme synthetic
    # rows while preserving a numerically stable logistic transform.
    return 1.0 / (1.0 + np.exp(-np.clip(value, -30.0, 30.0)))


def _clip_score(value: np.ndarray) -> np.ndarray:
    return np.clip(value, 0.0, 100.0)


def _profile_for_product(product: str, rng: np.random.Generator) -> str:
    """Sample plausible work context conditional on the requested product."""

    if product == "student-loan":
        values = WORKER_PROFILE_VALUES
        probabilities = (0.08, 0.12, 0.80)
    elif product == "credit-card":
        values = WORKER_PROFILE_VALUES
        probabilities = (0.48, 0.38, 0.14)
    else:
        values = WORKER_PROFILE_VALUES
        probabilities = (0.52, 0.34, 0.14)
    return str(rng.choice(values, p=probabilities))


def _profile_shift(profile: str) -> np.ndarray:
    """Return shifts for the seven latent financial domains."""

    if profile == "migrant-professional":
        return np.array([0.18, 0.25, 0.22, 0.16, 0.14, 0.13, 0.23])
    if profile == "gig-worker":
        return np.array([0.02, -0.12, -0.08, -0.10, -0.08, 0.06, 0.10])
    # Students have less established commitment/capacity but somewhat stronger
    # momentum in this research cohort; the status is not used by the model.
    return np.array([-0.05, -0.16, -0.18, -0.19, -0.12, 0.21, 0.08])


def _product_shift(product: str) -> np.ndarray:
    if product == "credit-card":
        return np.array([0.04, 0.00, 0.03, 0.02, 0.00, 0.00, 0.02])
    if product == "personal-loan":
        return np.array([0.02, 0.03, -0.02, -0.01, -0.01, 0.01, 0.03])
    return np.array([-0.03, -0.01, -0.12, -0.10, -0.07, 0.14, 0.04])


def _corridor_shift(corridor: str) -> np.ndarray:
    """Vary cross-border evidence context without using corridor as a feature."""

    if corridor == "corridor-a":
        return np.array([0.00, 0.02, 0.00, 0.01, 0.00, 0.00, 0.16])
    if corridor == "corridor-b":
        return np.array([0.01, 0.00, -0.01, 0.00, -0.01, 0.01, -0.05])
    return np.array([0.00, -0.01, 0.01, 0.00, 0.01, 0.00, 0.08])


def _normalised_amounts(
    product: np.ndarray,
    profile: np.ndarray,
    capacity_latent: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Create requested amounts in a common synthetic currency unit.

    The model does not treat the amount as a universal affordability rule; it
    is one applicant input alongside observed domain aggregates.  A serving
    caller must apply the same currency normalisation before inference.
    """

    product_base = {
        "credit-card": 75_000.0,
        "personal-loan": 260_000.0,
        "student-loan": 185_000.0,
    }
    profile_multiplier = {
        "migrant-professional": 1.15,
        "gig-worker": 0.82,
        "student": 0.68,
    }
    base = np.array(
        [product_base[str(value)] for value in product],
        dtype="float64",
    )
    multiplier = np.array(
        [profile_multiplier[str(value)] for value in profile],
        dtype="float64",
    )
    # Larger requested amounts are mildly more likely for applicants with
    # greater capacity, but substantial idiosyncratic variation remains.
    amount = base * multiplier * np.exp(0.13 * capacity_latent + rng.normal(0.0, 0.42, len(product)))
    return np.clip(amount, 5_000.0, 1_500_000.0).round(2)


def _make_domain_scores(
    product: np.ndarray,
    profile: np.ndarray,
    corridor: np.ndarray,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate correlated domain observations and hidden latent risk drivers."""

    # Common stability correlation makes cash capacity, income continuity and
    # liquidity move together while preserving domain-specific variation.
    correlation = np.array(
        [
            [1.00, 0.34, 0.30, 0.25, 0.24, 0.20, 0.16],
            [0.34, 1.00, 0.48, 0.40, 0.30, 0.44, 0.22],
            [0.30, 0.48, 1.00, 0.54, 0.40, 0.28, 0.20],
            [0.25, 0.40, 0.54, 1.00, 0.47, 0.24, 0.19],
            [0.24, 0.30, 0.40, 0.47, 1.00, 0.25, 0.21],
            [0.20, 0.44, 0.28, 0.24, 0.25, 1.00, 0.27],
            [0.16, 0.22, 0.20, 0.19, 0.21, 0.27, 1.00],
        ],
        dtype="float64",
    )
    latent = rng.multivariate_normal(np.zeros(len(DOMAIN_KEYS)), correlation, len(product))
    for row, product_value, profile_value, corridor_value in zip(
        latent, product, profile, corridor, strict=True
    ):
        row += _product_shift(str(product_value))
        row += _profile_shift(str(profile_value))
        row += _corridor_shift(str(corridor_value))

    # A score is an observable aggregate, not a hidden latent value.  Adding
    # domain noise keeps the synthetic prediction task from becoming a lookup
    # of the label while retaining realistic cross-domain correlation.
    scores = 50.0 + latent * 17.0 + rng.normal(0.0, 6.5, latent.shape)
    scores = _clip_score(scores)

    # Each source can omit a domain.  Missingness is generated from product and
    # worker context, not from the future outcome, so abstention is a coverage
    # policy rather than a proxy for repayment risk.
    missing_rates = np.array([0.045, 0.055, 0.050, 0.065, 0.085, 0.060, 0.105])
    for index, (product_value, profile_value) in enumerate(zip(product, profile, strict=True)):
        profile_extra = 0.025 if str(profile_value) == "student" else 0.0
        product_extra = 0.02 if str(product_value) == "student-loan" else 0.0
        probability = np.clip(missing_rates + profile_extra + product_extra, 0.0, 0.35)
        scores[index, rng.random(len(DOMAIN_KEYS)) < probability] = np.nan
    return scores, latent


def _make_event_features(
    product: np.ndarray,
    profile: np.ndarray,
    corridor: np.ndarray,
    scores: np.ndarray,
    latent: np.ndarray,
    requested_amount: np.ndarray,
    rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    """Project the latent cohort into reconciled economic-event aggregates.

    These are the same kinds of aggregates that ``build_feature_values`` in the
    API derives from deduplicated statement events.  The synthetic generator
    intentionally does not emit individual transactions or identity-linked
    records; it emits only the serving-level aggregates needed by the model.
    """

    observed = np.nan_to_num(scores, nan=50.0)
    income_score = observed[:, 1]
    capacity_score = observed[:, 2]
    liquidity_score = observed[:, 3]
    commitment_score = observed[:, 0]
    momentum_score = observed[:, 5]
    cross_border_score = observed[:, 6]
    domain_present = np.isfinite(scores).sum(axis=1)

    active_month_count = np.clip(
        np.rint(6.3 + 2.4 * latent[:, 1] + 1.2 * latent[:, 5] + rng.normal(0, 1.1, len(scores))),
        2,
        12,
    ).astype("float64")
    observed_span_days = np.clip(
        active_month_count * 30.0 + rng.normal(0.0, 14.0, len(scores)),
        45.0,
        365.0,
    )
    income_month_count = np.clip(
        np.rint(active_month_count * (0.70 + 0.20 * (income_score / 100.0)) + rng.normal(0, 0.8, len(scores))),
        1,
        12,
    ).astype("float64")
    commitment_month_count = np.clip(
        np.rint(active_month_count * (0.64 + 0.22 * (commitment_score / 100.0)) + rng.normal(0, 0.8, len(scores))),
        1,
        12,
    ).astype("float64")
    income_event_count = np.maximum(
        income_month_count,
        np.rint(income_month_count * (1.6 + 0.35 * (income_score / 100.0)) + rng.normal(0, 1.3, len(scores))),
    )
    commitment_event_count = np.maximum(
        commitment_month_count,
        np.rint(commitment_month_count * (1.3 + 0.30 * (commitment_score / 100.0)) + rng.normal(0, 1.1, len(scores))),
    )

    income_base = np.select(
        [profile == "migrant-professional", profile == "gig-worker", profile == "student"],
        [185_000.0, 92_000.0, 48_000.0],
        default=100_000.0,
    )
    income_monthly = np.clip(
        income_base * np.exp(0.18 * latent[:, 1] + 0.10 * latent[:, 5] + rng.normal(0.0, 0.22, len(scores))),
        12_000.0,
        750_000.0,
    )
    income_total = np.clip(
        income_monthly * income_month_count * (0.93 + 0.07 * income_score / 100.0),
        12_000.0,
        8_000_000.0,
    )
    obligation_ratio = np.clip(
        0.18 + 0.52 * (1.0 - capacity_score / 100.0) + 0.12 * (1.0 - liquidity_score / 100.0) + rng.normal(0.0, 0.045, len(scores)),
        0.08,
        0.92,
    )
    commitment_total = np.clip(income_total * obligation_ratio, 2_000.0, 6_500_000.0)
    other_debits = np.clip(
        income_total * (0.26 + 0.10 * (1.0 - liquidity_score / 100.0)) + rng.normal(0.0, 7_500.0, len(scores)),
        1_000.0,
        5_000_000.0,
    )
    net_flow_total = income_total - commitment_total - other_debits
    income_regularity = np.clip(
        0.46 + 0.44 * (income_score / 100.0) + rng.normal(0.0, 0.055, len(scores)),
        0.02,
        0.995,
    )
    commitment_on_time_rate = np.clip(
        0.48 + 0.48 * (commitment_score / 100.0) + rng.normal(0.0, 0.045, len(scores)),
        0.02,
        0.999,
    )
    balance_median = np.clip(
        income_monthly * (0.30 + 1.05 * (liquidity_score / 100.0)) + rng.normal(0.0, 12_000.0, len(scores)),
        0.0,
        3_000_000.0,
    )
    balance_min = np.clip(
        balance_median - income_monthly * (0.24 + 0.90 * (1.0 - liquidity_score / 100.0)) + rng.normal(0.0, 8_000.0, len(scores)),
        -250_000.0,
        2_500_000.0,
    )
    balance_last = np.clip(
        balance_median + income_monthly * (0.16 * (momentum_score / 100.0 - 0.5)) + rng.normal(0.0, 10_000.0, len(scores)),
        -250_000.0,
        3_500_000.0,
    )
    cross_border_event_count = np.maximum(
        0.0,
        np.rint(active_month_count * (0.12 + 0.55 * cross_border_score / 100.0) + rng.normal(0.0, 1.2, len(scores))),
    )
    remittance_event_count = np.minimum(
        cross_border_event_count,
        np.maximum(0.0, np.rint(cross_border_event_count * (0.42 + 0.18 * (profile == "student")) + rng.normal(0.0, 0.55, len(scores)))),
    )
    currency_count = np.where(
        cross_border_event_count >= 4,
        rng.choice([2.0, 3.0], len(scores), p=[0.76, 0.24]),
        1.0,
    )
    # Source and assertion counts are diagnostics/coverage only and are not
    # used as model features. Keep them realistic and never derive them from
    # the future label.
    source_count = np.clip(
        np.rint(1.2 + domain_present / 4.2 + rng.normal(0.0, 0.55, len(scores))),
        1,
        5,
    )
    unique_event_count = np.maximum(
        1.0,
        np.rint(income_event_count + commitment_event_count + cross_border_event_count * 0.4 + rng.normal(0.0, 2.2, len(scores))),
    )
    corroborated_count = np.minimum(
        unique_event_count,
        np.maximum(0.0, np.rint(unique_event_count * (0.10 + 0.24 * domain_present / len(DOMAIN_KEYS)) + rng.normal(0.0, 0.9, len(scores)))),
    )
    assertion_count = unique_event_count + corroborated_count + rng.integers(0, 4, len(scores))

    return {
        "requested_amount": requested_amount.astype("float64"),
        "assertion_count": assertion_count.astype("float64"),
        "unique_event_count": unique_event_count.astype("float64"),
        "corroborated_count": corroborated_count.astype("float64"),
        "source_count": source_count.astype("float64"),
        "active_month_count": active_month_count,
        "observed_span_days": observed_span_days,
        "income_event_count": income_event_count.astype("float64"),
        "commitment_event_count": commitment_event_count.astype("float64"),
        "income_total": income_total,
        "commitment_total": commitment_total,
        "net_flow_total": net_flow_total,
        "obligation_to_income_ratio": obligation_ratio,
        "income_month_count": income_month_count,
        "commitment_month_count": commitment_month_count,
        "income_regularity": income_regularity,
        "commitment_on_time_rate": commitment_on_time_rate,
        "balance_observation_count": np.clip(np.rint(active_month_count * (0.62 + 0.20 * domain_present / len(DOMAIN_KEYS)) + rng.normal(0.0, 1.0, len(scores))), 1, 24),
        "balance_min": balance_min,
        "balance_median": balance_median,
        "balance_last": balance_last,
        "cross_border_event_count": cross_border_event_count.astype("float64"),
        "remittance_event_count": remittance_event_count.astype("float64"),
        "currency_count": currency_count.astype("float64"),
    }


def _make_adverse_outcome(
    product: np.ndarray,
    profile: np.ndarray,
    latent: np.ndarray,
    scores: np.ndarray,
    event_features: dict[str, np.ndarray],
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Create a synthetic 90-day >=30-DPD/adverse-restructure outcome.

    The outcome depends on latent capacity/stability plus the observed
    event-aggregate signal and product context.  The hidden latent state is not
    exported, so a model has to learn a noisy, nonlinear relationship from
    evidence aggregates.
    """

    # Use latent values only as a small residual risk driver. Most of the label
    # signal is generated from the same event aggregates that a real serving
    # boundary can derive, making the synthetic task learnable without leakage.
    product_risk = np.select(
        [product == "credit-card", product == "personal-loan", product == "student-loan"],
        [0.00, 0.12, 0.26],
        default=0.0,
    )
    profile_risk = np.select(
        [profile == "migrant-professional", profile == "gig-worker", profile == "student"],
        [0.00, 0.14, 0.19],
        default=0.0,
    )
    latent_weight = np.array([0.35, 0.85, 1.05, 1.00, 0.55, 0.44, 0.24])
    latent_risk = -(latent @ latent_weight) / float(np.sum(latent_weight))

    # Event aggregates have their own measurement noise, but the label is
    # primarily driven by affordability, payment history, cash-flow direction
    # and the available balance. This is a plausible 90-day risk mechanism,
    # rather than a copied benchmark rule or a protected-attribute shortcut.
    income_total = np.maximum(
        1.0,
        np.nan_to_num(event_features["income_total"], nan=float(np.nanmedian(event_features["income_total"]))),
    )
    obligation_ratio = np.nan_to_num(event_features["obligation_to_income_ratio"], nan=0.45)
    regularity = np.nan_to_num(event_features["income_regularity"], nan=0.66)
    on_time = np.nan_to_num(event_features["commitment_on_time_rate"], nan=0.70)
    net_margin = np.clip(
        np.nan_to_num(event_features["net_flow_total"], nan=0.0) / income_total,
        -1.0,
        1.0,
    )
    balance_margin = np.clip(
        np.nan_to_num(event_features["balance_min"], nan=0.0) / income_total,
        -1.0,
        3.0,
    )
    event_risk = (
        2.45 * (obligation_ratio - 0.38)
        - 1.30 * (regularity - 0.66)
        - 1.45 * (on_time - 0.70)
        - 0.85 * net_margin
        - 0.35 * balance_margin
    )
    observed = np.nan_to_num(scores, nan=50.0)
    observed_centered = (observed - 50.0) / 17.0
    interaction = -0.20 * observed_centered[:, 2] * observed_centered[:, 3]
    logit = (
        -1.70
        + 3.80 * event_risk
        + 0.08 * latent_risk
        + 0.08 * interaction
        + 0.04 * product_risk
        + 0.04 * profile_risk
        + rng.normal(0.0, 0.10, len(product))
    )
    adverse_probability = _sigmoid(logit)
    adverse = rng.binomial(1, adverse_probability).astype("int64")

    # Keep the label definition explicit for review while retaining one target
    # column for the classifier.
    restructure = (adverse == 1) & (rng.random(len(product)) < 0.18)
    reason = np.where(
        adverse == 0,
        "current_or_paid_as_agreed",
        np.where(restructure, "adverse_restructure", "30_plus_dpd"),
    )
    return adverse, reason.astype("object")


def generate_synthetic_cohort(
    rows: int = 12_000,
    random_state: int = RANDOM_STATE,
    *,
    start_month: str = "2022-01-01",
    months: int = 30,
) -> pd.DataFrame:
    """Generate a reproducible synthetic migrant-applicant cohort.

    Parameters are intentionally explicit so a training run can be reproduced
    without relying on an external LLM, remote source, or hidden random state.
    The returned frame contains model features plus clearly marked metadata and
    the synthetic target.
    """

    if rows < 30:
        raise ValueError("rows must be at least 30 to preserve temporal split coverage")
    if months < 6:
        raise ValueError("months must be at least 6 to preserve temporal split coverage")

    rng = np.random.default_rng(random_state)
    product = rng.choice(PRODUCT_VALUES, rows, p=(0.43, 0.37, 0.20)).astype("object")
    profile = np.array([_profile_for_product(str(value), rng) for value in product], dtype="object")
    corridor = rng.choice(CORRIDOR_VALUES, rows, p=(0.42, 0.34, 0.24)).astype("object")
    month_values = pd.date_range(start_month, periods=months, freq="MS")
    application_month = pd.Series(rng.choice(month_values, rows), dtype="datetime64[ns]")

    scores, latent = _make_domain_scores(product, profile, corridor, rng)
    requested_amount = _normalised_amounts(product, profile, latent[:, 2], rng)
    event_features = _make_event_features(
        product,
        profile,
        corridor,
        scores,
        latent,
        requested_amount,
        rng,
    )
    # A small fraction of aggregates are unavailable in a given source bundle.
    # The missingness is independent of the future label and is used to test
    # imputation plus the serving abstention policy.
    for feature, probability in {
        "income_regularity": 0.045,
        "commitment_on_time_rate": 0.035,
        "balance_min": 0.065,
        "balance_median": 0.045,
        "balance_last": 0.065,
        "cross_border_event_count": 0.075,
        "remittance_event_count": 0.075,
    }.items():
        missing = rng.random(rows) < probability
        event_features[feature] = event_features[feature].copy()
        event_features[feature][missing] = np.nan
    adverse, outcome_reason = _make_adverse_outcome(
        product,
        profile,
        latent,
        scores,
        event_features,
        rng,
    )

    frame = pd.DataFrame(
        {
            PERSON_ID_COLUMN: [f"SYN-PERSON-{index:07d}" for index in range(rows)],
            TIME_COLUMN: application_month,
            WORKER_PROFILE_COLUMN: profile,
            CORRIDOR_COLUMN: corridor,
            "product_type": product,  # coverage metadata; not a model feature
            **{feature: scores[:, index] for index, feature in enumerate(DOMAIN_FEATURES)},
            **event_features,
            TARGET_COLUMN: adverse,
            OUTCOME_REASON_COLUMN: outcome_reason,
        }
    )
    # Stable ordering is useful for deterministic exports and makes the time
    # split helper's ordering visible to reviewers.
    return frame.sort_values([TIME_COLUMN, PERSON_ID_COLUMN], kind="mergesort").reset_index(drop=True)


def chronological_person_disjoint_split(
    frame: pd.DataFrame,
    *,
    time_column: str = TIME_COLUMN,
    person_column: str = PERSON_ID_COLUMN,
    train_fraction: float = 0.60,
    calibration_fraction: float = 0.20,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split by future time while guaranteeing no person crosses a split.

    The generator emits one row per person, but this helper groups by person
    anyway so a future caller can add multiple observations safely. A person's
    first application month determines their temporal cohort; all of that
    person's rows remain together.
    """

    required = {time_column, person_column}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"split requires columns {sorted(missing)}")
    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must be between 0 and 1")
    if not 0.0 < calibration_fraction < 1.0:
        raise ValueError("calibration_fraction must be between 0 and 1")
    if train_fraction + calibration_fraction >= 1.0:
        raise ValueError("train_fraction + calibration_fraction must be below 1")

    working = frame.copy()
    working[time_column] = pd.to_datetime(working[time_column], errors="raise")
    person_times = working.groupby(person_column, sort=False)[time_column].min()
    ordered_times = np.sort(person_times.drop_duplicates().to_numpy())
    if len(ordered_times) < 3:
        raise ValueError("split requires at least three distinct time cohorts")
    train_time_end = max(1, int(np.floor(len(ordered_times) * train_fraction))) - 1
    calibration_time_end = max(
        train_time_end + 1,
        int(np.floor(len(ordered_times) * (train_fraction + calibration_fraction))) - 1,
    )
    calibration_time_end = min(calibration_time_end, len(ordered_times) - 2)
    train_cutoff = ordered_times[train_time_end]
    calibration_cutoff = ordered_times[calibration_time_end]
    train_people = set(person_times.index[person_times <= train_cutoff])
    calibration_people = set(
        person_times.index[
            (person_times > train_cutoff) & (person_times <= calibration_cutoff)
        ]
    )
    test_people = set(person_times.index[person_times > calibration_cutoff])

    train = working[working[person_column].isin(train_people)].copy()
    calibration = working[working[person_column].isin(calibration_people)].copy()
    test = working[working[person_column].isin(test_people)].copy()
    for left_people, right_people, label in (
        (train_people, calibration_people, "train/calibration"),
        (train_people, test_people, "train/test"),
        (calibration_people, test_people, "calibration/test"),
    ):
        overlap = left_people.intersection(right_people)
        if overlap:
            raise AssertionError(f"person overlap in {label} split: {len(overlap)}")
    return tuple(
        part.sort_values([time_column, person_column], kind="mergesort").reset_index(drop=True)
        for part in (train, calibration, test)
    )  # type: ignore[return-value]


def eligible_for_inference(frame: pd.DataFrame, minimum_domains: int = 4) -> np.ndarray:
    """Return a serving coverage mask; quality is not a causal feature.

    The parameter name is retained for backwards compatibility with the first
    synthetic generator draft. It now means the minimum number of populated
    model features (rather than a domain count). Missing values can be imputed
    for research evaluation, but serving should abstain when the event payload
    is too sparse to support a useful output.
    """

    minimum_features = minimum_domains
    if minimum_features < 1 or minimum_features > len(MODEL_FEATURES):
        raise ValueError(f"minimum_domains must be between 1 and {len(MODEL_FEATURES)}")
    required = set(MODEL_FEATURES)
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"inference frame is missing {sorted(missing)}")
    amount_present = pd.to_numeric(frame["requested_amount"], errors="coerce").notna()
    populated = frame[list(MODEL_FEATURES)].notna().sum(axis=1) >= minimum_features
    return (amount_present & populated).to_numpy(dtype=bool)


def feature_contract() -> dict[str, object]:
    """Return the versioned model input contract for JSON export and serving."""

    numeric_specs: dict[str, dict[str, object]] = {
        "requested_amount": {
            "dtype": "number",
            "nullable": False,
            "minimum": 0.0,
            "maximum": 1_500_000.0,
            "unit": "normalised application-currency units",
            "source": "applicant.requested_amount after caller currency normalisation",
        },
    }
    for feature in MODEL_FEATURES:
        if feature == "requested_amount":
            continue
        if feature in {"income_regularity", "commitment_on_time_rate"}:
            minimum, maximum, unit = 0.0, 1.0, "ratio"
        elif feature == "obligation_to_income_ratio":
            minimum, maximum, unit = 0.0, 1.0, "ratio"
        elif feature in {"balance_min", "balance_median", "balance_last", "net_flow_total"}:
            minimum, maximum, unit = -5_000_000.0, 10_000_000.0, "normalised currency units"
        elif feature.endswith("_count") or feature.endswith("_months") or feature == "observed_span_days":
            minimum, maximum, unit = 0.0, 10_000.0, "count or days"
        else:
            minimum, maximum, unit = 0.0, 10_000_000.0, "normalised currency units"
        numeric_specs[feature] = {
            "dtype": "number",
            "nullable": True,
            "minimum": minimum,
            "maximum": maximum,
            "unit": unit,
            "source": f"reconciled event aggregate: {feature}",
        }
    features = [{"name": name, **numeric_specs[name]} for name in MODEL_FEATURES]
    return {
        "contract_version": "icp-repayment-v1",
        "dataset_version": SYNTHETIC_DATASET_VERSION,
        "target": {
            "name": TARGET_COLUMN,
            "positive_class": 1,
            "positive_class_meaning": "at least one 30+ days-past-due event or adverse restructure within 90 days",
            "negative_class_meaning": "current or paid as agreed through 90 days",
            "prediction_semantics": "probability of the positive adverse outcome",
        },
        "feature_order": list(MODEL_FEATURES),
        "features": features,
        "metadata_not_used_as_features": [
            PERSON_ID_COLUMN,
            TIME_COLUMN,
            WORKER_PROFILE_COLUMN,
            CORRIDOR_COLUMN,
            "product_type",
            *DOMAIN_FEATURES,
            *QUALITY_FEATURES,
            OUTCOME_REASON_COLUMN,
        ],
        "forbidden_feature_families": [
            "bureau_scores_or_credit_bureau_identifiers",
            "protected_attributes_or_proxies",
            "age_sex_ethnicity_nationality_religion",
            "employer_or_school_prestige",
            "gps_contacts_social_graph_or_app_surveillance",
            "post-outcome_repayment_fields",
        ],
        "abstention": {
            "minimum_populated_model_features": len(MODEL_FEATURES) - 8,
            "required_non_null_fields": ["requested_amount"],
            "behavior": "return abstain when event-aggregate coverage is below the minimum; missing values are imputed only for research evaluation",
            "quality_fields_are_not_model_features": True,
        },
        "serving_input": {
            "format": "object with event aggregate feature names as keys; preserve feature_order",
            "output": "predict_proba[:, 1] is adverse_90d probability",
            "model_method": "predict_proba returns adverse_outcome_probability; caller should abstain when coverage is below the threshold",
        },
        "synthetic_data_notice": "All training rows are generated; this artifact is for integration and research validation, not underwriting or production performance claims.",
    }


def cohort_coverage(frame: pd.DataFrame) -> dict[str, object]:
    """Summarise product/corridor/profile coverage without exposing rows."""

    return {
        "rows": int(len(frame)),
        "products": {str(key): int(value) for key, value in frame["product_type"].value_counts().sort_index().items()},
        "worker_profiles": {str(key): int(value) for key, value in frame[WORKER_PROFILE_COLUMN].value_counts().sort_index().items()},
        "corridors": {str(key): int(value) for key, value in frame[CORRIDOR_COLUMN].value_counts().sort_index().items()},
        "adverse_rate": float(frame[TARGET_COLUMN].mean()),
        "event_feature_coverage_rate": float(frame[list(MODEL_FEATURES)].notna().all(axis=1).mean()),
        "minimum_model_feature_coverage_rate": float((frame[list(MODEL_FEATURES)].notna().sum(axis=1) >= len(MODEL_FEATURES) - 8).mean()),
    }


__all__: Iterable[str] = (
    "CORRIDOR_COLUMN",
    "CORRIDOR_VALUES",
    "DOMAIN_FEATURES",
    "DOMAIN_KEYS",
    "EVENT_FEATURES",
    "MODEL_FEATURES",
    "OUTCOME_REASON_COLUMN",
    "PERSON_ID_COLUMN",
    "PRODUCT_VALUES",
    "QUALITY_FEATURES",
    "RANDOM_STATE",
    "SYNTHETIC_DATASET_VERSION",
    "TARGET_COLUMN",
    "TIME_COLUMN",
    "WORKER_PROFILE_COLUMN",
    "WORKER_PROFILE_VALUES",
    "SyntheticCohortConfig",
    "chronological_person_disjoint_split",
    "cohort_coverage",
    "eligible_for_inference",
    "feature_contract",
    "generate_synthetic_cohort",
)

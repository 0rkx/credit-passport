"""Serving boundary for the versioned ICP challenger model.

The transparent scorecard remains the primary, explainable score.  This module
only serves a separately exported research challenger when an operator points
the API at a validated artifact.  It deliberately fails closed when the
artifact or its contract is absent instead of inventing a probability.

The preferred artifact is a JSON bundle with this shape::

    {
      "artifact_version": "icp-challenger-2026.09.20",
      "model_name": "icp_adverse_risk",
      "task": "adverse_outcome_probability",
      "feature_names": ["income_total", "commitment_total"],
      "coefficients": {"income_total": 0.1, "commitment_total": -0.2},
      "intercept": 0.0,
      "blend_weight": 0.20,
      "risk_thresholds": {"low_max": 0.20, "high_min": 0.45},
      "validation_summary": {"provenance": "...", "metrics": {}},
      "provenance": {"synthetic": true, "training_data": "..."}
    }

An equivalent joblib bundle may contain ``model`` or ``estimator`` plus the
same metadata.  Raw joblib estimators are not accepted without a JSON sidecar;
the sidecar must carry the same metadata so the API never guesses model
version, feature order, thresholds, or provenance.
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from .schemas import (
    ChallengerBlendResponse,
    ChallengerRiskBand,
    ChallengerScoreResponse,
    ProductType,
)
from .scoring import COMMITMENT_TYPES, CROSS_BORDER_TYPES, INCOME_TYPES, UniqueEvent

try:  # Optional until a joblib artifact is configured.
    import joblib  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised by the explicit failure path
    joblib = None  # type: ignore[assignment]

try:  # sklearn pipelines typically require a pandas frame with named columns.
    import pandas as pd  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised only in minimal installs
    pd = None  # type: ignore[assignment]


FEATURE_CONTRACT: tuple[str, ...] = (
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


class ChallengerError(RuntimeError):
    """Base class for errors that must be surfaced by the API."""


class ChallengerUnavailable(ChallengerError):
    """The configured artifact cannot be loaded or is not configured."""


class ChallengerContractError(ChallengerError):
    """The artifact is readable but violates the serving contract."""


class ChallengerInferenceError(ChallengerError):
    """The artifact loaded but could not score the supplied feature row."""


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ChallengerContractError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ChallengerContractError(f"{field} must be finite")
    return number


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _income_regularity(events: Sequence[UniqueEvent]) -> float:
    amounts = [event.amount for event in events]
    if len(amounts) < 2:
        return 0.5 if amounts else 0.0
    middle = median(amounts)
    if middle <= 0:
        return 0.0
    deviation = sum(abs(amount - middle) for amount in amounts) / len(amounts)
    return _clamp(1.0 - deviation / middle, 0.0, 1.0)


def _on_time_rate(events: Sequence[UniqueEvent]) -> float:
    observed = 0
    on_time = 0
    for event in events:
        if event.due_on is not None and event.paid_on is not None:
            observed += 1
            on_time += int(event.paid_on <= event.due_on)
        elif event.direction == "debit":
            observed += 1
            # A debit without due/paid dates is an observed payment, not a
            # claim that it was on time.  The neutral treatment is intentional.
    return on_time / observed if observed else 0.5


def build_feature_values(
    applicant: Mapping[str, Any],
    events: Sequence[UniqueEvent],
    source_rows: Sequence[Mapping[str, Any]],
    assertion_count: int,
    corroborated_count: int,
) -> dict[str, float]:
    """Derive the stable, non-sensitive feature contract from observed evidence.

    No feature is pulled from contacts, device data, location, social data,
    employer/school prestige, or prospective income.  Missing observations are
    represented explicitly by neutral values and counts so the model can learn
    the distinction without the server fabricating a record.
    """

    incomes = [
        event
        for event in events
        if event.direction == "credit" and event.event_type in INCOME_TYPES
    ]
    commitments = [event for event in events if event.event_type in COMMITMENT_TYPES]
    months = {_month_key(event.date) for event in events}
    income_months = {_month_key(event.date) for event in incomes}
    commitment_months = {_month_key(event.date) for event in commitments}
    balances = [event.balance_after for event in events if event.balance_after is not None]
    first_date = min((event.date for event in events), default=None)
    last_date = max((event.date for event in events), default=None)
    income_total = sum(event.amount for event in incomes)
    commitment_total = sum(event.amount for event in commitments if event.direction == "debit")
    all_debits = sum(event.amount for event in events if event.direction == "debit")
    requested_amount = applicant.get("requested_amount")
    requested = _finite(requested_amount or 0.0, "requested_amount")
    source_count = len(source_rows)
    currencies = {str(event.currency).upper() for event in events if event.currency}
    cross_border = [event for event in events if event.event_type in CROSS_BORDER_TYPES]
    remittances = [event for event in events if event.event_type == "remittance"]

    values = {
        "requested_amount": requested,
        "assertion_count": float(assertion_count),
        "unique_event_count": float(len(events)),
        "corroborated_count": float(corroborated_count),
        "source_count": float(source_count),
        "active_month_count": float(len(months)),
        "observed_span_days": float((last_date - first_date).days + 1) if first_date and last_date else 0.0,
        "income_event_count": float(len(incomes)),
        "commitment_event_count": float(len(commitments)),
        "income_total": float(income_total),
        "commitment_total": float(commitment_total),
        "net_flow_total": float(income_total - all_debits),
        "obligation_to_income_ratio": float(commitment_total / income_total) if income_total > 0 else 1.0,
        "income_month_count": float(len(income_months)),
        "commitment_month_count": float(len(commitment_months)),
        "income_regularity": float(_income_regularity(incomes)),
        "commitment_on_time_rate": float(_on_time_rate(commitments)),
        "balance_observation_count": float(len(balances)),
        "balance_min": float(min(balances)) if balances else 0.0,
        "balance_median": float(median(balances)) if balances else 0.0,
        "balance_last": float(balances[-1]) if balances else 0.0,
        "cross_border_event_count": float(len(cross_border)),
        "remittance_event_count": float(len(remittances)),
        "currency_count": float(len(currencies)),
    }
    return {name: _finite(values[name], name) for name in FEATURE_CONTRACT}


@dataclass(frozen=True)
class ChallengerArtifact:
    artifact_version: str
    model_name: str
    task: str
    feature_names: tuple[str, ...]
    validation_summary: dict[str, Any]
    provenance: dict[str, Any]
    blend_weight: float
    low_max: float
    high_min: float
    estimator: Any = None
    coefficients: dict[str, float] | None = None
    intercept: float = 0.0

    @classmethod
    def from_payload(cls, payload: Any, artifact_path: Path) -> "ChallengerArtifact":
        sidecar: Mapping[str, Any] | None = None
        estimator: Any = None
        if isinstance(payload, Mapping):
            metadata = payload
            estimator = payload.get("model", payload.get("estimator"))
            if estimator is None and "artifact" in payload and not isinstance(payload["artifact"], (str, bytes)):
                estimator = payload["artifact"]
        else:
            estimator = payload
            sidecar_path = artifact_path.with_suffix(".json")
            if sidecar_path.exists():
                try:
                    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ChallengerContractError(f"Could not read artifact sidecar {sidecar_path}: {exc}") from exc
            metadata = sidecar or {}

        if not isinstance(metadata, Mapping):
            raise ChallengerContractError("artifact metadata must be an object")
        version = metadata.get("artifact_version", metadata.get("version"))
        name = metadata.get("model_name", metadata.get("name"))
        task = metadata.get("task")
        feature_names = metadata.get("feature_names", metadata.get("features", metadata.get("input_features")))
        if hasattr(feature_names, "tolist"):
            feature_names = feature_names.tolist()
        if not isinstance(version, str) or not version.strip():
            raise ChallengerContractError("artifact_version is required")
        if not isinstance(name, str) or not name.strip():
            raise ChallengerContractError("model_name is required")
        if task != "adverse_outcome_probability":
            raise ChallengerContractError("task must be adverse_outcome_probability")
        if isinstance(feature_names, tuple):
            feature_names = list(feature_names)
        if not isinstance(feature_names, list) or not feature_names or any(not isinstance(item, str) for item in feature_names):
            raise ChallengerContractError("feature_names must be a non-empty list of strings")
        if len(set(feature_names)) != len(feature_names):
            raise ChallengerContractError("feature_names must not contain duplicates")
        unsupported = sorted(set(feature_names) - set(FEATURE_CONTRACT))
        if unsupported:
            raise ChallengerContractError(
                "artifact requests features outside the server contract: " + ", ".join(unsupported)
            )

        validation = metadata.get("validation_summary", metadata.get("validation", metadata.get("metrics")))
        provenance = metadata.get("provenance")
        if not isinstance(validation, Mapping) or not validation:
            raise ChallengerContractError("validation_summary is required and must be non-empty")
        if not isinstance(provenance, Mapping) or not provenance:
            raise ChallengerContractError("provenance is required and must be non-empty")

        blend_value = metadata.get("blend_weight")
        if blend_value is None and isinstance(metadata.get("blend"), Mapping):
            blend_value = metadata["blend"].get("model_weight")
        blend_weight = _finite(blend_value, "blend_weight")
        if not 0 <= blend_weight <= 1:
            raise ChallengerContractError("blend_weight must be between 0 and 1")

        thresholds = metadata.get("risk_thresholds", metadata.get("risk_band_thresholds"))
        if thresholds is None and isinstance(metadata.get("risk_bands"), Mapping):
            bands = metadata["risk_bands"]
            low_band = bands.get("low")
            medium_band = bands.get("medium")
            if isinstance(low_band, (list, tuple)) and len(low_band) == 2 and isinstance(medium_band, (list, tuple)) and len(medium_band) == 2:
                thresholds = {"low_max": low_band[1], "high_min": medium_band[1]}
        if not isinstance(thresholds, Mapping):
            raise ChallengerContractError("risk_thresholds is required")
        low_max = thresholds.get("low_max", thresholds.get("medium_max", thresholds.get("medium")))
        high_min = thresholds.get("high_min", thresholds.get("high"))
        low_max = _finite(low_max, "risk_thresholds.low_max")
        high_min = _finite(high_min, "risk_thresholds.high_min")
        if not 0 <= low_max < high_min <= 1:
            raise ChallengerContractError("risk thresholds must satisfy 0 <= low_max < high_min <= 1")

        coefficients_raw = metadata.get("coefficients", metadata.get("weights"))
        intercept_raw = metadata.get("intercept", 0.0)
        # A JSON exporter may wrap the dependency-free linear model in a
        # ``model`` object.  Accept that explicit shape, but never infer an
        # algorithm or feature mapping from an opaque object.
        if coefficients_raw is None and isinstance(estimator, Mapping):
            coefficients_raw = estimator.get("coefficients", estimator.get("weights"))
            intercept_raw = estimator.get("intercept", intercept_raw)
            estimator = None
        if hasattr(coefficients_raw, "tolist"):
            coefficients_raw = coefficients_raw.tolist()
        coefficients: dict[str, float] | None = None
        intercept = _finite(intercept_raw, "intercept")
        if coefficients_raw is not None:
            if isinstance(coefficients_raw, Mapping):
                coefficients = {str(key): _finite(value, f"coefficients.{key}") for key, value in coefficients_raw.items()}
            elif isinstance(coefficients_raw, list) and len(coefficients_raw) == len(feature_names):
                coefficients = {
                    name: _finite(value, f"coefficients.{name}")
                    for name, value in zip(feature_names, coefficients_raw)
                }
            else:
                raise ChallengerContractError("coefficients must be an object or a list matching feature_names")
            missing = sorted(set(feature_names) - set(coefficients))
            if missing:
                raise ChallengerContractError("coefficients missing: " + ", ".join(missing))
            return cls(
                artifact_version=version,
                model_name=name,
                task=task,
                feature_names=tuple(feature_names),
                validation_summary=dict(validation),
                provenance=dict(provenance),
                blend_weight=blend_weight,
                low_max=low_max,
                high_min=high_min,
                coefficients=coefficients,
                intercept=intercept,
            )

        if estimator is None:
            raise ChallengerContractError("artifact must contain model/estimator or coefficients")
        if not hasattr(estimator, "predict_proba") and not hasattr(estimator, "decision_function") and not hasattr(estimator, "predict"):
            raise ChallengerContractError("model must expose predict_proba, decision_function, or predict")
        return cls(
            artifact_version=version,
            model_name=name,
            task=task,
            feature_names=tuple(feature_names),
            validation_summary=dict(validation),
            provenance=dict(provenance),
            blend_weight=blend_weight,
            low_max=low_max,
            high_min=high_min,
            estimator=estimator,
            intercept=intercept,
        )

    def risk_band(self, probability: float) -> ChallengerRiskBand:
        if probability <= self.low_max:
            return ChallengerRiskBand.LOW
        if probability < self.high_min:
            return ChallengerRiskBand.MEDIUM
        return ChallengerRiskBand.HIGH

    def _model_input(self, feature_values: Mapping[str, float]) -> Any:
        ordered = [feature_values[name] for name in self.feature_names]
        if pd is not None:
            return pd.DataFrame([{name: feature_values[name] for name in self.feature_names}], columns=list(self.feature_names))
        return [ordered]

    @staticmethod
    def _positive_probability(output: Any, estimator: Any) -> float:
        if hasattr(output, "tolist"):
            output = output.tolist()
        if isinstance(output, (float, int)):
            probability = float(output)
        elif isinstance(output, list) and output and isinstance(output[0], list):
            row = output[0]
            if len(row) == 1:
                probability = float(row[0])
            else:
                classes = list(getattr(estimator, "classes_", []))
                index = 1
                if classes:
                    positive_labels = {1, "1", "bad", "default", "adverse", "high_risk", "high-risk"}
                    for candidate in positive_labels:
                        if candidate in classes:
                            index = classes.index(candidate)
                            break
                if index >= len(row):
                    raise ChallengerInferenceError("model probability output has no positive class")
                probability = float(row[index])
        elif isinstance(output, list) and output:
            probability = float(output[0])
        else:
            raise ChallengerInferenceError("model returned an empty probability output")
        if not math.isfinite(probability) or probability < -1e-9 or probability > 1 + 1e-9:
            raise ChallengerInferenceError(
                f"model returned {probability!r}; adverse_outcome_probability must be in [0, 1]"
            )
        return _clamp(probability, 0.0, 1.0)

    def predict_probability(self, feature_values: Mapping[str, float]) -> float:
        if self.coefficients is not None:
            linear = self.intercept + sum(self.coefficients[name] * feature_values[name] for name in self.feature_names)
            # Numerically stable sigmoid.
            if linear >= 0:
                exponent = math.exp(-linear)
                return 1.0 / (1.0 + exponent)
            exponent = math.exp(linear)
            return exponent / (1.0 + exponent)

        if self.estimator is None:  # pragma: no cover - dataclass invariant
            raise ChallengerInferenceError("artifact has no estimator")
        model_input = self._model_input(feature_values)
        try:
            if hasattr(self.estimator, "predict_proba"):
                output = self.estimator.predict_proba(model_input)
                return self._positive_probability(output, self.estimator)
            if hasattr(self.estimator, "decision_function"):
                margin = self.estimator.decision_function(model_input)
                if hasattr(margin, "tolist"):
                    margin = margin.tolist()
                if isinstance(margin, list):
                    margin = margin[0]
                margin = float(margin)
                if margin >= 0:
                    exponent = math.exp(-margin)
                    return 1.0 / (1.0 + exponent)
                exponent = math.exp(margin)
                return exponent / (1.0 + exponent)
            return self._positive_probability(self.estimator.predict(model_input), self.estimator)
        except ChallengerError:
            raise
        except Exception as exc:  # pragma: no cover - depends on third-party estimator
            raise ChallengerInferenceError(f"model inference failed: {exc}") from exc


class ChallengerModelService:
    """Lazy, mtime-aware loader for one configured challenger artifact."""

    def __init__(self, artifact_path: str):
        self.artifact_path = artifact_path
        self._artifact: ChallengerArtifact | None = None
        self._signature: tuple[int, int] | None = None
        self._load_lock = threading.Lock()

    def _path(self) -> Path:
        return Path(self.artifact_path).expanduser().resolve()

    def load(self) -> ChallengerArtifact:
        with self._load_lock:
            return self._load_unlocked()

    def _load_unlocked(self) -> ChallengerArtifact:
        path = self._path()
        if not path.exists():
            raise ChallengerUnavailable(
                f"Configured challenger artifact was not found at {path}. "
                "Set CREDIT_PASSPORT_CHALLENGER_MODEL_ARTIFACT_PATH to a validated artifact."
            )
        try:
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except OSError as exc:
            raise ChallengerUnavailable(f"Could not inspect challenger artifact {path}: {exc}") from exc
        if self._artifact is not None and self._signature == signature:
            return self._artifact

        try:
            if path.suffix.lower() == ".json":
                payload = json.loads(path.read_text(encoding="utf-8"))
            else:
                if joblib is None:
                    raise ChallengerUnavailable("joblib is required to load a non-JSON challenger artifact")
                payload = joblib.load(path)
            artifact = ChallengerArtifact.from_payload(payload, path)
        except ChallengerError:
            raise
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            raise ChallengerUnavailable(f"Could not load challenger artifact {path}: {exc}") from exc
        self._artifact = artifact
        self._signature = signature
        return artifact

    def infer(
        self,
        *,
        applicant: Mapping[str, Any],
        product: ProductType,
        events: Sequence[UniqueEvent],
        source_rows: Sequence[Mapping[str, Any]],
        assertion_count: int,
        corroborated_count: int,
        transparent_score: int,
    ) -> ChallengerScoreResponse:
        if not events:
            raise ChallengerInferenceError(
                "Challenger scoring requires at least one ingested evidence event; no score is available yet."
            )
        artifact = self.load()
        feature_values = build_feature_values(
            applicant,
            events,
            source_rows,
            assertion_count,
            corroborated_count,
        )
        probability = artifact.predict_probability(feature_values)
        challenger_score = 100.0 * (1.0 - probability)
        blended_score = (1.0 - artifact.blend_weight) * float(transparent_score) + artifact.blend_weight * challenger_score
        return ChallengerScoreResponse(
            applicant_id=str(applicant["id"]),
            product=product,
            model_name=artifact.model_name,
            task="adverse_outcome_probability",
            probability=round(probability, 6),
            risk_band=artifact.risk_band(probability),
            feature_values={name: round(feature_values[name], 6) for name in artifact.feature_names},
            artifact_version=artifact.artifact_version,
            validation_summary=artifact.validation_summary,
            provenance=artifact.provenance,
            blend=ChallengerBlendResponse(
                transparent_score=transparent_score,
                challenger_score=round(challenger_score, 4),
                model_weight=artifact.blend_weight,
                model_contribution=round(artifact.blend_weight * challenger_score, 4),
                blended_score=round(blended_score, 4),
            ),
            generated_at=datetime.now(timezone.utc),
        )

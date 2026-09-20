"""Small serializable model wrappers used by the exported artifacts."""

from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin


class PlattCalibratedClassifier(BaseEstimator, ClassifierMixin):
    """Wrap a fitted binary estimator with a held-out sigmoid calibrator.

    The base estimator is fitted on the training partition and the calibrator
    is fitted only on the separate calibration partition. Keeping this wrapper
    in the package (rather than defining it in a script) makes joblib artifacts
    portable when loaded by a later API process.
    """

    def __init__(self, base_estimator, calibrator):
        self.base_estimator = base_estimator
        self.calibrator = calibrator
        self.classes_ = np.array([0, 1], dtype="int64")

    def _calibrated_positive_probability(self, x) -> np.ndarray:
        scores = np.asarray(self.base_estimator.decision_function(x)).reshape(-1, 1)
        return self.calibrator.predict_proba(scores)[:, 1]

    def predict_proba(self, x) -> np.ndarray:
        positive = self._calibrated_positive_probability(x)
        return np.column_stack([1.0 - positive, positive])

    def predict(self, x) -> np.ndarray:
        return (self._calibrated_positive_probability(x) >= 0.5).astype("int64")

    def decision_function(self, x) -> np.ndarray:
        return self.base_estimator.decision_function(x)


class ICPCalibratedClassifier(PlattCalibratedClassifier):
    """Calibrated event-native classifier with an explicit coverage gate.

    ``predict_proba`` remains compatible with scikit-learn and the API serving
    boundary.  ``predict_with_abstention`` adds the operational behavior needed
    when a sparse evidence bundle should not receive a fabricated probability.
    Evidence volume is used only for this coverage gate; it is not part of the
    model feature vector and cannot act as a causal repayment feature.
    """

    def __init__(
        self,
        base_estimator,
        calibrator,
        feature_order,
        minimum_populated_features: int = 12,
    ):
        super().__init__(base_estimator=base_estimator, calibrator=calibrator)
        self.feature_order = tuple(feature_order)
        self.minimum_populated_features = minimum_populated_features

    def abstain_mask(self, x) -> np.ndarray:
        """Return rows with insufficient serving coverage."""

        if hasattr(x, "loc") and hasattr(x, "columns"):
            values = x.loc[:, list(self.feature_order)].to_numpy(dtype="float64")
        else:
            values = np.asarray(x, dtype="float64")
            if values.ndim == 1:
                values = values.reshape(1, -1)
        if values.ndim != 2 or values.shape[1] != len(self.feature_order):
            raise ValueError(
                f"expected {len(self.feature_order)} ordered features, got shape {values.shape}"
            )
        amount_present = np.isfinite(values[:, 0])
        populated = np.isfinite(values).sum(axis=1) >= int(self.minimum_populated_features)
        return ~(amount_present & populated)

    def predict_with_abstention(self, x) -> tuple[np.ndarray, np.ndarray]:
        """Return probabilities and a boolean mask for rows that should abstain."""

        probabilities = np.asarray(self.predict_proba(x), dtype="float64")
        abstain = self.abstain_mask(x)
        probabilities[abstain, :] = np.nan
        return probabilities, abstain

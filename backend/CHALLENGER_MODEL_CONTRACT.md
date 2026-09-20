# ICP challenger serving contract

The API loads the file configured by `CREDIT_PASSPORT_CHALLENGER_MODEL_ARTIFACT_PATH`.
The default is `../model_pipeline/artifacts/icp_challenger.joblib` when the API is
started from `backend/`.

## Required bundle fields

```json
{
  "artifact_version": "icp-challenger-2026.09.20",
  "model_name": "icp-adverse-risk",
  "task": "adverse_outcome_probability",
  "feature_names": ["income_total", "commitment_total"],
  "coefficients": {"income_total": 0.1, "commitment_total": -0.2},
  "intercept": 0.0,
  "blend_weight": 0.2,
  "risk_thresholds": {"low_max": 0.20, "high_min": 0.45},
  "validation_summary": {
    "dataset": "...",
    "split": "...",
    "metrics": {"roc_auc": 0.0}
  },
  "provenance": {
    "synthetic": true,
    "training_data": "...",
    "limitations": ["..."],
    "note": "Research-only challenger; not a lending decision model."
  }
}
```

`coefficients` plus `intercept` is the dependency-light JSON form. A joblib
bundle is also accepted when it contains `model` or `estimator` and the same
metadata. A raw joblib estimator requires a same-name JSON sidecar and is
never loaded without that metadata.

`feature_names` must be a subset of the following server-derived, numeric
features. The service rejects every other field so model training cannot
silently introduce device, contact, location, employer prestige, school
prestige, social, or prospective-income variables:

```text
requested_amount
assertion_count
unique_event_count
corroborated_count
source_count
active_month_count
observed_span_days
income_event_count
commitment_event_count
income_total
commitment_total
net_flow_total
obligation_to_income_ratio
income_month_count
commitment_month_count
income_regularity
commitment_on_time_rate
balance_observation_count
balance_min
balance_median
balance_last
cross_border_event_count
remittance_event_count
currency_count
```

## Endpoint

```text
GET /api/v1/applicants/{applicant_id}/challenger-score?product=personal-loan
```

The response carries the artifact version, feature values actually sent to the
model, adverse-outcome probability, risk band, validation summary, provenance,
and a `blend` object. The blend is labelled `research-only`; it is not an
approval recommendation. Missing/invalid artifacts return `503`. Applicants
without an ingested event return `422` rather than receiving a guessed result.

## Curl example

```bash
curl "http://127.0.0.1:8000/api/v1/applicants/CP-.../challenger-score?product=personal-loan"
```

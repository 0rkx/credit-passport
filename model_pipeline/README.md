# Credit Passport model pipeline

This directory contains the real-data training and evaluation path used by Credit Passport. It is deliberately separate from the applicant-facing UI: the UI can later call a FastAPI service that loads the exported artifacts from `artifacts/`.

The pipeline's primary paired evaluation uses one defensible, real public source:

1. **Bureau/FICO-score regression:** predict LendingClub's `fico_n` field from non-score application metrics (`revenue`, `dti_n`, `loan_amnt`, and employment experience). This tests whether applicant evidence can reconstruct a bureau-like score. It is not a Credit Passport score.
2. **Repayment classification:** predict LendingClub's final `Default` outcome (charged off versus fully paid) from application-time fields. The calibrated classifier reports ROC-AUC, PR-AUC, Brier score and expected calibration error on an untouched, chronologically later test partition.

The primary dataset is the 1,347,681-row Lending Club granting-model file published on Zenodo (DOI `10.5281/zenodo.11295916`, CC BY 4.0). It is downloaded from a pinned URL with SHA-256 verification. The download step fails loudly if a source is unavailable or changes; it never fabricates rows or silently substitutes a fallback. UCI and FICO/HELOC are catalogued as secondary benchmarks, but are not silently mixed into the primary artifact.

## Reproduce

Use Python 3.10+ and install the locked top-level dependencies:

```bash
cd model_pipeline
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/python scripts/download_data.py
.venv/bin/python scripts/train_models.py
.venv/bin/pytest
```

The commands create raw data under `data/raw/`, metrics and provenance under `artifacts/`, and the trained models under `artifacts/*.joblib`. Raw data and binary models are intentionally gitignored; the scripts and checksums are the reproducible source of truth.

## ICP event-native model

The ICP track is a separately labelled, fully synthetic cohort for serving and
integration work. It covers credit-card, personal-loan and student-loan
applications across three anonymised corridors and migrant-professional,
gig-worker and student work contexts. The target is `adverse_90d`: at least one
30-days-past-due event or adverse restructure within 90 days. One row represents
one synthetic person, and the split is chronological and person-disjoint:
60% train, 20% calibration, and the latest 20% untouched test.

Run it with:

```bash
.venv/bin/python scripts/train_icp_model.py --rows 12000
.venv/bin/pytest tests/test_icp_pipeline.py
```

The command writes `artifacts/icp_challenger.joblib`, its metadata sidecar
`artifacts/icp_challenger.json`, `artifacts/icp_metrics.json`, and the serving
contract `artifacts/icp_feature_contract.json`. The model is a calibrated
HistGradientBoosting classifier over event-native aggregates derived from
reconciled evidence: amounts, active months, income/commitment cadence,
obligation-to-income ratio, net flow, balances, and cross-border event counts.
Evidence-volume fields are retained for coverage diagnostics and abstention,
not used as learned repayment features. No bureau score, identity, protected
attribute, employer/school prestige, GPS, contacts, social graph, or post-
outcome field is in the contract.

The checked-in metrics are synthetic-only validation, not a production claim.
The latest test block reports ROC-AUC 0.8520, PR-AUC 0.7192, Brier 0.1363 and
10-bin ECE 0.0189. The artifact's positive probability is the adverse-outcome
probability; serving should abstain when fewer than 12 of 20 model fields are
populated or `requested_amount` is missing.

## Important limitations

- The primary data are US LendingClub borrowers and 2007–2018 origination policy. The model is not trained for India or a migrant corridor.
- The data contain application fields, not permissioned payroll, rent, remittance, wallet or bank-statement evidence. The actual Credit Passport feature graph still needs corridor-specific validation.
- The FICO/HELOC and UCI sources remain secondary research benchmarks; their geography, licensing and leakage risks are documented in `DATASET_CATALOG.md`.
- The benchmark FICO and default fields must not be presented as a portable score or used for lending decisions without a separate fairness, legal and governance review.
- Held-out metrics quantify benchmark performance, not approval uplift, causal risk reduction or regulatory fitness.

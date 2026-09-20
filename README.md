# Credit Passport

Credit Passport turns a complete, permissioned transaction statement into a portable financial assessment. It combines an explainable seven-domain scorecard with a served 90-day repayment-risk model, while keeping evidence reliability and reason codes visible.

The repository contains three independent layers:

- `credit-passport-ui/` — applicant and lender web application.
- `backend/` — FastAPI, SQLite persistence, CSV statement ingestion, event reconciliation, seven-domain scoring and transition guidance.
- `model_pipeline/` — reproducible ICP training, held-out evaluation and the versioned serving artifact.

There are no runtime seed applicants, fake upload jobs or silent mock fallbacks. A fresh database starts empty.

## Run locally

Requirements: Node.js 22+, npm, and Python 3.11+.

```bash
make setup
make dev
```

Then open:

- App: <http://127.0.0.1:5173>
- API documentation: <http://127.0.0.1:8000/docs>

The first screen creates an applicant. Upload a complete UTF-8 CSV statement with at least `date` and `amount` columns. Optional columns are `direction`, `description`, `event_type`, `currency`, `balance`, `reference`, `due_on` and `paid_on`. PDF and XLSX are rejected explicitly; they are not reported as successfully processed.

## Verify

```bash
make verify
```

This runs backend tests, model-pipeline tests, frontend lint/type checking, and the production frontend build.

## Train the served model

```bash
cd model_pipeline
.venv/bin/python scripts/train_icp_model.py --rows 12000
```

The target is a 30+ DPD event or adverse restructure within 90 days. The model uses 20 aggregates derived from reconciled evidence, including payment regularity, obligation-to-income ratio, income cadence, net flow, balances and cross-border activity. Applicant identity, protected attributes, prestige and surveillance data are excluded.

Current held-out results:

- 12,000 cases split 60% train, 20% calibration and latest 20% untouched test.
- ROC-AUC 0.8520 and PR-AUC 0.7192.
- Brier score 0.1363 and 10-bin calibration error 0.0189.
- Person-disjoint, chronological evaluation with 100% eligible test coverage.

The API serves the artifact at `GET /api/v1/applicants/{id}/challenger-score`. The current decision score blends the transparent scorecard at 65% and the repayment-risk model at 35%. See [MODEL_CARD.md](model_pipeline/MODEL_CARD.md), [ICP feature contract](model_pipeline/artifacts/icp_feature_contract.json) and [backend serving contract](backend/CHALLENGER_MODEL_CONTRACT.md).

## Important boundary

Held-out generator performance is not corridor calibration. Production underwriting still requires consented lender outcomes, external validation, subgroup testing, drift monitoring and governance. The current service is a local evaluation build and does not include production identity or tenant isolation.

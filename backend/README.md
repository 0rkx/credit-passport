# Credit Passport API

This directory contains the production-shaped FastAPI service for Credit Passport. It stores applicants, permissioned evidence assertions, parsed CSV statement uploads, transition guidance, and score calculations in SQLite. A new database is empty by design: the service never inserts seeded applicants or fabricated financial records at startup.

## Run locally

From the repository root:

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/uvicorn app.main:app --reload --port 8000
```

The API is available at `http://127.0.0.1:8000`. OpenAPI is at `/docs`; the frontend can use `http://localhost:8000`.

The default SQLite file is `backend/data/credit_passport.db`. Override it without changing source:

```bash
CREDIT_PASSPORT_DB_PATH=/tmp/credit-passport.db .venv/bin/uvicorn app.main:app --port 8000
```

The default CORS allowlist is `http://localhost:5173,http://127.0.0.1:5173`. Override it with `CREDIT_PASSPORT_CORS_ORIGINS` as a comma-separated list. Uploads are limited to 10 MiB by default; use `CREDIT_PASSPORT_MAX_UPLOAD_BYTES` to change the limit.

## API surface

All application routes are under `/api/v1`.

| Route | Purpose |
| --- | --- |
| `GET /health` or `GET /healthz` | Database-backed health check |
| `GET /api/v1/config` | Product weights, domains, evidence types and scoring version; safe for an empty database |
| `GET /api/v1/model/validation` | Read-only model-pipeline metrics inspection; returns `unavailable` when no artifact exists |
| `GET /api/v1/applicants` | List applicants; returns `[]` on a fresh database |
| `POST /api/v1/applicants` | Create an applicant profile |
| `GET /api/v1/applicants/{id}` | Read one applicant and its current summary |
| `POST /api/v1/applicants/{id}/evidence` | Ingest a structured, consented statement payload |
| `POST /api/v1/applicants/{id}/statements` | Upload and immediately parse a complete CSV statement |
| `GET /api/v1/applicants/{id}/evidence` | Read source assertions, deduplicated economic events and corroborations |
| `GET /api/v1/applicants/{id}/score?product=personal-loan` | Calculate the deterministic seven-domain score |
| `GET /api/v1/applicants/{id}/challenger-score?product=personal-loan` | Run the configured ICP challenger and return probability, provenance and research-only blend |
| `GET /api/v1/applicants/{id}/transition` | Read saved transition guidance state; accepts optional `event` for a preview |
| `PUT /api/v1/applicants/{id}/transition` | Save a transition state and return deterministic guidance tasks |
| `POST /api/v1/guide/query` | Ask a source-grounded India cross-border transition question |
| `GET /api/v1/guide/suggested-prompts` | List starter questions for the transition guide |
| `GET /api/v1/guide/sources` | List the official policy sources used by the guide |

### Transition guide

The guide is stateless and bounded to the official source register in
`backend/policy_knowledge/sources.json`. It covers NRE, NRO, FCNR(B) and RFC
accounts, FEMA residence, income-tax residency basics, KYC, FATCA/CRS, moving
abroad, job changes and returning to India. It does not make a legal or tax
determination and does not affect a credit score or lending decision.

With no `GEMINI_API_KEY`, the endpoint returns a deterministic answer assembled
from the source register and includes citations. If a Gemini key is present,
the server sends only the retrieved source records to Gemini with a strict
grounding prompt. The model must return citations drawn from those records; an
invalid or unavailable provider falls back to the same cited deterministic
answer. Secrets are read only from environment variables and are not stored.

The main request/response contract is:

```json
POST /api/v1/guide/query
{
  "query": "I am returning to India after living abroad. What should I review first?",
  "intent": "returning-india",
  "session_id": "optional-ui-correlation-id",
  "country_from": "UAE",
  "country_to": "India",
  "facts": {},
  "max_sources": 4
}
```

```json
{
  "query": "...",
  "answer": "...",
  "bullets": ["..."],
  "follow_up_questions": ["..."],
  "citations": [
    {
      "id": "rbi-accounts-non-residents-2025",
      "title": "Accounts in India by Non-residents",
      "publisher": "Reserve Bank of India",
      "url": "https://www.rbi.org.in/commonman/Upload/English/FAQs/PDFs/Accountresidents16012025.pdf",
      "locator": "RBI FAQ dated 16 January 2025, Q1-Q3 and change-of-status section",
      "matched_topics": ["nre", "returning-india"]
    }
  ],
  "suggested_prompts": [],
  "grounded": true,
  "abstained": false,
  "provider": "deterministic",
  "provider_status": "keyless",
  "session_id": "optional-ui-correlation-id",
  "disclaimer": "This is general information, not legal or tax advice..."
}
```

`intent` accepts `general`, `moving-abroad`, `returning-india`, `job-change`,
`account-choices`, `residential-status`, `account-conversion` and
`kyc-fatca-crs`. Every response includes at least one citation, including an
abstention that points to the guide's coverage boundary.

To enable Gemini later, set `GEMINI_API_KEY` in the runtime environment and
optionally change `GEMINI_MODEL`. For local development, the API automatically
loads either the repository-root `.env` (recommended) or `backend/.env` before
reading settings. If both exist, `backend/.env` wins; an already-exported shell
or CI variable always wins. These files are ignored by Git, values are never
printed or logged, and `.env.example` contains the safe variable names only.
The default remains keyless and deterministic.

### CSV statements

The upload endpoint requires multipart fields `file`, `source_type`, `provider`, `currency`, and `consent=true`. CSV is the only file format currently parsed. XLSX and PDF return HTTP 415 with an explicit unsupported-format response; they are never reported as successfully ingested.

The parser accepts common aliases. The minimum useful columns are `date` (or `occurred_on`) and `amount`. Optional columns include `direction`, `event_type`/`category`, `description`/`narration`, `currency`, `balance`, `reference`, `due_on`, and `paid_on`. If direction is omitted, a negative amount is a debit and a positive amount is a credit. If event type is omitted, the parser uses conservative keyword classification from the description and otherwise records `other`.

The raw file is not stored. The service stores upload metadata (filename, byte count and SHA-256) plus the parsed, structured assertions needed for scoring. The complete statement period is preserved in the source record.

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/applicants/CP-.../statements \
  -F 'file=@statement.csv;type=text/csv' \
  -F 'source_type=bank-statement' \
  -F 'provider=Applicant bank' \
  -F 'currency=INR' \
  -F 'consent=true'
```

## Scoring contract

The score is a transparent weighted score over:

1. commitment performance;
2. income continuity;
3. affordability and capacity;
4. liquidity;
5. shock resilience;
6. economic momentum; and
7. cross-border robustness.

Each product has a separate weight vector. The vectors sum to 100:

- credit card: 30/15/20/15/10/5/5;
- personal loan: 25/20/25/10/10/5/5; and
- student loan: 15/15/20/10/10/20/10.

Source assertions are deduplicated into unique economic events using date, normalized event type, amount, currency and direction. A payroll record that matches a bank deposit corroborates that event; it does not award a second behavioral point. Reliability is reported separately from the behavioral score and is based on evidence volume, period coverage, source diversity, completeness and corroboration. With no evidence, the explicit score endpoint reports a neutral calculation with reliability `0`; applicant summary responses expose `score: null` so a UI can show “not available” rather than imply an assessed result.

The score response includes domain observations, adjusted values, weights, contributions, evidence IDs, reason codes, corroboration counts and a p10–p90 display range. Transition tasks are always marked `score_effect: none`.

## Model validation artifact

`GET /api/v1/model/validation` reads the versioned ICP metrics artifact. Configure its path with `CREDIT_PASSPORT_MODEL_METRICS_PATH`. Missing artifacts return an explicit `unavailable` status; there are no fabricated metrics or fallback predictions.

## ICP challenger artifact

The challenger is served only through the dedicated endpoint. Configure its
artifact with `CREDIT_PASSPORT_CHALLENGER_MODEL_ARTIFACT_PATH`; the default is
`../model_pipeline/artifacts/icp_challenger.joblib` when the API runs from this
directory. The artifact must declare its version, feature order, risk
thresholds, blend weight, validation summary and provenance. JSON coefficient
bundles and joblib estimator bundles are supported. See
[`CHALLENGER_MODEL_CONTRACT.md`](CHALLENGER_MODEL_CONTRACT.md) for the exact
contract and server-derived feature allowlist.

The checked-in joblib artifact requires the optional model dependencies and the
local `model_pipeline` package. The root `make setup` command installs both.

The response reports an adverse-outcome probability and a low/medium/high risk
band, plus the exact feature values sent to the artifact. It also exposes a
transparent-score/challenger blend labelled `research-only`; it is not an
approval recommendation. If the artifact is missing or invalid the endpoint
returns `503`. If the applicant has no ingested evidence it returns `422` and
does not guess a probability.

## Tests

```bash
cd backend
.venv/bin/pytest -q
```

The tests use temporary SQLite files, exercise the empty state, structured ingestion, alias-aware deduplication, product weights, CSV parsing, upload rejection, transition persistence and score neutrality. They do not write to the default development database.

# Credit Passport UI

Applicant and lender interfaces for the Credit Passport API. Runtime applicant, evidence, event, score and guidance data are fetched from FastAPI; the browser bundle contains no seeded cases or fallback records.

## Run

Start the API first on `127.0.0.1:8000`, then:

```bash
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Open <http://127.0.0.1:5173>.

The default API root is `http://127.0.0.1:8000/api/v1`. Override it with:

```bash
NEXT_PUBLIC_API_BASE_URL=https://api.example.com/api/v1 npm run dev
```

## User flow

1. Create an applicant passport.
2. Upload a complete UTF-8 CSV statement.
3. Review deduplicated evidence, the seven-domain score, reliability and reason codes.
4. Record a move, job change or return-to-India event for score-neutral guidance.
5. Switch to the lender workspace to inspect the queue and held-out model validation.

No score is displayed before valid evidence exists. Upload errors and unsupported formats are returned by the API and shown without a success fallback.

## Quality gates

```bash
npm run lint
npm run typecheck
npm run build
```

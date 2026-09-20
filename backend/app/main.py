from __future__ import annotations

import hashlib
import json
import mimetypes
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings
from .challenger import (
    ChallengerError,
    ChallengerInferenceError,
    ChallengerModelService,
)
from .db import Database
from .schemas import (
    ApplicantCreate,
    ApplicantResponse,
    ConfigResponse,
    ChallengerScoreResponse,
    DomainConfig,
    EvidenceResponse,
    EvidenceSourceResponse,
    EvidenceType,
    GuidePrompt,
    GuideQueryRequest,
    GuideResponse,
    GuideSourceResponse,
    GuidanceRequest,
    GuidanceTask,
    HealthResponse,
    ModelValidationResponse,
    ProductConfig,
    ProductType,
    StatementRecord,
    StatementIngestResponse,
    ScoreResponse,
    StructuredStatementIngest,
    TransitionEvent,
    TransitionResponse,
    TransitionUpdate,
)
from .scoring import (
    canonical_fingerprint,
    DOMAIN_DESCRIPTIONS,
    DOMAIN_LABELS,
    PRODUCT_WEIGHTS,
    SCORING_VERSION,
    calculate_score,
    event_response,
    unique_events,
)
from .statement_parser import StatementParseError, parse_csv, parse_statement_file
from .transition_guide import TransitionGuide, suggested_prompts


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value[:10])


def _http_error(status: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


def _get_applicant(db: Database, applicant_id: str) -> dict[str, Any]:
    with db.connection() as connection:
        row = connection.execute("SELECT * FROM applicants WHERE id = ?", (applicant_id,)).fetchone()
    if row is None:
        raise _http_error(404, "Applicant not found")
    return dict(row)


def _get_sources(db: Database, applicant_id: str) -> list[dict[str, Any]]:
    with db.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM evidence_sources WHERE applicant_id = ? ORDER BY period_end DESC, created_at DESC",
            (applicant_id,),
        ).fetchall()
    return Database.rows_dict(rows)


def _get_assertions(db: Database, applicant_id: str) -> list[dict[str, Any]]:
    with db.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM evidence_assertions WHERE applicant_id = ? ORDER BY occurred_on DESC, id DESC",
            (applicant_id,),
        ).fetchall()
    return Database.rows_dict(rows)


def _sources_map(sources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["id"]): row for row in sources}


def _score(db: Database, applicant: dict[str, Any], product: ProductType | None = None):
    selected = product or ProductType(applicant["product"])
    return calculate_score(applicant["id"], selected, _get_assertions(db, applicant["id"]), _get_sources(db, applicant["id"]))


def _applicant_response(db: Database, row: dict[str, Any]) -> ApplicantResponse:
    selected = ProductType(row["product"])
    score = _score(db, row, selected)
    return ApplicantResponse(
        id=row["id"],
        name=row["name"],
        corridor=row["corridor"],
        product=selected,
        requested_amount=row["requested_amount"],
        currency=row["currency"],
        employment=row["employment"],
        residency=row["residency"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        score=score.score if score.assertion_count else None,
        reliability=score.reliability,
        reliability_band=score.reliability_band,
        assertion_count=score.assertion_count,
        unique_event_count=score.unique_event_count,
    )


def _insert_statement(
    db: Database,
    applicant_id: str,
    statement: StructuredStatementIngest,
    *,
    filename: str | None = None,
    content_type: str | None = None,
    file_bytes: bytes | None = None,
) -> EvidenceSourceResponse:
    source_id = _new_id("SRC")
    created_at = _now()
    source_type = statement.source_type.value
    with db.connection() as connection:
        connection.execute(
            """
            INSERT INTO evidence_sources
              (id, applicant_id, source_type, provider, currency, period_start, period_end, assertion_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                applicant_id,
                source_type,
                statement.provider,
                statement.currency,
                statement.period_start.isoformat(),
                statement.period_end.isoformat(),
                len(statement.records),
                created_at,
            ),
        )
        for record in statement.records:
            fingerprint = _statement_fingerprint(record)
            connection.execute(
                """
                INSERT INTO evidence_assertions
                  (id, applicant_id, source_id, occurred_on, event_type, amount, currency, direction,
                   reference, due_on, paid_on, description, balance_after, metadata_json, fingerprint)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _new_id("AST"),
                    applicant_id,
                    source_id,
                    record.occurred_on.isoformat(),
                    record.event_type,
                    record.amount,
                    record.currency or statement.currency,
                    record.direction.value,
                    record.reference,
                    record.due_on.isoformat() if record.due_on else None,
                    record.paid_on.isoformat() if record.paid_on else None,
                    record.description,
                    record.balance_after,
                    db.json_dumps(record.metadata),
                    fingerprint,
                ),
            )
        if filename is not None and file_bytes is not None:
            connection.execute(
                """
                INSERT INTO statement_uploads
                  (id, applicant_id, source_id, filename, content_type, size_bytes, sha256, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _new_id("UPL"),
                    applicant_id,
                    source_id,
                    filename,
                    content_type or "text/csv",
                    len(file_bytes),
                    hashlib.sha256(file_bytes).hexdigest(),
                    created_at,
                ),
            )
        connection.execute("UPDATE applicants SET updated_at = ? WHERE id = ?", (created_at, applicant_id))

    all_sources = _get_sources(db, applicant_id)
    all_assertions = _get_assertions(db, applicant_id)
    events = unique_events(all_assertions, _sources_map(all_sources))
    source_events = [event for event in events if source_id in event.source_ids]
    corroborated = sum(max(0, len(event.source_ids) - 1) for event in source_events)
    return EvidenceSourceResponse(
        id=source_id,
        applicant_id=applicant_id,
        source_type=statement.source_type,
        provider=statement.provider,
        currency=statement.currency,
        period_start=statement.period_start,
        period_end=statement.period_end,
        assertion_count=len(statement.records),
        unique_event_count=len(source_events),
        corroborated_count=corroborated,
        created_at=created_at,
    )


def _statement_fingerprint(record: StatementRecord) -> str:
    return canonical_fingerprint(
        record.occurred_on,
        record.event_type,
        record.amount,
        record.currency,
        record.direction.value,
    )


def _csv_statement(
    content: bytes,
    *,
    source_type: EvidenceType,
    provider: str,
    currency: str,
    consent: bool,
) -> StructuredStatementIngest:
    if not consent:
        raise _http_error(400, "consent must be true before a statement is ingested")
    try:
        return parse_csv(content, source_type=source_type, provider=provider, currency=currency.upper())
    except StatementParseError as exc:
        raise _http_error(422, str(exc)) from exc


def _guidance(event: TransitionEvent | None) -> list[GuidanceTask]:
    if event is None:
        return []
    rbi = "https://www.rbi.org.in/"
    tax = "https://www.incometax.gov.in/"
    tasks: dict[TransitionEvent, list[GuidanceTask]] = {
        TransitionEvent.MOVING_ABROAD: [
            GuidanceTask(id="preserve-statements", title="Preserve the complete financial record", action="Download complete bank, payroll, rent and repayment statements before access or residency changes.", priority="now", sources=[rbi]),
            GuidanceTask(id="record-destination-income", title="Record destination employment", action="Capture employer, expected start date and first expected pay cycle as prospective evidence.", priority="next", sources=[]),
            GuidanceTask(id="review-indian-accounts", title="Review Indian account status", action="Ask the bank whether account type, KYC or tax declarations need updating after the move.", priority="next", sources=[rbi, tax]),
        ],
        TransitionEvent.JOB_CHANGE: [
            GuidanceTask(id="preserve-employment-end", title="Close the previous employment period", action="Add the final payslip and termination or relieving letter so the old period remains traceable.", priority="now", sources=[]),
            GuidanceTask(id="calculate-runway", title="Calculate cash runway", action="Use current liquid balances and recurring obligations to understand the transition period.", priority="now", sources=[]),
            GuidanceTask(id="separate-prospective-income", title="Separate prospective income", action="Store a signed offer and expected joining date separately from observed income.", priority="next", sources=[]),
        ],
        TransitionEvent.RETURNING_INDIA: [
            GuidanceTask(id="check-fema-status", title="Check FEMA residential status", action="Review the current facts and confirm status with the bank or authorised adviser; FEMA status is separate from income-tax residency.", priority="now", sources=[rbi]),
            GuidanceTask(id="review-nre-nro", title="Review NRE/NRO account actions", action="Ask the bank whether NRE/NRO accounts need conversion, redesignation or updated KYC after return.", priority="now", sources=[rbi]),
            GuidanceTask(id="update-fatca-crs", title="Update KYC, FATCA and CRS", action="Complete the declarations and account updates requested by the relevant financial institution.", priority="next", sources=[rbi]),
            GuidanceTask(id="check-tax-residency", title="Check income-tax residency separately", action="Use the official tax guidance and the person’s day-count and facts; do not infer tax residency from a bank account type.", priority="next", sources=[tax]),
        ],
    }
    return tasks[event]


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime = settings or Settings.from_env()
    runtime.ensure_database_parent()
    database = Database(runtime.db_path)
    database.initialise()
    challenger_service = ChallengerModelService(runtime.challenger_model_artifact_path)
    transition_guide = TransitionGuide()

    app = FastAPI(
        title="Credit Passport API",
        version="0.1.0",
        description="Permissioned financial evidence ingestion and explainable, product-specific assessment.",
    )
    app.state.db = database
    app.state.settings = runtime
    app.state.transition_guide = transition_guide
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    @app.get("/healthz", response_model=HealthResponse, tags=["system"])
    @app.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        try:
            with database.connection() as connection:
                connection.execute("SELECT 1").fetchone()
            status = "ok"
        except Exception as exc:  # pragma: no cover - operational failure path
            raise _http_error(503, f"database unavailable: {exc}") from exc
        return HealthResponse(status="ok", service="credit-passport-api", database=status, scoring_version=SCORING_VERSION)

    @app.get("/api/v1/config", response_model=ConfigResponse, tags=["system"])
    def config() -> ConfigResponse:
        return ConfigResponse(
            products=[
                ProductConfig(product=product, label=product.value.replace("-", " ").title(), weights=weights)
                for product, weights in PRODUCT_WEIGHTS.items()
            ],
            domains=[DomainConfig(key=key, label=DOMAIN_LABELS[key], description=DOMAIN_DESCRIPTIONS[key]) for key in DOMAIN_LABELS],
            evidence_types=list(EvidenceType),
            transition_events=list(TransitionEvent),
            scoring_version=SCORING_VERSION,
        )

    @app.get("/api/v1/products", response_model=list[ProductConfig], tags=["system"])
    def products() -> list[ProductConfig]:
        return config().products

    @app.get("/api/v1/model/validation", response_model=ModelValidationResponse, tags=["system"])
    def model_validation() -> ModelValidationResponse:
        metrics_path = Path(runtime.model_metrics_path).expanduser()
        if not metrics_path.is_absolute():
            metrics_path = (Path.cwd() / metrics_path).resolve()
        if not metrics_path.exists():
            return ModelValidationResponse(status="unavailable", metrics=None, message="No validation artifact is available; the transparent scorecard remains active.")
        try:
            payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return ModelValidationResponse(status="invalid", metrics=None, message=f"Validation artifact could not be read: {exc}")
        if not isinstance(payload, dict):
            return ModelValidationResponse(status="invalid", metrics=None, message="Validation artifact must contain a JSON object.")
        secondary_path = metrics_path.with_name("secondary_heloc_metrics.json")
        if secondary_path.exists():
            try:
                secondary = json.loads(secondary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                secondary = None
            if isinstance(secondary, dict):
                payload = {**payload, "secondary_benchmarks": {"heloc_external_risk": secondary}}
        return ModelValidationResponse(status="available", metrics=payload, message="Validation artifact loaded for read-only inspection; it is not used for applicant scoring.")

    @app.post("/api/v1/applicants", response_model=ApplicantResponse, status_code=201, tags=["applicants"])
    def create_applicant(payload: ApplicantCreate) -> ApplicantResponse:
        applicant_id = _new_id("CP")
        now = _now()
        with database.connection() as connection:
            connection.execute(
                """
                INSERT INTO applicants
                  (id, name, corridor, product, requested_amount, currency, employment, residency, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (applicant_id, payload.name, payload.corridor, payload.product.value, payload.requested_amount, payload.currency, payload.employment, payload.residency, now, now),
            )
        return _applicant_response(database, _get_applicant(database, applicant_id))

    @app.get("/api/v1/applicants", response_model=list[ApplicantResponse], tags=["applicants"])
    def list_applicants() -> list[ApplicantResponse]:
        with database.connection() as connection:
            rows = connection.execute("SELECT * FROM applicants ORDER BY created_at DESC").fetchall()
        return [_applicant_response(database, dict(row)) for row in rows]

    @app.get("/api/v1/applicants/{applicant_id}", response_model=ApplicantResponse, tags=["applicants"])
    def get_applicant(applicant_id: str) -> ApplicantResponse:
        return _applicant_response(database, _get_applicant(database, applicant_id))

    @app.get("/api/v1/applicants/{applicant_id}/evidence", response_model=EvidenceResponse, tags=["evidence"])
    def evidence(applicant_id: str) -> EvidenceResponse:
        _get_applicant(database, applicant_id)
        sources = _get_sources(database, applicant_id)
        assertions = _get_assertions(database, applicant_id)
        source_map = _sources_map(sources)
        events = unique_events(assertions, source_map)
        source_responses: list[EvidenceSourceResponse] = []
        for source in sources:
            source_events = [event for event in events if source["id"] in event.source_ids]
            source_responses.append(
                EvidenceSourceResponse(
                    id=source["id"],
                    applicant_id=applicant_id,
                    source_type=EvidenceType(source["source_type"]) if source["source_type"] in {item.value for item in EvidenceType} else EvidenceType.OTHER,
                    provider=source["provider"],
                    currency=source["currency"],
                    period_start=source["period_start"],
                    period_end=source["period_end"],
                    assertion_count=source["assertion_count"],
                    unique_event_count=len(source_events),
                    corroborated_count=sum(max(0, len(event.source_ids) - 1) for event in source_events),
                    created_at=source["created_at"],
                )
            )
        return EvidenceResponse(
            applicant_id=applicant_id,
            assertion_count=len(assertions),
            unique_event_count=len(events),
            corroborated_count=max(0, len(assertions) - len(events)),
            sources=source_responses,
            events=[event_response(event, source_map) for event in events],
        )

    @app.post("/api/v1/applicants/{applicant_id}/evidence", response_model=EvidenceSourceResponse, status_code=201, tags=["evidence"])
    def ingest_evidence(applicant_id: str, payload: StructuredStatementIngest) -> EvidenceSourceResponse:
        _get_applicant(database, applicant_id)
        return _insert_statement(database, applicant_id, payload)

    @app.post("/api/v1/applicants/{applicant_id}/statements", response_model=StatementIngestResponse, status_code=201, tags=["evidence"])
    async def ingest_statement_file(
        applicant_id: str,
        file: UploadFile = File(...),
        source_type: EvidenceType = Form(EvidenceType.BANK_STATEMENT),
        provider: str = Form(...),
        currency: str = Form("INR"),
        consent: bool = Form(...),
    ) -> StatementIngestResponse:
        applicant = _get_applicant(database, applicant_id)
        filename = file.filename or "statement.csv"
        content = await file.read(runtime.max_upload_bytes + 1)
        if len(content) > runtime.max_upload_bytes:
            raise _http_error(413, f"Statement exceeds the {runtime.max_upload_bytes} byte upload limit")
        if not consent:
            raise _http_error(400, "consent must be true before a statement is ingested")
        try:
            statement = parse_statement_file(
                content,
                filename=filename,
                source_type=source_type,
                provider=provider,
                currency=currency.upper(),
            )
        except StatementParseError as exc:
            # Unsupported extensions are a media-type problem; malformed or
            # unreadable content is a user-correctable validation error.
            status = 415 if str(exc).startswith("Unsupported statement format") else 422
            raise _http_error(status, str(exc)) from exc
        source = _insert_statement(
            database,
            applicant_id,
            statement,
            filename=filename,
            content_type=file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
            file_bytes=content,
        )
        score = _score(database, applicant, ProductType(applicant["product"]))
        return StatementIngestResponse(applicant_id=applicant_id, source=source, parsed_rows=len(statement.records), score=score)

    @app.get("/api/v1/applicants/{applicant_id}/score", response_model=ScoreResponse, tags=["score"])
    def score(applicant_id: str, product: ProductType = ProductType.PERSONAL_LOAN) -> ScoreResponse:
        applicant = _get_applicant(database, applicant_id)
        return _score(database, applicant, product)

    @app.get(
        "/api/v1/applicants/{applicant_id}/challenger-score",
        response_model=ChallengerScoreResponse,
        tags=["score"],
        summary="Run the configured ICP challenger model",
    )
    def challenger_score(
        applicant_id: str,
        product: ProductType = ProductType.PERSONAL_LOAN,
    ) -> ChallengerScoreResponse:
        """Serve an applicant-level probability from the versioned challenger.

        The endpoint is intentionally separate from ``/score``.  A missing or
        invalid artifact is a 503 rather than a fabricated fallback, and an
        applicant with no evidence receives a 422 rather than a guessed score.
        """

        applicant = _get_applicant(database, applicant_id)
        sources = _get_sources(database, applicant_id)
        assertions = _get_assertions(database, applicant_id)
        events = unique_events(assertions, _sources_map(sources))
        transparent = _score(database, applicant, product)
        try:
            return challenger_service.infer(
                applicant=applicant,
                product=product,
                events=events,
                source_rows=sources,
                assertion_count=len(assertions),
                corroborated_count=max(0, len(assertions) - len(events)),
                transparent_score=transparent.score,
            )
        except ChallengerInferenceError as exc:
            raise _http_error(422, str(exc)) from exc
        except ChallengerError as exc:
            raise _http_error(503, str(exc)) from exc

    @app.get("/api/v1/applicants/{applicant_id}/transition", response_model=TransitionResponse, tags=["transition"])
    def get_transition(applicant_id: str, event: TransitionEvent | None = None) -> TransitionResponse:
        _get_applicant(database, applicant_id)
        with database.connection() as connection:
            row = connection.execute("SELECT * FROM transitions WHERE applicant_id = ?", (applicant_id,)).fetchone()
        if row is None:
            return TransitionResponse(applicant_id=applicant_id, event=event, tasks=_guidance(event))
        payload = dict(row)
        event = TransitionEvent(payload["event"]) if payload["event"] else None
        return TransitionResponse(
            applicant_id=applicant_id,
            event=event,
            country_from=payload["country_from"],
            country_to=payload["country_to"],
            facts=database.json_loads(payload["facts_json"], {}),
            tasks=_guidance(event),
            updated_at=payload["updated_at"],
        )

    @app.put("/api/v1/applicants/{applicant_id}/transition", response_model=TransitionResponse, tags=["transition"])
    def put_transition(applicant_id: str, payload: TransitionUpdate) -> TransitionResponse:
        _get_applicant(database, applicant_id)
        updated_at = _now()
        with database.connection() as connection:
            connection.execute(
                """
                INSERT INTO transitions (applicant_id, event, country_from, country_to, facts_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(applicant_id) DO UPDATE SET
                  event=excluded.event,
                  country_from=excluded.country_from,
                  country_to=excluded.country_to,
                  facts_json=excluded.facts_json,
                  updated_at=excluded.updated_at
                """,
                (applicant_id, payload.event.value if payload.event else None, payload.country_from, payload.country_to, database.json_dumps(payload.facts), updated_at),
            )
        return TransitionResponse(
            applicant_id=applicant_id,
            event=payload.event,
            country_from=payload.country_from,
            country_to=payload.country_to,
            facts=payload.facts,
            tasks=_guidance(payload.event),
            updated_at=updated_at,
        )

    @app.post("/api/v1/transition-guidance", response_model=TransitionResponse, tags=["transition"])
    def transition_guidance(payload: GuidanceRequest) -> TransitionResponse:
        return TransitionResponse(
            applicant_id="unattached",
            event=payload.event,
            country_from=payload.country_from,
            country_to=payload.country_to,
            facts=payload.facts,
            tasks=_guidance(payload.event),
        )

    @app.get(
        "/api/v1/guide/sources",
        response_model=list[GuideSourceResponse],
        tags=["transition-guide"],
        summary="List the official sources used by the transition guide",
    )
    def guide_sources() -> list[GuideSourceResponse]:
        return transition_guide.list_sources()

    @app.get(
        "/api/v1/guide/suggested-prompts",
        response_model=list[GuidePrompt],
        tags=["transition-guide"],
        summary="List starter questions for the transition guide",
    )
    def guide_suggested_prompts() -> list[GuidePrompt]:
        return suggested_prompts()

    @app.post(
        "/api/v1/guide/query",
        response_model=GuideResponse,
        tags=["transition-guide"],
        summary="Ask a source-grounded India cross-border transition question",
    )
    def guide_query(payload: GuideQueryRequest) -> GuideResponse:
        return transition_guide.query(payload)

    return app


app = create_app()

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductType(str, Enum):
    CREDIT_CARD = "credit-card"
    PERSONAL_LOAN = "personal-loan"
    STUDENT_LOAN = "student-loan"


class EvidenceType(str, Enum):
    BANK_STATEMENT = "bank-statement"
    PAYROLL = "payroll"
    RENT = "rent"
    UTILITY = "utility"
    REMITTANCE = "remittance"
    WALLET = "wallet"
    PLATFORM_EARNINGS = "platform-earnings"
    ASSET_REPAYMENT = "asset-repayment"
    INSURANCE = "insurance"
    MERCHANT_SALES = "merchant-sales"
    OTHER = "other"


class Direction(str, Enum):
    CREDIT = "credit"
    DEBIT = "debit"


class TransitionEvent(str, Enum):
    MOVING_ABROAD = "moving-abroad"
    JOB_CHANGE = "job-change"
    RETURNING_INDIA = "returning-india"


class ReliabilityBand(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class ApplicantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    corridor: str = Field(min_length=1, max_length=120)
    product: ProductType = ProductType.PERSONAL_LOAN
    requested_amount: float | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    employment: str | None = Field(default=None, max_length=160)
    residency: str | None = Field(default=None, max_length=160)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class ApplicantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: ProductType | None = None
    requested_amount: float | None = Field(default=None, ge=0)
    employment: str | None = Field(default=None, max_length=160)
    residency: str | None = Field(default=None, max_length=160)


class StatementRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurred_on: date
    event_type: str = Field(min_length=1, max_length=80)
    amount: float = Field(ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    direction: Direction
    reference: str | None = Field(default=None, max_length=200)
    due_on: date | None = None
    paid_on: date | None = None
    description: str | None = Field(default=None, max_length=500)
    balance_after: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class StructuredStatementIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: EvidenceType = EvidenceType.BANK_STATEMENT
    provider: str = Field(min_length=1, max_length=160)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    period_start: date
    period_end: date
    records: list[StatementRecord] = Field(min_length=1, max_length=10000)
    consent: Literal[True]

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("period_end")
    @classmethod
    def period_is_ordered(cls, value: date, info: Any) -> date:
        start = info.data.get("period_start")
        if start is not None and value < start:
            raise ValueError("period_end must be on or after period_start")
        return value


class ApplicantResponse(BaseModel):
    id: str
    name: str
    corridor: str
    product: ProductType
    requested_amount: float | None
    currency: str
    employment: str | None
    residency: str | None
    created_at: datetime
    updated_at: datetime
    score: int | None = None
    reliability: int = 0
    reliability_band: ReliabilityBand = ReliabilityBand.LOW
    assertion_count: int = 0
    unique_event_count: int = 0


class EvidenceSourceResponse(BaseModel):
    id: str
    applicant_id: str
    source_type: EvidenceType
    provider: str
    currency: str
    period_start: date
    period_end: date
    assertion_count: int
    unique_event_count: int
    corroborated_count: int
    created_at: datetime


class EconomicEventResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    date: date
    event_type: str
    amount: float
    currency: str
    direction: Direction
    source_ids: list[str]
    source_types: list[EvidenceType]
    financial_construct: str = Field(alias="construct", serialization_alias="construct")
    status: Literal["scored", "corroborated", "policy-only"]
    reference: str | None = None
    description: str | None = None


class EvidenceResponse(BaseModel):
    applicant_id: str
    assertion_count: int
    unique_event_count: int
    corroborated_count: int
    sources: list[EvidenceSourceResponse]
    events: list[EconomicEventResponse]


class ReasonCode(BaseModel):
    code: str
    domain: str
    message: str
    evidence_ids: list[str] = Field(default_factory=list)
    value: str | None = None


class DomainResult(BaseModel):
    key: str
    label: str
    observed: int
    reliability: int
    adjusted: float
    weight: int
    contribution: float
    evidence_count: int
    reason_codes: list[ReasonCode]


class ScoreRange(BaseModel):
    p10: int
    p90: int


class ScoreResponse(BaseModel):
    applicant_id: str
    product: ProductType
    score: int
    band: ReliabilityBand
    reliability: int
    reliability_band: ReliabilityBand
    assertion_count: int
    unique_event_count: int
    corroborated_count: int
    score_range: ScoreRange
    domains: list[DomainResult]
    reason_codes: list[ReasonCode]
    generated_at: datetime


class ChallengerRiskBand(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ChallengerBlendResponse(BaseModel):
    """Research-only combination of the transparent score and challenger output."""

    transparent_score: int
    challenger_score: float
    model_weight: float = Field(ge=0, le=1)
    model_contribution: float
    blended_score: float
    decision_use: Literal["research-only"] = "research-only"


class ChallengerScoreResponse(BaseModel):
    """An applicant-level prediction from the versioned ICP challenger artifact.

    The probability is the artifact's declared adverse-outcome probability.  It
    is intentionally returned beside the transparent score and never replaces
    the explainable scorecard or becomes an approval decision by itself.
    """

    applicant_id: str
    product: ProductType
    model_name: str
    task: Literal["adverse_outcome_probability"]
    probability: float = Field(ge=0, le=1)
    risk_band: ChallengerRiskBand
    feature_values: dict[str, float]
    artifact_version: str
    validation_summary: dict[str, Any]
    provenance: dict[str, Any]
    blend: ChallengerBlendResponse
    generated_at: datetime


class ProductConfig(BaseModel):
    product: ProductType
    label: str
    weights: dict[str, int]


class DomainConfig(BaseModel):
    key: str
    label: str
    description: str


class ConfigResponse(BaseModel):
    products: list[ProductConfig]
    domains: list[DomainConfig]
    evidence_types: list[EvidenceType]
    transition_events: list[TransitionEvent]
    scoring_version: str


class StatementIngestResponse(BaseModel):
    applicant_id: str
    source: EvidenceSourceResponse
    parsed_rows: int
    score: ScoreResponse


class TransitionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: TransitionEvent | None = None
    country_from: str | None = Field(default=None, max_length=100)
    country_to: str | None = Field(default=None, max_length=100)
    facts: dict[str, Any] = Field(default_factory=dict)


class GuidanceTask(BaseModel):
    id: str
    title: str
    action: str
    priority: Literal["now", "next", "when-ready"]
    score_effect: Literal["none"] = "none"
    sources: list[str] = Field(default_factory=list)


class TransitionResponse(BaseModel):
    applicant_id: str
    event: TransitionEvent | None
    country_from: str | None = None
    country_to: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    tasks: list[GuidanceTask] = Field(default_factory=list)
    disclaimer: str = "Guidance is informational; confirm tax, FEMA and account actions with the relevant official authority or adviser."
    updated_at: datetime | None = None


class GuidanceRequest(TransitionUpdate):
    pass


class GuideIntent(str, Enum):
    GENERAL = "general"
    MOVING_ABROAD = "moving-abroad"
    RETURNING_INDIA = "returning-india"
    JOB_CHANGE = "job-change"
    ACCOUNT_CHOICES = "account-choices"
    RESIDENTIAL_STATUS = "residential-status"
    ACCOUNT_CONVERSION = "account-conversion"
    KYC_FATCA_CRS = "kyc-fatca-crs"


class GuideQueryRequest(BaseModel):
    """A stateless, source-grounded question for the transition guide."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=3, max_length=4000)
    intent: GuideIntent | None = None
    session_id: str | None = Field(default=None, min_length=1, max_length=120)
    country_from: str | None = Field(default=None, max_length=100)
    country_to: str | None = Field(default=None, max_length=100)
    facts: dict[str, Any] = Field(default_factory=dict)
    max_sources: int = Field(default=4, ge=1, le=6)


class GuideCitation(BaseModel):
    id: str
    title: str
    publisher: str
    url: str
    locator: str | None = None
    matched_topics: list[str] = Field(default_factory=list)


class GuidePrompt(BaseModel):
    id: str
    label: str
    query: str
    intent: GuideIntent


class GuideSourceResponse(BaseModel):
    id: str
    title: str
    publisher: str
    url: str
    locator: str | None = None
    last_reviewed: date
    topics: list[str] = Field(default_factory=list)
    summary: str


class GuideResponse(BaseModel):
    """Stable frontend contract for source-grounded transition guidance."""

    query: str
    answer: str
    bullets: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    citations: list[GuideCitation] = Field(min_length=1)
    suggested_prompts: list[GuidePrompt] = Field(default_factory=list)
    grounded: bool
    abstained: bool
    provider: Literal["deterministic", "gemini"]
    provider_status: Literal["keyless", "configured", "fallback"]
    session_id: str | None = None
    disclaimer: str = "This is general information, not legal or tax advice. Confirm account, FEMA and tax actions with your bank, authorised dealer or qualified adviser. It does not affect a credit score or lending decision."


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    database: Literal["ok"]
    scoring_version: str


class ModelValidationResponse(BaseModel):
    status: Literal["available", "unavailable", "invalid"]
    metrics: dict[str, Any] | None = None
    message: str

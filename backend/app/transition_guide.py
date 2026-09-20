from __future__ import annotations

"""Source-grounded guidance for people moving between India and another country.

The guide is intentionally small and explicit.  The checked-in source register is
the retrieval boundary; when a question does not match that register, the guide
abstains instead of filling the gap from general model knowledge.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .config import load_local_env
from .schemas import (
    GuideCitation,
    GuideIntent,
    GuidePrompt,
    GuideQueryRequest,
    GuideResponse,
    GuideSourceResponse,
)


GUIDE_DISCLAIMER = (
    "This is general information, not legal or tax advice. Confirm account, FEMA and tax actions "
    "with your bank, authorised dealer or qualified adviser. It does not affect a credit score or "
    "lending decision."
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_STOP_WORDS = {
    "a", "about", "after", "again", "all", "an", "and", "are", "as", "at", "be", "before",
    "can", "do", "for", "from", "how", "i", "if", "in", "is", "it", "me", "my", "of",
    "on", "or", "should", "the", "this", "to", "what", "when", "with", "you", "your",
}


@dataclass(frozen=True)
class PolicySource:
    id: str
    title: str
    publisher: str
    url: str
    locator: str | None
    last_reviewed: date
    topics: tuple[str, ...]
    intents: tuple[str, ...]
    summary: str
    key_points: tuple[str, ...]


@dataclass(frozen=True)
class RetrievedSource:
    source: PolicySource
    score: float
    matched_topics: tuple[str, ...]


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str | None
    model: str = "gemini-2.5-flash"
    base_url: str = "https://generativelanguage.googleapis.com/v1beta/models"
    timeout_seconds: float = 20.0
    mode: str = "auto"

    @classmethod
    def from_env(cls) -> "GeminiConfig":
        load_local_env()
        mode = os.getenv("CREDIT_PASSPORT_GUIDE_PROVIDER", "auto").strip().lower()
        if mode not in {"auto", "deterministic", "gemini"}:
            mode = "auto"
        try:
            timeout = max(3.0, min(60.0, float(os.getenv("GEMINI_TIMEOUT_SECONDS", "20"))))
        except ValueError:
            timeout = 20.0
        api_key = os.getenv("GEMINI_API_KEY", "").strip() or None
        return cls(
            api_key=api_key,
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            base_url=os.getenv(
                "GEMINI_API_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/models",
            ).rstrip("/"),
            timeout_seconds=timeout,
            mode=mode,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) and self.mode != "deterministic"


class GuideProviderError(RuntimeError):
    """A provider failure that must never be shown with credentials or raw payloads."""


def default_policy_path() -> Path:
    return Path(__file__).resolve().parents[1] / "policy_knowledge" / "sources.json"


def load_policy_sources(path: str | Path | None = None) -> tuple[PolicySource, ...]:
    source_path = Path(path) if path is not None else default_policy_path()
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Guide policy source register could not be loaded: {source_path}") from exc
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("Guide policy source register must contain at least one source")

    sources: list[PolicySource] = []
    seen: set[str] = set()
    for raw in payload:
        if not isinstance(raw, dict):
            raise RuntimeError("Guide policy source register contains an invalid record")
        required = {"id", "title", "publisher", "url", "last_reviewed", "topics", "intents", "summary", "key_points"}
        if not required.issubset(raw):
            missing = ", ".join(sorted(required - set(raw)))
            raise RuntimeError(f"Guide policy source is missing fields: {missing}")
        source_id = str(raw["id"])
        if source_id in seen:
            raise RuntimeError(f"Guide policy source id is duplicated: {source_id}")
        seen.add(source_id)
        try:
            reviewed = date.fromisoformat(str(raw["last_reviewed"]))
        except ValueError as exc:
            raise RuntimeError(f"Guide policy source has invalid review date: {source_id}") from exc
        topics = tuple(str(item).strip().lower() for item in raw["topics"] if str(item).strip())
        intents = tuple(str(item).strip().lower() for item in raw["intents"] if str(item).strip())
        key_points = tuple(str(item).strip() for item in raw["key_points"] if str(item).strip())
        if not topics or not key_points or not str(raw["url"]).startswith("https://"):
            raise RuntimeError(f"Guide policy source is incomplete: {source_id}")
        sources.append(
            PolicySource(
                id=source_id,
                title=str(raw["title"]),
                publisher=str(raw["publisher"]),
                url=str(raw["url"]),
                locator=str(raw["locator"]) if raw.get("locator") else None,
                last_reviewed=reviewed,
                topics=topics,
                intents=intents,
                summary=str(raw["summary"]),
                key_points=key_points,
            )
        )
    return tuple(sources)


def _terms(value: str | None) -> set[str]:
    if not value:
        return set()
    normalized = value.lower().replace("fcnr(b)", "fcnr b").replace("fcnr-b", "fcnr b")
    return {term for term in _WORD_RE.findall(normalized) if term not in _STOP_WORDS and len(term) > 1}


def _compact_topic(topic: str) -> set[str]:
    return _terms(topic.replace("_", " ").replace("-", " "))


def _matched_topics(query_terms: set[str], topics: Iterable[str]) -> tuple[str, ...]:
    matched: list[str] = []
    for topic in topics:
        topic_terms = _compact_topic(topic)
        if topic_terms and topic_terms.intersection(query_terms):
            matched.append(topic)
    return tuple(sorted(set(matched)))


def retrieve_sources(
    query: str,
    intent: GuideIntent | None,
    sources: Iterable[PolicySource],
    limit: int = 4,
) -> list[RetrievedSource]:
    """Return the highest-scoring official sources for a question.

    Retrieval uses topic and intent overlap only.  It is deliberately not a
    free-form web search, so an answer cannot silently expand beyond the checked-in
    policy register.
    """

    terms = _terms(query)
    requested_intent = intent.value if intent else None
    scored: list[RetrievedSource] = []
    for source in sources:
        topic_terms: set[str] = set()
        for topic in source.topics:
            topic_terms.update(_compact_topic(topic))
        topic_overlap = terms.intersection(topic_terms)
        score = float(len(topic_overlap))
        matched = _matched_topics(terms, source.topics)
        if requested_intent and requested_intent in source.intents:
            score += 2.5
        if not requested_intent and "general" in source.intents and terms.intersection(topic_terms):
            score += 0.25
        # Exact account names are useful high-signal terms in short questions.
        for phrase in ("nre", "nro", "fcnr", "rfc", "fatca", "crs", "fema"):
            if phrase in terms and phrase in topic_terms:
                score += 1.5
        if score > 0:
            scored.append(RetrievedSource(source=source, score=score, matched_topics=matched))
    scored.sort(key=lambda item: (-item.score, item.source.id))
    return scored[: max(1, min(6, limit))]


def _source_by_id(sources: Iterable[PolicySource], source_id: str) -> PolicySource | None:
    return next((source for source in sources if source.id == source_id), None)


def source_response(source: PolicySource) -> GuideSourceResponse:
    return GuideSourceResponse(
        id=source.id,
        title=source.title,
        publisher=source.publisher,
        url=source.url,
        locator=source.locator,
        last_reviewed=source.last_reviewed,
        topics=list(source.topics),
        summary=source.summary,
    )


def suggested_prompts() -> list[GuidePrompt]:
    return [
        GuidePrompt(
            id="moving-abroad-account-review",
            label="Moving abroad: account review",
            query="I am moving from India abroad for work. What should I ask my bank about my Indian accounts?",
            intent=GuideIntent.MOVING_ABROAD,
        ),
        GuidePrompt(
            id="compare-nri-accounts",
            label="Compare NRE, NRO and FCNR(B)",
            query="What is the practical difference between NRE, NRO and FCNR(B) accounts?",
            intent=GuideIntent.ACCOUNT_CHOICES,
        ),
        GuidePrompt(
            id="returning-india-checklist",
            label="Returning to India",
            query="I am returning to India after living abroad. What should I review first?",
            intent=GuideIntent.RETURNING_INDIA,
        ),
        GuidePrompt(
            id="fema-tax-residency",
            label="FEMA and tax residency",
            query="How is FEMA residential status different from income-tax residency?",
            intent=GuideIntent.RESIDENTIAL_STATUS,
        ),
        GuidePrompt(
            id="kyc-fatca-crs-update",
            label="KYC, FATCA and CRS",
            query="What KYC, FATCA and CRS updates might my bank ask for after a move?",
            intent=GuideIntent.KYC_FATCA_CRS,
        ),
    ]


def _citation(retrieved: Iterable[RetrievedSource]) -> list[GuideCitation]:
    return [
        GuideCitation(
            id=item.source.id,
            title=item.source.title,
            publisher=item.source.publisher,
            url=item.source.url,
            locator=item.source.locator,
            matched_topics=list(item.matched_topics),
        )
        for item in retrieved
    ]


def _contains(terms: set[str], *values: str) -> bool:
    return any(value in terms for value in values)


def _deterministic_content(
    request: GuideQueryRequest,
    retrieved: list[RetrievedSource],
) -> tuple[str, list[str], list[str], bool]:
    """Create a concise answer from the retrieved source register only."""

    terms = _terms(request.query)
    intent = request.intent
    if not retrieved:
        return (
            "I do not have enough official source support to answer that safely. "
            "I can help with NRE, NRO, FCNR(B) and RFC accounts; FEMA status; income-tax residency basics; "
            "KYC, FATCA and CRS; moving abroad; job changes; and returning to India.",
            [],
            [
                "How do NRE and NRO accounts differ?",
                "What should I review when returning to India?",
            ],
            False,
        )

    moving = intent == GuideIntent.MOVING_ABROAD or _contains(terms, "moving", "abroad", "overseas", "relocate", "leaving")
    returning = intent == GuideIntent.RETURNING_INDIA or _contains(terms, "returning", "return", "back", "home")
    tax = intent == GuideIntent.RESIDENTIAL_STATUS or _contains(terms, "tax", "residency", "resident", "days", "day")
    kyc = intent == GuideIntent.KYC_FATCA_CRS or _contains(terms, "kyc", "fatca", "crs", "self", "certification", "tin")
    accounts = intent in {GuideIntent.ACCOUNT_CHOICES, GuideIntent.ACCOUNT_CONVERSION} or _contains(
        terms, "nre", "nro", "fcnr", "rfc", "account", "accounts", "convert", "conversion"
    )
    job_change = intent == GuideIntent.JOB_CHANGE or _contains(
        terms,
        "job",
        "employment",
        "employer",
        "joining",
        "lost",
        "change",
        "jobless",
        "unemployed",
        "layoff",
        "laid",
        "redundancy",
        "terminated",
        "termination",
    )

    if job_change:
        return (
            "A job change can affect the facts your bank and tax records rely on, especially if the new job changes your country of work or intended stay. Ask the bank to review the account and KYC implications when the change is known.",
            [
                "Keep the end date of the old job and start date of the new job clear in your records.",
                "If the change involves leaving or returning to India, ask whether your FEMA account status needs review.",
                "Update address and tax-residency information, including FATCA or CRS details where requested.",
            ],
            [
                "Does my new country of work change my FEMA account status?",
                "What should I update with my bank after a job change?",
            ],
            True,
        )

    if returning:
        return (
            "On returning to India, start with your authorised dealer bank. Explain your return date, purpose and intended stay, then ask which accounts should be redesignated or converted.",
            [
                "NRE accounts should be designated resident or may be moved to an RFC account at the holder's option, subject to the current rules.",
                "FCNR(B) deposits may be allowed to continue to maturity; the bank can confirm whether an RFC or resident rupee account is appropriate at maturity.",
                "NRO accounts may be designated resident when you intend to stay in India for an uncertain period.",
                "Update KYC and tax-residency, FATCA and CRS information with the bank.",
            ],
            [
                "Should I ask my bank about NRE, NRO or RFC first?",
                "What information may I need to update after returning?",
            ],
            True,
        )

    if moving:
        return (
            "Before or soon after moving abroad, ask your authorised dealer bank to review your account status against your new facts. Keep the move, employment and tax-residency details consistent across your bank records.",
            [
                "Ask whether an existing resident account should be redesignated as NRO once you are a person resident outside India.",
                "Review whether NRE, NRO or FCNR(B) best fits the money you will receive, keep or send from India.",
                "Update KYC, address and tax-residency information, including any FATCA or CRS self-certification the bank requests.",
                "Keep the bank's confirmation and relevant statements with your records.",
            ],
            [
                "What is the difference between FEMA status and income-tax residency?",
                "Which account is generally used for income that stays in India?",
            ],
            True,
        )

    if tax and not accounts and not kyc:
        return (
            "Income-tax residency is checked separately for each tax year. It is not determined by whether an account is labelled NRE or NRO.",
            [
                "For tax years beginning on or after 1 April 2026, the official FAQ describes the basic 182-day test and the 60-days-plus-365-days test, subject to statutory exceptions.",
                "A citizen leaving India for employment outside India has a special rule in the official FAQ.",
                "Visiting citizens or persons of Indian origin, deemed residency and not-ordinarily-resident status can involve additional tests.",
                "Use the relevant tax year, day count and personal facts with the Income Tax Department guidance or a qualified adviser.",
            ],
            [
                "How many days have I spent in India in the relevant tax year?",
                "What is the difference between FEMA residence and tax residence?",
            ],
            True,
        )

    if kyc:
        return (
            "Your bank may need to refresh customer and tax-residency records after a move or return. Use the bank's current forms because the document list depends on your account and facts.",
            [
                "Be ready to confirm identity, address and other KYC details requested by the bank.",
                "FATCA or CRS information may include your tax-residence jurisdiction(s) and tax identification number or equivalent.",
                "Tell the financial institution when your country of residence or tax details change.",
            ],
            [
                "Why is my bank asking for a tax-residency self-certification?",
                "What should I update after returning to India?",
            ],
            True,
        )

    if accounts:
        return (
            "The useful distinction is what the account is for, where the money comes from and whether it needs to remain in foreign currency or be sent abroad. Your FEMA status and the bank's current rules still control the final choice.",
            [
                "NRE: rupee account generally used by eligible non-residents when repatriability is important.",
                "NRO: rupee account for a person resident outside India to handle Indian income and other permitted rupee transactions; interest is taxable and repatriation has conditions.",
                "FCNR(B): foreign-currency term deposit for eligible non-residents.",
                "RFC: resident foreign-currency account that may be relevant after returning to India if you are eligible.",
                "Ask your authorised dealer to confirm eligibility, permitted credits and debits, tax treatment and repatriation conditions for your facts.",
            ],
            [
                "Which account is used for Indian rent or pension after moving abroad?",
                "What changes when I return to India?",
            ],
            True,
        )

    if intent == GuideIntent.GENERAL or not terms:
        return (
            "I can help you work through Indian account choices, FEMA status, income-tax residency basics, KYC, FATCA and CRS, and the steps around moving abroad or returning to India.",
            [
                "Tell me whether you are moving abroad, changing jobs, or returning to India.",
                "Include the account type or residency question you want to understand.",
                "I will point to the official source and flag where the bank or a qualified adviser must confirm the answer.",
            ],
            [
                "I am moving abroad for work; where should I start?",
                "What is the difference between NRE, NRO and FCNR(B)?",
            ],
            True,
        )

    return (
        "I do not have enough official source support to answer that safely. Try one of the supported transition or account questions below.",
        [],
        [
            "How do NRE and NRO accounts differ?",
            "What should I review when returning to India?",
        ],
        False,
    )


def _retrieved_context(retrieved: list[RetrievedSource]) -> str:
    blocks: list[str] = []
    for item in retrieved:
        source = item.source
        points = "\n".join(f"- {point}" for point in source.key_points)
        blocks.append(
            f"SOURCE_ID: {source.id}\nTITLE: {source.title}\nPUBLISHER: {source.publisher}\nURL: {source.url}\n"
            f"LOCATOR: {source.locator or 'official source'}\nKEY POINTS:\n{points}"
        )
    return "\n\n".join(blocks)


class GeminiGuideProvider:
    """Minimal Gemini REST adapter; no provider dependency is required."""

    system_prompt = (
        "You are the Credit Passport transition guide for India cross-border account questions. "
        "Use only the supplied official source records. Do not use memory, outside knowledge or "
        "unstated policy. The user may ask for legal or tax advice: provide general information, "
        "say when the sources do not settle the facts, and preserve the non-advice boundary. "
        "Never discuss credit scoring or lending decisions as part of this guide. "
        "Return one JSON object with exactly these useful fields: answer (string), bullets (array "
        "of short strings), follow_up_questions (array of strings), citation_ids (array of source "
        "IDs). citation_ids must contain only supplied SOURCE_ID values and must contain at least "
        "one ID. If the source records do not support the question, say so and cite the closest "
        "source as a coverage boundary. Do not invent URLs, laws, thresholds or account actions."
    )

    def __init__(self, config: GeminiConfig) -> None:
        self.config = config

    def answer(
        self,
        request: GuideQueryRequest,
        retrieved: list[RetrievedSource],
    ) -> tuple[str, list[str], list[str], list[RetrievedSource]]:
        if not self.config.enabled:
            raise GuideProviderError("Gemini provider is not configured")
        source_ids = {item.source.id: item for item in retrieved}
        user_payload = {
            "question": request.query,
            "intent": request.intent.value if request.intent else None,
            "country_from": request.country_from,
            "country_to": request.country_to,
            "facts": request.facts,
            "source_records": _retrieved_context(retrieved),
        }
        body = {
            "systemInstruction": {"parts": [{"text": self.system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps(user_payload, ensure_ascii=False)}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "maxOutputTokens": 900,
            },
        }
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        url = (
            f"{self.config.base_url}/{urllib.parse.quote(self.config.model, safe='')}:generateContent?"
            f"{urllib.parse.urlencode({'key': self.config.api_key})}"
        )
        request_obj = urllib.request.Request(
            url,
            data=encoded,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request_obj, timeout=self.config.timeout_seconds) as response:
                raw = response.read(2_000_000).decode("utf-8")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GuideProviderError("Gemini provider request failed") from exc
        try:
            payload = json.loads(raw)
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            model_payload = self._parse_model_json(text)
            answer = str(model_payload["answer"]).strip()
            bullets = [str(item).strip() for item in model_payload.get("bullets", []) if str(item).strip()]
            follow_ups = [
                str(item).strip()
                for item in model_payload.get("follow_up_questions", [])
                if str(item).strip()
            ]
            citation_ids = model_payload.get("citation_ids")
            if not answer or not isinstance(citation_ids, list) or not citation_ids:
                raise ValueError("provider response omitted answer or citations")
            cited = [source_ids[str(source_id)] for source_id in citation_ids if str(source_id) in source_ids]
            if len(cited) != len(citation_ids):
                raise ValueError("provider response cited an unavailable source")
            return answer, bullets[:8], follow_ups[:5], cited
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GuideProviderError("Gemini provider returned an invalid grounded response") from exc

    @staticmethod
    def _parse_model_json(text: str) -> dict[str, Any]:
        cleaned = _CODE_FENCE_RE.sub("", text.strip())
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise
            payload = json.loads(cleaned[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("provider response must be an object")
        return payload


class TransitionGuide:
    """Retrieval, deterministic answer and optional Gemini orchestration."""

    def __init__(
        self,
        source_path: str | Path | None = None,
        provider_config: GeminiConfig | None = None,
    ) -> None:
        self.sources = load_policy_sources(source_path)
        self.config = provider_config or GeminiConfig.from_env()
        self.provider = GeminiGuideProvider(self.config)

    def list_sources(self) -> list[GuideSourceResponse]:
        return [source_response(source) for source in self.sources]

    def query(self, request: GuideQueryRequest) -> GuideResponse:
        retrieved = retrieve_sources(request.query, request.intent, self.sources, request.max_sources)
        supported = bool(retrieved and retrieved[0].score >= 1.0)
        if not supported:
            fallback = _source_by_id(self.sources, "rbi-accounts-non-residents-2025") or self.sources[0]
            # A coverage citation explains which official boundary was checked even
            # when the question itself is outside the guide's supported scope.
            retrieved = [RetrievedSource(source=fallback, score=0.0, matched_topics=())]
        answer, bullets, follow_ups, grounded = _deterministic_content(request, retrieved if supported else [])
        provider = "deterministic"
        provider_status = "keyless" if not self.config.enabled else "fallback"
        cited = retrieved
        if supported and self.config.enabled:
            try:
                answer, bullets, follow_ups, cited = self.provider.answer(request, retrieved)
                provider = "gemini"
                provider_status = "configured"
                grounded = True
            except GuideProviderError:
                # Keep a usable, cited answer when the optional provider is down.
                provider = "deterministic"
                provider_status = "fallback"
        return GuideResponse(
            query=request.query,
            answer=answer,
            bullets=bullets,
            follow_up_questions=follow_ups,
            citations=_citation(cited),
            suggested_prompts=suggested_prompts(),
            grounded=grounded,
            abstained=not grounded,
            provider=provider,
            provider_status=provider_status,
            session_id=request.session_id,
            disclaimer=GUIDE_DISCLAIMER,
        )

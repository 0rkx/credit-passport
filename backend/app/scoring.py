from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable

from .schemas import (
    DomainResult,
    EconomicEventResponse,
    EvidenceType,
    ProductType,
    ReasonCode,
    ReliabilityBand,
    ScoreRange,
    ScoreResponse,
)

SCORING_VERSION = "2026.09.v2"

DOMAIN_LABELS: dict[str, str] = {
    "commitment": "Commitment performance",
    "income": "Income continuity",
    "capacity": "Affordability and capacity",
    "liquidity": "Liquidity",
    "shock": "Shock resilience",
    "momentum": "Economic momentum",
    "cross_border": "Cross-border robustness",
}

DOMAIN_DESCRIPTIONS: dict[str, str] = {
    "commitment": "Due-and-paid obligations and recurring commitments.",
    "income": "Regularity and continuity of verified inflows.",
    "capacity": "Observed inflows relative to recurring outflows.",
    "liquidity": "Cash-flow balance and available liquid buffer.",
    "shock": "Evidence of reserves, protection and ability to absorb disruption.",
    "momentum": "Direction of income and net-flow trends across the period.",
    "cross_border": "Consistency and diversity of cross-border financial activity.",
}

PRODUCT_WEIGHTS: dict[ProductType, dict[str, int]] = {
    # Revolving credit is most sensitive to whether a person has kept regular
    # obligations current and can maintain a cash buffer between pay cycles.
    # Capacity still matters, but the card policy does not let a strong income
    # history compensate for weak payment or liquidity evidence as easily as a
    # term-loan policy would.
    ProductType.CREDIT_CARD: {
        "commitment": 35,
        "income": 10,
        "capacity": 15,
        "liquidity": 25,
        "shock": 5,
        "momentum": 5,
        "cross_border": 5,
    },
    # A fixed instalment needs observed room for a new payment and a stable
    # current income stream. Cross-border continuity stays visible, but no
    # policy-only or prospective-income signal enters this calculation.
    ProductType.PERSONAL_LOAN: {
        "commitment": 20,
        "income": 25,
        "capacity": 30,
        "liquidity": 10,
        "shock": 5,
        "momentum": 5,
        "cross_border": 5,
    },
    # For a student-loan review, current affordability and resilience matter
    # more than a long payment history. Momentum means observed current-income
    # direction only; it is deliberately not a proxy for projected graduate
    # earnings or an education-provider promise.
    ProductType.STUDENT_LOAN: {
        "commitment": 15,
        "income": 15,
        "capacity": 25,
        "liquidity": 10,
        "shock": 15,
        "momentum": 10,
        "cross_border": 10,
    },
}

EVENT_ALIASES: dict[str, str] = {
    "salary": "salary",
    "payroll": "salary",
    "wages": "salary",
    "gig_income": "gig_income",
    "gig earnings": "gig_income",
    "platform_earnings": "gig_income",
    "platform earnings": "gig_income",
    "business_income": "business_income",
    "merchant_sales": "merchant_sales",
    "stipend": "stipend",
    "scholarship": "stipend",
    "pension": "pension",
    "rent": "rent",
    "rent_payment": "rent",
    "utility": "utility",
    "utility_payment": "utility",
    "bill": "bill",
    "loan_payment": "loan_payment",
    "credit_card_payment": "credit_card_payment",
    "asset_repayment": "asset_repayment",
    "paygo": "asset_repayment",
    "insurance": "insurance",
    "insurance_premium": "insurance",
    "remittance": "remittance",
    "family_remittance": "remittance",
    "international_transfer": "international_transfer",
    "savings": "savings",
    "reserve_transfer": "savings",
    "deposit": "deposit",
}

INCOME_TYPES = {"salary", "gig_income", "business_income", "merchant_sales", "stipend", "pension"}
COMMITMENT_TYPES = {"rent", "utility", "bill", "loan_payment", "credit_card_payment", "asset_repayment", "insurance"}
CROSS_BORDER_TYPES = {"remittance", "international_transfer"}
PROTECTION_TYPES = {"insurance", "savings", "deposit"}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def normalize_event_type(value: str) -> str:
    key = re.sub(r"\s+", " ", value.strip().lower().replace("-", "_")).strip()
    return EVENT_ALIASES.get(key, key)


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _months_between(start: date, end: date) -> int:
    return max(1, (end.year - start.year) * 12 + end.month - start.month + 1)


def _band(value: int) -> ReliabilityBand:
    if value >= 75:
        return ReliabilityBand.HIGH
    if value >= 55:
        return ReliabilityBand.MEDIUM
    return ReliabilityBand.LOW


@dataclass
class UniqueEvent:
    id: str
    date: date
    event_type: str
    amount: float
    currency: str
    direction: str
    source_ids: list[str]
    source_types: list[str]
    reference: str | None
    description: str | None
    due_on: date | None
    paid_on: date | None
    balance_after: float | None
    assertion_ids: list[str]


def canonical_fingerprint(
    occurred_on: date | str,
    event_type: str,
    amount: float,
    currency: str,
    direction: str,
) -> str:
    event_type = normalize_event_type(event_type)
    occurred_on = _as_date(occurred_on).isoformat()
    amount = f"{float(amount):.2f}"
    currency = str(currency).upper()
    direction = str(direction).lower()
    # A same-day, same-amount, same-currency economic event from a second source is
    # corroboration even when the providers assign different reference IDs.
    return "|".join((occurred_on, event_type, amount, currency, direction))


def unique_events(assertions: Iterable[dict[str, Any]], sources: dict[str, dict[str, Any]]) -> list[UniqueEvent]:
    grouped: dict[str, UniqueEvent] = {}
    for row in assertions:
        source_id = str(row["source_id"])
        source = sources.get(source_id, {})
        source_type = str(source.get("source_type", EvidenceType.OTHER.value))
        key = str(
            row.get("fingerprint")
            or canonical_fingerprint(row["occurred_on"], str(row["event_type"]), float(row["amount"]), str(row["currency"]), str(row["direction"]))
        )
        event_type = normalize_event_type(str(row["event_type"]))
        if key not in grouped:
            grouped[key] = UniqueEvent(
                id=f"EV-{str(row['id'])[-10:]}",
                date=_as_date(row["occurred_on"]),
                event_type=event_type,
                amount=float(row["amount"]),
                currency=str(row["currency"]).upper(),
                direction=str(row["direction"]).lower(),
                source_ids=[source_id],
                source_types=[source_type],
                reference=row.get("reference"),
                description=row.get("description"),
                due_on=_as_date(row["due_on"]) if row.get("due_on") else None,
                paid_on=_as_date(row["paid_on"]) if row.get("paid_on") else None,
                balance_after=float(row["balance_after"]) if row.get("balance_after") is not None else None,
                assertion_ids=[str(row["id"])],
            )
        else:
            event = grouped[key]
            if source_id not in event.source_ids:
                event.source_ids.append(source_id)
            if source_type not in event.source_types:
                event.source_types.append(source_type)
            event.assertion_ids.append(str(row["id"]))
            # Prefer richer fields from a corroborating assertion.
            event.reference = event.reference or row.get("reference")
            event.description = event.description or row.get("description")
            event.due_on = event.due_on or (_as_date(row["due_on"]) if row.get("due_on") else None)
            event.paid_on = event.paid_on or (_as_date(row["paid_on"]) if row.get("paid_on") else None)
            if event.balance_after is None and row.get("balance_after") is not None:
                event.balance_after = float(row["balance_after"])
    return sorted(grouped.values(), key=lambda event: event.date, reverse=True)


def _event_matches(event: UniqueEvent, types: set[str]) -> bool:
    return event.event_type in types


def _reliability(events: list[UniqueEvent], period_months: int) -> int:
    if not events:
        return 0
    source_count = len({source_id for event in events for source_id in event.source_ids})
    complete_count = sum(1 for event in events if event.date and event.currency and event.direction)
    volume = min(1.0, len(events) / 8.0)
    source_diversity = min(1.0, source_count / 3.0)
    period = min(1.0, period_months / 6.0)
    completeness = complete_count / len(events)
    return round(100 * (0.48 * volume + 0.22 * source_diversity + 0.18 * period + 0.12 * completeness))


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _monthly_totals(events: list[UniqueEvent], direction: str | None = None) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for event in events:
        if direction is None or event.direction == direction:
            totals[f"{event.date.year:04d}-{event.date.month:02d}"] += event.amount
    return dict(totals)


def _reason(
    code: str,
    domain: str,
    message: str,
    events: list[UniqueEvent],
    value: str | None = None,
) -> ReasonCode:
    ids = [event.id for event in events[:10]]
    return ReasonCode(code=code, domain=domain, message=message, evidence_ids=ids, value=value)


def _domain_metrics(domain: str, all_events: list[UniqueEvent], period_months: int) -> tuple[float, int, list[ReasonCode], list[UniqueEvent]]:
    relevant: list[UniqueEvent]
    if domain == "commitment":
        relevant = [event for event in all_events if _event_matches(event, COMMITMENT_TYPES) or event.due_on is not None]
        if not relevant:
            return 50.0, 0, [_reason("COMMITMENT_NO_OBSERVATIONS", domain, "No due-and-paid commitments were observed.", [])], relevant
        scheduled = [event for event in relevant if event.due_on and event.paid_on]
        if scheduled:
            on_time = sum(event.paid_on <= event.due_on for event in scheduled)
            ratio = on_time / len(scheduled)
            observed = _clamp(35 + ratio * 65)
            code = "COMMITMENT_ON_TIME" if ratio >= 0.8 else "COMMITMENT_MISSED_OR_LATE"
            message = f"{on_time} of {len(scheduled)} scheduled commitments were paid on or before the due date."
            return observed, _reliability(relevant, period_months), [_reason(code, domain, message, scheduled, f"{ratio:.0%} on time")], relevant

        # A bank debit proves that a payment happened, but not that it happened
        # on time. Reward longitudinal payment evidence conservatively and keep
        # the missing due-date limitation explicit in the reason code.
        payments = [event for event in relevant if event.direction == "debit"]
        payment_months = {f"{event.date.year:04d}-{event.date.month:02d}" for event in payments}
        continuity = min(1.0, len(payment_months) / 12.0)
        observed = _clamp(50 + continuity * 15)
        message = (
            f"{len(payments)} commitment payment(s) were observed across {len(payment_months)} month(s); "
            "due dates were unavailable, so payment timeliness was not inferred."
        )
        return observed, _reliability(relevant, period_months), [
            _reason("COMMITMENT_PAYMENTS_OBSERVED", domain, message, payments, f"{len(payment_months)} payment month(s)")
        ], relevant

    if domain == "income":
        relevant = [event for event in all_events if event.direction == "credit" and event.event_type in INCOME_TYPES]
        if not relevant:
            return 50.0, 0, [_reason("INCOME_NO_OBSERVATIONS", domain, "No classifiable income inflows were observed.", [])], relevant
        months = {f"{event.date.year:04d}-{event.date.month:02d}" for event in relevant}
        month_ratio = min(1.0, len(months) / max(1, period_months))
        amounts = [event.amount for event in relevant]
        median = _median(amounts)
        deviation = sum(abs(value - median) for value in amounts) / max(1, len(amounts))
        consistency = _clamp(1.0 - deviation / max(1.0, median))
        observed = _clamp(40 + month_ratio * 40 + consistency * 20)
        message = f"{len(months)} observed income month(s); recurring inflows are {consistency:.0%} consistent."
        return observed, _reliability(relevant, period_months), [_reason("INCOME_CONTINUITY", domain, message, relevant, f"{len(months)} month(s)")], relevant

    if domain == "capacity":
        inflows = [event for event in all_events if event.direction == "credit" and event.event_type in INCOME_TYPES]
        obligations = [event for event in all_events if event.direction == "debit" and event.event_type in COMMITMENT_TYPES]
        relevant = inflows + obligations
        if not relevant:
            return 50.0, 0, [_reason("CAPACITY_NO_OBSERVATIONS", domain, "No income and obligation events were available for capacity analysis.", [])], relevant
        if not inflows:
            message = (
                f"{len(obligations)} commitment outflow(s) were observed, but no inflows could be classified as income; "
                "capacity remained neutral."
            )
            return 50.0, _reliability(relevant, period_months), [
                _reason("CAPACITY_INCOME_UNCLASSIFIED", domain, message, relevant, "income unavailable")
            ], relevant
        income_total = sum(event.amount for event in inflows)
        obligation_total = sum(event.amount for event in obligations)
        ratio = obligation_total / income_total
        observed = _clamp(100 - ratio * 100)
        message = f"Observed commitment outflows were {ratio:.0%} of classified income inflows."
        return observed, _reliability(relevant, period_months), [_reason("CAPACITY_OBLIGATION_RATIO", domain, message, relevant, f"{ratio:.0%} obligations/income")], relevant

    if domain == "liquidity":
        relevant = [event for event in all_events if event.balance_after is not None]
        if not relevant:
            relevant = list(all_events)
        if not relevant:
            return 50.0, 0, [_reason("LIQUIDITY_NO_OBSERVATIONS", domain, "No cash-flow or balance observations were available.", [])], relevant
        balances = [event.balance_after for event in relevant if event.balance_after is not None]
        monthly_credit = _monthly_totals(all_events, "credit")
        monthly_debit = _monthly_totals(all_events, "debit")
        months = set(monthly_credit) | set(monthly_debit)
        positive_months = sum(1 for month in months if monthly_credit.get(month, 0) >= monthly_debit.get(month, 0))
        positive_ratio = positive_months / max(1, len(months))
        balance_signal = 1.0 if balances and min(balances) >= 0 else 0.0
        observed = _clamp(35 + positive_ratio * 45 + balance_signal * 20)
        message = f"{positive_months} of {max(1, len(months))} observed month(s) had non-negative net flow."
        return observed, _reliability(relevant, period_months), [_reason("LIQUIDITY_NET_FLOW", domain, message, relevant, f"{positive_ratio:.0%} positive months")], relevant

    if domain == "shock":
        relevant = [event for event in all_events if event.event_type in PROTECTION_TYPES or event.balance_after is not None]
        if not relevant:
            return 50.0, 0, [_reason("SHOCK_NO_OBSERVATIONS", domain, "No reserve, protection or balance observations were available.", [])], relevant
        reserve_count = sum(1 for event in relevant if event.event_type in {"savings", "deposit"})
        protection_count = sum(1 for event in relevant if event.event_type == "insurance")
        observed = _clamp(40 + min(1.0, reserve_count / 3) * 35 + min(1.0, protection_count / 2) * 25)
        message = f"Observed {reserve_count} reserve/deposit event(s) and {protection_count} protection payment(s)."
        return observed, _reliability(relevant, period_months), [_reason("SHOCK_BUFFER", domain, message, relevant, f"{reserve_count} reserves")], relevant

    if domain == "momentum":
        relevant = [event for event in all_events if event.direction == "credit" and event.event_type in INCOME_TYPES]
        if not relevant:
            return 50.0, 0, [_reason("MOMENTUM_NO_OBSERVATIONS", domain, "No income trend observations were available.", [])], relevant
        totals = _monthly_totals(relevant, "credit")
        ordered = sorted(totals.items())
        if len(ordered) < 2:
            observed = 55.0
            trend = "one observed month"
        else:
            first = sum(value for _, value in ordered[: max(1, len(ordered) // 2)]) / max(1, len(ordered[: max(1, len(ordered) // 2)]))
            last = sum(value for _, value in ordered[len(ordered) // 2 :]) / max(1, len(ordered[len(ordered) // 2 :]))
            change = (last - first) / max(1.0, first)
            observed = _clamp(50 + change * 100)
            trend = f"{change:+.0%} from early to late observed income"
        return observed, _reliability(relevant, period_months), [_reason("MOMENTUM_INCOME_TREND", domain, f"Income trend: {trend}.", relevant, trend)], relevant

    relevant = [event for event in all_events if event.event_type in CROSS_BORDER_TYPES]
    if not relevant:
        return 50.0, 0, [_reason("CROSS_BORDER_NO_OBSERVATIONS", domain, "No cross-border transfer events were observed.", [])], relevant
    currencies = {event.currency for event in relevant}
    months = {f"{event.date.year:04d}-{event.date.month:02d}" for event in relevant}
    consistency = min(1.0, len(months) / max(1, period_months))
    diversity = min(1.0, len(currencies) / 2)
    observed = _clamp(45 + consistency * 40 + diversity * 15)
    message = f"{len(relevant)} cross-border event(s) across {len(months)} month(s) and {len(currencies)} currency/currencies."
    return observed, _reliability(relevant, period_months), [_reason("CROSS_BORDER_PATTERN", domain, message, relevant, f"{len(relevant)} transfer(s)")], relevant


def calculate_score(
    applicant_id: str,
    product: ProductType,
    assertions: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
) -> ScoreResponse:
    sources = {str(row["id"]): row for row in source_rows}
    events = unique_events(assertions, sources)
    source_count = len(sources)
    assertion_count = len(assertions)
    corroborated_count = max(0, assertion_count - len(events))
    if events:
        first_date = min(event.date for event in events)
        last_date = max(event.date for event in events)
        period_months = _months_between(first_date, last_date)
    else:
        period_months = 0

    if events:
        field_complete = sum(1 for event in events if event.currency and event.direction and event.event_type) / len(events)
        history = min(1.0, period_months / 6)
        volume = min(1.0, len(events) / 24)
        diversity = min(1.0, source_count / 5)
        corroboration = min(1.0, corroborated_count / max(1.0, len(events) * 0.25))
        reliability = round(100 * (0.30 * history + 0.26 * volume + 0.22 * diversity + 0.17 * field_complete + 0.05 * corroboration))
    else:
        reliability = 0

    domain_results: list[DomainResult] = []
    all_reasons: list[ReasonCode] = []
    weights = PRODUCT_WEIGHTS[product]
    for key, weight in weights.items():
        observed, domain_reliability, reasons, relevant = _domain_metrics(key, events, period_months)
        adjusted = 50 + (observed - 50) * (domain_reliability / 100)
        contribution = adjusted * weight / 100
        domain_results.append(
            DomainResult(
                key=key,
                label=DOMAIN_LABELS[key],
                observed=round(observed),
                reliability=domain_reliability,
                adjusted=round(adjusted, 2),
                weight=weight,
                contribution=round(contribution, 2),
                evidence_count=len(relevant),
                reason_codes=reasons,
            )
        )
        all_reasons.extend(reasons)

    weighted_score = sum(domain.contribution for domain in domain_results)
    score = round(_clamp(weighted_score))
    uncertainty = max(3, round((100 - reliability) * 0.18))
    score_range = ScoreRange(p10=max(0, score - uncertainty), p90=min(100, score + uncertainty))
    now = datetime.now(timezone.utc)
    return ScoreResponse(
        applicant_id=applicant_id,
        product=product,
        score=score,
        band=_band(score),
        reliability=reliability,
        reliability_band=_band(reliability),
        assertion_count=assertion_count,
        unique_event_count=len(events),
        corroborated_count=corroborated_count,
        score_range=score_range,
        domains=domain_results,
        reason_codes=all_reasons,
        generated_at=now,
    )


def event_response(event: UniqueEvent, sources: dict[str, dict[str, Any]]) -> EconomicEventResponse:
    construct = "policy-only"
    if event.event_type in INCOME_TYPES:
        construct = "income-continuity"
    elif event.event_type in COMMITMENT_TYPES:
        construct = "commitment-performance"
    elif event.event_type in CROSS_BORDER_TYPES:
        construct = "cross-border-robustness"
    elif event.event_type in {"savings", "deposit"}:
        construct = "liquidity"
    elif event.event_type == "insurance":
        construct = "shock-resilience"
    status = "corroborated" if len(event.assertion_ids) > 1 else "scored"
    return EconomicEventResponse(
        id=event.id,
        date=event.date,
        event_type=event.event_type,
        amount=event.amount,
        currency=event.currency,
        direction=event.direction,
        source_ids=event.source_ids,
        source_types=[EvidenceType(value=source_type) if source_type in {item.value for item in EvidenceType} else EvidenceType.OTHER for source_type in event.source_types],
        financial_construct=construct,
        status=status,
        reference=event.reference,
        description=event.description,
    )

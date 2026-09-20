"""Parsers for consented statement uploads.

The upload contract deliberately uses a small, human-editable transaction table.  A
statement is converted to :class:`StatementRecord` rows before it reaches the
database, so every supported file format follows the same scoring and provenance
path.  In particular, no score/risk column from an uploaded workbook is trusted.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

from .schemas import Direction, EvidenceType, StatementRecord, StructuredStatementIngest
from .scoring import normalize_event_type


class StatementParseError(ValueError):
    """A user-correctable upload error with an HTTP-friendly message."""


_COMPACT_RE = re.compile(r"[^a-z0-9]+")
_DATE_RE = re.compile(
    r"\b(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|"
    r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4})\b"
)
_NUMBER_RE = re.compile(r"(?<![A-Za-z])\(?[+-]?\s*(?:[$€£₹]|[A-Z]{3}\s*)?\d[\d,]*(?:\.\d+)?\)?(?:\s*(?:CR|DR))?(?![A-Za-z])", re.IGNORECASE)


# These aliases intentionally describe the transaction data rather than a model
# output.  ``score``, ``risk`` and similar columns are ignored even if a user
# includes them in an otherwise valid workbook.
_ALIASES: dict[str, tuple[str, ...]] = {
    "date": (
        "date",
        "occurred_on",
        "occurred",
        "transaction_date",
        "posted_date",
        "value_date",
        "txn_date",
    ),
    "amount": ("amount", "value", "transaction_amount", "net_amount", "total"),
    "credit_amount": ("credit", "credit_amount", "inflow", "income", "deposit_amount"),
    "debit_amount": ("debit", "debit_amount", "outflow", "expense", "withdrawal_amount"),
    "direction": (
        "direction",
        "debit_credit",
        "credit_debit",
        "dr_cr",
        "cr_dr",
        "in_out",
        "flow",
        "type",
    ),
    "event_type": (
        "event_type",
        "event",
        "category",
        "transaction_type",
        "financial_category",
        "construct",
        "purpose",
    ),
    "description": ("description", "narration", "memo", "details", "merchant", "notes"),
    "currency": ("currency", "ccy"),
    "balance_after": ("balance_after", "balance", "running_balance", "closing_balance"),
    "reference": ("reference", "reference_id", "transaction_id", "txn_id", "id"),
    "due_on": ("due_on", "due_date", "due", "scheduled_date"),
    "paid_on": ("paid_on", "paid_date", "paid", "settled_on", "settlement_date"),
    "status": ("status", "payment_status", "payment_state", "outcome"),
    "days_past_due": ("days_past_due", "days_late", "late_days", "days_overdue", "dpd"),
}

_INCOME_WORDS = re.compile(r"\b(?:salary|payroll|wage|income|bonus|stipend|scholarship|pension|"
                           r"gig|platform|freelance|contract|revenue|sale|sales|merchant)\b", re.I)
_RENT_WORDS = re.compile(r"\b(?:rent|lease|landlord)\b", re.I)
_UTILITY_WORDS = re.compile(r"\b(?:utility|electric|electricity|gas|water|internet|mobile|phone)\b", re.I)
_INSURANCE_WORDS = re.compile(r"\b(?:insurance|premium|policy)\b", re.I)
_REMITTANCE_WORDS = re.compile(r"\b(?:remittance|family transfer|international transfer|cross.border|"
                                r"overseas transfer|swift)\b", re.I)
_CARD_WORDS = re.compile(r"\b(?:credit card|card payment|card repayment)\b", re.I)
_LOAN_WORDS = re.compile(r"\b(?:loan|emi|installment|instalment|repayment|finance payment)\b", re.I)
_SAVINGS_WORDS = re.compile(r"\b(?:saving|savings|reserve|fixed deposit|term deposit|deposit)\b", re.I)
_BILL_WORDS = re.compile(r"\b(?:bill|grocery|subscription|obligation|payment|fee|penalty|fine|charge|tuition|debt)\b", re.I)
_COMMITMENT_EVENT_TYPES = {"rent", "utility", "bill", "loan_payment", "credit_card_payment", "asset_repayment", "insurance"}

_POSITIVE_STATUS = {"paid", "complete", "completed", "settled", "on time", "on-time", "current", "success", "successful"}
_LATE_STATUS = {"late", "overdue", "past due", "delayed", "missed", "unpaid", "default", "failed", "returned", "reversed", "bounce", "bounced"}
_DIRECTION_CREDIT = {"credit", "cr", "in", "inflow", "income", "deposit", "positive", "+"}
_DIRECTION_DEBIT = {"debit", "dr", "out", "outflow", "expense", "withdrawal", "negative", "-"}


def _compact(value: Any) -> str:
    return _COMPACT_RE.sub("", str(value or "").strip().lower())


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _columns(headers: Sequence[Any]) -> dict[str, int]:
    aliases = {_compact(header): index for index, header in enumerate(headers) if _text(header)}
    result: dict[str, int] = {}
    for canonical, names in _ALIASES.items():
        for name in names:
            index = aliases.get(_compact(name))
            if index is not None:
                result[canonical] = index
                break
    return result


def _date_value(value: Any, *, excel_book: Any = None) -> date:
    if value is None or _text(value) == "":
        raise ValueError("date is empty")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and excel_book is not None:
        try:
            import xlrd  # type: ignore[import-not-found]

            return xlrd.xldate_as_datetime(float(value), excel_book.datemode).date()
        except Exception:
            # A numeric date without an XLS workbook is not safe to guess.
            pass
    raw = _text(value).replace(".", "-")
    for format_string in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%b-%Y",
        "%d %b %Y",
        "%b %d, %Y",
        "%b %d %Y",
    ):
        try:
            return datetime.strptime(raw, format_string).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw[:19]).date()
    except ValueError as exc:
        raise ValueError(f"invalid date {raw!r}") from exc


def _number(raw: Any) -> tuple[float, Direction]:
    """Return an absolute amount and the direction encoded by its sign/tokens."""

    text = _text(raw)
    if not text:
        raise ValueError("amount is empty")
    upper = text.upper().replace(",", "")
    direction = Direction.DEBIT if (upper.startswith("-") or " DR" in f" {upper}" or upper.endswith("DR") or "(" in upper) else Direction.CREDIT
    match = re.search(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", upper)
    if match is None:
        raise ValueError(f"invalid amount {text!r}")
    value = abs(float(match.group(0)))
    if value <= 0:
        raise ValueError("amount must be greater than zero")
    return value, direction


def _signed_number(raw: Any) -> float:
    """Parse a balance while retaining its sign (unlike transaction amounts)."""

    text = _text(raw)
    if not text:
        raise ValueError("balance is empty")
    cleaned = text.upper().replace(",", "")
    match = re.search(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", cleaned)
    if match is None:
        raise ValueError(f"invalid balance {text!r}")
    value = float(match.group(0))
    if "(" in cleaned and value > 0:
        value = -value
    return value


def _direction(raw: Any, fallback: Direction) -> Direction:
    key = _text(raw).lower().replace("_", " ").strip()
    if key in _DIRECTION_CREDIT or key.startswith("credit") or key.startswith("cr") or key.startswith("in"):
        return Direction.CREDIT
    if key in _DIRECTION_DEBIT or key.startswith("debit") or key.startswith("dr") or key.startswith("out"):
        return Direction.DEBIT
    return fallback


def _event_type(category: Any, description: str, direction: Direction) -> str:
    """Classify evidence conservatively; never use an uploaded score/risk field."""

    candidate = _text(category)
    candidate_compact = _compact(candidate)
    # A finite set of canonical event aliases is safe to accept.  Broad labels
    # are only hints and are resolved from the description/direction below.
    if candidate_compact and candidate_compact not in {
        "income", "expense", "outflow", "inflow", "payment", "transaction", "other", "good", "bad", "positive", "negative", "score", "risk"
    }:
        normalized = normalize_event_type(candidate)
        if normalized not in {"other", "income", "expense", "payment", "transaction"}:
            return normalized

    text = f"{candidate} {description}".strip()
    if _CARD_WORDS.search(text):
        return "credit_card_payment"
    if _RENT_WORDS.search(text):
        return "rent"
    if _UTILITY_WORDS.search(text):
        return "utility"
    if _INSURANCE_WORDS.search(text):
        return "insurance"
    if _REMITTANCE_WORDS.search(text):
        return "remittance"
    if _LOAN_WORDS.search(text):
        return "loan_payment"
    if _SAVINGS_WORDS.search(text):
        return "savings" if "saving" in text.lower() or "reserve" in text.lower() else "deposit"
    if _INCOME_WORDS.search(text):
        lower = text.lower()
        if any(token in lower for token in ("gig", "platform", "freelance", "contract")):
            return "gig_income"
        if any(token in lower for token in ("sale", "sales", "merchant", "revenue")):
            return "merchant_sales"
        if "stipend" in lower or "scholarship" in lower:
            return "stipend"
        return "salary"
    if direction is Direction.DEBIT and _BILL_WORDS.search(text):
        return "bill"
    return "other"


def _status_dates(
    *,
    occurred_on: date,
    due_on: date | None,
    paid_on: date | None,
    status: str,
    days_past_due: int | None,
) -> tuple[date | None, date | None]:
    """Turn editable status/DPD cells into the canonical due/paid dates.

    The scorecard only scores timeliness when both dates are known.  For a row
    explicitly marked late/missed, deriving a paid date after the due date makes
    the negative evidence visible without trusting a precomputed score.
    """

    normalized = re.sub(r"\s+", " ", status.lower().replace("_", " ").strip())
    late_days = max(1, days_past_due or 1)
    if due_on is None and (normalized in _POSITIVE_STATUS or normalized in _LATE_STATUS or days_past_due is not None):
        due_on = occurred_on
    if normalized in _POSITIVE_STATUS and paid_on is None and due_on is not None:
        paid_on = due_on
    elif (normalized in _LATE_STATUS or days_past_due is not None) and due_on is not None and paid_on is None:
        paid_on = due_on + timedelta(days=late_days)
    elif paid_on is not None and due_on is None and days_past_due is not None:
        due_on = paid_on - timedelta(days=max(1, days_past_due))
    return due_on, paid_on


def _int_value(value: Any) -> int | None:
    raw = _text(value)
    if not raw:
        return None
    match = re.search(r"-?\d+", raw)
    if match is None:
        raise ValueError(f"invalid days-past-due value {raw!r}")
    return int(match.group(0))


def _statement_from_rows(
    headers: Sequence[Any],
    rows: Iterable[Sequence[Any]],
    *,
    source_type: EvidenceType,
    provider: str,
    currency: str,
    excel_book: Any = None,
    row_offset: int = 2,
    format_name: str = "statement",
) -> StructuredStatementIngest:
    column_map = _columns(headers)
    if "date" not in column_map:
        raise StatementParseError(f"{format_name} is missing a date column (for example date or occurred_on)")
    if not ({"amount", "credit_amount", "debit_amount"} & column_map.keys()):
        raise StatementParseError(f"{format_name} is missing an amount column (amount, credit, or debit)")

    def get(row: Sequence[Any], key: str) -> Any:
        index = column_map.get(key)
        return row[index] if index is not None and index < len(row) else None

    records: list[StatementRecord] = []
    errors: list[str] = []
    for row_number, row in enumerate(rows, start=row_offset):
        if not any(_text(value) for value in row):
            continue
        try:
            occurred_on = _date_value(get(row, "date"), excel_book=excel_book)
            amount_raw = get(row, "amount")
            inferred: Direction
            if amount_raw is not None and _text(amount_raw):
                amount, inferred = _number(amount_raw)
            else:
                credit_raw = get(row, "credit_amount")
                debit_raw = get(row, "debit_amount")
                credit = _text(credit_raw)
                debit = _text(debit_raw)
                if credit and debit:
                    # A row with both columns is usually a malformed edit.  A
                    # zero is harmless, so only reject two non-zero values.
                    credit_value, _ = _number(credit)
                    debit_value, _ = _number(debit)
                    if credit_value > 0 and debit_value > 0:
                        raise ValueError("both credit and debit are populated")
                    amount, inferred = (credit_value, Direction.CREDIT) if credit_value > 0 else (debit_value, Direction.DEBIT)
                elif credit:
                    amount, _ = _number(credit)
                    inferred = Direction.CREDIT
                elif debit:
                    amount, _ = _number(debit)
                    inferred = Direction.DEBIT
                else:
                    raise ValueError("amount is empty")
            direction = _direction(get(row, "direction"), inferred)
            description = _text(get(row, "description"))
            event_type = _event_type(get(row, "event_type"), description, direction)
            record_currency = _text(get(row, "currency")).upper() or currency
            due_raw = get(row, "due_on")
            paid_raw = get(row, "paid_on")
            due_on = _date_value(due_raw, excel_book=excel_book) if _text(due_raw) else None
            paid_on = _date_value(paid_raw, excel_book=excel_book) if _text(paid_raw) else None
            days_past_due = _int_value(get(row, "days_past_due"))
            status = _text(get(row, "status"))
            if not status:
                lowered_description = description.lower()
                if any(token in lowered_description for token in ("missed", "unpaid", "overdue", "past due", "default", "failed", "late")):
                    status = "late"
            if days_past_due is None:
                days_match = re.search(r"(\d+)\s*(?:day|days)\s*(?:past due|late|overdue)", description, re.I)
                if days_match:
                    days_past_due = int(days_match.group(1))
            if event_type in _COMMITMENT_EVENT_TYPES or due_on is not None or paid_on is not None or days_past_due is not None:
                due_on, paid_on = _status_dates(
                    occurred_on=occurred_on,
                    due_on=due_on,
                    paid_on=paid_on,
                    status=status,
                    days_past_due=days_past_due,
                )
            balance_raw = get(row, "balance_after")
            balance_after = _signed_number(balance_raw) if _text(balance_raw) else None
            # Keep the source status/DPD for auditability without letting a
            # precomputed score or label participate in scoring.
            metadata = {"parser": format_name}
            if status:
                metadata["status"] = status
            if days_past_due is not None:
                metadata["days_past_due"] = days_past_due
            records.append(
                StatementRecord(
                    occurred_on=occurred_on,
                    event_type=event_type,
                    amount=amount,
                    currency=record_currency,
                    direction=direction,
                    reference=_text(get(row, "reference")) or None,
                    due_on=due_on,
                    paid_on=paid_on,
                    description=description or None,
                    balance_after=balance_after,
                    metadata=metadata,
                )
            )
        except (ValueError, TypeError, OverflowError) as exc:
            errors.append(f"row {row_number}: {exc}")
            if len(errors) >= 10:
                break
    if errors:
        raise StatementParseError(f"Invalid {format_name} rows: " + "; ".join(errors))
    if not records:
        raise StatementParseError(f"{format_name} contains no transaction rows")
    return StructuredStatementIngest(
        source_type=source_type,
        provider=provider,
        currency=currency.upper(),
        period_start=min(record.occurred_on for record in records),
        period_end=max(record.occurred_on for record in records),
        records=records,
        consent=True,
    )


def parse_csv(
    content: bytes,
    *,
    source_type: EvidenceType,
    provider: str,
    currency: str,
) -> StructuredStatementIngest:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise StatementParseError("CSV must be UTF-8 encoded") from exc
    reader = csv.reader(io.StringIO(text))
    try:
        headers = next(reader)
    except StopIteration as exc:
        raise StatementParseError("CSV must include a header row") from exc
    if not any(_text(header) for header in headers):
        raise StatementParseError("CSV must include a header row")
    return _statement_from_rows(
        headers,
        reader,
        source_type=source_type,
        provider=provider,
        currency=currency,
        format_name="CSV",
    )


def parse_xlsx(
    content: bytes,
    *,
    source_type: EvidenceType,
    provider: str,
    currency: str,
) -> StructuredStatementIngest:
    try:
        import openpyxl  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - packaging/runtime guard
        raise StatementParseError("XLSX support is unavailable on this server; install the openpyxl parser") from exc
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        worksheet = next((sheet for sheet in workbook.worksheets if sheet.max_row and sheet.max_column), None)
        if worksheet is None:
            raise StatementParseError("XLSX contains no readable worksheet")
        values = worksheet.iter_rows(values_only=True)
        headers = next(values, None)
        if headers is None:
            raise StatementParseError("XLSX must include a header row")
        result = _statement_from_rows(
            headers,
            values,
            source_type=source_type,
            provider=provider,
            currency=currency,
            format_name="XLSX",
        )
        workbook.close()
        return result
    except StatementParseError:
        raise
    except Exception as exc:
        raise StatementParseError(f"XLSX could not be read: {exc}") from exc


def parse_xls(
    content: bytes,
    *,
    source_type: EvidenceType,
    provider: str,
    currency: str,
) -> StructuredStatementIngest:
    try:
        import xlrd  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - packaging/runtime guard
        raise StatementParseError("XLS support is unavailable on this server; install the xlrd parser") from exc
    try:
        workbook = xlrd.open_workbook(file_contents=content, on_demand=True)
        sheet = next((workbook.sheet_by_index(index) for index in range(workbook.nsheets) if workbook.sheet_by_index(index).nrows), None)
        if sheet is None:
            raise StatementParseError("XLS contains no readable worksheet")
        headers = sheet.row_values(0)
        rows: list[list[Any]] = []
        date_columns = {_compact(name) for name in _ALIASES["date"]}
        date_indexes = {index for index, value in enumerate(headers) if _compact(value) in date_columns}
        for row_index in range(1, sheet.nrows):
            values = sheet.row_values(row_index)
            for index in date_indexes:
                if index < len(values) and sheet.cell_type(row_index, index) == xlrd.XL_CELL_DATE:
                    values[index] = xlrd.xldate_as_datetime(values[index], workbook.datemode).date()
            rows.append(values)
        result = _statement_from_rows(
            headers,
            rows,
            source_type=source_type,
            provider=provider,
            currency=currency,
            excel_book=workbook,
            format_name="XLS",
        )
        workbook.release_resources()
        return result
    except StatementParseError:
        raise
    except Exception as exc:
        raise StatementParseError(f"XLS could not be read: {exc}") from exc


def _pdf_table_rows(text: str) -> tuple[list[str], list[list[str]]] | None:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    # Prefer a visible delimiter/header table.  PDF text extraction generally
    # preserves pipes or tabs from statement tables.
    for index, line in enumerate(lines):
        pieces = [piece.strip() for piece in re.split(r"\s*\|\s*|\t+", line) if piece.strip()]
        if len(pieces) >= 2 and _columns(pieces).get("date") is not None and ({"amount", "credit_amount", "debit_amount"} & _columns(pieces).keys()):
            rows: list[list[str]] = []
            for candidate in lines[index + 1 :]:
                values = [piece.strip() for piece in re.split(r"\s*\|\s*|\t+", candidate)]
                if len(values) < len(pieces):
                    continue
                if _DATE_RE.search(values[0]):
                    rows.append(values[: len(pieces)])
            if rows:
                return pieces, rows
    return None


def _pdf_line_rows(text: str) -> tuple[list[str], list[list[str]]]:
    """Parse common bank PDF text where each transaction is one whitespace line."""

    headers = ["date", "description", "amount", "direction", "balance_after"]
    rows: list[list[str]] = []
    for line in (re.sub(r"\s+", " ", item).strip() for item in text.splitlines()):
        if not line or not _DATE_RE.search(line):
            continue
        date_match = _DATE_RE.search(line)
        assert date_match is not None
        raw_date = date_match.group(0)
        remainder = (line[: date_match.start()] + " " + line[date_match.end() :]).strip()
        numbers = list(_NUMBER_RE.finditer(remainder))
        if not numbers:
            continue
        amount_match = numbers[0]
        amount_token = amount_match.group(0)
        before = remainder[: amount_match.start()].strip()
        after = remainder[amount_match.end() :].strip()
        # CR/DR may be adjacent to the amount or appear as a word after it.
        direction = ""
        direction_match = re.search(r"\b(?:CR|DR|CREDIT|DEBIT)\b", after, re.I)
        if direction_match:
            direction = direction_match.group(0)
            after_without_direction = (after[: direction_match.start()] + " " + after[direction_match.end() :]).strip()
        else:
            after_without_direction = after
        # A signed/parenthesized amount already carries direction.  Otherwise
        # an explicit CR/DR token or description semantics determine it.
        balance_token = ""
        trailing_numbers = list(_NUMBER_RE.finditer(after_without_direction))
        if trailing_numbers:
            balance_token = trailing_numbers[-1].group(0)
            after_without_direction = (after_without_direction[: trailing_numbers[-1].start()] + " " + after_without_direction[trailing_numbers[-1].end() :]).strip()
        description = before or after_without_direction
        rows.append([raw_date, description, amount_token, direction, balance_token])
    return headers, rows


def parse_pdf(
    content: bytes,
    *,
    source_type: EvidenceType,
    provider: str,
    currency: str,
) -> StructuredStatementIngest:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - packaging/runtime guard
        raise StatementParseError("PDF support is unavailable on this server; install the pypdf parser") from exc
    try:
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise StatementParseError(f"PDF could not be read: {exc}") from exc
    if not text.strip():
        raise StatementParseError("PDF has no readable text; upload a text-based statement table rather than a scanned image")
    table = _pdf_table_rows(text)
    if table is None:
        table = _pdf_line_rows(text)
    headers, rows = table
    if not rows:
        raise StatementParseError("PDF did not contain a readable transaction table with date and amount columns")
    try:
        return _statement_from_rows(
            headers,
            rows,
            source_type=source_type,
            provider=provider,
            currency=currency,
            format_name="PDF",
        )
    except StatementParseError as exc:
        raise StatementParseError(
            f"PDF did not contain a readable transaction table with date and amount columns: {exc}"
        ) from exc


def parse_statement_file(
    content: bytes,
    *,
    filename: str,
    source_type: EvidenceType,
    provider: str,
    currency: str,
) -> StructuredStatementIngest:
    suffix = Path(filename or "statement.csv").suffix.lower()
    if suffix == ".csv":
        return parse_csv(content, source_type=source_type, provider=provider, currency=currency)
    if suffix == ".xlsx":
        return parse_xlsx(content, source_type=source_type, provider=provider, currency=currency)
    if suffix == ".xls":
        return parse_xls(content, source_type=source_type, provider=provider, currency=currency)
    if suffix == ".pdf":
        return parse_pdf(content, source_type=source_type, provider=provider, currency=currency)
    raise StatementParseError("Unsupported statement format. Upload a .csv, .xlsx, .xls, or text-based .pdf file.")

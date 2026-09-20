from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS applicants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    corridor TEXT NOT NULL,
    product TEXT NOT NULL,
    requested_amount REAL,
    currency TEXT NOT NULL DEFAULT 'INR',
    employment TEXT,
    residency TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_sources (
    id TEXT PRIMARY KEY,
    applicant_id TEXT NOT NULL REFERENCES applicants(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    currency TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    assertion_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_assertions (
    id TEXT PRIMARY KEY,
    applicant_id TEXT NOT NULL REFERENCES applicants(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES evidence_sources(id) ON DELETE CASCADE,
    occurred_on TEXT NOT NULL,
    event_type TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('credit', 'debit')),
    reference TEXT,
    due_on TEXT,
    paid_on TEXT,
    description TEXT,
    balance_after REAL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    fingerprint TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_assertions_applicant_date
    ON evidence_assertions(applicant_id, occurred_on);
CREATE INDEX IF NOT EXISTS idx_assertions_fingerprint
    ON evidence_assertions(applicant_id, fingerprint);

CREATE TABLE IF NOT EXISTS statement_uploads (
    id TEXT PRIMARY KEY,
    applicant_id TEXT NOT NULL REFERENCES applicants(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES evidence_sources(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transitions (
    applicant_id TEXT PRIMARY KEY REFERENCES applicants(id) ON DELETE CASCADE,
    event TEXT,
    country_from TEXT,
    country_to TEXT,
    facts_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
"""


class Database:
    """Small SQLite repository with one short-lived connection per operation."""

    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:" and not path.startswith("file:"):
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._keeper: sqlite3.Connection | None = None
        if path == ":memory:":
            # Keep an in-memory database alive across request connections when used by
            # tests or an embedding application.
            self._keeper = sqlite3.connect(":memory:", check_same_thread=False)
            self._keeper.row_factory = sqlite3.Row
            self._configure(self._keeper)

    @staticmethod
    def _configure(connection: sqlite3.Connection) -> None:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        if self._keeper is not None:
            connection = self._keeper
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            return

        connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        self._configure(connection)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialise(self) -> None:
        with self.connection() as connection:
            connection.executescript(SCHEMA)

    @staticmethod
    def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    @staticmethod
    def rows_dict(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        return [dict(row) for row in rows]

    @staticmethod
    def json_dumps(value: Any) -> str:
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def json_loads(value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path


_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _dotenv_value(raw: str) -> str:
    """Parse one simple dotenv value without evaluating arbitrary text."""

    value = raw.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        try:
            parsed = shlex.split(value, comments=False, posix=True)
            return parsed[0] if parsed else ""
        except ValueError:
            return value[1:].strip(value[0])
    # Match the common dotenv convention for an unquoted inline comment while
    # preserving values that legitimately contain a # without a preceding space.
    return value.split(" #", 1)[0].rstrip()


def _read_dotenv(path: Path) -> dict[str, str]:
    """Read a local dotenv file, returning only valid environment assignments."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return {}
    parsed: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, raw = stripped.partition("=")
        key = key.strip()
        if not separator or not _ENV_KEY.fullmatch(key):
            continue
        parsed[key] = _dotenv_value(raw)
    return parsed


def load_local_env(project_root: Path | None = None) -> tuple[Path, ...]:
    """Load ignored project-local dotenv files without overriding real env vars.

    ``backend/.env`` takes precedence over the repository-root ``.env`` when both
    exist. Explicit shell/CI variables always win. Values are never printed,
    logged or returned; only the loaded file paths are returned for diagnostics.
    """

    root = project_root or Path(__file__).resolve().parents[2]
    candidates = (root / ".env", root / "backend" / ".env")
    loaded: list[Path] = []
    # Read backend first so it wins over the root file while setdefault preserves
    # values already supplied by the process environment.
    for path in reversed(candidates):
        if not path.is_file():
            continue
        for key, value in _read_dotenv(path).items():
            os.environ.setdefault(key, value)
        loaded.append(path)
    return tuple(loaded)


@dataclass(frozen=True)
class Settings:
    """Runtime settings read from environment variables.

    The service deliberately has no credentials or provider tokens. Integrations can
    be added later behind the same typed evidence-ingestion contract.
    """

    db_path: str = "./data/credit_passport.db"
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    max_upload_bytes: int = 10 * 1024 * 1024
    model_metrics_path: str = "../model_pipeline/artifacts/icp_metrics.json"
    # The challenger artifact is deliberately configured separately from the
    # transparent scorecard metrics.  There is no runtime fallback: when the
    # configured file is missing or invalid, the challenger endpoint fails
    # explicitly and the transparent scorecard remains the only score path.
    challenger_model_artifact_path: str = "../model_pipeline/artifacts/icp_challenger.joblib"

    @classmethod
    def from_env(cls) -> "Settings":
        load_local_env()
        raw_limit = os.getenv("CREDIT_PASSPORT_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))
        try:
            max_upload_bytes = max(1024, int(raw_limit))
        except ValueError:
            max_upload_bytes = 10 * 1024 * 1024

        db_path = os.getenv("CREDIT_PASSPORT_DB_PATH", "./data/credit_passport.db")
        origins = _csv(
            os.getenv(
                "CREDIT_PASSPORT_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            )
        )
        metrics_path = os.getenv(
            "CREDIT_PASSPORT_MODEL_METRICS_PATH",
            "../model_pipeline/artifacts/icp_metrics.json",
        )
        challenger_artifact_path = os.getenv(
            "CREDIT_PASSPORT_CHALLENGER_MODEL_ARTIFACT_PATH",
            "../model_pipeline/artifacts/icp_challenger.joblib",
        )
        return cls(
            db_path=db_path,
            cors_origins=origins,
            max_upload_bytes=max_upload_bytes,
            model_metrics_path=metrics_path,
            challenger_model_artifact_path=challenger_artifact_path,
        )

    def ensure_database_parent(self) -> None:
        if self.db_path == ":memory:" or self.db_path.startswith("file:"):
            return
        Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

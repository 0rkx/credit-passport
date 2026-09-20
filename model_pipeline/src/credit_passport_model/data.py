"""Download and load the two pinned public benchmark datasets.

There is intentionally no generated-data branch in this module. A missing,
changed, or unreadable source is an error that the caller must surface.
"""

from __future__ import annotations

import hashlib
import io
import json
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd


PIPELINE_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PIPELINE_ROOT / "data" / "raw"
ARTIFACT_DIR = PIPELINE_ROOT / "artifacts"


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    url: str
    sha256: str
    filename: str
    source_page: str
    license_or_access: str
    geography: str
    rows_expected: int


DATASETS = {
    "lendingclub": DatasetSpec(
        name="lendingclub",
        url="https://zenodo.org/api/records/11295916/files/LC_loans_granting_model_dataset.csv/content",
        # SHA-256 of the Zenodo file; the record also publishes md5:b019384d6bc65bf2a3e839362e4ff502.
        sha256="207d65b2712f775a91404496ab27c786ac0da6b0f977f849e6d5d8149e925acc",
        filename="lendingclub_loans.csv",
        source_page="https://zenodo.org/records/11295916",
        license_or_access="CC BY 4.0 (Zenodo record 10.5281/zenodo.11295916)",
        geography="United States; LendingClub loans issued 2007–2018",
        rows_expected=1_347_681,
    ),
    "uci_default": DatasetSpec(
        name="uci_default",
        url="https://archive.ics.uci.edu/static/public/350/default+of+credit+card+clients.zip",
        sha256="56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602",
        filename="default_of_credit_card_clients.zip",
        source_page="https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients",
        license_or_access="UCI repository lists CC BY 4.0",
        geography="Taiwan; credit-card clients observed in 2005",
        rows_expected=30_000,
    ),
    "heloc": DatasetSpec(
        name="heloc",
        url=(
            "https://raw.githubusercontent.com/ZhangXinyiCindy/"
            "FICO-Explainable-ML-Challenge-HELOC-Dataset/"
            "d4c6f7736b3b42ffb0da7c24e93411b76de0f848/HelocData.csv"
        ),
        sha256="6daaf54b11d695b9fe7eaede1b0321373877b170c11869a3dd12cbb09d9c7a53",
        filename="heloc.csv",
        source_page="https://community.fico.com/s/explainable-machine-learning-challenge",
        license_or_access=(
            "Public FICO challenge data via a pinned GitHub mirror; the mirror "
            "does not publish an explicit license"
        ),
        geography="Anonymised US homeowners applying for a HELOC",
        rows_expected=10_459,
    ),
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(spec: DatasetSpec, destination: Path, timeout: int = 120) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        spec.url,
        headers={"User-Agent": "credit-passport-model-pipeline/0.1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    digest = sha256_bytes(payload)
    if digest != spec.sha256:
        raise RuntimeError(
            f"Checksum mismatch for {spec.name}: expected {spec.sha256}, got {digest}. "
            "The source may have changed; refusing to train."
        )
    destination.write_bytes(payload)
    return destination


def download_dataset(name: str, force: bool = False) -> Path:
    """Download one dataset or verify an existing exact copy."""

    try:
        spec = DATASETS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown dataset {name!r}; choose {sorted(DATASETS)}") from exc
    destination = RAW_DIR / spec.filename
    if destination.exists() and not force:
        digest = sha256_file(destination)
        if digest != spec.sha256:
            raise RuntimeError(
                f"Existing {destination} has checksum {digest}, not {spec.sha256}. "
                "Delete it explicitly or rerun with --force; no fallback is used."
            )
        return destination
    return _download(spec, destination)


def download_all(force: bool = False) -> dict[str, Path]:
    return {name: download_dataset(name, force=force) for name in DATASETS}


def write_data_manifest(paths: dict[str, Path]) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    destination = ARTIFACT_DIR / "data_manifest.json"
    existing: dict[str, dict] = {}
    if destination.exists():
        try:
            existing = json.loads(destination.read_text(encoding="utf-8")).get("datasets", {})
        except (json.JSONDecodeError, OSError):
            existing = {}
    entries = dict(existing)
    entries.update(
        {
            name: {
                **asdict(DATASETS[name]),
                "local_path": str(path),
                "sha256_verified": sha256_file(path),
            }
            for name, path in paths.items()
        }
    )
    manifest = {
        "generated_by": "credit_passport_model_pipeline",
        "datasets": entries,
    }
    destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return destination


def _extract_uci_xls(zip_path: Path) -> Path:
    with zipfile.ZipFile(zip_path) as archive:
        members = [
            member
            for member in archive.namelist()
            if member.lower().endswith((".xls", ".xlsx"))
        ]
        if len(members) != 1:
            raise ValueError(f"Expected exactly one spreadsheet in {zip_path}, found {members}")
        extracted = RAW_DIR / members[0].split("/")[-1]
        extracted.write_bytes(archive.read(members[0]))
    return extracted


def load_heloc(path: Path | None = None) -> pd.DataFrame:
    path = path or RAW_DIR / DATASETS["heloc"].filename
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}; run scripts/download_data.py first")
    if sha256_file(path) != DATASETS["heloc"].sha256:
        raise RuntimeError(f"Refusing to load unverified HELOC file {path}")
    frame = pd.read_csv(path)
    expected = ["RiskFlag", *[f"x{i}" for i in range(1, 24)]]
    if frame.columns.tolist() != expected:
        raise ValueError(f"Unexpected HELOC columns: {frame.columns.tolist()}")
    if len(frame) != DATASETS["heloc"].rows_expected:
        raise ValueError(f"Unexpected HELOC row count: {len(frame)}")
    frame["RiskFlag"] = frame["RiskFlag"].map({"Good": 0, "Bad": 1})
    if frame["RiskFlag"].isna().any():
        raise ValueError("HELOC RiskFlag contains labels outside Good/Bad")
    return frame.astype({"RiskFlag": "int64"})


def load_uci_default(path: Path | None = None) -> pd.DataFrame:
    path = path or RAW_DIR / DATASETS["uci_default"].filename
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}; run scripts/download_data.py first")
    if sha256_file(path) != DATASETS["uci_default"].sha256:
        raise RuntimeError(f"Refusing to load unverified UCI file {path}")
    spreadsheet = _extract_uci_xls(path)
    frame = pd.read_excel(spreadsheet, header=1)
    expected_target = "default payment next month"
    if expected_target not in frame.columns or len(frame) != DATASETS["uci_default"].rows_expected:
        raise ValueError(
            f"Unexpected UCI schema: rows={len(frame)}, columns={frame.columns.tolist()}"
        )
    frame = frame.rename(columns={expected_target: "default_next_month"})
    if not frame["default_next_month"].isin([0, 1]).all():
        raise ValueError("UCI target is not binary 0/1")
    return frame


def load_all() -> tuple[pd.DataFrame, pd.DataFrame]:
    return load_heloc(), load_uci_default()


def load_lendingclub(path: Path | None = None) -> pd.DataFrame:
    """Load the Zenodo LendingClub granting-model file after checksum validation."""

    path = path or RAW_DIR / DATASETS["lendingclub"].filename
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}; run scripts/download_data.py first")
    spec = DATASETS["lendingclub"]
    if spec.sha256.startswith("REPLACE_") or sha256_file(path) != spec.sha256:
        raise RuntimeError(f"Refusing to load unverified LendingClub file {path}")
    frame = pd.read_csv(path, low_memory=False)
    expected = [
        "id",
        "issue_d",
        "revenue",
        "dti_n",
        "loan_amnt",
        "fico_n",
        "experience_c",
        "emp_length",
        "purpose",
        "home_ownership_n",
        "addr_state",
        "zip_code",
        "Default",
        "title",
        "desc",
    ]
    if frame.columns.tolist() != expected:
        raise ValueError(f"Unexpected LendingClub columns: {frame.columns.tolist()}")
    if len(frame) != spec.rows_expected:
        raise ValueError(f"Unexpected LendingClub row count: {len(frame)}")
    if not frame["Default"].isin([0, 1]).all():
        raise ValueError("LendingClub Default target is not binary 0/1")
    return frame

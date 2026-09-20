#!/usr/bin/env python3
"""Train explicitly-labelled secondary public benchmarks.

This script is separate from the primary LendingClub artifacts. It exists to
measure how a detailed anonymised credit-report benchmark performs when its
actual bureau-like field is available; it must not be represented as the
production Credit Passport model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit_passport_model.data import (  # noqa: E402
    ARTIFACT_DIR,
    download_dataset,
    load_heloc,
    write_data_manifest,
)
from train_models import train_heloc_regressor  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-download", action="store_true")
    args = parser.parse_args()
    try:
        path = download_dataset("heloc", force=args.force_download)
        write_data_manifest({"heloc": path})
        frame = load_heloc(path)
        model, metrics = train_heloc_regressor(frame)
        artifact_path = ARTIFACT_DIR / "secondary_heloc_external_risk_regressor.joblib"
        joblib.dump(model, artifact_path, compress=3)
        metrics["artifact"] = str(artifact_path)
        metrics["status"] = "secondary_research_benchmark"
        metrics_path = ARTIFACT_DIR / "secondary_heloc_metrics.json"
        metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(metrics, indent=2))
    except Exception as exc:  # noqa: BLE001 - CLI must expose source/training errors
        print(f"secondary benchmark failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Download and checksum the public data used by the model pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credit_passport_model.data import (  # noqa: E402
    DATASETS,
    download_all,
    download_dataset,
    write_data_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="redownload exact pinned bytes after an explicit checksum mismatch",
    )
    parser.add_argument(
        "--dataset",
        choices=sorted(DATASETS),
        action="append",
        help="download only the named dataset; repeat for multiple (default: lendingclub)",
    )
    args = parser.parse_args()
    try:
        names = args.dataset or ["lendingclub"]
        paths = {name: download_dataset(name, force=args.force) for name in names}
        manifest = write_data_manifest(paths)
    except Exception as exc:  # noqa: BLE001 - CLI must show a useful source error
        print(f"download failed: {exc}", file=sys.stderr)
        return 1
    for name, path in paths.items():
        print(f"{name}: {path}")
    print(f"manifest: {manifest}")
    print("verified sources: " + ", ".join(DATASETS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

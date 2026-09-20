#!/usr/bin/env python3
"""Add worksheet dimensions missing from some artifact-tool XLSX exports.

The workbook cells and styles are already authored by artifact-tool. This small
compatibility pass only adds the optional worksheet dimension metadata so
read-only openpyxl consumers can discover populated sheets.
"""

from __future__ import annotations

import re
import sys
import tempfile
import zipfile
from pathlib import Path


CELL_RE = re.compile(rb'<x:c\s+[^>]*\br="([A-Z]+)(\d+)"')
DIMENSION_RE = re.compile(rb"<x:dimension\b")


def column_number(column: bytes) -> int:
    value = 0
    for char in column:
        value = value * 26 + char - 64
    return value


def normalize(path: Path) -> None:
    temp_path: Path | None = None
    with zipfile.ZipFile(path, "r") as source, tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}.", suffix=".xlsx", dir=path.parent, delete=False
    ) as raw:
        temp_path = Path(raw.name)
        with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                payload = source.read(info.filename)
                if info.filename.startswith("xl/worksheets/sheet") and info.filename.endswith(".xml") and not DIMENSION_RE.search(payload):
                    cells = [(column_number(column), int(row)) for column, row in CELL_RE.findall(payload)]
                    if cells:
                        max_column, max_row = max(cells)
                        column = ""
                        number = max_column
                        while number:
                            number, remainder = divmod(number - 1, 26)
                            column = chr(65 + remainder) + column
                        marker = b">"
                        worksheet_start = payload.find(b"<x:worksheet")
                        marker_position = payload.find(marker, worksheet_start)
                        if worksheet_start >= 0 and marker_position >= 0:
                            dimension = f'<x:dimension ref="A1:{column}{max_row}" />'.encode("ascii")
                            payload = payload[: marker_position + 1] + dimension + payload[marker_position + 1 :]
                target.writestr(info, payload)
    assert temp_path is not None
    temp_path.replace(path)


def main() -> None:
    paths = [Path(item).expanduser().resolve() for item in sys.argv[1:]]
    if not paths:
        raise SystemExit("Pass one or more explicit .xlsx paths")
    for path in paths:
        if path.suffix.lower() != ".xlsx" or not path.is_file():
            raise SystemExit(f"Not an existing .xlsx file: {path}")
        normalize(path)
    print("Normalized", len(paths), "workbook(s)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Seed the fictional multi-source demo packs into a running Credit Passport API.

Usage from the repository root:

    python3 scripts/demo_seed.py

The command validates every CSV before making a request, creates one applicant
per selected case, uploads each source through the public multipart endpoint,
then writes a machine-readable score/evidence summary to
``demo/results/latest.json``. It never deletes or updates existing applicants.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo"
MANIFEST_PATH = DEMO_DIR / "manifest.json"
sys.path.insert(0, str(DEMO_DIR))
from validate_demo_inputs import validate  # noqa: E402


class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int | None, detail: str):
        self.method = method
        self.path = path
        self.status = status
        self.detail = detail
        suffix = f" ({status})" if status is not None else ""
        super().__init__(f"{method} {path}{suffix}: {detail}")


def _json_body(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"detail": raw.decode("utf-8", errors="replace")[:500]}


def api_request(base_url: str, method: str, path: str, *, body: bytes | None = None, headers: dict[str, str] | None = None, timeout: float = 20.0) -> tuple[int, Any]:
    request = Request(
        base_url.rstrip("/") + path,
        data=body,
        headers=headers or {},
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, _json_body(response.read())
    except HTTPError as exc:
        payload = _json_body(exc.read())
        detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
        raise ApiError(method, path, exc.code, str(detail)) from exc
    except URLError as exc:
        raise ApiError(method, path, None, f"API is unreachable: {exc.reason}") from exc


def json_request(base_url: str, method: str, path: str, payload: dict[str, Any], *, timeout: float) -> tuple[int, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return api_request(
        base_url,
        method,
        path,
        body=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=timeout,
    )


def multipart_body(fields: dict[str, str], file_field: str, file_name: str, file_bytes: bytes, content_type: str = "text/csv") -> tuple[bytes, str]:
    boundary = f"----CreditPassportDemo{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def upload_csv(base_url: str, applicant_id: str, source: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    file_path = DEMO_DIR / "inputs" / str(source["file"])
    file_bytes = file_path.read_bytes()
    body, content_type = multipart_body(
        {
            "source_type": str(source["source_type"]),
            "provider": str(source["provider"]),
            "currency": "INR",
            "consent": "true",
        },
        "file",
        file_path.name,
        file_bytes,
    )
    status, payload = api_request(
        base_url,
        "POST",
        f"/api/v1/applicants/{applicant_id}/statements",
        body=body,
        headers={"Content-Type": content_type, "Accept": "application/json"},
        timeout=timeout,
    )
    if status != 201:
        raise ApiError("POST", f"/api/v1/applicants/{applicant_id}/statements", status, str(payload))
    return {
        "file": str(source["file"]),
        "source_type": str(source["source_type"]),
        "provider": str(source["provider"]),
        "rows": payload.get("parsed_rows"),
        "source_id": (payload.get("source") or {}).get("id"),
    }


def _qualitative(score: int | None) -> str:
    if score is None:
        return "not-assessed"
    if score >= 75:
        return "strong"
    if score < 45:
        return "weak"
    return "mixed"


def seed_case(base_url: str, case: dict[str, Any], *, timeout: float, skip_challenger: bool) -> dict[str, Any]:
    applicant_payload = {
        "name": case["name"],
        "corridor": case["corridor"],
        "product": case["product"],
        "requested_amount": case["requested_amount"],
        "currency": case["currency"],
        "employment": case.get("employment"),
        "residency": case.get("residency"),
    }
    status, applicant = json_request(base_url, "POST", "/api/v1/applicants", applicant_payload, timeout=timeout)
    if status != 201:
        raise ApiError("POST", "/api/v1/applicants", status, str(applicant))
    applicant_id = str(applicant["id"])

    uploaded = [upload_csv(base_url, applicant_id, source, timeout=timeout) for source in case["sources"]]
    _, evidence = api_request(base_url, "GET", f"/api/v1/applicants/{applicant_id}/evidence", timeout=timeout)
    _, score = api_request(base_url, "GET", f"/api/v1/applicants/{applicant_id}/score?product={case['product']}", timeout=timeout)

    challenger: dict[str, Any]
    if skip_challenger:
        challenger = {"status": "skipped", "reason": "--skip-challenger"}
    else:
        try:
            _, challenger_payload = api_request(
                base_url,
                "GET",
                f"/api/v1/applicants/{applicant_id}/challenger-score?product={case['product']}",
                timeout=timeout,
            )
            challenger = {
                "status": "available",
                "model_name": challenger_payload.get("model_name"),
                "artifact_version": challenger_payload.get("artifact_version"),
                "probability": challenger_payload.get("probability"),
                "risk_band": challenger_payload.get("risk_band"),
                "blend": challenger_payload.get("blend"),
            }
        except ApiError as exc:
            # A missing optional challenger artifact is a valid local state. The
            # transparent score still provides a complete demo result.
            challenger = {
                "status": "unavailable",
                "http_status": exc.status,
                "detail": exc.detail,
            }

    transparent_score = score.get("score")
    blend = challenger.get("blend") if challenger.get("status") == "available" else None
    decision_score = blend.get("blended_score") if isinstance(blend, dict) else None
    return {
        "case_id": case["case_id"],
        "applicant_id": applicant_id,
        "name": case["name"],
        "expected_outcome": case["expected_outcome"],
        "uploaded_sources": uploaded,
        "evidence": {
            "source_count": len(evidence.get("sources", [])),
            "assertion_count": evidence.get("assertion_count"),
            "unique_event_count": evidence.get("unique_event_count"),
            "corroborated_count": evidence.get("corroborated_count"),
            "event_types": sorted({event.get("event_type") for event in evidence.get("events", []) if event.get("event_type")}),
        },
        "transparent_score": {
            "score": transparent_score,
            "band": score.get("band"),
            "score_range": score.get("score_range"),
            "reliability": score.get("reliability"),
            "reliability_band": score.get("reliability_band"),
        },
        "challenger": challenger,
        "decision": {
            "score": decision_score,
            "status": "research-only blend available" if decision_score is not None else "transparent score only",
        },
        "observed_outcome": {
            "score_signal": _qualitative(transparent_score),
            "risk_signal": challenger.get("risk_band") if challenger.get("status") == "available" else "unavailable",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("CREDIT_PASSPORT_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--summary-output", type=Path, default=DEMO_DIR / "results" / "latest.json")
    parser.add_argument("--case", action="append", dest="case_ids", help="seed only this case_id; repeat for multiple cases")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--skip-challenger", action="store_true", help="do not call the optional challenger endpoint")
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    validation = validate(manifest_path)
    if validation["status"] != "passed":
        print(json.dumps(validation, indent=2), file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case_ids = set(args.case_ids or [])
    cases = [case for case in manifest["cases"] if not case_ids or case["case_id"] in case_ids]
    unknown = case_ids - {case["case_id"] for case in manifest["cases"]}
    if unknown:
        print(f"Unknown case_id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    if not cases:
        print("No cases selected", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    try:
        for case in cases:
            result = seed_case(args.base_url, case, timeout=args.timeout, skip_challenger=args.skip_challenger)
            results.append(result)
            score = result["transparent_score"]
            print(f"{case['case_id']}: {score.get('score')}/100 ({score.get('band')}); reliability {score.get('reliability')} ({score.get('reliability_band')})")
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    summary = {
        "schema_version": "credit-passport-demo-run-1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url.rstrip("/"),
        "validation": {"status": validation["status"], "checked_files": validation["checked_files"], "checked_rows": validation["checked_rows"]},
        "cases": results,
    }
    output_path = args.summary_output if args.summary_output.is_absolute() else ROOT / args.summary_output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote summary: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

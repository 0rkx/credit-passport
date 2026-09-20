from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import GuideQueryRequest
from app.transition_guide import (
    GeminiConfig,
    GuideProviderError,
    TransitionGuide,
)


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                db_path=str(tmp_path / "guide.db"),
                cors_origins=("http://localhost:5173",),
                max_upload_bytes=1024 * 1024,
                model_metrics_path=str(tmp_path / "metrics.json"),
            )
        )
    )


def test_keyless_guide_is_grounded_and_cites_official_sources(tmp_path: Path):
    with _client(tmp_path) as client:
        response = client.post(
            "/api/v1/guide/query",
            json={
                "query": "What is the difference between NRE, NRO and FCNR(B) accounts?",
                "intent": "account-choices",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["provider"] == "deterministic"
        assert body["provider_status"] == "keyless"
        assert body["grounded"] is True
        assert body["abstained"] is False
        assert body["citations"]
        assert all(item["url"].startswith("https://") for item in body["citations"])
        assert any("NRE" in item for item in body["bullets"])
        assert body["disclaimer"]


def test_unsupported_question_abstains_but_explains_coverage(tmp_path: Path):
    with _client(tmp_path) as client:
        response = client.post("/api/v1/guide/query", json={"query": "Can you recommend a restaurant?"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["grounded"] is False
        assert body["abstained"] is True
        assert body["citations"]
        assert "official source support" in body["answer"]


def test_sources_and_prompts_are_available_to_frontend(tmp_path: Path):
    with _client(tmp_path) as client:
        sources = client.get("/api/v1/guide/sources")
        prompts = client.get("/api/v1/guide/suggested-prompts")
        assert sources.status_code == prompts.status_code == 200
        assert len(sources.json()) >= 6
        assert all(item["publisher"] for item in sources.json())
        assert {item["intent"] for item in prompts.json()} >= {"moving-abroad", "returning-india"}


def test_gemini_adapter_accepts_only_retrieved_citations(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit: int) -> bytes:
            return json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": json.dumps(
                                            {
                                                "answer": "Ask the authorised dealer to review the account.",
                                                "bullets": ["The correct action depends on your facts."],
                                                "follow_up_questions": [],
                                                "citation_ids": ["rbi-accounts-non-residents-2025"],
                                            }
                                        )
                                    }
                                ]
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    monkeypatch.setattr("app.transition_guide.urllib.request.urlopen", lambda *_args, **_kwargs: FakeResponse())
    guide = TransitionGuide(provider_config=GeminiConfig(api_key="test-key", mode="gemini"))
    response = guide.query(
        GuideQueryRequest(query="What should I ask my bank about NRE?", intent="account-choices")
    )
    assert response.provider == "gemini"
    assert response.provider_status == "configured"
    assert response.citations[0].id == "rbi-accounts-non-residents-2025"


def test_provider_error_returns_cited_deterministic_fallback():
    class FailingProvider:
        def answer(self, *_args, **_kwargs):
            raise GuideProviderError("provider unavailable")

    guide = TransitionGuide(provider_config=GeminiConfig(api_key="test-key", mode="gemini"))
    guide.provider = FailingProvider()  # type: ignore[assignment]
    response = guide.query(
        GuideQueryRequest(query="I am returning to India; what should I review?", intent="returning-india")
    )
    assert response.provider == "deterministic"
    assert response.provider_status == "fallback"
    assert response.grounded is True
    assert response.citations

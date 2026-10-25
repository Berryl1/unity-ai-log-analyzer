import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as main_module
from app.analyzer import LogAnalyzer
from app.main import MAXIMUM_REQUEST_BYTES, _analyze_until_disconnect, app
from app.models import AnalyzeRequest, AnalyzeResponse
from app.ollama_analyzer import OllamaStatus


client = TestClient(app)


def valid_payload() -> dict:
    return {
        "error_type": "Exception",
        "message": "NullReferenceException: Object reference not set",
        "stack_trace": (
            "Game.Player.Update() "
            "(at C:\\Users\\alice\\DiceAndDie\\Assets\\Player.cs:42)"
        ),
        "occurrence_count": 2,
        "first_occurred_at": "2026-10-25T10:00:00+09:00",
        "last_occurred_at": "2026-10-25T10:01:00+09:00",
    }


def test_health_returns_mock_server_status(monkeypatch) -> None:
    async def ready_status():
        return OllamaStatus("ready", "ready for tests")

    monkeypatch.setattr(main_module.ollama_analyzer, "check_status", ready_status)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "analyzer": "mock",
        "version": "0.5.0",
        "ollama_status": "ready",
        "ollama_model": "qwen2.5-coder:7b",
        "ollama_message": "ready for tests",
    }


def test_analyze_returns_structured_mock_result() -> None:
    response = client.post("/analyze", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["error_type"] == "Exception"
    assert body["is_mock"] is True
    assert "null" in body["probable_cause"].lower()
    assert "<redacted-user>" in body["location"]
    assert body["request_id"]
    assert body["disclaimer"]
    assert body["impact_scope"]


def test_analyze_selects_local_llm_mode(monkeypatch) -> None:
    async def local_result(request):
        return AnalyzeResponse(
            error_type=request.error_type,
            location="Assets/Game.cs:42",
            probable_cause="로컬 분석 원인",
            suggested_fix="로컬 분석 해결 방법",
            checks_required="로컬 분석 확인 사항",
            impact_scope="로컬 분석 영향 범위",
            disclaimer="추정 분석입니다.",
            is_mock=False,
            analyzed_at=datetime.now(timezone.utc),
            request_id="local-test-id",
        )

    monkeypatch.setattr(main_module.ollama_analyzer, "analyze", local_result)
    payload = valid_payload()
    payload["analyzer_mode"] = "local_llm"

    response = client.post("/analyze", json=payload)

    assert response.status_code == 200
    assert response.json()["is_mock"] is False
    assert response.json()["request_id"] == "local-test-id"


def test_analyze_rejects_invalid_input() -> None:
    payload = valid_payload()
    payload["occurrence_count"] = 0
    payload["unexpected"] = "not allowed"

    response = client.post("/analyze", json=payload)

    assert response.status_code == 422


def test_analyze_rejects_reversed_timestamps() -> None:
    payload = valid_payload()
    payload["last_occurred_at"] = "2026-10-25T09:59:00+09:00"

    response = client.post("/analyze", json=payload)

    assert response.status_code == 422


def test_analyze_rejects_oversized_request() -> None:
    response = client.post(
        "/analyze",
        content=b"x" * (MAXIMUM_REQUEST_BYTES + 1),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413


def test_analysis_is_cancelled_when_client_disconnects() -> None:
    class DisconnectedRequest:
        async def is_disconnected(self) -> bool:
            return True

    class SlowAnalyzer(LogAnalyzer):
        def __init__(self) -> None:
            self.cancelled = False

        async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    analyzer = SlowAnalyzer()
    analysis_request = AnalyzeRequest.model_validate(valid_payload())

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            _analyze_until_disconnect(
                DisconnectedRequest(),
                analyzer,
                analysis_request,
            )
        )

    assert raised.value.status_code == 499
    assert analyzer.cancelled is True

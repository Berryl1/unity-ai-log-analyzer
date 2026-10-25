import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.analyzer import AnalyzerError
from app.models import AnalyzeRequest
from app.ollama_analyzer import OllamaLogAnalyzer
from app.settings import Settings


def make_request() -> AnalyzeRequest:
    timestamp = datetime.now(timezone.utc)
    return AnalyzeRequest(
        error_type="Exception",
        message="NullReferenceException: Object reference not set",
        stack_trace="Game.Run() (at Assets/Game.cs:10)",
        occurrence_count=2,
        first_occurred_at=timestamp,
        last_occurred_at=timestamp,
        analyzer_mode="local_llm",
    )


def valid_analysis_content() -> str:
    return json.dumps(
        {
            "error_type": "Exception",
            "location": "Assets/Game.cs:10",
            "probable_cause": "참조 객체가 null일 가능성이 있습니다.",
            "suggested_fix": "초기화와 Inspector 할당을 확인하세요.",
            "checks_required": "첫 프로젝트 Stack Frame의 객체 상태를 확인하세요.",
            "impact_scope": "해당 게임 동작이 중단될 수 있습니다.",
            "disclaimer": "소스코드를 확인하지 않은 추정 분석입니다.",
            "source_category": "user_code",
            "confidence": "medium",
            "analysis_basis": "Assets/Game.cs 관련 프레임을 근거로 분류했습니다.",
        },
        ensure_ascii=False,
    )


def make_analyzer(handler, **settings_overrides) -> OllamaLogAnalyzer:
    settings = Settings(**settings_overrides)
    return OllamaLogAnalyzer(settings, httpx.MockTransport(handler))


def test_ollama_request_uses_chat_schema_and_separate_system_prompt() -> None:
    analyzer = OllamaLogAnalyzer(Settings(llm_max_output_tokens=777))

    body = analyzer.build_request_body(make_request())

    assert body["model"] == "qwen2.5-coder:7b"
    assert body["stream"] is False
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"
    assert "NullReferenceException" not in body["messages"][0]["content"]
    assert "NullReferenceException" in body["messages"][1]["content"]
    assert body["format"]["type"] == "object"
    assert body["options"]["num_predict"] == 777


def test_ollama_analyzer_parses_valid_structured_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5-coder:7b"}]})
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": valid_analysis_content()}},
        )

    result = asyncio.run(make_analyzer(handler).analyze(make_request()))

    assert result.is_mock is False
    assert result.error_type == "Exception"
    assert "null" in result.probable_cause
    assert result.impact_scope
    assert result.source_category == "user_code"


def test_ollama_analyzer_reports_missing_model() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "another-model:latest"}]})

    with pytest.raises(AnalyzerError) as raised:
        asyncio.run(make_analyzer(handler).analyze(make_request()))

    assert raised.value.code == "ollama_model_missing"
    assert raised.value.status_code == 503


def test_ollama_analyzer_reports_server_unavailable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    status = asyncio.run(make_analyzer(handler).check_status())

    assert status.status == "unavailable"


def test_ollama_analyzer_reports_analysis_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5-coder:7b"}]})
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(AnalyzerError) as raised:
        asyncio.run(make_analyzer(handler, ollama_timeout_seconds=1).analyze(make_request()))

    assert raised.value.code == "ollama_timeout"
    assert raised.value.status_code == 504


def test_ollama_analyzer_rejects_invalid_structured_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5-coder:7b"}]})
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": '{"location":"missing fields"}'}},
        )

    with pytest.raises(AnalyzerError) as raised:
        asyncio.run(make_analyzer(handler).analyze(make_request()))

    assert raised.value.code == "ollama_invalid_analysis"
    assert raised.value.status_code == 502


def test_ollama_analyzer_rejects_non_json_ollama_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5-coder:7b"}]})
        return httpx.Response(200, text="not json")

    with pytest.raises(AnalyzerError) as raised:
        asyncio.run(make_analyzer(handler).analyze(make_request()))

    assert raised.value.code == "ollama_invalid_response"


def test_ollama_analyzer_reports_insufficient_memory() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5-coder:7b"}]})
        return httpx.Response(500, json={"error": "failed to allocate system memory"})

    with pytest.raises(AnalyzerError) as raised:
        asyncio.run(make_analyzer(handler).analyze(make_request()))

    assert raised.value.code == "ollama_insufficient_memory"
    assert raised.value.status_code == 503


def test_ollama_analyzer_refuses_remote_base_url() -> None:
    analyzer = OllamaLogAnalyzer(Settings(ollama_base_url="https://example.com"))

    status = asyncio.run(analyzer.check_status())

    assert status.status == "configuration_error"

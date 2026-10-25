"""FastAPI 진입점.

Unity가 승인한 로그만 받아 로컬 분석기로 전달하고, 서버가 보관한 분석 결과만
Slack 미리보기와 전송에 사용할 수 있도록 API 경계를 구성한다.
"""

import asyncio
from contextlib import suppress

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.analyzer import AnalyzerError, LogAnalyzer, MockLogAnalyzer
from app.analysis_store import AnalysisStore
from app.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    HealthResponse,
    SlackPreviewResponse,
    SlackRequest,
    SlackSendRequest,
    SlackSendResponse,
    SlackStatusResponse,
)
from app.ollama_analyzer import OllamaLogAnalyzer
from app.sanitizer import sanitize_text
from app.settings import Settings
from app.slack_service import SlackService


APP_VERSION = "0.5.0"
MAXIMUM_REQUEST_BYTES = 384 * 1024

settings = Settings.from_environment()
mock_analyzer = MockLogAnalyzer()
ollama_analyzer = OllamaLogAnalyzer(settings)
# Slack 요청에서 Unity가 임의 결과를 만들어 보내지 못하도록 성공한 분석을 서버가 보관한다.
analysis_store = AnalysisStore(
    settings.analysis_history_ttl_seconds,
    settings.analysis_history_max_entries,
)
slack_service = SlackService(settings, analysis_store)

app = FastAPI(
    title="Dice And Die AI Log Analyzer",
    version=APP_VERSION,
    description="Local-only Unity log analysis API with Mock and Ollama modes.",
)


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    """JSON 파싱 전에 과도한 요청을 거부해 메모리 사용량을 제한한다."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAXIMUM_REQUEST_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body exceeds the 384 KiB limit."},
                )
        except ValueError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "Content-Length must be an integer."},
            )

    return await call_next(request)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    ollama_status = await ollama_analyzer.check_status()
    return HealthResponse(
        version=APP_VERSION,
        analyzer=settings.analyzer_mode,
        ollama_status=ollama_status.status,
        ollama_model=settings.ollama_model,
        ollama_message=ollama_status.message,
    )


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest, http_request: Request) -> AnalyzeResponse:
    # Unity에서도 필터링하지만 신뢰 경계인 서버에서 반드시 다시 필터링한다.
    sanitized_request = request.model_copy(
        update={
            "message": sanitize_text(request.message),
            "stack_trace": sanitize_text(request.stack_trace),
        }
    )
    selected_mode = request.analyzer_mode or settings.analyzer_mode
    analyzer = mock_analyzer if selected_mode == "mock" else ollama_analyzer

    try:
        result = await _analyze_until_disconnect(
            http_request,
            analyzer,
            sanitized_request,
        )
        await analysis_store.save(
            sanitized_request,
            result,
            "Mock" if result.is_mock else "Qwen Local LLM",
            "Mock 규칙 기반 분석기" if result.is_mock else settings.ollama_model,
        )
        return result
    except AnalyzerError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": exception.message},
        ) from exception


@app.get("/slack/status", response_model=SlackStatusResponse)
async def slack_status() -> SlackStatusResponse:
    return await slack_service.status()


@app.post("/slack/preview", response_model=SlackPreviewResponse)
async def slack_preview(request: SlackRequest) -> SlackPreviewResponse:
    try:
        return await slack_service.create_preview(request.request_id)
    except ValueError as exception:
        raise HTTPException(status_code=503, detail=str(exception)) from exception
    except LookupError as exception:
        raise HTTPException(status_code=404, detail=str(exception)) from exception


@app.post("/slack/send", response_model=SlackSendResponse)
async def slack_send(request: SlackSendRequest) -> SlackSendResponse:
    return await slack_service.send(request.request_id, request.preview_token)


async def _analyze_until_disconnect(
    http_request: Request,
    analyzer: LogAnalyzer,
    analysis_request: AnalyzeRequest,
) -> AnalyzeResponse:
    """클라이언트 연결이 끊어지면 장시간 실행 중인 Ollama task도 함께 취소한다."""
    analysis_task = asyncio.create_task(analyzer.analyze(analysis_request))
    try:
        while not analysis_task.done():
            await asyncio.wait({analysis_task}, timeout=0.1)
            if await http_request.is_disconnected():
                analysis_task.cancel()
                with suppress(asyncio.CancelledError):
                    await analysis_task
                raise HTTPException(
                    status_code=499,
                    detail={
                        "code": "client_cancelled",
                        "message": "클라이언트가 분석 요청을 취소했습니다.",
                    },
                )
        return await analysis_task
    finally:
        if not analysis_task.done():
            analysis_task.cancel()

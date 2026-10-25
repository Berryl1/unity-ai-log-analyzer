from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnalyzeRequest(BaseModel):
    """Unity에서 선택·승인한 단일 오류의 분석 요청."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    error_type: Literal["Error", "Exception", "Assert"]
    message: str = Field(min_length=1, max_length=16_000)
    stack_trace: str = Field(max_length=64_000)
    occurrence_count: int = Field(ge=1, le=2_147_483_647)
    first_occurred_at: datetime
    last_occurred_at: datetime
    analyzer_mode: Literal["mock", "local_llm"] | None = None

    @model_validator(mode="after")
    def validate_timestamp_order(self) -> "AnalyzeRequest":
        if self.last_occurred_at < self.first_occurred_at:
            raise ValueError("last_occurred_at must not precede first_occurred_at")
        return self


class AnalyzeResponse(BaseModel):
    """Unity UI 및 Slack 단계가 공통으로 사용하는 구조화 분석 결과."""
    model_config = ConfigDict(extra="forbid")

    error_type: Literal["Error", "Exception", "Assert"]
    location: str = Field(min_length=1, max_length=2_000)
    probable_cause: str = Field(min_length=1, max_length=4_000)
    suggested_fix: str = Field(min_length=1, max_length=4_000)
    checks_required: str = Field(min_length=1, max_length=4_000)
    impact_scope: str = Field(min_length=1, max_length=3_000)
    disclaimer: str = Field(min_length=1, max_length=1_000)
    is_mock: bool = True
    analyzed_at: datetime
    request_id: str
    source_category: Literal[
        "user_code", "unity_engine", "unity_editor", "external_package", "unknown"
    ] = "unknown"
    confidence: Literal["low", "medium", "high"] = "low"
    analysis_basis: str = Field(default="제공된 오류 메시지와 Stack Trace", max_length=3_000)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    analyzer: Literal["mock", "local_llm"] = "mock"
    version: str
    ollama_status: Literal[
        "ready", "unavailable", "model_missing", "configuration_error"
    ]
    ollama_model: str
    ollama_message: str


class SlackStatusResponse(BaseModel):
    enabled: bool
    token_configured: bool
    channel_configured: bool
    connection_status: Literal[
        "disabled", "not_configured", "ready", "authentication_failed", "unavailable"
    ]
    channel_id: str
    status_message: str


class SlackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(min_length=1, max_length=128)


class SlackSendRequest(SlackRequest):
    preview_token: str = Field(min_length=32, max_length=128)


class SlackPreviewResponse(BaseModel):
    """사용자 확인용 고정 메시지와 단기 승인 토큰."""
    request_id: str
    channel_id: str
    preview_token: str
    preview_text: str = Field(min_length=1, max_length=16_000)
    expires_at: datetime


class SlackSendResponse(BaseModel):
    """Token 같은 인증정보를 제외한 Slack 전송 결과."""
    success: bool
    request_id: str
    channel_id: str = ""
    slack_message_ts: str = ""
    sent_at: datetime | None = None
    error_code: str = ""
    status_message: str


class LLMAnalysisPayload(BaseModel):
    """Qwen 자유 형식 출력을 허용하지 않기 위한 내부 검증 스키마."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    error_type: Literal["Error", "Exception", "Assert"]
    location: str = Field(min_length=1, max_length=2_000)
    probable_cause: str = Field(min_length=1, max_length=4_000)
    suggested_fix: str = Field(min_length=1, max_length=4_000)
    checks_required: str = Field(min_length=1, max_length=4_000)
    impact_scope: str = Field(min_length=1, max_length=3_000)
    disclaimer: str = Field(min_length=1, max_length=1_000)
    source_category: Literal[
        "user_code", "unity_engine", "unity_editor", "external_package", "unknown"
    ]
    confidence: Literal["low", "medium", "high"]
    analysis_basis: str = Field(min_length=1, max_length=3_000)

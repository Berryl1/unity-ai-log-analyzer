import asyncio
import html
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from typing import Any, Callable

from slack_sdk.errors import SlackApiError, SlackClientError
from slack_sdk.web.async_client import AsyncWebClient

from app.analysis_store import AnalysisRecord, AnalysisStore
from app.models import (
    SlackPreviewResponse,
    SlackSendResponse,
    SlackStatusResponse,
)
from app.sanitizer import sanitize_text
from app.settings import Settings


PREVIEW_TTL_SECONDS = 300
MAX_FALLBACK_TEXT_LENGTH = 12_000
MAX_BLOCK_TEXT_LENGTH = 2_900
_BROADCAST_MENTION = re.compile(r"(?i)@(channel|here|everyone)\b")


@dataclass(frozen=True)
class SlackPayload:
    request_id: str
    channel_id: str
    text: str
    blocks: list[dict[str, Any]]
    preview_token: str
    expires_at: datetime


class SlackService:
    """분석 결과의 미리보기, 명시적 승인, 단일 Slack 전송을 관리한다.

    Unity는 Token이나 임의 채널을 전달하지 않는다. 서버가 만든 무작위 preview_token과
    환경변수의 고정 채널만 사용하며, 전송 상태는 request_id 단위로 중복을 차단한다.
    """

    def __init__(
        self,
        settings: Settings,
        analysis_store: AnalysisStore,
        client_factory: Callable[[], AsyncWebClient] | None = None,
    ) -> None:
        self.settings = settings
        self.analysis_store = analysis_store
        self._client_factory = client_factory
        self._previews: OrderedDict[str, SlackPayload] = OrderedDict()
        self._send_states: OrderedDict[str, tuple[str, datetime]] = OrderedDict()
        self._maximum_state_entries = settings.analysis_history_max_entries
        self._state_ttl = timedelta(seconds=settings.analysis_history_ttl_seconds)
        self._lock = asyncio.Lock()

    async def status(self) -> SlackStatusResponse:
        base_status = self._configuration_status()
        if base_status is not None:
            return base_status
        try:
            response = await self._client().auth_test()
            if not response.get("ok"):
                return self._status("authentication_failed", "Slack 인증에 실패했습니다.")
            return self._status("ready", "Slack Bot 인증이 확인되었습니다.")
        except SlackApiError as exception:
            code = _slack_error_code(exception)
            state = "authentication_failed" if code in {
                "invalid_auth", "not_authed", "account_inactive", "token_revoked"
            } else "unavailable"
            return self._status(state, _safe_error_message(code))
        except (SlackClientError, asyncio.TimeoutError):
            return self._status(
                "unavailable", "Slack API에 연결할 수 없거나 응답 시간이 초과되었습니다."
            )

    async def create_preview(self, request_id: str) -> SlackPreviewResponse:
        """서버에 존재하는 분석만 고정 payload로 만들고 단기 승인 토큰을 발급한다."""
        configuration = self._configuration_status()
        if configuration is not None:
            raise ValueError(configuration.status_message)
        record = await self.analysis_store.get(request_id)
        if record is None:
            raise LookupError(
                "분석 결과를 찾을 수 없거나 보관 시간이 만료되었습니다. 다시 분석하세요."
            )
        payload = self._build_payload(record)
        async with self._lock:
            # 미리보기도 민감정보를 포함할 수 있으므로 TTL뿐 아니라 개수도 제한한다.
            self._prune_previews(datetime.now(timezone.utc))
            self._previews[payload.preview_token] = payload
            self._previews.move_to_end(payload.preview_token)
            while len(self._previews) > self._maximum_state_entries:
                self._previews.popitem(last=False)
        return SlackPreviewResponse(
            request_id=request_id,
            channel_id=payload.channel_id,
            preview_token=payload.preview_token,
            preview_text=payload.text,
            expires_at=payload.expires_at,
        )

    async def send(self, request_id: str, preview_token: str) -> SlackSendResponse:
        """승인된 미리보기와 request_id가 일치할 때만 chat.postMessage를 한 번 호출한다."""
        configuration = self._configuration_status()
        if configuration is not None:
            return self._failure(request_id, "slack_not_ready", configuration.status_message)

        now = datetime.now(timezone.utc)
        async with self._lock:
            # 검증과 sending 전환을 같은 lock 안에서 수행해 연속 클릭과 동시 요청을 막는다.
            self._prune_previews(now)
            self._prune_send_states(now)
            state_record = self._send_states.get(request_id)
            state = state_record[0] if state_record is not None else None
            if state in {"sending", "sent", "indeterminate"}:
                message = {
                    "sending": "동일한 분석 결과를 이미 전송 중입니다.",
                    "sent": "동일한 분석 결과는 이미 Slack으로 전송되었습니다.",
                    "indeterminate": (
                        "이전 요청의 성공 여부를 확인할 수 없어 중복 방지를 위해 재전송하지 않았습니다."
                    ),
                }[state]
                return self._failure(request_id, f"duplicate_{state}", message)
            payload = self._previews.get(preview_token)
            if payload is None or payload.request_id != request_id:
                return self._failure(
                    request_id,
                    "preview_expired",
                    "미리보기가 없거나 만료되었습니다. 내용을 다시 확인하세요.",
                )
            self._set_send_state(request_id, "sending", now)

        try:
            response = await self._client().chat_postMessage(
                channel=payload.channel_id,
                text=payload.text,
                blocks=payload.blocks,
                unfurl_links=False,
                unfurl_media=False,
                link_names=False,
            )
            if not response.get("ok"):
                raise SlackClientError("Slack returned an unsuccessful response.")
            sent_at = datetime.now(timezone.utc)
            async with self._lock:
                self._set_send_state(request_id, "sent", sent_at)
                self._previews.pop(preview_token, None)
            return SlackSendResponse(
                success=True,
                request_id=request_id,
                channel_id=payload.channel_id,
                slack_message_ts=str(response.get("ts", "")),
                sent_at=sent_at,
                status_message="Slack 메시지를 전송했습니다.",
            )
        except SlackApiError as exception:
            code = _slack_error_code(exception)
            async with self._lock:
                self._send_states.pop(request_id, None)
            message = _safe_error_message(code)
            retry_after = _retry_after_seconds(exception)
            if retry_after:
                message += f" Retry-After: {retry_after}초"
            return self._failure(request_id, code, message)
        except (SlackClientError, asyncio.TimeoutError):
            async with self._lock:
                # 요청이 Slack에 도달했을 수 있으므로 결과 불명 상태는 자동 재시도하지 않는다.
                self._set_send_state(
                    request_id,
                    "indeterminate",
                    datetime.now(timezone.utc),
                )
            return self._failure(
                request_id,
                "slack_result_indeterminate",
                "Slack 응답을 확인할 수 없습니다. 중복 가능성이 있어 자동 재전송하지 않습니다.",
            )

    def _configuration_status(self) -> SlackStatusResponse | None:
        if not self.settings.slack_enabled:
            return self._status("disabled", "Slack 연동이 비활성화되어 있습니다.")
        if not self.settings.slack_bot_token or not self.settings.slack_channel_id:
            return self._status(
                "not_configured",
                "SLACK_BOT_TOKEN과 SLACK_CHANNEL_ID를 모두 설정하세요.",
            )
        return None

    def _status(self, state: str, message: str) -> SlackStatusResponse:
        return SlackStatusResponse(
            enabled=self.settings.slack_enabled,
            token_configured=bool(self.settings.slack_bot_token),
            channel_configured=bool(self.settings.slack_channel_id),
            connection_status=state,
            channel_id=self.settings.slack_channel_id,
            status_message=message,
        )

    def _client(self) -> AsyncWebClient:
        if self._client_factory is not None:
            return self._client_factory()
        return AsyncWebClient(
            token=self.settings.slack_bot_token,
            timeout=self.settings.slack_timeout_seconds,
        )

    def _build_payload(self, record: AnalysisRecord) -> SlackPayload:
        """미리보기와 실제 전송에서 공유할 단일 Slack payload를 생성한다."""
        request = record.request
        response = record.response
        fields = [
            ("프로젝트", self.settings.project_name),
            ("오류 유형", response.error_type),
            ("발생 영역", response.source_category),
            ("분석 신뢰도", response.confidence),
            ("오류 발생 위치", response.location),
            ("발생 횟수", str(request.occurrence_count)),
            ("최초 발생", request.first_occurred_at.isoformat()),
            ("최근 발생", request.last_occurred_at.isoformat()),
            ("분석 모드", record.analyzer_name),
            ("사용 모델", record.model_name),
            ("분석 근거", response.analysis_basis),
            ("예상 원인", response.probable_cause),
            ("권장 해결 방법", response.suggested_fix),
            ("추가 확인 사항", response.checks_required),
            ("예상 영향 범위", response.impact_scope),
            ("분석 시각", response.analyzed_at.isoformat()),
            ("request_id", response.request_id),
            ("안내", response.disclaimer),
        ]
        # LLM 결과도 신뢰하지 않고 외부 서비스 전송 직전에 다시 필터링한다.
        cleaned = [(label, _clean(value)) for label, value in fields]
        lines = ["Unity AI Log Analyzer"] + [
            f"{label}: {value}" for label, value in cleaned
        ]
        text = _truncate("\n".join(lines), MAX_FALLBACK_TEXT_LENGTH)
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Unity AI Log Analyzer"},
            }
        ]
        for label, value in cleaned:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "plain_text",
                        "text": _truncate(f"{label}\n{value}", MAX_BLOCK_TEXT_LENGTH),
                    },
                }
            )
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=PREVIEW_TTL_SECONDS)
        # 내용 해시는 추측 가능하므로 승인 토큰은 암호학적으로 안전한 난수를 사용한다.
        preview_token = token_urlsafe(32)
        return SlackPayload(
            request_id=response.request_id,
            channel_id=self.settings.slack_channel_id,
            text=text,
            blocks=blocks,
            preview_token=preview_token,
            expires_at=expires_at,
        )

    def _failure(self, request_id: str, code: str, message: str) -> SlackSendResponse:
        return SlackSendResponse(
            success=False,
            request_id=request_id,
            error_code=code,
            status_message=message,
        )

    def _prune_previews(self, now: datetime) -> None:
        expired = [
            token for token, payload in self._previews.items() if payload.expires_at <= now
        ]
        for token in expired:
            self._previews.pop(token, None)

    def _set_send_state(self, request_id: str, state: str, now: datetime) -> None:
        self._send_states[request_id] = (state, now + self._state_ttl)
        self._send_states.move_to_end(request_id)
        while len(self._send_states) > self._maximum_state_entries:
            self._send_states.popitem(last=False)

    def _prune_send_states(self, now: datetime) -> None:
        expired = [
            request_id
            for request_id, (_, expires_at) in self._send_states.items()
            if expires_at <= now
        ]
        for request_id in expired:
            self._send_states.pop(request_id, None)


def _clean(value: Any) -> str:
    cleaned = sanitize_text(str(value or ""))
    cleaned = html.unescape(cleaned)
    cleaned = _BROADCAST_MENTION.sub(lambda match: "@\u200b" + match.group(1), cleaned)
    cleaned = cleaned.replace("<", "‹").replace(">", "›")
    return cleaned.strip() or "정보 없음"


def _truncate(value: str, maximum: int) -> str:
    return value if len(value) <= maximum else value[: maximum - 1] + "…"


def _slack_error_code(exception: SlackApiError) -> str:
    try:
        return str(exception.response.get("error", "slack_api_error"))
    except (AttributeError, TypeError):
        return "slack_api_error"


def _safe_error_message(code: str) -> str:
    messages = {
        "invalid_auth": "Slack Bot Token이 올바르지 않습니다.",
        "not_authed": "Slack 인증정보가 설정되지 않았습니다.",
        "account_inactive": "Slack Bot 계정이 비활성화되어 있습니다.",
        "token_revoked": "Slack Bot Token이 취소되었습니다.",
        "missing_scope": "Slack 앱에 chat:write 권한이 필요합니다.",
        "not_in_channel": "Slack Bot이 대상 채널에 참여하지 않았습니다.",
        "channel_not_found": "설정된 Slack 채널을 찾을 수 없습니다.",
        "is_archived": "대상 Slack 채널이 보관 처리되었습니다.",
        "ratelimited": "Slack API 요청 한도를 초과했습니다. 잠시 후 다시 시도하세요.",
    }
    return messages.get(code, f"Slack API 요청이 실패했습니다. ({code})")


def _retry_after_seconds(exception: SlackApiError) -> str:
    try:
        headers = exception.response.headers
        return str(headers.get("Retry-After") or headers.get("retry-after") or "")
    except (AttributeError, TypeError):
        return ""

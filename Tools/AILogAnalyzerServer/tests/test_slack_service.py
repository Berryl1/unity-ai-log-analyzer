import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.analysis_store import AnalysisStore
from app.models import AnalyzeRequest, AnalyzeResponse
from app.settings import Settings
from app.slack_service import SlackService
from slack_sdk.errors import SlackApiError
from slack_sdk.web.slack_response import SlackResponse


class FakeSlackClient:
    def __init__(self, post_delay: float = 0.0, fail_post: bool = False) -> None:
        self.post_delay = post_delay
        self.fail_post = fail_post
        self.posts: list[dict] = []

    async def auth_test(self):
        return {"ok": True, "user_id": "U_TEST"}

    async def chat_postMessage(self, **kwargs):
        self.posts.append(kwargs)
        if self.post_delay:
            await asyncio.sleep(self.post_delay)
        if self.fail_post:
            from slack_sdk.errors import SlackClientError

            raise SlackClientError("network failed")
        return {"ok": True, "ts": "1234.5678"}


class ApiErrorSlackClient(FakeSlackClient):
    def __init__(self, error_code: str, fail_auth: bool = False) -> None:
        super().__init__()
        self.error_code = error_code
        self.fail_auth = fail_auth

    def _error(self) -> SlackApiError:
        response = SlackResponse(
            client=None,
            http_verb="POST",
            api_url="https://slack.com/api/test",
            req_args={},
            data={"ok": False, "error": self.error_code},
            headers={},
            status_code=429 if self.error_code == "ratelimited" else 200,
        )
        return SlackApiError("test error", response)

    async def auth_test(self):
        if self.fail_auth:
            raise self._error()
        return await super().auth_test()

    async def chat_postMessage(self, **kwargs):
        self.posts.append(kwargs)
        raise self._error()


def _request() -> AnalyzeRequest:
    timestamp = datetime.now(timezone.utc)
    return AnalyzeRequest(
        error_type="Exception",
        message="token=secret @channel",
        stack_trace="Game.Run() (at C:\\Users\\alice\\Game.cs:10)",
        occurrence_count=3,
        first_occurred_at=timestamp,
        last_occurred_at=timestamp,
        analyzer_mode="local_llm",
    )


def _response(request_id: str = "request-1") -> AnalyzeResponse:
    return AnalyzeResponse(
        error_type="Exception",
        location="Game.Run() (at C:\\Users\\alice\\Game.cs:10)",
        probable_cause="token=secret @here 참조가 null일 수 있습니다.",
        suggested_fix="Inspector 할당을 확인하세요.",
        checks_required="재현 경로를 확인하세요.",
        impact_scope="해당 기능이 중단될 수 있습니다.",
        disclaimer="추정 분석이며 확정된 사실이 아닙니다.",
        is_mock=False,
        analyzed_at=datetime.now(timezone.utc),
        request_id=request_id,
    )


async def _make_service(
    client: FakeSlackClient | None = None,
    **settings_overrides,
) -> tuple[SlackService, FakeSlackClient, AnalysisStore]:
    fake_client = client or FakeSlackClient()
    values = {
        "slack_enabled": True,
        "slack_bot_token": "test-token",
        "slack_channel_id": "C_TEST",
    }
    values.update(settings_overrides)
    store = AnalysisStore(ttl_seconds=3_600, max_entries=20)
    service = SlackService(Settings(**values), store, lambda: fake_client)
    return service, fake_client, store


def test_slack_disabled_does_not_require_credentials() -> None:
    async def run():
        store = AnalysisStore(3_600, 20)
        service = SlackService(Settings(), store)
        result = await service.status()
        assert result.connection_status == "disabled"
        assert result.enabled is False

    asyncio.run(run())


def test_slack_missing_token_or_channel_is_reported() -> None:
    async def run():
        service, _, _ = await _make_service(slack_bot_token="")
        result = await service.status()
        assert result.connection_status == "not_configured"
        assert result.token_configured is False

    asyncio.run(run())


def test_status_uses_auth_test_without_exposing_token() -> None:
    async def run():
        service, _, _ = await _make_service()
        result = await service.status()
        assert result.connection_status == "ready"
        assert "test-token" not in result.model_dump_json()

    asyncio.run(run())


def test_invalid_auth_is_reported_without_token() -> None:
    async def run():
        service, _, _ = await _make_service(
            ApiErrorSlackClient("invalid_auth", fail_auth=True)
        )
        result = await service.status()
        assert result.connection_status == "authentication_failed"
        assert "Token" in result.status_message
        assert "test-token" not in result.model_dump_json()

    asyncio.run(run())


def test_preview_requires_server_known_analysis() -> None:
    async def run():
        service, _, _ = await _make_service()
        try:
            await service.create_preview("made-up-id")
            raise AssertionError("unknown request_id must fail")
        except LookupError:
            pass

    asyncio.run(run())


def test_preview_and_send_use_same_sanitized_payload() -> None:
    async def run():
        service, client, store = await _make_service()
        request = _request()
        response = _response()
        await store.save(request, response, "Qwen Local LLM", "qwen2.5-coder:7b")

        preview = await service.create_preview(response.request_id)
        sent = await service.send(response.request_id, preview.preview_token)

        assert sent.success is True
        assert client.posts[0]["text"] == preview.preview_text
        assert "secret" not in preview.preview_text
        assert "alice" not in preview.preview_text
        assert "@channel" not in preview.preview_text
        assert "@here" not in preview.preview_text
        assert client.posts[0]["unfurl_links"] is False
        assert client.posts[0]["channel"] == "C_TEST"

    asyncio.run(run())


def test_mock_analysis_is_labeled_in_preview() -> None:
    async def run():
        service, _, store = await _make_service()
        response = _response("mock-id").model_copy(update={"is_mock": True})
        await store.save(_request(), response, "Mock", "Mock 규칙 기반 분석기")
        preview = await service.create_preview(response.request_id)
        assert "분석 모드: Mock" in preview.preview_text

    asyncio.run(run())


def test_message_obeys_slack_block_text_limits() -> None:
    async def run():
        service, _, store = await _make_service()
        response = _response().model_copy(
            update={
                "probable_cause": "원인" * 1_300,
                "suggested_fix": "해결" * 1_300,
            }
        )
        await store.save(_request(), response, "Qwen Local LLM", "qwen2.5-coder:7b")
        preview = await service.create_preview(response.request_id)
        payload = service._previews[preview.preview_token]
        assert len(preview.preview_text) <= 12_000
        assert all(
            len(block.get("text", {}).get("text", "")) <= 2_900
            for block in payload.blocks
        )

    asyncio.run(run())


def test_duplicate_send_calls_slack_only_once() -> None:
    async def run():
        service, client, store = await _make_service()
        response = _response()
        await store.save(_request(), response, "Qwen Local LLM", "qwen2.5-coder:7b")
        preview = await service.create_preview(response.request_id)

        first = await service.send(response.request_id, preview.preview_token)
        second = await service.send(response.request_id, preview.preview_token)

        assert first.success is True
        assert second.success is False
        assert second.error_code == "duplicate_sent"
        assert len(client.posts) == 1

    asyncio.run(run())


def test_tampered_preview_token_is_rejected_without_slack_call() -> None:
    async def run():
        service, client, store = await _make_service()
        response = _response()
        await store.save(_request(), response, "Qwen Local LLM", "qwen2.5-coder:7b")
        preview = await service.create_preview(response.request_id)
        tampered = preview.preview_token[:-1] + (
            "A" if preview.preview_token[-1] != "A" else "B"
        )
        result = await service.send(response.request_id, tampered)
        assert result.error_code == "preview_expired"
        assert client.posts == []

    asyncio.run(run())


def test_expired_preview_token_is_rejected_without_slack_call() -> None:
    async def run():
        service, client, store = await _make_service()
        response = _response()
        await store.save(_request(), response, "Qwen Local LLM", "qwen2.5-coder:7b")
        preview = await service.create_preview(response.request_id)
        payload = service._previews[preview.preview_token]
        service._previews[preview.preview_token] = replace(
            payload,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        result = await service.send(response.request_id, preview.preview_token)
        assert result.error_code == "preview_expired"
        assert client.posts == []

    asyncio.run(run())


def test_preview_tokens_are_random_and_not_reusable_across_requests() -> None:
    async def run():
        service, client, store = await _make_service()
        first = _response("request-1")
        second = _response("request-2")
        await store.save(_request(), first, "Qwen Local LLM", "qwen2.5-coder:7b")
        await store.save(_request(), second, "Qwen Local LLM", "qwen2.5-coder:7b")
        first_preview = await service.create_preview(first.request_id)
        second_preview = await service.create_preview(second.request_id)
        assert first_preview.preview_token != second_preview.preview_token
        result = await service.send(second.request_id, first_preview.preview_token)
        assert result.error_code == "preview_expired"
        assert client.posts == []

    asyncio.run(run())


def test_concurrent_duplicate_send_calls_slack_only_once() -> None:
    async def run():
        service, client, store = await _make_service(FakeSlackClient(post_delay=0.05))
        response = _response()
        await store.save(_request(), response, "Qwen Local LLM", "qwen2.5-coder:7b")
        preview = await service.create_preview(response.request_id)
        results = await asyncio.gather(
            service.send(response.request_id, preview.preview_token),
            service.send(response.request_id, preview.preview_token),
        )
        assert sum(result.success for result in results) == 1
        assert len(client.posts) == 1

    asyncio.run(run())


def test_unknown_network_result_is_not_automatically_retried() -> None:
    async def run():
        service, client, store = await _make_service(FakeSlackClient(fail_post=True))
        response = _response()
        await store.save(_request(), response, "Qwen Local LLM", "qwen2.5-coder:7b")
        preview = await service.create_preview(response.request_id)
        first = await service.send(response.request_id, preview.preview_token)
        second = await service.send(response.request_id, preview.preview_token)
        assert first.error_code == "slack_result_indeterminate"
        assert second.error_code == "duplicate_indeterminate"
        assert len(client.posts) == 1

    asyncio.run(run())


def test_slack_permission_error_is_safe_and_retryable() -> None:
    async def run():
        service, client, store = await _make_service(
            ApiErrorSlackClient("missing_scope")
        )
        response = _response()
        await store.save(_request(), response, "Qwen Local LLM", "qwen2.5-coder:7b")
        preview = await service.create_preview(response.request_id)
        result = await service.send(response.request_id, preview.preview_token)
        assert result.success is False
        assert result.error_code == "missing_scope"
        assert "chat:write" in result.status_message
        assert len(client.posts) == 1

    asyncio.run(run())


def test_channel_not_found_error_is_explained() -> None:
    async def run():
        service, _, store = await _make_service(
            ApiErrorSlackClient("channel_not_found")
        )
        response = _response()
        await store.save(_request(), response, "Qwen Local LLM", "qwen2.5-coder:7b")
        preview = await service.create_preview(response.request_id)
        result = await service.send(response.request_id, preview.preview_token)
        assert result.error_code == "channel_not_found"
        assert "채널" in result.status_message

    asyncio.run(run())


def test_rate_limit_does_not_trigger_automatic_retry() -> None:
    async def run():
        service, client, store = await _make_service(ApiErrorSlackClient("ratelimited"))
        response = _response()
        await store.save(_request(), response, "Qwen Local LLM", "qwen2.5-coder:7b")
        preview = await service.create_preview(response.request_id)
        result = await service.send(response.request_id, preview.preview_token)
        assert result.error_code == "ratelimited"
        assert len(client.posts) == 1

    asyncio.run(run())


def test_preview_and_duplicate_state_stores_are_bounded() -> None:
    async def run():
        service, _, store = await _make_service(analysis_history_max_entries=2)
        previews = []
        for index in range(3):
            response = _response(f"bounded-{index}")
            await store.save(_request(), response, "Qwen Local LLM", "qwen2.5-coder:7b")
            previews.append(await service.create_preview(response.request_id))

        assert len(service._previews) == 2
        assert previews[0].preview_token not in service._previews

        for preview in previews[1:]:
            result = await service.send(preview.request_id, preview.preview_token)
            assert result.success is True
        assert len(service._send_states) == 2

    asyncio.run(run())

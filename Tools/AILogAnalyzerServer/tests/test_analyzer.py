import asyncio
from datetime import datetime, timezone

from app.analyzer import MockLogAnalyzer
from app.models import AnalyzeRequest
from app.sanitizer import sanitize_text


def make_request(message: str, stack_trace: str = "Game.Run() (at Assets/Game.cs:10)"):
    timestamp = datetime.now(timezone.utc)
    return AnalyzeRequest(
        error_type="Exception",
        message=message,
        stack_trace=stack_trace,
        occurrence_count=1,
        first_occurred_at=timestamp,
        last_occurred_at=timestamp,
    )


def test_mock_analyzer_uses_specific_null_reference_guidance() -> None:
    result = asyncio.run(
        MockLogAnalyzer().analyze(
            make_request("NullReferenceException: Object reference not set")
        )
    )

    assert "null" in result.probable_cause.lower()
    assert result.location == "관련 사용자 코드 프레임: Game.Run() (at Assets/Game.cs:10)"
    assert result.is_mock is True
    assert result.impact_scope
    assert result.source_category == "user_code"
    assert result.analysis_basis


def test_sanitizer_redacts_common_sensitive_values() -> None:
    original = (
        "email=dev@example.com token=abc123456 password=hunter2 "
        "Bearer very-secret C:\\Users\\alice\\Project 192.168.10.20"
    )

    sanitized = sanitize_text(original)

    assert "dev@example.com" not in sanitized
    assert "abc123456" not in sanitized
    assert "hunter2" not in sanitized
    assert "very-secret" not in sanitized
    assert "alice" not in sanitized
    assert "192.168.10.20" not in sanitized
    assert sanitized.count("redacted") >= 6


def test_sanitizer_redacts_cross_platform_paths_url_and_slack_token() -> None:
    # 실제 토큰처럼 보이는 고정 문자열을 저장소에 남기지 않고 필터 동작만 검증한다.
    fake_slack_token = "xox" + "b-" + "fake-token-value"
    original = (
        "/Users/alice/Game /home/bob/Game "
        f"{fake_slack_token} "
        "https://example.test/private?token=value"
    )

    sanitized = sanitize_text(original)

    assert "alice" not in sanitized
    assert "bob" not in sanitized
    assert fake_slack_token not in sanitized
    assert "example.test" not in sanitized

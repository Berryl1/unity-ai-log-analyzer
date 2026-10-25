import os
from dataclasses import dataclass
from urllib.parse import urlparse


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b"
ALLOWED_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class Settings:
    """환경변수에서 읽는 로컬 분석 및 Slack 설정의 불변 스냅샷."""
    project_name: str = "DiceAndDie"
    analyzer_mode: str = "mock"
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_timeout_seconds: float = 120.0
    llm_max_output_tokens: int = 1_500
    slack_enabled: bool = False
    slack_bot_token: str = ""
    slack_channel_id: str = ""
    slack_timeout_seconds: float = 10.0
    analysis_history_ttl_seconds: int = 3_600
    analysis_history_max_entries: int = 200

    @classmethod
    def from_environment(cls) -> "Settings":
        analyzer_mode = os.getenv("ANALYZER_MODE", "mock").strip().lower()
        if analyzer_mode not in {"mock", "local_llm"}:
            raise ValueError("ANALYZER_MODE must be 'mock' or 'local_llm'.")

        timeout = _read_float("OLLAMA_TIMEOUT_SECONDS", 120.0, 1.0, 600.0)
        max_tokens = _read_int("LLM_MAX_OUTPUT_TOKENS", 1_500, 128, 8_192)
        return cls(
            project_name=os.getenv("UNITY_PROJECT_NAME", "DiceAndDie").strip()
            or "DiceAndDie",
            analyzer_mode=analyzer_mode,
            ollama_base_url=os.getenv(
                "OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL
            ).strip().rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL).strip(),
            ollama_timeout_seconds=timeout,
            llm_max_output_tokens=max_tokens,
            slack_enabled=_read_bool("SLACK_ENABLED", False),
            slack_bot_token=os.getenv("SLACK_BOT_TOKEN", "").strip(),
            slack_channel_id=os.getenv("SLACK_CHANNEL_ID", "").strip(),
            slack_timeout_seconds=_read_float(
                "SLACK_TIMEOUT_SECONDS", 10.0, 1.0, 60.0
            ),
            analysis_history_ttl_seconds=_read_int(
                "ANALYSIS_HISTORY_TTL_SECONDS", 3_600, 60, 86_400
            ),
            analysis_history_max_entries=_read_int(
                "ANALYSIS_HISTORY_MAX_ENTRIES", 200, 10, 2_000
            ),
        )

    def validate_ollama(self) -> None:
        # 게임 로그가 의도치 않은 원격 Ollama 서버로 전송되지 않도록 loopback만 허용한다.
        parsed = urlparse(self.ollama_base_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("OLLAMA_BASE_URL must use http or https.")
        if parsed.hostname not in ALLOWED_LOOPBACK_HOSTS:
            raise ValueError(
                "OLLAMA_BASE_URL must use 127.0.0.1, localhost, or ::1. "
                "Remote Ollama connections are disabled."
            )
        if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
            raise ValueError("OLLAMA_BASE_URL must not include a path, query, or fragment.")
        if not self.ollama_model:
            raise ValueError("OLLAMA_MODEL must not be empty.")


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false.")


def _read_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as exception:
        raise ValueError(f"{name} must be a number.") from exception
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _read_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exception:
        raise ValueError(f"{name} must be an integer.") from exception
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value

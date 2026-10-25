"""Ollama와 Slack으로 전달하기 전에 로그의 대표 민감정보를 재필터링한다."""

import re


_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)\b(authorization\s*:\s*bearer|bearer)\s+[^\s,;]+"),
        r"\1 <redacted>",
    ),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|token|password|secret)"
            r"(\s*[:=]\s*)[^\s,;]+"
        ),
        r"\1\2<redacted>",
    ),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "<redacted-api-key>"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "<redacted-slack-token>"),
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "<redacted-email>",
    ),
    (
        re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+"),
        r"C:\\Users\\<redacted-user>",
    ),
    (
        re.compile(r"(?i)/Users/[^/\s]+"),
        "/Users/<redacted-user>",
    ),
    (
        re.compile(r"(?i)/home/[^/\s]+"),
        "/home/<redacted-user>",
    ),
    (
        re.compile(
            r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)"
            r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])"
        ),
        "<redacted-ip>",
    ),
    (re.compile(r"(?i)https?://[^\s<>]+"), "<redacted-url>"),
)


def sanitize_text(value: str) -> str:
    """합성 테스트로 검증한 패턴을 순서대로 치환하며 원문을 실행하지 않는다."""
    sanitized = value
    for pattern, replacement in _REPLACEMENTS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized

import re


UNITY_ASSERTION_MARKERS = (
    "assertion failed on expression",
    "testhideflag",
    "kdontsaveineditor",
)


def classify_error_source(message: str, stack_trace: str) -> str:
    """첫 관련 프레임의 영역을 분류하되 이를 근본 원인으로 단정하지 않는다."""
    normalized_message = message.casefold()
    normalized_stack = stack_trace.replace("\\", "/").casefold()

    if any(marker in normalized_message for marker in UNITY_ASSERTION_MARKERS):
        return "unity_editor"

    for line in normalized_stack.splitlines():
        if "library/packagecache/" in line or "packages/" in line:
            return "external_package"
        if re.search(r"\(at assets/.*\.cs:\d+\)", line):
            return "user_code"
        if "unityeditor." in line or "/editor/mono/" in line:
            return "unity_editor"
        if "unityengine." in line or "[native code]" in line:
            return "unity_engine"
    return "unknown"


def extract_related_location(stack_trace: str) -> str:
    """개발자가 확인할 관련 프레임을 고르고 '관련' 위치임을 명시한다."""
    lines = [
        line.strip()
        for line in stack_trace.replace("\r\n", "\n").split("\n")
        if line.strip()
    ]
    if not lines:
        return "Stack Trace에 발생 위치가 포함되지 않았습니다."

    normalized = [(line, line.replace("\\", "/").casefold()) for line in lines]
    priorities = (
        (r"\(at assets/.*\.cs:\d+\)", "관련 사용자 코드 프레임"),
        (r"(?:library/packagecache|packages)/", "관련 외부 패키지 프레임"),
        (r"unityeditor\.|/editor/mono/", "관련 Unity Editor 프레임"),
        (r"unityengine\.|\[native code\]", "관련 Unity Engine 프레임"),
    )
    for pattern, label in priorities:
        for original, candidate in normalized:
            if re.search(pattern, candidate):
                return f"{label}: {original}"
    return f"로그에서 확인된 첫 관련 프레임: {lines[0]}"


def classification_basis(category: str) -> str:
    """분류 결과가 어떤 로그 단서에 근거했는지 사용자에게 설명한다."""
    descriptions = {
        "user_code": "Stack Trace에서 Assets 아래의 사용자 C# 코드 프레임이 확인되었습니다.",
        "unity_engine": "Stack Trace에서 UnityEngine 또는 네이티브 엔진 프레임이 확인되었습니다.",
        "unity_editor": "오류 메시지 또는 Stack Trace에서 Unity Editor 관련 단서가 확인되었습니다.",
        "external_package": "Stack Trace에서 Packages 또는 Library/PackageCache 프레임이 확인되었습니다.",
        "unknown": "로그만으로 사용자 코드, Unity 또는 외부 패키지 중 발생 영역을 구분할 근거가 부족합니다.",
    }
    return descriptions[category]

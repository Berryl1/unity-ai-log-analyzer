from abc import ABC, abstractmethod
from datetime import datetime, timezone
from uuid import uuid4

from app.models import AnalyzeRequest, AnalyzeResponse
from app.log_classification import (
    classification_basis,
    classify_error_source,
    extract_related_location,
)


MOCK_DISCLAIMER = (
    "이 결과는 규칙 기반 Mock 분석이며 확정된 진단이 아닙니다. "
    "코드를 수정하기 전에 Stack Trace와 실행 상태를 직접 확인하세요."
)


class AnalyzerError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class LogAnalyzer(ABC):
    @abstractmethod
    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        """Analyze a validated, sanitized Unity error without executing its contents."""


class MockLogAnalyzer(LogAnalyzer):
    """외부 모델 없이 API와 UI 흐름을 검증할 수 있는 결정적 규칙 분석기."""

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        source_category = classify_error_source(request.message, request.stack_trace)
        probable_cause, suggested_fix, checks_required, impact_scope = (
            _recommendation_for(request)
        )
        return AnalyzeResponse(
            error_type=request.error_type,
            location=extract_related_location(request.stack_trace),
            probable_cause=probable_cause,
            suggested_fix=suggested_fix,
            checks_required=checks_required,
            impact_scope=impact_scope,
            disclaimer=MOCK_DISCLAIMER,
            is_mock=True,
            analyzed_at=datetime.now(timezone.utc),
            request_id=str(uuid4()),
            source_category=source_category,
            confidence="medium" if source_category == "user_code" else "low",
            analysis_basis=classification_basis(source_category),
        )


def _recommendation_for(request: AnalyzeRequest) -> tuple[str, str, str, str]:
    message = request.message.casefold()

    if "assertion failed on expression" in message or "testhideflag" in message:
        return (
            "Unity Editor의 객체 저장 가능 여부 또는 HideFlags 검사에서 assertion이 발생했을 가능성이 있습니다. 로그만으로 해당 객체나 호출 주체는 특정할 수 없습니다.",
            "재현 시점의 전체 Editor.log와 Stack Trace를 확보하고, 에디터 확장 코드가 임시 객체를 저장하거나 직렬화하는 경로를 점검하세요. Unity 재현 여부와 사용 버전의 알려진 문제도 함께 확인하세요.",
            "assertion 직전 작업, 전체 네이티브/관리 Stack Trace, 대상 객체의 HideFlags, 도메인 리로드 및 에셋 저장 여부가 추가로 필요합니다.",
            "게임 런타임보다 에디터 작업, 에셋 저장 또는 Inspector 표시 흐름에 영향을 줄 가능성이 있으나 현재 로그만으로 범위를 확정할 수 없습니다.",
        )

    if "nullreferenceexception" in message or "object reference" in message:
        return (
            "첫 번째 관련 Stack Trace 위치에서 참조 객체가 null일 가능성이 있습니다.",
            "해당 위치에 필요한 null 검사를 추가하고 누락된 할당 또는 초기화 경로를 수정하세요.",
            "Inspector 직렬화 참조, 객체 생명주기, 프로젝트 코드의 첫 Stack Frame을 확인하세요.",
            "해당 코드 경로의 기능 중단 또는 이후 프레임의 반복 예외가 예상됩니다.",
        )
    if "missingreferenceexception" in message:
        return (
            "UnityEngine.Object가 파괴된 뒤 관리 참조가 남아 있을 가능성이 있습니다.",
            "파괴 전에 callback과 coroutine을 해제하고 오래된 참조를 정리하세요.",
            "씬 전환, OnDestroy 정리, 지연 또는 비동기 callback을 확인하세요.",
            "씬 전환 이후 관련 UI 또는 게임 오브젝트 동작이 중단될 수 있습니다.",
        )
    if "indexoutofrangeexception" in message or "argumentoutofrangeexception" in message:
        return (
            "실행 시점의 인덱스 또는 범위가 컬렉션 크기와 맞지 않을 가능성이 있습니다.",
            "접근 지점에서 범위를 검증하고 컬렉션 구성 로직을 수정하세요.",
            "실패한 인덱스, 컬렉션 Count, 빈 컬렉션 처리 경로를 비교하세요.",
            "현재 처리 루프 또는 UI 목록 갱신이 중단될 수 있습니다.",
        )
    if "keynotfoundexception" in message:
        return (
            "등록되지 않았거나 제거된 키로 Dictionary를 조회했을 가능성이 있습니다.",
            "키 부재가 정상 흐름이면 TryGetValue를 사용하고 등록 생명주기를 수정하세요.",
            "키 문자열, 초기화 순서, 정리 시점을 확인하세요.",
            "해당 키를 사용하는 상태 복원 또는 데이터 조회가 실패할 수 있습니다.",
        )
    if "argumentexception" in message:
        return (
            "API에 전달된 인수의 값이나 형식이 요구 조건과 맞지 않을 가능성이 있습니다.",
            "예외 메시지의 parameter 이름과 관련 프레임에서 전달한 값을 확인하고 호출 전 검증을 추가하세요.",
            "전체 예외 메시지, parameter 이름, 호출 당시 입력 값과 관련 API 문서가 필요합니다.",
            "해당 API 호출 경로가 중단될 수 있으나 다른 기능으로의 영향은 추가 정보가 필요합니다.",
        )
    if any(marker in message for marker in ("filenotfound", "failed to load", "could not load", "resource")):
        return (
            "요청한 파일 또는 리소스의 경로, 포함 상태, 로드 시점 중 하나가 기대와 다를 가능성이 있습니다.",
            "실제 경로와 대소문자, 빌드 포함 설정, Addressables 또는 Resources 키와 로드 시점을 차례로 확인하세요.",
            "요청 경로, 대상 플랫폼, 파일 존재 여부, 빌드 로그와 로드 API 종류가 추가로 필요합니다.",
            "해당 리소스에 의존하는 화면이나 게임 기능이 로드되지 않을 수 있습니다.",
        )

    return (
        f"제공된 로그에서 {request.error_type}가 확인되지만 근본 원인을 특정할 정보는 부족합니다.",
        "문제를 재현하고 해당 위치 주변의 값과 제어 흐름을 확인하세요.",
        "재현 절차, 전체 Stack Trace, 최근 코드 또는 에셋 변경 사항을 확인하세요.",
        "정보가 부족하므로 영향 범위를 확정할 수 없으며 해당 호출 경로를 우선 점검해야 합니다.",
    )

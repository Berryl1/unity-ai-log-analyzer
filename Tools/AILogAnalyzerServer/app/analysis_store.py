import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.models import AnalyzeRequest, AnalyzeResponse


@dataclass(frozen=True)
class AnalysisRecord:
    request: AnalyzeRequest
    response: AnalyzeResponse
    analyzer_name: str
    model_name: str
    expires_at: datetime


class AnalysisStore:
    """Slack 전송 권한 확인용 제한된 프로세스 메모리 저장소.

    request_id가 이 저장소에 존재해야만 미리보기를 만들 수 있다. TTL과 최대 개수로
    민감한 로그가 서버 메모리에 무기한 남거나 계속 증가하는 것을 방지한다.
    """

    def __init__(self, ttl_seconds: int, max_entries: int) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_entries = max_entries
        self._records: OrderedDict[str, AnalysisRecord] = OrderedDict()
        self._lock = asyncio.Lock()

    async def save(
        self,
        request: AnalyzeRequest,
        response: AnalyzeResponse,
        analyzer_name: str,
        model_name: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        record = AnalysisRecord(
            request=request,
            response=response,
            analyzer_name=analyzer_name,
            model_name=model_name,
            expires_at=now + self._ttl,
        )
        async with self._lock:
            # 동시 분석 완료 시 OrderedDict와 용량 제한을 원자적으로 갱신한다.
            self._prune(now)
            self._records[response.request_id] = record
            self._records.move_to_end(response.request_id)
            while len(self._records) > self._max_entries:
                self._records.popitem(last=False)

    async def get(self, request_id: str) -> AnalysisRecord | None:
        now = datetime.now(timezone.utc)
        async with self._lock:
            self._prune(now)
            return self._records.get(request_id)

    def _prune(self, now: datetime) -> None:
        expired = [
            request_id
            for request_id, record in self._records.items()
            if record.expires_at <= now
        ]
        for request_id in expired:
            self._records.pop(request_id, None)

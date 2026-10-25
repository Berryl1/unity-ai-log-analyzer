import asyncio
from datetime import datetime, timezone

from app.analysis_store import AnalysisStore
from app.models import AnalyzeRequest, AnalyzeResponse


def _request() -> AnalyzeRequest:
    timestamp = datetime.now(timezone.utc)
    return AnalyzeRequest(
        error_type="Error",
        message="test",
        stack_trace="",
        occurrence_count=1,
        first_occurred_at=timestamp,
        last_occurred_at=timestamp,
    )


def _response(request_id: str) -> AnalyzeResponse:
    return AnalyzeResponse(
        error_type="Error",
        location="위치 정보 없음",
        probable_cause="추정 원인",
        suggested_fix="확인 방법",
        checks_required="추가 정보",
        impact_scope="영향 미확정",
        disclaimer="확정된 진단이 아닙니다.",
        analyzed_at=datetime.now(timezone.utc),
        request_id=request_id,
    )


def test_analysis_store_evicts_oldest_record_at_capacity() -> None:
    async def run():
        store = AnalysisStore(ttl_seconds=3_600, max_entries=2)
        request = _request()
        for request_id in ("one", "two", "three"):
            await store.save(request, _response(request_id), "Mock", "Mock")
        assert await store.get("one") is None
        assert await store.get("two") is not None
        assert await store.get("three") is not None

    asyncio.run(run())


def test_analysis_store_expires_records() -> None:
    async def run():
        store = AnalysisStore(ttl_seconds=0, max_entries=2)
        await store.save(_request(), _response("expired"), "Mock", "Mock")
        assert await store.get("expired") is None

    asyncio.run(run())

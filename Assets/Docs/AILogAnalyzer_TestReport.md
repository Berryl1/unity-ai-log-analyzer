# Unity AI Log Analyzer 5단계 테스트 결과 보고서

## 실행 기준

- 실행일: 2026-10-25
- Unity 프로젝트 버전: 6000.0.32f1
- FastAPI 버전 표기: 0.5.0
- Python 자동 테스트 실행 환경: Python 3.10.7
- 대상 권장 환경: Python 3.11 이상
- 로컬 모델: Ollama `qwen2.5-coder:7b`
- 실제 Slack 자동 전송: 수행하지 않음

상태는 `성공`, `실패`, `미검증`으로 구분한다. 이전 단계의 기록은 이번 실행 결과로 합산하지 않는다.

## 결과 요약

| 구분 | 이번 실행 결과 |
|---|---|
| Python 자동 테스트 | 성공, 56개 통과, 1개 deprecation warning |
| FastAPI 실제 프로세스 | 성공, loopback 포트 8012/8013에서 실행 |
| Mock 분석 HTTP | 성공 |
| 실제 Qwen 분석 HTTP | 성공, Assertion 사례 품질 가드 적용 후 재검증 |
| Unity C# 프로젝트 빌드 | 성공, 경고 0개, 오류 0개 |
| Unity 실제 UI 조작 | 미검증 |
| 실제 Slack TestWS 전송 | 미검증, 이번 실행에서 승인·호출하지 않음 |
| Python 3.11 실행 | 미검증, 설치 확인 실패 |
| 기존 게임 Edit/Play Mode 전체 테스트 | 미검증 |

## 세부 테스트

| 테스트 ID | 대상 | 목적 | 사전 조건 | 절차 | 기대 결과 | 실제 결과 | 상태 |
|---|---|---|---|---|---|---|---|
| PY-UNIT-001 | Mock 분석기 | 대표 예외별 보수적 안내 확인 | Python 가상환경 | Null/Missing/Index/Argument/리소스 사례 실행 | 구조화 응답과 추가 확인사항 | 관련 테스트 통과 | 성공 |
| PY-UNIT-002 | 오류 분류 | 사용자·Engine·Editor·패키지·미상 구분 | 고정 로그 10종 | `test_analysis_quality.py` 실행 | 예상 범주와 일치 | 10개 매개변수 사례 통과 | 성공 |
| PY-UNIT-003 | Assertion 품질 가드 | 내부 구현 단정 억제 | Unity HideFlags Assertion 사례 | 위험한 LLM payload에 품질 가드 적용 | low 신뢰도, 관련 프레임 표현, 안전한 확인 절차 | 조건 모두 통과 | 성공 |
| PY-UNIT-004 | 분석 저장소 | TTL·최대 개수 확인 | 메모리 저장소 | 용량 초과 및 즉시 만료 생성 | 오래된 항목 제거 | 2개 테스트 통과 | 성공 |
| API-001 | `GET /health` | 서버·Ollama 상태 확인 | Uvicorn 실행 | 실제 loopback HTTP 호출 | 200, version 0.5.0 | `status=ok`, Ollama ready | 성공 |
| API-002 | `POST /analyze` Mock | API 호환성과 JSON 확인 | Uvicorn 실행 | Assertion Mock 요청 | 200, 구조화 응답 | `unity_editor`, low, basis 반환 | 성공 |
| API-003 | 입력 검증 | 누락·범위·역순 시각 차단 | TestClient | 잘못된 payload 전송 | 422 | 자동 테스트 통과 | 성공 |
| API-004 | 요청 크기 | 384 KiB 초과 차단 | TestClient | 제한 초과 body 전송 | 413 | 자동 테스트 통과 | 성공 |
| API-005 | 클라이언트 취소 | 분석 task 정리 | 가짜 disconnect 요청 | 진행 중 분석에서 disconnect | 499 및 task 취소 | 자동 테스트 통과 | 성공 |
| API-006 | 서버 연결 실패 | Unity 측 실패 안내 | 서버 중지 필요 | Unity UI에서 요청 | 게임과 분리된 오류 표시 | 실제 Unity UI 미실행 | 미검증 |
| MOCK-001 | Mock/Qwen 구분 | 결과 혼동 방지 | 두 모드 응답 | `is_mock`, 모델 라벨 확인 | 명확히 구분 | 모델·API 테스트 통과 | 성공 |
| QWEN-001 | 상태·모델 | Ollama와 모델 확인 | 로컬 Ollama 실행 | `/health` 호출 | ready, qwen2.5-coder:7b | ready 확인 | 성공 |
| QWEN-002 | 실제 분석 | 구조화 출력과 품질 가드 확인 | Ollama 모델 로드 | Assertion을 local_llm로 실제 요청 | Pydantic 통과, 보수적 결과 | `is_mock=false`, `unity_editor`, `confidence=low`; 약 2.72초 | 성공 |
| QWEN-003 | 모델 누락·종료·timeout | 오류 코드 구분 | MockTransport | 각 오류 응답 재현 | 503/504 등 구분 | 9개 Ollama 테스트에 포함되어 통과 | 성공 |
| QWEN-004 | 실제 모델의 다양한 10개 사례 | 모델별 품질 평가 | Ollama 장시간 실행 | 고정 사례 전체 실제 추론 | 구조적 기준 평가 | Assertion 1건만 실제 추론 | 미검증 |
| UNITY-001 | Editor 코드 | C# 컴파일 확인 | 생성된 csproj | `dotnet build Assembly-CSharp-Editor.csproj` | 경고·오류 없음 | 경고 0, 오류 0 | 성공 |
| UNITY-002 | 로그 수집 | Error/Exception/Assert, 중복, 검색·필터 확인 | Unity UI 조작 | 테스트 로그와 반복 로그 생성 | 유형·횟수·상세 정상 | 이번 단계 실제 조작 안 함 | 미검증 |
| UNITY-003 | 수집 한도 | 500개/큐 2,000개/프레임 100개 확인 | Unity Editor | 대량 로그 발생 | 제한과 응답성 유지 | 상수·로직 정적 확인만 수행 | 미검증 |
| UNITY-004 | 이벤트 등록 | 재로드·Play Mode 후 중복 집계 방지 | Unity Editor | 재로드 전후 동일 로그 1회씩 발생 | 실제 횟수와 일치 | idempotent 구독 코드 확인, 실행 미검증 | 미검증 |
| UNITY-005 | 비동기 수명주기 | 창 닫기·Play Mode 전환 시 취소 | Unity Editor | 분석 중 창 닫기·모드 전환 | 결과가 다른 항목에 표시되지 않음 | 취소 코드·빌드 확인, UI 실행 미검증 | 미검증 |
| SLACK-MOCK-001 | 상태 | disabled·설정 누락·인증 실패 구분 | Fake Slack client | 상태별 호출 | 안전한 상태 메시지 | 통과 | 성공 |
| SLACK-MOCK-002 | 미리보기 | 서버 보관 request_id만 허용 | 분석 이력 | 정상·임의 ID 요청 | 정상 생성·임의 ID 거부 | 통과 | 성공 |
| SLACK-MOCK-003 | 승인 토큰 | 무작위·변조·교차 사용·만료 차단 | Fake client | 토큰 변조/재사용 | Slack 호출 없이 거부 | 통과 | 성공 |
| SLACK-MOCK-004 | 중복 | 순차·동시 요청 한 번만 전송 | 지연 Fake client | 동일 ID 동시 전송 | API 호출 1회 | 통과 | 성공 |
| SLACK-MOCK-005 | 오류 처리 | 권한·채널·rate limit·네트워크 처리 | 오류 Fake client | 각 오류 발생 | 안전한 코드·메시지, 자동 재시도 없음 | 통과 | 성공 |
| SLACK-MOCK-006 | 메모리 한도 | 미리보기·중복 상태 무한 증가 방지 | 최대 2개 설정 | 3개 생성 | 가장 오래된 상태 제거 | 통과 | 성공 |
| SLACK-REAL-001 | TestWS 전송 | 실제 인증·채널 수신 확인 | 실제 Token/Channel과 사용자 승인 | 미리보기 후 한 건 전송 | 채널 메시지 수신 | 이번 단계 수행하지 않음 | 미검증 |
| SEC-001 | Python 필터 | 이메일·경로·Bearer·키·비밀번호·Secret·IP·URL·Slack Token 제거 | 합성 데이터 | sanitizer 실행 | 원문 비밀값 제거 | 자동 테스트 통과 | 성공 |
| SEC-002 | Ollama 경계 | 필터링 후 데이터만 LLM 전달 | FastAPI 분석 요청 | sanitizer 및 요청 body 검사 | 민감정보 제거 | 서버 흐름·테스트 통과 | 성공 |
| SEC-003 | Slack payload | 재필터링·멘션·전체 Stack Trace 차단 | Fake client | preview/send payload 비교 | 민감정보·멘션 없음, 승인 내용 일치 | 자동 테스트 통과 | 성공 |
| SEC-004 | Unity 미리보기 | C# 측 필터 화면 확인 | Unity UI | 합성 민감 로그 선택 | 마스킹 표시 | C# 빌드만 확인 | 미검증 |
| SEC-005 | Token 노출 | API·소스·로그에 Token 비노출 | 합성 Token | 코드 검색 및 상태 응답 테스트 | Token 문자열 없음 | 하드코딩 없음, 응답 테스트 통과 | 성공 |
| PERF-001 | Python 회귀 | 자동 테스트 시간 확인 | Python 3.10.7 | 56개 실행 | 안정적 완료 | 최종 실행 0.92초, 경고 1개 | 성공 |
| PERF-002 | 실제 Qwen | 단일 Assertion 응답 시간 참고 | 로컬 모델 준비 | HTTP 1회 측정 | timeout 이내 | 품질 가드 재검증 요청 약 2.72초 | 성공 |
| PERF-003 | Unity 대량 로그 | Editor 응답성 측정 | Unity Profiler/UI | 2,000건 이상 발생 | 프레임 정지 최소화 | 실행하지 않음 | 미검증 |
| REG-001 | Python 전체 | 기존 1~4단계 회귀 | 가상환경 | `python -m pytest` | 전부 통과 | 56 passed | 성공 |
| REG-002 | 게임 전체 | 기존 Edit/Play Mode 회귀 | Unity Test Runner | 전체 테스트 실행 | 기존 게임 정상 | 이번 단계 실행하지 않음 | 미검증 |

## 발견 및 수정한 문제

1. Slack 승인 토큰이 메시지 해시여서 추측 가능했다. `secrets.token_urlsafe(32)` 기반 무작위 토큰으로 변경하고 변조·교차 사용·만료 테스트를 추가했다.
2. Slack 미리보기 및 중복 상태 저장소에 최대 개수 제한이 없었다. TTL과 분석 이력 한도에 맞춘 제거 로직을 추가했다.
3. Qwen이 Unity Assertion의 내부 메서드와 변수 상태를 단정할 수 있었다. 프롬프트를 강화하고 서버 측 품질 가드로 발생 영역, 위치 표현, 신뢰도와 핵심 안내를 정규화했다.
4. 첫 Stack Trace 줄이 근본 원인처럼 보일 수 있었다. 사용자 코드·Unity·패키지 관련 프레임을 분류하고 항상 `관련 ... 프레임`으로 표현하도록 변경했다.
5. URL과 독립형 Slack Token 패턴이 필터에서 누락됐다. Unity와 Python 필터에 동일 규칙을 추가했다.
6. Play Mode 전환 시 진행 요청 취소가 명시적이지 않았다. EditorWindow에서 상태 전환 이벤트를 구독해 HTTP 작업을 취소하도록 보강했다.

## 경고와 미검증 사유

- `StarletteDeprecationWarning`: 현재 FastAPI TestClient가 `httpx`를 사용하는 방식의 향후 변경 경고다. 테스트 실패나 런타임 오류는 아니며 불필요한 의존성 변경은 하지 않았다.
- Python 3.11: `py -0p`에서 설치된 Python을 찾지 못했고 현재 `python`과 가상환경은 3.10.7이었다. 시스템 Python은 사용자 승인 없이 변경하지 않았다.
- Unity UI/전체 게임 테스트: Unity 프로세스는 실행 중이었지만 자동 UI 조작이나 별도 batchmode 인스턴스를 실행하지 않았다.
- 실제 Slack: 외부 메시지 전송은 명시적 사용자 승인 없이 수행하지 않았다. 이전 단계 성공 기록은 이번 실행 결과로 계산하지 않았다.
- 성능 환경의 CPU/RAM/GPU 정보는 시스템 조회 권한이 없어 기록하지 못했다. 따라서 Qwen 시간은 이 PC의 단일 참고값이며 일반화할 수 없다.

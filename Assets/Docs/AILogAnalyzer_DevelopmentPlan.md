# Unity AI Log Analyzer 개발 계획 및 1단계 구현 기록

## 목적

Unity 에디터에서 발생한 오류를 안전하게 수집하고, 이후 로컬 FastAPI 서버와 LLM 및 Slack을 연결할 수 있는 개발 지원 도구를 구축한다. 1단계는 외부 통신 없이 Unity 에디터 안에서 오류를 수집하고 검토하는 기능만 제공한다.

## 기존 프로젝트 분석

### 구조

- `Assets/Scripts`: 게임 런타임 코드. `DiceAndDie.Runtime.asmdef`와 `DiceAndDie` 루트 네임스페이스를 사용한다.
- `Assets/Scripts/Online/Steam`: Steamworks.NET 의존 코드를 별도 `DiceAndDie.Steam.asmdef`로 분리한다.
- `Assets/Editor`: 씬/UI 생성기, 임포터, 빌드 설정 등 에디터 전용 코드가 평면 구조로 모여 있다.
- `Assets/Tests/EditMode`, `Assets/Tests/PlayMode`: NUnit 기반 테스트와 전용 asmdef를 사용한다.
- `Assets/Docs`: GDD, 개발 기록, Steam 설정 문서를 보관한다.
- `Assets/Scenes`, `Assets/Prefabs`, `Assets/Resources`, `Assets/ScriptableObjects`: 게임 콘텐츠와 설정을 용도별로 분리한다.

분석 시점에는 런타임 C# 파일 71개, Editor C# 파일 10개, Edit Mode 테스트 파일 22개, Play Mode 테스트 파일 1개가 있었다.

### 코드 규칙

- Allman 중괄호 스타일과 공백 4칸 들여쓰기를 사용한다.
- 타입과 공개 멤버는 PascalCase, private 필드는 camelCase를 사용한다.
- 기능별로 `DiceAndDie.Core`, `DiceAndDie.UI`, `DiceAndDie.Online` 등의 네임스페이스를 사용한다.
- Editor 코드는 `DiceAndDie.Editor` 네임스페이스와 `Assets/Editor` 경로를 사용한다.
- 입력값 검사, 조기 반환, 명시적인 예외 메시지를 주로 사용한다.

### 기존 Editor 확장

- `MenuItem` 기반 씬/UI 생성 및 검증 도구가 있다.
- `InitializeOnLoad` 또는 `InitializeOnLoadMethod` 기반 자동 설정 도구가 있다.
- 기존 `EditorWindow` 구현은 없으므로 AI Log Analyzer가 첫 번째 EditorWindow다.

### 주요 패키지와 의존성

- Unity 6000.0.32f1
- Universal Render Pipeline 17.0.3
- Input System 1.11.2
- Unity Test Framework 1.4.5
- TextMesh Pro 및 uGUI
- Steamworks.NET 2025.164.0

1단계 구현에는 Unity 기본 `UnityEngine`과 `UnityEditor` API만 사용하며 신규 패키지를 추가하지 않는다.

## 전체 아키텍처와 단계별 계획

```text
Unity Editor log callback
        |
        v
bounded thread-safe queue
        |
        v
deduplication / bounded in-memory store
        |
        v
AI Log Analyzer EditorWindow
        |
        |  (2단계 이후, 사용자가 선택 및 승인한 로그만 전송)
        v
localhost FastAPI -> sanitizer -> LLM provider / mock -> history
                                      |
                                      v
                              Slack Bot API
```

1. **Unity 에디터 확장**: Error, Exception, Assert 수집, 중복 집계, 검색/필터, 상세 보기, 테스트 로그, 초기화를 구현한다.
2. **로컬 자동화 서버**: FastAPI의 `/health`, `/analyze`, `/slack/send`와 검증, 타임아웃, 이력 관리를 구현한다.
3. **LLM 연결**: 공급자 인터페이스, Mock 모드, 민감정보 필터, 불확실성 표기와 구조화된 분석 응답을 구현한다.
4. **Unity-서버 통합**: 선택 로그 미리보기와 사용자 승인 후 localhost로만 전송하고 실패가 게임에 영향을 주지 않게 한다.
5. **Slack 통합**: 수동 전송, 채널 설정, 중복 알림 방지와 향후 명령 처리 확장 지점을 구현한다.

## 1단계 설계 및 구현

신규 파일은 기존 Editor 코드 배치 규칙에 맞춰 `Assets/Editor`에 추가했다. 세 파일만으로 역할을 분리할 수 있고 기존 Editor 폴더가 평면 구조이므로 새 하위 폴더와 asmdef는 만들지 않았다. 런타임 게임 코드, 씬, 프리팹, 리소스, 패키지는 변경하지 않았다.

- `AILogEntry`: 메시지, Stack Trace, 유형, 최초/최근 발생 시각, 발생 횟수를 보관하는 데이터 모델이다.
- `AILogCollector`: 창이 닫혀 있어도 에디터 세션에서 오류를 수집한다. 스레드 콜백은 큐 적재만 수행하고 실제 집계는 Editor update에서 프레임당 최대 100건씩 처리한다.
- `AILogAnalyzerWindow`: `Tools > AI Log Analyzer` 메뉴, 목록/상세 패널, 검색, 유형 필터, 테스트 로그 생성, 전체 초기화를 제공한다.

성능과 안정성을 위해 고유 오류는 최대 500개, 처리 대기 로그는 최대 2,000개로 제한한다. 대기 한도를 넘긴 로그 수는 창에 표시한다. 메시지, Stack Trace, 로그 유형이 모두 같은 경우 동일 오류로 판단해 발생 횟수와 최근 시각만 갱신한다. 가장 오래된 고유 오류부터 제거한다.

현재 기록은 에디터 도메인 메모리에만 존재하므로 스크립트 재컴파일, 도메인 재로드 또는 Unity 종료 시 초기화된다. 영구 저장은 민감 로그의 보관 정책과 함께 후속 단계에서 결정한다.

## 사용 방법

1. Unity 메뉴에서 `Tools > AI Log Analyzer`를 연다.
2. Console에 Error, Exception 또는 Assert가 발생하면 목록에서 확인한다.
3. 검색창에 메시지 또는 Stack Trace 일부를 입력하거나 유형 필터를 선택한다.
4. 목록 항목을 선택해 발생 위치, 시각, 전체 메시지와 Stack Trace를 확인한다.
5. `테스트 생성`에서 Error, Exception, Assert 중 하나를 선택해 수집을 확인한다.
6. `초기화`를 누르고 확인하면 수집 기록과 제외 건수가 모두 초기화된다.

## 검증 결과

### 실제 수행한 검증

- Unity 6000.0.32f1 Asset Pipeline이 신규 스크립트 3개를 가져왔다.
- 신규 파일이 포함된 `Assembly-CSharp-Editor.dll` C# 컴파일과 IL post-processing이 성공했다.
- 컴파일 후 Unity 도메인 재로드가 성공했고 Editor 로그에 신규 C# 컴파일 오류가 없음을 확인했다.
- 신규 패키지, 런타임 코드, 씬, 프리팹, 리소스 변경이 없음을 확인했다.

### 아직 수행하지 않은 검증

- EditorWindow 버튼 클릭, 검색/필터 표시, 중복 횟수 갱신은 실제 Unity UI에서 수동 검증하지 않았다.
- 기존 Edit Mode 및 Play Mode 전체 테스트는 이번 변경에서 실행하지 않았다.
- Python 서버, LLM, Slack은 1단계 범위가 아니므로 구현하거나 테스트하지 않았다.

수동 검증 시 같은 테스트 오류를 두 번 생성해 목록이 한 건으로 유지되고 횟수가 2가 되는지, 각 필터가 해당 유형만 표시하는지, 초기화 확인 창의 취소/삭제가 올바르게 동작하는지 확인한다.

## 보안 및 후속 고려사항

- 현재 외부 전송은 전혀 수행하지 않는다.
- 후속 단계에서도 전체 프로젝트 소스나 전체 Console을 자동 전송하지 않고 사용자가 선택하고 승인한 로그만 전송한다.
- API 키와 Slack Bot Token은 환경변수로만 읽고 저장소 파일에는 기록하지 않는다.
- 로컬 서버 전송 전 경로, 사용자명, 토큰, 이메일, IP 등 민감정보 필터를 적용한다.
- 서버 및 외부 API 오류는 Editor 도구 안에서 처리하며 게임 런타임과 분리한다.
- Slack 전송은 명시적인 버튼 동작으로만 수행하고 분석 식별자 기반 중복 방지를 적용한다.

## 2단계 구현 기록: FastAPI 및 Unity 연동

### 구현 구조

Python 서버는 게임 자산과 섞이지 않도록 새 도구 경로 `Tools/AILogAnalyzerServer`에 배치했다. 기존 프로젝트에 Python 영역이 없었기 때문에 필요한 최소 신규 폴더다.

```text
Tools/AILogAnalyzerServer
├─ app
│  ├─ main.py        # FastAPI 라우팅, 요청 크기 제한
│  ├─ models.py      # Pydantic 요청/응답 검증
│  ├─ sanitizer.py   # 서버 측 민감정보 재필터링
│  └─ analyzer.py    # 분석 인터페이스와 Mock 구현
└─ tests             # API, 분석기, 필터 테스트
```

Unity Editor 코드는 기존 `Assets/Editor` 평면 구조를 유지했다.

- `AILogAnalysisModels.cs`: Unity JSON 요청/응답 DTO와 API 결과 모델
- `AILogSensitiveDataFilter.cs`: 전송 전 민감정보 필터 및 글자 수 제한
- `AILogAnalyzerClient.cs`: `UnityWebRequest` 기반 비동기 localhost 클라이언트
- `AILogAnalyzerWindow.cs`: 서버 상태, 전송 미리보기, 사용자 승인, 진행 상태 및 분석 결과 UI 추가

기존 `AILogEntry`와 `AILogCollector`는 수정하지 않아 수집, 검색, 필터링, 중복 집계 동작을 보존했다.

### API

`GET /health`

```json
{
  "status": "ok",
  "analyzer": "mock",
  "version": "0.2.0"
}
```

`POST /analyze` 요청 예시

```json
{
  "error_type": "Exception",
  "message": "NullReferenceException: Object reference not set",
  "stack_trace": "Game.Run() (at Assets/Game.cs:42)",
  "occurrence_count": 2,
  "first_occurred_at": "2026-10-25T10:00:00+09:00",
  "last_occurred_at": "2026-10-25T10:01:00+09:00"
}
```

응답 예시

```json
{
  "error_type": "Exception",
  "location": "Game.Run() (at Assets/Game.cs:42)",
  "probable_cause": "A referenced object may be null at the first relevant stack frame.",
  "suggested_fix": "Add a targeted null guard and fix the missing assignment or initialization path.",
  "checks_required": "Inspect serialized Inspector references, object lifetime, and the first project frame.",
  "disclaimer": "This is a mock, heuristic analysis rather than a confirmed diagnosis.",
  "is_mock": true,
  "analyzed_at": "2026-10-25T12:30:05Z",
  "request_id": "generated-uuid"
}
```

### 실행 방법

Python 3.11 이상 PowerShell 환경에서 다음을 실행한다.

```powershell
cd Tools/AILogAnalyzerServer
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Unity에서 `Tools > AI Log Analyzer`를 열고 테스트 오류를 만든 뒤 항목을 선택한다. 필터링된 전송 미리보기를 검토하고 `선택한 오류 분석 요청`을 누른 다음 승인한다.

### 보안 및 안정성

- 서버 주소는 `http://127.0.0.1:8000`으로 고정했다.
- 선택 항목을 사용자가 확인하고 승인해야만 전송한다.
- Unity와 서버 양쪽에서 Bearer 값, API 키, 토큰, 비밀번호, secret, 이메일, 사용자 홈 경로, IPv4를 필터링한다.
- 메시지는 16,000자, Stack Trace는 64,000자로 제한한다.
- 전체 HTTP 요청은 384 KiB로 제한한다.
- Unity 요청 타임아웃은 10초이며 창이 닫히거나 선택이 바뀌면 진행 요청을 취소한다.
- 서버 장애와 잘못된 JSON은 EditorWindow 상태 메시지로 처리하고 게임 런타임에는 의존성을 추가하지 않는다.
- 외부 LLM과 Slack 통신은 수행하지 않는다.

### 2단계 검증 결과

실제 수행:

- Python API/분석기/입력 검증/민감정보/크기 제한 테스트 7개 통과
- Uvicorn을 `127.0.0.1:8000`에서 실제 실행
- 실제 HTTP `GET /health` 200 응답 확인
- 실제 HTTP `POST /analyze` 200 및 구조화된 Mock 응답 확인
- 응답 위치에서 Windows 사용자 경로가 마스킹되는 것 확인
- 서버 프로세스 종료 후 연결 실패 확인
- Unity 6000.0.32f1에서 신규 Editor 스크립트를 포함한 `Assembly-CSharp-Editor.dll` 컴파일 및 도메인 재로드 성공

환경 제약 및 미검증:

- 테스트 머신에는 Python 3.10.7만 설치되어 있어 Python 테스트는 3.10.7 가상환경에서 수행했다. 코드는 Python 3.11 이상을 대상으로 선언했지만 3.11 인터프리터 실행은 미검증이다.
- 실제 Unity EditorWindow에서 버튼을 눌러 요청하고 결과가 그려지는 전체 UI 흐름은 수동 검증하지 않았다.
- 기존 전체 Edit Mode/Play Mode 회귀 테스트는 실행하지 않았다.
- 설치된 FastAPI/Starlette 조합에서 TestClient의 향후 `httpx2` 전환 관련 deprecation warning 1건이 있으나 테스트 결과에는 영향을 주지 않았다.

### 3단계 예정 작업

- `LogAnalyzer` 인터페이스의 실제 LLM 구현과 공급자 설정 추가
- 환경변수 기반 API 키, 모델, 타임아웃 설정
- 구조화 출력 스키마 검증, 재시도와 rate limit 처리
- 프롬프트 인젝션 방어 및 전송 데이터 최소화 강화
- Mock/실제 공급자 전환 설정과 분석 이력 저장
- 오류 유형, 원인, 해결 방법 외에 예상 영향 범위 추가
- LLM 응답이 추정임을 유지하고 정보 부족 시 추가 확인 사항을 명시

## 3단계 구현 기록: Ollama + Qwen 로컬 LLM

### 통신 구조

```text
AI Log Analyzer EditorWindow
  -> FastAPI /analyze
     -> MockLogAnalyzer
     또는
     -> OllamaLogAnalyzer
        -> http://127.0.0.1:11434/api/tags
        -> http://127.0.0.1:11434/api/chat
        -> Pydantic 구조 검증
  -> Unity 분석 결과 UI
```

기본 분석 모드는 Mock이고 기본 모델은 `qwen2.5-coder:7b`다. Unity 요청별로 Mock 또는 Local LLM을 선택할 수 있으며, API 요청에 모드가 없으면 `ANALYZER_MODE` 환경변수 설정을 사용한다.

### Python 구현

- 기존 `LogAnalyzer`를 비동기 인터페이스로 변경했다.
- `OllamaLogAnalyzer`를 추가해 `/api/tags`로 연결과 모델 설치 상태를 확인하고 `/api/chat`으로 분석한다.
- System Prompt와 사용자 로그 JSON을 별도 메시지로 전달한다.
- 로그 내부 명령과 역할 변경 지시를 신뢰하지 않도록 System Prompt에 명시했다.
- Pydantic의 JSON Schema를 Ollama `format`에 전달하고 `stream: false`를 사용한다.
- Qwen 응답을 `LLMAnalysisPayload`로 검증한 후 기존 API 응답으로 변환한다.
- 누락 필드, 잘못된 JSON, timeout, 모델 누락, 연결 실패, 모델 로딩 및 메모리 오류를 구분한다.
- Local LLM 실패를 Mock 성공으로 바꾸지 않는다.
- 응답 필드 길이와 `num_predict`를 제한한다.
- Ollama 모델은 자동 설치하거나 다운로드하지 않는다.
- 외부 Ollama 주소는 거부하고 loopback 주소만 허용한다.

설정 환경변수:

```text
ANALYZER_MODE=mock
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5-coder:7b
OLLAMA_TIMEOUT_SECONDS=120
LLM_MAX_OUTPUT_TOKENS=1500
```

### Unity Editor 구현

- Mock / Local LLM 모드 선택
- Python 서버 연결 상태 표시
- Ollama 연결 및 모델 설치 상태 표시
- 현재 Qwen 모델 표시
- Local LLM을 고려해 분석 timeout을 135초로 확장
- 분석 중 UI 비차단 유지
- 진행 중 요청 취소 버튼
- Mock과 실제 Qwen 결과 제목 구분
- `impact_scope` 예상 영향 범위 표시
- 긴 결과는 기존 상세 스크롤 영역에서 확인

기존 로그 수집, 검색, 유형 필터, 중복 집계 및 초기화 기능은 변경하지 않았다.

### 실제 검증 결과

- Python 자동 테스트 18개 통과
- Mock 분석 정상 응답 확인
- 요청별 Local LLM 분석기 선택 확인
- Ollama `/api/chat` 요청에 `stream: false`, JSON Schema, System/User 메시지 분리 확인
- 정상 구조화 응답 파싱과 Pydantic 검증 확인
- 모델 누락, Ollama 연결 실패, timeout, 잘못된 구조 응답 처리 확인
- 클라이언트 연결 종료 시 진행 중 Python 분석 task 취소 확인
- 외부 Ollama 주소 거부 확인
- FastAPI 실제 `/health` 응답에서 Ollama 및 `qwen2.5-coder:7b` 준비 상태 확인
- 실제 `qwen2.5-coder:7b` 분석 요청 성공
- 실제 응답에서 `is_mock: false`, 한국어 분석, 예상 영향 범위 및 disclaimer 확인
- Unity 생성 C# 프로젝트의 `Assembly-CSharp-Editor` 빌드 성공, 오류 0개

제약 및 미검증:

- Python 자동 테스트는 설치 환경 제약으로 Python 3.10.7에서 실행했다. Python 3.11 이상 실행은 미검증이다.
- 실제 Unity EditorWindow 버튼으로 Qwen 분석을 요청하고 취소하는 전체 UI 흐름은 수동 검증하지 않았다.
- Unity의 기존 Edit Mode/Play Mode 전체 회귀 테스트는 실행하지 않았다.
- FastAPI TestClient의 향후 `httpx2` 전환 관련 deprecation warning 1건이 남아 있다.

### 4단계 Slack 준비

- Slack 전송 DTO는 분석 응답의 `impact_scope`, 모델명, Mock 여부를 포함해야 한다.
- 사용자가 분석 결과를 검토하고 승인한 뒤에만 `/slack/send`를 호출한다.
- 환경변수 기반 Bot Token과 Channel 설정, Slack API timeout 및 오류 처리를 추가한다.
- `request_id`를 중복 알림 방지 키로 사용할 수 있다.
- Slack 실패가 분석 결과와 Unity 게임 런타임에 영향을 주지 않도록 분리한다.

## 4단계 구현 기록: Slack Bot 수동 전송

### 아키텍처

```text
Unity 분석 결과
  -> POST /slack/preview (request_id)
     -> 서버 보관 분석 검증 -> 민감정보 재필터링 -> 고정 메시지/승인 토큰
  -> Unity 미리보기 + 사용자 승인
  -> POST /slack/send (request_id, preview_token)
     -> 중복 상태 확인 -> Slack chat.postMessage -> 결과 표시
```

`/analyze`가 성공하면 서버는 필터링된 요청과 분석 결과를 `request_id`에 연결해 메모리에 보관한다. 기본 보관 범위는 1시간·200건이다. Unity가 임의로 만든 분석 내용은 Slack 전송에 사용할 수 없고, 미리보기에서 발급한 5분 유효 토큰과 동일한 payload만 전송된다.

Slack 기능은 `app/slack_service.py`, 분석 이력은 `app/analysis_store.py`로 분리했다. API 라우팅은 기존 `app/main.py`, DTO는 `app/models.py`, 환경변수는 `app/settings.py`에 유지했다. Unity 쪽은 기존 세 파일의 역할을 확장했으며 런타임 게임 코드, 씬, 프리팹, 리소스, Unity 패키지는 변경하지 않았다.

### 환경변수와 권한

필수 Slack 환경변수는 `SLACK_ENABLED`, `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`다. `SLACK_APP_ID`는 전송 대상 식별자가 아니므로 사용하지 않는다. Token은 API 응답과 Unity UI에 반환하지 않는다. Slack 앱에는 `chat:write` Bot Token Scope만 필요하며 Bot은 대상 채널에 참여해야 한다.

Slack 설정이 없거나 비활성화된 상태에서도 기존 로그 수집, Mock 분석과 Qwen 로컬 분석은 정상 동작한다. Slack 전송 실패도 기존 분석 결과를 삭제하거나 게임 런타임에 예외를 전달하지 않는다.

### 메시지 및 안정성

- 프로젝트명, 오류 유형·위치·횟수·시각, 분석 모드·모델, 원인·해결책·확인사항·영향범위, 분석 시각, request_id와 추정 결과 안내를 전송한다.
- 원본 Stack Trace 전체는 게시하지 않는다.
- 외부 전송 직전에 민감정보를 다시 필터링한다.
- Block Kit은 사용자/LLM 문자열을 `plain_text`로 취급하고 전체 채널 멘션 및 Slack 특수 멘션을 무력화한다.
- 링크 미리보기를 비활성화하고 Slack 길이 제한에 맞게 안전하게 자른다.
- 같은 `request_id`의 순차 및 동시 재전송을 서버에서 차단한다.
- timeout이나 네트워크 단절로 결과가 불명확하면 자동 재시도하지 않는다.
- 메모리 기반 상태이므로 FastAPI 재시작 시 분석 이력과 중복 전송 상태가 초기화된다.

### 검증 결과

실제 수행:

- Python 전체 자동 테스트 32개 통과
- Slack 비활성화, 설정 누락, 인증 실패, 권한 부족, 채널 없음, rate limit, 서버 미보관 request_id 거부 검증
- Mock/Qwen 메시지 구분, 민감정보 및 `@channel`/`@here` 제거 검증
- 미리보기 문자열과 실제 `chat.postMessage` payload 일치 검증
- 순차·동시 중복 전송 차단 및 결과 불명 요청 자동 재시도 방지 검증
- 기존 Mock/Ollama/API 테스트 전체 회귀 통과
- Unity Editor C# 빌드 성공: 경고 0개, 오류 0개

미검증:

- 실제 Slack Token을 사용한 `TestWS` 인증과 실제 채널 게시
- Unity EditorWindow에서 상태 확인, 미리보기, 승인, 성공/실패 표시를 클릭하는 수동 UI 흐름
- Python 3.11 이상 실행(현재 테스트 머신의 가상환경은 Python 3.10.7)
- Unity 기존 Edit Mode/Play Mode 전체 회귀 테스트

자동 테스트는 Fake Slack client만 사용해 실제 채널에 메시지를 게시하지 않았다. 실제 전송 검증 시에는 별도 테스트 채널에서 사용자가 환경변수를 직접 설정한 뒤 한 건만 승인해 확인한다.

### 5단계 준비

- 실제 Slack 통합 수동 테스트와 캡처 가능한 운영 점검 절차
- 영구 이력 저장이 필요할 경우 암호화·보존기간·삭제 정책 설계
- Slack 명령 또는 양방향 연동은 별도 인증·서명 검증 설계 후 확장
- 최종 Unity Edit/Play Mode 회귀 테스트와 장애 시나리오 통합 검증

## 5단계 구현 기록: 최종 안정화 및 포트폴리오 정리

### 코드 검토와 최소 수정

- 기존 `/analyze` 필드를 유지하면서 `source_category`, `confidence`, `analysis_basis`를 추가했다.
- Stack Trace 파일 경로를 근본 원인으로 표현하지 않고 사용자 코드, Unity Engine, Unity Editor, 외부 패키지의 `관련 프레임`으로 표시한다.
- Qwen Prompt에 사실/추정 구분, Editor/런타임 구분, 근거·추가 정보와 프롬프트 인젝션 무시 원칙을 구체화했다.
- 실제 Unity HideFlags Assertion 추론에서 내부 메서드와 변수 상태를 과도하게 제안하는 결과를 확인해 서버 측 품질 가드를 추가했다.
- Slack 승인 토큰을 결정적 해시에서 암호학적으로 안전한 무작위 토큰으로 변경했다.
- Slack 미리보기와 중복 상태 저장소에도 TTL·최대 개수 제한을 적용했다.
- Unity/Python 필터에 URL과 독립형 Slack Token을 추가하고 macOS/Linux 경로 표현을 구분했다.
- Play Mode 전환 시 진행 중인 분석·Slack HTTP 작업을 명시적으로 취소한다.

### 5단계 실제 검증

- Python 3.10.7 자동 테스트 56개 통과, 최종 실행 시간 0.92초
- FastAPI 0.5.0을 loopback에서 실제 실행하고 `/health`, `/slack/status`, Mock `/analyze` 확인
- 실제 `qwen2.5-coder:7b`로 Unity Assertion 분석 성공
- 품질 가드 적용 후 `source_category=unity_editor`, `confidence=low`, 내부 메서드 수정 제안 제거 및 런타임 영향 미확정 안내 확인
- Unity Editor C# 프로젝트 빌드 경고 0개, 오류 0개
- Unity Editor.log에서 Tundra 스크립트 빌드 성공 확인
- 실제 Slack API는 호출하지 않고 Fake client 테스트만 실행

### 미검증과 제한

- Python 3.11은 설치되어 있지 않아 실환경 테스트를 수행하지 않았다.
- Unity UI 클릭, 대량 로그 응답성, 이벤트 중복 등록 및 전체 Edit/Play Mode 회귀 테스트는 수행하지 않았다.
- 이전 단계에 실제 TestWS 전송 성공 기록이 있으나 이번 단계에서는 사용자 승인 없이 재전송하지 않았다.
- 메모리 기반 분석·Slack 상태는 FastAPI 재시작 시 초기화된다.
- Qwen 응답은 품질 가드를 거쳐도 추정이며 실제 소스와 재현 상태를 대신하지 않는다.

상세 테스트 결과는 `AILogAnalyzer_TestReport.md`, 포트폴리오 설명과 촬영 가이드는 `AILogAnalyzer_Portfolio.md`, 설치·API·아키텍처는 `Tools/AILogAnalyzerServer/README.md`에 기록했다.

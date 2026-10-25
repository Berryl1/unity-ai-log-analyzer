# Unity AI Log Analyzer

Unity 6 프로젝트에서 Error, Exception, Assert 로그를 수집하고 로컬 Qwen 모델로 분석한 뒤, 사용자가 승인한 결과만 Slack에 공유하는 개발 지원 도구입니다.

이 저장소는 DiceAndDie 게임 전체가 아니라 AI Log Analyzer 포트폴리오 관련 파일만 포함합니다. 게임 런타임 코드, 씬, 프리팹과 리소스는 포함하지 않습니다.

## 주요 기능

- Unity EditorWindow 기반 오류 수집, 검색, 유형 필터와 중복 집계
- 전송 전 민감정보 마스킹 및 사용자 승인
- FastAPI 기반 localhost 분석 서버
- Mock 분석 및 Ollama `qwen2.5-coder:7b` 구조화 분석
- 사실과 추정을 구분하는 결과 검증 및 품질 가드
- 미리보기와 재승인을 거치는 Slack Bot 전송
- 승인 토큰, timeout, 취소 및 중복 전송 방지

## 저장소 구조

```text
Assets/
├─ Editor/                 # Unity AI Log Analyzer Editor 확장
└─ Docs/                   # 개발 기록, 테스트 보고서, 포트폴리오 문서
Tools/
└─ AILogAnalyzerServer/    # FastAPI, Ollama, Slack 연동 및 Python 테스트
```

## 문서

- [서버 설치·실행 및 API 문서](Tools/AILogAnalyzerServer/README.md)
- [개발 계획 및 단계별 구현 기록](Assets/Docs/AILogAnalyzer_DevelopmentPlan.md)
- [최종 테스트 결과](Assets/Docs/AILogAnalyzer_TestReport.md)
- [포트폴리오 설명 및 스크린샷](Assets/Docs/AILogAnalyzer_Portfolio.md)

## 빠른 실행

Python 3.11 이상과 Ollama를 준비한 뒤 실행합니다.

```powershell
cd Tools/AILogAnalyzerServer
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
ollama pull qwen2.5-coder:7b
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Unity 프로젝트에서는 `Assets/Editor`의 `AILog*.cs`와 `.meta` 파일을 복사한 뒤 `Tools > AI Log Analyzer`를 엽니다. 자세한 설정과 Slack 환경변수는 서버 README를 참고하세요.

## 보안 원칙

- 실제 API Key와 Slack Bot Token은 소스에 저장하지 않습니다.
- `.env`, Python 가상환경과 Unity 생성 파일은 Git에서 제외합니다.
- 전체 프로젝트 소스나 Console 로그를 자동으로 LLM 또는 Slack에 전송하지 않습니다.
- Slack 전송은 미리보기 확인과 명시적인 사용자 승인이 필요합니다.
- AI 분석 결과는 추정이며 확정된 진단이 아닙니다.

## 현재 검증 범위

- Python 자동 테스트 56개 통과
- Unity Editor C# 빌드 경고 0개, 오류 0개
- 실제 로컬 Qwen 구조화 분석 확인
- Slack 자동 테스트는 Fake client를 사용하며 실제 채널에는 메시지를 보내지 않음

Python 3.11, 실제 Unity UI 및 실제 Slack 전송의 최신 검증 여부는 테스트 보고서에서 성공·미검증으로 구분합니다.

using System;
using System.Threading;
using UnityEditor;
using UnityEngine;

namespace DiceAndDie.Editor
{
    /// <summary>
    /// 수집된 오류 검토, 로컬 분석 승인, Slack 미리보기와 최종 전송 승인을 제공하는 EditorWindow입니다.
    /// </summary>
    public sealed class AILogAnalyzerWindow : EditorWindow
    {
        private const float MinimumListWidth = 280f;
        private const float ListWidthRatio = 0.45f;
        private const int MaximumSummaryLength = 100;

        private readonly GUIContent clearContent = new GUIContent("초기화");
        private readonly GUIContent testContent = new GUIContent("테스트 생성");
        private Vector2 listScrollPosition;
        private Vector2 detailScrollPosition;
        private string searchText = string.Empty;
        private string selectedEntryKey;
        private LogFilter logFilter;
        private AnalysisMode analysisMode;
        private ServerConnectionState serverConnectionState;
        private string serverStatusMessage = "연결 상태를 확인하지 않았습니다.";
        private string ollamaStatusMessage = "Ollama 상태를 확인하지 않았습니다.";
        private string ollamaModel = "qwen2.5-coder:7b";
        private bool isOllamaReady;
        private bool isAnalyzing;
        private string analysisStatusMessage = string.Empty;
        private AILogAnalysisResponse analysisResponse;
        private AILogTransmissionPreview transmissionPreview;
        private CancellationTokenSource healthCancellation;
        private CancellationTokenSource analysisCancellation;
        private CancellationTokenSource slackStatusCancellation;
        private CancellationTokenSource slackActionCancellation;
        private bool isSlackReady;
        private bool isSlackBusy;
        private string slackChannelId = string.Empty;
        private string slackStatusMessage = "Slack 상태를 확인하지 않았습니다.";
        private string slackActionMessage = string.Empty;
        private string slackSentRequestId = string.Empty;
        private AILogSlackPreviewResponse slackPreview;

        [MenuItem("Tools/AI Log Analyzer")]
        public static void Open()
        {
            var window = GetWindow<AILogAnalyzerWindow>();
            window.titleContent = new GUIContent("AI Log Analyzer");
            window.minSize = new Vector2(760f, 440f);
            window.Show();
        }

        private void OnEnable()
        {
            // 도메인 리로드 후에도 수집은 한 번만 구독하고, 창 수명에 속한 비동기 상태를 다시 확인합니다.
            AILogCollector.EnsureListening();
            AILogCollector.Changed -= Repaint;
            AILogCollector.Changed += Repaint;
            EditorApplication.playModeStateChanged -= HandlePlayModeStateChanged;
            EditorApplication.playModeStateChanged += HandlePlayModeStateChanged;
            CheckServerHealth();
            CheckSlackStatus();
        }

        private void OnDisable()
        {
            AILogCollector.Changed -= Repaint;
            EditorApplication.playModeStateChanged -= HandlePlayModeStateChanged;
            EditorApplication.delayCall -= CompleteTestLogCapture;
            CancelAndDispose(ref healthCancellation);
            CancelAndDispose(ref analysisCancellation);
            CancelAndDispose(ref slackStatusCancellation);
            CancelAndDispose(ref slackActionCancellation);
        }

        private void OnGUI()
        {
            DrawToolbar();
            DrawStatus();
            DrawServerStatus();
            DrawSlackStatus();

            EditorGUILayout.BeginHorizontal();
            DrawLogList();
            DrawDetails();
            EditorGUILayout.EndHorizontal();
        }

        private void DrawToolbar()
        {
            EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);

            string nextSearchText = GUILayout.TextField(
                searchText,
                EditorStyles.toolbarSearchField,
                GUILayout.MinWidth(180f));
            if (!string.Equals(searchText, nextSearchText, StringComparison.Ordinal))
            {
                searchText = nextSearchText;
                listScrollPosition = Vector2.zero;
            }

            logFilter = (LogFilter)EditorGUILayout.EnumPopup(
                logFilter,
                EditorStyles.toolbarPopup,
                GUILayout.Width(100f));

            if (GUILayout.Button(testContent, EditorStyles.toolbarDropDown, GUILayout.Width(90f)))
            {
                ShowTestLogMenu();
            }

            if (GUILayout.Button(clearContent, EditorStyles.toolbarButton, GUILayout.Width(60f)) &&
                EditorUtility.DisplayDialog(
                    "AI Log Analyzer",
                    "수집된 오류 기록을 모두 삭제하시겠습니까?",
                    "삭제",
                    "취소"))
            {
                selectedEntryKey = null;
                ResetAnalysis();
                AILogCollector.Clear();
            }

            EditorGUILayout.EndHorizontal();
        }

        private void DrawStatus()
        {
            int visibleCount = CountVisibleEntries();
            string status = $"표시 {visibleCount} / 고유 오류 {AILogCollector.Entries.Count}";

            if (AILogCollector.DroppedLogCount > 0)
            {
                status += $"  |  처리 한도 초과로 제외 {AILogCollector.DroppedLogCount}";
            }

            EditorGUILayout.HelpBox(
                status + $"  |  최대 {AILogCollector.MaximumUniqueLogCount}개 보관",
                AILogCollector.DroppedLogCount > 0 ? MessageType.Warning : MessageType.Info);
        }

        private void DrawServerStatus()
        {
            EditorGUILayout.BeginVertical();
            EditorGUILayout.BeginHorizontal();
            MessageType messageType = serverConnectionState == ServerConnectionState.Online
                ? MessageType.Info
                : serverConnectionState == ServerConnectionState.Offline
                    ? MessageType.Warning
                    : MessageType.None;
            EditorGUILayout.HelpBox(
                $"Python 서버: {serverStatusMessage} ({AILogAnalyzerClient.BaseUrl})",
                messageType);

            bool wasEnabled = GUI.enabled;
            GUI.enabled = serverConnectionState != ServerConnectionState.Checking;
            if (GUILayout.Button("연결 확인", GUILayout.Width(90f), GUILayout.Height(38f)))
            {
                CheckServerHealth();
            }

            GUI.enabled = wasEnabled;
            EditorGUILayout.EndHorizontal();

            EditorGUILayout.BeginHorizontal();
            EditorGUILayout.LabelField("분석 모드", GUILayout.Width(70f));
            GUI.enabled = !isAnalyzing;
            AnalysisMode nextMode = (AnalysisMode)EditorGUILayout.EnumPopup(
                analysisMode,
                GUILayout.Width(110f));
            GUI.enabled = wasEnabled;
            if (nextMode != analysisMode)
            {
                analysisMode = nextMode;
                ResetAnalysis();
            }

            EditorGUILayout.LabelField($"Qwen 모델: {ollamaModel}");
            EditorGUILayout.EndHorizontal();
            EditorGUILayout.HelpBox(
                $"Ollama: {ollamaStatusMessage}",
                isOllamaReady ? MessageType.Info : MessageType.Warning);
            EditorGUILayout.EndVertical();
        }

        private void DrawLogList()
        {
            float listWidth = Mathf.Max(MinimumListWidth, position.width * ListWidthRatio);
            EditorGUILayout.BeginVertical(GUILayout.Width(listWidth));
            EditorGUILayout.LabelField("오류 목록", EditorStyles.boldLabel);
            listScrollPosition = EditorGUILayout.BeginScrollView(listScrollPosition);

            bool hasVisibleEntry = false;
            for (int index = AILogCollector.Entries.Count - 1; index >= 0; index--)
            {
                AILogEntry entry = AILogCollector.Entries[index];
                if (!IsVisible(entry))
                {
                    continue;
                }

                hasVisibleEntry = true;
                DrawLogRow(entry);
            }

            if (!hasVisibleEntry)
            {
                EditorGUILayout.HelpBox(
                    "조건에 맞는 오류가 없습니다. '테스트 생성'으로 수집 동작을 확인할 수 있습니다.",
                    MessageType.None);
            }

            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        private void DrawSlackStatus()
        {
            EditorGUILayout.BeginHorizontal();
            EditorGUILayout.HelpBox(
                $"Slack: {slackStatusMessage}" +
                (string.IsNullOrWhiteSpace(slackChannelId) ? string.Empty : $" / 채널 {slackChannelId}"),
                isSlackReady ? MessageType.Info : MessageType.Warning);

            bool wasEnabled = GUI.enabled;
            GUI.enabled = slackStatusCancellation == null && !isSlackBusy;
            if (GUILayout.Button("Slack 상태 확인", GUILayout.Width(105f), GUILayout.Height(38f)))
            {
                CheckSlackStatus();
            }

            GUI.enabled = wasEnabled;
            EditorGUILayout.EndHorizontal();
        }

        private void DrawLogRow(AILogEntry entry)
        {
            string key = CreateEntryKey(entry);
            Color previousColor = GUI.backgroundColor;
            if (string.Equals(selectedEntryKey, key, StringComparison.Ordinal))
            {
                GUI.backgroundColor = new Color(0.45f, 0.7f, 1f);
            }

            string summary = GetSummary(entry.Message);
            string label = $"[{GetTypeLabel(entry.LogType)}] x{entry.OccurrenceCount}  {summary}";
            if (GUILayout.Button(label, EditorStyles.miniButton, GUILayout.Height(28f)))
            {
                selectedEntryKey = key;
                detailScrollPosition = Vector2.zero;
                ResetAnalysis();
                transmissionPreview = AILogSensitiveDataFilter.CreatePreview(entry);
            }

            GUI.backgroundColor = previousColor;
        }

        private void DrawDetails()
        {
            EditorGUILayout.BeginVertical(GUILayout.ExpandWidth(true));
            EditorGUILayout.LabelField("상세 정보", EditorStyles.boldLabel);

            AILogEntry selectedEntry = FindSelectedEntry();
            if (selectedEntry == null)
            {
                EditorGUILayout.HelpBox("목록에서 오류를 선택하세요.", MessageType.Info);
                EditorGUILayout.EndVertical();
                return;
            }

            detailScrollPosition = EditorGUILayout.BeginScrollView(detailScrollPosition);
            DrawReadOnlyField("오류 유형", GetTypeLabel(selectedEntry.LogType));
            DrawReadOnlyField("발생 횟수", selectedEntry.OccurrenceCount.ToString());
            DrawReadOnlyField("최초 발생", FormatTimestamp(selectedEntry.FirstOccurredAt));
            DrawReadOnlyField("최근 발생", FormatTimestamp(selectedEntry.LastOccurredAt));
            DrawReadOnlyField("오류 발생 위치", selectedEntry.Location);

            EditorGUILayout.Space(6f);
            EditorGUILayout.LabelField("오류 메시지", EditorStyles.boldLabel);
            EditorGUILayout.TextArea(selectedEntry.Message, GUILayout.MinHeight(70f));

            EditorGUILayout.Space(6f);
            EditorGUILayout.LabelField("Stack Trace", EditorStyles.boldLabel);
            EditorGUILayout.TextArea(selectedEntry.StackTrace, GUILayout.MinHeight(180f));
            DrawAnalysisPanel(selectedEntry);
            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        private void DrawAnalysisPanel(AILogEntry selectedEntry)
        {
            if (transmissionPreview == null)
            {
                // 원본 로그가 아니라 필터링된 사본만 승인 화면과 HTTP 요청에 사용합니다.
                transmissionPreview = AILogSensitiveDataFilter.CreatePreview(selectedEntry);
            }

            EditorGUILayout.Space(12f);
            EditorGUILayout.LabelField("서버 전송 미리보기", EditorStyles.boldLabel);
            EditorGUILayout.HelpBox(
                "아래 내용만 127.0.0.1 서버로 전송됩니다. 사용자 경로, 이메일, IP, API 키와 토큰 형식은 마스킹됩니다.",
                MessageType.Warning);
            EditorGUILayout.LabelField("필터링된 오류 메시지", EditorStyles.miniBoldLabel);
            EditorGUILayout.TextArea(transmissionPreview.Message, GUILayout.MinHeight(60f));
            EditorGUILayout.LabelField("필터링된 Stack Trace", EditorStyles.miniBoldLabel);
            EditorGUILayout.TextArea(transmissionPreview.StackTrace, GUILayout.MinHeight(100f));

            bool wasEnabled = GUI.enabled;
            EditorGUILayout.BeginHorizontal();
            GUI.enabled = !isAnalyzing;
            string requestLabel = analysisMode == AnalysisMode.Mock
                ? "Mock 분석 요청"
                : "Qwen 로컬 LLM 분석 요청";
            if (GUILayout.Button(isAnalyzing ? "분석 요청 중..." : requestLabel, GUILayout.Height(30f)))
            {
                RequestAnalysis(selectedEntry);
            }

            GUI.enabled = isAnalyzing;
            if (GUILayout.Button("분석 취소", GUILayout.Width(85f), GUILayout.Height(30f)))
            {
                CancelAnalysis();
            }

            GUI.enabled = wasEnabled;
            EditorGUILayout.EndHorizontal();

            if (isAnalyzing)
            {
                Rect progressRect = EditorGUILayout.GetControlRect(false, 20f);
                string progressLabel = analysisMode == AnalysisMode.Mock
                    ? "Mock 분석 결과를 기다리는 중"
                    : "Qwen 로컬 분석 결과를 기다리는 중";
                EditorGUI.ProgressBar(progressRect, 0.5f, progressLabel);
            }

            if (!string.IsNullOrWhiteSpace(analysisStatusMessage))
            {
                EditorGUILayout.HelpBox(
                    analysisStatusMessage,
                    analysisResponse == null ? MessageType.Error : MessageType.Info);
            }

            if (analysisResponse != null)
            {
                DrawAnalysisResult(analysisResponse);
                DrawSlackPanel();
            }
        }

        private void DrawSlackPanel()
        {
            EditorGUILayout.Space(12f);
            EditorGUILayout.LabelField("Slack 전송", EditorStyles.boldLabel);
            EditorGUILayout.HelpBox(
                "Slack은 외부 서비스입니다. 아래 미리보기를 확인하고 명시적으로 승인한 경우에만 전송됩니다.",
                MessageType.Warning);

            bool alreadySent = string.Equals(
                slackSentRequestId,
                analysisResponse.request_id,
                StringComparison.Ordinal);
            bool wasEnabled = GUI.enabled;
            GUI.enabled = isSlackReady && !isSlackBusy && !alreadySent;
            if (GUILayout.Button(
                    isSlackBusy ? "Slack 처리 중..." : "Slack 메시지 미리보기 생성",
                    GUILayout.Height(28f)))
            {
                RequestSlackPreview();
            }

            GUI.enabled = wasEnabled;

            if (slackPreview != null && string.Equals(
                    slackPreview.request_id,
                    analysisResponse.request_id,
                    StringComparison.Ordinal))
            {
                DrawReadOnlyField("대상 채널", slackPreview.channel_id);
                EditorGUILayout.LabelField("실제 전송 메시지", EditorStyles.miniBoldLabel);
                EditorGUILayout.TextArea(slackPreview.preview_text, GUILayout.MinHeight(180f));

                GUI.enabled = isSlackReady && !isSlackBusy && !alreadySent;
                if (GUILayout.Button("확인한 내용 Slack으로 전송", GUILayout.Height(30f)))
                {
                    ConfirmAndSendToSlack();
                }

                GUI.enabled = wasEnabled;
            }

            if (!string.IsNullOrWhiteSpace(slackActionMessage))
            {
                EditorGUILayout.HelpBox(
                    slackActionMessage,
                    alreadySent ? MessageType.Info : MessageType.Warning);
            }
        }

        private static void DrawAnalysisResult(AILogAnalysisResponse response)
        {
            EditorGUILayout.Space(8f);
            EditorGUILayout.LabelField(
                response.is_mock ? "Mock AI 분석 결과" : "AI 분석 결과",
                EditorStyles.boldLabel);
            DrawReadOnlyField("오류 유형", response.error_type);
            DrawReadOnlyField("발생 영역", GetSourceCategoryLabel(response.source_category));
            DrawReadOnlyField("분석 신뢰도", GetConfidenceLabel(response.confidence));
            DrawReadOnlyField("발생 위치", response.location);
            DrawResultText("분석 근거", response.analysis_basis);
            DrawResultText("예상 원인", response.probable_cause);
            DrawResultText("해결 방법 제안", response.suggested_fix);
            DrawResultText("확인 필요 사항", response.checks_required);
            DrawResultText("예상 영향 범위", response.impact_scope);
            EditorGUILayout.HelpBox(response.disclaimer, MessageType.Warning);
            DrawReadOnlyField("분석 시각", FormatTimestamp(response.analyzed_at));
            DrawReadOnlyField("요청 ID", response.request_id);
        }

        private static void DrawResultText(string label, string value)
        {
            EditorGUILayout.LabelField(label, EditorStyles.miniBoldLabel);
            EditorGUILayout.TextArea(value ?? string.Empty, GUILayout.MinHeight(44f));
        }

        private async void CheckServerHealth()
        {
            CancelAndDispose(ref healthCancellation);
            healthCancellation = new CancellationTokenSource();
            CancellationTokenSource currentCancellation = healthCancellation;
            serverConnectionState = ServerConnectionState.Checking;
            serverStatusMessage = "확인 중...";
            Repaint();

            try
            {
                AILogApiResult<AILogHealthResponse> result =
                    await AILogAnalyzerClient.CheckHealthAsync(currentCancellation.Token);
                if (this == null || currentCancellation.IsCancellationRequested)
                {
                    return;
                }

                serverConnectionState = result.Success
                    ? ServerConnectionState.Online
                    : ServerConnectionState.Offline;
                serverStatusMessage = result.Success
                    ? $"연결됨 / {result.Value.analyzer} / v{result.Value.version}"
                    : result.ErrorMessage;
                if (result.Success)
                {
                    ollamaModel = result.Value.ollama_model;
                    ollamaStatusMessage = result.Value.ollama_message;
                    isOllamaReady = string.Equals(
                        result.Value.ollama_status,
                        "ready",
                        StringComparison.OrdinalIgnoreCase);
                }
                else
                {
                    ollamaStatusMessage = "Python 서버에 연결할 수 없어 확인하지 못했습니다.";
                    isOllamaReady = false;
                }
            }
            catch (OperationCanceledException)
            {
                return;
            }
            finally
            {
                if (ReferenceEquals(healthCancellation, currentCancellation))
                {
                    healthCancellation.Dispose();
                    healthCancellation = null;
                }

                if (this != null)
                {
                    Repaint();
                }
            }
        }

        private async void RequestAnalysis(AILogEntry selectedEntry)
        {
            if (selectedEntry == null || transmissionPreview == null)
            {
                return;
            }

            // 자동 전송을 금지하고 사용자가 현재 미리보기를 확인한 경우에만 요청합니다.
            bool approved = EditorUtility.DisplayDialog(
                "분석 요청 승인",
                "미리보기에 표시된 필터링 로그를 로컬 Python 서버로 전송하시겠습니까?",
                "전송 및 분석",
                "취소");
            if (!approved)
            {
                return;
            }

            CancelAndDispose(ref analysisCancellation);
            analysisCancellation = new CancellationTokenSource();
            CancellationTokenSource currentCancellation = analysisCancellation;
            string analyzerMode = analysisMode == AnalysisMode.Mock ? "mock" : "local_llm";
            var request = new AILogAnalysisRequest(
                selectedEntry,
                transmissionPreview,
                analyzerMode);
            isAnalyzing = true;
            analysisResponse = null;
            analysisStatusMessage = string.Empty;
            Repaint();

            try
            {
                AILogApiResult<AILogAnalysisResponse> result =
                    await AILogAnalyzerClient.AnalyzeAsync(request, currentCancellation.Token);
                // 선택 변경이나 창 종료로 취소된 이전 응답이 새 화면에 표시되지 않게 합니다.
                if (this == null || currentCancellation.IsCancellationRequested)
                {
                    return;
                }

                if (result.Success)
                {
                    analysisResponse = result.Value;
                    ResetSlackDelivery();
                    analysisStatusMessage = result.Value.is_mock
                        ? "Mock 분석이 완료되었습니다."
                        : $"Qwen 로컬 분석이 완료되었습니다. ({ollamaModel})";
                    serverConnectionState = ServerConnectionState.Online;
                    serverStatusMessage = "연결됨";
                }
                else
                {
                    analysisStatusMessage = result.ErrorMessage;
                    if (result.StatusCode == 0)
                    {
                        serverConnectionState = ServerConnectionState.Offline;
                        serverStatusMessage = result.ErrorMessage;
                    }
                }
            }
            catch (OperationCanceledException)
            {
                return;
            }
            finally
            {
                if (ReferenceEquals(analysisCancellation, currentCancellation))
                {
                    analysisCancellation.Dispose();
                    analysisCancellation = null;
                    isAnalyzing = false;
                }

                if (this != null)
                {
                    Repaint();
                }
            }
        }

        private void ResetAnalysis()
        {
            CancelAndDispose(ref analysisCancellation);
            isAnalyzing = false;
            analysisStatusMessage = string.Empty;
            analysisResponse = null;
            transmissionPreview = null;
            ResetSlackDelivery();
        }

        private async void CheckSlackStatus()
        {
            CancelAndDispose(ref slackStatusCancellation);
            slackStatusCancellation = new CancellationTokenSource();
            CancellationTokenSource currentCancellation = slackStatusCancellation;
            slackStatusMessage = "확인 중...";
            Repaint();

            try
            {
                AILogApiResult<AILogSlackStatusResponse> result =
                    await AILogAnalyzerClient.CheckSlackStatusAsync(currentCancellation.Token);
                if (this == null || currentCancellation.IsCancellationRequested)
                {
                    return;
                }

                isSlackReady = result.Success && result.Value.IsReady();
                slackStatusMessage = result.Success
                    ? result.Value.status_message
                    : result.ErrorMessage;
                slackChannelId = result.Success ? result.Value.channel_id : string.Empty;
            }
            catch (OperationCanceledException)
            {
                return;
            }
            finally
            {
                if (ReferenceEquals(slackStatusCancellation, currentCancellation))
                {
                    slackStatusCancellation.Dispose();
                    slackStatusCancellation = null;
                }

                if (this != null)
                {
                    Repaint();
                }
            }
        }

        private async void RequestSlackPreview()
        {
            if (analysisResponse == null || !isSlackReady || isSlackBusy)
            {
                return;
            }

            // 서버가 보관 중인 request_id를 사용해 Unity가 Slack 내용을 임의 구성하지 못하게 합니다.
            string requestId = analysisResponse.request_id;
            CancelAndDispose(ref slackActionCancellation);
            slackActionCancellation = new CancellationTokenSource();
            CancellationTokenSource currentCancellation = slackActionCancellation;
            isSlackBusy = true;
            slackPreview = null;
            slackActionMessage = "Slack 메시지 미리보기를 생성하는 중입니다.";
            Repaint();

            try
            {
                AILogApiResult<AILogSlackPreviewResponse> result =
                    await AILogAnalyzerClient.CreateSlackPreviewAsync(
                        requestId,
                        currentCancellation.Token);
                if (this == null || currentCancellation.IsCancellationRequested ||
                    analysisResponse == null ||
                    !string.Equals(analysisResponse.request_id, requestId, StringComparison.Ordinal))
                {
                    return;
                }

                slackPreview = result.Success ? result.Value : null;
                slackActionMessage = result.Success
                    ? "미리보기를 확인한 뒤 전송 버튼을 누르세요. 미리보기는 5분간 유효합니다."
                    : result.ErrorMessage;
            }
            catch (OperationCanceledException)
            {
                return;
            }
            finally
            {
                FinishSlackAction(currentCancellation);
            }
        }

        private void ConfirmAndSendToSlack()
        {
            if (slackPreview == null || analysisResponse == null)
            {
                return;
            }

            // 미리보기 생성과 실제 외부 전송 승인을 별도 동작으로 분리합니다.
            bool approved = EditorUtility.DisplayDialog(
                "Slack 전송 승인",
                $"미리보기에 표시된 분석 결과를 채널 {slackPreview.channel_id}에 전송하시겠습니까?\n\n" +
                "Slack은 외부 서비스이며, 전송 후에는 메시지가 워크스페이스에 보관됩니다.",
                "승인 및 전송",
                "취소");
            if (approved)
            {
                SendToSlack();
            }
        }

        private async void SendToSlack()
        {
            // preview_token은 서버가 표시한 고정 payload를 승인했다는 단기 증표입니다.
            string requestId = analysisResponse.request_id;
            string previewToken = slackPreview.preview_token;
            CancelAndDispose(ref slackActionCancellation);
            slackActionCancellation = new CancellationTokenSource();
            CancellationTokenSource currentCancellation = slackActionCancellation;
            isSlackBusy = true;
            slackActionMessage = "Slack으로 전송하는 중입니다.";
            Repaint();

            try
            {
                AILogApiResult<AILogSlackSendResponse> result =
                    await AILogAnalyzerClient.SendToSlackAsync(
                        requestId,
                        previewToken,
                        currentCancellation.Token);
                if (this == null || currentCancellation.IsCancellationRequested ||
                    analysisResponse == null ||
                    !string.Equals(analysisResponse.request_id, requestId, StringComparison.Ordinal))
                {
                    return;
                }

                if (result.Success && result.Value.success)
                {
                    slackSentRequestId = requestId;
                    slackActionMessage = result.Value.status_message;
                    slackPreview = null;
                }
                else
                {
                    slackActionMessage = result.Success
                        ? result.Value.status_message
                        : result.ErrorMessage;
                }
            }
            catch (OperationCanceledException)
            {
                return;
            }
            finally
            {
                FinishSlackAction(currentCancellation);
            }
        }

        private void FinishSlackAction(CancellationTokenSource currentCancellation)
        {
            if (ReferenceEquals(slackActionCancellation, currentCancellation))
            {
                slackActionCancellation.Dispose();
                slackActionCancellation = null;
                isSlackBusy = false;
            }

            if (this != null)
            {
                Repaint();
            }
        }

        private void ResetSlackDelivery()
        {
            CancelAndDispose(ref slackActionCancellation);
            isSlackBusy = false;
            slackPreview = null;
            slackActionMessage = string.Empty;
            slackSentRequestId = string.Empty;
        }

        private void HandlePlayModeStateChanged(PlayModeStateChange state)
        {
            if (state != PlayModeStateChange.ExitingEditMode &&
                state != PlayModeStateChange.ExitingPlayMode)
            {
                return;
            }

            // 도메인 리로드 여부와 관계없이 전환 직전에 진행 중인 HTTP 작업을 명시적으로 끝냅니다.
            bool cancelledAnalysis = isAnalyzing;
            bool cancelledSlack = isSlackBusy;
            CancelAndDispose(ref healthCancellation);
            CancelAndDispose(ref analysisCancellation);
            CancelAndDispose(ref slackStatusCancellation);
            CancelAndDispose(ref slackActionCancellation);
            isAnalyzing = false;
            isSlackBusy = false;
            if (cancelledAnalysis)
            {
                analysisStatusMessage = "Play Mode 전환으로 진행 중인 분석 요청을 취소했습니다.";
            }

            if (cancelledSlack)
            {
                slackActionMessage = "Play Mode 전환으로 진행 중인 Slack 요청을 취소했습니다.";
            }
            Repaint();
        }

        private void CancelAnalysis()
        {
            if (!isAnalyzing)
            {
                return;
            }

            CancelAndDispose(ref analysisCancellation);
            isAnalyzing = false;
            analysisResponse = null;
            analysisStatusMessage = "사용자가 분석 요청을 취소했습니다.";
            Repaint();
        }

        private static void CancelAndDispose(ref CancellationTokenSource cancellation)
        {
            if (cancellation == null)
            {
                return;
            }

            cancellation.Cancel();
            cancellation.Dispose();
            cancellation = null;
        }

        private void ShowTestLogMenu()
        {
            var menu = new GenericMenu();
            menu.AddItem(
                new GUIContent("Error"),
                false,
                () => GenerateTestLog(LogType.Error));
            menu.AddItem(
                new GUIContent("Exception"),
                false,
                () => GenerateTestLog(LogType.Exception));
            menu.AddItem(
                new GUIContent("Assert"),
                false,
                () => GenerateTestLog(LogType.Assert));
            menu.ShowAsContext();
        }

        private void GenerateTestLog(LogType type)
        {
            searchText = string.Empty;
            logFilter = LogFilter.All;
            AILogCollector.EnsureListening();

            switch (type)
            {
                case LogType.Exception:
                    Debug.LogException(new InvalidOperationException(
                        "[AI Log Analyzer Test] 테스트 Exception 로그입니다."));
                    break;
                case LogType.Assert:
                    Debug.Assert(false, "[AI Log Analyzer Test] 테스트 Assert 로그입니다.");
                    break;
                default:
                    Debug.LogError("[AI Log Analyzer Test] 테스트 Error 로그입니다.");
                    break;
            }

            EditorApplication.delayCall -= CompleteTestLogCapture;
            EditorApplication.delayCall += CompleteTestLogCapture;
        }

        private void CompleteTestLogCapture()
        {
            AILogCollector.FlushPendingLogs();
            listScrollPosition = Vector2.zero;
            Repaint();
        }

        private int CountVisibleEntries()
        {
            int count = 0;
            foreach (AILogEntry entry in AILogCollector.Entries)
            {
                if (IsVisible(entry))
                {
                    count++;
                }
            }

            return count;
        }

        private bool IsVisible(AILogEntry entry)
        {
            return MatchesFilter(entry.LogType) && entry.Matches(searchText);
        }

        private bool MatchesFilter(LogType type)
        {
            return logFilter == LogFilter.All ||
                   logFilter == LogFilter.Error && type == LogType.Error ||
                   logFilter == LogFilter.Exception && type == LogType.Exception ||
                   logFilter == LogFilter.Assert && type == LogType.Assert;
        }

        private AILogEntry FindSelectedEntry()
        {
            if (string.IsNullOrEmpty(selectedEntryKey))
            {
                return null;
            }

            foreach (AILogEntry entry in AILogCollector.Entries)
            {
                if (string.Equals(CreateEntryKey(entry), selectedEntryKey, StringComparison.Ordinal))
                {
                    return entry;
                }
            }

            selectedEntryKey = null;
            return null;
        }

        private static string CreateEntryKey(AILogEntry entry)
        {
            return $"{(int)entry.LogType}\u001f{entry.Message}\u001f{entry.StackTrace}";
        }

        private static string GetSummary(string message)
        {
            string summary = string.IsNullOrWhiteSpace(message)
                ? "(메시지 없음)"
                : message.Replace("\r", " ").Replace("\n", " ").Trim();

            return summary.Length <= MaximumSummaryLength
                ? summary
                : summary.Substring(0, MaximumSummaryLength) + "…";
        }

        private static string GetTypeLabel(LogType type)
        {
            return AILogAnalysisUtility.GetTypeLabel(type);
        }

        private static string GetSourceCategoryLabel(string category)
        {
            switch (category)
            {
                case "user_code":
                    return "사용자 C# 코드";
                case "unity_engine":
                    return "Unity Engine";
                case "unity_editor":
                    return "Unity Editor";
                case "external_package":
                    return "외부 패키지/플러그인";
                default:
                    return "특정 불가";
            }
        }

        private static string GetConfidenceLabel(string confidence)
        {
            switch (confidence)
            {
                case "high":
                    return "높음";
                case "medium":
                    return "중간";
                default:
                    return "낮음";
            }
        }

        private static string FormatTimestamp(string timestamp)
        {
            return DateTime.TryParse(timestamp, out DateTime parsed)
                ? parsed.ToString("yyyy-MM-dd HH:mm:ss")
                : timestamp;
        }

        private static void DrawReadOnlyField(string label, string value)
        {
            EditorGUILayout.BeginHorizontal();
            EditorGUILayout.LabelField(label, GUILayout.Width(90f));
            EditorGUILayout.SelectableLabel(value ?? string.Empty, GUILayout.Height(18f));
            EditorGUILayout.EndHorizontal();
        }

        private enum LogFilter
        {
            All,
            Error,
            Exception,
            Assert
        }

        private enum ServerConnectionState
        {
            Unknown,
            Checking,
            Online,
            Offline
        }

        private enum AnalysisMode
        {
            Mock,
            LocalLLM
        }
    }
}

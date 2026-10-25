using System;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;

namespace DiceAndDie.Editor
{
    /// <summary>
    /// Editor 전용 localhost API 클라이언트입니다. 게임 런타임에서는 참조하지 않습니다.
    /// </summary>
    internal static class AILogAnalyzerClient
    {
        public const string BaseUrl = "http://127.0.0.1:8000";
        public const int HealthTimeoutSeconds = 10;
        public const int AnalysisTimeoutSeconds = 135;
        public const int SlackTimeoutSeconds = 15;
        public const int MaximumRequestBytes = 384 * 1024;

        public static async Task<AILogApiResult<AILogHealthResponse>> CheckHealthAsync(
            CancellationToken cancellationToken)
        {
            using (UnityWebRequest request = UnityWebRequest.Get(BaseUrl + "/health"))
            {
                request.timeout = HealthTimeoutSeconds;
                request.SetRequestHeader("Accept", "application/json");

                AILogApiResult<string> response = await SendAsync(request, cancellationToken);
                if (!response.Success)
                {
                    return AILogApiResult<AILogHealthResponse>.Failed(
                        response.ErrorMessage,
                        response.StatusCode);
                }

                AILogHealthResponse health = TryDeserialize<AILogHealthResponse>(response.Value);
                return health != null && health.IsValid()
                    ? AILogApiResult<AILogHealthResponse>.Succeeded(health, response.StatusCode)
                    : AILogApiResult<AILogHealthResponse>.Failed(
                        "서버가 올바르지 않은 상태 응답을 반환했습니다.",
                        response.StatusCode);
            }
        }

        public static async Task<AILogApiResult<AILogAnalysisResponse>> AnalyzeAsync(
            AILogAnalysisRequest analysisRequest,
            CancellationToken cancellationToken)
        {
            if (analysisRequest == null)
            {
                throw new ArgumentNullException(nameof(analysisRequest));
            }

            string json = JsonUtility.ToJson(analysisRequest);
            byte[] requestBody = Encoding.UTF8.GetBytes(json);
            if (requestBody.Length > MaximumRequestBytes)
            {
                return AILogApiResult<AILogAnalysisResponse>.Failed(
                    $"요청 크기가 {MaximumRequestBytes / 1024} KiB 제한을 초과했습니다.");
            }

            using (var request = new UnityWebRequest(BaseUrl + "/analyze", "POST"))
            {
                request.uploadHandler = new UploadHandlerRaw(requestBody);
                request.downloadHandler = new DownloadHandlerBuffer();
                request.timeout = AnalysisTimeoutSeconds;
                request.SetRequestHeader("Content-Type", "application/json; charset=utf-8");
                request.SetRequestHeader("Accept", "application/json");

                AILogApiResult<string> response = await SendAsync(request, cancellationToken);
                if (!response.Success)
                {
                    return AILogApiResult<AILogAnalysisResponse>.Failed(
                        response.ErrorMessage,
                        response.StatusCode);
                }

                AILogAnalysisResponse analysis =
                    TryDeserialize<AILogAnalysisResponse>(response.Value);
                return analysis != null && analysis.IsValid()
                    ? AILogApiResult<AILogAnalysisResponse>.Succeeded(
                        analysis,
                        response.StatusCode)
                    : AILogApiResult<AILogAnalysisResponse>.Failed(
                        "서버가 올바르지 않은 분석 응답을 반환했습니다.",
                        response.StatusCode);
            }
        }

        public static async Task<AILogApiResult<AILogSlackStatusResponse>> CheckSlackStatusAsync(
            CancellationToken cancellationToken)
        {
            using (UnityWebRequest request = UnityWebRequest.Get(BaseUrl + "/slack/status"))
            {
                request.timeout = SlackTimeoutSeconds;
                request.SetRequestHeader("Accept", "application/json");
                return await SendAndDeserializeAsync<AILogSlackStatusResponse>(
                    request,
                    response => response.IsValid(),
                    "서버가 올바르지 않은 Slack 상태 응답을 반환했습니다.",
                    cancellationToken);
            }
        }

        public static Task<AILogApiResult<AILogSlackPreviewResponse>> CreateSlackPreviewAsync(
            string requestId,
            CancellationToken cancellationToken)
        {
            return PostAsync<AILogSlackRequest, AILogSlackPreviewResponse>(
                "/slack/preview",
                new AILogSlackRequest(requestId),
                SlackTimeoutSeconds,
                response => response.IsValid(),
                "서버가 올바르지 않은 Slack 미리보기 응답을 반환했습니다.",
                cancellationToken);
        }

        public static Task<AILogApiResult<AILogSlackSendResponse>> SendToSlackAsync(
            string requestId,
            string previewToken,
            CancellationToken cancellationToken)
        {
            return PostAsync<AILogSlackSendRequest, AILogSlackSendResponse>(
                "/slack/send",
                new AILogSlackSendRequest(requestId, previewToken),
                SlackTimeoutSeconds,
                response => response.IsValid(),
                "서버가 올바르지 않은 Slack 전송 응답을 반환했습니다.",
                cancellationToken);
        }

        private static async Task<AILogApiResult<TResponse>> PostAsync<TRequest, TResponse>(
            string path,
            TRequest body,
            int timeoutSeconds,
            Func<TResponse, bool> validator,
            string invalidResponseMessage,
            CancellationToken cancellationToken)
            where TResponse : class
        {
            // 서버 제한보다 먼저 차단해 큰 문자열을 불필요하게 업로드하지 않습니다.
            byte[] requestBody = Encoding.UTF8.GetBytes(JsonUtility.ToJson(body));
            if (requestBody.Length > MaximumRequestBytes)
            {
                return AILogApiResult<TResponse>.Failed(
                    $"요청 크기가 {MaximumRequestBytes / 1024} KiB 제한을 초과했습니다.");
            }

            using (var request = new UnityWebRequest(BaseUrl + path, "POST"))
            {
                request.uploadHandler = new UploadHandlerRaw(requestBody);
                request.downloadHandler = new DownloadHandlerBuffer();
                request.timeout = timeoutSeconds;
                request.SetRequestHeader("Content-Type", "application/json; charset=utf-8");
                request.SetRequestHeader("Accept", "application/json");
                return await SendAndDeserializeAsync(
                    request,
                    validator,
                    invalidResponseMessage,
                    cancellationToken);
            }
        }

        private static async Task<AILogApiResult<T>> SendAndDeserializeAsync<T>(
            UnityWebRequest request,
            Func<T, bool> validator,
            string invalidResponseMessage,
            CancellationToken cancellationToken)
            where T : class
        {
            AILogApiResult<string> response = await SendAsync(request, cancellationToken);
            if (!response.Success)
            {
                return AILogApiResult<T>.Failed(response.ErrorMessage, response.StatusCode);
            }

            T value = TryDeserialize<T>(response.Value);
            return value != null && validator(value)
                ? AILogApiResult<T>.Succeeded(value, response.StatusCode)
                : AILogApiResult<T>.Failed(invalidResponseMessage, response.StatusCode);
        }

        private static async Task<AILogApiResult<string>> SendAsync(
            UnityWebRequest request,
            CancellationToken cancellationToken)
        {
            try
            {
                UnityWebRequestAsyncOperation operation = request.SendWebRequest();
                while (!operation.isDone)
                {
                    if (cancellationToken.IsCancellationRequested)
                    {
                        // 창 닫기, 항목 변경, Play Mode 전환 시 진행 중인 네트워크 요청도 중단합니다.
                        request.Abort();
                        cancellationToken.ThrowIfCancellationRequested();
                    }

                    await Task.Delay(25, cancellationToken);
                }

                if (request.result == UnityWebRequest.Result.Success)
                {
                    return AILogApiResult<string>.Succeeded(
                        request.downloadHandler?.text ?? string.Empty,
                        request.responseCode);
                }

                string serverDetail = request.downloadHandler?.text;
                string message = string.IsNullOrWhiteSpace(serverDetail)
                    ? request.error
                    : serverDetail;
                return AILogApiResult<string>.Failed(
                    $"HTTP 요청 실패 ({request.responseCode}): {message}",
                    request.responseCode);
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception exception)
            {
                // Python 서버 장애는 Editor 도구의 실패 상태로만 변환하고 게임 실행에는 전파하지 않습니다.
                return AILogApiResult<string>.Failed(
                    $"서버 연결 중 예외가 발생했습니다: {exception.Message}");
            }
        }

        private static T TryDeserialize<T>(string json) where T : class
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                return null;
            }

            try
            {
                return JsonUtility.FromJson<T>(json);
            }
            catch (ArgumentException)
            {
                return null;
            }
        }
    }
}

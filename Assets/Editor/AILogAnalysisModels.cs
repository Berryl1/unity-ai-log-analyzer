using System;

namespace DiceAndDie.Editor
{
    /// <summary>Python /analyze 요청과 필드명이 일치하는 Unity JSON DTO입니다.</summary>
    [Serializable]
    internal sealed class AILogAnalysisRequest
    {
        public string error_type;
        public string message;
        public string stack_trace;
        public int occurrence_count;
        public string first_occurred_at;
        public string last_occurred_at;
        public string analyzer_mode;

        public AILogAnalysisRequest(
            AILogEntry entry,
            AILogTransmissionPreview preview,
            string analyzerMode)
        {
            error_type = AILogAnalysisUtility.GetTypeLabel(entry.LogType);
            message = preview.Message;
            stack_trace = preview.StackTrace;
            occurrence_count = entry.OccurrenceCount;
            first_occurred_at = entry.FirstOccurredAt;
            last_occurred_at = entry.LastOccurredAt;
            analyzer_mode = analyzerMode;
        }
    }

    /// <summary>Mock과 Qwen이 공통으로 반환하는 구조화 분석 결과입니다.</summary>
    [Serializable]
    internal sealed class AILogAnalysisResponse
    {
        public string error_type = string.Empty;
        public string location = string.Empty;
        public string probable_cause = string.Empty;
        public string suggested_fix = string.Empty;
        public string checks_required = string.Empty;
        public string impact_scope = string.Empty;
        public string disclaimer = string.Empty;
        public bool is_mock = false;
        public string analyzed_at = string.Empty;
        public string request_id = string.Empty;
        public string source_category = "unknown";
        public string confidence = "low";
        public string analysis_basis = string.Empty;

        public bool IsValid()
        {
            return !string.IsNullOrWhiteSpace(error_type) &&
                   !string.IsNullOrWhiteSpace(probable_cause) &&
                   !string.IsNullOrWhiteSpace(suggested_fix) &&
                   !string.IsNullOrWhiteSpace(checks_required) &&
                   !string.IsNullOrWhiteSpace(impact_scope);
        }
    }

    [Serializable]
    internal sealed class AILogHealthResponse
    {
        public string status = string.Empty;
        public string analyzer = string.Empty;
        public string version = string.Empty;
        public string ollama_status = string.Empty;
        public string ollama_model = string.Empty;
        public string ollama_message = string.Empty;

        public bool IsValid()
        {
            return string.Equals(status, "ok", StringComparison.OrdinalIgnoreCase) &&
                   !string.IsNullOrWhiteSpace(version);
        }
    }

    [Serializable]
    internal sealed class AILogSlackStatusResponse
    {
        public bool enabled = false;
        public bool token_configured = false;
        public bool channel_configured = false;
        public string connection_status = string.Empty;
        public string channel_id = string.Empty;
        public string status_message = string.Empty;

        public bool IsValid()
        {
            return !string.IsNullOrWhiteSpace(connection_status) &&
                   !string.IsNullOrWhiteSpace(status_message);
        }

        public bool IsReady()
        {
            return enabled && token_configured && channel_configured &&
                   string.Equals(connection_status, "ready", StringComparison.OrdinalIgnoreCase);
        }
    }

    [Serializable]
    internal sealed class AILogSlackRequest
    {
        public string request_id;

        public AILogSlackRequest(string requestId)
        {
            request_id = requestId;
        }
    }

    [Serializable]
    internal sealed class AILogSlackSendRequest
    {
        public string request_id;
        public string preview_token;

        public AILogSlackSendRequest(string requestId, string previewToken)
        {
            request_id = requestId;
            preview_token = previewToken;
        }
    }

    /// <summary>서버가 생성한 Slack 미리보기와 단기 승인 토큰입니다.</summary>
    [Serializable]
    internal sealed class AILogSlackPreviewResponse
    {
        public string request_id = string.Empty;
        public string channel_id = string.Empty;
        public string preview_token = string.Empty;
        public string preview_text = string.Empty;
        public string expires_at = string.Empty;

        public bool IsValid()
        {
            return !string.IsNullOrWhiteSpace(request_id) &&
                   !string.IsNullOrWhiteSpace(channel_id) &&
                   !string.IsNullOrWhiteSpace(preview_token) &&
                   !string.IsNullOrWhiteSpace(preview_text);
        }
    }

    /// <summary>인증정보를 포함하지 않는 Slack 전송 결과입니다.</summary>
    [Serializable]
    internal sealed class AILogSlackSendResponse
    {
        public bool success = false;
        public string request_id = string.Empty;
        public string channel_id = string.Empty;
        public string slack_message_ts = string.Empty;
        public string sent_at = string.Empty;
        public string error_code = string.Empty;
        public string status_message = string.Empty;

        public bool IsValid()
        {
            return !string.IsNullOrWhiteSpace(request_id) &&
                   !string.IsNullOrWhiteSpace(status_message) &&
                   (success || !string.IsNullOrWhiteSpace(error_code));
        }
    }

    internal sealed class AILogTransmissionPreview
    {
        public AILogTransmissionPreview(string message, string stackTrace)
        {
            Message = message ?? string.Empty;
            StackTrace = stackTrace ?? string.Empty;
        }

        public string Message { get; }
        public string StackTrace { get; }
    }

    internal sealed class AILogApiResult<T>
    {
        private AILogApiResult(bool success, T value, string errorMessage, long statusCode)
        {
            Success = success;
            Value = value;
            ErrorMessage = errorMessage;
            StatusCode = statusCode;
        }

        public bool Success { get; }
        public T Value { get; }
        public string ErrorMessage { get; }
        public long StatusCode { get; }

        public static AILogApiResult<T> Succeeded(T value, long statusCode)
        {
            return new AILogApiResult<T>(true, value, string.Empty, statusCode);
        }

        public static AILogApiResult<T> Failed(string errorMessage, long statusCode = 0)
        {
            return new AILogApiResult<T>(false, default, errorMessage, statusCode);
        }
    }

    internal static class AILogAnalysisUtility
    {
        public static string GetTypeLabel(UnityEngine.LogType type)
        {
            switch (type)
            {
                case UnityEngine.LogType.Exception:
                    return "Exception";
                case UnityEngine.LogType.Assert:
                    return "Assert";
                default:
                    return "Error";
            }
        }
    }
}

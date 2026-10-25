using System;
using System.Text.RegularExpressions;

namespace DiceAndDie.Editor
{
    /// <summary>
    /// 사용자가 서버 전송 전에 확인할 로그 미리보기에서 대표 민감정보와 과도한 길이를 제거합니다.
    /// 서버에서도 같은 목적의 재필터링을 수행합니다.
    /// </summary>
    internal static class AILogSensitiveDataFilter
    {
        public const int MaximumMessageCharacters = 16000;
        public const int MaximumStackTraceCharacters = 64000;
        private const string TruncatedSuffix = "\n<truncated-by-unity-client>";
        private static readonly TimeSpan RegexTimeout = TimeSpan.FromMilliseconds(100);

        private static readonly Replacement[] Replacements =
        {
            new Replacement(
                @"\b(authorization\s*:\s*bearer|bearer)\s+[^\s,;]+",
                "$1 <redacted>"),
            new Replacement(
                @"\b(api[_-]?key|access[_-]?token|auth[_-]?token|token|password|secret)(\s*[:=]\s*)[^\s,;]+",
                "$1$2<redacted>"),
            new Replacement(@"\bsk-[A-Za-z0-9_-]{12,}\b", "<redacted-api-key>"),
            new Replacement(@"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "<redacted-slack-token>"),
            new Replacement(
                @"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
                "<redacted-email>"),
            new Replacement(
                @"\b[A-Z]:\\Users\\[^\\\s]+",
                @"C:\Users\<redacted-user>"),
            new Replacement(@"/Users/[^/\s]+", "/Users/<redacted-user>"),
            new Replacement(@"/home/[^/\s]+", "/home/<redacted-user>"),
            new Replacement(
                @"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])",
                "<redacted-ip>"),
            new Replacement(@"https?://[^\s<>]+", "<redacted-url>")
        };

        public static AILogTransmissionPreview CreatePreview(AILogEntry entry)
        {
            if (entry == null)
            {
                throw new ArgumentNullException(nameof(entry));
            }

            return new AILogTransmissionPreview(
                SanitizeAndLimit(entry.Message, MaximumMessageCharacters),
                SanitizeAndLimit(entry.StackTrace, MaximumStackTraceCharacters));
        }

        private static string SanitizeAndLimit(string value, int maximumCharacters)
        {
            // 먼저 길이를 제한해 복잡한 입력에 대한 정규식 처리 비용도 함께 제한합니다.
            string sanitized = Limit(value ?? string.Empty, maximumCharacters);

            foreach (Replacement replacement in Replacements)
            {
                try
                {
                    sanitized = replacement.Pattern.Replace(sanitized, replacement.Value);
                }
                catch (RegexMatchTimeoutException)
                {
                    // 일부만 필터링된 값을 반환하지 않고 전체를 가려 민감정보 노출을 우선 방지합니다.
                    return "<content-redacted-after-filter-timeout>";
                }
            }

            return sanitized;
        }

        private static string Limit(string value, int maximumCharacters)
        {
            if (value.Length <= maximumCharacters)
            {
                return value;
            }

            int contentLength = Math.Max(0, maximumCharacters - TruncatedSuffix.Length);
            return value.Substring(0, contentLength) + TruncatedSuffix;
        }

        private sealed class Replacement
        {
            public Replacement(string pattern, string value)
            {
                Pattern = new Regex(
                    pattern,
                    RegexOptions.Compiled | RegexOptions.IgnoreCase | RegexOptions.CultureInvariant,
                    RegexTimeout);
                Value = value;
            }

            public Regex Pattern { get; }
            public string Value { get; }
        }
    }
}

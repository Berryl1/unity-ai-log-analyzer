using System;
using UnityEngine;

namespace DiceAndDie.Editor
{
    [Serializable]
    internal sealed class AILogEntry
    {
        [SerializeField] private string message;
        [SerializeField] private string stackTrace;
        [SerializeField] private LogType logType;
        [SerializeField] private int occurrenceCount;
        [SerializeField] private string firstOccurredAt;
        [SerializeField] private string lastOccurredAt;

        public AILogEntry(string message, string stackTrace, LogType logType, DateTime occurredAt)
        {
            this.message = message ?? string.Empty;
            this.stackTrace = stackTrace ?? string.Empty;
            this.logType = logType;
            occurrenceCount = 1;
            firstOccurredAt = occurredAt.ToString("O");
            lastOccurredAt = firstOccurredAt;
        }

        public string Message => message;
        public string StackTrace => stackTrace;
        public LogType LogType => logType;
        public int OccurrenceCount => occurrenceCount;
        public string FirstOccurredAt => firstOccurredAt;
        public string LastOccurredAt => lastOccurredAt;

        public string Location
        {
            get
            {
                if (string.IsNullOrWhiteSpace(stackTrace))
                {
                    return "Stack trace 없음";
                }

                string normalized = stackTrace.Replace("\r\n", "\n");
                string[] lines = normalized.Split('\n');

                foreach (string line in lines)
                {
                    if (!string.IsNullOrWhiteSpace(line))
                    {
                        return line.Trim();
                    }
                }

                return "Stack trace 없음";
            }
        }

        public void RegisterOccurrence(DateTime occurredAt)
        {
            occurrenceCount++;
            lastOccurredAt = occurredAt.ToString("O");
        }

        public bool Matches(string searchText)
        {
            if (string.IsNullOrWhiteSpace(searchText))
            {
                return true;
            }

            return message.IndexOf(searchText, StringComparison.OrdinalIgnoreCase) >= 0 ||
                   stackTrace.IndexOf(searchText, StringComparison.OrdinalIgnoreCase) >= 0;
        }
    }
}

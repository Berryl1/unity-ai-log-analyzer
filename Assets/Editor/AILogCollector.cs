using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;
using UnityEditor;
using UnityEngine;

namespace DiceAndDie.Editor
{
    /// <summary>
    /// Unity 로그 callback과 Editor UI 사이에서 오류를 제한적으로 수집하고 중복 집계합니다.
    /// </summary>
    [InitializeOnLoad]
    internal static class AILogCollector
    {
        public const int MaximumUniqueLogCount = 500;
        public const int MaximumPendingLogCount = 2000;
        private const int MaximumLogsProcessedPerUpdate = 100;

        private static readonly ConcurrentQueue<PendingLog> PendingLogs =
            new ConcurrentQueue<PendingLog>();
        private static readonly List<AILogEntry> LogEntries = new List<AILogEntry>();
        private static readonly Dictionary<string, AILogEntry> EntriesByKey =
            new Dictionary<string, AILogEntry>(StringComparer.Ordinal);

        private static int pendingLogCount;
        private static int droppedLogCount;

        static AILogCollector()
        {
            EnsureListening();
        }

        public static IReadOnlyList<AILogEntry> Entries => LogEntries;
        public static int DroppedLogCount => Volatile.Read(ref droppedLogCount);

        public static event Action Changed;

        public static void EnsureListening()
        {
            // 도메인 리로드나 창 재오픈 뒤에도 callback이 중복 등록되지 않도록 먼저 제거합니다.
            Application.logMessageReceivedThreaded -= HandleLogMessage;
            Application.logMessageReceivedThreaded += HandleLogMessage;
            EditorApplication.update -= ProcessPendingLogs;
            EditorApplication.update += ProcessPendingLogs;
            AssemblyReloadEvents.beforeAssemblyReload -= Detach;
            AssemblyReloadEvents.beforeAssemblyReload += Detach;
        }

        public static void FlushPendingLogs()
        {
            ProcessPendingLogs();
        }

        public static void Clear()
        {
            while (PendingLogs.TryDequeue(out _))
            {
                Interlocked.Decrement(ref pendingLogCount);
            }

            LogEntries.Clear();
            EntriesByKey.Clear();
            Interlocked.Exchange(ref pendingLogCount, 0);
            Interlocked.Exchange(ref droppedLogCount, 0);
            Changed?.Invoke();
        }

        private static void HandleLogMessage(string condition, string stackTrace, LogType type)
        {
            if (!IsSupported(type))
            {
                return;
            }

            // 이 callback은 여러 스레드에서 호출될 수 있으므로 Unity API/UI를 건드리지 않고 큐에만 넣습니다.
            int queueSize = Interlocked.Increment(ref pendingLogCount);
            if (queueSize > MaximumPendingLogCount)
            {
                Interlocked.Decrement(ref pendingLogCount);
                Interlocked.Increment(ref droppedLogCount);
                return;
            }

            PendingLogs.Enqueue(new PendingLog(
                condition ?? string.Empty,
                stackTrace ?? string.Empty,
                type,
                DateTime.Now));
        }

        private static void ProcessPendingLogs()
        {
            bool changed = false;
            int processedCount = 0;

            // 한 프레임의 처리량을 제한해 오류 폭주가 Editor를 오래 점유하지 않게 합니다.
            while (processedCount < MaximumLogsProcessedPerUpdate &&
                   PendingLogs.TryDequeue(out PendingLog pendingLog))
            {
                Interlocked.Decrement(ref pendingLogCount);
                AddOrUpdate(pendingLog);
                processedCount++;
                changed = true;
            }

            if (changed)
            {
                Changed?.Invoke();
            }
        }

        private static void AddOrUpdate(PendingLog pendingLog)
        {
            string key = CreateKey(pendingLog);

            if (EntriesByKey.TryGetValue(key, out AILogEntry existingEntry))
            {
                // 메시지, Stack Trace, 유형이 모두 같은 경우 새 행 대신 발생 횟수만 갱신합니다.
                existingEntry.RegisterOccurrence(pendingLog.OccurredAt);
                return;
            }

            if (LogEntries.Count >= MaximumUniqueLogCount)
            {
                AILogEntry oldestEntry = LogEntries[0];
                LogEntries.RemoveAt(0);
                EntriesByKey.Remove(CreateKey(oldestEntry));
            }

            var entry = new AILogEntry(
                pendingLog.Message,
                pendingLog.StackTrace,
                pendingLog.LogType,
                pendingLog.OccurredAt);
            LogEntries.Add(entry);
            EntriesByKey.Add(key, entry);
        }

        private static string CreateKey(PendingLog pendingLog)
        {
            return $"{(int)pendingLog.LogType}\u001f{pendingLog.Message}\u001f{pendingLog.StackTrace}";
        }

        private static string CreateKey(AILogEntry entry)
        {
            return $"{(int)entry.LogType}\u001f{entry.Message}\u001f{entry.StackTrace}";
        }

        private static bool IsSupported(LogType type)
        {
            return type == LogType.Error ||
                   type == LogType.Exception ||
                   type == LogType.Assert;
        }

        private static void Detach()
        {
            Application.logMessageReceivedThreaded -= HandleLogMessage;
            EditorApplication.update -= ProcessPendingLogs;
            AssemblyReloadEvents.beforeAssemblyReload -= Detach;
        }

        private readonly struct PendingLog
        {
            public PendingLog(
                string message,
                string stackTrace,
                LogType logType,
                DateTime occurredAt)
            {
                Message = message;
                StackTrace = stackTrace;
                LogType = logType;
                OccurredAt = occurredAt;
            }

            public string Message { get; }
            public string StackTrace { get; }
            public LogType LogType { get; }
            public DateTime OccurredAt { get; }
        }
    }
}

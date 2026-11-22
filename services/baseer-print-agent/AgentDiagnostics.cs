using System.Drawing;
using System.Drawing.Imaging;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

sealed record DiagnosticEvent(
    DateTimeOffset Utc, int? JobId, string Stage, string Code, string? ExceptionType = null,
    int? HResult = null, int? WindowsJobId = null, int? NativeStatus = null,
    string? Fingerprint = null, int? Width = null, int? Height = null);

/// <summary>Local evidence only. Never owns print retries, config, or business data.</summary>
static class AgentDiagnostics
{
    private const long JournalLimit = 1024 * 1024;
    private const long CaptureLimit = 20 * 1024 * 1024;
    private const int MaxLine = 2048;
    private static readonly TimeSpan EventLifetime = TimeSpan.FromDays(7);
    private static readonly TimeSpan ImageLifetime = TimeSpan.FromHours(24);
    // Reflection-only isolated tests; no CLI or environment can redirect production diagnostics.
    private static string? _testRoot = null;
    private static DateTimeOffset _nextCaptureCleanup;
    private static string Root => _testRoot ?? Path.Combine(AgentRuntime.DataDirectory, "diagnostics");
    public static string CaptureDirectory => Path.Combine(Root, "captures");
    private static readonly HashSet<string> Stages = new(StringComparer.Ordinal)
    { "start", "connection", "claim", "persist", "validate", "prepare", "submit", "queue", "ack", "recovery", "update", "capture" };
    private static readonly HashSet<string> Codes = new(StringComparer.Ordinal)
    {
        "ok", "unknown", "claimed", "inflight_saved", "image_validated", "image_prepared",
        "spool_submitting", "spool_accepted", "completed", "printer_offline", "invalid_receipt",
        "print_failed", "outcome_unknown", "ack_failed", "recovery_unknown", "connection_failed",
        "runtime_busy", "heartbeat", "started", "queue_pending", "queue_printing",
        "queue_reported_complete", "queue_unobserved", "queue_unavailable", "queue_paperout",
        "queue_paused", "queue_error", "queue_deleted", "diagnostics_error", "process_failed", "storage_failed",
        "protocol_failed", "prepare_failed", "capture_armed", "capture_saved"
    };

    public static void Record(int? jobId, string stage, string code = "ok", Exception? error = null,
        int? windowsJobId = null, int? nativeStatus = null, string? fingerprint = null,
        int? width = null, int? height = null)
    {
        try
        {
            WithLock(() =>
            {
                if (DateTimeOffset.UtcNow >= _nextCaptureCleanup)
                {
                    _nextCaptureCleanup = DateTimeOffset.UtcNow.AddMinutes(1);
                    try { CleanupCaptures(); } catch { /* Keep event writes available. */ }
                }
                Append(Sanitize(new DiagnosticEvent(DateTimeOffset.UtcNow, jobId,
                    stage, code, SafeException(error), error?.HResult, windowsJobId, nativeStatus,
                    fingerprint, width, height)));
            });
        }
        catch { /* Evidence must not change the print or acknowledgement outcome. */ }
    }

    private static string? SafeException(Exception? error) => error switch
    {
        null => null,
        InvalidReceiptException => nameof(InvalidReceiptException),
        PrinterUnavailableException => nameof(PrinterUnavailableException),
        HttpRequestException => nameof(HttpRequestException),
        System.ComponentModel.Win32Exception => nameof(System.ComponentModel.Win32Exception),
        UnauthorizedAccessException => nameof(UnauthorizedAccessException),
        IOException => nameof(IOException),
        OperationCanceledException => nameof(OperationCanceledException),
        ArgumentException => nameof(ArgumentException),
        InvalidOperationException => nameof(InvalidOperationException),
        _ => nameof(Exception)
    };

    private static DiagnosticEvent Sanitize(DiagnosticEvent item) => item with
    {
        JobId = item.JobId is > 0 ? item.JobId : null,
        Stage = Stages.Contains(item.Stage ?? "") ? item.Stage ?? "start" : "start",
        Code = Codes.Contains(item.Code ?? "") ? item.Code ?? "unknown" : "unknown",
        ExceptionType = item.ExceptionType is "InvalidReceiptException" or "PrinterUnavailableException"
            or "HttpRequestException" or "Win32Exception" or "UnauthorizedAccessException" or "IOException"
            or "OperationCanceledException" or "ArgumentException" or "InvalidOperationException" or "Exception"
            ? item.ExceptionType : null,
        WindowsJobId = item.WindowsJobId is > 0 ? item.WindowsJobId : null,
        Fingerprint = item.Fingerprint is { Length: 64 } && item.Fingerprint.All(Uri.IsHexDigit)
            ? item.Fingerprint.ToLowerInvariant() : null,
        Width = item.Width is > 0 and <= 12000 ? item.Width : null,
        Height = item.Height is > 0 and <= 12000 ? item.Height : null
    };

    private static bool WithLock(Action action)
    {
        var key = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(Path.GetFullPath(Root).ToUpperInvariant())));
        using var mutex = new Mutex(false, @"Local\BaseerPrintDiagnostics-" + key);
        var owned = false;
        try
        {
            try { owned = mutex.WaitOne(0); }
            catch (AbandonedMutexException) { owned = true; }
            if (!owned) return false;
            if (_testRoot is null && !Directory.Exists(AgentRuntime.DataDirectory))
                AgentStorage.EnsureProtectedDirectory(AgentRuntime.DataDirectory);
            if (!Directory.Exists(Root)) AgentStorage.EnsureProtectedDirectory(Root);
            if ((File.GetAttributes(Root) & FileAttributes.ReparsePoint) != 0
                || (Directory.Exists(CaptureDirectory)
                    && (File.GetAttributes(CaptureDirectory) & FileAttributes.ReparsePoint) != 0))
                return false;
            action();
            return true;
        }
        finally { if (owned) mutex.ReleaseMutex(); }
    }

    private static void Append(DiagnosticEvent item)
    {
        var path = Path.Combine(Root, "events.jsonl");
        var previous = Path.Combine(Root, "events.previous.jsonl");
        var line = JsonSerializer.Serialize(item) + "\n";
        var bytes = Encoding.UTF8.GetBytes(line);
        if (bytes.Length > MaxLine) return;
        foreach (var candidate in new[] { path, previous })
            if (File.Exists(candidate) && File.GetLastWriteTimeUtc(candidate) < DateTime.UtcNow - EventLifetime)
                File.Delete(candidate);
        if (File.Exists(previous) && new FileInfo(previous).Length > JournalLimit) File.Delete(previous);
        if (File.Exists(path) && new FileInfo(path).Length > JournalLimit) File.Delete(path);
        if (File.Exists(path) && new FileInfo(path).Length + bytes.Length > JournalLimit)
            File.Move(path, previous, overwrite: true);
        using var stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.Read);
        stream.Write(bytes);
    }

    public static List<DiagnosticEvent> ReadRecent()
    {
        var result = new List<DiagnosticEvent>(200);
        try
        {
            WithLock(() =>
            {
                CleanupCaptures();
                foreach (var name in new[] { "events.previous.jsonl", "events.jsonl" })
                {
                    var path = Path.Combine(Root, name);
                    if (!File.Exists(path) || new FileInfo(path).Length > JournalLimit) continue;
                    using var reader = new StreamReader(path, Encoding.UTF8);
                    // Read bounded characters too, including a corrupt single-line journal.
                    var remaining = (int)JournalLimit;
                    while (remaining-- > 0 && !reader.EndOfStream)
                    {
                        var line = ReadBoundedLine(reader, ref remaining);
                        if (line is null) continue;
                        try
                        {
                            var item = JsonSerializer.Deserialize<DiagnosticEvent>(line);
                            if (item is null || item.Utc < DateTimeOffset.UtcNow - EventLifetime
                                || item.Utc > DateTimeOffset.UtcNow.AddMinutes(1)) continue;
                            result.Add(Sanitize(item));
                            if (result.Count > 200) result.RemoveAt(0);
                        }
                        catch (JsonException) { }
                    }
                }
            });
        }
        catch { /* A damaged/unavailable journal is not an agent failure. */ }
        return result.OrderByDescending(item => item.Utc).ToList();
    }

    private static string? ReadBoundedLine(StreamReader reader, ref int remaining)
    {
        var line = new StringBuilder(MaxLine);
        var overflow = false;
        while (remaining-- > 0)
        {
            var value = reader.Read();
            if (value < 0 || value == '\n') break;
            if (line.Length < MaxLine) line.Append((char)value);
            else overflow = true;
        }
        return overflow ? null : line.ToString();
    }

    public static void Export(string zipPath)
    {
        // Never recursively zip agent storage: config/logs/images are deliberately excluded.
        var events = ReadRecent();
        using var stream = new FileStream(zipPath, FileMode.CreateNew, FileAccess.Write, FileShare.None);
        using var archive = new ZipArchive(stream, ZipArchiveMode.Create);
        WriteEntry(archive, "summary.json", JsonSerializer.Serialize(new
        {
            agent_version = AgentBuild.Version, generated_utc = DateTimeOffset.UtcNow,
            paper_confirmation = "unavailable", includes_customer_images = false,
            event_count = events.Count
        }));
        WriteEntry(archive, "events.json", JsonSerializer.Serialize(events));
        WriteEntry(archive, "READ-ME.txt", "Baseer diagnostics: metadata only. No pairing keys, configuration, raw logs or receipt images. Windows acceptance/queue disappearance does not confirm paper output.\n");
    }

    private static void WriteEntry(ZipArchive archive, string name, string text)
    {
        using var writer = new StreamWriter(archive.CreateEntry(name).Open(), new UTF8Encoding(false));
        writer.Write(text);
    }

    private sealed record CaptureArm(DateTimeOffset Until, int Remaining);
    public static bool ArmCapture()
    {
        try
        {
            var armed = false;
            WithLock(() =>
            {
                CleanupCaptures();
                var folders = CaptureFolders();
                if (folders.Count >= 3 || CaptureBytes(folders) >= CaptureLimit - 4096) return;
                AgentStorage.EnsureProtectedDirectory(CaptureDirectory);
                File.WriteAllText(Path.Combine(Root, "capture-arm.json"), JsonSerializer.Serialize(
                    new CaptureArm(DateTimeOffset.UtcNow.AddMinutes(15), 3)));
                armed = true;
            });
            if (armed) Record(null, "capture", "capture_armed");
            return armed;
        }
        catch { return false; }
    }

    public static string CaptureStatus()
    {
        try
        {
            CaptureArm? arm = null;
            WithLock(() => arm = ReadArm());
            return arm is null ? "off" : "armed";
        }
        catch { return "unavailable"; }
    }

    private static CaptureArm? ReadArm()
    {
        var path = Path.Combine(Root, "capture-arm.json");
        if (!File.Exists(path) || new FileInfo(path).Length > 512) return null;
        try
        {
            var arm = JsonSerializer.Deserialize<CaptureArm>(File.ReadAllText(path));
            return arm is { Remaining: > 0 and <= 3 } && arm.Until > DateTimeOffset.UtcNow
                && arm.Until <= DateTimeOffset.UtcNow.AddMinutes(15) ? arm : null;
        }
        catch (JsonException) { return null; }
    }

    public static void CaptureRaster(int jobId, byte[] original, Image processed)
    {
        try
        {
            if (jobId <= 0 || original.Length is < 1 or > 256 * 1024
                || processed.Width is < 1 or > 1000 || processed.Height is < 1 or > 12000
                || (long)processed.Width * processed.Height > 5_000_000) return;
            WithLock(() =>
            {
                CleanupCaptures();
                var arm = ReadArm();
                if (arm is null) return;
                var folders = CaptureFolders();
                if (folders.Count >= 3) return;
                var existing = CaptureBytes(folders);
                if (existing >= CaptureLimit) return;
                using var image = new LimitedMemoryStream(CaptureLimit - existing - original.Length - 4096);
                processed.Save(image, ImageFormat.Png);
                var png = image.ToArray();
                // Consume first, so capture storage failure cannot cause repeated attempts.
                File.WriteAllText(Path.Combine(Root, "capture-arm.json"), JsonSerializer.Serialize(arm with { Remaining = arm.Remaining - 1 }));
                AgentStorage.EnsureProtectedDirectory(CaptureDirectory);
                var folder = Path.Combine(CaptureDirectory, $"job-{jobId}-{DateTime.UtcNow:yyyyMMddHHmmss}-{Guid.NewGuid():N}");
                Directory.CreateDirectory(folder);
                File.WriteAllBytes(Path.Combine(folder, "original.jpg"), original);
                File.WriteAllBytes(Path.Combine(folder, "processed.png"), png);
                File.WriteAllText(Path.Combine(folder, "evidence.json"), JsonSerializer.Serialize(new
                {
                    job_id = jobId, captured_utc = DateTimeOffset.UtcNow,
                    original_sha256 = Convert.ToHexString(SHA256.HashData(original)).ToLowerInvariant(),
                    processed_sha256 = Convert.ToHexString(SHA256.HashData(png)).ToLowerInvariant(),
                    width = processed.Width, height = processed.Height,
                    note = "Local customer images: not included in normal support export. Delete after comparison."
                }));
                Append(new DiagnosticEvent(DateTimeOffset.UtcNow, jobId, "capture", "capture_saved"));
            });
        }
        catch { /* Image evidence is optional, never a print requirement. */ }
    }

    private static List<string> CaptureFolders()
    {
        if (!Directory.Exists(CaptureDirectory)) return [];
        // Unexpected volume/reparse points disable capture rather than allow an unbounded scan.
        var folders = Directory.EnumerateDirectories(CaptureDirectory, "job-*").Take(33).ToList();
        if (folders.Any(path => (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0))
            throw new IOException("Capture directory is unavailable.");
        return folders;
    }

    private static long CaptureBytes(List<string> folders)
    {
        long total = 0;
        foreach (var folder in folders)
        {
            var files = Directory.EnumerateFiles(folder).Take(5).ToList();
            if (files.Count > 3) return CaptureLimit;
            foreach (var file in files) total += new FileInfo(file).Length;
        }
        return total;
    }

    private static void CleanupCaptures()
    {
        foreach (var folder in CaptureFolders())
        {
            if (Directory.GetLastWriteTimeUtc(folder) >= DateTime.UtcNow - ImageLifetime) continue;
            // Only known files, no recursive deletion or arbitrary supplied paths.
            foreach (var name in new[] { "original.jpg", "processed.png", "evidence.json" })
                File.Delete(Path.Combine(folder, name));
            if (!Directory.EnumerateFileSystemEntries(folder).Any()) Directory.Delete(folder);
        }
    }

    private sealed class LimitedMemoryStream(long limit) : MemoryStream
    {
        public override void Write(byte[] buffer, int offset, int count)
        {
            if (limit <= 0 || Position + count > limit) throw new IOException("Capture limit reached.");
            base.Write(buffer, offset, count);
        }
        public override void Write(ReadOnlySpan<byte> buffer)
        {
            if (limit <= 0 || Position + buffer.Length > limit) throw new IOException("Capture limit reached.");
            base.Write(buffer);
        }
    }

    public static string Describe(string code, bool arabic) => (code, arabic) switch
    {
        ("printer_offline", true) => "الطابعة غير متاحة",
        ("invalid_receipt", true) => "صورة الطباعة غير صالحة",
        ("queue_paperout", true) => "Windows يبلغ عن نفاد الورق",
        ("queue_paused", true) => "قائمة الطباعة متوقفة مؤقتًا",
        ("queue_error", true) => "Windows يبلغ عن خطأ في الطباعة",
        ("queue_deleted", true) => "أزيلت المهمة من قائمة Windows",
        ("connection_failed", true) => "تعذر الاتصال بأودو",
        ("runtime_busy", true) => "يوجد إيجنت آخر مرتبط بالجهاز",
        ("invalid_receipt", false) => "Invalid print image",
        ("spool_accepted", true) => "قبل Windows المهمة؛ خروج الورق غير مؤكد",
        ("queue_reported_complete", true) => "Windows يبلغ عن الاكتمال؛ خروج الورق غير مؤكد",
        ("queue_unobserved", true) => "لم تُرصد حالة المهمة في Windows؛ خروج الورق غير مؤكد",
        ("queue_unavailable", true) => "تعذر قراءة حالة قائمة Windows",
        ("outcome_unknown" or "ack_failed" or "recovery_unknown", true) => "النتيجة غير معروفة؛ لا تعِد الطباعة تلقائيًا",
        ("outcome_unknown" or "ack_failed" or "recovery_unknown", false) => "Outcome unknown; do not automatically reprint",
        ("spool_accepted" or "queue_reported_complete", false) => "Windows accepted/reported completion; paper unconfirmed",
        ("completed", true) => "حُفظ قبول Windows في أودو؛ خروج الورق غير مؤكد",
        ("completed", false) => "Windows acceptance acknowledged by Odoo; paper unconfirmed",
        ("started", true) => "بدأ تشغيل الإيجنت؛ الاتصال بأودو لم يتأكد بعد",
        ("started", false) => "Agent started; Odoo connection not yet confirmed",
        ("heartbeat", true) => "تأكد اتصال الإيجنت بأودو",
        ("heartbeat", false) => "Odoo connection confirmed",
        ("storage_failed", true) => "تعذر حفظ حالة المهمة على الجهاز",
        ("storage_failed", false) => "Could not persist local job state",
        ("protocol_failed", true) => "تعذر قراءة استجابة أودو بالشكل المتوقع",
        ("protocol_failed", false) => "Unexpected Odoo response format",
        ("prepare_failed", true) => "تعذر تجهيز صورة الطباعة محليًا",
        ("prepare_failed", false) => "Local image preparation failed",
        ("process_failed", true) => "توقف الإيجنت بسبب خطأ في التشغيل",
        ("process_failed", false) => "Agent runtime failed",
        ("capture_armed", true) => "فُعّل التقاط صور التشخيص مؤقتًا",
        ("capture_saved", true) => "حُفظت صور التشخيص محليًا",
        ("print_failed", true) => "تعذر إتمام إرسال الطباعة",
        ("queue_pending", true) => "المهمة تنتظر في قائمة Windows",
        ("queue_printing", true) => "Windows يعالج الطباعة",
        (_, true) => "مرحلة تشخيص: " + (Codes.Contains(code) ? code : "unknown"),
        (_, false) => Codes.Contains(code) ? code.Replace('_', ' ') : "Unknown diagnostic event"
    };

    public static string Action(string code, bool arabic) => (code, arabic) switch
    {
        ("printer_offline", true) => "تحقق من تشغيل الطابعة والكيبل ووجودها في إعدادات Windows.",
        ("printer_offline", false) => "Check printer power, cable and Windows printer settings.",
        ("invalid_receipt", true) => "صدّر التقرير وأرسل رقم المهمة للدعم لمراجعة صورة أودو.",
        ("invalid_receipt", false) => "Export the report and provide the job ID to support for Odoo image validation.",
        ("queue_paperout", true) => "ضع الورق وتحقق من غطاء الطابعة؛ راجع القائمة قبل إعادة الطباعة.",
        ("queue_paperout", false) => "Refill paper and check the cover; inspect the queue before reprinting.",
        ("queue_paused", true) => "راجع قائمة Windows وألغِ الإيقاف المؤقت إذا كان مناسبًا.",
        ("queue_paused", false) => "Inspect the Windows queue and resume it if appropriate.",
        ("connection_failed", true) => "تحقق من الشبكة وإمكانية فتح أودو ثم صدّر التقرير إن استمر الخطأ.",
        ("connection_failed", false) => "Check network and Odoo availability; export the report if the issue persists.",
        ("storage_failed", true) => "تحقق من مساحة القرص وصلاحيات حساب الإيجنت، ثم صدّر التقرير للدعم.",
        ("storage_failed", false) => "Check free disk space and agent account permissions, then export the support report.",
        ("protocol_failed", true) => "صدّر التقرير مع رقم نسخة الإيجنت للدعم لمراجعة توافق أودو والإيجنت.",
        ("protocol_failed", false) => "Export the report and agent version for support to check Odoo compatibility.",
        ("prepare_failed" or "process_failed", true) => "راجع رقم المهمة وآخر مرحلة، ثم صدّر التقرير للدعم؛ لا تعِد المهمة تلقائيًا.",
        ("prepare_failed" or "process_failed", false) => "Check the job ID and last stage, then export the support report; do not automatically reprint.",
        ("outcome_unknown" or "ack_failed" or "recovery_unknown" or "print_failed", true) => "راجع الورقة وقائمة Windows أولًا لمنع التكرار، ثم صدّر التقرير للدعم.",
        ("outcome_unknown" or "ack_failed" or "recovery_unknown" or "print_failed", false) => "Check paper and the Windows queue first to avoid duplicates, then export the support report.",
        ("queue_error" or "queue_deleted" or "queue_unavailable", true) => "افحص قائمة Windows والتعريف والاتصال، ثم صدّر تقرير التشخيص.",
        ("queue_error" or "queue_deleted" or "queue_unavailable", false) => "Inspect the Windows queue, driver and connection, then export diagnostics.",
        (_, true) => "إذا اختلفت الورقة، فعّل التقاط الصور مؤقتًا وصدّر تقرير المهمة للدعم.",
        (_, false) => "If paper differs, temporarily enable image capture and export the job report for support."
    };
}

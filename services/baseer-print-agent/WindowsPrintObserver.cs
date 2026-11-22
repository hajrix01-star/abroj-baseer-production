using System.Runtime.InteropServices;

/// <summary>Best-effort read-only correlation. Never controls retries or claims paper output.</summary>
static class WindowsPrintObserver
{
    private static int active;
    private const uint MaxBytes = 2 * 1024 * 1024;

    public static void Observe(int jobId, string printer, string document)
    {
        // A stalled remote driver must not consume more background threads on each job.
        if (Interlocked.CompareExchange(ref active, 1, 0) != 0)
        {
            // Normal throughput can overlap observations; this is not a printer fault.
            AgentDiagnostics.Record(jobId, "queue", "queue_unobserved");
            return;
        }
        _ = Task.Run(async () =>
        {
            try
            {
                await ObserveAsync(jobId, printer, document);
            }
            catch (Exception error)
            {
                AgentDiagnostics.Record(jobId, "queue", "queue_unavailable", error);
            }
            finally { Volatile.Write(ref active, 0); }
        });
    }

    private static async Task ObserveAsync(int jobId, string printer, string document)
    {
        if (!OpenPrinter(printer, out var handle, IntPtr.Zero))
        {
            AgentDiagnostics.Record(jobId, "queue", "queue_unavailable");
            return;
        }
        try
        {
            uint? windowsId = null;
            string? lastCode = null;
            // Maximum 15 observations / 30 seconds. Slow native calls occupy only this worker.
            for (var attempt = 0; attempt < 15; attempt++)
            {
                var result = ReadJob(handle, windowsId, document);
                if (!result.Available)
                {
                    AgentDiagnostics.Record(jobId, "queue", "queue_unavailable");
                    return;
                }
                if (result.Job is { } job)
                {
                    windowsId = job.JobId;
                    var code = StatusCode(job.Status);
                    if (code != lastCode)
                    {
                        AgentDiagnostics.Record(jobId, "queue", code,
                            windowsJobId: unchecked((int)job.JobId), nativeStatus: unchecked((int)job.Status));
                        lastCode = code;
                    }
                    if (code is "queue_reported_complete" or "queue_deleted") return;
                }
                else if (windowsId is not null)
                {
                    // Queue removal can mean printed, deleted or purged. It is not success evidence.
                    AgentDiagnostics.Record(jobId, "queue", "queue_unobserved", windowsJobId: unchecked((int)windowsId.Value));
                    return;
                }
                if (attempt < 14) await Task.Delay(2000);
            }
            if (windowsId is null) AgentDiagnostics.Record(jobId, "queue", "queue_unobserved");
        }
        finally { ClosePrinter(handle); }
    }

    internal static string StatusCode(uint status)
    {
        if ((status & 0x40) != 0) return "queue_paperout";
        if ((status & 0x20) != 0) return "printer_offline";
        if ((status & 0x1) != 0) return "queue_paused";
        if ((status & (0x2 | 0x200 | 0x400)) != 0) return "queue_error";
        if ((status & (0x4 | 0x100)) != 0) return "queue_deleted";
        if ((status & (0x80 | 0x1000)) != 0) return "queue_reported_complete";
        if ((status & 0x10) != 0) return "queue_printing";
        return "queue_pending";
    }

    private readonly record struct JobRead(bool Available, JobInfo1? Job);

    private static JobRead ReadJob(IntPtr handle, uint? id, string document)
    {
        uint needed, count;
        bool probe;
        if (id is uint known)
        {
            probe = GetJob(handle, known, 1, IntPtr.Zero, 0, out needed);
            count = 1;
        }
        else probe = EnumJobs(handle, 0, 128, 1, IntPtr.Zero, 0, out needed, out count);
        var error = Marshal.GetLastWin32Error();
        if (!probe && error != 122)
            return new JobRead(id is not null && error is 87 or 2, null);
        if (needed == 0) return new JobRead(true, null);
        if (needed > MaxBytes) return new JobRead(false, null);
        var buffer = Marshal.AllocHGlobal((int)needed);
        try
        {
            var size = needed;
            var success = id is uint exact
                ? GetJob(handle, exact, 1, buffer, size, out needed)
                : EnumJobs(handle, 0, 128, 1, buffer, size, out needed, out count);
            if (!success) return new JobRead(false, null);
            var stride = Marshal.SizeOf<JobInfo1>();
            if (count > 128 || (long)count * stride > size) return new JobRead(false, null);
            for (var index = 0; index < count; index++)
            {
                var job = Marshal.PtrToStructure<JobInfo1>(IntPtr.Add(buffer, checked((int)index * stride)));
                // Only this process's unpredictable exact document name is eligible.
                if ((id is null || job.JobId == id) && DocumentMatches(job.Document, buffer, size, document))
                    return new JobRead(true, job);
            }
            return new JobRead(true, null);
        }
        finally { Marshal.FreeHGlobal(buffer); }
    }

    private static bool DocumentMatches(IntPtr value, IntPtr buffer, uint bytes, string expected)
    {
        var offset = value.ToInt64() - buffer.ToInt64();
        var length = checked((expected.Length + 1) * 2);
        if (offset < 0 || offset + length > bytes || (offset & 1) != 0) return false;
        return Marshal.PtrToStringUni(value, expected.Length + 1) == expected + "\0";
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SystemTime
    {
        public ushort Year, Month, DayOfWeek, Day, Hour, Minute, Second, Milliseconds;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobInfo1
    {
        public uint JobId;
        public IntPtr PrinterName, MachineName, UserName, Document, Datatype, StatusText;
        public uint Status, Priority, Position, TotalPages, PagesPrinted;
        public SystemTime Submitted;
    }

    [DllImport("winspool.drv", EntryPoint = "OpenPrinterW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool OpenPrinter(string name, out IntPtr handle, IntPtr defaults);
    [DllImport("winspool.drv", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ClosePrinter(IntPtr handle);
    [DllImport("winspool.drv", EntryPoint = "EnumJobsW", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EnumJobs(IntPtr handle, uint first, uint count, uint level, IntPtr buffer, uint size, out uint needed, out uint returned);
    [DllImport("winspool.drv", EntryPoint = "GetJobW", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetJob(IntPtr handle, uint id, uint level, IntPtr buffer, uint size, out uint needed);
}

using System.Drawing;
using System.Globalization;
using System.Windows.Forms;

/// <summary>Read-only, local support window. It has no HTTP listener and cannot print or retry jobs.</summary>
static class AgentStatusWindow
{
    /// <summary>A running worker exposes status through its own version, including after a safe update.</summary>
    public static IDisposable StartTray()
    {
        try { return new TraySession(); }
        catch { return new NoTray(); }
    }

    private sealed class NoTray : IDisposable
    {
        public void Dispose() { }
    }

    private sealed class TraySession : IDisposable
    {
        private readonly object gate = new();
        private bool disposed;
        private Control? dispatcher;
        private ApplicationContext? context;

        public TraySession()
        {
            var thread = new Thread(WatchTray) { IsBackground = true, Name = "Baseer print status" };
            thread.SetApartmentState(ApartmentState.STA);
            thread.Start();
        }

        private void WatchTray()
        {
            try
            {
                Application.EnableVisualStyles();
                using var dispatch = new Control();
                _ = dispatch.Handle;
                using var loop = new ApplicationContext();
                using var menu = new ContextMenuStrip();
                using var icon = new NotifyIcon {
                    Icon = SystemIcons.Application, Text = "حالة طباعة بصير / Baseer Print Status",
                    ContextMenuStrip = menu,
                };
                using var poll = new System.Windows.Forms.Timer { Interval = 3000 };
                var seenError = DateTimeOffset.UtcNow;
                var lastAlert = DateTimeOffset.MinValue;
                poll.Tick += (_, _) =>
                {
                    try
                    {
                        var latestError = AgentDiagnostics.ReadRecent().FirstOrDefault(item => IsError(item.Code));
                        var now = DateTimeOffset.UtcNow;
                        icon.Icon = latestError is not null && now - latestError.Utc <= TimeSpan.FromMinutes(10)
                            ? SystemIcons.Warning : SystemIcons.Application;
                        if (latestError is null || latestError.Utc <= seenError) return;
                        seenError = latestError.Utc;
                        if (now - lastAlert < TimeSpan.FromMinutes(1)) return;
                        lastAlert = now;
                        icon.ShowBalloonTip(8000, "تحقق من الطباعة / Check printing",
                            "حدثت مشكلة. افتح حالة الطباعة لمعرفة الخطوة المقترحة.\nA problem was recorded. Open Print status for the suggested action.",
                            ToolTipIcon.Warning);
                    }
                    catch { /* Notification failures do not affect printing. */ }
                };
                StatusForm? window = null;
                void ShowStatus()
                {
                    if (window is null || window.IsDisposed)
                    {
                        window = new StatusForm();
                        window.Show();
                    }
                    else
                    {
                        if (window.WindowState == FormWindowState.Minimized) window.WindowState = FormWindowState.Normal;
                        window.Activate();
                    }
                }
                menu.Items.Add("حالة الطباعة / Print status", null, (_, _) => ShowStatus());
                icon.DoubleClick += (_, _) => ShowStatus();
                lock (gate)
                {
                    if (disposed) return;
                    dispatcher = dispatch;
                    context = loop;
                    icon.Visible = true;
                    poll.Start();
                }
                try { Application.Run(loop); }
                finally
                {
                    poll.Stop();
                    icon.Visible = false;
                    window?.Dispose();
                    lock (gate) { dispatcher = null; context = null; }
                }
            }
            catch
            {
                // Optional shell UI cannot prevent the worker from printing.
            }
        }

        public void Dispose()
        {
            lock (gate)
            {
                disposed = true;
                try
                {
                    var loop = context;
                    if (dispatcher is { IsDisposed: false } dispatch && loop is not null)
                        dispatch.BeginInvoke((Action)(() => loop.ExitThread()));
                }
                catch { /* The UI thread may already have exited. */ }
            }
        }
    }

    private static bool IsError(string code) => code is "printer_offline" or "invalid_receipt"
        or "print_failed" or "outcome_unknown" or "ack_failed" or "recovery_unknown"
        or "connection_failed" or "runtime_busy" or "queue_unavailable" or "queue_paperout"
        or "queue_paused" or "queue_error" or "queue_deleted" or "diagnostics_error" or "process_failed"
        or "storage_failed" or "protocol_failed" or "prepare_failed";

    public static int Run()
    {
        var result = 0;
        var thread = new Thread(() =>
        {
            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                using var window = new StatusForm();
                Application.Run(window);
            }
            catch
            {
                result = 1;
                MessageBox.Show("تعذّر فتح حالة الطباعة. أعد فتحها من قائمة ابدأ.\nPrint status could not open. Reopen it from Start.",
                    "بصير / Baseer", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        return result;
    }

    private sealed class StatusForm : Form
    {
        private readonly Label connection = StatusLabel();
        private readonly Label lastJob = StatusLabel();
        private readonly Label capture = StatusLabel();
        private readonly TextBox detail = new() {
            Multiline = true, ReadOnly = true, Dock = DockStyle.Fill,
            ScrollBars = ScrollBars.Vertical, BorderStyle = BorderStyle.FixedSingle,
            AccessibleName = "تفاصيل الحدث والخطوة المقترحة / Event and suggested action",
        };
        private readonly DataGridView events = new() {
            Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false,
            AllowUserToDeleteRows = false, AllowUserToResizeRows = false,
            AutoGenerateColumns = false, MultiSelect = false,
            SelectionMode = DataGridViewSelectionMode.FullRowSelect,
            RowHeadersVisible = false, BackgroundColor = SystemColors.Window,
            BorderStyle = BorderStyle.FixedSingle, AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill,
            AccessibleName = "آخر أحداث الطباعة / Recent print events",
        };
        private readonly System.Windows.Forms.Timer timer = new() { Interval = 3000 };
        private bool refreshing;

        public StatusForm()
        {
            Text = "حالة طباعة بصير / Baseer Print Status";
            Width = 1000;
            Height = 760;
            MinimumSize = new Size(720, 560);
            StartPosition = FormStartPosition.CenterScreen;
            AutoScaleMode = AutoScaleMode.Dpi;
            Font = new Font("Segoe UI", 10f);
            RightToLeft = RightToLeft.Yes;
            RightToLeftLayout = true;

            var layout = new TableLayoutPanel {
                Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 8,
                Padding = new Padding(18), AutoSize = false,
            };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 115));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            var title = StatusLabel();
            title.Font = new Font(Font, FontStyle.Bold);
            title.Text = "تشخيص الطباعة / Print diagnostics — " + AgentBuild.Version;
            layout.Controls.Add(title, 0, 0);
            layout.Controls.Add(connection, 0, 1);
            layout.Controls.Add(lastJob, 0, 2);
            var boundary = StatusLabel();
            boundary.Text = "قبول Windows لا يؤكد خروج الورقة. لا تُعد الطباعة عند غموض النتيجة قبل فحص الورق والطابور.\nWindows acceptance does not confirm paper output. Check paper and queue before reprinting an uncertain job.";
            layout.Controls.Add(boundary, 0, 3);

            AddColumn("Time", "الوقت UTC / Time", 23);
            AddColumn("Job", "المهمة / Job", 12);
            AddColumn("Stage", "المرحلة / Stage", 24);
            AddColumn("Description", "الحالة / Status", 41);
            events.SelectionChanged += (_, _) => ShowSelected();
            layout.Controls.Add(events, 0, 4);
            layout.Controls.Add(detail, 0, 5);
            layout.Controls.Add(capture, 0, 6);

            var actions = new FlowLayoutPanel {
                Dock = DockStyle.Fill, AutoSize = true, WrapContents = true,
                FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(0, 8, 0, 0),
            };
            var refresh = ActionButton("تحديث / Refresh");
            refresh.Click += (_, _) => RefreshEvents();
            var export = ActionButton("تصدير تقرير الدعم / Export report");
            export.Click += async (_, _) => await ExportAsync(export);
            var arm = ActionButton("التقاط 3 مهام / Capture 3 jobs");
            arm.Click += (_, _) => ArmCapture();
            actions.Controls.AddRange([refresh, export, arm]);
            layout.Controls.Add(actions, 0, 7);
            Controls.Add(layout);
            timer.Tick += (_, _) => RefreshEvents();
            Shown += (_, _) => { RefreshEvents(); timer.Start(); };
            FormClosed += (_, _) => timer.Stop();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) timer.Dispose();
            base.Dispose(disposing);
        }

        private static Label StatusLabel() => new() {
            AutoSize = true, Dock = DockStyle.Fill, Padding = new Padding(0, 3, 0, 5),
            UseMnemonic = false, MaximumSize = new Size(0, 0),
        };

        private static Button ActionButton(string text) => new() {
            Text = text, AutoSize = true, MinimumSize = new Size(140, 40),
            Padding = new Padding(10, 5, 10, 5), Margin = new Padding(4),
            UseVisualStyleBackColor = true, AccessibleName = text,
        };

        private void AddColumn(string name, string header, float weight) =>
            events.Columns.Add(new DataGridViewTextBoxColumn {
                Name = name, HeaderText = header, FillWeight = weight,
                MinimumWidth = name == "Time" ? 190 : name == "Job" ? 64 : 80,
                SortMode = DataGridViewColumnSortMode.NotSortable,
            });

        private void RefreshEvents()
        {
            if (refreshing) return;
            refreshing = true;
            try
            {
                var rows = AgentDiagnostics.ReadRecent().OrderByDescending(item => item.Utc).Take(200).ToList();
                var selected = events.CurrentRow?.Tag as DiagnosticEvent;
                events.Rows.Clear();
                foreach (var item in rows)
                {
                    var index = events.Rows.Add(
                        "\u200e" + item.Utc.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture) + "\u200e",
                        item.JobId?.ToString(CultureInfo.InvariantCulture) ?? "—", StageLabel(item.Stage),
                        AgentDiagnostics.Describe(item.Code, true));
                    events.Rows[index].Tag = item;
                    if (IsError(item.Code)) events.Rows[index].DefaultCellStyle.ForeColor = Color.Maroon;
                }
                var heartbeat = rows.FirstOrDefault(item => item.Stage == "connection" && item.Code == "heartbeat");
                if (heartbeat is null)
                    connection.Text = "الاتصال: لا يوجد تأكيد حديث متاح / Connection: no recent confirmation available";
                else
                {
                    var age = DateTimeOffset.UtcNow - heartbeat.Utc;
                    connection.Text = age >= TimeSpan.Zero && age <= TimeSpan.FromSeconds(60)
                        ? "الاتصال: آخر تواصل مع أودو خلال دقيقة / Last Odoo contact within 1 minute"
                        : "الاتصال: التأكيد قديم؛ افحص تشغيل الإيجنت والشبكة / Confirmation is stale; check agent and network";
                }
                var latestError = rows.FirstOrDefault(item => IsError(item.Code));
                var newerIssue = latestError is not null && (heartbeat is null || latestError.Utc > heartbeat.Utc);
                connection.ForeColor = newerIssue ? Color.Maroon : SystemColors.ControlText;
                if (newerIssue)
                    connection.Text += "\nيوجد خطأ أحدث / Newer issue: " + AgentDiagnostics.Describe(latestError!.Code, true)
                        + " / " + AgentDiagnostics.Describe(latestError.Code, false);
                var job = rows.FirstOrDefault(item => item.JobId is not null);
                lastJob.Text = job is null
                    ? "لا توجد مهمة مسجلة بعد / No recorded job yet"
                    : "آخر مهمة / Last job: " + job.JobId!.Value.ToString(CultureInfo.InvariantCulture)
                        + " — " + StageLabel(job.Stage) + " — " + AgentDiagnostics.Describe(job.Code, true);
                var captureState = AgentDiagnostics.CaptureStatus();
                var captureArabic = captureState switch { "armed" => "مفعّل", "off" => "متوقف", _ => "غير متاح" };
                capture.Text = "التقاط الصور المحلي / Local image capture: " + captureArabic + " / " + captureState
                    + "\nصور الإيصالات لا تدخل في تقرير الدعم / Receipt images are excluded from the support report";
                if (selected is not null)
                    foreach (DataGridViewRow row in events.Rows)
                        if (row.Tag is DiagnosticEvent item && item.Utc == selected.Utc && item.JobId == selected.JobId
                            && item.Stage == selected.Stage && item.Code == selected.Code)
                        { events.CurrentCell = row.Cells[0]; break; }
                ShowSelected();
            }
            catch
            {
                connection.Text = "تعذّرت قراءة التشخيص الآن؛ الطباعة مستقلة عن هذه النافذة.\nDiagnostics are unavailable; printing operates independently of this window.";
            }
            finally { refreshing = false; }
        }

        private void ShowSelected()
        {
            if (events.CurrentRow?.Tag is not DiagnosticEvent item)
            {
                detail.Text = "اختر حدثًا لعرض تفاصيله والخطوة المقترحة.\nSelect an event for details and the suggested action.";
                return;
            }
            detail.Text = AgentDiagnostics.Describe(item.Code, true) + " / " + AgentDiagnostics.Describe(item.Code, false)
                + "\r\n" + AgentDiagnostics.Action(item.Code, true)
                + "\r\n" + AgentDiagnostics.Action(item.Code, false)
                + "\r\nCode: " + item.Code + " | Stage: " + item.Stage
                + (string.IsNullOrEmpty(item.ExceptionType) ? "" : " | " + item.ExceptionType)
                + (item.HResult is null ? "" : " | HResult: 0x" + item.HResult.Value.ToString("X8", CultureInfo.InvariantCulture))
                + "\r\nWindows job: " + Invariant(item.WindowsJobId)
                + " | Native status: " + (item.NativeStatus is null ? "—" : "0x" + item.NativeStatus.Value.ToString("X8", CultureInfo.InvariantCulture))
                + " | Raster: " + Invariant(item.Width) + " × " + Invariant(item.Height)
                + (string.IsNullOrEmpty(item.Fingerprint) ? "" : "\r\nSHA-256: " + item.Fingerprint);
        }

        private static string Invariant(int? value) => value?.ToString(CultureInfo.InvariantCulture) ?? "—";

        private async Task ExportAsync(Button button)
        {
            using var dialog = new SaveFileDialog {
                Title = "حفظ تقرير الدعم / Save support report", Filter = "ZIP report (*.zip)|*.zip",
                DefaultExt = "zip", AddExtension = true, OverwritePrompt = false,
                FileName = "Baseer-Print-Support-" + DateTime.UtcNow.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture) + ".zip",
            };
            if (dialog.ShowDialog(this) != DialogResult.OK) return;
            if (File.Exists(dialog.FileName))
            {
                MessageBox.Show(this, "يوجد ملف بهذا الاسم. صدّر التقرير باسم جديد للحفاظ على الملف السابق.\nA file with this name exists. Export under a new name to keep the previous file.",
                    Text, MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            button.Enabled = false;
            try
            {
                await Task.Run(() => AgentDiagnostics.Export(dialog.FileName));
                if (!IsDisposed) MessageBox.Show(this,
                    "تم حفظ التقرير دون مفاتيح الربط أو صور الإيصالات.\nReport saved without pairing secrets or receipt images.",
                    Text, MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            catch
            {
                if (!IsDisposed) MessageBox.Show(this,
                    "تعذّر حفظ التقرير. اختر مجلدًا يمكنك الكتابة فيه وتأكد من المساحة المتاحة.\nCould not save the report. Choose a writable folder and check free space.",
                    Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            finally { if (!IsDisposed) button.Enabled = true; }
        }

        private void ArmCapture()
        {
            var consent = MessageBox.Show(this,
                "سيُحفظ الأصل والصورة المعالجة محليًا للمهام الثلاث التالية خلال 15 دقيقة، حتى 20 MiB. قد تحتوي الصور أسماء وأرقام عملاء. تُحذف بعد 24 ساعة عند تشغيل التشخيص، ولا تدخل في تقرير الدعم.\n\nThis saves original and processed receipt images locally for the next 3 jobs within 15 minutes, up to 20 MiB. Images may contain customer names and phone numbers. Cleanup runs after 24 hours when diagnostics run. Images are excluded from the support report.\n\nتفعيل الالتقاط؟ / Enable capture?",
                "التقاط تشخيصي اختياري / Optional diagnostic capture", MessageBoxButtons.YesNo, MessageBoxIcon.Warning,
                MessageBoxDefaultButton.Button2);
            if (consent != DialogResult.Yes) return;
            if (!AgentDiagnostics.ArmCapture())
                MessageBox.Show(this, "تعذّر تفعيل الالتقاط الآن. حاول مجددًا.\nCapture could not be enabled. Try again.",
                    Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            RefreshEvents();
        }

        private static string StageLabel(string stage) => stage switch {
            "start" => "تشغيل / Runtime",
            "connection" => "اتصال أودو / Odoo contact",
            "claim" => "استلام المهمة / Claim",
            "persist" => "حفظ المهمة / Saved",
            "validate" => "التحقق / Validate",
            "prepare" => "تجهيز الصورة / Raster",
            "submit" => "إرسال Windows / Submit",
            "queue" => "طابور Windows / Queue",
            "ack" => "إبلاغ أودو / Acknowledge",
            "recovery" => "استعادة / Recovery",
            "capture" => "التقاط تشخيصي / Capture",
            "update" => "تحديث / Update",
            _ => stage,
        };
    }
}

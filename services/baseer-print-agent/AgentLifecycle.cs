using System.Diagnostics;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using System.Windows.Forms;
using Microsoft.Win32;

static class AgentBuild
{
    public const string Version = "1.5.12";
}

static class AgentLog
{
    private static readonly string Path = System.IO.Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
        "BaseerPrintAgent", "agent.log");

    /// <summary>Keep background diagnostics available without a console window.</summary>
    public static void Write(string message)
    {
        try
        {
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(Path)!);
            File.AppendAllText(Path, $"{DateTime.UtcNow:O} {message}{Environment.NewLine}");
        }
        catch
        {
            // Logging must never stop receipt printing or recovery.
        }
    }
}

static class AgentRuntime
{
    public const string WatchdogMutexName = @"Global\BaseerPrintAgent.Watchdog";
    public const string RunnerMutexName = @"Global\BaseerPrintAgent.Runner";
    public static readonly string InstanceId = Guid.NewGuid().ToString("N");

    private static string RuntimePath(string configPath) => Path.Combine(
        Path.GetDirectoryName(configPath) ?? throw new InvalidOperationException("Agent configuration directory is unavailable."),
        "runtime.id");

    public static void WriteCurrentId(string configPath)
    {
        var path = RuntimePath(configPath);
        var temporaryPath = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllText(temporaryPath, InstanceId);
            File.Move(temporaryPath, path, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporaryPath)) File.Delete(temporaryPath);
        }
    }

    public static string? ReadCurrentId(string configPath)
    {
        var path = RuntimePath(configPath);
        if (!File.Exists(path)) return null;
        var value = File.ReadAllText(path).Trim();
        return value.Length is >= 16 and <= 128 ? value : null;
    }

    public static void ClearCurrentId(string configPath)
    {
        var path = RuntimePath(configPath);
        if (!File.Exists(path)) return;
        // A newer process may have already published its own identity.
        if (string.Equals(File.ReadAllText(path).Trim(), InstanceId, StringComparison.Ordinal))
            File.Delete(path);
    }
}

sealed class AgentBootstrap
{
    public string ServerUrl { get; init; } = "";
    public string PairingCode { get; init; } = "";
}

/// <summary>
/// Reads a short-lived setup envelope appended by Odoo to an approved EXE.
/// It is deliberately not a second config file: copying the EXE preserves the
/// envelope through elevation, while an existing protected config always wins.
/// </summary>
static class AgentBootstrapEnvelope
{
    private static readonly byte[] Magic = Encoding.ASCII.GetBytes("BASEER-BOOTSTRAP-V1");
    private const int MaxEnvelopeBytes = 4096;

    public static bool TryRead(string executablePath, out AgentBootstrap bootstrap)
    {
        bootstrap = new AgentBootstrap();
        try
        {
            using var stream = new FileStream(executablePath, FileMode.Open, FileAccess.Read, FileShare.Read);
            if (stream.Length < Magic.Length + sizeof(int)) return false;
            stream.Position = stream.Length - Magic.Length;
            var tail = new byte[Magic.Length];
            if (stream.Read(tail, 0, tail.Length) != tail.Length || !tail.AsSpan().SequenceEqual(Magic)) return false;
            stream.Position = stream.Length - Magic.Length - sizeof(int);
            var sizeBytes = new byte[sizeof(int)];
            if (stream.Read(sizeBytes, 0, sizeBytes.Length) != sizeBytes.Length) return false;
            var size = BitConverter.ToInt32(sizeBytes, 0);
            if (size is < 1 or > MaxEnvelopeBytes || stream.Length < Magic.Length + sizeof(int) + size) return false;
            stream.Position = stream.Length - Magic.Length - sizeof(int) - size;
            var json = new byte[size];
            if (stream.Read(json, 0, json.Length) != json.Length) return false;
            var candidate = JsonSerializer.Deserialize<AgentBootstrap>(json);
            if (candidate is null || string.IsNullOrWhiteSpace(candidate.ServerUrl)
                || string.IsNullOrWhiteSpace(candidate.PairingCode)) return false;
            AgentConfig.SecureBaseUri(candidate.ServerUrl);
            bootstrap = candidate;
            return true;
        }
        catch
        {
            // A normal release has no envelope.  Malformed downloads must
            // never fall through to a partially trusted automatic pairing.
            return false;
        }
    }
}

/// <summary>
/// Windows lifecycle owner for the interactive print process.  The print
/// process intentionally remains outside a Windows Service because the current
/// System.Drawing.Printing implementation requires an interactive user context.
/// </summary>
static class AgentLifecycle
{
    private const string ProductFolder = "Baseer Print Agent";
    private const string TaskName = "Baseer Print Agent";

    private static string InstallDirectory => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), ProductFolder);

    private static string InstalledExecutable => Path.Combine(InstallDirectory, "Baseer.PrintAgent.exe");

    public static bool IsInstalled(string executablePath) => string.Equals(
        Path.GetFullPath(executablePath), Path.GetFullPath(InstalledExecutable), StringComparison.OrdinalIgnoreCase);

    public static int BeginFirstInstall(string executablePath)
    {
        var result = MessageBox.Show(
            "سيتم تثبيت وكيل طباعة بصير على هذا الكمبيوتر. سيعمل تلقائيًا بعد تسجيل الدخول ويمكن إصلاحه من نقاط البيع. متابعة؟\n\nBaseer will install the print agent on this Windows computer. It starts automatically after sign-in and can be repaired from Point of Sale. Continue?",
            "Baseer Print Agent", MessageBoxButtons.YesNo, MessageBoxIcon.Information);
        if (result != DialogResult.Yes)
            return 0;
        return RelaunchElevated(executablePath, "install");
    }

    public static int Install(string sourceExecutable)
    {
        if (!IsAdministrator())
            return RelaunchElevated(sourceExecutable, "install");

        Directory.CreateDirectory(InstallDirectory);
        StopPreviousAgents();
        File.Copy(sourceExecutable, InstalledExecutable, overwrite: true);
        RegisterRepairProtocol(InstalledExecutable);
        RegisterLogonTask(InstalledExecutable);
        var configPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "BaseerPrintAgent", "config.json");
        // An upgrade must retain the existing one-time pairing.  Opening the
        // pairing window here would invite an unnecessary second pairing and
        // can create a competing configuration.
        if (File.Exists(configPath))
        {
            EnsureWatchdog(InstalledExecutable);
            return 0;
        }
        Process.Start(new ProcessStartInfo(InstalledExecutable, "pair-ui") { UseShellExecute = true });
        return 0;
    }

    /// <summary>
    /// The elevated installer owns a controlled handover.  It stops only
    /// existing Baseer agent processes, never a printer spooler or unrelated
    /// Windows process, before replacing the installed executable.
    /// </summary>
    private static void StopPreviousAgents()
    {
        var currentProcessId = Environment.ProcessId;
        foreach (var process in Process.GetProcessesByName("Baseer.PrintAgent"))
        {
            using (process)
            {
                if (process.Id == currentProcessId)
                    continue;
                try
                {
                    process.Kill(entireProcessTree: true);
                    process.WaitForExit(10_000);
                }
                catch (Exception error)
                {
                    throw new InvalidOperationException(
                        "The existing Baseer print agent could not be stopped. Finish any active print and run the installer again.", error);
                }
            }
        }
    }

    public static int Repair(string executablePath, string configPath)
    {
        if (!File.Exists(configPath))
            return ShowPairingWindow(configPath, executablePath);

        // The repair protocol is launched by a browser as the signed-in user,
        // while the watchdog can be owned by a different/elevated session.
        // Named global event handles inherit the creator's ACL, which made the
        // previous signal-only repair path fail with UnauthorizedAccessException.
        // Use the same controlled, elevated handover as an upgrade instead:
        // one supervisor and one worker are restarted without crossing an ACL.
        if (!IsAdministrator())
            return RelaunchElevated(executablePath, "repair", "Administrator permission is required to repair the Baseer print agent.");

        ReleaseLocalRuntime(configPath);
        StopPreviousAgents();
        RegisterLogonTask(executablePath);
        EnsureWatchdog(executablePath);
        return 0;
    }

    /// <summary>
    /// A deliberate, elevated repair may release only the exact runtime ID
    /// written by the local runner.  A copied config does not carry authority
    /// to release another computer's active lease; a failed release falls back
    /// to the normal server-side 90-second takeover protection.
    /// </summary>
    private static void ReleaseLocalRuntime(string configPath)
    {
        try
        {
            var runtimeId = AgentRuntime.ReadCurrentId(configPath);
            if (string.IsNullOrEmpty(runtimeId))
                return;
            var config = AgentConfig.Load(configPath);
            using var http = new HttpClient { BaseAddress = AgentConfig.SecureBaseUri(config.ServerUrl), Timeout = TimeSpan.FromSeconds(10) };
            http.DefaultRequestHeaders.Authorization = new("Bearer", config.Token);
            using var response = http.PostAsync("baseer/print/v1/runtime/release", AgentConfig.JsonContent(new { runtime_id = runtimeId }))
                .GetAwaiter().GetResult();
            if (!response.IsSuccessStatusCode)
                AgentLog.Write($"Controlled runtime release was not accepted: {(int)response.StatusCode}.");
        }
        catch (Exception error)
        {
            // Never make repair dependent on the network.  If this cannot be
            // confirmed, normal lease expiry remains the safe fallback.
            AgentLog.Write($"Controlled runtime release was unavailable: {error.Message}");
        }
    }

    public static int Watch(string executablePath, string configPath)
    {
        using var mutex = new Mutex(false, AgentRuntime.WatchdogMutexName);
        var ownsMutex = false;
        try
        {
            ownsMutex = mutex.WaitOne(0);
        }
        catch (AbandonedMutexException)
        {
            // A crashed watchdog must not prevent the next startup.
            ownsMutex = true;
        }
        if (!ownsMutex)
            return 0;
        try
        {
            var retryDelays = new[] { 2000, 5000, 10000, 30000 };
            var failures = 0;
            while (true)
            {
                if (!File.Exists(configPath))
                    return 2;
                try
                {
                    using var agent = Process.Start(new ProcessStartInfo(executablePath, "run") {
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        WindowStyle = ProcessWindowStyle.Hidden,
                    }) ?? throw new InvalidOperationException("The print agent could not be started.");
                    agent.WaitForExit();
                }
                catch (Exception error)
                {
                    // A transient launch failure must be supervised just like an
                    // agent exit; otherwise a bad first launch defeats recovery.
                    AgentLog.Write($"Launcher: {error.Message}");
                }
                var delay = retryDelays[Math.Min(failures++, retryDelays.Length - 1)];
                Thread.Sleep(delay);
            }
        }
        finally
        {
            mutex.ReleaseMutex();
        }
    }

    public static int ShowPairingWindow(string configPath, string executablePath)
    {
        AgentStorage.EnsureProtectedDirectory(Path.GetDirectoryName(configPath)!);
        if (AgentBootstrapEnvelope.TryRead(executablePath, out var bootstrap))
            return PairBootstrap(configPath, executablePath, bootstrap);
        Application.EnableVisualStyles();
        using var form = new Form {
            Text = "Baseer Print Agent",
            Width = 560,
            Height = 360,
            StartPosition = FormStartPosition.CenterScreen,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            MaximizeBox = false,
            MinimizeBox = false,
        };
        var title = new Label {
            Left = 24, Top = 20, Width = 500, Height = 46,
            Text = "اربط جهاز الطابعة مرة واحدة؛ بعدها سيبدأ الوكيل تلقائيًا مع Windows.\nPair this printer computer once. The agent will then start automatically with Windows.",
            Font = new System.Drawing.Font(System.Drawing.SystemFonts.DefaultFont, System.Drawing.FontStyle.Bold),
        };
        var server = AddTextBox(form, "عنوان أودو HTTPS / Odoo HTTPS address", "", 88);
        var code = AddTextBox(form, "رمز الربط لمرة واحدة / One-time pairing code", "", 152);
        code.UseSystemPasswordChar = true;
        var pair = new Button { Left = 312, Top = 236, Width = 210, Height = 38, Text = "ربط وبدء الوكيل / Pair and start" };
        var cancel = new Button { Left = 208, Top = 236, Width = 92, Height = 38, Text = "إلغاء / Cancel", DialogResult = DialogResult.Cancel };
        form.Controls.AddRange([title, pair, cancel]);
        form.AcceptButton = pair;
        form.CancelButton = cancel;
        pair.Click += async (_, _) =>
        {
            pair.Enabled = false;
            try
            {
                var deviceUid = "BASEER-" + Environment.MachineName.ToUpperInvariant();
                var paired = await AgentConfig.PairAsync(server.Text.Trim(), deviceUid, code.Text.Trim());
                AgentConfig.Save(configPath, paired);
                EnsureWatchdog(executablePath);
                MessageBox.Show("تم ربط وكيل طباعة بصير وهو يعمل الآن.\nThe Baseer print agent is paired and running.", "Baseer Print Agent", MessageBoxButtons.OK, MessageBoxIcon.Information);
                form.DialogResult = DialogResult.OK;
                form.Close();
            }
            catch (Exception error)
            {
                MessageBox.Show(error.Message, "لم يكتمل الربط / Pairing was not completed", MessageBoxButtons.OK, MessageBoxIcon.Error);
                pair.Enabled = true;
            }
        };
        return form.ShowDialog() == DialogResult.OK ? 0 : 1;
    }

    private static int PairBootstrap(string configPath, string executablePath, AgentBootstrap bootstrap)
    {
        try
        {
            var deviceUid = "BASEER-" + Environment.MachineName.ToUpperInvariant();
            var paired = AgentConfig.PairAsync(bootstrap.ServerUrl, deviceUid, bootstrap.PairingCode)
                .GetAwaiter().GetResult();
            AgentConfig.Save(configPath, paired);
            EnsureWatchdog(executablePath);
            MessageBox.Show(
                "تم تثبيت وربط وكيل طباعة بصير وهو يعمل الآن.\nThe Baseer print agent is installed, connected and running.",
                "Baseer Print Agent", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 0;
        }
        catch (Exception error)
        {
            AgentLog.Write($"Automatic setup was not completed: {error.Message}");
            MessageBox.Show(
                "لم يكتمل الربط التلقائي. ارجع إلى أودو ونزّل ملف ربط جديداً.\nAutomatic connection was not completed. Return to Odoo and download a new connection file.",
                "Baseer Print Agent", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
    }

    private static TextBox AddTextBox(Form form, string label, string value, int top)
    {
        form.Controls.Add(new Label { Left = 24, Top = top, Width = 500, Height = 20, Text = label });
        var input = new TextBox { Left = 24, Top = top + 22, Width = 498, Text = value };
        form.Controls.Add(input);
        return input;
    }

    private static void EnsureWatchdog(string executablePath)
    {
        Process.Start(new ProcessStartInfo(executablePath, "watch") {
            UseShellExecute = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        });
    }

    private static int RelaunchElevated(string executablePath, string arguments, string? deniedMessage = null)
    {
        try
        {
            Process.Start(new ProcessStartInfo(executablePath, arguments) {
                UseShellExecute = true,
                Verb = "runas",
            });
            return 0;
        }
        catch (System.ComponentModel.Win32Exception)
        {
            MessageBox.Show(deniedMessage ?? "Administrator permission is required to install the Baseer print agent.", "Baseer Print Agent", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
    }

    private static bool IsAdministrator()
    {
        using var identity = WindowsIdentity.GetCurrent();
        return new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator);
    }

    private static void RegisterRepairProtocol(string executablePath)
    {
        using var key = Registry.LocalMachine.CreateSubKey(@"Software\Classes\baseer-print");
        key!.SetValue(string.Empty, "URL:Baseer Print Agent");
        key.SetValue("URL Protocol", string.Empty);
        using var command = key.CreateSubKey(@"shell\open\command");
        command!.SetValue(string.Empty, $"\"{executablePath}\" repair");
    }

    private static void RegisterLogonTask(string executablePath)
    {
        var info = new ProcessStartInfo("schtasks.exe") {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardError = true,
            RedirectStandardOutput = true,
        };
        info.ArgumentList.Add("/Create");
        info.ArgumentList.Add("/TN");
        info.ArgumentList.Add(TaskName);
        info.ArgumentList.Add("/SC");
        info.ArgumentList.Add("ONLOGON");
        info.ArgumentList.Add("/TR");
        info.ArgumentList.Add($"\"{executablePath}\" watch");
        info.ArgumentList.Add("/RL");
        info.ArgumentList.Add("LIMITED");
        info.ArgumentList.Add("/F");
        using var task = Process.Start(info) ?? throw new InvalidOperationException("Windows Task Scheduler could not be started.");
        task.WaitForExit();
        if (task.ExitCode != 0)
            throw new InvalidOperationException("Windows could not register automatic agent startup. " + task.StandardError.ReadToEnd().Trim());
    }
}

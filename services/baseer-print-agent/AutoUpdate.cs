using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;
using System.Text.Json.Serialization;

sealed record AgentUpdate(
    [property: JsonPropertyName("version")] string Version,
    [property: JsonPropertyName("download_url")] string DownloadUrl,
    [property: JsonPropertyName("sha256")] string Sha256);

static class AutoUpdate
{
    public const int StagedExit = 42;
    public static TimeSpan CheckInterval
    {
        get
        {
#if QA_PROFILE
            if (File.Exists(Path.Combine(Root, "qa-offer.json")))
                return TimeSpan.FromSeconds(5);
#endif
            return TimeSpan.FromHours(6) + TimeSpan.FromMinutes(Random.Shared.Next(15));
        }
    }
    private const long MaxBytes = 256L * 1024 * 1024;
#if QA_PROFILE
    private static string Root => Path.Combine(AgentRuntime.DataDirectory, "updates-v2");
    private const string WorkerFilename = "Baseer.PrintAgent.QA.exe";
#else
    private static string Root => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "BaseerPrintAgent", "updates-v2", _pairingScope
        ?? throw new InvalidOperationException("Update profile is not initialized."));
    private static string? _pairingScope;
    private const string WorkerFilename = "Baseer.PrintAgent.exe";
#endif

    public static void InitializeProfile(AgentConfig config)
    {
#if !QA_PROFILE
        var identity = $"{AgentConfig.SecureBaseUri(config.ServerUrl).AbsoluteUri}\n{config.DeviceUid}";
        _pairingScope = Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(identity)));
#endif
    }

    public static bool IsLimitedUser()
    {
        using var identity = WindowsIdentity.GetCurrent();
        var sid = identity.User;
        return sid is not null && !identity.IsSystem
            && !sid.IsWellKnown(WellKnownSidType.LocalServiceSid)
            && !sid.IsWellKnown(WellKnownSidType.NetworkServiceSid)
            && !new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator)
            && GetTokenInformation(identity.AccessToken, 20, out var elevated, sizeof(int), out _)
            && elevated == 0;
    }

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetTokenInformation(
        Microsoft.Win32.SafeHandles.SafeAccessTokenHandle token, int informationClass,
        out int information, int informationLength, out int returnLength);

    private static bool Valid(AgentUpdate? update)
    {
        if (update is null || !Version.TryParse(update.Version, out var version)
            || version.Build < 0 || version.Revision >= 0 || version.ToString() != update.Version
            || update.Sha256 is not { Length: 64 } || !update.Sha256.All(Uri.IsHexDigit))
            return false;
        return update.DownloadUrl == "https://github.com/hajrix01-star/abroj-baseer-production/releases/download/"
            + $"baseer-print-agent-{update.Version}/Baseer.PrintAgent.exe";
    }

    private static string Binary(AgentUpdate update) =>
        Path.Combine(Root, $"{update.Version}-{update.Sha256.ToLowerInvariant()}", WorkerFilename);

    private static AgentUpdate? Read(string name)
    {
        var path = Path.Combine(Root, name);
        if (!File.Exists(path)) return null;
        var value = JsonSerializer.Deserialize<AgentUpdate>(File.ReadAllText(path));
        return Valid(value) ? value : null;
    }

    private static void Write(string name, AgentUpdate? update)
    {
        Directory.CreateDirectory(Root);
        var path = Path.Combine(Root, name);
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllText(temporary, JsonSerializer.Serialize(update));
            File.Move(temporary, path, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporary)) File.Delete(temporary);
        }
    }

    public static async Task<AgentUpdate?> StageAsync(HttpClient server)
    {
        if (!IsLimitedUser()) return null;
        try
        {
#if QA_PROFILE
            // Test-only local offer. The QA binary uses isolated credentials,
            // process names and storage and cannot enter the Windows installer.
            var localOffer = Read("qa-offer.json");
            if (localOffer is not null)
                return IsNewOffer(localOffer) && Verified(localOffer) ? localOffer : null;
#endif
            using var response = await server.GetAsync("baseer/print/v2/update/manifest");
            response.EnsureSuccessStatusCode();
            using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            var candidate = document.RootElement.GetProperty("update").Deserialize<AgentUpdate>();
            if (candidate is null || !IsNewOffer(candidate))
                return null;
            var path = Binary(candidate);
            if (!Verified(candidate))
                await DownloadAsync(candidate, path);
            return candidate;
        }
        catch (Exception error)
        {
            AgentLog.Write($"Update download deferred ({error.GetType().Name}).");
            return null;
        }
    }

    private static bool IsNewOffer(AgentUpdate candidate) =>
        Valid(candidate) && Version.Parse(candidate.Version) > Version.Parse(AgentBuild.Version)
        && candidate != Read("rejected.json");

    private static async Task DownloadAsync(AgentUpdate update, string path)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var partial = path + "." + Guid.NewGuid().ToString("N") + ".download";
        using var deadline = new CancellationTokenSource(TimeSpan.FromMinutes(5));
        using var client = new HttpClient();
        try
        {
            // Separate client: the Odoo pairing token is never sent to GitHub.
            using var response = await client.GetAsync(update.DownloadUrl,
                HttpCompletionOption.ResponseHeadersRead, deadline.Token);
            response.EnsureSuccessStatusCode();
            if (response.Content.Headers.ContentLength is > MaxBytes)
                throw new InvalidDataException("Agent update exceeds the download limit.");
            using var input = await response.Content.ReadAsStreamAsync(deadline.Token);
            await using (var output = new FileStream(partial, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                var buffer = new byte[64 * 1024];
                int count;
                while ((count = await input.ReadAsync(buffer, deadline.Token)) != 0)
                {
                    if (output.Length + count > MaxBytes)
                        throw new InvalidDataException("Agent update exceeds the download limit.");
                    await output.WriteAsync(buffer.AsMemory(0, count), deadline.Token);
                }
            }
            if (!Verified(update, partial))
                throw new InvalidDataException("Agent update version or SHA-256 does not match.");
            File.Move(partial, path, overwrite: true);
        }
        finally
        {
            if (File.Exists(partial)) File.Delete(partial);
        }
    }

    private static bool Verified(AgentUpdate update, string? path = null)
    {
        path ??= Binary(update);
        if (!File.Exists(path)) return false;
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length is <= 0 or > MaxBytes
            || !CryptographicOperations.FixedTimeEquals(SHA256.HashData(stream), Convert.FromHexString(update.Sha256)))
            return false;
        var fileVersion = FileVersionInfo.GetVersionInfo(path);
        return $"{fileVersion.FileMajorPart}.{fileVersion.FileMinorPart}.{fileVersion.FileBuildPart}" == update.Version;
    }

    public static void Queue(AgentUpdate update) => Write("pending.json", update);

    public static void Watch(string installed, string configPath)
    {
#if QA_PROFILE
        var limited = IsLimitedUser();
#else
        var limited = AgentLifecycle.IsInstalled(installed) && IsLimitedUser();
#endif
        var session = Guid.NewGuid().ToString("N");
        AgentUpdate? active = null;
        AgentUpdate? fallback = null;
        Process? running = null;
        var failures = 0;
        if (limited)
        {
            try
            {
                InitializeProfile(AgentConfig.Load(configPath));
                active = Read("active.json");
                if (active is not null && Version.Parse(active.Version) <= Version.Parse(AgentBuild.Version))
                    active = null;
                if (active is not null)
                {
                    fallback = Read("previous.json");
                    if (fallback is not null && Version.Parse(fallback.Version) >= Version.Parse(active.Version))
                        fallback = null;
                }
            }
            catch (Exception error) { AgentLog.Write($"Update selection ignored ({error.GetType().Name})."); }
        }
        while (File.Exists(configPath))
        {
            try
            {
                using var worker = running ?? StartWorker(installed, active, session, limited);
                running = null;
                worker.WaitForExit();
                var result = worker.ExitCode;
                if (limited && result == StagedExit)
                {
                    var candidate = Read("pending.json");
                    Write("pending.json", null);
                    var currentVersion = Version.Parse(active?.Version ?? AgentBuild.Version);
                    if (candidate is not null && Version.Parse(candidate.Version) > currentVersion
                        && candidate != Read("rejected.json") && Verified(candidate))
                    {
                        try
                        {
                            running = Trial(candidate, active, session);
                        }
                        catch (Exception error)
                        {
                            AgentLog.Write($"Update trial failed ({error.GetType().Name}).");
                        }
                        if (running is null)
                        {
                            Write("active.json", active);
                            Write("rejected.json", candidate);
                            AgentLog.Write($"Update {candidate.Version} rejected. Resuming {active?.Version ?? AgentBuild.Version}.");
                        }
                        else
                        {
                            fallback = active;
                            active = candidate;
                        }
                    }
                    continue;
                }
            }
            catch (Exception error)
            {
                AgentLog.Write($"Print supervisor recovery ({error.GetType().Name}).");
            }
            // A verified worker that subsequently exits unexpectedly gives
            // way to the prior worker or the immutable installed worker.
            if (active is not null)
            {
                var rejected = active;
                active = fallback;
                fallback = null;
                try
                {
                    Write("active.json", active);
                    Write("rejected.json", rejected);
                }
                catch (Exception error) { AgentLog.Write($"Could not persist recovery ({error.GetType().Name})."); }
                continue;
            }
            Thread.Sleep(Math.Min(++failures, 6) * 1000);
        }
    }

    private static Process StartWorker(string installed, AgentUpdate? active, string session, bool limited)
    {
        if (active is not null && !Verified(active))
            throw new InvalidDataException("The active worker does not match the approved release.");
        return Start(active is null ? installed : Binary(active),
            limited ? ["run-supervised", session] : ["run"]);
    }

    private static Process? Trial(AgentUpdate candidate, AgentUpdate? previous, string session)
    {
        var key = Guid.NewGuid().ToString("N");
        using var ready = new EventWaitHandle(false, EventResetMode.ManualReset, Ready(key));
        using var proceed = new EventWaitHandle(false, EventResetMode.ManualReset, Proceed(key));
        var worker = Start(Binary(candidate), ["run-supervised", session, key]);
        var timer = Stopwatch.StartNew();
        var accepted = false;
        try
        {
            while (timer.Elapsed < TimeSpan.FromSeconds(45) && !worker.HasExited)
            {
                if (!ready.WaitOne(100)) continue;
                Write("previous.json", previous);
                Write("active.json", candidate);
                proceed.Set();
                accepted = true;
                AgentLog.Write($"Update {candidate.Version} passed startup checks.");
                return worker;
            }
            return null;
        }
        finally
        {
            // No print job can have been claimed before the proceed signal.
            if (!accepted)
            {
                using (worker)
                {
                    if (!worker.HasExited)
                    {
                        try { worker.Kill(); }
                        catch (InvalidOperationException) when (worker.HasExited) { }
                        finally { worker.WaitForExit(); }
                    }
                }
            }
        }
    }

    private static Process Start(string path, string[] arguments)
    {
        var info = new ProcessStartInfo(path) { UseShellExecute = false, CreateNoWindow = true };
        foreach (var argument in arguments) info.ArgumentList.Add(argument);
        return Process.Start(info) ?? throw new InvalidOperationException("Windows could not start the print worker.");
    }

    private static string Ready(string key) => @"Local\BaseerPrintAgent.Ready." + key;
    private static string Proceed(string key) => @"Local\BaseerPrintAgent.Proceed." + key;

    public static bool ConfirmStartup(string key)
    {
        using var ready = EventWaitHandle.OpenExisting(Ready(key));
        using var proceed = EventWaitHandle.OpenExisting(Proceed(key));
        ready.Set();
        return proceed.WaitOne(TimeSpan.FromSeconds(45));
    }
}

using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;

sealed class AgentUpdateManifest
{
    public string Version { get; set; } = "";
    public string DownloadUrl { get; set; } = "";
    public string Sha256 { get; set; } = "";
}

static class AutoUpdate
{
    private const string UpdateTaskName = "Baseer Print Agent Update";
    private static string Root(string configPath) => Path.GetDirectoryName(configPath)!;
    private static string PendingPath(string configPath) => Path.Combine(Root(configPath), "pending-update.json");

    public static async Task<bool> TryStageAndStartAsync(HttpClient http, string configPath)
    {
        using var response = await http.GetAsync("baseer/print/v1/update/manifest");
        response.EnsureSuccessStatusCode();
        using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        if (!json.RootElement.TryGetProperty("update", out var update) || update.ValueKind == JsonValueKind.Null)
            return false;
        var manifest = JsonSerializer.Deserialize<AgentUpdateManifest>(update) ?? new();
        if (Compare(manifest.Version, AgentBuild.Version) <= 0 || !Valid(manifest)) return false;
        AgentStorage.EnsureProtectedDirectory(Root(configPath));
        var source = Path.Combine(Root(configPath), "update-" + manifest.Version + ".exe");
        var temporary = source + ".download";
        using (var download = new HttpClient { Timeout = TimeSpan.FromMinutes(10) })
        using (var stream = await download.GetStreamAsync(manifest.DownloadUrl))
        using (var file = new FileStream(temporary, FileMode.Create, FileAccess.Write, FileShare.None))
            await stream.CopyToAsync(file);
        if (!string.Equals(Hash(temporary), manifest.Sha256, StringComparison.OrdinalIgnoreCase))
        {
            File.Delete(temporary);
            throw new InvalidOperationException("The approved agent update failed SHA-256 verification.");
        }
        File.Move(temporary, source, true);
        File.WriteAllText(PendingPath(configPath), JsonSerializer.Serialize(manifest));
        var start = Process.Start(new ProcessStartInfo("schtasks.exe", $"/Run /TN \"{UpdateTaskName}\"") { UseShellExecute = false, CreateNoWindow = true });
        if (start is null) throw new InvalidOperationException("Windows could not start the approved agent update.");
        await start.WaitForExitAsync();
        if (start.ExitCode != 0) throw new InvalidOperationException("Windows rejected the approved agent update task.");
        AgentLog.Write($"Agent update {manifest.Version} staged and handed to Windows.");
        return true;
    }

    public static int Apply(string executablePath, string configPath)
    {
        if (!File.Exists(PendingPath(configPath))) return 2;
        var manifest = JsonSerializer.Deserialize<AgentUpdateManifest>(File.ReadAllText(PendingPath(configPath))) ?? new();
        var source = Path.Combine(Root(configPath), "update-" + manifest.Version + ".exe");
        if (!Valid(manifest) || !File.Exists(source) || !string.Equals(Hash(source), manifest.Sha256, StringComparison.OrdinalIgnoreCase)) return 3;
        AgentLifecycle.PrepareForUpdate();
        var script = Path.Combine(Root(configPath), "apply-agent-update.cmd");
        File.WriteAllText(script, "@echo off\r\ntimeout /t 3 /nobreak >nul\r\ncopy /y \"" + source + "\" \"" + executablePath + "\" >nul\r\nschtasks /Run /TN \"Baseer Print Agent\" >nul\r\ndel \"" + PendingPath(configPath) + "\"\r\ndel \"%~f0\"\r\n");
        Process.Start(new ProcessStartInfo("cmd.exe", $"/c \"{script}\"") { UseShellExecute = false, CreateNoWindow = true });
        return 0;
    }

    private static bool Valid(AgentUpdateManifest m) => Uri.TryCreate(m.DownloadUrl, UriKind.Absolute, out var uri)
        && uri.Scheme == Uri.UriSchemeHttps && uri.Host.Equals("github.com", StringComparison.OrdinalIgnoreCase)
        && m.Sha256.Length == 64 && m.Sha256.All(Uri.IsHexDigit) && Version.TryParse(m.Version, out _);
    private static int Compare(string candidate, string current) => Version.TryParse(candidate, out var a) && Version.TryParse(current, out var b) ? a.CompareTo(b) : 0;
    private static string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path)));
}

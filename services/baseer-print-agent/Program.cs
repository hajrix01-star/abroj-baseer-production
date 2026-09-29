using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Printing;
using System.Globalization;
using System.Diagnostics;
using Microsoft.Win32;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Runtime.InteropServices;

var configPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "BaseerPrintAgent", "config.json");
var executablePath = Environment.ProcessPath ?? throw new InvalidOperationException("Agent executable path is unavailable.");

if (args.Length > 0 && args[0].Equals("install", StringComparison.OrdinalIgnoreCase))
    return AgentLifecycle.Install(executablePath);

if (args.Length > 0 && args[0].Equals("watch", StringComparison.OrdinalIgnoreCase))
    return AgentLifecycle.Watch(Environment.ProcessPath ?? throw new InvalidOperationException("Agent executable path is unavailable."), configPath);

if (args.Length > 0 && args[0].Equals("repair", StringComparison.OrdinalIgnoreCase))
    return AgentLifecycle.Repair(Environment.ProcessPath ?? throw new InvalidOperationException("Agent executable path is unavailable."), configPath);

if (args.Length > 0 && args[0].Equals("pair-ui", StringComparison.OrdinalIgnoreCase))
    return AgentLifecycle.ShowPairingWindow(configPath, Environment.ProcessPath ?? throw new InvalidOperationException("Agent executable path is unavailable."));

// A downloaded agent must always become the installed, supervised copy.  In
// particular, an existing pairing must not bypass installation just because
// config.json already exists from an older manual runner.
if (args.Length == 0 && !AgentLifecycle.IsInstalled(executablePath))
{
    return AgentLifecycle.BeginFirstInstall(executablePath);
}

if (args.Length == 0 && !File.Exists(configPath))
{
    return AgentLifecycle.ShowPairingWindow(configPath, executablePath);
}

AgentStorage.EnsureProtectedDirectory(Path.GetDirectoryName(configPath)!);

if (args.Length > 0 && args[0].Equals("pair", StringComparison.OrdinalIgnoreCase))
{
    var options = AgentOptions.FromArguments(args.Skip(1).ToArray());
    if (string.IsNullOrWhiteSpace(options.ServerUrl) || string.IsNullOrWhiteSpace(options.DeviceUid) || string.IsNullOrWhiteSpace(options.PairingCode))
    {
        Console.Error.WriteLine("Usage: Baseer.PrintAgent pair --url https://odoo.example --device DEVICE-ID --code PAIRING-CODE");
        return 2;
    }
    var paired = await AgentConfig.PairAsync(options.ServerUrl, options.DeviceUid, options.PairingCode);
    AgentConfig.Save(configPath, paired);
    Console.WriteLine("Paired successfully. Start the agent with: Baseer.PrintAgent run");
    return 0;
}

if (args.Length == 0 || args[0].Equals("run", StringComparison.OrdinalIgnoreCase))
{
    if (!File.Exists(configPath))
    {
        Console.Error.WriteLine("This agent is not paired. Run the pair command first.");
        return 2;
    }
    var config = AgentConfig.Load(configPath);
    await new PrintAgent(config, configPath).RunAsync();
    return 0;
}

Console.Error.WriteLine("Commands: pair, run");
return 2;

sealed class AgentOptions
{
    public string ServerUrl { get; private set; } = "";
    public string DeviceUid { get; private set; } = "";
    public string PairingCode { get; private set; } = "";

    public static AgentOptions FromArguments(string[] args)
    {
        var result = new AgentOptions();
        for (var index = 0; index + 1 < args.Length; index += 2)
        {
            switch (args[index])
            {
                case "--url": result.ServerUrl = args[index + 1]; break;
                case "--device": result.DeviceUid = args[index + 1]; break;
                case "--code": result.PairingCode = args[index + 1]; break;
            }
        }
        return result;
    }
}

sealed class AgentConfig
{
    public string ServerUrl { get; set; } = "";
    public string DeviceUid { get; set; } = "";
    public string TokenBlob { get; set; } = "";
    public List<InFlightJob> InFlightJobs { get; set; } = [];

    public string Token => Encoding.UTF8.GetString(ProtectedData.Unprotect(Convert.FromBase64String(TokenBlob), null, DataProtectionScope.LocalMachine));

    public static Uri SecureBaseUri(string serverUrl)
    {
        if (!Uri.TryCreate(serverUrl, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps)
            throw new ArgumentException("The Odoo server URL must use HTTPS.", nameof(serverUrl));
        return new Uri(uri.ToString().TrimEnd('/') + "/");
    }

    public static async Task<AgentConfig> PairAsync(string serverUrl, string deviceUid, string pairingCode)
    {
        using var http = new HttpClient { BaseAddress = SecureBaseUri(serverUrl) };
        var response = await http.PostAsync("baseer/print/v1/pair", JsonContent(new { pairing_code = pairingCode, device_uid = deviceUid, agent_version = AgentBuild.Version }));
        response.EnsureSuccessStatusCode();
        using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var token = body.RootElement.GetProperty("token").GetString() ?? throw new InvalidOperationException("No pairing token returned.");
        return new AgentConfig
        {
            ServerUrl = SecureBaseUri(serverUrl).ToString().TrimEnd('/'), DeviceUid = deviceUid,
            TokenBlob = Convert.ToBase64String(ProtectedData.Protect(Encoding.UTF8.GetBytes(token), null, DataProtectionScope.LocalMachine)),
        };
    }

    public static AgentConfig Load(string path) => JsonSerializer.Deserialize<AgentConfig>(File.ReadAllText(path)) ?? throw new InvalidOperationException("Invalid agent configuration.");
    public static void Save(string path, AgentConfig config)
    {
        var temporaryPath = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllText(temporaryPath, JsonSerializer.Serialize(config, new JsonSerializerOptions { WriteIndented = true }));
            File.Move(temporaryPath, path, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporaryPath)) File.Delete(temporaryPath);
        }
    }
    public static StringContent JsonContent(object data) => new(JsonSerializer.Serialize(data), Encoding.UTF8, "application/json");
}

sealed class InFlightJob
{
    public int Id { get; set; }
    public string LeaseToken { get; set; } = "";
}

sealed class PrintAgent
{
    private const string AgentName = "Baseer.PrintAgent";
    private readonly AgentConfig _config;
    private readonly string _configPath;
    private readonly HttpClient _http;

    public PrintAgent(AgentConfig config, string configPath)
    {
        _config = config;
        _configPath = configPath;
        _http = new HttpClient { BaseAddress = AgentConfig.SecureBaseUri(config.ServerUrl), Timeout = TimeSpan.FromSeconds(30) };
        _http.DefaultRequestHeaders.Authorization = new("Bearer", config.Token);
    }

    public async Task RunAsync()
    {
        using var runner = new Mutex(false, AgentRuntime.RunnerMutexName);
        var ownsRunner = false;
        try
        {
            ownsRunner = runner.WaitOne(0);
        }
        catch (AbandonedMutexException)
        {
            // A crashed predecessor cannot block recovery.
            ownsRunner = true;
        }
        if (!ownsRunner)
        {
            AgentLog.Write($"{AgentName}: another agent is already running on this Windows computer.");
            return;
        }
        try
        {
            AgentRuntime.WriteCurrentId(_configPath);
            await RecoverUnknownJobsAsync();
            while (true)
            {
                try
                {
                    await HeartbeatAsync();
                    await SyncPrintersAsync();
                    var job = await ClaimAsync();
                    if (job is not null) await ExecuteAsync(job);
                    else await Task.Delay(TimeSpan.FromSeconds(2));
                }
                catch (AgentRuntimeBusyException)
                {
                    // Another active instance owns this paired device. Stay
                    // passive; this runner automatically takes over if its
                    // server lease expires, but it never claims or prints now.
                    await Task.Delay(TimeSpan.FromSeconds(10));
                }
                catch (Exception error)
                {
                    AgentLog.Write($"{AgentName}: {error.Message}");
                    await Task.Delay(TimeSpan.FromSeconds(5));
                }
            }
        }
        finally
        {
            AgentRuntime.ClearCurrentId(_configPath);
            runner.ReleaseMutex();
        }
    }

    private async Task RecoverUnknownJobsAsync()
    {
        foreach (var job in _config.InFlightJobs.ToList())
        {
            try
            {
                await PostAsync($"baseer/print/v1/jobs/{job.Id}/fail", new { lease_token = job.LeaseToken, error_code = "outcome_unknown", retryable = false, runtime_id = AgentRuntime.InstanceId });
            }
            catch (Exception error)
            {
                // Do not respool an ambiguous job. The server lease expires to
                // outcome_unknown, and this entry must not block startup.
                AgentLog.Write($"{AgentName}: recovery for job {job.Id} was not acknowledged: {error.Message}");
            }
            _config.InFlightJobs.Remove(job);
        }
        Save();
    }

    private Task HeartbeatAsync() => PostAsync("baseer/print/v1/heartbeat", new { agent_version = AgentBuild.Version, runtime_id = AgentRuntime.InstanceId });

    private Task SyncPrintersAsync()
    {
        var printers = PrinterSettings.InstalledPrinters.Cast<string>().Select(name => new
        {
            display_name = name, machine_identifier = name, driver_name = "",
        });
        return PostAsync("baseer/print/v1/printers/sync", new { printers, runtime_id = AgentRuntime.InstanceId });
    }

    private async Task<ClaimedJob?> ClaimAsync()
    {
        using var response = await _http.PostAsync("baseer/print/v1/jobs/claim", AgentConfig.JsonContent(new { agent_version = AgentBuild.Version, runtime_id = AgentRuntime.InstanceId }));
        await ThrowIfRuntimeBusy(response);
        response.EnsureSuccessStatusCode();
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        if (document.RootElement.GetProperty("job").ValueKind == JsonValueKind.Null) return null;
        return JsonSerializer.Deserialize<ClaimedJob>(document.RootElement.GetProperty("job"));
    }

    private async Task ExecuteAsync(ClaimedJob job)
    {
        var durable = new InFlightJob { Id = job.Id, LeaseToken = job.LeaseToken };
        _config.InFlightJobs.Add(durable);
        Save(); // durable before contacting the Windows spooler; a restart reports outcome_unknown.
        using var renewal = new CancellationTokenSource();
        var renewTask = RenewLeaseAsync(job, renewal.Token);
        var spoolAccepted = false;
        var outcomeReported = false;
        try
        {
            ThermalPrinter.Print(job.Payload);
            spoolAccepted = true;
            await PostAsync($"baseer/print/v1/jobs/{job.Id}/complete", new { lease_token = job.LeaseToken, runtime_id = AgentRuntime.InstanceId });
            outcomeReported = true;
        }
        catch (PrinterUnavailableException) when (!spoolAccepted)
        {
            await PostAsync($"baseer/print/v1/jobs/{job.Id}/fail", new { lease_token = job.LeaseToken, error_code = "printer_offline", retryable = true, runtime_id = AgentRuntime.InstanceId });
            outcomeReported = true;
        }
        catch (InvalidReceiptException) when (!spoolAccepted)
        {
            await PostAsync($"baseer/print/v1/jobs/{job.Id}/fail", new { lease_token = job.LeaseToken, error_code = "invalid_receipt", retryable = false, runtime_id = AgentRuntime.InstanceId });
            outcomeReported = true;
        }
        catch
        {
            var errorCode = spoolAccepted ? "outcome_unknown" : "print_failed";
            await PostAsync($"baseer/print/v1/jobs/{job.Id}/fail", new { lease_token = job.LeaseToken, error_code = errorCode, retryable = false, runtime_id = AgentRuntime.InstanceId });
            outcomeReported = true;
        }
        finally
        {
            renewal.Cancel();
            try { await renewTask; } catch (OperationCanceledException) { }
            if (outcomeReported)
            {
                _config.InFlightJobs.RemoveAll(item => item.Id == job.Id);
                Save();
            }
        }
    }

    private async Task RenewLeaseAsync(ClaimedJob job, CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            await Task.Delay(TimeSpan.FromSeconds(50), cancellationToken);
            if (!cancellationToken.IsCancellationRequested)
                await PostAsync($"baseer/print/v1/jobs/{job.Id}/renew", new { lease_token = job.LeaseToken, runtime_id = AgentRuntime.InstanceId });
        }
    }

    private async Task PostAsync(string path, object body)
    {
        using var response = await _http.PostAsync(path, AgentConfig.JsonContent(body));
        await ThrowIfRuntimeBusy(response);
        response.EnsureSuccessStatusCode();
    }

    private static async Task ThrowIfRuntimeBusy(HttpResponseMessage response)
    {
        if (response.StatusCode != System.Net.HttpStatusCode.Conflict)
            return;
        var responseBody = await response.Content.ReadAsStringAsync();
        if (responseBody.Contains("agent_already_running", StringComparison.Ordinal))
            throw new AgentRuntimeBusyException();
    }

    private void Save() => AgentConfig.Save(_configPath, _config);
}

sealed class ClaimedJob
{
    [JsonPropertyName("id")]
    public int Id { get; set; }
    [JsonPropertyName("lease_token")]
    public string LeaseToken { get; set; } = "";
    [JsonPropertyName("payload")]
    public JsonElement Payload { get; set; }
}

sealed class PrinterUnavailableException : Exception { }
sealed class InvalidReceiptException(string message) : Exception(message) { }
sealed class AgentRuntimeBusyException : Exception { }

static class AgentStorage
{
    public static void EnsureProtectedDirectory(string directory)
    {
        Directory.CreateDirectory(directory);
        if (!OperatingSystem.IsWindows()) return;

        var security = new DirectorySecurity();
        security.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
        var inheritance = InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit;
        security.AddAccessRule(new FileSystemAccessRule(
            new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null), FileSystemRights.FullControl,
            inheritance, PropagationFlags.None, AccessControlType.Allow));
        security.AddAccessRule(new FileSystemAccessRule(
            new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null), FileSystemRights.FullControl,
            inheritance, PropagationFlags.None, AccessControlType.Allow));
        var currentUser = WindowsIdentity.GetCurrent().User;
        if (currentUser is not null)
        {
            // The QA agent is intentionally a console process, so the account
            // that pairs it must retain access to its own DPAPI-protected file.
            // Do not grant a broad Users/Everyone rule: LocalMachine DPAPI
            // requires the ACL to remain the boundary for the token.
            security.AddAccessRule(new FileSystemAccessRule(
                currentUser, FileSystemRights.FullControl,
                inheritance, PropagationFlags.None, AccessControlType.Allow));
        }
        new DirectoryInfo(directory).SetAccessControl(security);
    }
}

static class ThermalPrinter
{
    private const float Left = 5f;
    private const float SessionReportMaxWidth = 270f;
    private record ReceiptRow(string Label, string Value = "", bool Strong = false, bool Divider = false);

    public static void Print(JsonElement payload)
    {
        var printer = payload.GetProperty("printer").GetProperty("machine_identifier").GetString() ?? "";
        var ticketType = GetString(payload, "ticket_type");
        var nativeReceipt = ticketType == "receipt" &&
            payload.TryGetProperty("schema", out var nativeSchema) && nativeSchema.GetInt32() == 4;
        var paymentCount = ticketType == "session_close" && payload.TryGetProperty("payments", out var payments)
            ? payments.GetArrayLength()
            : 0;
        // Older receipt jobs contained kitchen-style lines but no financial snapshot.
        // Never pass them to the kitchen renderer or fabricate a customer total.
        if (ticketType == "receipt" && !nativeReceipt &&
            (!payload.TryGetProperty("schema", out var receiptSchema) || receiptSchema.GetInt32() < 3 ||
             !payload.TryGetProperty("receipt", out var receiptData) ||
             receiptData.ValueKind != JsonValueKind.Object ||
             string.IsNullOrWhiteSpace(GetString(receiptData, "total")) ||
             string.IsNullOrWhiteSpace(GetString(receiptData, "currency"))))
            throw new InvalidReceiptException("Legacy or incomplete customer receipt; a new audited snapshot is required.");
        byte[] nativeBytes = [];
        if (nativeReceipt)
        {
            var imageData = payload.GetProperty("receipt_image");
            var encoded = GetString(imageData, "base64");
            if (encoded.Length == 0 || encoded.Length > 349528)
                throw new InvalidReceiptException("The Odoo receipt image is missing or too large.");
            try { nativeBytes = Convert.FromBase64String(encoded); }
            catch (FormatException) { throw new InvalidReceiptException("The Odoo receipt image is not valid base64."); }
            byte[] expectedHash;
            try { expectedHash = Convert.FromHexString(GetString(imageData, "sha256")); }
            catch (FormatException) { throw new InvalidReceiptException("The Odoo receipt image checksum is invalid."); }
            if (nativeBytes.Length == 0 || nativeBytes.Length > 256 * 1024 ||
                expectedHash.Length != 32 || !SHA256.HashData(nativeBytes).AsSpan().SequenceEqual(expectedHash))
                throw new InvalidReceiptException("The Odoo receipt image checksum is invalid.");
        }
        using var imageStream = new MemoryStream(nativeBytes, writable: false);
        Image? decodedImage = null;
        if (nativeReceipt)
        {
            try { decodedImage = Image.FromStream(imageStream, useEmbeddedColorManagement: false, validateImageData: true); }
            catch (ArgumentException) { throw new InvalidReceiptException("The Odoo receipt JPEG cannot be decoded."); }
        }
        using var nativeImage = decodedImage;
        if (nativeImage is not null &&
            (nativeImage.RawFormat.Guid != System.Drawing.Imaging.ImageFormat.Jpeg.Guid ||
             nativeImage.Width < 200 || nativeImage.Width > 1000 || nativeImage.Height < 1 ||
             nativeImage.Height > 12000 || (long)nativeImage.Width * nativeImage.Height > 5_000_000 ||
             nativeImage.Width != payload.GetProperty("receipt_image").GetProperty("width").GetInt32() ||
            nativeImage.Height != payload.GetProperty("receipt_image").GetProperty("height").GetInt32()))
            throw new InvalidReceiptException("The Odoo receipt image dimensions are invalid.");
        // Thermal heads are binary (a dot is heated or not heated).  Supplying
        // an RGB JPEG lets a Windows driver dither every anti-aliased glyph,
        // which is perceived as a field of dots.  Quantise the audited image
        // locally, after checksum validation, so the driver receives crisp
        // black/white pixels without altering the stored receipt snapshot.
        using var thermalImage = nativeImage is null ? null : ToThermalMonochrome(nativeImage);
        var printableNativeImage = thermalImage ?? nativeImage;
        using var document = new PrintDocument();
        document.PrinterSettings.PrinterName = printer;
        if (!document.PrinterSettings.IsValid) throw new PrinterUnavailableException();
        var paperWidth = payload.GetProperty("printer").GetProperty("paper_width").GetString();
        var paperHeight = ticketType == "session_close" ? 900 + (paymentCount * 46) : 1180;
        document.DefaultPageSettings.PaperSize = new PaperSize(
            "Baseer thermal", paperWidth == "58" ? 228 : 315, paperHeight
        );
        document.DefaultPageSettings.Margins = new Margins(0, 0, 0, 0);
        document.OriginAtMargins = false;
        if (payload.GetProperty("printer").TryGetProperty("copies", out var copies))
            document.PrinterSettings.Copies = (short)Math.Clamp(copies.GetInt32(), 1, 10);
        var receiptRows = ticketType == "receipt" && !nativeReceipt ? BuildReceiptRows(payload) : [];
        var receiptRowIndex = 0;
        var receiptPage = 0;
        var nativeOffset = 0;
        if (printableNativeImage is not null)
        {
            var nativeWidth = Math.Min((float)(paperWidth == "58" ? 218 : 305), SessionReportMaxWidth);
            var sourcePerPage = Math.Max(1, (int)Math.Floor(1130f * printableNativeImage.Width / nativeWidth));
            if ((printableNativeImage.Height + sourcePerPage - 1) / sourcePerPage > 15)
                throw new InvalidReceiptException("The Odoo receipt exceeds 15 thermal pages.");
        }
        document.PrintPage += (_, eventArgs) =>
        {
            if (eventArgs.Graphics is null) return;
            using var normal = new Font("Segoe UI", 8.5f);
            using var bold = new Font("Segoe UI", 8.5f, FontStyle.Bold);
            using var headline = new Font("Segoe UI", 11f, FontStyle.Bold);
            using var subhead = new Font("Segoe UI", 9f, FontStyle.Bold);
            var width = eventArgs.PageBounds.Width - (Left * 2);
            if (printableNativeImage is not null)
            {
                var targetWidth = Math.Min(width, SessionReportMaxWidth);
                var scale = targetWidth / printableNativeImage.Width;
                // PrintDocument's origin is the printer's printable origin,
                // not the physical left edge of the paper. Compensating the
                // device hard margin keeps the whole audited receipt centred
                // on 80 mm stock instead of visibly shifted to the right.
                var centeredLeft = (eventArgs.PageBounds.Width - targetWidth) / 2f
                    - eventArgs.PageSettings.HardMarginX;
                var sourceHeight = Math.Min(printableNativeImage.Height - nativeOffset,
                    Math.Max(1, (int)Math.Floor(1130f / scale)));
                // The native receipt is an audited raster.  Scale it with a
                // print-quality filter so a 80 mm printer does not turn text
                // edges into a visible nearest-neighbour pixel grid.
                eventArgs.Graphics.CompositingQuality = CompositingQuality.HighQuality;
                eventArgs.Graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
                eventArgs.Graphics.PixelOffsetMode = PixelOffsetMode.HighQuality;
                eventArgs.Graphics.DrawImage(printableNativeImage,
                    new RectangleF(centeredLeft, 5f, targetWidth, sourceHeight * scale),
                    new RectangleF(0, nativeOffset, printableNativeImage.Width, sourceHeight),
                    GraphicsUnit.Pixel);
                nativeOffset += sourceHeight;
                eventArgs.HasMorePages = nativeOffset < printableNativeImage.Height;
                return;
            }
            if (ticketType == "session_close")
            {
                // 80 mm thermal mechanisms normally expose about 72 mm of printable width even
                // when the driver reports the full nominal paper size. Keep the report inside a
                // 270-unit safe width so the right border and values are not physically clipped.
                var sessionWidth = Math.Min(width, SessionReportMaxWidth);
                DrawSessionClosingReport(
                    eventArgs.Graphics, payload, normal, bold, headline, subhead,
                    sessionWidth, paperWidth == "58"
                );
                return;
            }
            if (ticketType == "receipt")
            {
                receiptPage++;
                DrawCustomerReceiptPage(eventArgs, payload, receiptRows, ref receiptRowIndex,
                    receiptPage, normal, bold, headline, subhead, Math.Min(width, SessionReportMaxWidth));
                return;
            }
            var y = 5f;
            var orderInfo = payload.GetProperty("order");
            var order = orderInfo.GetProperty("reference").GetString() ?? "Baseer";
            if (payload.TryGetProperty("cancellation", out var cancellation))
            {
                DrawCentered(eventArgs.Graphics, "CANCEL / إلغاء الطلب", headline, y, width);
                y += 24;
                var reason = cancellation.TryGetProperty("reason_label", out var reasonValue)
                    ? reasonValue.GetString() ?? "Other"
                    : "Other";
                var note = cancellation.TryGetProperty("reason_note", out var noteValue)
                    ? noteValue.GetString() ?? ""
                    : "";
                eventArgs.Graphics.DrawString($"Reason / السبب: {reason}", bold, Brushes.Black, Left, y);
                y += 18;
                if (!string.IsNullOrWhiteSpace(note))
                {
                    y += DrawWrapped(eventArgs.Graphics, note, normal, Left, y, width);
                }
            }
            else
            {
                var actions = payload.GetProperty("lines").EnumerateArray()
                    .Select(line => line.TryGetProperty("action", out var action) ? action.GetString() : "")
                    .ToList();
                var normalizedActions = actions.Select(action => action?.ToLowerInvariant() ?? "").ToList();
                var allCancelled = normalizedActions.Count > 0 && normalizedActions.All(action => action == "cancel");
                var hasChanges = normalizedActions.Any(action => action is "add" or "reduce" or "cancel" or "update");
                DrawCentered(eventArgs.Graphics, allCancelled ? "CANCEL / إلغاء الطلب" :
                    (hasChanges ? "KITCHEN CHANGES / تغييرات المطبخ" : "KITCHEN ORDER / طلب مطبخ"), headline, y, width);
                y += 24;
            }
            DrawCentered(eventArgs.Graphics, order, subhead, y, width);
            y += 18;
            y = DrawHeaderValue(
                eventArgs.Graphics, "Time / الوقت",
                FormatTicketTime(GetString(orderInfo, "created_at")), normal, y, width
            );
            y = DrawHeaderValue(eventArgs.Graphics, "Cashier / الكاشير", GetString(orderInfo, "requested_by"), normal, y, width);
            y = DrawHeaderValue(eventArgs.Graphics, "Table / الطاولة", GetString(orderInfo, "table"), normal, y, width);
            DrawDivider(eventArgs.Graphics, y, width);
            y += 5;

            const float quantityWidth = 38f;
            eventArgs.Graphics.DrawString("QTY", bold, Brushes.Black, Left, y);
            eventArgs.Graphics.DrawString("ITEM / الصنف", bold, Brushes.Black, Left + quantityWidth, y);
            y += 16;
            DrawDivider(eventArgs.Graphics, y, width);
            y += 4;
            foreach (var line in payload.GetProperty("lines").EnumerateArray())
            {
                var action = NormalizeAction(line);
                var name = GetString(line, "name");
                var quantity = GetQuantity(line, "quantity");
                var previousQuantity = GetQuantity(line, "previous_quantity");
                var deltaQuantity = GetQuantity(line, "delta_quantity");
                var displayedQuantity = action switch
                {
                    "new" => $"+{FormatQuantity(quantity)}",
                    "add" => $"+{FormatQuantity(Math.Abs(deltaQuantity))}",
                    "reduce" => $"-{FormatQuantity(Math.Abs(deltaQuantity))}",
                    "cancel" => $"×{FormatQuantity(previousQuantity != 0 ? previousQuantity : Math.Abs(deltaQuantity))}",
                    _ => FormatQuantity(quantity),
                };
                eventArgs.Graphics.DrawString(displayedQuantity, bold, Brushes.Black, Left, y);
                var actionLabel = action switch
                {
                    "new" => "NEW / جديد",
                    "add" => "ADD / إضافة",
                    "reduce" => "REDUCE / تخفيض",
                    "cancel" => "CANCEL / إلغاء",
                    _ => "NEW / جديد",
                };
                var label = $"[{actionLabel}] {name}";
                var rowHeight = DrawWrapped(eventArgs.Graphics, label, bold, Left + quantityWidth, y, width - quantityWidth);
                y += Math.Max(16f, rowHeight) + 3;
                if (action == "add")
                {
                    y += DrawWrapped(eventArgs.Graphics,
                        $"Total / الإجمالي: {FormatQuantity(quantity)}", normal,
                        Left + quantityWidth, y, width - quantityWidth);
                }
                else if (action == "reduce")
                {
                    y += DrawWrapped(eventArgs.Graphics,
                        $"Remaining / المتبقي: {FormatQuantity(quantity)}", normal,
                        Left + quantityWidth, y, width - quantityWidth);
                }

                var reason = GetString(line, "reason_label");
                var reasonNote = GetString(line, "reason_note");
                if (!string.IsNullOrWhiteSpace(reason))
                {
                    y += DrawWrapped(eventArgs.Graphics, $"Reason / السبب: {Shorten(reason, 80)}", normal,
                        Left + quantityWidth, y, width - quantityWidth);
                }
                if (!string.IsNullOrWhiteSpace(reasonNote))
                {
                    y += DrawWrapped(eventArgs.Graphics, Shorten(reasonNote, 120), normal,
                        Left + quantityWidth, y, width - quantityWidth);
                }
                var note = GetString(line, "note");
                if (!string.IsNullOrWhiteSpace(note))
                {
                    y += DrawWrapped(eventArgs.Graphics, $"Note / ملاحظة: {Shorten(note, 120)}", normal,
                        Left + quantityWidth, y, width - quantityWidth);
                }
            }
        };
        document.Print(); // confirms Windows spooler acceptance only; paper output is not observable programmatically.
    }

    private static List<ReceiptRow> BuildReceiptRows(JsonElement payload)
    {
        var receipt = payload.GetProperty("receipt");
        var currency = GetString(receipt, "currency");
        var rows = new List<ReceiptRow>();
        foreach (var line in payload.GetProperty("lines").EnumerateArray())
        {
            var name = GetString(line, "name");
            if (name.Length > 200)
                throw new InvalidReceiptException("A customer receipt item name is too long to print safely.");
            rows.Add(new ReceiptRow($"{FormatQuantity(GetQuantity(line, "quantity"))} × {name}",
                $"{GetString(line, "price")} {currency}"));
            var discount = GetQuantity(line, "discount");
            if (discount != 0)
                rows.Add(new ReceiptRow($"Unit {GetString(line, "unit_price")} · Discount {FormatQuantity(discount)}%"));
        }
        rows.Add(new ReceiptRow("", Divider: true));
        rows.Add(new ReceiptRow("Subtotal / قبل الضريبة", $"{GetString(receipt, "subtotal")} {currency}"));
        rows.Add(new ReceiptRow("VAT / الضريبة", $"{GetString(receipt, "tax")} {currency}"));
        if (receipt.TryGetProperty("has_adjustment", out var hasAdjustment) && hasAdjustment.ValueKind == JsonValueKind.True)
            rows.Add(new ReceiptRow("Adjustment / تسوية", $"{GetString(receipt, "adjustment")} {currency}"));
        rows.Add(new ReceiptRow("TOTAL / الإجمالي", $"{GetString(receipt, "total")} {currency}", Strong: true));
        rows.Add(new ReceiptRow("", Divider: true));
        rows.Add(new ReceiptRow("PAYMENT METHODS / طرق الدفع", Strong: true));
        foreach (var payment in receipt.GetProperty("payments").EnumerateArray())
        {
            var method = GetString(payment, "method");
            if (method.Length > 100)
                throw new InvalidReceiptException("A payment method name is too long to print safely.");
            rows.Add(new ReceiptRow(method, $"{GetString(payment, "amount")} {currency}"));
        }
        rows.Add(new ReceiptRow("Paid / المدفوع", $"{GetString(receipt, "paid")} {currency}"));
        rows.Add(new ReceiptRow("Change / الباقي", $"{GetString(receipt, "change")} {currency}"));
        rows.Add(new ReceiptRow("", Divider: true));
        rows.Add(new ReceiptRow("THANK YOU / شكراً لزيارتكم", Strong: true));
        return rows;
    }

    private static Bitmap ToThermalMonochrome(Image source)
    {
        var bitmap = new Bitmap(source.Width, source.Height, PixelFormat.Format24bppRgb);
        using (var graphics = Graphics.FromImage(bitmap))
        {
            graphics.Clear(Color.White);
            graphics.DrawImageUnscaled(source, 0, 0);
        }

        var bounds = new Rectangle(0, 0, bitmap.Width, bitmap.Height);
        var locked = bitmap.LockBits(bounds, ImageLockMode.ReadWrite, PixelFormat.Format24bppRgb);
        try
        {
            var bytes = Math.Abs(locked.Stride) * bitmap.Height;
            var pixels = new byte[bytes];
            Marshal.Copy(locked.Scan0, pixels, 0, bytes);
            for (var y = 0; y < bitmap.Height; y++)
            {
                var row = y * Math.Abs(locked.Stride);
                for (var x = 0; x < bitmap.Width; x++)
                {
                    var offset = row + (x * 3);
                    var blue = pixels[offset];
                    var green = pixels[offset + 1];
                    var red = pixels[offset + 2];
                    // Preserve legibility without making anti-aliased Arabic
                    // and Latin strokes visibly heavier on thermal paper.
                    var luminance = (red * 299 + green * 587 + blue * 114) / 1000;
                    var tone = luminance < 170 ? (byte)0 : (byte)255;
                    pixels[offset] = tone;
                    pixels[offset + 1] = tone;
                    pixels[offset + 2] = tone;
                }
            }
            Marshal.Copy(pixels, 0, locked.Scan0, bytes);
        }
        finally
        {
            bitmap.UnlockBits(locked);
        }
        return bitmap;
    }

    private static void DrawCustomerReceiptPage(
        PrintPageEventArgs eventArgs, JsonElement payload, List<ReceiptRow> rows, ref int rowIndex,
        int page, Font normal, Font bold, Font headline, Font subhead, float width)
    {
        var graphics = eventArgs.Graphics!;
        var order = payload.GetProperty("order");
        var receipt = payload.GetProperty("receipt");
        var y = 5f;
        y += DrawWrappedRtlAware(graphics, GetString(receipt, "company"), headline, Left, y, width) + 4f;
        y += DrawWrappedRtlAware(graphics, GetString(receipt, "point_of_sale"), subhead, Left, y, width) + 4f;
        DrawCenteredRtlAware(graphics, "إيصال بيع تجريبي", bold, y, width);
        y += 18f;
        DrawCentered(graphics, "QA SALES RECEIPT", bold, y, width);
        y += 22f;
        y = DrawHeaderValue(graphics, "Order / الطلب", GetString(order, "reference"), normal, y, width);
        y = DrawHeaderValue(graphics, "Time / الوقت", FormatTicketTime(GetString(order, "created_at")), normal, y, width);
        y = DrawHeaderValue(graphics, "Cashier / الكاشير", GetString(order, "requested_by"), normal, y, width);
        y = DrawHeaderValue(graphics, "Table / الطاولة", GetString(order, "table"), normal, y, width);
        y = DrawHeaderValue(graphics, "VAT No. / الرقم الضريبي", GetString(receipt, "company_vat"), normal, y, width);
        if (page > 1) y = DrawHeaderValue(graphics, "Page / الصفحة", page.ToString(CultureInfo.InvariantCulture), normal, y, width);
        DrawDivider(graphics, y + 2f, width);
        y += 10f;
        var firstRowOnPage = rowIndex;
        while (rowIndex < rows.Count)
        {
            var row = rows[rowIndex];
            var font = row.Strong ? bold : normal;
            var labelWidth = row.Value.Length == 0 ? width : width * 0.62f;
            var valueWidth = width - labelWidth - 5f;
            var height = row.Divider ? 9f : Math.Max(18f,
                Math.Max(MeasureWrapped(graphics, row.Label, font, labelWidth),
                    row.Value.Length == 0 ? 0f : MeasureWrapped(graphics, row.Value, font, valueWidth)) + 3f);
            if (y + height > eventArgs.PageBounds.Height - 25f)
            {
                if (rowIndex == firstRowOnPage)
                    throw new InvalidReceiptException("The receipt row cannot fit on thermal paper.");
                DrawCentered(graphics, "CONTINUED / يتبع", bold, y, width);
                eventArgs.HasMorePages = true;
                return;
            }
            if (row.Divider)
                DrawDivider(graphics, y + 3f, width);
            else
            {
                DrawCellValue(graphics, row.Label, font, Left, y, labelWidth, height - 2f, alignRight: false);
                if (row.Value.Length != 0)
                    DrawCellValue(graphics, row.Value, font, Left + labelWidth + 5f, y,
                        valueWidth, height - 2f, alignRight: true);
            }
            y += height;
            rowIndex++;
        }
        eventArgs.HasMorePages = false;
    }

    private static void DrawSessionClosingReport(
        Graphics graphics, JsonElement payload, Font normal, Font bold, Font headline, Font subhead,
        float width, bool narrowPaper)
    {
        var session = payload.GetProperty("session");
        var summary = payload.GetProperty("summary");
        var currency = GetString(session, "currency_code");
        var y = 5f;

        if (!narrowPaper)
        {
            DrawSessionClosingReportTable(
                graphics, payload, normal, bold, headline, subhead, width
            );
            return;
        }

        DrawCenteredRtlAware(graphics, "تقرير إغلاق الجلسة", headline, y, width);
        y += 23;
        DrawCentered(graphics, "SESSION CLOSING REPORT", subhead, y, width);
        y += 21;
        DrawCenteredRtlAware(graphics, GetString(session, "reference"), subhead, y, width);
        y += 21;
        y = DrawBilingualValueBlock(graphics, "نقطة البيع", "POS", GetString(session, "point_of_sale"), normal, bold, y, width, narrowPaper);
        y = DrawBilingualValueBlock(graphics, "الكاشير", "Cashier", GetString(session, "cashier"), normal, bold, y, width, narrowPaper);
        y = DrawBilingualValueBlock(graphics, "البداية", "Opened", FormatTicketTime(GetString(session, "opened_at")), normal, bold, y, width, narrowPaper);
        y = DrawBilingualValueBlock(graphics, "النهاية", "Closed", FormatTicketTime(GetString(session, "closed_at")), normal, bold, y, width, narrowPaper);
        y = DrawBilingualValueBlock(graphics, "مدة الجلسة", "Duration", GetString(session, "duration_label"), normal, bold, y, width, narrowPaper);
        DrawDivider(graphics, y + 2, width);
        y += 9;

        DrawCenteredRtlAware(graphics, "طرق الدفع", subhead, y, width);
        y += 19;
        DrawCentered(graphics, "PAYMENT METHODS", subhead, y, width);
        y += 22;
        foreach (var payment in payload.GetProperty("payments").EnumerateArray())
        {
            var method = GetString(payment, "method");
            var amount = $"{GetString(payment, "amount")} {currency}".Trim();
            y += DrawWrappedRtlAware(graphics, method, normal, Left, y, width);
            using var amountFormat = new StringFormat {
                Alignment = StringAlignment.Far,
                LineAlignment = StringAlignment.Near,
                FormatFlags = StringFormatFlags.NoWrap,
            };
            graphics.DrawString(amount, bold, Brushes.Black, new RectangleF(Left, y, width, 18f), amountFormat);
            y += 23f;
        }
        DrawDivider(graphics, y, width);
        y += 7;

        y = DrawBilingualValueBlock(graphics, "عدد الفواتير", "Invoices", GetString(summary, "invoice_count"), normal, bold, y, width, narrowPaper);
        y = DrawBilingualValueBlock(graphics, "فواتير مرتجعة", "Refunds", GetString(summary, "refund_count"), normal, bold, y, width, narrowPaper);
        y = DrawBilingualValueBlock(graphics, "الإجمالي", "Total", $"{GetString(summary, "total_amount")} {currency}".Trim(), normal, bold, y, width, narrowPaper);
        y = DrawBilingualValueBlock(graphics, "متوسط الفاتورة", "Average invoice", $"{GetString(summary, "average_invoice")} {currency}".Trim(), normal, bold, y, width, narrowPaper);
        y = DrawBilingualValueBlock(graphics, "إجمالي الإلغاءات", "Cancellations", GetString(summary, "cancellation_count"), normal, bold, y, width, narrowPaper);
        y = DrawBilingualValueBlock(graphics, "الطلبات الملغاة", "Cancelled orders", GetString(summary, "cancelled_orders"), normal, bold, y, width, narrowPaper);
        y = DrawBilingualValueBlock(graphics, "الأصناف الملغاة", "Cancelled items", GetString(summary, "cancelled_items"), normal, bold, y, width, narrowPaper);
        DrawDivider(graphics, y + 2, width);
        y += 10;
        DrawCenteredRtlAware(graphics, "نهاية التقرير", bold, y, width);
        y += 19;
        DrawCentered(graphics, "END OF REPORT", bold, y, width);
    }

    private static void DrawSessionClosingReportTable(
        Graphics graphics, JsonElement payload, Font normal, Font bold, Font headline, Font subhead, float width)
    {
        var session = payload.GetProperty("session");
        var summary = payload.GetProperty("summary");
        var currency = GetString(session, "currency_code");
        var y = 5f;

        DrawCenteredRtlAware(graphics, "تقرير إغلاق الجلسة", headline, y, width);
        y += 23f;
        DrawCentered(graphics, "SESSION CLOSING REPORT", subhead, y, width);
        y += 27f;

        y = DrawSectionTitle(graphics, "بيانات الجلسة", "SESSION DETAILS", subhead, y, width);
        y = DrawBilingualTableHeader(graphics, "البند", "ITEM", "القيمة", "VALUE", bold, y, width, 0.42f);
        y = DrawBilingualTableRow(graphics, "رقم الجلسة", "Session", GetString(session, "reference"), normal, bold, y, width, 0.42f);
        y = DrawBilingualTableRow(graphics, "نقطة البيع", "POS", GetString(session, "point_of_sale"), normal, bold, y, width, 0.42f);
        y = DrawBilingualTableRow(graphics, "الكاشير", "Cashier", GetString(session, "cashier"), normal, bold, y, width, 0.42f);
        y = DrawBilingualTableRow(graphics, "البداية", "Opened", FormatTicketTime(GetString(session, "opened_at")), normal, bold, y, width, 0.42f);
        y = DrawBilingualTableRow(graphics, "النهاية", "Closed", FormatTicketTime(GetString(session, "closed_at")), normal, bold, y, width, 0.42f);
        y = DrawBilingualTableRow(graphics, "مدة الجلسة", "Duration", GetString(session, "duration_label"), normal, bold, y, width, 0.42f);
        y += 8f;

        y = DrawSectionTitle(graphics, "طرق الدفع", "PAYMENT METHODS", subhead, y, width);
        y = DrawBilingualTableHeader(graphics, "الطريقة", "METHOD", "المبلغ", "AMOUNT", bold, y, width, 0.68f);
        var payments = payload.GetProperty("payments").EnumerateArray().ToList();
        if (payments.Count == 0)
        {
            y = DrawBilingualTableRow(graphics, "لا توجد مدفوعات", "No payments", "—", normal, bold, y, width, 0.68f);
        }
        else
        {
            foreach (var payment in payments)
            {
                var amount = $"{GetString(payment, "amount")} {currency}".Trim();
                y = DrawTableRow(graphics, GetString(payment, "method"), amount, normal, bold, y, width, 0.68f);
            }
        }
        var paymentTotal = GetString(summary, "payment_total");
        if (string.IsNullOrWhiteSpace(paymentTotal))
        {
            var parsedAmounts = payments.Select(payment => decimal.TryParse(
                GetString(payment, "amount"), NumberStyles.Number, CultureInfo.InvariantCulture,
                out var amount) ? (decimal?)amount : null).ToList();
            paymentTotal = parsedAmounts.All(amount => amount.HasValue)
                ? parsedAmounts.Sum(amount => amount.GetValueOrDefault()).ToString("0.00", CultureInfo.InvariantCulture)
                : "—";
        }
        y = DrawBilingualTableRow(graphics, "مجموع طرق الدفع", "Payment total",
            $"{paymentTotal} {currency}".Trim(), bold, bold, y, width, 0.68f);
        y += 8f;

        y = DrawSectionTitle(graphics, "ملخص الجلسة", "SESSION SUMMARY", subhead, y, width);
        y = DrawBilingualTableHeader(graphics, "البند", "ITEM", "القيمة", "VALUE", bold, y, width, 0.56f);
        y = DrawBilingualTableRow(graphics, "عدد الفواتير", "Invoices", GetString(summary, "invoice_count"), normal, bold, y, width, 0.56f);
        y = DrawBilingualTableRow(graphics, "فواتير مرتجعة", "Refunds", GetString(summary, "refund_count"), normal, bold, y, width, 0.56f);
        y = DrawBilingualTableRow(graphics, "الإجمالي", "Total", $"{GetString(summary, "total_amount")} {currency}".Trim(), normal, bold, y, width, 0.56f);
        y = DrawBilingualTableRow(graphics, "متوسط الفاتورة", "Average invoice", $"{GetString(summary, "average_invoice")} {currency}".Trim(), normal, bold, y, width, 0.56f);
        y = DrawBilingualTableRow(graphics, "إجمالي الإلغاءات", "Cancellations", GetString(summary, "cancellation_count"), normal, bold, y, width, 0.56f);
        y = DrawBilingualTableRow(graphics, "الطلبات الملغاة", "Cancelled orders", GetString(summary, "cancelled_orders"), normal, bold, y, width, 0.56f);
        y = DrawBilingualTableRow(graphics, "الأصناف الملغاة", "Cancelled items", GetString(summary, "cancelled_items"), normal, bold, y, width, 0.56f);
        y += 12f;

        DrawCenteredRtlAware(graphics, "نهاية التقرير", bold, y, width);
        y += 19f;
        DrawCentered(graphics, "END OF REPORT", bold, y, width);
    }

    private static float DrawSectionTitle(
        Graphics graphics, string arabic, string english, Font font, float y, float width)
    {
        DrawCenteredRtlAware(graphics, arabic, font, y, width);
        y += 18f;
        DrawCentered(graphics, english, font, y, width);
        return y + 23f;
    }

    private static float DrawBilingualTableHeader(
        Graphics graphics, string leftArabic, string leftEnglish, string rightArabic, string rightEnglish,
        Font font, float y, float width, float leftRatio)
    {
        const float rowHeight = 38f;
        var leftWidth = width * leftRatio;
        DrawTableFrame(graphics, y, width, rowHeight, leftWidth);
        DrawCellLine(graphics, leftArabic, font, Left + 4f, y + 3f, leftWidth - 8f, true, true);
        DrawCellLine(graphics, leftEnglish, font, Left + 4f, y + 19f, leftWidth - 8f, false, true);
        DrawCellLine(graphics, rightArabic, font, Left + leftWidth + 4f, y + 3f, width - leftWidth - 8f, true, true);
        DrawCellLine(graphics, rightEnglish, font, Left + leftWidth + 4f, y + 19f, width - leftWidth - 8f, false, true);
        return y + rowHeight;
    }

    private static float DrawBilingualTableRow(
        Graphics graphics, string arabicLabel, string englishLabel, string value,
        Font labelFont, Font valueFont, float y, float width, float leftRatio)
    {
        var leftWidth = width * leftRatio;
        var valueWidth = width - leftWidth - 8f;
        var valueHeight = MeasureWrapped(graphics, value, valueFont, valueWidth);
        var rowHeight = Math.Max(39f, valueHeight + 10f);
        DrawTableFrame(graphics, y, width, rowHeight, leftWidth);
        DrawCellLine(graphics, arabicLabel, labelFont, Left + 4f, y + 4f, leftWidth - 8f, true, false);
        DrawCellLine(graphics, englishLabel, labelFont, Left + 4f, y + 21f, leftWidth - 8f, false, false);
        DrawCellValue(graphics, value, valueFont, Left + leftWidth + 4f, y + 5f, valueWidth, rowHeight - 10f,
            alignCenter: true);
        return y + rowHeight;
    }

    private static float DrawTableRow(
        Graphics graphics, string leftValue, string rightValue, Font leftFont, Font rightFont,
        float y, float width, float leftRatio)
    {
        var leftWidth = width * leftRatio;
        var leftHeight = MeasureWrapped(graphics, leftValue, leftFont, leftWidth - 8f);
        var rightHeight = MeasureWrapped(graphics, rightValue, rightFont, width - leftWidth - 8f);
        var rowHeight = Math.Max(29f, Math.Max(leftHeight, rightHeight) + 10f);
        DrawTableFrame(graphics, y, width, rowHeight, leftWidth);
        DrawCellValue(graphics, leftValue, leftFont, Left + 4f, y + 5f, leftWidth - 8f, rowHeight - 10f, alignRight: false);
        DrawCellValue(graphics, rightValue, rightFont, Left + leftWidth + 4f, y + 5f,
            width - leftWidth - 8f, rowHeight - 10f, alignCenter: true);
        return y + rowHeight;
    }

    private static void DrawTableFrame(Graphics graphics, float y, float width, float height, float leftWidth)
    {
        graphics.DrawRectangle(Pens.Black, Left, y, width, height);
        graphics.DrawLine(Pens.Black, Left + leftWidth, y, Left + leftWidth, y + height);
    }

    private static void DrawCellLine(
        Graphics graphics, string text, Font font, float x, float y, float width, bool rightToLeft, bool centered)
    {
        using var format = new StringFormat {
            Alignment = centered ? StringAlignment.Center : (rightToLeft ? StringAlignment.Far : StringAlignment.Near),
            FormatFlags = rightToLeft ? StringFormatFlags.DirectionRightToLeft : 0,
        };
        graphics.DrawString(text, font, Brushes.Black, new RectangleF(x, y, width, 17f), format);
    }

    private static void DrawCellValue(
        Graphics graphics, string text, Font font, float x, float y, float width, float height,
        bool alignRight = true, bool alignCenter = false)
    {
        var rightToLeft = ContainsRightToLeft(text);
        using var format = new StringFormat {
            Alignment = alignCenter ? StringAlignment.Center :
                (alignRight || rightToLeft ? StringAlignment.Far : StringAlignment.Near),
            LineAlignment = StringAlignment.Center,
            FormatFlags = rightToLeft ? StringFormatFlags.DirectionRightToLeft : 0,
        };
        graphics.DrawString(text, font, Brushes.Black, new RectangleF(x, y, width, height), format);
    }

    private static float DrawBilingualValueBlock(
        Graphics graphics, string arabicLabel, string englishLabel, string value,
        Font labelFont, Font valueFont, float y, float width, bool narrowPaper)
    {
        if (string.IsNullOrWhiteSpace(value)) return y;
        if (narrowPaper)
        {
            y += DrawAlignedText(graphics, arabicLabel, labelFont, y, width, rightToLeft: true);
            y += DrawAlignedText(graphics, englishLabel, labelFont, y, width, rightToLeft: false);
        }
        else
        {
            var halfWidth = (width - 6f) / 2f;
            DrawAlignedText(graphics, englishLabel, labelFont, y, halfWidth, rightToLeft: false);
            DrawAlignedText(graphics, arabicLabel, labelFont, y, halfWidth, rightToLeft: true, x: Left + halfWidth + 6f);
            y += 18f;
        }
        y += DrawWrappedRtlAware(graphics, value, valueFont, Left, y, width);
        return y + 5f;
    }

    private static string GetString(JsonElement element, string property)
    {
        return element.TryGetProperty(property, out var value) ? value.ToString() : "";
    }

    private static string NormalizeAction(JsonElement line)
    {
        var action = GetString(line, "action").Trim().ToLowerInvariant();
        if (action == "update")
        {
            return GetQuantity(line, "delta_quantity") < 0 ? "reduce" : "add";
        }
        return action is "new" or "add" or "reduce" or "cancel" ? action : "new";
    }

    private static decimal GetQuantity(JsonElement element, string property)
    {
        if (!element.TryGetProperty(property, out var value)) return 0;
        if (value.ValueKind == JsonValueKind.Number && value.TryGetDecimal(out var number)) return number;
        return decimal.TryParse(value.ToString(), NumberStyles.Number, CultureInfo.InvariantCulture, out number)
            ? number
            : 0;
    }

    private static string FormatQuantity(decimal quantity) =>
        quantity.ToString("0.###", CultureInfo.InvariantCulture);

    private static string FormatTicketTime(string value)
    {
        if (!DateTime.TryParse(
                value,
                CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal,
                out var utc))
        {
            return value;
        }
        return utc.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);
    }

    private static string Shorten(string text, int maxLength)
    {
        var normalized = string.Join(" ", text.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
        return normalized.Length <= maxLength ? normalized : normalized[..(maxLength - 1)] + "…";
    }

    private static void DrawCentered(Graphics graphics, string text, Font font, float y, float width)
    {
        using var format = new StringFormat { Alignment = StringAlignment.Center };
        graphics.DrawString(text, font, Brushes.Black, new RectangleF(Left, y, width, 22f), format);
    }

    private static void DrawCenteredRtlAware(Graphics graphics, string text, Font font, float y, float width)
    {
        using var format = new StringFormat {
            Alignment = StringAlignment.Center,
            FormatFlags = ContainsRightToLeft(text) ? StringFormatFlags.DirectionRightToLeft : 0,
        };
        graphics.DrawString(text, font, Brushes.Black, new RectangleF(Left, y, width, 22f), format);
    }

    private static float DrawAlignedText(
        Graphics graphics, string text, Font font, float y, float width, bool rightToLeft, float? x = null)
    {
        var height = MeasureWrapped(graphics, text, font, width);
        using var format = new StringFormat {
            Alignment = rightToLeft ? StringAlignment.Far : StringAlignment.Near,
            FormatFlags = rightToLeft ? StringFormatFlags.DirectionRightToLeft : 0,
        };
        graphics.DrawString(text, font, Brushes.Black, new RectangleF(x ?? Left, y, width, height), format);
        return height;
    }

    private static float DrawWrapped(Graphics graphics, string text, Font font, float x, float y, float width)
    {
        var bounds = new RectangleF(x, y, width, 1000f);
        var size = graphics.MeasureString(text, font, new SizeF(width, 1000f));
        graphics.DrawString(text, font, Brushes.Black, bounds);
        return Math.Max(16f, size.Height);
    }

    private static float MeasureWrapped(Graphics graphics, string text, Font font, float width) =>
        Math.Max(16f, graphics.MeasureString(text, font, new SizeF(width, 1000f)).Height);

    private static float DrawWrappedRtlAware(
        Graphics graphics, string text, Font font, float x, float y, float width)
    {
        var height = MeasureWrapped(graphics, text, font, width);
        using var format = new StringFormat {
            Alignment = ContainsRightToLeft(text) ? StringAlignment.Far : StringAlignment.Near,
            FormatFlags = ContainsRightToLeft(text) ? StringFormatFlags.DirectionRightToLeft : 0,
        };
        graphics.DrawString(text, font, Brushes.Black, new RectangleF(x, y, width, height), format);
        return height;
    }

    private static bool ContainsRightToLeft(string text) =>
        text.Any(character => character is >= '\u0590' and <= '\u08FF');

    private static float DrawHeaderValue(Graphics graphics, string label, string value, Font font, float y, float width)
    {
        if (string.IsNullOrWhiteSpace(value)) return y;
        return y + DrawWrapped(graphics, $"{label}: {value}", font, Left, y, width);
    }

    private static void DrawDivider(Graphics graphics, float y, float width)
    {
        graphics.DrawLine(Pens.Black, Left, y, Left + width, y);
    }
}

using System.Drawing;
using System.Drawing.Imaging;
using System.Drawing.Text;
using System.Globalization;
using System.Text.Json;

// A stateful renderer: each page consumes only characters that actually fit.
// Data, action, and routing decisions remain owned by the Odoo snapshot.
sealed class KitchenTicketRenderer
{
    private sealed record Row(string Text, float Points, bool Bold = false, bool Center = false, bool Rule = false, bool ItemStart = false);
    private readonly List<Row> rows = [];
    private int rowIndex;
    private int charOffset;
    private int pageNumber;
    private readonly string orderReference;
    private readonly string trackingNumber;
    public KitchenTicketRenderer(JsonElement payload)
    {
        var lines = payload.GetProperty("lines").EnumerateArray().ToArray();
        var actions = lines.Select(Action).ToArray();
        var allCancelled = actions.Length > 0 && actions.All(a => a == "cancel");
        var changed = actions.Any(a => a is "add" or "reduce" or "cancel" or "update");
        var order = payload.GetProperty("order");
        orderReference = Get(order, "reference");
        trackingNumber = Get(order, "tracking_number").Trim();
        bool cancelled = payload.TryGetProperty("cancellation", out var cancel);
        Add(cancelled || allCancelled ? "CANCEL" : changed ? "تغييرات المطبخ" : "طلب مطبخ • جديد", cancelled || allCancelled ? 20 : 14, true, true);
        if (trackingNumber.Length > 0)
        {
            Add("رقم الطلب", 10, true, true);
            Add(trackingNumber, 20, true, true);
            Add(orderReference, 10, false, true);
        }
        else
        {
            // Legacy jobs carry only the reference; never infer a tracking number from it.
            Add(orderReference, 17, true, true);
        }
        var time = Get(order, "created_at");
        if (DateTime.TryParse(time, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out var dt))
            time = dt.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);
        if (time.Length > 0) Add($"الوقت: {time}", 10, false, true);
        Header("الكاشير", Get(order, "requested_by"));
        Header("الطاولة", Get(order, "table"));
        if (cancelled)
        {
            Header("سبب الإلغاء", Get(cancel, "reason_label"));
            Header("ملاحظة السبب", Get(cancel, "reason_note"));
        }
        Rule();
        foreach (var line in lines)
        {
            var action = Action(line);
            var qty = Quantity(line, "quantity");
            var previous = Quantity(line, "previous_quantity");
            var delta = Quantity(line, "delta_quantity");
            var qtyText = action switch {
                "new" => "+" + Format(qty),
                "add" => "+" + Format(Math.Abs(delta)),
                "reduce" => "-" + Format(Math.Abs(delta)),
                "cancel" => "×" + Format(previous != 0 ? previous : Math.Abs(delta)),
                _ => Format(qty),
            };
            var label = action switch {
                "new" => "جديد", "add" => "إضافة",
                "reduce" => "تخفيض", "cancel" => "CANCEL", "update" => "تعديل", _ => "جديد",
            };
            rows.Add(new Row(label, action == "cancel" ? 18 : 10, Bold: true, ItemStart: true));
            Add($"الكمية: {qtyText}", 13, true);
            // full_product_name is one authoritative string; never guess how to split attributes.
            Add(Get(line, "name"), 13, true);
            if (action == "add") Header("الإجمالي", Format(qty));
            if (action == "reduce") Header("المتبقي", Format(qty));
            Header("السبب", Get(line, "reason_label"));
            Header("تفاصيل السبب", Get(line, "reason_note"));
            Header("ملاحظة", Get(line, "note"));
            Rule();
        }
        Add("نهاية الطلب", 10, true, true);
    }

    private void Add(string text, float points, bool bold = false, bool center = false)
    { if (!string.IsNullOrWhiteSpace(text)) rows.Add(new Row(text, points, bold, center)); }
    private void Header(string label, string value) { if (!string.IsNullOrWhiteSpace(value)) Add($"{label}: {value}", 10, true); }
    private void Rule() => rows.Add(new Row("", 0, Rule: true));
    internal (string Text, float Points)[] PreviewRows() => rows.Select(row => (row.Text, row.Points)).ToArray();
    private static string Get(JsonElement e, string p) => e.TryGetProperty(p, out var v) && v.ValueKind is not JsonValueKind.Null ? v.ToString() : "";
    internal static decimal Quantity(JsonElement e, string p)
    {
        if (!e.TryGetProperty(p, out var value)) return 0m;
        if (value.ValueKind == JsonValueKind.Number && value.TryGetDecimal(out var numeric)) return numeric;
        return decimal.TryParse(value.ToString(), NumberStyles.Number, CultureInfo.InvariantCulture, out var parsed) ? parsed : 0m;
    }
    private static string Format(decimal n) => n.ToString("0.###", CultureInfo.InvariantCulture);
    private static string Action(JsonElement line)
    {
        var action = Get(line, "action").Trim().ToLowerInvariant();
        if (action == "update") return Quantity(line, "delta_quantity") switch {
            < 0 => "reduce", > 0 => "add", _ => "update",
        };
        return action is "new" or "add" or "reduce" or "cancel" ? action : "new";
    }

    // Returns true when another page is needed. Height and width use the same
    // 1/100-inch units as PrintDocument; every fitted substring is drawn once.
    public bool DrawPage(Graphics g, float x, float width, float bottom)
    {
        float y = 8;
        pageNumber++;
        if (pageNumber > 1)
        {
            using var continuationFont = new Font("Segoe UI", 11, FontStyle.Bold);
            using var continuationFormat = new StringFormat(StringFormat.GenericDefault) {
                Alignment = StringAlignment.Center,
                FormatFlags = StringFormatFlags.DirectionRightToLeft | StringFormatFlags.LineLimit,
                Trimming = StringTrimming.None,
            };
            var continuation = trackingNumber.Length > 0
                ? $"متابعة الطلب • صفحة {pageNumber}\nرقم الطلب: {trackingNumber}\n{orderReference}"
                : $"متابعة الطلب • صفحة {pageNumber}\n{orderReference}";
            var maximum = new SizeF(width, Math.Max(1, bottom / 3));
            var measured = g.MeasureString(continuation, continuationFont, maximum, continuationFormat, out int fittedHeader, out _);
            if (fittedHeader < continuation.Length)
                throw new InvalidOperationException("Kitchen continuation reference does not fit safely.");
            var height = measured.Height + 3;
            g.DrawString(continuation, continuationFont, Brushes.Black, new RectangleF(x, y, width, height), continuationFormat);
            y += height + 7;
            g.DrawLine(Pens.Black, x, y, x + width, y);
            y += 8;
        }
        int startRow = rowIndex, startOffset = charOffset;
        while (rowIndex < rows.Count)
        {
            var row = rows[rowIndex];
            // Keep action, quantity and at least the first name line together.
            if (row.ItemStart && y > 100 && bottom - y < 95) break;
            if (row.Rule)
            {
                if (y + 13 > bottom) break;
                g.DrawLine(Pens.Black, x, y + 4, x + width, y + 4);
                y += 13; rowIndex++; continue;
            }
            using var font = new Font("Segoe UI", row.Points, row.Bold ? FontStyle.Bold : FontStyle.Regular);
            using var format = new StringFormat(StringFormat.GenericDefault) {
                Alignment = row.Center ? StringAlignment.Center : StringAlignment.Near,
                FormatFlags = StringFormatFlags.DirectionRightToLeft | StringFormatFlags.LineLimit,
                Trimming = StringTrimming.None,
            };
            var available = bottom - y;
            var lineHeight = font.GetHeight(g);
            if (available < lineHeight + 3) break;
            var text = row.Text[charOffset..];
            var area = new SizeF(width, available - 2);
            var measured = g.MeasureString(text, font, area, format, out int fitted, out _);
            if (fitted <= 0) break;
            var segment = text[..fitted];
            // Re-measure the exact drawn segment; a small padding prevents a last-line clip.
            var height = Math.Min(available, Math.Max(lineHeight, measured.Height) + 2);
            g.DrawString(segment, font, Brushes.Black, new RectangleF(x, y, width, height), format);
            y += height + 4;
            charOffset += fitted;
            if (charOffset >= row.Text.Length) { rowIndex++; charOffset = 0; }
            else break;
        }
        if (rowIndex == startRow && charOffset == startOffset && rowIndex < rows.Count)
            throw new InvalidOperationException("Kitchen ticket page is too small to fit one line safely.");
        return rowIndex < rows.Count;
    }
}

static class KitchenTicketPreview
{
    // Offline-only example; never opens config, pairs, touches Odoo, or prints.
    public static int Run(string[] args)
    {
        if (args.Length != 1) return 2;
        Directory.CreateDirectory(args[0]);
        const string sample = """
        {"order":{"reference":"SHAMI/000018","tracking_number":"035","created_at":"2026-11-07 11:35:00","requested_by":"أحمد","table":"4"},"lines":[{"action":"new","quantity":2,"name":"كباب لحم (كبير، دبل جبن)","note":"بدون بصل"},{"action":"new","quantity":1,"name":"2 نص مسحب مع رز مع 1 لتر بيبسي"},{"action":"add","quantity":3,"delta_quantity":1,"name":"شيش طاووق"},{"action":"reduce","quantity":1,"delta_quantity":-2,"name":"أوصال لحم","reason_label":"تعديل العميل"},{"action":"cancel","quantity":0,"previous_quantity":2,"delta_quantity":-2,"name":"كفتة طحينية","reason_label":"طلب خاطئ","reason_note":"ملاحظة السبب"}]}
        """;
        using var document = JsonDocument.Parse(sample);
        var mixedRows = new KitchenTicketRenderer(document.RootElement).PreviewRows();
        if (mixedRows[0] != ("تغييرات المطبخ", 14f) ||
            !mixedRows.Contains(("رقم الطلب", 10f)) || !mixedRows.Contains(("035", 20f)) ||
            !mixedRows.Contains(("SHAMI/000018", 10f)) ||
            mixedRows.Count(row => row == ("CANCEL", 18f)) != 1 ||
            !mixedRows.Contains(("تخفيض", 10f)) || !mixedRows.Contains(("جديد", 10f)) ||
            !mixedRows.Contains(("الكمية: ×2", 13f)) || !mixedRows.Contains(("المتبقي: 1", 10f)))
            throw new InvalidOperationException("Mixed kitchen action labels or quantities changed unexpectedly.");
        var cancelledTicket = JsonSerializer.SerializeToElement(new {
            order = document.RootElement.GetProperty("order"),
            lines = document.RootElement.GetProperty("lines").EnumerateArray().Where(line => line.GetProperty("action").GetString() == "cancel").ToArray(),
        });
        var cancelledRows = new KitchenTicketRenderer(cancelledTicket).PreviewRows();
        if (cancelledRows[0] != ("CANCEL", 20f) || cancelledRows.Count(row => row == ("CANCEL", 18f)) != 1 ||
            !cancelledRows.Contains(("الكمية: ×2", 13f)) || !cancelledRows.Contains(("035", 20f)))
            throw new InvalidOperationException("Kitchen cancellation heading or quantity is incorrect.");
        var legacyTicket = JsonSerializer.SerializeToElement(new {
            order = new { reference = "LEGACY/000018" },
            lines = document.RootElement.GetProperty("lines").EnumerateArray().Take(1).ToArray(),
        });
        var legacyRows = new KitchenTicketRenderer(legacyTicket).PreviewRows();
        if (!legacyRows.Contains(("LEGACY/000018", 17f)) || legacyRows.Any(row => row.Text == "رقم الطلب"))
            throw new InvalidOperationException("Legacy kitchen reference fallback changed.");
        var wholeCancellation = JsonSerializer.SerializeToElement(new {
            order = new { reference = "ORD/007", tracking_number = 42 },
            cancellation = new { reason_label = "خطأ" },
            lines = document.RootElement.GetProperty("lines").EnumerateArray().Take(1).ToArray(),
        });
        var wholeRows = new KitchenTicketRenderer(wholeCancellation).PreviewRows();
        if (wholeRows[0] != ("CANCEL", 20f) || !wholeRows.Contains(("42", 20f)) ||
            !wholeRows.Contains(("سبب الإلغاء: خطأ", 10f)))
            throw new InvalidOperationException("Whole-order cancellation tracking failed.");
        using var numericTest = JsonDocument.Parse("{\"number\":1e2,\"negative\":-2.5e-1,\"string\":\"3.5\"}");
        if (KitchenTicketRenderer.Quantity(numericTest.RootElement, "number") != 100m ||
            KitchenTicketRenderer.Quantity(numericTest.RootElement, "negative") != -0.25m ||
            KitchenTicketRenderer.Quantity(numericTest.RootElement, "string") != 3.5m)
            throw new InvalidOperationException("Kitchen quantity parsing failed.");
        foreach (var paper in new[] { "58", "80" })
        {
            var width = paper == "58" ? 190 : 270;
            var renderer = new KitchenTicketRenderer(document.RootElement);
            int page = 0; bool more;
            do
            {
                using var image = new Bitmap(width + 10, 1150);
                image.SetResolution(100, 100);
                using var graphics = Graphics.FromImage(image);
                graphics.Clear(Color.White);
                graphics.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
                more = renderer.DrawPage(graphics, 5, width, 1135);
                image.Save(Path.Combine(args[0], $"kitchen-{paper}-{++page}.png"), ImageFormat.Png);
                if (page > 30) throw new InvalidOperationException("Kitchen pagination exceeded preview limit.");
            } while (more);
            Console.WriteLine($"{paper}: {page} page(s)");

            var cancelledRenderer = new KitchenTicketRenderer(cancelledTicket);
            using (var image = new Bitmap(width + 10, 800))
            {
                image.SetResolution(100, 100);
                using var graphics = Graphics.FromImage(image);
                graphics.Clear(Color.White);
                graphics.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
                if (cancelledRenderer.DrawPage(graphics, 5, width, 785))
                    throw new InvalidOperationException("Cancellation preview unexpectedly exceeded one page.");
                image.Save(Path.Combine(args[0], $"kitchen-{paper}-cancel.png"), ImageFormat.Png);
            }

            var original = document.RootElement;
            var fresh = JsonSerializer.SerializeToElement(new {
                order = original.GetProperty("order"),
                lines = original.GetProperty("lines").EnumerateArray().Take(2).ToArray(),
            });
            var freshRenderer = new KitchenTicketRenderer(fresh);
            using (var image = new Bitmap(width + 10, 800))
            {
                image.SetResolution(100, 100);
                using var graphics = Graphics.FromImage(image);
                graphics.Clear(Color.White);
                graphics.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
                if (freshRenderer.DrawPage(graphics, 5, width, 785))
                    throw new InvalidOperationException("New-order preview unexpectedly exceeded one page.");
                image.Save(Path.Combine(args[0], $"kitchen-{paper}-new.png"), ImageFormat.Png);
            }

            // Exercise continuation with many items and a single very long note.
            var stressLines = Enumerable.Range(0, 35).Select(i => new {
                action = i % 4 == 0 ? "reduce" : "new", quantity = 1,
                previous_quantity = 2, delta_quantity = -1,
                name = $"صنف {i + 1}: 2 نص مسحب مع رز مع 1 لتر بيبسي",
                note = i == 17 ? string.Join(" ", Enumerable.Repeat("ملاحظة إضافية", 180)) : "بدون بصل",
            }).ToArray();
            var stress = JsonSerializer.SerializeToElement(new {
                order = new { reference = "STRESS/000001", tracking_number = "035", created_at = "2026-11-07 11:35:00" },
                lines = stressLines,
            });
            var stressRenderer = new KitchenTicketRenderer(stress);
            int stressPages = 0;
            do
            {
                using var image = new Bitmap(width + 10, 1150);
                image.SetResolution(100, 100);
                using var graphics = Graphics.FromImage(image);
                graphics.Clear(Color.White);
                more = stressRenderer.DrawPage(graphics, 5, width, 1135);
                if (stressPages == 1)
                    image.Save(Path.Combine(args[0], $"kitchen-{paper}-continuation.png"), ImageFormat.Png);
                if (++stressPages > 30) throw new InvalidOperationException("Kitchen stress pagination did not terminate.");
            } while (more);
            if (stressPages <= 1) throw new InvalidOperationException("Kitchen stress pagination did not reach a second page.");
            Console.WriteLine($"{paper}: stress {stressPages} pages, complete");
        }
        return 0;
    }
}

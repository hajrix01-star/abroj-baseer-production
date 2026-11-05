#Requires -Version 5.1
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Baseer.Connection.psm1') -Force
if ($CheckOnly) { Get-BaseerConnectionInfo | ConvertTo-Json; exit 0 }
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object Windows.Forms.Form
$form.Text = 'Baseer | اتصال أودو الآمن'
$form.ClientSize = New-Object Drawing.Size(550, 350)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.Font = New-Object Drawing.Font('Segoe UI', 10)
$heading = New-Object Windows.Forms.Label
$heading.Text = "اتصال بصير — أدخل المفتاح هنا، وليس في المحادثة`r`nhttps://baseer.abroj.sa"
$heading.SetBounds(20, 16, 510, 52)
$heading.RightToLeft = 'Yes'
$form.Controls.Add($heading)
$dbLabel = New-Object Windows.Forms.Label
$dbLabel.Text = 'Database / قاعدة البيانات (اختياري)'
$dbLabel.SetBounds(20, 85, 510, 25)
$form.Controls.Add($dbLabel)
$database = New-Object Windows.Forms.TextBox
$database.SetBounds(20, 112, 510, 28)
$database.MaxLength = 128
$form.Controls.Add($database)
$keyLabel = New-Object Windows.Forms.Label
$keyLabel.Text = 'Odoo API key / مفتاح API'
$keyLabel.SetBounds(20, 155, 510, 25)
$form.Controls.Add($keyLabel)
$keyBox = New-Object Windows.Forms.TextBox
$keyBox.SetBounds(20, 182, 510, 28)
$keyBox.UseSystemPasswordChar = $true
$keyBox.MaxLength = 1024
$form.Controls.Add($keyBox)
$note = New-Object Windows.Forms.Label
$note.Text = 'يُحفظ المفتاح مشفراً لهذا المستخدم على Windows. الاختبار للقراءة فقط.'
$note.RightToLeft = 'Yes'
$note.SetBounds(20, 225, 510, 32)
$form.Controls.Add($note)
$status = New-Object Windows.Forms.Label
$status.SetBounds(20, 264, 510, 28)
$status.AutoEllipsis = $true
$form.Controls.Add($status)
$save = New-Object Windows.Forms.Button
$save.Text = 'Test && save / اختبار وحفظ'
$save.SetBounds(285, 305, 245, 32)
$form.Controls.Add($save)
$cancel = New-Object Windows.Forms.Button
$cancel.Text = 'Cancel / إلغاء'
$cancel.SetBounds(20, 305, 120, 32)
$cancel.DialogResult = 'Cancel'
$form.Controls.Add($cancel)
$form.CancelButton = $cancel
$form.AcceptButton = $save
$save.Add_Click({
    $save.Enabled = $false
    $status.Text = 'Testing secure read-only connection...'
    $form.Refresh()
    $connection = $null
    try {
        $secure = ConvertTo-SecureString -String $keyBox.Text -AsPlainText -Force
        $connection = New-BaseerConnection -ApiKey $secure -Database $database.Text
        $request = New-BaseerReadRequest -Model 'res.users' -Method 'context_get'
        $context = Invoke-BaseerRead -Request $request -Connection $connection | ConvertFrom-Json
        if ($null -eq $context.uid -or [int]$context.uid -le 0) { throw 'Odoo did not confirm an authenticated user.' }
        Save-BaseerConnection -Connection $connection
        $keyBox.Clear()
        $status.Text = 'Connected. Key saved encrypted. / تم الاتصال والحفظ المشفر'
        $note.Text = 'اكتمل الاتصال. عمليات التعديل غير مفعلة في أداة القراءة.'
        $save.Text = 'Saved / تم الحفظ'
        $form.Tag = 'connected'
    } catch {
        $message = $_.Exception.Message
        if ($message -notmatch '^(Odoo |Cannot reach Odoo securely|Invalid connection input\.|Could not securely save connection)') { $message = 'Secure connection setup failed; previous connection was retained.' }
        $status.Text = $message
        $save.Enabled = $true
    } finally { if ($null -ne $connection) { $connection.ApiKey.Dispose() }; $secure = $null }
})
$form.Add_FormClosed({ $keyBox.Clear() })
[void]$form.ShowDialog()
$form.Dispose()

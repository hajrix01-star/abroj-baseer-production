# Baseer Print Agent

Windows source and local QA build for the pull-only agent used by `baseer_pos_print_bridge`.

Every installer release follows the [Odoo registration and QA release runbook](../../docs/build-governance/PRINT-AGENT-RELEASE-PROCESS.md). Verify the release in Print Agent Center before closing the release.

The Windows x64 agent rejects non-HTTPS Odoo URLs, pairs once, stores its token with machine-level DPAPI in an ACL-restricted directory, polls Odoo over HTTPS, and records a durable in-flight job before asking Windows to print. Receipt/kitchen layout belongs to Odoo. The agent has no local HTTP listener. The installed watchdog and print worker run in the signed-in user's interactive session; they are not a LocalSystem Windows service. Installer/repair elevation is separate from the limited-user worker and safe updater. QA uses its own directory, mutexes and restricted server profile.

To rebuild the executable from source:

```powershell
dotnet publish -c Release
Baseer.PrintAgent.exe pair --url https://odoo.example --device WINDOWS-DEVICE-ID --code ONE-TIME-CODE
Baseer.PrintAgent.exe run
```

Use the QA profile and release runbook before promotion. A successful submission means Windows accepted the job; it does not prove paper exited the printer.

## Local diagnostics (1.5.22)

Double-click the running agent's icon beside the Windows clock, choose **Print status**, or run `Baseer.PrintAgent.exe status`. New installations also add **Baseer Print Status** to Start. The running worker's icon opens its own current version after an automatic update.

The window shows recent Odoo contact, job/stage/error codes, suggested actions and Windows queue observations when the driver exposes them. Warnings appear beside the clock, at most once per minute. Queue disappearance, PRINTED and COMPLETE do not universally confirm physical paper. An unknown result requires checking paper and the queue before any manual reprint; diagnostics never retry, cancel or modify printer jobs.

**Export report** creates a ZIP containing only sanitized metadata/events, without configuration, pairing keys, raw logs or receipt images. Events rotate within two 1 MiB files, expire from displayed/exported evidence after seven days, and the view/export is limited to 200 events. Diagnostic storage failures never change print outcomes.

**Capture 3 jobs** is optional and off by default. After explicit confirmation it saves the original Odoo JPEG, processed PNG and SHA-256 manifest locally for up to three jobs within 15 minutes, at most 20 MiB. These can contain customer information, stay in the protected `diagnostics/captures` folder, and are excluded from support export. Cleanup removes them after 24 hours when diagnostics next run (a stopped PC cannot execute cleanup). Compare these images against the physical paper when investigating distorted digits. This evidence narrows the failing stage; it cannot diagnose an unreported mechanical fault automatically.

Run local no-printer checks against the compiled DLL:

```powershell
pwsh -File qa/Test-AgentDiagnostics.ps1 -AgentDll bin/Release/net8.0-windows/win-x64/Baseer.PrintAgent.dll
pwsh -File qa/Test-RasterPixelScale.ps1 -AgentDll bin/Release/net8.0-windows/win-x64/Baseer.PrintAgent.dll
```

Candidate verification and real QA/physical acceptance are recorded separately in [PAD1](../../docs/build-governance/PRINT-AGENT-DIAGNOSTICS-20261122.md). Building this version does not publish it or register it as the production download.

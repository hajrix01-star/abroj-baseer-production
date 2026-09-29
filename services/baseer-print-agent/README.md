# Baseer Print Agent

Windows source and local QA build for the pull-only agent used by `baseer_pos_print_bridge`.

The standalone Windows x64 QA executable is built at `artifacts/win-x64/Baseer.PrintAgent.exe`. It has not been installed, paired with a real HTTPS Odoo system, or tested against a physical thermal printer. The agent never exposes `localhost`; it rejects non-HTTPS server URLs, pairs once, stores its token with machine-level DPAPI in an ACL-restricted ProgramData directory, polls Odoo over HTTPS, and records a durable in-flight job before asking the Windows spooler to print. Pairing or updating this protected configuration must run from an elevated Administrator console.

To rebuild the executable from source:

```powershell
dotnet publish -c Release
Baseer.PrintAgent.exe pair --url https://odoo.example --device WINDOWS-DEVICE-ID --code ONE-TIME-CODE
Baseer.PrintAgent.exe run
```

Run it initially in a visible QA console. Convert it to a service only after a manager confirms that the configured service account can see the machine-wide printer and has permission to print. A successful test means the Windows spooler accepted the job; it does not prove paper exited the printer.

The v1 service account is **LocalSystem only**. Install each printer machine-wide and verify it is visible and printable from LocalSystem before enabling the service. A named service account is intentionally unsupported in v1 because the protected token directory grants access only to LocalSystem and Administrators; adding a named account requires a separate installer/configuration and security review.

# IC1 parser-only install recovery review

Decision: GO

Candidate: `24bc64d2a778590e8e8e6577eb3866d18727bc24`.
Runner: `docs/build-governance/ic1_install_recovery.py`.
Runner SHA256: `1dc28f6c8cb32cca566e6fafcdaf40a5192ae97574103c691edfa604631378b2`.

The original install log records CLI rejection of `--i18n-overwrite` without an update option, before Odoo server startup. The independently reviewed recovery removes only that incompatible flag from the otherwise identical new-addon initialization command. It preserves the frozen source, initial failure log and accepted release helper; the working release helper is byte-identical to its frozen evidence copy.

Before retry, the runner verifies the exact accepted candidate and prior GO, stopped MAIN on its original pinned image/mounts, unchanged protected columns/data, versions, security memberships and user presets, uninstalled module/no pending module operations, and the exact prepared compose content. It uses an exclusive maintenance lock and a separate retry log.

After initialization it retains original-column/data and security/version preservation, default-true permission and empty-audit checks. The backup mapping is switched and reloaded before a coherent post-release backup while MAIN remains stopped. Only then does it start the runtime and verify health and mounted source. Failure before startup leaves MAIN stopped for investigation. This approval is limited to the identified parser-only recovery of the exact candidate; it does not authorize source or accounting changes.

Reviewer: icons_release. Runner reviewed without execution or MAIN mutation. Postdeployment preservation/runtime evidence remains required.

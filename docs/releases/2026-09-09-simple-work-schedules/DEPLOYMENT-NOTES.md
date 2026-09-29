# WS1 deployment notes

The protected installation completed successfully; 245 protected tables matched on every pre-existing row and column, and the original service restarted healthy.

The first post-start runtime assertion expected separate mounts for the two third-party subdirectories, while the accepted compose configuration mounts their common parent. It raised StopIteration after successful installation/restart. The verification was corrected to check the actual three read-only addon mounts (baseer, extra, third-party parent), and only `verify-runtime` was rerun. Installation and backup were not repeated. Runtime evidence now asserts the pinned image, matching frozen paths, installed version, no pending modules, and HTTP 200.

A separate read-only ORM verification initially used `docker exec odoo shell` without the image entrypoint that supplies database connection arguments. It failed before connecting. Repeating through `/entrypoint.sh` succeeded, as recorded in `main-verify.log`. Neither attempt changed business data.

The root browser verified the original Arabic Employees > Configuration > Work schedule templates menu and its empty state. QA UI test template262 was deleted with native ORM after asserting its exact test name and no employee version references; QA stopped afterwards. No employee schedule was assigned on MAIN.

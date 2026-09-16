# Baseer Workspace

The Baseer Workspace is an Odoo application that provides role-curated access
to approved Baseer operations. It depends on the existing access-role, sales
heat-calendar and purchase-expense-dashboard modules; it does not create
accounting documents, analytic allocations or business data.

The workspace is a navigation and visibility layer. Native Odoo permissions,
company isolation and each target feature's own access rules remain the source
of authorization. Its backend assets provide the workspace presentation only.

Operational deployment and recovery are governed by
`docs/build-governance/BUILD-GOVERNANCE.md`.

"""Fixed, read-only endpoint for the advance reconciliation snapshot."""
from odoo import http
from odoo.http import request


class BaseerAdvanceSnapshotController(http.Controller):
    @http.route(
        '/baseer/api/v1/payroll/advance-snapshot',
        type='jsonrpc', auth='user', methods=['POST'], csrf=False,
    )
    def advance_snapshot(self, company_key=None, cutoff=None, employee_id=None,
                         cursor=None, snapshot_token=None):
        return request.env['baseer.hr.loan.snapshot'].read_snapshot(
            company_key=company_key,
            cutoff=cutoff,
            employee_id=employee_id,
            cursor=cursor,
            snapshot_token=snapshot_token,
        )

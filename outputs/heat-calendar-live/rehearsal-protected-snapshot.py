"""Read-only business-record baseline for a fresh rehearsal database."""
import json


protected_models = (
    "account.move", "account.move.line", "account.payment", "hr.employee",
    "hr.payslip", "res.partner", "baseer.pos.daily.report",
)


def count(model):
    domain = [("user_ids", "=", False)] if model == "res.partner" else []
    return env[model].sudo().with_context(active_test=False).search_count(domain)


print(json.dumps({model: count(model) for model in protected_models}, sort_keys=True))

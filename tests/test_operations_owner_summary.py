"""Pure unittest coverage for the owner summary's accounting invariants."""

import copy
import importlib.util
from pathlib import Path
import unittest
from decimal import Decimal, localcontext


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_addons/baseer_operations_report/models/owner_summary.py"
)
SPEC = importlib.util.spec_from_file_location("operations_owner_summary", MODULE_PATH)
OWNER_SUMMARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OWNER_SUMMARY)
build_owner_summary = OWNER_SUMMARY.build_owner_summary
D = Decimal


def incoming(line_id=1, amount="100.00", channels=None, **overrides):
    amount = D(amount)
    event = {
        "company_id": 1,
        "direction": "incoming",
        "source_model": "pos.order",
        "source_id": line_id,
        "line_model": "pos.order.line",
        "line_id": line_id,
        "amount": amount,
        "channels": [("cash", "Cash", amount)] if channels is None else channels,
    }
    event.update(overrides)
    return event


def outgoing(line_id=1, payment_line_id=101, amount="20.00", **overrides):
    event = {
        "company_id": 1,
        "direction": "outgoing",
        "source_model": "account.payment",
        "source_id": line_id,
        "line_model": "account.move.line",
        "line_id": line_id,
        "payment_line_id": payment_line_id,
        "amount": D(amount),
        "classification": "unclassified",
    }
    event.update(overrides)
    return event


def classified_outgoing(kind, line_id=1, payment_line_id=101, amount="20.00",
                       **facts):
    event = outgoing(line_id, payment_line_id, amount, classification=kind)
    event.update(facts)
    return event


class OwnerSummaryTests(unittest.TestCase):
    def build(self, events, liquidity=None, company_id=1):
        return build_owner_summary(events, {} if liquidity is None else liquidity,
                                   company_id=company_id)

    def test_advance_and_salary_cash_are_distinct_without_deduction_recount(self):
        events = [
            classified_outgoing('employee_advance', 1, 101, '500.00'),
            classified_outgoing('payroll', 2, 102, '600.00'),
            classified_outgoing('payroll', 2, 103, '900.00'),
        ]
        result = self.build(events, {101: D('500'), 102: D('600'), 103: D('900')})
        self.assertEqual(result['cash_total'], D('2000.00'))
        buckets = {item['key']: item for item in result['outflow_buckets']}
        self.assertEqual(buckets['payroll']['amount'], D('1500.00'))
        self.assertEqual(buckets['employee_advance']['amount'], D('500.00'))
        self.assertEqual(buckets['payroll']['count'], 2)
        self.assertFalse(result['has_unclassified_outflows'])

    def test_operating_and_employee_service_keys_do_not_merge(self):
        events = [classified_outgoing(kind, index, 100 + index,
                                     service_key='shared_key', service_name='Same label')
                  for index, kind in enumerate(('operating_services', 'employee_services'), 1)]
        result = self.build(events, {101: D('20'), 102: D('20')})
        self.assertEqual({item['key'] for item in result['outflow_buckets']},
                         {'operating_services:shared_key', 'employee_services:shared_key'})
        self.assertEqual(result['cash_total'], D('40'))

    def test_empty_summary(self):
        result = self.build([])
        for key in ("incoming_total", "cash_total", "difference"):
            self.assertEqual(result[key], D("0"))
            self.assertIsInstance(result[key], D)
        self.assertEqual(result["channels"], [])
        self.assertEqual(result["outflow_buckets"], [])
        self.assertEqual(result["incoming_event_count"], 0)
        self.assertEqual(result["cash_event_count"], 0)
        self.assertIs(result["has_unclassified_outflows"], False)

    def test_income_minus_cash_outflow(self):
        result = self.build([incoming(), outgoing()], {101: D("20.00")})
        self.assertEqual(result["incoming_total"], D("100.00"))
        self.assertEqual(result["cash_total"], D("20.00"))
        self.assertEqual(result["difference"], D("80.00"))
        self.assertEqual(result["incoming_event_count"], 1)
        self.assertEqual(result["cash_event_count"], 1)
        self.assertIs(result["has_unclassified_outflows"], True)

    def test_outflow_can_exceed_income(self):
        result = self.build([incoming(amount="10"), outgoing()], {101: D("20")})
        self.assertEqual(result["difference"], D("-10"))

    def test_mixed_tender_preserves_amounts_and_sorts_channel_keys(self):
        result = self.build([incoming(channels=[("cash", "Cash", D("25")),
                                                ("card", "Card", D("75"))])])
        self.assertEqual(result["channels"], [
            {"key": "card", "name": "Card", "amount": D("75"), "percentage": D("75.00")},
            {"key": "cash", "name": "Cash", "amount": D("25"), "percentage": D("25.00")},
        ])

    def test_same_channel_aggregates_across_income_events(self):
        result = self.build([incoming(), incoming(2, "25")])
        self.assertEqual(result["channels"][0]["amount"], D("125"))
        self.assertEqual(result["incoming_event_count"], 2)

    def test_signed_refund_reduces_income(self):
        result = self.build([incoming(), incoming(2, "-25")])
        self.assertEqual(result["incoming_total"], D("75"))
        self.assertEqual(result["channels"][0]["amount"], D("75"))
        self.assertEqual(result["channels"][0]["percentage"], D("100.00"))

    def test_refund_only_total_is_signed(self):
        result = self.build([incoming(amount="-25")])
        self.assertEqual(result["incoming_total"], D("-25"))
        self.assertEqual(result["difference"], D("-25"))
        self.assertEqual(result["channels"][0]["percentage"], D("100.00"))

    def test_zero_income_has_no_percentage(self):
        result = self.build([incoming(amount="0")])
        self.assertIsNone(result["channels"][0]["percentage"])

    def test_refund_cancelling_income_has_no_percentage(self):
        result = self.build([incoming(), incoming(2, "-100")])
        self.assertEqual(result["incoming_total"], D("0"))
        self.assertIsNone(result["channels"][0]["percentage"])

    def test_unallocated_channel_is_retained(self):
        result = self.build([incoming(channels=[("unallocated", "Unallocated", D("100"))])])
        self.assertEqual(result["channels"][0]["key"], "unallocated")
        self.assertEqual(result["channels"][0]["amount"], D("100"))

    def test_percentages_round_half_up(self):
        result = self.build([incoming(amount="32", channels=[
            ("a", "A", D("1")), ("b", "B", D("31")),
        ])])
        self.assertEqual(result["channels"][0]["percentage"], D("3.13"))
        self.assertEqual(result["channels"][1]["percentage"], D("96.88"))

    def test_rounded_percentages_may_total_99_99(self):
        result = self.build([incoming(amount="3", channels=[
            ("a", "A", D("1")), ("b", "B", D("1")), ("c", "C", D("1")),
        ])])
        self.assertEqual([c["percentage"] for c in result["channels"]], [D("33.33")] * 3)
        self.assertEqual(sum(c["percentage"] for c in result["channels"]), D("99.99"))

    def test_low_caller_precision_preserves_large_amounts_cents_and_percentages(self):
        events = [incoming(amount="999999999999999999.99", channels=[
            ("card", "Card", D("500000000000000000.00")),
            ("cash", "Cash", D("499999999999999999.99")),
        ]), outgoing(amount="20.00")]
        with localcontext() as caller_context:
            caller_context.prec = 6
            result = self.build(events, {101: D("20.00")})
            self.assertEqual(caller_context.prec, 6)
            self.assertEqual(result["incoming_total"], D("999999999999999999.99"))
            self.assertEqual(result["cash_total"], D("20.00"))
            self.assertEqual(result["difference"], D("999999999999999979.99"))
            self.assertEqual(result["channels"], [
                {"key": "card", "name": "Card", "amount": D("500000000000000000.00"),
                 "percentage": D("50.00")},
                {"key": "cash", "name": "Cash", "amount": D("499999999999999999.99"),
                 "percentage": D("50.00")},
            ])

    def test_reducer_does_not_claim_report_completeness_or_source_coverage(self):
        for events in ([], [incoming()]):
            with self.subTest(events=events):
                result = self.build(events)
                self.assertIs(result["has_unclassified_outflows"], False)
                self.assertFalse(any("complete" in key for key in result))
                self.assertFalse(any("coverage" in key for key in result))

    def test_payment_allocated_to_multiple_lines_counts_once_as_cash_event_and_in_bucket(self):
        result = self.build([outgoing(1, 101, "12.34"), outgoing(2, 101, "7.66")],
                            {101: D("20")})
        self.assertEqual(result["cash_total"], D("20"))
        self.assertEqual(result["outflow_buckets"], [
            {"key": "unclassified", "amount": D("20"), "count": 1},
        ])
        self.assertEqual(result["cash_event_count"], 1)

    def test_one_line_with_two_partial_payments_is_not_duplicate(self):
        result = self.build([outgoing(1, 101, "8"), outgoing(1, 102, "12")],
                            {101: D("8"), 102: D("12")})
        self.assertEqual(result["cash_total"], D("20"))
        self.assertEqual(result["outflow_buckets"][0]["count"], 2)

    def test_unconfirmed_bill_classification_has_unclassified_outflows(self):
        result = self.build([outgoing(classification="unconfirmed_bill_classification")],
                            {101: D("20")})
        self.assertIs(result["has_unclassified_outflows"], True)
        self.assertEqual(result["outflow_buckets"], [
            {"key": "unconfirmed_bill_classification", "amount": D("20"), "count": 1},
        ])

    def test_one_cash_witness_can_split_across_two_purchase_categories(self):
        result = self.build([
            classified_outgoing(
                "purchase", 1, 101, "12.34",
                category_path=[(10, "Items"), (11, "Food")],
            ),
            classified_outgoing(
                "purchase", 2, 101, "7.66",
                category_path=[(10, "Items"), (12, "Packaging")],
            ),
        ], {101: D("20")})
        buckets = {row["key"]: row for row in result["outflow_buckets"]}
        self.assertEqual(buckets["purchase:10/11"]["amount"], D("12.34"))
        self.assertEqual(buckets["purchase:10/12"]["amount"], D("7.66"))
        # Bucket counts are witnesses touched, deliberately non-additive.
        self.assertEqual(buckets["purchase:10/11"]["count"], 1)
        self.assertEqual(buckets["purchase:10/12"]["count"], 1)
        self.assertEqual(result["cash_total"], D("20"))
        self.assertEqual(result["cash_event_count"], 1)
        self.assertIs(result["has_unclassified_outflows"], False)

    def test_partial_cash_payments_keep_category_and_witness_totals_exact(self):
        result = self.build([
            classified_outgoing(
                "purchase", 1, 101, "8",
                category_path=[(10, "Items"), (11, "Food")],
            ),
            classified_outgoing(
                "purchase", 1, 102, "12",
                category_path=[(10, "Items"), (11, "Food")],
            ),
        ], {101: D("8"), 102: D("12")})
        self.assertEqual(result["cash_total"], D("20"))
        self.assertEqual(result["cash_event_count"], 2)
        bucket = next(row for row in result["outflow_buckets"]
                      if row["key"] == "purchase:10/11")
        self.assertEqual(bucket["amount"], D("20"))
        self.assertEqual(bucket["count"], 2)

    def test_unconfirmed_cash_cannot_mix_with_confirmed_category(self):
        events = [
            outgoing(1, 101, "12", classification="unconfirmed_bill_classification"),
            classified_outgoing(
                "purchase", 2, 101, "8",
                category_path=[(10, "Items"), (11, "Food")],
            ),
        ]
        with self.assertRaises(ValueError):
            self.build(events, {101: D("20")})

    def test_operating_account_and_employee_service_have_stable_identity_keys(self):
        result = self.build([
            classified_outgoing(
                "operating_account", 1, 101, "7",
                account_id=77, account_name="Electricity expense",
            ),
            classified_outgoing(
                "employee_services", 2, 102, "13",
                service_key="hr_medical_insurance", service_name="Medical insurance",
            ),
        ], {101: D("7"), 102: D("13")})
        buckets = {row["key"]: row for row in result["outflow_buckets"]}
        self.assertEqual(buckets["operating_account:77"]["amount"], D("7"))
        self.assertEqual(buckets["employee_services:hr_medical_insurance"]["amount"], D("13"))
        self.assertIs(result["has_unclassified_outflows"], False)

    def test_classified_facts_are_required_and_must_not_hide_unknown_data(self):
        invalid = (
            classified_outgoing("purchase", category_path=[]),
            classified_outgoing("purchase", category_path=[(0, "Items")]),
            classified_outgoing("operating_account", account_id=0, account_name="Expense"),
            classified_outgoing("employee_services", service_key="", service_name="Service"),
        )
        for event in invalid:
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.build([event], {101: D("20")})

    def test_two_classifications_on_separate_payments(self):
        result = self.build([outgoing(), outgoing(2, 102, "30", classification=
                                                 "unconfirmed_bill_classification")],
                            {101: D("20"), 102: D("30")})
        self.assertEqual({b["key"]: (b["amount"], b["count"]) for b in result["outflow_buckets"]},
                         {"unclassified": (D("20"), 1),
                          "unconfirmed_bill_classification": (D("30"), 1)})

    def test_mixed_companies_are_rejected(self):
        with self.assertRaises(ValueError):
            self.build([incoming(), incoming(2, company_id=2)])

    def test_company_two_is_accepted_when_explicitly_selected(self):
        result = self.build([incoming(company_id=2)], company_id=2)
        self.assertEqual(result["incoming_total"], D("100"))

    def test_missing_company_is_rejected(self):
        event = incoming()
        del event["company_id"]
        with self.assertRaises(ValueError):
            self.build([event])

    def test_cross_company_outflow_is_rejected(self):
        with self.assertRaises(ValueError):
            self.build([outgoing(company_id=2)], {101: D("20")})

    def test_duplicate_income_line_is_rejected(self):
        with self.assertRaises(ValueError):
            self.build([incoming(), incoming(source_model="sale.order", source_id=99)])

    def test_duplicate_allocation_is_rejected_even_with_another_source(self):
        with self.assertRaises(ValueError):
            self.build([outgoing(), outgoing(source_model="account.move", source_id=99)],
                       {101: D("40")})

    def test_inconsistent_classification_for_same_payment_is_rejected(self):
        with self.assertRaises(ValueError):
            self.build([outgoing(), outgoing(2, classification="unconfirmed_bill_classification")],
                       {101: D("40")})

    def test_unknown_classification_is_rejected(self):
        for classification in ("food", "", None):
            with self.subTest(classification=classification), self.assertRaises(ValueError):
                self.build([outgoing(classification=classification)], {101: D("20")})

    def test_missing_channel_witness_is_rejected(self):
        event = incoming()
        del event["channels"]
        with self.assertRaises(ValueError):
            self.build([event])

    def test_channel_sum_must_equal_income(self):
        for channels in ([], [("cash", "Cash", D("99.99"))],
                         [("cash", "Cash", D("100.01"))]):
            with self.subTest(channels=channels), self.assertRaises(ValueError):
                self.build([incoming(channels=channels)])

    def test_duplicate_channel_keys_in_one_event_are_rejected(self):
        with self.assertRaises(ValueError):
            self.build([incoming(channels=[("cash", "Cash", D("50")),
                                           ("cash", "Cash", D("50"))])])

    def test_channel_sign_must_match_its_event(self):
        for amount, channels in (("100", [("cash", "Cash", D("110")),
                                          ("card", "Card", D("-10"))]),
                                 ("-100", [("cash", "Cash", D("-110")),
                                           ("card", "Card", D("10"))])):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.build([incoming(amount=amount, channels=channels)])

    def test_zero_event_cannot_hide_offsetting_channels(self):
        with self.assertRaises(ValueError):
            self.build([incoming(amount="0", channels=[("cash", "Cash", D("10")),
                                                       ("card", "Card", D("-10"))])])

    def test_conflicting_channel_names_are_rejected(self):
        with self.assertRaises(ValueError):
            self.build([incoming(), incoming(2, channels=[("cash", "Different name", D("100"))])])

    def test_missing_extra_or_mismatched_liquidity_is_rejected(self):
        for liquidity in ({}, {101: D("19.99")}, {101: D("20.01")},
                          {101: D("20"), 102: D("1")}, {102: D("20")}):
            with self.subTest(liquidity=liquidity), self.assertRaises(ValueError):
                self.build([outgoing()], liquidity)

    def test_liquidity_without_events_is_rejected(self):
        with self.assertRaises(ValueError):
            self.build([], {101: D("20")})

    def test_nonpositive_outflows_are_rejected(self):
        for amount in ("0", "-0.01", "-20"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.build([outgoing(amount=amount)], {101: D(amount)})

    def test_invalid_event_money_is_rejected(self):
        for amount in (1.5, D("1.001"), D("NaN"), D("Infinity"), D("-Infinity"),
                       D("1000000000000000000"), D("-1000000000000000000")):
            for direction in ("incoming", "outgoing"):
                with self.subTest(amount=amount, direction=direction), self.assertRaises(ValueError):
                    event = incoming() if direction == "incoming" else outgoing()
                    event["amount"] = amount
                    self.build([event], {} if direction == "incoming" else {101: D("20")})

    def test_invalid_channel_money_is_rejected(self):
        for amount in (100.0, D("100.001"), D("NaN"), D("Infinity")):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.build([incoming(channels=[("cash", "Cash", amount)])])

    def test_invalid_liquidity_money_is_rejected(self):
        for amount in (20.0, D("20.001"), D("NaN"), D("Infinity"), D("0"), D("-20")):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.build([outgoing()], {101: amount})

    def test_invalid_event_identity_is_rejected(self):
        for field, value in (("source_model", ""), ("source_id", 0),
                             ("source_id", -1), ("line_id", 0), ("line_id", -1)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.build([incoming(**{field: value})])

    def test_invalid_payment_line_identity_is_rejected(self):
        for payment_line_id in (0, -1, None, True, "101"):
            with self.subTest(payment_line_id=payment_line_id), self.assertRaises(ValueError):
                self.build([outgoing(payment_line_id=payment_line_id)], {101: D("20")})

    def test_liquidity_keys_must_be_positive_integer_identifiers(self):
        for key in (True, "101", 101.0, 0, -1):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.build([outgoing()], {key: D("20")})

    def test_unknown_direction_is_rejected(self):
        with self.assertRaises(ValueError):
            self.build([incoming(direction="transfer")])

    def test_inputs_are_not_mutated(self):
        events = [incoming(channels=[("cash", "Cash", D("40")), ("card", "Card", D("60"))]),
                  outgoing(1, 101, "12"), outgoing(2, 101, "8")]
        liquidity = {101: D("20")}
        before_events, before_liquidity = copy.deepcopy(events), copy.deepcopy(liquidity)
        self.build(events, liquidity)
        self.assertEqual(events, before_events)
        self.assertEqual(liquidity, before_liquidity)


if __name__ == "__main__":
    unittest.main()

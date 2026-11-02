"""
Unit tests for the customer analytics pipeline.

By default the tests run against the refactored script:
    python -m unittest TEST_CASES -v

To show the bugs in the legacy script, run the same tests against it:
    TARGET=process_data python -m unittest TEST_CASES -v

The "bug" tests fail on the legacy process_data.py and pass on
process_data_final.py. The "regression" tests pass on both, proving the
refactor didn't change correct behaviour.
"""

import csv
import importlib
import json
import logging
import os
import shutil
import tempfile
import unittest
from unittest import mock

TARGET = os.environ.get("TARGET", "process_data_final")
pd = importlib.import_module(TARGET)
logging.disable(logging.CRITICAL)  # keep test output readable

CUSTOMERS = (
    "customer_id,name,email,join_date\n"
    "C001,John Smith,john.smith@email.com,2023-01-15\n"
    "C002,Jane Doe,jane.doe@email.com,2023-02-20\n"
    "C003,Bob Johnson,bob.johnson@email.com,2023-03-10\n"
)

TRANSACTIONS = (
    "transaction_id,customer_id,amount,date,category\n"
    "T001,C001,150.50,2024-01-10,electronics\n"
    "T002,C002,75.25,2024-01-11,clothing\n"
    "T003,C001,200.00,2024-01-12,electronics\n"
    "T004,C003,45.75,2024-01-13,food\n"
)


class PipelineTestCase(unittest.TestCase):
    """Creates a temporary working directory with CSV fixtures."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmp)
        self.write("customers.csv", CUSTOMERS)
        self.write("transactions.csv", TRANSACTIONS)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp)

    def write(self, name, content):
        with open(os.path.join(self.tmp, name), "w", newline="") as f:
            f.write(content)

    def loaded(self, transactions=None):
        if transactions is not None:
            self.write("transactions.csv", transactions)
        p = pd.DataProcessor("customers.csv")
        self.assertTrue(p.load_data())
        return p


class TestBugs(PipelineTestCase):
    """Each test reproduces a defect in the legacy script."""

    def test_export_csv_with_non_uniform_records(self):
        """Bug from error.log: the export inferred columns from the first record,
        so any record with a different shape crashed the export."""
        p = self.loaded()
        self.assertTrue(p.process_transactions("transactions.csv"))
        p.customers["C002"]["loyalty_tier"] = "gold"  # extra field on one record
        self.assertTrue(p.export_customer_data("out.csv", "csv"))
        with open("out.csv", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["customer_id"], "C001")

    def test_export_csv_with_no_customers_still_writes_header(self):
        """An empty export should be a valid CSV with a header, not an empty file."""
        p = pd.DataProcessor("customers.csv")
        self.assertTrue(p.export_customer_data("out.csv", "csv"))
        with open("out.csv", newline="") as f:
            header = next(csv.reader(f), None)
        self.assertIsNotNone(header)
        self.assertIn("customer_id", header)

    def test_pipeline_does_not_report_success_after_a_failed_step(self):
        """error.log shows 'completed successfully' straight after an export
        error. main() must report failure when any step fails."""
        with mock.patch.object(pd.DataProcessor, "export_customer_data", return_value=False):
            with self.assertLogs(pd.logger.name, level="INFO") as logs:
                logging.disable(logging.NOTSET)
                try:
                    result = pd.main()
                finally:
                    logging.disable(logging.CRITICAL)
        self.assertEqual(result, 1)
        self.assertFalse(any("completed successfully" in m for m in logs.output))

    def test_one_malformed_transaction_does_not_abort_the_run(self):
        """Intermittent nightly failure: one bad amount stopped the whole batch."""
        bad = TRANSACTIONS + "T005,C002,,2024-01-14,clothing\nT006,C003,abc,2024-01-15,food\n"
        p = self.loaded(bad)
        self.assertTrue(p.process_transactions("transactions.csv"))
        self.assertEqual(len(p.transactions), 4)
        self.assertEqual(p.customers["C001"]["total_spent"], 350.50)

    def test_whitespace_does_not_split_categories(self):
        """The real transactions.csv ends with 'books ' (trailing space), which
        the legacy script counted as a separate category from 'books'."""
        data = TRANSACTIONS + "T005,C002,10.00,2024-01-14,books\nT006,C003,5.00,2024-01-15,books \n"
        p = self.loaded(data)
        p.process_transactions("transactions.csv")
        breakdown = p.calculate_customer_metrics()["category_breakdown"]
        self.assertEqual(breakdown.get("books"), 2)
        self.assertNotIn("books ", breakdown)

    def test_money_totals_do_not_drift(self):
        """Float addition turned 0.10 + 0.20 into 0.30000000000000004."""
        data = (
            "transaction_id,customer_id,amount,date,category\n"
            "T001,C001,0.10,2024-01-10,food\n"
            "T002,C001,0.20,2024-01-11,food\n"
        )
        p = self.loaded(data)
        p.process_transactions("transactions.csv")
        self.assertEqual(p.customers["C001"]["total_spent"], 0.30)
        self.assertEqual(p.calculate_customer_metrics()["total_revenue"], 0.30)


class TestRegression(PipelineTestCase):
    """Correct behaviour that must survive the refactor."""

    def test_totals_and_counts_per_customer(self):
        p = self.loaded()
        p.process_transactions("transactions.csv")
        self.assertEqual(p.customers["C001"]["total_spent"], 350.50)
        self.assertEqual(p.customers["C001"]["transaction_count"], 2)
        self.assertEqual(p.customers["C003"]["transaction_count"], 1)

    def test_metrics_totals_and_top_customer(self):
        p = self.loaded()
        p.process_transactions("transactions.csv")
        m = p.calculate_customer_metrics()
        self.assertEqual(m["total_customers"], 3)
        self.assertEqual(m["total_transactions"], 4)
        self.assertAlmostEqual(m["total_revenue"], 471.50)
        self.assertAlmostEqual(m["average_transaction_value"], 117.875, places=2)
        top = m["top_customers"][0]
        top_id = top[0] if isinstance(top, (tuple, list)) else top["customer_id"]
        self.assertEqual(top_id, "C001")

    def test_unknown_customer_is_ignored_in_totals(self):
        data = TRANSACTIONS + "T005,C999,500.00,2024-01-14,food\n"
        p = self.loaded(data)
        self.assertTrue(p.process_transactions("transactions.csv"))
        self.assertNotIn("C999", p.customers)
        self.assertEqual(p.customers["C001"]["total_spent"], 350.50)

    def test_find_matches_is_case_insensitive(self):
        p = self.loaded()
        ids = [m["customer_id"] for m in p.find_matches("JANE")]
        self.assertEqual(ids, ["C002"])
        self.assertEqual(len(p.find_matches("email.com", field="email")), 3)
        self.assertEqual(p.find_matches("anything", field="no_such_field"), [])

    def test_missing_files_return_false(self):
        self.assertFalse(pd.DataProcessor("nope.csv").load_data())
        p = self.loaded()
        self.assertFalse(p.process_transactions("nope.csv"))

    def test_reports_and_json_export_are_valid_json(self):
        p = self.loaded()
        p.process_transactions("transactions.csv")
        for kind in ("customer_summary", "metrics", "transactions"):
            self.assertTrue(p.generate_report(kind, f"{kind}.json"))
            with open(f"{kind}.json") as f:
                self.assertIn("generated_at", json.load(f))
        self.assertTrue(p.export_customer_data("out.json", "json"))
        self.assertFalse(p.generate_report("unknown", "x.json"))
        self.assertFalse(p.export_customer_data("x.xml", "xml"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

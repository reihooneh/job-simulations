#!/usr/bin/env python3
"""
Customer analytics data processing pipeline (refactored).

Reads customers and transactions from CSV files, aggregates spend per
customer, and writes JSON reports and CSV/JSON exports.

Fixes over the legacy process_data.py:
  1. Export no longer infers CSV columns from whichever customer happens to be
     first. Columns are a fixed schema, so mixed or partial records can't crash
     the export, and an empty dataset still produces a valid header.
  2. One malformed transaction (missing column, blank or non-numeric amount)
     no longer aborts the whole nightly run. Bad rows are skipped, counted and
     logged with their line number.
  3. The pipeline no longer reports "completed successfully" after a step has
     failed. Every step's result is checked and main() returns an exit code.
  4. All CSV values are whitespace-trimmed, so "books " and "books" are the
     same category and dates/emails are clean.
  5. Money is accumulated as integer cents, so totals don't drift
     (0.10 + 0.20 is exactly 0.30, not 0.30000000000000004).
  6. Performance: single-pass aggregation with O(1) dictionary lookups and a
     Counter for categories (no second pass over transactions), a cached
     lowercase index for searches, and heapq.nlargest for the top 10
     customers (O(n log k) instead of sorting every customer).
"""

from __future__ import annotations

import csv
import heapq
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

CUSTOMER_COLUMNS = ("customer_id", "name", "email", "join_date")
TRANSACTION_COLUMNS = ("transaction_id", "customer_id", "amount", "date", "category")
EXPORT_FIELDS = (
    "customer_id",
    "name",
    "email",
    "join_date",
    "total_spent",
    "transaction_count",
)
CENT = Decimal("0.01")


def _clean(row: Dict[str, Optional[str]]) -> Dict[str, str]:
    """Strip whitespace from keys and values. Missing values become ''."""
    return {(k or "").strip(): (v or "").strip() for k, v in row.items()}


def _money(value: Decimal) -> float:
    """Round a Decimal to cents and return a JSON-friendly float."""
    return float(value.quantize(CENT, rounding=ROUND_HALF_UP))


def _missing_columns(fieldnames: Optional[List[str]], required: tuple) -> List[str]:
    present = {(f or "").strip() for f in (fieldnames or [])}
    return [c for c in required if c not in present]


class DataProcessor:
    """Processes customer transaction data and generates analytics reports."""

    def __init__(self, input_file: str):
        self.input_file = input_file
        self.customers: Dict[str, Dict[str, Any]] = {}
        self.transactions: List[Dict[str, Any]] = []
        self.skipped_rows: List[Dict[str, Any]] = []
        self._totals: Dict[str, int] = {}  # integer cents
        self._category_counts: Counter = Counter()
        self._search_index: Dict[str, List[tuple]] = {}

    # ------------------------------------------------------------------ load
    def load_data(self) -> bool:
        """Load customers. Returns False if the file is missing or unusable."""
        try:
            with open(self.input_file, "r", newline="", encoding="utf-8") as file:
                reader = csv.DictReader(file)
                missing = _missing_columns(reader.fieldnames, CUSTOMER_COLUMNS)
                if missing:
                    logger.error(f"{self.input_file} is missing columns: {missing}")
                    return False

                for line_no, raw in enumerate(reader, start=2):
                    row = _clean(raw)
                    customer_id = row.get("customer_id", "")
                    if not customer_id:
                        self._skip("customer", line_no, "blank customer_id", raw)
                        continue
                    if customer_id in self.customers:
                        logger.warning(
                            f"Duplicate customer_id {customer_id} on line {line_no}; "
                            "keeping the first record"
                        )
                        continue
                    self.customers[customer_id] = {
                        "name": row.get("name", ""),
                        "email": row.get("email", ""),
                        "join_date": row.get("join_date", ""),
                        "total_spent": 0.0,
                        "transaction_count": 0,
                    }
                    self._totals[customer_id] = 0

            self._search_index.clear()
            logger.info(f"Loaded {len(self.customers)} customers")
            return True
        except FileNotFoundError:
            logger.error(f"Input file {self.input_file} not found")
            return False
        except (OSError, csv.Error) as e:
            logger.error(f"Error loading data: {e}")
            return False

    # ----------------------------------------------------------- transactions
    def process_transactions(self, transaction_file: str) -> bool:
        """Aggregate transactions in one pass. Malformed rows are skipped."""
        try:
            with open(transaction_file, "r", newline="", encoding="utf-8") as file:
                reader = csv.reader(file)
                header = [h.strip() for h in next(reader, [])]
                missing = _missing_columns(header, TRANSACTION_COLUMNS)
                if missing:
                    logger.error(f"{transaction_file} is missing columns: {missing}")
                    return False

                # Column positions are resolved once, then each row is a plain
                # list index lookup (cheaper than building a dict per row).
                i_tid, i_cid, i_amt, i_date, i_cat = (
                    header.index(c) for c in TRANSACTION_COLUMNS
                )
                width = max(i_tid, i_cid, i_amt, i_date, i_cat) + 1
                customers = self.customers
                totals = self._totals
                categories = self._category_counts
                append = self.transactions.append

                for line_no, row in enumerate(reader, start=2):
                    if not row:
                        continue  # blank line
                    if len(row) < width:
                        self._skip("transaction", line_no, "missing columns", row)
                        continue
                    try:
                        cents = round(float(row[i_amt]) * 100)  # integer cents
                    except (ValueError, OverflowError):
                        self._skip("transaction", line_no, "invalid amount", row)
                        continue

                    customer_id = row[i_cid].strip()
                    category = row[i_cat].strip()
                    append(
                        {
                            "transaction_id": row[i_tid].strip(),
                            "customer_id": customer_id,
                            "amount": cents / 100,
                            "date": row[i_date].strip(),
                            "category": category,
                        }
                    )
                    categories[category] += 1

                    customer = customers.get(customer_id)  # O(1) dictionary lookup
                    if customer is None:
                        logger.warning(
                            f"Transaction {row[i_tid].strip()} on line {line_no} "
                            f"is for unknown customer {customer_id}"
                        )
                        continue
                    totals[customer_id] += cents
                    customer["transaction_count"] += 1

            for customer_id, cents in self._totals.items():
                self.customers[customer_id]["total_spent"] = cents / 100

            logger.info(
                f"Processed {len(self.transactions)} transactions "
                f"({len(self.skipped_rows)} rows skipped)"
            )
            return True
        except FileNotFoundError:
            logger.error(f"Transaction file {transaction_file} not found")
            return False
        except (OSError, csv.Error) as e:
            logger.error(f"Error processing transactions: {e}")
            return False

    def _skip(self, kind: str, line_no: int, reason: str, raw: Any) -> None:
        self.skipped_rows.append({"type": kind, "line": line_no, "reason": reason})
        logger.warning(f"Skipping {kind} on line {line_no}: {reason} ({raw})")

    # ---------------------------------------------------------------- metrics
    def calculate_customer_metrics(self) -> Dict[str, Any]:
        """Totals, average transaction value, top 10 customers, categories."""
        if not self.customers:
            logger.error("No customer data available")
            return {}

        total_cents = sum(self._totals.values())
        counted = sum(c["transaction_count"] for c in self.customers.values())
        top = heapq.nlargest(
            10, self.customers.items(), key=lambda item: item[1]["total_spent"]
        )

        return {
            "total_customers": len(self.customers),
            "total_transactions": len(self.transactions),
            "total_revenue": total_cents / 100,
            "average_transaction_value": (
                _money(Decimal(total_cents) / counted / 100) if counted else 0.0
            ),
            "top_customers": [
                {"customer_id": cid, **data} for cid, data in top
            ],
            "category_breakdown": dict(self._category_counts.most_common()),
            "skipped_rows": len(self.skipped_rows),
        }

    # ----------------------------------------------------------------- search
    def find_matches(self, search_term: str, field: str = "name") -> List[Dict[str, Any]]:
        """Case-insensitive substring search, using a cached lowercase index."""
        if field not in self._search_index:
            self._search_index[field] = [
                (str(data[field]).lower(), cid)
                for cid, data in self.customers.items()
                if field in data
            ]
        term = search_term.lower()
        return [
            {"customer_id": cid, **self.customers[cid]}
            for value, cid in self._search_index[field]
            if term in value
        ]

    # ---------------------------------------------------------------- reports
    def generate_report(self, report_type: str, output_file: str) -> bool:
        builders = {
            "customer_summary": lambda: {
                "customers": [
                    {"customer_id": cid, **data} for cid, data in self.customers.items()
                ]
            },
            "metrics": lambda: {"metrics": self.calculate_customer_metrics()},
            "transactions": lambda: {"transactions": self.transactions},
        }
        if report_type not in builders:
            logger.error(f"Unknown report type: {report_type}")
            return False
        try:
            report = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                **builders[report_type](),
            }
            with open(output_file, "w", encoding="utf-8") as file:
                json.dump(report, file, indent=2, ensure_ascii=False)
            logger.info(f"Generated {report_type} report: {output_file}")
            return True
        except (OSError, TypeError, ValueError) as e:
            logger.error(f"Error generating {report_type} report: {e}")
            return False

    # ----------------------------------------------------------------- export
    def export_customer_data(self, output_file: str, file_format: str = "csv") -> bool:
        """Export customers as CSV (fixed schema) or JSON."""
        try:
            if file_format == "csv":
                with open(output_file, "w", newline="", encoding="utf-8") as file:
                    writer = csv.DictWriter(
                        file, fieldnames=EXPORT_FIELDS, extrasaction="ignore"
                    )
                    writer.writeheader()
                    for customer_id, data in self.customers.items():
                        writer.writerow({"customer_id": customer_id, **data})
            elif file_format == "json":
                with open(output_file, "w", encoding="utf-8") as file:
                    json.dump(self.customers, file, indent=2, ensure_ascii=False)
            else:
                logger.error(f"Unsupported format: {file_format}")
                return False

            logger.info(f"Exported customer data to {output_file}")
            return True
        except (OSError, TypeError, ValueError) as e:
            logger.error(f"Error exporting data to {output_file}: {e}")
            return False


def main(
    customers_file: str = "customers.csv",
    transactions_file: str = "transactions.csv",
) -> int:
    """Run the pipeline. Returns 0 on success and 1 if any step failed."""
    processor = DataProcessor(customers_file)

    if not processor.load_data():
        logger.error("Failed to load customer data")
        return 1
    if not processor.process_transactions(transactions_file):
        logger.error("Failed to process transactions")
        return 1

    steps = [
        processor.generate_report("customer_summary", "customer_summary.json"),
        processor.generate_report("metrics", "metrics.json"),
        processor.generate_report("transactions", "transactions.json"),
        processor.export_customer_data("customers_export.csv", "csv"),
        processor.export_customer_data("customers_export.json", "json"),
    ]
    failed = steps.count(False)
    if failed:
        logger.error(f"Data processing finished with {failed} failed step(s)")
        return 1

    logger.info("Data processing completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))

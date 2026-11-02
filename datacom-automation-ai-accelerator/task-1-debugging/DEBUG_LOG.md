# DEBUG_LOG: process_data.py investigation

**Role:** Graduate Developer, Datacom · **AI co-pilot:** Claude (Anthropic)
**Ticket:** The nightly `process_data.py` job fails intermittently and runs slower than its SLA allows. The original author has moved teams.
**Outcome:** I reproduced 6 defects with failing unit tests, then fixed all of them in `process_data_final.py`. All 12 tests pass, the 6 regression tests pass on both versions, and metrics and search are much faster.

---

## Step 1: Understand the codebase

**Prompt**

> This is a legacy Python script. Please provide a high-level summary of what it's supposed to do. Then, break down your explanation function by function, detailing the purpose of each, its expected inputs and outputs, and any side effects. Finally, identify any potential areas of concern or parts of the code that seem overly complex or inefficient.

**AI response (key parts)**

> **Summary:** a nightly ETL job. It loads customers from `customers.csv`, streams `transactions.csv` to total spend per customer, then writes three JSON reports (`customer_summary`, `metrics`, `transactions`) and exports customers as CSV and JSON.
>
> | Function | Purpose | In → Out | Side effects |
> | --- | --- | --- | --- |
> | `load_data` | Build `self.customers` keyed by `customer_id` | path → `bool` | Mutates state, logs |
> | `process_transactions` | Append transactions and add amounts to customer totals | path → `bool` | Mutates state, logs |
> | `calculate_customer_metrics` | Totals, average, top 10 and category counts | none → `dict` | None |
> | `find_matches` | Case-insensitive substring search on one field | term, field → `list` | None |
> | `generate_report` | Serialise one report type to JSON | type, path → `bool` | Writes a file |
> | `export_customer_data` | Export customers as CSV or JSON | path, format → `bool` | Writes a file |
> | `main` | Run the pipeline end to end | none → `None` | Writes 5 files |
>
> **Concerns:**
> 1. `main()` **ignores the return values** of every report and export, then always logs "completed successfully".
> 2. `export_customer_data` **infers the CSV columns from the first customer record** (`next(iter(...)).keys()`). That's fragile.
> 3. A single bad row in `process_transactions` (for example a blank amount) raises inside the loop and **aborts the whole batch**, because the `try` wraps the entire file.
> 4. No input cleaning: values are used exactly as read, including stray whitespace.
> 5. Money is summed as `float`, so totals drift.
> 6. Efficiency: `float(row["amount"])` is parsed twice per row. `calculate_customer_metrics` makes a second full pass over every transaction for categories and sorts every customer to get the top 10. `find_matches` lowercases every value on every call.
> 7. Smaller issues: `format` shadows a built-in; `Optional` and `self.reports` are unused; timestamps have no timezone.

**My notes:** I ran the original script on the provided data before trusting the summary. It "succeeded", but `metrics.json` showed **`"books": 1` and `"books ": 1`** as two separate categories. The last line of `transactions.csv` has a trailing space. That's concern #4 confirmed with real client data, and it's a silent wrong answer rather than a crash.

---

## Step 2: Diagnose the specific bug

**Prompt**

> Given the following function from the script and the associated error log, what is the most likely root cause of the failure? Please explain your reasoning step-by-step, referencing specific lines of code and the error message.
>
> *(Pasted `export_customer_data`, `main` and the full `error.log`.)*

```text
... INFO  - Exported customer data to customers_export.csv
... ERROR - Error exporting data: 'dict' object has no attribute 'keys'
... ERROR - Data processing completed successfully
```

**AI response (key parts)**

> 1. The failure is in **`export_customer_data`**, on the second call (`format="json"`), right after the CSV export succeeded. Its broad `except Exception` turns any error into the log line `Error exporting data: ...` and returns `False`.
> 2. The only `.keys()` call is `next(iter(self.customers.values())).keys()`, used to **derive the CSV schema from whichever record comes first**. Any record that isn't a plain, uniform dict (a different shape, or a different mapping type from another loader) breaks the export. If later records have extra fields, `csv.DictWriter` raises `ValueError: dict contains fields not in fieldnames`.
> 3. The **more serious defect** is visible on the last line: `main()` never checks the `False` returned by the export and **logs "completed successfully" anyway**. That's why the failure looks "intermittent" to the client. The job reports success, and downstream consumers find a missing or partial export later.
> 4. **Caveat:** a built-in `dict` always has `.keys()`, so that exact message can't come from this code with the provided CSVs. It points to the records not being plain dicts at runtime. The robust fix doesn't depend on the record type: use a fixed export schema, and make `main()` honour step results.

**My notes:** I treated the AI's caveat as a hypothesis to test, not a conclusion. I couldn't reproduce the literal message with built-in dicts, which confirms the caveat. But I could reproduce the same class of failure (schema inferred from the first record, then a crash) and the false "success" message. So I wrote tests for the behaviour, not the exact string. I also added the malformed-row and whitespace issues from Step 1, because they explain the "intermittent" part of the ticket: the job only fails on nights when the upstream file contains a bad row.

---

## Step 3: Write tests to replicate the bugs

**Prompt**

> Based on your analysis of the bug, write a Python unit test using the 'unittest' library that is specifically designed to fail in the same way the error log shows. This test should call the problematic function with data that triggers the bug.

Follow-up prompt:

> Also add tests for the malformed amount row, the trailing-space category, float drift, and the false "completed successfully". Keep a separate group of regression tests that must pass on BOTH versions, so I can prove the refactor doesn't change correct behaviour. Let me switch the module under test with an environment variable.

**AI response (summary):** produced `TEST_CASES.py` with 12 tests in two classes:

- `TestBugs` (6 tests) reproduces each defect.
- `TestRegression` (6 tests) covers totals, metrics, unknown customers, search, missing files and JSON validity.

Setting `TARGET=process_data` runs the suite against the legacy file.

**Result against the legacy script** (`TARGET=process_data python -m unittest TEST_CASES`):

```text
FAIL: test_export_csv_with_no_customers_still_writes_header
FAIL: test_export_csv_with_non_uniform_records
FAIL: test_money_totals_do_not_drift
FAIL: test_one_malformed_transaction_does_not_abort_the_run
FAIL: test_pipeline_does_not_report_success_after_a_failed_step
FAIL: test_whitespace_does_not_split_categories
Ran 12 tests ... FAILED (failures=6)
```

All 6 regression tests passed on the legacy code, as they should.

**My notes:** I checked that every bug test fails for the right reason, not because of a typo in the test. For example, the export test fails because `export_customer_data` returns `False` after the `DictWriter` `ValueError`, and the drift test shows `0.30000000000000004 != 0.3`. I also asked the AI to make `top_customers` assertions work with both the old tuple format and the new dict format, so the regression test stays fair to both versions.

---

## Step 4: Refactor and fix

**Prompt**

> Refactor this function to fix the bug we identified. While doing so, also improve its performance. The current implementation uses inefficient nested for-loops; please replace this logic with a more performant method, such as using a dictionary lookup. Keep the public method names and outputs compatible, and don't swallow errors silently.

**AI response (key changes):**

| # | Problem | Fix in `process_data_final.py` |
| --- | --- | --- |
| 1 | CSV schema inferred from the first record | Fixed `EXPORT_FIELDS` with `extrasaction="ignore"`. An empty dataset still writes a header. |
| 2 | One bad row aborts the batch | Validate per row. Bad rows are skipped, logged with line numbers and counted in `skipped_rows`. |
| 3 | False "completed successfully" | `main()` checks every step and returns exit code `0` or `1`, and the script calls `sys.exit(main())`. |
| 4 | Whitespace splits categories and dirties data | All fields are stripped. Header columns are validated up front. |
| 5 | Float drift | Totals are kept as integer cents, so 0.10 + 0.20 is exactly 0.30. |
| 6 | Extra passes and repeated work | Single pass with O(1) dictionary lookups (`customers.get`). A `Counter` builds category counts during that pass. `heapq.nlargest` finds the top 10. Search uses a cached lowercase index. |
| 7 | Hygiene | `format` renamed to `file_format`, UTF-8 everywhere, UTC timestamps, narrower `except` clauses, duplicate customer IDs warned about instead of silently overwritten. |

**I challenged one AI suggestion:** the first version used `Decimal` and built a cleaned dict for every row. It was correct but **slower than the original** on a 500,000-row benchmark (2.90s vs 1.87s). I asked for a faster approach that kept the same correctness. The AI switched to resolving the column positions once from the header and storing integer cents, which brought processing back level with the original while keeping all the new validation.

**Results**

```text
python -m unittest TEST_CASES -v  →  Ran 12 tests ... OK
```

Benchmark: 20,000 customers and 500,000 transactions, same machine:

| Operation | Legacy | Final | Change |
| --- | --- | --- | --- |
| Load + process (now with validation) | 1.47s | 1.45s | Same speed, much safer |
| 200 searches | 0.72s | 0.21s | **~3.4× faster** |
| Metrics | 0.178s | 0.005s | **~35× faster** |

Totals matched exactly between versions (125,144,632.86).

On the client's real files, the category breakdown is now correct: `{"electronics": 3, "clothing": 3, "food": 2, "books": 2}`.

**My notes:** the brief mentioned "nested for-loops". The legacy code doesn't actually nest them, but it does repeated full scans (a second pass for categories, a full sort for the top 10, re-lowercasing on every search), which costs the same kind of time. I fixed what was really there instead of inventing a loop to remove.

---

## Step 5: Reflection

- **Context beats commands.** Prompts that included the code, the full log and a clear goal produced accurate diagnoses. Vague prompts would have produced a generic fix.
- **Treat AI output as a hypothesis.** The AI flagged that the literal log message was inconsistent with built-in dicts. Checking that stopped me "fixing" the wrong thing and pointed me at the real defect: false success reporting.
- **Tests first, then refactor.** The failing suite made it obvious when each bug was fixed, and the regression group proved I hadn't changed correct behaviour.
- **Verify performance claims.** The AI's first refactor was slower. Measuring it caught that before it reached the client.
- **Next steps I'd propose:** alert on a non-zero exit code in the scheduler, write skipped rows to a quarantine file for the data team, and add these tests to CI.

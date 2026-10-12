# Multi-Branch Inventory & Stock Management System

## Requirements
- Python 3.9 or newer
- Standard library only; no third-party packages required

## Run
```bash
python main.py
python -m unittest discover -v
```

## Modules
- `main.py`: loads input, resumes durable state, processes only new transaction IDs, generates reports, saves state.
- `models.py`: optional dataclasses compatible with Python 3.10+ and older type annotation style.
- `utils.py`: validated JSON loading/saving and general-purpose helpers.
- `validation.py`: catalog, branch, transaction, batch, stock, and return validation.
- `inventory.py`: shared batch operations, FEFO deduction, transfers' lot support, and consistency checks.
- `processing.py`: applies transactions once and stores transaction-time financial snapshots.
- `transfering.py`: atomic branch transfers and complete physical-stock reconciliation.
- `reports.py`: read-only reports; dashboard generation never reprocesses transactions.
- `test_cases.py`: unittest coverage for transaction safety and reporting.

## Data and behavior
- `input_data.json` provides the initial catalog, branch inventory, opening batches, physical counts, and transaction feed.
- `state.json` is created on the first successful run and stores current inventory, batch quantities, batch validation notes, and the transaction ledger.
- `results.json` stores the transaction ledger.
- Re-running `main.py` does not replay transaction IDs already in the ledger. To intentionally start over for a new demo, back up and remove `state.json` and `results.json`.
- Batch quantities are kept consistent with aggregate stock. If initial stock has no lot records, the system creates opening lots with unknown expiry (`expiry_days: null`) rather than inventing expiry dates.
- Opening batches with duplicate IDs, invalid fields, or quantities exceeding aggregate branch stock are rejected and listed in the report.
- Sales use FEFO (first-expiring, first-out) and exclude batches known to be expired. Lots with unknown expiry can be sold after dated eligible lots.
- Customer returns require `original_sale_id`, restore quantities to the original sale's batch allocations, and reverse the original transaction-time revenue, cost, and gross profit.
- Sales store transaction-time unit price and cost so later catalog changes do not rewrite historical sales.
- Reports are read-only. They calculate from current inventory and the existing ledger without mutating stock.
- Reconciliation includes system products omitted from physical counts as `NOT_COUNTED`; unknown physical SKUs are flagged.
- The JSON state file is suitable for a single-user learning project. It is not a substitute for database transactions, file locking, authentication, authorization, or concurrent-write handling in a multi-user production application.

## Important workflow note
Transactions in `input_data.json` are treated as an incoming feed. To add transactions, append records with new unique IDs. Existing IDs are skipped on subsequent runs. Customer return example:
```json
{
  "id": "T005",
  "type": "customer_return",
  "branch": "B001",
  "product": "P001",
  "quantity": 2,
  "original_sale_id": "T001"
}
```

# Multi-Branch Inventory & Stock Management System

## How to run
```
python main.py          # runs input_data.json, prints the dashboard + detailed reports, saves results.json
python test_cases.py    # runs all the test cases
```

## Files
- `main.py` - loads the JSON file, runs the dashboard, prints the reports, saves `results.json`
- `models.py` - dataclasses (`Product`, `Branch`, `Transaction`)
- `utils.py` - `load_data`, `save_data`, `classify_batch`, `combine_inventories(*inventories)`
- `validation.py` - all validation (transactions, stock, returns, batches)
- `processing.py` - applies valid transactions to stock, builds the result of each transaction
- `transfering.py` - `transfer_stock` and `reconcile_inventory`
- `reports.py` - expiry, reorder, stock value, sales report, dashboard
- `test_cases.py` - tests, `edge_cases_input.json` - deliberately bad data

## Approach
Data is kept in plain dictionaries. Every transaction goes through `validate_transaction` first.
Only if it passes, the stock is changed (`process_sale`, `process_purchase`, `transfer_stock`, ...).
The result is a dictionary with `SUCCESS` or `REJECTED` and a reason, and it is added to a list.

## Inventory consistency logic
1. Validate first: type, missing fields, duplicate ID, quantity, product, branch, stock.
2. Change stock only after validation passes, in one small function.
3. A sale, supplier return or transfer that is bigger than the available stock fails validation, so
   stock can never go negative. A REJECTED transaction never touches the inventory.
4. A customer return is checked against the earlier results: successful sales minus successful returns
   for the same branch and product = remaining returnable quantity.
5. The list of results processed so far is also used to find duplicate transaction IDs.

## Python concepts used
- Lists/dicts: inventory, results, reports. Sets: duplicate transaction IDs (`used_ids`) and duplicate batches (`seen_batches`).
- Tuples: functions return `(valid, reason)`.
- Comprehensions: missing fields, used IDs, company totals.
- Lambda: `max`/`min` keys in `generate_sales_report`.
- `*args`: `combine_inventories(*inventories)`. `**kwargs`: `make_result(..., **details)`.
- LEGB: comment inside `generate_sales_report` (local `highest`, enclosing `units_sold`, built-in `max`/`sum`).

## Assumptions
- Customer returns are matched by branch + product (transactions have no sale id).
- Revenue counts sales only; returns change stock but not revenue.
- Reconciliation difference = system - physical (shortage is positive).
- Expiry days of 0 = Expired; negative expiry days are rejected as invalid.

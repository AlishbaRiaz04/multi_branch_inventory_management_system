"""Application entry point with durable JSON state and transaction-ID de-duplication."""
import os
from copy import deepcopy
from utils import load_data, save_data
from inventory import prepare_batches, check_batch_aggregate_consistency
from processing import process_all_transactions
from reports import generate_inventory_dashboard, print_detailed_reports

INPUT_FILE = "input_data.json"
STATE_FILE = "state.json"
RESULTS_FILE = "results.json"

def main():
    source, error = load_data(INPUT_FILE)
    if error:
        print(error)
        return

    products = source["products"]
    physical_stock = source.get("physical_stock", {})
    incoming_transactions = source.get("transactions", [])

    if os.path.exists(STATE_FILE):
        state, error = load_data(STATE_FILE)
        if error:
            print(f"Persistent state could not be loaded: {error}")
            print("Do not delete or overwrite the state file until it has been inspected.")
            return
        branches = state["branches"]
        batches = state.get("batches", [])
        ledger = state.get("transactions", [])
        batch_rejections = state.get("batch_rejections", [])
    else:
        branches = deepcopy(source["branches"])
        batches, batch_rejections = prepare_batches(
            source.get("batches", []), products, branches
        )
        ledger = []

    # Only process new IDs. Re-running main.py must not replay previously applied transactions.
    existing_ids = {row.get("transaction_id") for row in ledger}
    new_transactions = [
        tx for tx in incoming_transactions
        if isinstance(tx, dict) and tx.get("id") not in existing_ids
    ]
    # Preserve malformed rows so they receive an explicit rejection result.
    new_transactions.extend(tx for tx in incoming_transactions if not isinstance(tx, dict))

    all_results = process_all_transactions(
        new_transactions, products, branches, batches, prior_results=ledger
    )

    consistency_errors = check_batch_aggregate_consistency(batches, branches)
    if consistency_errors:
        print("INTERNAL INVENTORY CONSISTENCY ERROR:")
        for issue in consistency_errors:
            print(" -", issue)
        print("State was not saved. Inspect the issue before continuing.")
        return

    report = generate_inventory_dashboard(
        products, branches, all_results, physical_stock, batches, batch_rejections
    )
    print_detailed_reports(report, products, branches)

    # Persist only one ledger record per transaction ID. A duplicate-ID attempt is
    # visible in this run's report but cannot create a second ledger entry.
    unique_results = []
    persisted_ids = set()
    for row in all_results:
        txid = row.get("transaction_id")
        if txid is not None and txid in persisted_ids:
            continue
        if txid is not None:
            persisted_ids.add(txid)
        unique_results.append(row)

    state_to_save = {
        "products": products,
        "branches": branches,
        "batches": batches,
        "transactions": unique_results,
        "batch_rejections": batch_rejections,
    }
    saved, save_error = save_data(STATE_FILE, state_to_save)
    if not saved:
        print(save_error)
        return
    saved, save_error = save_data(RESULTS_FILE, unique_results)
    if not saved:
        print(save_error)
        return
    print(f"Saved persistent inventory state to {STATE_FILE} and transaction ledger to {RESULTS_FILE}.")

if __name__ == "__main__":
    main()

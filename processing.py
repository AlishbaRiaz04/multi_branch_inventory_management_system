"""Transaction processing with validated inputs, inventory snapshots, and auditable results."""
from copy import deepcopy
from inventory import prepare_batches, deduct_from_batches, add_batch, restore_allocations
from transfering import transfer_stock
from validation import validate_transaction

def make_result(transaction_id, status, reason, **details):
    result = {"transaction_id": transaction_id, "transaction_status": status, "reason": reason}
    result.update(details)
    return result

def _sale_return_allocations(original_sale, transactions, quantity):
    already_returned = {}
    for result in transactions:
        if result.get("transaction_status") == "SUCCESS" and result.get("transaction_type") == "customer_return" and result.get("original_sale_id") == original_sale.get("transaction_id"):
            for allocation in result.get("batch_allocations", []):
                already_returned[allocation["batch"]] = already_returned.get(allocation["batch"], 0) + allocation["quantity"]
    remaining_by_batch = {}
    for allocation in original_sale.get("batch_allocations", []):
        remaining_by_batch[allocation["batch"]] = max(
            0, allocation["quantity"] - already_returned.get(allocation["batch"], 0)
        )
    allocations, remaining = [], quantity
    for batch_id, available in remaining_by_batch.items():
        amount = min(available, remaining)
        if amount:
            allocations.append({"batch": batch_id, "quantity": amount})
            remaining -= amount
        if remaining == 0:
            break
    if remaining:
        return False, f"Could not trace {remaining} returned units to original sale batches"
    return True, allocations

def process_purchase(branches, branch_id, product_id, quantity, batches=None, transaction=None):
    inventory = branches[branch_id]["inventory"]
    tx = transaction or {}
    batch_id = tx.get("batch") or f"PURCHASE-{tx.get('id', 'UNKNOWN')}"
    expiry_days = tx.get("expiry_days")
    ok, detail = add_batch(batches, branch_id, product_id, quantity, batch_id, expiry_days)
    if not ok:
        return False, detail
    inventory[product_id] = inventory.get(product_id, 0) + quantity
    return True, None

def process_sale(branches, branch_id, product_id, quantity, batches):
    ok, allocations = deduct_from_batches(batches, branch_id, product_id, quantity)
    if not ok:
        return False, allocations
    branches[branch_id]["inventory"][product_id] -= quantity
    return True, allocations

def process_supplier_return(branches, branch_id, product_id, quantity, batches):
    # Supplier returns may include expired stock, unlike sales.
    ok, allocations = deduct_from_batches(batches, branch_id, product_id, quantity, allow_expired=True)
    if not ok:
        return False, allocations
    branches[branch_id]["inventory"][product_id] -= quantity
    return True, allocations

def process_customer_return(branches, branch_id, product_id, quantity, batches, original_sale, transactions):
    ok, allocations = _sale_return_allocations(original_sale, transactions, quantity)
    if not ok:
        return False, allocations
    ok, reason = restore_allocations(batches, branch_id, product_id, allocations)
    if not ok:
        return False, reason
    branches[branch_id]["inventory"][product_id] += quantity
    return True, allocations

def process_transaction(transaction, transactions, products, branches, batches):
    valid, reason = validate_transaction(transaction, transactions, products, branches, batches)
    data = transaction if isinstance(transaction, dict) else {}
    tx_type = data.get("type")
    txid = data.get("id")
    product_id = data.get("product")
    quantity = data.get("quantity")
    branch_id = data.get("branch")
    to_branch_id = data.get("to_branch") if tx_type == "transfer" else None
    if tx_type == "transfer":
        branch_id = data.get("from_branch")

    details = {
        "product_id": product_id,
        "branch_id": branch_id,
        "to_branch_id": to_branch_id,
        "quantity": quantity if isinstance(quantity, int) and not isinstance(quantity, bool) else 0,
        "transaction_type": tx_type,
        "original_sale_id": data.get("original_sale_id"),
        "batch_allocations": [],
    }
    if not valid:
        return make_result(txid, "REJECTED", reason, **details)

    # Snapshot mutable state. If a known runtime/data error occurs, restore both dictionaries.
    branches_before = deepcopy(branches)
    batches_before = deepcopy(batches)
    try:
        unit_price = products[product_id]["price"]
        unit_cost = products[product_id]["cost"]
        allocations = []
        if tx_type == "purchase":
            ok, reason = process_purchase(branches, branch_id, product_id, quantity, batches, data)
            if not ok:
                raise ValueError(reason)
        elif tx_type == "sale":
            ok, allocations_or_reason = process_sale(branches, branch_id, product_id, quantity, batches)
            if not ok:
                raise ValueError(allocations_or_reason)
            allocations = allocations_or_reason
            details.update(unit_price=unit_price, unit_cost=unit_cost,
                           revenue_delta=unit_price * quantity,
                           cost_delta=unit_cost * quantity,
                           gross_profit_delta=(unit_price - unit_cost) * quantity)
        elif tx_type == "supplier_return":
            ok, allocations_or_reason = process_supplier_return(branches, branch_id, product_id, quantity, batches)
            if not ok:
                raise ValueError(allocations_or_reason)
            allocations = allocations_or_reason
        elif tx_type == "customer_return":
            original_sale = next(t for t in transactions if t.get("transaction_id") == data["original_sale_id"])
            ok, allocations_or_reason = process_customer_return(
                branches, branch_id, product_id, quantity, batches, original_sale, transactions
            )
            if not ok:
                raise ValueError(allocations_or_reason)
            allocations = allocations_or_reason
            details.update(unit_price=original_sale["unit_price"], unit_cost=original_sale["unit_cost"],
                           revenue_delta=-original_sale["unit_price"] * quantity,
                           cost_delta=-original_sale["unit_cost"] * quantity,
                           gross_profit_delta=-(original_sale["unit_price"] - original_sale["unit_cost"]) * quantity)
        elif tx_type == "transfer":
            ok, reason = transfer_stock(data, branches, batches, transaction_id=txid)
            if not ok:
                raise ValueError(reason)
        details["batch_allocations"] = allocations
        if tx_type == "sale":
            details["unit_price"] = unit_price
            details["unit_cost"] = unit_cost
        return make_result(txid, "SUCCESS", "Transaction processed successfully", **details)
    except (TypeError, KeyError, ValueError, OverflowError) as exc:
        branches.clear()
        branches.update(branches_before)
        batches[:] = batches_before
        return make_result(txid, "REJECTED", f"Transaction could not be applied: {exc}", **details)

def process_all_transactions(transactions, products, branches, batches=None, prior_results=None):
    if batches is None:
        batches = []
    # Ensure existing aggregate inventory is represented by validated lots.
    prepared, _ = prepare_batches(batches, products, branches)
    batches[:] = prepared
    processed = deepcopy(prior_results or [])
    for transaction in transactions:
        result = process_transaction(transaction, processed, products, branches, batches)
        processed.append(result)
    return processed

def process_sales(transaction, products):
    """Financial impact of a processed sale/return, using transaction-time snapshots."""
    tx_type = transaction.get("transaction_type")
    status = transaction.get("transaction_status")
    revenue = cost = gross_profit = 0
    product_id = transaction.get("product_id")
    branch_id = transaction.get("branch_id")
    quantity = transaction.get("quantity", 0)
    if status == "SUCCESS" and tx_type in ("sale", "customer_return"):
        if "revenue_delta" in transaction:
            revenue = transaction["revenue_delta"]
            cost = transaction["cost_delta"]
            gross_profit = transaction["gross_profit_delta"]
        elif tx_type == "sale":
            # Compatibility for older ledger rows without snapshots.
            price = products[product_id]["price"]
            unit_cost = products[product_id]["cost"]
            revenue, cost = price * quantity, unit_cost * quantity
            gross_profit = revenue - cost
    return {"revenue": revenue, "cost": cost, "gross_profit": gross_profit,
            "product_id": product_id, "branch_id": branch_id, "quantity": quantity}

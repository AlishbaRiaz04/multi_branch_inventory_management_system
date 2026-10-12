"""Safe stock transfer and physical reconciliation operations."""
from copy import deepcopy
from validation import validate_branch, validate_stock_value
from inventory import move_batches

def transfer_stock(transfer, branches, batches=None, transaction_id=None):
    from_branch = transfer.get("from_branch")
    to_branch = transfer.get("to_branch")
    product_id = transfer.get("product")
    quantity = transfer.get("quantity")

    valid, _ = validate_branch(from_branch, branches)
    if not valid:
        return False, f"Invalid source branch: {from_branch}"
    valid, _ = validate_branch(to_branch, branches)
    if not valid:
        return False, f"Invalid destination branch: {to_branch}"
    if from_branch == to_branch:
        return False, "Source and destination are the same branch"
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        return False, "Quantity must be a positive whole number"

    source_inventory = branches[from_branch]["inventory"]
    destination_inventory = branches[to_branch]["inventory"]
    if product_id not in source_inventory:
        return False, f"Product {product_id} not found in source branch {from_branch}"
    source_stock = source_inventory[product_id]
    destination_stock = destination_inventory.get(product_id, 0)
    if not validate_stock_value(source_stock):
        return False, f"Invalid source stock value: {source_stock!r}"
    if not validate_stock_value(destination_stock):
        return False, f"Invalid destination stock value: {destination_stock!r}"
    if quantity > source_stock:
        return False, f"Insufficient stock. Available: {source_stock}, requested: {quantity}"

    if batches is None:
        return False, "Batch records are required for a consistent transfer"

    # Precompute balances, and roll back both stock and lots if lot movement fails.
    branches_before = deepcopy(branches)
    batches_before = deepcopy(batches)
    try:
        ok, reason = move_batches(batches, from_branch, to_branch, product_id, quantity, transaction_id or transfer.get("id", "TRANSFER"))
        if not ok:
            return False, reason
        source_inventory[product_id] = source_stock - quantity
        destination_inventory[product_id] = destination_stock + quantity
    except (TypeError, KeyError, ValueError) as exc:
        branches.clear()
        branches.update(branches_before)
        batches[:] = batches_before
        return False, f"Transfer failed without changing inventory: {exc}"
    return True, None

def reconcile_inventory(physical_stock, branches, products=None):
    """Report every system SKU, including products omitted from the physical count."""
    stats = {}
    for branch_id, branch in branches.items():
        physical = physical_stock.get(branch_id, {})
        stats[branch_id] = {}
        if not isinstance(physical, dict):
            stats[branch_id]["invalid"] = {"product": None, "status": "invalid physical count"}
            physical = {}
        catalog_ids = set(products) if products is not None else set(branch["inventory"])
        all_products = catalog_ids | set(branch["inventory"]) | set(physical)
        for product_id in sorted(all_products):
            if products is not None and product_id not in products:
                stats[branch_id][product_id] = {"product": product_id, "status": "invalid product"}
                continue
            system_stock = branch["inventory"].get(product_id, 0)
            if product_id not in physical:
                stats[branch_id][product_id] = {
                    "product": product_id, "system_stock": system_stock,
                    "physical_stock": None, "difference": None, "status": "NOT_COUNTED"
                }
                continue
            count = physical[product_id]
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                stats[branch_id][product_id] = {"product": product_id, "status": "invalid physical quantity"}
                continue
            difference = system_stock - count
            status = "MATCHED" if difference == 0 else ("SHORTAGE" if difference > 0 else "EXCESS")
            stats[branch_id][product_id] = {
                "product": product_id, "system_stock": system_stock,
                "physical_stock": count, "difference": difference, "status": status
            }
    for branch_id, physical in physical_stock.items():
        if branch_id not in branches:
            stats[branch_id] = {"invalid": {"product": None, "status": "invalid branch"}}
    return stats

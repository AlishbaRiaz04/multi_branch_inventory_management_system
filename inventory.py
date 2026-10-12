"""Inventory lot helpers shared by transaction processing and branch transfers.

Batch quantities are maintained to match aggregate branch inventory. Existing
stock without known expiry data is represented as an opening batch with expiry_days=None.
"""
from copy import deepcopy
from validation import validate_batch

def prepare_batches(batches, products, branches):
    """Validate opening batches, reject duplicate/overstated lots, and represent unbatched stock."""
    accepted, rejected, seen = [], [], set()
    totals = {}
    for raw in batches if isinstance(batches, list) else []:
        valid, reason = validate_batch(raw, seen, products, branches)
        if not valid:
            rejected.append({"batch": raw.get("batch") if isinstance(raw, dict) else None, "reason": reason})
            continue
        seen.add(raw["batch"])
        key = (raw["branch"], raw["product"])
        aggregate = branches[raw["branch"]]["inventory"].get(raw["product"], 0)
        already = totals.get(key, 0)
        if already + raw["quantity"] > aggregate:
            rejected.append({"batch": raw["batch"], "reason": f"Batch total would exceed branch stock ({aggregate})"})
            continue
        record = deepcopy(raw)
        record.setdefault("expiry_days", None)
        accepted.append(record)
        totals[key] = already + record["quantity"]

    for branch_id, branch in branches.items():
        for product_id, aggregate in branch["inventory"].items():
            key = (branch_id, product_id)
            gap = aggregate - totals.get(key, 0)
            if gap > 0:
                batch_id = f"OPENING-{branch_id}-{product_id}"
                suffix = 1
                while batch_id in seen:
                    suffix += 1
                    batch_id = f"OPENING-{branch_id}-{product_id}-{suffix}"
                accepted.append({
                    "batch": batch_id, "product": product_id, "branch": branch_id,
                    "quantity": gap, "expiry_days": None, "opening_stock": True
                })
                seen.add(batch_id)
    return accepted, rejected

def stock_from_batches(batches, branch_id, product_id):
    return sum(b["quantity"] for b in batches if b["branch"] == branch_id and b["product"] == product_id)

def check_batch_aggregate_consistency(batches, branches):
    errors = []
    for branch_id, branch in branches.items():
        product_ids = set(branch["inventory"])
        product_ids.update(b["product"] for b in batches if b.get("branch") == branch_id)
        for product_id in product_ids:
            aggregate = branch["inventory"].get(product_id, 0)
            lot_total = stock_from_batches(batches, branch_id, product_id)
            if aggregate != lot_total:
                errors.append(f"{branch_id}/{product_id}: aggregate={aggregate}, batches={lot_total}")
    return errors

def deduct_from_batches(batches, branch_id, product_id, quantity, allow_expired=False):
    """Deduct FEFO. Returns allocations for audit/return restoration."""
    eligible = [
        b for b in batches
        if b.get("branch") == branch_id and b.get("product") == product_id
        and b.get("quantity", 0) > 0
        and (allow_expired or b.get("expiry_days") is None or b["expiry_days"] > 0)
    ]
    eligible.sort(key=lambda b: (b.get("expiry_days") is None, b.get("expiry_days") if b.get("expiry_days") is not None else float("inf"), b["batch"]))
    available = sum(b["quantity"] for b in eligible)
    if quantity > available:
        return False, f"Insufficient unexpired batch stock. Available: {available}, requested: {quantity}"
    allocations, remaining = [], quantity
    for batch in eligible:
        amount = min(batch["quantity"], remaining)
        if amount:
            allocations.append({"batch": batch["batch"], "quantity": amount})
            batch["quantity"] -= amount
            remaining -= amount
        if remaining == 0:
            break
    return True, allocations

def add_batch(batches, branch_id, product_id, quantity, batch_id, expiry_days=None, extra=None):
    if any(b.get("batch") == batch_id for b in batches):
        return False, f"Duplicate batch ID: {batch_id}"
    record = {"batch": batch_id, "product": product_id, "branch": branch_id,
              "quantity": quantity, "expiry_days": expiry_days}
    if extra:
        record.update(extra)
    batches.append(record)
    return True, record

def restore_allocations(batches, branch_id, product_id, allocations):
    """Restore returns to the exact original lots, creating a traceable return lot if needed."""
    by_id = {b["batch"]: b for b in batches}
    for allocation in allocations:
        batch = by_id.get(allocation["batch"])
        if batch and batch.get("branch") == branch_id and batch.get("product") == product_id:
            batch["quantity"] += allocation["quantity"]
        else:
            return False, f"Original batch unavailable for return: {allocation['batch']}"
    return True, None

def move_batches(batches, from_branch, to_branch, product_id, quantity, transaction_id):
    eligible = [b for b in batches if b.get("branch") == from_branch and b.get("product") == product_id and b.get("quantity", 0) > 0]
    eligible.sort(key=lambda b: (b.get("expiry_days") is None, b.get("expiry_days") if b.get("expiry_days") is not None else float("inf"), b["batch"]))
    if quantity > sum(b["quantity"] for b in eligible):
        return False, "Insufficient batch stock for transfer"
    planned, remaining = [], quantity
    for batch in eligible:
        amount = min(batch["quantity"], remaining)
        if amount:
            planned.append((batch, amount))
            remaining -= amount
        if remaining == 0:
            break
    # Precheck all destination batch IDs before mutation.
    new_records = []
    existing_ids = {b["batch"] for b in batches}
    for index, (source, amount) in enumerate(planned, 1):
        new_id = f"XFER-{transaction_id}-{index}"
        if new_id in existing_ids:
            return False, f"Duplicate transfer batch ID: {new_id}"
        new_records.append({"batch": new_id, "product": product_id, "branch": to_branch,
                            "quantity": amount, "expiry_days": source.get("expiry_days"),
                            "source_batch": source["batch"], "transfer_id": transaction_id})
        existing_ids.add(new_id)
    for source, amount in planned:
        source["quantity"] -= amount
    batches.extend(new_records)
    return True, new_records

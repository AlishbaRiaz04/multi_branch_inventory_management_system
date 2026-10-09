from validation import validate_branch

def transfer_stock(transfer, branches):
    from_branch=transfer.get("from_branch")
    to_branch=transfer.get("to_branch")
    product_id=transfer.get("product")
    quantity=transfer.get("quantity")

    # checks first, then we read the stock (reading it first crashed on invalid branches)
    valid, reason=validate_branch(from_branch, branches)
    if not valid:
        return False, f"Invalid Source branch: {from_branch}"

    valid, reason=validate_branch(to_branch, branches)
    if not valid:
        return False, f"Invalid Destination branch: {to_branch}"

    if from_branch == to_branch:
        return False, "Source and destination branch are same branch"

    source_stock=branches[from_branch]["inventory"].get(product_id, 0)

    if product_id not in branches[from_branch]["inventory"]:
        return False, f"Product {product_id} not found in {from_branch}"

    if quantity>source_stock:
        return False, f"Insufficient stock. Available: {source_stock}, requested: {quantity}"

    branches[from_branch]["inventory"][product_id]-=quantity
    # .get so a destination that doesn't have the product yet doesn't crash
    branches[to_branch]["inventory"][product_id]=branches[to_branch]["inventory"].get(product_id, 0)+quantity

    return True, None




def reconcile_inventory(physical_stock, branches):
    reconcile_stats = {}
    for branch_id, products in physical_stock.items():

        # Unknown branch: record it instead of crashing
        if branch_id not in branches:
            reconcile_stats[branch_id] = {"invalid": {"product": None, "status": "invalid branch"}}
            continue

        reconcile_stats[branch_id] = {}
        branch = branches[branch_id]
        for product_id, stock in products.items():

            # Unknown product for this branch: record it instead of crashing
            if product_id not in branch["inventory"]:
                reconcile_stats[branch_id][product_id]={"product": product_id, "status": "invalid product"}
                continue

            system_stock = branch["inventory"][product_id]
            # Difference = system - physical, so a shortage is a positive number
            difference = system_stock - stock

            if stock == system_stock:
                status = "MATCHED"
            elif stock < system_stock:
                status = "SHORTAGE"
            else:
                status = "EXCESS"

            # Two keys: branch slot, then product slot, so nothing gets overwritten
            reconcile_stats[branch_id][product_id]={
                "product": product_id,
                "system_stock": system_stock,
                "physical_stock": stock,
                "difference": difference,
                "status": status
            }
    return reconcile_stats

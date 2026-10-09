def validate_product(product_id, products):
    if not isinstance(product_id, str) or product_id not in products:
        return False, f"Invalid Product: {product_id}"
    return True, None

def validate_branch(branch_id, branches):
    if not isinstance(branch_id, str) or branch_id not in branches:
        return False, f"Invalid branch: {branch_id}"

    return True, None


# how many units of this product can still be returned at this branch
# (successful sales minus successful customer returns)
def get_returnable_quantity(branch_id, product_id, transactions):
    sold=0
    returned=0
    for t in transactions:
        if t["transaction_status"]=="SUCCESS" and t["branch_id"]==branch_id and t["product_id"]==product_id:
            if t["transaction_type"]=="sale":
                sold+=t["quantity"]
            elif t["transaction_type"]=="customer_return":
                returned+=t["quantity"]
    return sold-returned


# "transactions" here = the results of the transactions processed so far
def validate_transaction(transaction, transactions, products, branches):
    if not isinstance(transaction, dict):
        return False, "Transaction must be a dictionary"

    transaction_type=transaction.get("type")

    #checking transaction type (first, so the missing-fields check below uses the right list)
    valid_transaction_types=["purchase", "sale", "customer_return", "supplier_return", "transfer"]
    if transaction_type not in valid_transaction_types:
        return False, f"Invalid transaction type: {transaction_type}"

    #check missing fields
    if transaction_type == "transfer":
        required = ["id", "type", "from_branch", "to_branch", "product", "quantity"]
    else:
        required = ["id", "type", "branch", "product", "quantity"]

    missing=[field for field in required if field not in transaction]
    if len(missing)>0:
        return False, f"Missing fields: {missing}"

    #duplicate transaction id (set of ids already processed)
    transaction_id=transaction["id"]
    if not isinstance(transaction_id, str):
        return False, "Transaction id must be text"
    used_ids={t["transaction_id"] for t in transactions}
    if transaction_id in used_ids:
        return False, f"Duplicate transaction ID: {transaction_id}"

    quantity=transaction.get("quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        return False, "Quantity must be a whole number"

    if quantity<0:
        return False, "Quantity can't be negative"
    if quantity==0:
        return False, "Quantity can't be zero"

    #validating product in transaction
    product_id=transaction.get("product")
    valid, reason=validate_product(product_id, products)
    if not valid:
        return False, reason

    #validating branches in transaction
    if transaction_type == "transfer":
        from_branch = transaction.get("from_branch")
        to_branch = transaction.get("to_branch")

        valid, reason = validate_branch(from_branch, branches)
        if not valid:
            return False, f"Invalid source branch: {from_branch}"

        valid, reason = validate_branch(to_branch, branches)
        if not valid:
            return False, f"Invalid destination branch: {to_branch}"
        # stock + same-branch checks for transfers happen in transfer_stock
    else:
        branch_id = transaction.get("branch")
        valid, reason = validate_branch(branch_id, branches)
        if not valid:
            return False, reason

        if transaction_type in ("sale", "supplier_return"):
            valid, reason = validate_stock(transaction, branches)
            if not valid:
                return False, f"Insufficient stock. {reason}"

        if transaction_type == "customer_return":
            returnable=get_returnable_quantity(branch_id, product_id, transactions)
            if quantity>returnable:
                return False, f"Return more than sold. Returnable: {returnable} - Requested quantities: {quantity}"

    return True, None

def validate_stock(transaction, branches):
    quantity=transaction["quantity"]
    branch_id=transaction["branch"]
    product_id=transaction["product"]
    stock=branches[branch_id]["inventory"].get(product_id,0)
    if quantity>stock:
        return False, f"Available: {stock} - Requested quantities: {quantity}"

    return True,f"Available: {stock} - Requested quantities: {quantity}"


def validate_batch(batch, seen_batches, products, branches):
    if not isinstance(batch, dict):
        return False, "Batch must be a dictionary"

    missing=[field for field in ["batch", "product", "branch", "quantity", "expiry_days"] if field not in batch]
    if len(missing)>0:
        return False, f"Missing fields: {missing}"

    if not isinstance(batch["batch"], str):
        return False, "Batch id must be text"
    if batch["batch"] in seen_batches:
        return False, "Duplicate batch Id"

    valid, reason=validate_product(batch["product"], products)
    if not valid:
        return False, f"Unknown batch product: {batch['product']}"
    valid, reason=validate_branch(batch["branch"], branches)
    if not valid:
        return False, f"Unknown batch branch: {batch['branch']}"

    quantity=batch["quantity"]
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity<=0:
        return False, "Batch quantity must be a positive whole number"

    expiry_days=batch["expiry_days"]
    if isinstance(expiry_days, bool) or not isinstance(expiry_days, int):
        return False, "Expiry days must be a number"
    if expiry_days<0:
        return False, "Expiry days must not be negative"

    return True, None

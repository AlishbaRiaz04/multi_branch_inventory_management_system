"""Input and transaction validation. Validation functions do not mutate data."""
def validate_product(product_id, products):
    if not isinstance(product_id, str) or product_id not in products:
        return False, f"Invalid Product: {product_id}"
    return True, None

def validate_branch(branch_id, branches):
    if not isinstance(branch_id, str) or branch_id not in branches:
        return False, f"Invalid branch: {branch_id}"
    branch = branches[branch_id]
    if not isinstance(branch, dict) or not isinstance(branch.get("inventory"), dict):
        return False, f"Invalid inventory structure for branch: {branch_id}"
    return True, None

def validate_stock_value(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0

def get_returnable_quantity(branch_id, product_id, transactions, sale_id=None):
    sold = returned = 0
    for result in transactions:
        if result.get("transaction_status") != "SUCCESS":
            continue
        if result.get("transaction_type") == "sale":
            if result.get("branch_id") == branch_id and result.get("product_id") == product_id:
                if sale_id is None or result.get("transaction_id") == sale_id:
                    sold += result.get("quantity", 0)
        elif result.get("transaction_type") == "customer_return":
            if result.get("branch_id") == branch_id and result.get("product_id") == product_id:
                if sale_id is None or result.get("original_sale_id") == sale_id:
                    returned += result.get("quantity", 0)
    return sold - returned

def validate_transaction(transaction, transactions, products, branches, batches=None):
    if not isinstance(transaction, dict):
        return False, "Transaction must be a dictionary"

    tx_type = transaction.get("type")
    allowed = {"purchase", "sale", "customer_return", "supplier_return", "transfer"}
    if not isinstance(tx_type, str) or tx_type not in allowed:
        return False, f"Invalid transaction type: {tx_type}"

    required = ["id", "type", "from_branch", "to_branch", "product", "quantity"] if tx_type == "transfer" else ["id", "type", "branch", "product", "quantity"]
    missing = [field for field in required if field not in transaction]
    if missing:
        return False, f"Missing fields: {missing}"

    txid = transaction.get("id")
    if not isinstance(txid, str) or not txid.strip():
        return False, "Transaction id must be non-empty text"
    used_ids = {t.get("transaction_id") for t in transactions}
    if txid in used_ids:
        return False, f"Duplicate transaction ID: {txid}"

    qty = transaction.get("quantity")
    if isinstance(qty, bool) or not isinstance(qty, int):
        return False, "Quantity must be a whole number"
    if qty <= 0:
        return False, "Quantity must be positive; zero and negative quantities are invalid"

    product_id = transaction.get("product")
    valid, reason = validate_product(product_id, products)
    if not valid:
        return False, reason

    if tx_type == "transfer":
        source, destination = transaction.get("from_branch"), transaction.get("to_branch")
        valid, reason = validate_branch(source, branches)
        if not valid:
            return False, f"Invalid source branch: {source}"
        valid, reason = validate_branch(destination, branches)
        if not valid:
            return False, f"Invalid destination branch: {destination}"
        if source == destination:
            return False, "Source and destination are the same branch"
        stock = branches[source]["inventory"].get(product_id, 0)
        if not validate_stock_value(stock):
            return False, f"Invalid source stock value for {product_id}: {stock!r}"
        if qty > stock:
            return False, f"Insufficient stock. Available: {stock}, requested: {qty}"
        if batches is not None:
            batch_stock = sum(b.get("quantity", 0) for b in batches
                              if b.get("branch") == source and b.get("product") == product_id)
            if qty > batch_stock:
                return False, f"Insufficient source batch stock. Available: {batch_stock}, requested: {qty}"
        dest_stock = branches[destination]["inventory"].get(product_id, 0)
        if not validate_stock_value(dest_stock):
            return False, f"Invalid destination stock value for {product_id}: {dest_stock!r}"
        return True, None

    branch_id = transaction.get("branch")
    valid, reason = validate_branch(branch_id, branches)
    if not valid:
        return False, reason
    inventory = branches[branch_id]["inventory"]
    stock = inventory.get(product_id, 0)
    if not validate_stock_value(stock):
        return False, f"Invalid stock value for {product_id}: {stock!r}"

    if tx_type in ("sale", "supplier_return") and qty > stock:
        return False, f"Insufficient stock. Available: {stock}, requested: {qty}"
    if tx_type in ("sale", "supplier_return") and batches is not None:
        if tx_type == "sale":
            available_batch_stock = sum(
                b.get("quantity", 0) for b in batches
                if b.get("branch") == branch_id and b.get("product") == product_id
                and (b.get("expiry_days") is None or b.get("expiry_days") > 0)
            )
        else:
            available_batch_stock = sum(
                b.get("quantity", 0) for b in batches
                if b.get("branch") == branch_id and b.get("product") == product_id
            )
        if qty > available_batch_stock:
            return False, f"Insufficient batch stock. Available: {available_batch_stock}, requested: {qty}"

    if tx_type == "customer_return":
        sale_id = transaction.get("original_sale_id")
        if not isinstance(sale_id, str) or not sale_id:
            return False, "Customer return requires original_sale_id"
        original_sale = next((t for t in transactions if t.get("transaction_id") == sale_id), None)
        if not original_sale or original_sale.get("transaction_status") != "SUCCESS" or original_sale.get("transaction_type") != "sale":
            return False, f"Original successful sale not found: {sale_id}"
        if original_sale.get("branch_id") != branch_id or original_sale.get("product_id") != product_id:
            return False, "Return branch and product must match the original sale"
        returnable = get_returnable_quantity(branch_id, product_id, transactions, sale_id=sale_id)
        if qty > returnable:
            return False, f"Return exceeds remaining quantity. Returnable: {returnable}, requested: {qty}"

    for field in ("price", "cost"):
        if field in transaction and (isinstance(transaction[field], bool) or not isinstance(transaction[field], int) or transaction[field] < 0):
            return False, f"{field} must be a non-negative number"
    if tx_type == "purchase":
        expiry = transaction.get("expiry_days")
        if expiry is not None and (isinstance(expiry, bool) or not isinstance(expiry, int) or expiry < 0):
            return False, "expiry_days must be a non-negative whole number or null"
    return True, None

def validate_batch(batch, seen_batches, products, branches):
    if not isinstance(batch, dict):
        return False, "Batch must be a dictionary"
    required = ["batch", "product", "branch", "quantity"]
    missing = [field for field in required if field not in batch]
    if missing:
        return False, f"Missing fields: {missing}"
    batch_id = batch.get("batch")
    if not isinstance(batch_id, str) or not batch_id.strip():
        return False, "Batch id must be non-empty text"
    if batch_id in seen_batches:
        return False, f"Duplicate batch ID: {batch_id}"
    valid, _ = validate_product(batch.get("product"), products)
    if not valid:
        return False, f"Unknown batch product: {batch.get('product')}"
    valid, _ = validate_branch(batch.get("branch"), branches)
    if not valid:
        return False, f"Unknown batch branch: {batch.get('branch')}"
    quantity = batch.get("quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        return False, "Batch quantity must be a positive whole number"
    expiry = batch.get("expiry_days")
    if expiry is not None and (isinstance(expiry, bool) or not isinstance(expiry, int) or expiry < 0):
        return False, "expiry_days must be a non-negative whole number or null"
    return True, None


def validate_stock(transaction, branches):
    branch_id, product_id, quantity = transaction.get("branch"), transaction.get("product"), transaction.get("quantity")
    valid, reason = validate_branch(branch_id, branches)
    if not valid:
        return False, reason
    stock = branches[branch_id]["inventory"].get(product_id, 0)
    if not validate_stock_value(stock):
        return False, f"Invalid stock value: {stock!r}"
    if quantity > stock:
        return False, f"Available: {stock} - Requested quantities: {quantity}"
    return True, f"Available: {stock} - Requested quantities: {quantity}"

from transfering import transfer_stock
from validation import validate_transaction

# **kwargs: every result has the same 3 base fields, the rest depends on the transaction
def make_result(transaction_id, status, reason, **details):
    result={
        "transaction_id": transaction_id,
        "transaction_status": status,
        "reason": reason
    }
    result.update(details)
    return result


#Processing Purchase
def process_purchase(branches, branch_id, product_id, quantity):
    inventory=branches[branch_id]["inventory"]
    inventory[product_id]=inventory.get(product_id, 0)+quantity

def process_customer_return(branches, branch_id, product_id, quantity):
    inventory=branches[branch_id]["inventory"]
    inventory[product_id]=inventory.get(product_id, 0)+quantity

def process_supplier_return(branches, branch_id, product_id, quantity):
    branches[branch_id]["inventory"][product_id]-=quantity

def process_sale(branches, branch_id, product_id, quantity):
    branches[branch_id]["inventory"][product_id]-=quantity


#processing Transactions
# "transactions" = results of the transactions processed so far
def process_transaction(transaction, transactions, products, branches):
    is_valid, rsn=validate_transaction(transaction, transactions, products, branches)
    status="SUCCESS"
    reason="Transaction processed successfully"

    data=transaction if isinstance(transaction, dict) else {}
    transaction_type = data.get("type")
    branch_id = data.get("branch")
    product_id = data.get("product")
    quantity = data.get("quantity")
    to_branch_id = None

    if transaction_type=="transfer":
        branch_id=data.get("from_branch")      # so reports can see where the stock moved
        to_branch_id=data.get("to_branch")

    if is_valid:
        if transaction_type=="purchase":
            process_purchase(branches, branch_id, product_id, quantity)
        elif transaction_type=="sale":
            process_sale(branches, branch_id, product_id, quantity)
        elif transaction_type=="customer_return":
            process_customer_return(branches, branch_id, product_id, quantity)
        elif transaction_type=="supplier_return":
            process_supplier_return(branches, branch_id, product_id, quantity)
        elif transaction_type=="transfer":
            ok, transfer_reason=transfer_stock(transaction, branches)
            if not ok:
                status="REJECTED"
                reason=transfer_reason
    else:
        status="REJECTED"
        reason=rsn

    return make_result(
        data.get("id"), status, reason,
        product_id=product_id,
        branch_id=branch_id,
        to_branch_id=to_branch_id,
        quantity=quantity if isinstance(quantity, int) else 0,
        transaction_type=transaction_type
    )

def process_all_transactions(transactions, products, branches):
    processed_transactions=[]

    #Empty transaction list: just return an empty list (dashboard shows 0 processed)
    for t in transactions:
        try:
            result=process_transaction(t, processed_transactions, products, branches)
        except Exception as e:      # safety net, one bad record must not stop the rest
            result=make_result(None, "REJECTED", f"Unexpected error: {e}",
                               product_id=None, branch_id=None, to_branch_id=None,
                               quantity=0, transaction_type=None)
        processed_transactions.append(result)

    return processed_transactions


#Processing Sales (one sale -> its revenue/cost/profit)
def process_sales(transaction, products):
    transaction_type = transaction["transaction_type"]
    status=transaction["transaction_status"]
    revenue = 0
    total_cost = 0
    gross_profit=0
    product_id = transaction["product_id"]
    quantity=transaction["quantity"]
    if transaction_type=="sale" and status=="SUCCESS":

        price=products[product_id]["price"]
        cost=products[product_id]["cost"]
        revenue=price*quantity
        total_cost=cost*quantity
        gross_profit=revenue-total_cost


    return {
        "revenue": revenue,
        "cost": total_cost,
        "gross_profit": gross_profit,
        "product_id": product_id,
        "branch_id": transaction["branch_id"],
        "quantity": quantity
    }

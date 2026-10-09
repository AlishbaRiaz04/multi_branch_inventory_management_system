from processing import process_all_transactions, process_sales
from transfering import reconcile_inventory
from utils import classify_batch, combine_inventories
from validation import validate_batch



def generate_expiry_report(batches, products, branches):
    expiry_stats={}
    rejected_batches=[]
    seen_batches=set()

    # one loop: validate each batch, skip (and record) the bad ones
    for batch in batches:
        valid, reason=validate_batch(batch, seen_batches, products, branches)
        if not valid:
            batch_id=batch.get("batch") if isinstance(batch, dict) else None
            rejected_batches.append({"batch": batch_id, "reason": reason})
            continue
        seen_batches.add(batch["batch"])

        expiry_days=batch["expiry_days"]
        branch_id=batch["branch"]
        if branch_id not in expiry_stats:
            expiry_stats[branch_id] = []
        expiry_stats[branch_id].append({
            "product": batch["product"],
            "batch": batch["batch"],
            "quantity": batch["quantity"],
            "expiry_days": expiry_days,
            "status": classify_batch(expiry_days),

        })
    return expiry_stats, rejected_batches



def generate_reorder_report(products, branches):
    branch_reorder_stats={}

    for branch_id in branches:
        branch_reorder_stats[branch_id]=[]
        inventory=branches[branch_id]["inventory"]
        # loop over products (not inventory) so a product missing from an empty inventory counts as 0
        for product_id in products:
            stock=inventory.get(product_id, 0)
            reorder_level=products[product_id]["reorder_level"]
            if stock<=reorder_level:
                branch_reorder_stats[branch_id].append(product_id)

    return branch_reorder_stats


def calculate_stock_value(products, branches):
    branch_values={}
    for branch_id, branch_detail in branches.items():
        units=0
        cost_value=0
        sales_value=0
        for product_id, quantity in branch_detail["inventory"].items():
            if product_id not in products:
                continue
            units+=quantity
            cost_value+=products[product_id]["cost"]*quantity
            sales_value+=products[product_id]["price"]*quantity
        branch_values[branch_id]={
            "units": units,
            "cost_value": cost_value,
            "sales_value": sales_value,
            "profit": sales_value-cost_value
        }

    # company-wide totals
    totals={
        "units": sum(v["units"] for v in branch_values.values()),
        "cost_value": sum(v["cost_value"] for v in branch_values.values()),
        "sales_value": sum(v["sales_value"] for v in branch_values.values()),
        "profit": sum(v["profit"] for v in branch_values.values())
    }
    # *args used here: units per product for the whole company
    company_stock=combine_inventories(*[b["inventory"] for b in branches.values()])
    return branch_values, totals, company_stock


def generate_sales_report(processed_transactions, products):
    revenue=0
    cost=0
    gross_profit=0
    units_sold={}
    revenue_by_product={}
    profit_by_product={}
    revenue_by_branch={}

    for transaction in processed_transactions:
        if transaction["transaction_type"]=="sale" and transaction["transaction_status"]=="SUCCESS":
            sale=process_sales(transaction, products)
            product_id=sale["product_id"]
            branch_id=sale["branch_id"]
            revenue+=sale["revenue"]
            cost+=sale["cost"]
            gross_profit+=sale["gross_profit"]
            units_sold[product_id]=units_sold.get(product_id, 0)+sale["quantity"]
            revenue_by_product[product_id]=revenue_by_product.get(product_id, 0)+sale["revenue"]
            profit_by_product[product_id]=profit_by_product.get(product_id, 0)+sale["gross_profit"]
            revenue_by_branch[branch_id]=revenue_by_branch.get(branch_id, 0)+sale["revenue"]

    # LEGB: `highest` is Local, `data` comes in as a parameter, and `sum`/`max` are Built-in.
    # (units_sold etc. are Enclosing names of generate_sales_report; nothing is Global here.)
    def highest(data):
        if len(data)==0:
            return None
        return max(data, key=lambda key: data[key])

    def lowest(data):
        if len(data)==0:
            return None
        return min(data, key=lambda key: data[key])

    return {
        "revenue": revenue,
        "cost": cost,
        "gross_profit": gross_profit,
        "units_sold": sum(units_sold.values()),
        "best_selling": highest(units_sold),
        "worst_selling": lowest(units_sold),
        "top_revenue_product": highest(revenue_by_product),
        "top_profit_product": highest(profit_by_product),
        "top_branch": highest(revenue_by_branch)
    }


def generate_inventory_dashbaord(products, branches, transactions, physical_stock, batches):


    total_branches=len(branches)
    total_products=len(products)


    #transactions
    processed_transactions=process_all_transactions(transactions, products, branches)
    processed=0
    successful=0
    rejected=0
    for transaction in processed_transactions:
        processed+=1
        if transaction["transaction_status"]=="SUCCESS":
            successful+=1
        elif transaction["transaction_status"]=="REJECTED":
            rejected+=1

    #sales
    sales=generate_sales_report(processed_transactions, products)

    #inventory
    branch_values, totals, company_stock=calculate_stock_value(products, branches)

    #stock alerts
    low_stock_products = []
    branch_reorder_stats = generate_reorder_report(products, branches)
    for branch_low_stock in branch_reorder_stats.values():
        low_stock_products.extend(branch_low_stock)

    critical_expiry_batches = []
    expired_batches = []
    expiry_stats, rejected_batches = generate_expiry_report(batches, products, branches)
    for records in expiry_stats.values():
        for record in records:
            if record["status"] == "Expired":
                expired_batches.append(record["batch"])
            elif record["status"] == "Critical":
                critical_expiry_batches.append(record["batch"])



    #reconcilation
    matched=0
    shortages=0
    excess=0
    reconcile_stats=reconcile_inventory(physical_stock, branches)
    for records in reconcile_stats.values():
        for record in records.values():
            if record["status"]=="MATCHED":
                matched+=1
            elif record["status"]=="SHORTAGE":
                shortages+=1
            elif record["status"]=="EXCESS":
                excess+=1

    top_product=sales["top_revenue_product"]
    if top_product is None:
        top_product_text="N/A"
    else:
        top_product_text=f"{top_product} ({products[top_product]['name']})"


    print("=" * 50)
    print("INVENTORY MANAGEMENT DASHBOARD".center(50, ' '))
    print("=" * 50)
    print("Branches: ", total_branches)
    print("Products: ", total_products)
    print("\nTransactions")
    print("-"*50)
    print("Processed: ", processed)
    print("Successful: ", successful)
    print("Rejected: ", rejected)
    print("\nInventory")
    print("-" * 50)
    print("Total Units: ", totals["units"])
    print("Inventory Cost Value: $", totals["cost_value"])
    print("Potential Sales Value: $", totals["sales_value"])
    print("Potential Profit: $", totals["profit"])
    print("\nSales")
    print("-"*50)
    print("Revenue: $", sales["revenue"])
    print("Cost: $", sales["cost"])
    print("Gross Profit: $", sales["gross_profit"])
    print("Top Product: ", top_product_text)
    print("Top Branch: ", sales["top_branch"] or "N/A")
    print("\nStock Alerts")
    print("-"*50)
    if len(low_stock_products)==0:
        print("Low Stock Products: ", "No Products low in stock")
    else:
        print("Low Stock Products: ", len(low_stock_products), low_stock_products)
    if len(critical_expiry_batches)==0:
        print("Critical Expiry Batches: ", "None")
    else:
        print("Critical Expiry Batches: ", len(critical_expiry_batches), critical_expiry_batches)

    if len(expired_batches)==0:
        print("Expired Batches: ", "None")
    else:
        print("Expired Batches: ", len(expired_batches), expired_batches)
    print("\nReconciliation")
    print("-"*50)
    print("Matched: ", matched)
    print("Shortages: ", shortages)
    print("Excess: ", excess)

    # everything the detailed reports need, handed back to main
    return {
        "transactions": processed_transactions,
        "sales": sales,
        "branch_values": branch_values,
        "totals": totals,
        "reorder": branch_reorder_stats,
        "expiry": expiry_stats,
        "rejected_batches": rejected_batches,
        "reconcile": reconcile_stats
    }


# the detailed reports the assignment asks for (branch by branch)
def print_detailed_reports(report, products, branches):
    print("\n\nTRANSACTION LOG")
    print("-"*50)
    if len(report["transactions"])==0:
        print("No transactions to process")
    for t in report["transactions"]:
        print(t["transaction_id"], t["transaction_type"], t["transaction_status"], "-", t["reason"])

    print("\nSTOCK VALUE PER BRANCH")
    print("-"*50)
    for branch_id, v in report["branch_values"].items():
        print(branches[branch_id]["name"], "| Units:", v["units"], "| Cost:", v["cost_value"],
              "| Sales:", v["sales_value"], "| Profit:", v["profit"])
    totals=report["totals"]
    print("COMPANY TOTAL | Units:", totals["units"], "| Cost:", totals["cost_value"],
          "| Sales:", totals["sales_value"], "| Profit:", totals["profit"])

    sales=report["sales"]
    print("\nSALES ANALYTICS")
    print("-"*50)
    print("Units sold: ", sales["units_sold"])
    print("Best-selling product: ", sales["best_selling"])
    print("Worst-selling product: ", sales["worst_selling"])
    print("Highest-revenue product: ", sales["top_revenue_product"])
    print("Highest-profit product: ", sales["top_profit_product"])
    print("Highest-revenue branch: ", sales["top_branch"])

    print("\nREORDER REPORT")
    print("-"*50)
    for branch_id, product_ids in report["reorder"].items():
        for product_id in product_ids:
            stock=branches[branch_id]["inventory"].get(product_id, 0)
            print(branches[branch_id]["name"], "-", products[product_id]["name"],
                  "stock:", stock, "reorder level:", products[product_id]["reorder_level"])
    if sum(len(p) for p in report["reorder"].values())==0:
        print("No products at or below reorder level")

    print("\nEXPIRY REPORT")
    print("-"*50)
    for branch_id, records in report["expiry"].items():
        print(branches[branch_id]["name"])
        for record in records:
            print("  ", record["batch"], record["product"], "qty:", record["quantity"],
                  "days:", record["expiry_days"], "->", record["status"])
    for bad in report["rejected_batches"]:
        print("Rejected batch", bad["batch"], "-", bad["reason"])

    print("\nRECONCILIATION")
    print("-"*50)
    for branch_id, records in report["reconcile"].items():
        for record in records.values():
            if "system_stock" in record:
                print(branch_id, record["product"], "system:", record["system_stock"],
                      "physical:", record["physical_stock"], "difference:", record["difference"],
                      record["status"])
            else:
                print(branch_id, record["product"], "-", record["status"])

import io
from contextlib import redirect_stdout
from processing import process_all_transactions
from reports import (generate_inventory_dashbaord, generate_expiry_report,
                     generate_reorder_report, calculate_stock_value, generate_sales_report)
from transfering import reconcile_inventory
from utils import load_data, classify_batch


def get_data():
    products = {
        "P001": {"name": "Panadol", "category": "Medicine", "price": 100, "cost": 70, "reorder_level": 10},
        "P002": {"name": "Vitamin C", "category": "Supplement", "price": 250, "cost": 180, "reorder_level": 5}
    }
    branches = {
        "B001": {"name": "Lahore Branch", "inventory": {"P001": 50, "P002": 20}},
        "B002": {"name": "Islamabad Branch", "inventory": {}}          # empty inventory
    }
    return products, branches


def txn(id, type, quantity, **extra):
    t = {"id": id, "type": type, "product": "P001", "quantity": quantity}
    if type != "transfer":
        t["branch"] = "B001"
    t.update(extra)
    return t


# each case: (name, transactions, expected statuses, text expected in last reason)
cases = [
    ("negative quantity", [txn("T1", "sale", -1)], ["REJECTED"], "negative"),
    ("zero quantity", [txn("T1", "sale", 0)], ["REJECTED"], "zero"),
    ("text quantity", [txn("T1", "sale", "5")], ["REJECTED"], "whole number"),
    ("insufficient stock", [txn("T1", "sale", 999)], ["REJECTED"], "Available: 50"),
    ("invalid product", [txn("T1", "sale", 1, product="P999")], ["REJECTED"], "Invalid Product"),
    ("invalid branch", [txn("T1", "sale", 1, branch="B999")], ["REJECTED"], "Invalid branch"),
    ("invalid type", [txn("T1", "refund", 1)], ["REJECTED"], "Invalid transaction type"),
    ("missing fields", [{"id": "T1", "type": "sale"}], ["REJECTED"], "Missing fields"),
    ("not a dictionary", ["hello"], ["REJECTED"], "dictionary"),
    ("duplicate id", [txn("T1", "sale", 1), txn("T1", "sale", 1)], ["SUCCESS", "REJECTED"], "Duplicate"),
    ("same branch transfer", [txn("T1", "transfer", 5, from_branch="B001", to_branch="B001")], ["REJECTED"], "same"),
    ("invalid source branch", [txn("T1", "transfer", 5, from_branch="B9", to_branch="B002")], ["REJECTED"], "source"),
    ("invalid destination branch", [txn("T1", "transfer", 5, from_branch="B001", to_branch="B9")], ["REJECTED"], "destination"),
    ("transfer too big", [txn("T1", "transfer", 99, from_branch="B001", to_branch="B002")], ["REJECTED"], "Insufficient"),
    ("transfer to empty branch", [txn("T1", "transfer", 10, from_branch="B001", to_branch="B002")], ["SUCCESS"], "success"),
    ("supplier return over stock", [txn("T1", "supplier_return", 999)], ["REJECTED"], "Insufficient"),
    ("sale from empty inventory", [txn("T1", "sale", 1, branch="B002")], ["REJECTED"], "Available: 0"),
    ("purchase into empty inventory", [txn("T1", "purchase", 5, branch="B002")], ["SUCCESS"], "success"),
    ("return more than sold",
     [txn("T1", "sale", 5), txn("T2", "customer_return", 2), txn("T3", "customer_return", 4)],
     ["SUCCESS", "SUCCESS", "REJECTED"], "Returnable: 3"),
    ("return exactly what is left",
     [txn("T1", "sale", 5), txn("T2", "customer_return", 2), txn("T3", "customer_return", 3)],
     ["SUCCESS", "SUCCESS", "SUCCESS"], "success"),
    ("return with no sale", [txn("T1", "customer_return", 1)], ["REJECTED"], "Returnable: 0"),
    ("empty transaction list", [], [], None),
]


def test_transactions():
    for name, transactions, expected, text in cases:
        products, branches = get_data()
        results = process_all_transactions(transactions, products, branches)
        statuses = [r["transaction_status"] for r in results]
        assert statuses == expected, f"{name}: expected {expected}, got {statuses}"
        assert all(r["reason"] for r in results), f"{name}: reason is empty"
        if text:
            assert text.lower() in results[-1]["reason"].lower(), f"{name}: reason was {results[-1]['reason']}"
        for branch in branches.values():                       # stock must never be negative
            assert all(q >= 0 for q in branch["inventory"].values()), f"{name}: negative stock"
        print("PASS", name)


def test_stock_changes():
    products, branches = get_data()
    process_all_transactions([
        txn("T1", "purchase", 10), txn("T2", "sale", 4), txn("T3", "customer_return", 2),
        txn("T4", "supplier_return", 3), txn("T5", "transfer", 5, from_branch="B001", to_branch="B002")
    ], products, branches)
    # 50 + 10 - 4 + 2 - 3 - 5 = 50
    assert branches["B001"]["inventory"]["P001"] == 50
    assert branches["B002"]["inventory"]["P001"] == 5
    print("PASS stock changes")


def test_rejected_does_not_change_stock():
    products, branches = get_data()
    process_all_transactions([txn("T1", "sale", 999)], products, branches)
    assert branches["B001"]["inventory"]["P001"] == 50
    print("PASS rejected transaction leaves stock alone")


def test_expiry():
    assert [classify_batch(d) for d in (0, 1, 7, 8, 30, 31)] == \
        ["Expired", "Critical", "Critical", "Expiring Soon", "Expiring Soon", "Safe"]
    products, branches = get_data()
    batches = [
        {"batch": "A", "product": "P001", "branch": "B001", "quantity": 1, "expiry_days": 5},
        {"batch": "A", "product": "P001", "branch": "B001", "quantity": 1, "expiry_days": 50},    # duplicate
        {"batch": "B", "product": "P001", "branch": "B001", "quantity": 1, "expiry_days": -1},    # negative days
        {"batch": "C", "product": "P999", "branch": "B001", "quantity": 1, "expiry_days": 5},     # unknown product
        {"batch": "D", "product": "P001", "branch": "B999", "quantity": 1, "expiry_days": 5},     # unknown branch
        {"batch": "E", "product": "P001", "branch": "B001", "quantity": 1},                       # missing field
    ]
    stats, rejected = generate_expiry_report(batches, products, branches)
    assert len(stats["B001"]) == 1 and len(rejected) == 5
    assert generate_expiry_report([], products, branches) == ({}, [])
    print("PASS expiry")


def test_reorder():
    products, branches = get_data()
    stats = generate_reorder_report(products, branches)
    assert stats["B001"] == []
    assert stats["B002"] == ["P001", "P002"]       # empty inventory = 0 stock
    print("PASS reorder")


def test_stock_value():
    products, branches = get_data()
    values, totals, company_stock = calculate_stock_value(products, branches)
    assert values["B001"]["cost_value"] == 50 * 70 + 20 * 180
    assert totals["profit"] == totals["sales_value"] - totals["cost_value"]
    assert company_stock == {"P001": 50, "P002": 20}
    print("PASS stock value")


def test_sales_report():
    products, branches = get_data()
    results = process_all_transactions([txn("T1", "sale", 5), txn("T2", "sale", 2, product="P002")],
                                       products, branches)
    sales = generate_sales_report(results, products)
    assert sales["revenue"] == 1000 and sales["cost"] == 710 and sales["gross_profit"] == 290
    assert sales["best_selling"] == "P001" and sales["top_branch"] == "B001"
    assert generate_sales_report([], products)["best_selling"] is None
    print("PASS sales report")


def test_reconciliation():
    products, branches = get_data()
    stats = reconcile_inventory({"B001": {"P001": 50, "P002": 19, "P999": 1}, "B404": {"P001": 1}}, branches)
    assert stats["B001"]["P001"]["status"] == "MATCHED"
    assert stats["B001"]["P002"]["status"] == "SHORTAGE"
    assert stats["B001"]["P999"]["status"] == "invalid product"
    assert stats["B404"]["invalid"]["status"] == "invalid branch"
    print("PASS reconciliation")


def test_load_data():
    data, error = load_data("file_that_does_not_exist.json")
    assert data is None and "not found" in error
    print("PASS load_data missing file")


def test_edge_file_does_not_crash():
    data, error = load_data("edge_cases_input.json")
    assert error is None
    with redirect_stdout(io.StringIO()):               # hide the dashboard print
        report = generate_inventory_dashbaord(data["products"], data["branches"], data["transactions"],
                                              data["physical_stock"], data["batches"])
    assert len(report["transactions"]) == len(data["transactions"])
    print("PASS edge_cases_input.json runs without crashing")


def test_sample_data():
    data, error = load_data("input_data.json")
    with redirect_stdout(io.StringIO()):
        report = generate_inventory_dashbaord(data["products"], data["branches"], data["transactions"],
                                              data["physical_stock"], data["batches"])
    assert [t["transaction_status"] for t in report["transactions"]] == ["SUCCESS"] * 4
    assert report["totals"]["units"] == 570 and report["sales"]["revenue"] == 1750
    print("PASS assignment sample data")


def test_empty_everything():
    with redirect_stdout(io.StringIO()):
        generate_inventory_dashbaord({}, {}, [], {}, [])
    print("PASS everything empty")


if __name__ == "__main__":
    test_transactions()
    test_stock_changes()
    test_rejected_does_not_change_stock()
    test_expiry()
    test_reorder()
    test_stock_value()
    test_sales_report()
    test_reconciliation()
    test_load_data()
    test_edge_file_does_not_crash()
    test_sample_data()
    test_empty_everything()
    print("\nALL TESTS PASSED")

"""Regression tests for the lead's review findings; standard-library unittest."""
import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from inventory import prepare_batches, check_batch_aggregate_consistency
from processing import process_all_transactions
from reports import generate_inventory_dashboard, generate_sales_report, calculate_stock_value
from transfering import transfer_stock, reconcile_inventory
from utils import load_data, classify_batch

def fixture():
    products = {
        "P001": {"name": "Panadol", "category": "Medicine", "price": 100, "cost": 70, "reorder_level": 2},
        "P002": {"name": "Vitamin C", "category": "Supplement", "price": 250, "cost": 180, "reorder_level": 2},
    }
    branches = {
        "B001": {"name": "Lahore", "inventory": {"P001": 10, "P002": 0}},
        "B002": {"name": "Karachi", "inventory": {"P001": 2, "P002": 0}},
    }
    batches = [
        {"batch": "LOT-A", "product": "P001", "branch": "B001", "quantity": 4, "expiry_days": 3},
        {"batch": "LOT-B", "product": "P001", "branch": "B001", "quantity": 6, "expiry_days": 30},
        {"batch": "LOT-C", "product": "P001", "branch": "B002", "quantity": 2, "expiry_days": 60},
    ]
    return products, branches, batches

def tx(txid, kind, quantity, **extra):
    base = {"id": txid, "type": kind, "product": "P001", "quantity": quantity}
    if kind == "transfer":
        base.update({"from_branch": "B001", "to_branch": "B002"})
    else:
        base["branch"] = "B001"
    base.update(extra)
    return base

class InventoryTests(unittest.TestCase):
    def test_transfer_corrupt_destination_is_atomic(self):
        branches = {
            "B001": {"name": "A", "inventory": {"P001": 10}},
            "B002": {"name": "B", "inventory": {"P001": "corrupted"}},
        }
        transfer = {"id": "X1", "type": "transfer", "from_branch": "B001",
                    "to_branch": "B002", "product": "P001", "quantity": 3}
        ok, reason = transfer_stock(transfer, branches)
        self.assertFalse(ok)
        self.assertIn("Invalid destination stock", reason)
        self.assertEqual(branches["B001"]["inventory"]["P001"], 10)

    def test_sale_uses_fefo_and_keeps_totals_consistent(self):
        products, branches, batches = fixture()
        results = process_all_transactions([tx("S1", "sale", 3)], products, branches, batches)
        self.assertEqual(results[-1]["transaction_status"], "SUCCESS")
        lots = {b["batch"]: b["quantity"] for b in batches}
        self.assertEqual(lots["LOT-A"], 1)
        self.assertEqual(lots["LOT-B"], 6)
        self.assertEqual(branches["B001"]["inventory"]["P001"], 7)
        self.assertEqual(check_batch_aggregate_consistency(batches, branches), [])


    def test_successful_transfer_moves_lots_and_preserves_totals(self):
        products, branches, batches = fixture()
        results = process_all_transactions([tx("X1", "transfer", 4)], products, branches, batches)
        self.assertEqual(results[-1]["transaction_status"], "SUCCESS")
        self.assertEqual(branches["B001"]["inventory"]["P001"], 6)
        self.assertEqual(branches["B002"]["inventory"]["P001"], 6)
        self.assertEqual(check_batch_aggregate_consistency(batches, branches), [])
        self.assertTrue(any(b.get("transfer_id") == "X1" for b in batches))

    def test_purchase_creates_batch_and_keeps_stock_consistent(self):
        products, branches, batches = fixture()
        results = process_all_transactions([tx("P1", "purchase", 5)], products, branches, batches)
        self.assertEqual(results[-1]["transaction_status"], "SUCCESS")
        self.assertEqual(branches["B001"]["inventory"]["P001"], 15)
        self.assertTrue(any(b["batch"] == "PURCHASE-P1" and b["quantity"] == 5 for b in batches))
        self.assertEqual(check_batch_aggregate_consistency(batches, branches), [])

    def test_customer_return_reverses_financials_and_restores_original_lots(self):
        products, branches, batches = fixture()
        results = process_all_transactions([
            tx("S1", "sale", 4),
            tx("R1", "customer_return", 2, original_sale_id="S1"),
        ], products, branches, batches)
        self.assertEqual([r["transaction_status"] for r in results], ["SUCCESS", "SUCCESS"])
        self.assertEqual(results[0]["revenue_delta"], 400)
        self.assertEqual(results[1]["revenue_delta"], -200)
        sales = generate_sales_report(results, products)
        self.assertEqual(sales["revenue"], 200)
        self.assertEqual(sales["cost"], 140)
        self.assertEqual(sales["gross_profit"], 60)
        self.assertEqual(branches["B001"]["inventory"]["P001"], 8)
        self.assertEqual(check_batch_aggregate_consistency(batches, branches), [])

    def test_return_without_original_sale_is_rejected(self):
        products, branches, batches = fixture()
        results = process_all_transactions([tx("R1", "customer_return", 1)], products, branches, batches)
        self.assertEqual(results[0]["transaction_status"], "REJECTED")
        self.assertIn("original_sale_id", results[0]["reason"])

    def test_dashboard_does_not_replay_transactions(self):
        products, branches, batches = fixture()
        results = process_all_transactions([tx("S1", "sale", 2)], products, branches, batches)
        stock_after_processing = copy.deepcopy(branches)
        batches_after_processing = copy.deepcopy(batches)
        with redirect_stdout(io.StringIO()):
            generate_inventory_dashboard(products, branches, results, {}, batches)
            generate_inventory_dashboard(products, branches, results, {}, batches)
        self.assertEqual(branches, stock_after_processing)
        self.assertEqual(batches, batches_after_processing)
        self.assertEqual(branches["B001"]["inventory"]["P001"], 8)

    def test_duplicate_or_overstated_batches_are_rejected(self):
        products, branches, _ = fixture()
        supplied = [
            {"batch": "BAD", "product": "P001", "branch": "B001", "quantity": 999, "expiry_days": 10}
        ]
        accepted, rejected = prepare_batches(supplied, products, branches)
        self.assertEqual(len(rejected), 1)
        self.assertIn("exceed", rejected[0]["reason"])
        self.assertEqual(sum(b["quantity"] for b in accepted if b["branch"] == "B001" and b["product"] == "P001"), 10)

    def test_worst_selling_includes_zero_sales_products(self):
        products, branches, batches = fixture()
        results = process_all_transactions([tx("S1", "sale", 1)], products, branches, batches)
        sales = generate_sales_report(results, products)
        self.assertEqual(sales["worst_selling"], "P002")

    def test_historical_prices_are_snapshotted(self):
        products, branches, batches = fixture()
        results = process_all_transactions([tx("S1", "sale", 2)], products, branches, batches)
        products["P001"]["price"] = 900
        products["P001"]["cost"] = 500
        sales = generate_sales_report(results, products)
        self.assertEqual(sales["revenue"], 200)
        self.assertEqual(sales["cost"], 140)

    def test_unknown_inventory_sku_is_not_silently_ignored(self):
        products, branches, _ = fixture()
        branches["B001"]["inventory"]["P999"] = 1
        with self.assertRaisesRegex(ValueError, "Unknown inventory SKU"):
            calculate_stock_value(products, branches)

    def test_reconciliation_marks_omitted_physical_items_not_counted(self):
        _, branches, _ = fixture()
        products, _, _ = fixture()
        result = reconcile_inventory({"B001": {"P001": 10, "P999": 1}}, branches, products)
        self.assertEqual(result["B001"]["P002"]["status"], "NOT_COUNTED")
        self.assertEqual(result["B002"]["P001"]["status"], "NOT_COUNTED")
        self.assertEqual(result["B001"]["P999"]["status"], "invalid product")

    def test_batch_expiry_classification(self):
        self.assertEqual(classify_batch(None), "Unknown")
        self.assertEqual(classify_batch(0), "Expired")
        self.assertEqual(classify_batch(1), "Critical")
        self.assertEqual(classify_batch(8), "Expiring Soon")
        self.assertEqual(classify_batch(31), "Safe")

    def test_input_loader_rejects_bad_nested_inventory(self):
        data = {
            "products": {"P001": {"name": "Item", "price": 100, "cost": 50, "reorder_level": 1}},
            "branches": {"B001": {"name": "Branch", "inventory": {"P001": "bad"}}},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as file:
            json.dump(data, file)
            path = file.name
        try:
            loaded, error = load_data(path)
            self.assertIsNone(loaded)
            self.assertIn("invalid stock", error.lower())
        finally:
            os.remove(path)

    def test_invalid_transaction_preserves_details(self):
        products, branches, batches = fixture()
        results = process_all_transactions([{
            "id": "BAD-TX", "type": "sale", "branch": "B001",
            "product": "P001", "quantity": "many"
        }], products, branches, batches)
        self.assertEqual(results[0]["transaction_id"], "BAD-TX")
        self.assertEqual(results[0]["transaction_type"], "sale")
        self.assertEqual(results[0]["branch_id"], "B001")
        self.assertEqual(results[0]["transaction_status"], "REJECTED")

if __name__ == "__main__":
    unittest.main(verbosity=2)

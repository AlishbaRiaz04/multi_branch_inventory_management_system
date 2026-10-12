"""General-purpose JSON and data helpers."""
import json
import os
from copy import deepcopy

def load_data(filename):
    try:
        with open(filename, "r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return None, f"File not found: {filename}"
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON in file {filename}: {exc}"
    except OSError as exc:
        return None, f"Could not read file {filename}: {exc}"

    if not isinstance(data, dict):
        return None, "JSON file must contain an object"
    for section in ("products", "branches"):
        if not isinstance(data.get(section), dict):
            return None, f"Missing or invalid section: {section}"
    if not isinstance(data.get("transactions", []), list):
        return None, "Section 'transactions' must be a list"
    if not isinstance(data.get("batches", []), list):
        return None, "Section 'batches' must be a list"
    if not isinstance(data.get("physical_stock", {}), dict):
        return None, "Section 'physical_stock' must be an object"

    errors = validate_catalog_and_branches(data["products"], data["branches"])
    if errors:
        return None, "Invalid input data: " + "; ".join(errors)
    data.setdefault("transactions", [])
    data.setdefault("batches", [])
    data.setdefault("physical_stock", {})
    for branch_id, counts in data["physical_stock"].items():
        if not isinstance(counts, dict):
            return None, f"Physical stock for {branch_id} must be an object"
        for product_id, quantity in counts.items():
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
                return None, f"Invalid physical stock quantity for {branch_id}/{product_id}"
    return data, None

def validate_catalog_and_branches(products, branches):
    errors = []
    for pid, product in products.items():
        if not isinstance(pid, str) or not pid:
            errors.append("product IDs must be non-empty strings")
            continue
        if not isinstance(product, dict):
            errors.append(f"product {pid} must be an object")
            continue
        for field in ("name", "price", "cost", "reorder_level"):
            if field not in product:
                errors.append(f"product {pid} missing {field}")
        if not isinstance(product.get("name"), str) or not product.get("name").strip():
            errors.append(f"product {pid} has invalid name")
        if "category" in product and not isinstance(product["category"], str):
            errors.append(f"product {pid} has invalid category")
        for field in ("price", "cost", "reorder_level"):
            value = product.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                errors.append(f"product {pid} has invalid {field}")
    for bid, branch in branches.items():
        if not isinstance(bid, str) or not bid:
            errors.append("branch IDs must be non-empty strings")
            continue
        if not isinstance(branch, dict) or not isinstance(branch.get("inventory"), dict):
            errors.append(f"branch {bid} must have an inventory object")
            continue
        if not isinstance(branch.get("name"), str) or not branch.get("name").strip():
            errors.append(f"branch {bid} has invalid name")
        for pid, qty in branch["inventory"].items():
            if pid not in products:
                errors.append(f"branch {bid} has unknown inventory SKU {pid}")
            if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
                errors.append(f"branch {bid} has invalid stock for {pid}")
    return errors

def save_data(filename, data):
    temporary = filename + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
        os.replace(temporary, filename)
    except (OSError, TypeError, ValueError) as exc:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass
        return False, f"Could not save file: {exc}"
    return True, None

def classify_batch(expiry_days):
    if expiry_days is None:
        return "Unknown"
    if expiry_days <= 0:
        return "Expired"
    if expiry_days <= 7:
        return "Critical"
    if expiry_days <= 30:
        return "Expiring Soon"
    return "Safe"

def combine_inventories(*inventories):
    combined = {}
    for inventory in inventories:
        for product_id, quantity in inventory.items():
            combined[product_id] = combined.get(product_id, 0) + quantity
    return combined

def create_products(products_data):
    from models import Product
    return {pid: Product(product_id=pid, **info) for pid, info in products_data.items()}

def create_branches(branches_data):
    from models import Branch
    return {bid: Branch(branch_id=bid, **info) for bid, info in branches_data.items()}

def create_transactions(transactions_data):
    from models import Transaction
    records, errors = [], []
    for index, raw in enumerate(transactions_data):
        if not isinstance(raw, dict):
            errors.append(f"Skipped transaction at index {index}: record must be an object")
            continue
        try:
            records.append(Transaction(**raw))
        except TypeError as exc:
            errors.append(f"Skipped transaction at index {index}: {exc}")
    return records, errors

import json
from models import Product, Branch, Transaction

#data loader
def load_data(filename):
    try:
        with open(filename, "r") as file:
            data=json.load(file)
    except FileNotFoundError:
        return None, f"File not found: {filename}"
    except json.JSONDecodeError:                      # added: broken json
        return None, f"Invalid JSON in file: {filename}"

    # added: make sure the main sections exist
    if not isinstance(data, dict):
        return None, "JSON file must contain an object"
    for section in ["products", "branches"]:
        if section not in data:
            return None, f"Missing section in file: {section}"

    return data, None

#data saver
def save_data(filename, data):
    try:
        with open(filename, "w") as file:
            json.dump(data, file, indent=4)
    except OSError as e:
        return False, f"Could not save file: {e}"
    return True, None


def classify_batch(expiry_days):
    if expiry_days<=0:
        return "Expired"
    elif expiry_days<=7:
        return "Critical"
    elif expiry_days<=30:
        return "Expiring Soon"
    else:
        return "Safe"

# *args: merge any number of branch inventories into one company-wide inventory
def combine_inventories(*inventories):
    combined={}
    for inventory in inventories:
        for product_id, quantity in inventory.items():
            combined[product_id]=combined.get(product_id, 0)+quantity
    return combined

def create_products(products_data):
    return {product_id: Product(product_id, **info)
            for product_id, info in products_data.items()}


def create_branches(branches_data):
    return {branch_id: Branch(branch_id, **info)
            for branch_id, info in branches_data.items()}


def create_transactions(transactions_data):
    transactions = []
    errors = []
    for raw in transactions_data:
        try:
            transactions.append(Transaction(**raw))
        except TypeError as e:
            errors.append(f"Skipped bad transaction record {raw}: {e}")
    return transactions, errors

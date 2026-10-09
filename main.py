from utils import load_data, save_data
from reports import generate_inventory_dashbaord, print_detailed_reports


def main():
    data, error = load_data("input_data.json")
    if error:
        print(error)
        return

    products = data["products"]
    branches = data["branches"]
    transactions = data.get("transactions", [])
    batches = data.get("batches", [])
    physical_stock = data.get("physical_stock", {})

    report = generate_inventory_dashbaord(products, branches, transactions, physical_stock, batches)
    print_detailed_reports(report, products, branches)

    # save every transaction result (SUCCESS / REJECTED + reason) to a json file
    saved, error = save_data("results.json", report["transactions"])
    if not saved:
        print(error)


if __name__ == "__main__":
    main()

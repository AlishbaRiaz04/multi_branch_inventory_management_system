"""Optional typed models. Runtime processing uses validated dictionaries for JSON compatibility."""
from dataclasses import dataclass
from typing import Optional

@dataclass
class Product:
    product_id: str
    name: str
    category: str
    price: int
    cost: int
    reorder_level: int

@dataclass
class Branch:
    branch_id: str
    name: str
    inventory: dict

@dataclass
class Transaction:
    id: str
    type: str
    product: str
    quantity: int
    branch: Optional[str] = None
    from_branch: Optional[str] = None
    to_branch: Optional[str] = None
    original_sale_id: Optional[str] = None
    batch: Optional[str] = None
    expiry_days: Optional[int] = None

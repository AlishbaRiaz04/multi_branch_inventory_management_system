from dataclasses import dataclass

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
    type:str
    product: str
    quantity: int
    branch: str | None= None
    from_branch: str | None= None
    to_branch: str | None= None

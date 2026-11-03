"""Carga e tratamento dos CSVs da loja.

Tratamentos aplicados:
- `specs` (JSON em string) vira dict;
- categoria e promoção ativa são unidas ao produto;
- só promoções `is_active=1` valem (as demais são histórico);
- e-mails/telefones são normalizados para comparação na verificação de identidade.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from .config import DATA_DIR


@dataclass(frozen=True)
class Promotion:
    promotion_id: int
    discount_percent: float
    description: str


@dataclass(frozen=True)
class Product:
    product_id: int
    name: str
    category: str
    price: float  # preço de tabela
    description: str
    stock: int
    status: str  # active | discontinued | coming_soon
    specs: dict = field(compare=False, hash=False)
    created_at: date | None
    promotion: Promotion | None = None


@dataclass(frozen=True)
class Customer:
    customer_id: int
    name: str
    phone: str
    email: str
    city: str


@dataclass(frozen=True)
class OrderItem:
    product_id: int
    quantity: int


@dataclass(frozen=True)
class Order:
    order_id: int
    customer_id: int
    order_date: date
    status: str
    total: float
    payment_method: str
    tracking_code: str | None
    estimated_delivery: date | None
    notes: str | None
    items: tuple[OrderItem, ...]


@dataclass
class Store:
    products: dict[int, Product]
    categories: dict[int, str]
    customers: dict[int, Customer]
    orders: dict[int, Order]


def _read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _file(suffix: str, data_dir: Path) -> Path:
    matches = sorted(data_dir.glob(f"*{suffix}.csv"))
    if not matches:
        raise FileNotFoundError(f"CSV '{suffix}' não encontrado em {data_dir}")
    return matches[0]


def _date(v: str | None) -> date | None:
    v = (v or "").strip()
    return date.fromisoformat(v) if v else None


def _specs(raw: str) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


def normalize_phone(p: str) -> str:
    """Só dígitos; descarta DDI 55 se presente."""
    d = re.sub(r"\D", "", p or "")
    return d[2:] if d.startswith("55") and len(d) > 11 else d


def normalize_email(e: str) -> str:
    return (e or "").strip().lower()


def load_store(data_dir: Path = DATA_DIR) -> Store:
    categories = {
        int(r["category_id"]): r["name"].strip()
        for r in _read(_file("categories", data_dir))
    }

    # Apenas promoções ativas. Se houver mais de uma para o produto, vale a maior.
    promos: dict[int, Promotion] = {}
    for r in _read(_file("promotions", data_dir)):
        if r["is_active"].strip() != "1":
            continue
        pid = int(r["product_id"])
        p = Promotion(int(r["promotion_id"]), float(r["discount_percent"]), r["description"].strip())
        if pid not in promos or p.discount_percent > promos[pid].discount_percent:
            promos[pid] = p

    products = {}
    for r in _read(_file("products", data_dir)):
        pid = int(r["product_id"])
        products[pid] = Product(
            product_id=pid,
            name=r["name"].strip(),
            category=categories.get(int(r["category_id"]), "Outros"),
            price=float(r["price_brl"]),
            description=r["description"].strip(),
            stock=int(r["stock_quantity"]),
            status=r["status"].strip(),
            specs=_specs(r["specs"]),
            created_at=_date(r["created_at"]),
            promotion=promos.get(pid),
        )

    customers = {
        int(r["customer_id"]): Customer(
            int(r["customer_id"]), r["name"].strip(), r["phone"].strip(),
            normalize_email(r["email"]), r["city"].strip(),
        )
        for r in _read(_file("customers", data_dir))
    }

    items: dict[int, list[OrderItem]] = {}
    for r in _read(_file("order_items", data_dir)):
        items.setdefault(int(r["order_id"]), []).append(
            OrderItem(int(r["product_id"]), int(r["quantity"]))
        )

    orders = {}
    for r in _read(_file("orders", data_dir)):
        oid = int(r["order_id"])
        orders[oid] = Order(
            order_id=oid,
            customer_id=int(r["customer_id"]),
            order_date=date.fromisoformat(r["order_date"]),
            status=r["status"].strip(),
            total=float(r["total_brl"]),
            payment_method=r["payment_method"].strip(),
            tracking_code=(r["tracking_code"] or "").strip() or None,
            estimated_delivery=_date(r["estimated_delivery"]),
            notes=(r["notes"] or "").strip() or None,
            items=tuple(items.get(oid, [])),
        )

    return Store(products, categories, customers, orders)


@lru_cache(maxsize=1)
def get_store() -> Store:
    return load_store()

"""`python -m emporio` — por enquanto, apenas verifica o ambiente (Sprint 0).

A CLI de conversa chega na Sprint 3/4.
"""
from __future__ import annotations

from . import config
from .data import load_store
from .llm import smoke_test


def main() -> None:
    store = load_store()
    print(
        f"Dados OK: {len(store.products)} produtos, {len(store.orders)} pedidos, "
        f"{len(store.customers)} clientes. Data de referência: {config.today()}"
    )
    try:
        print(f"LLM ({config.MODEL}) respondeu: {smoke_test()}")
    except Exception as e:  # noqa: BLE001
        print(f"LLM indisponível: {e}")


if __name__ == "__main__":
    main()

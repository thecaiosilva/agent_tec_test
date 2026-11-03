"""Regras de preço e pagamento do manual (seções 3 e 6).

Decisões / interpretações (documentadas no README):
- Promoção NÃO acumula com o desconto de PIX (6.2): produto em promoção não recebe 5%.
- Parcelamento: usamos as faixas da seção 3.1 (mais específicas) em vez do
  "mínimo de R$100" genérico da tabela da seção 3:
    1-3x  -> parcela mínima R$50
    4-6x  -> parcela mínima R$80
    7-12x -> parcela mínima R$100
"""
from __future__ import annotations

from .data import Product

PIX_DISCOUNT_PERCENT = 5.0
MAX_INSTALLMENTS = 12
# (até n parcelas, parcela mínima)
_TIERS = [(3, 50.0), (6, 80.0), (12, 100.0)]


def _round(v: float) -> float:
    return round(v + 1e-9, 2)


def current_price(p: Product) -> float:
    """Preço praticado hoje: tabela com a promoção ativa, se houver."""
    if p.promotion:
        return _round(p.price * (1 - p.promotion.discount_percent / 100))
    return _round(p.price)


def pix_price(p: Product) -> float | None:
    """Preço no PIX à vista; None se o produto está em promoção (não cumulativo)."""
    if p.promotion:
        return None
    return _round(p.price * (1 - PIX_DISCOUNT_PERCENT / 100))


def _min_installment(n: int) -> float:
    for limit, minimum in _TIERS:
        if n <= limit:
            return minimum
    return _TIERS[-1][1]


def installment_options(amount: float) -> list[dict]:
    """Opções de parcelamento sem juros no cartão de crédito respeitando a parcela mínima."""
    options = []
    for n in range(1, MAX_INSTALLMENTS + 1):
        value = _round(amount / n)
        if n == 1 or value >= _min_installment(n):
            options.append({"parcelas": n, "valor_parcela": value})
    return options


def max_installments(amount: float) -> int:
    return installment_options(amount)[-1]["parcelas"]

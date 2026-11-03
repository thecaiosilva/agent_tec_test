"""Ferramentas determinísticas que o agente poderá chamar (Sprint 1).

Todas retornam dicts serializáveis em JSON e NUNCA levantam exceção para
situações esperadas (não encontrado, verificação falhou): devolvem {"erro": ...}.
"""
from __future__ import annotations

from datetime import datetime

from . import config
from .data import Product, Store, get_store, normalize_email, normalize_phone
from .policies import search_policies  # noqa: F401  (reexportada como ferramenta)
from .pricing import current_price, installment_options, pix_price
from .text import compact, normalize, tokens

# ---------------------------------------------------------------- informações da loja

STORE_INFO = {
    "nome": "Empório da Música",
    "slogan": "Sua música começa aqui.",
    "endereco": "Rua 14 de Maio, 3200 — Centro, Campo Grande - MS, CEP 79202-333",
    "telefone": "(67) 3341-4444",
    "whatsapp": "(67) 3321-4500",
    "email": "contato@emporiodamusica.com.br",
    "horarios": {
        "segunda a sexta": "09:00 às 18:00",
        "sábado": "09:00 às 13:00",
        "domingo e feriados": "fechado",
    },
    "observacao": "Em datas especiais (Black Friday, aniversário da loja, Natal) o horário pode ser estendido.",
    "escopo": "Vendemos exclusivamente instrumentos musicais. Não vendemos acessórios "
    "(cordas, palhetas, cabos, cases, pedais, amplificadores).",
}

# weekday(): 0=segunda ... 6=domingo -> (abre, fecha) em horas
_HOURS = {**{d: (9, 18) for d in range(5)}, 5: (9, 13)}
_DAY_NAMES = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def _next_opening(dt: datetime) -> str:
    for i in range(0, 8):
        wd = (dt.weekday() + i) % 7
        if wd in _HOURS:
            opens, _ = _HOURS[wd]
            if i == 0 and dt.hour >= opens:
                continue  # hoje já passou do horário de abertura
            when = "hoje" if i == 0 else ("amanhã" if i == 1 else _DAY_NAMES[wd])
            return f"{when} às {opens:02d}:00"
    return "segunda às 09:00"  # inalcançável


def is_open(dt: datetime | None = None) -> dict:
    """Informa se a loja está aberta no momento (feriados não modelados)."""
    dt = dt or config.now()
    hours = _HOURS.get(dt.weekday())
    aberta = bool(hours and hours[0] <= dt.hour + dt.minute / 60 < hours[1])
    out = {"aberta_agora": aberta, "dia": _DAY_NAMES[dt.weekday()], "hora": dt.strftime("%H:%M")}
    if not aberta:
        out["proxima_abertura"] = _next_opening(dt)
    return out


def get_store_info(now: datetime | None = None) -> dict:
    return {**STORE_INFO, "status_atual": is_open(now)}


# ---------------------------------------------------------------- produtos

_STATUS_PT = {"active": "ativo", "discontinued": "descontinuado", "coming_soon": "em breve"}

# termo do cliente -> nome da categoria (comparação normalizada)
_CATEGORY_ALIASES = {
    "guitarra": "guitarras", "guitarras": "guitarras",
    "baixo": "baixos", "baixos": "baixos", "contrabaixo": "baixos",
    "bateria": "baterias e percussao", "baterias": "baterias e percussao", "percussao": "baterias e percussao",
    "teclado": "teclados e pianos", "teclados": "teclados e pianos", "piano": "teclados e pianos",
    "pianos": "teclados e pianos", "sintetizador": "teclados e pianos",
    "violao": "violoes", "violoes": "violoes",
    "ukulele": "ukuleles", "ukuleles": "ukuleles", "ukelele": "ukuleles", "cavaquinho": "ukuleles",
    "sopro": "instrumentos de sopro", "flauta": "instrumentos de sopro", "saxofone": "instrumentos de sopro",
    "clarinete": "instrumentos de sopro", "trompete": "instrumentos de sopro",
    "violino": "cordas orquestrais", "viola": "cordas orquestrais", "violoncelo": "cordas orquestrais",
}


def _match_category(store: Store, term: str | None) -> str | None:
    """Resolve o termo livre para o nome real da categoria; None se não houver match."""
    if not term:
        return None
    t = normalize(term)
    wanted = _CATEGORY_ALIASES.get(t, t)
    for name in store.categories.values():
        n = normalize(name)
        if wanted == n or wanted in n:
            return name
    return None


# Os specs misturam inglês e português ("steel", "Black", "Preto"). Para a busca,
# acrescentamos os equivalentes em português.
_SPEC_PT = {"steel": "aço", "black": "preto", "red": "vermelho", "blue": "azul", "wine red": "vinho vermelho",
            "synthesizer": "sintetizador", "natural": "natural"}


def _spec_text(p: Product) -> str:
    parts: list[str] = []
    for k, v in p.specs.items():
        sv = str(v)
        parts.append(sv)
        if sv.lower() in _SPEC_PT:
            parts.append(_SPEC_PT[sv.lower()])
        if k == "electronics" and sv == "yes":
            parts.append("eletroacustico eletrico com captacao")
    return " ".join(parts)


def _availability(p: Product) -> str:
    if p.status == "discontinued":
        return "descontinuado"
    if p.status == "coming_soon":
        return "em breve (ainda não disponível para compra)"
    return "em estoque" if p.stock > 0 else "esgotado temporariamente"


def _product_view(p: Product, detailed: bool = False) -> dict:
    price = current_price(p)
    view: dict = {
        "id": p.product_id,
        "nome": p.name,
        "categoria": p.category,
        "preco_atual": price,
        "disponibilidade": _availability(p),
    }
    if p.promotion:
        view["promocao"] = {
            "descricao": p.promotion.description,
            "desconto_percent": p.promotion.discount_percent,
            "preco_original": p.price,
        }
        view["observacao_pagamento"] = "Produto em promoção: desconto de PIX não se aplica."
    else:
        view["preco_pix_a_vista"] = pix_price(p)
    if p.status == "active" and p.stock > 0:
        view["unidades_em_estoque"] = p.stock
    if detailed:
        view["descricao"] = p.description
        view["especificacoes"] = p.specs
        view["parcelamento_cartao"] = installment_options(price)
    return view


def search_products(
    query: str | None = None,
    category: str | None = None,
    max_price: float | None = None,
    min_price: float | None = None,
    only_available: bool = True,
    limit: int = 10,
    store: Store | None = None,
) -> dict:
    """Busca no catálogo.

    - `only_available=True` (padrão) devolve só itens ativos com estoque.
    - `max_price`/`min_price` consideram o preço praticado (com promoção, sem PIX).
    - `query` é livre (marca, modelo, cor, tipo de corda...) e ignora acentos/caixa.
    """
    store = store or get_store()
    cat_name = None
    if category:
        cat_name = _match_category(store, category)
        if cat_name is None:
            return {
                "total": 0, "produtos": [],
                "aviso": f"Não trabalhamos com '{category}' no catálogo. "
                f"Categorias: {', '.join(store.categories.values())}.",
            }

    q_tokens = tokens(query) if query else []
    scored: list[tuple[int, Product]] = []
    for p in store.products.values():
        if cat_name and p.category != cat_name:
            continue
        if only_available and not (p.status == "active" and p.stock > 0):
            continue
        price = current_price(p)
        if max_price is not None and price > max_price:
            continue
        if min_price is not None and price < min_price:
            continue
        score = 0
        if q_tokens:
            haystack = normalize(" ".join([p.name, p.category, p.description, _spec_text(p)]))
            name_n = normalize(p.name)
            hits = [t for t in q_tokens if t in haystack]
            if len(hits) < len(q_tokens):  # todos os termos precisam casar
                continue
            score = sum(2 if t in name_n else 1 for t in hits)
        scored.append((score, p))

    scored.sort(key=lambda sp: (-sp[0], current_price(sp[1])))
    limit = max(1, min(limit, 25))
    return {
        "total": len(scored),
        "exibindo": min(limit, len(scored)),
        "produtos": [_product_view(p) for _, p in scored[:limit]],
    }


def get_product(name_or_id: str | int, store: Store | None = None) -> dict:
    """Detalhe de um produto por id ou nome (tolerante: 'takamine gd 20' acha 'Takamine GD20')."""
    store = store or get_store()
    s = str(name_or_id).strip()
    if s.isdigit() and int(s) in store.products:
        return _product_view(store.products[int(s)], detailed=True)

    c = compact(s)
    if not c:
        return {"erro": "Informe o nome ou o id do produto."}
    exact = [p for p in store.products.values() if c in compact(p.name)]
    if len(exact) == 1:
        return _product_view(exact[0], detailed=True)
    if len(exact) > 1:
        return {
            "erro": "Mais de um produto corresponde; peça ao cliente para especificar.",
            "candidatos": [{"id": p.product_id, "nome": p.name} for p in exact[:8]],
        }

    # fallback: todos os termos presentes no nome
    q = tokens(s)
    loose = [p for p in store.products.values() if q and all(t in normalize(p.name) for t in q)]
    if len(loose) == 1:
        return _product_view(loose[0], detailed=True)
    if loose:
        return {
            "erro": "Mais de um produto corresponde; peça ao cliente para especificar.",
            "candidatos": [{"id": p.product_id, "nome": p.name} for p in loose[:8]],
        }
    return {"erro": f"Produto '{s}' não encontrado no catálogo."}


# ---------------------------------------------------------------- pedidos

_ORDER_STATUS_PT = {
    "pending": "aguardando confirmação de pagamento",
    "confirmed": "pagamento confirmado, em preparação",
    "shipped": "enviado",
    "delivered": "entregue",
    "cancelled": "cancelado",
}
_PAYMENT_PT = {
    "pix": "PIX", "debit": "cartão de débito", "boleto": "boleto",
    "credit_3x": "crédito em 3x", "credit_6x": "crédito em 6x", "credit_12x": "crédito em 12x",
}

_NOT_FOUND = {
    "erro": "Não encontrei um pedido com esses dados. Confira o número do pedido e o "
    "e-mail ou telefone cadastrado na compra."
}


def verify_order(order_id, email, phone, store: Store):
    """Retorna (order, customer, None) se o titular foi verificado; senão (None, None, erro).

    Pedido inexistente e verificação falha retornam a MESMA mensagem para não
    permitir descobrir quais números de pedido existem (LGPD).
    """
    try:
        oid = int(str(order_id).strip().lstrip("#"))
    except ValueError:
        return None, None, dict(_NOT_FOUND)

    if not email and not phone:
        return None, None, {
            "erro": "Para consultar o pedido, preciso do e-mail ou do telefone cadastrado na compra."
        }

    order = store.orders.get(oid)
    customer = store.customers.get(order.customer_id) if order else None
    if not order or not customer:
        return None, None, dict(_NOT_FOUND)

    ok = (email and normalize_email(email) == customer.email) or (
        phone and normalize_phone(phone) == normalize_phone(customer.phone)
    )
    if not ok:
        return None, None, dict(_NOT_FOUND)
    return order, customer, None


def get_order_status(
    order_id: int | str,
    email: str | None = None,
    phone: str | None = None,
    store: Store | None = None,
) -> dict:
    """Status de pedido. Exige verificação: e-mail OU telefone do titular."""
    store = store or get_store()
    order, customer, err = verify_order(order_id, email, phone, store)
    if err:
        return err

    out: dict = {
        "pedido": order.order_id,
        "cliente": customer.name.split()[0],
        "data_do_pedido": order.order_date.isoformat(),
        "status": _ORDER_STATUS_PT.get(order.status, order.status),
        "status_codigo": order.status,
        "total": order.total,
        "forma_pagamento": _PAYMENT_PT.get(order.payment_method, order.payment_method),
        "itens": [
            {
                "produto": store.products[i.product_id].name if i.product_id in store.products else f"#{i.product_id}",
                "quantidade": i.quantity,
            }
            for i in order.items
        ],
    }
    if order.tracking_code:
        out["codigo_rastreio"] = order.tracking_code
    if order.estimated_delivery:
        out["previsao_entrega"] = order.estimated_delivery.isoformat()
    if order.notes:
        out["observacoes"] = order.notes
    return out


# ---------------------------------------------------------------- pagamento

def calculate_installments(amount: float, in_promotion: bool = False) -> dict:
    """Parcelamento e preço no PIX para um valor. `in_promotion=True` desliga o desconto de PIX."""
    if amount <= 0:
        return {"erro": "Valor inválido."}
    out = {
        "valor": round(amount, 2),
        "parcelas_cartao_sem_juros": installment_options(amount),
        "debito_ou_boleto_a_vista": round(amount, 2),
    }
    if in_promotion:
        out["pix"] = "Sem desconto adicional (promoções não acumulam com o desconto de PIX)."
    else:
        out["pix_a_vista"] = round(amount * 0.95 + 1e-9, 2)
    return out

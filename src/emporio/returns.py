"""Elegibilidade de troca/devolução (manual, seções 4 e 8).

Faz a conta de datas em código — o LLM só comunica o resultado.

Suposições (documentadas no README):
- Não há data de entrega real nos dados: para pedidos `delivered` usamos
  `estimated_delivery` como data de recebimento.
- Todos os pedidos da base são tratados como compras online (direito de
  arrependimento, 4.1). Compra presencial não tem o direito de 7 dias por lei.
- Defeito (4.2): 30 dias corridos contados da COMPRA, como diz o manual. Depois,
  vale a garantia legal de 90 dias do RECEBIMENTO (8.1), via fabricante.
- O que depende de informação que não temos (uso, embalagem, personalização,
  "venda final") vai em `confirmar_com_cliente`/`encaminhar_para_equipe`.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import config
from .data import Store, get_store
from .tools import verify_order

MOTIVOS = ("arrependimento", "defeito", "preferencia")

ARREPENDIMENTO_DIAS = 7
PREFERENCIA_DIAS = 7
DEFEITO_DIAS = 30
GARANTIA_LEGAL_DIAS = 90

_CONDICOES_COMUNS = [
    "Produto na embalagem original, sem sinais de uso, com todos os acessórios e manuais.",
    "Não pode ser instrumento personalizado/ajustado sob encomenda nem item de liquidação com aviso de 'venda final'.",
]


def _fmt(d: date) -> str:
    return d.isoformat()


def check_return_eligibility(
    order_id: int | str,
    motivo: str,
    email: str | None = None,
    phone: str | None = None,
    store: Store | None = None,
    today: date | None = None,
) -> dict:
    """Avalia se o pedido pode ser devolvido/trocado pelo motivo informado.

    motivo: 'arrependimento' | 'defeito' | 'preferencia'.
    Exige verificação do titular (e-mail OU telefone), como get_order_status.
    """
    store = store or get_store()
    today = today or config.today()
    motivo = (motivo or "").strip().lower()
    if motivo not in MOTIVOS:
        return {"erro": f"motivo deve ser um de: {', '.join(MOTIVOS)}."}

    order, customer, err = verify_order(order_id, email, phone, store)
    if err:
        return err

    base = {
        "pedido": order.order_id,
        "motivo": motivo,
        "status_pedido": order.status,
        "data_de_hoje": _fmt(today),
        "data_da_compra": _fmt(order.order_date),
    }

    # ----- pedidos que ainda não foram recebidos
    if order.status == "cancelled":
        return {**base, "elegivel": False, "situacao": "pedido_cancelado",
                "explicacao": "O pedido já está cancelado, então não há o que devolver."
                + (f" Motivo registrado: {order.notes}." if order.notes else "")}
    if order.status in ("pending", "confirmed"):
        return {**base, "elegivel": None, "situacao": "ainda_nao_enviado",
                "explicacao": "O pedido ainda não foi enviado, então ainda não há devolução. "
                "O manual não define cancelamento de pedido em andamento: encaminhar para a equipe.",
                "encaminhar_para_equipe": True}
    if order.status == "shipped":
        return {**base, "elegivel": None, "situacao": "em_transito",
                "explicacao": "O pedido está a caminho. Os prazos de devolução só começam a contar "
                "a partir do recebimento (7 dias corridos para arrependimento). "
                "Se chegar avariado, recusar o recebimento e avisar a loja imediatamente.",
                "previsao_entrega": _fmt(order.estimated_delivery) if order.estimated_delivery else None}

    # ----- entregue
    received = order.estimated_delivery or order.order_date
    base["data_de_recebimento_considerada"] = _fmt(received)
    base["observacao_dados"] = "Sem data real de entrega nos dados; usamos a previsão de entrega como recebimento."
    days_since_received = (today - received).days

    if motivo in ("arrependimento", "preferencia"):
        limit = received + timedelta(days=ARREPENDIMENTO_DIAS if motivo == "arrependimento" else PREFERENCIA_DIAS)
        ok = today <= limit
        out = {
            **base,
            "elegivel": ok,
            "regra": "4.1 Direito de Arrependimento" if motivo == "arrependimento" else "4.3 Troca por Preferência",
            "prazo_limite": _fmt(limit),
            "dias_desde_recebimento": days_since_received,
            "situacao": "dentro_do_prazo" if ok else "prazo_expirado",
        }
        if ok:
            out["dias_restantes"] = (limit - today).days
            out["confirmar_com_cliente"] = _CONDICOES_COMUNS
            if motivo == "arrependimento":
                out["como_funciona"] = ("Reembolso na mesma forma de pagamento em até 10 dias úteis; "
                                        "frete de devolução por conta da loja.")
            else:
                out["como_funciona"] = ("Troca sujeita à disponibilidade do produto desejado; "
                                        "diferença de valor cobrada ou reembolsada.")
        else:
            out["dias_de_atraso"] = (today - limit).days
            out["alternativas"] = [
                "Se houver defeito de fabricação, a garantia legal de 90 dias do recebimento ainda pode valer."
                if days_since_received <= GARANTIA_LEGAL_DIAS else
                "Garantia legal de 90 dias também já expirou; resta a garantia do fabricante, se houver.",
                "Caso queira insistir, encaminhar para a equipe/gerência avaliar.",
            ]
        return out

    # defeito
    limit_loja = order.order_date + timedelta(days=DEFEITO_DIAS)
    limit_legal = received + timedelta(days=GARANTIA_LEGAL_DIAS)
    na_loja = today <= limit_loja
    out = {
        **base,
        "regra": "4.2 Trocas por Defeito",
        "elegivel": na_loja,
        "prazo_limite_troca_na_loja": _fmt(limit_loja),
        "situacao": "troca_na_loja" if na_loja else "prazo_de_troca_expirado",
        "confirmar_com_cliente": [
            "Descrever o defeito. Mau uso, queda, umidade excessiva ou modificações não autorizadas não são cobertos.",
        ],
    }
    if na_loja:
        out["dias_restantes"] = (limit_loja - today).days
    else:
        out["dias_de_atraso"] = (today - limit_loja).days
        if today <= limit_legal:
            out["garantia_legal_vigente_ate"] = _fmt(limit_legal)
            out["proximo_passo"] = ("Acionar a garantia com o fabricante (garantia legal de 90 dias ainda vigente); "
                                    "a loja pode intermediar mediante solicitação.")
        else:
            out["proximo_passo"] = ("Garantia legal de 90 dias expirada; verificar o certificado de garantia do "
                                    "fabricante. A loja pode intermediar mediante solicitação.")
    return out

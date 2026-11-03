from datetime import datetime

import pytest

from emporio import tools
from emporio.config import TZ
from emporio.data import get_store
from emporio.pricing import current_price, installment_options, pix_price

S = get_store()


# ---------------------------------------------------------------- dados

def test_carga_e_tratamento():
    assert len(S.products) == 65
    assert S.products[95].specs["strings"] == "steel"  # JSON parseado
    assert S.products[95].category == "Violões"
    # só promoções ativas: 102 (Black Friday) está inativa, 127 ativa
    assert S.products[102].promotion is None
    assert S.products[127].promotion.discount_percent == 10


# ---------------------------------------------------------------- preços

def test_preco_promocional_e_sem_pix():
    p = S.products[127]  # Kalani KAL-700T, R$359 com 10%
    assert current_price(p) == pytest.approx(323.10)
    assert pix_price(p) is None


def test_pix_5_por_cento_sem_promocao():
    assert pix_price(S.products[95]) == pytest.approx(2089.05)  # 2199 * 0.95


def test_parcelamento_respeita_minimos():
    opts = {o["parcelas"] for o in installment_options(1000)}
    assert 12 not in opts  # 83,33 < R$100
    assert 10 in opts  # 100,00 >= R$100
    assert max(opts) == 10
    assert installment_options(60)[-1]["parcelas"] == 1  # 2x = 30 < 50


# ---------------------------------------------------------------- busca

def test_violoes_ate_1000_em_estoque():
    r = tools.search_products(category="violões", max_price=1000)
    assert r["total"] > 0
    for p in r["produtos"] + tools.search_products(category="violão", max_price=1000, limit=25)["produtos"]:
        assert p["categoria"] == "Violões"
        assert p["preco_atual"] <= 1000
        assert p["disponibilidade"] == "em estoque"


def test_busca_exclui_esgotado_e_descontinuado_por_padrao():
    ids = {p["id"] for p in tools.search_products(category="violão", limit=25)["produtos"]}
    assert 96 not in ids  # estoque 0
    assert 113 not in ids  # descontinuado
    ids_all = {p["id"] for p in tools.search_products(category="violão", only_available=False, limit=25)["produtos"]}
    assert {96, 113} <= ids_all


def test_acessorio_nao_vendido():
    r = tools.search_products(category="cordas")
    assert r["total"] == 0 or "aviso" in r
    r2 = tools.search_products(category="pedal")
    assert r2["total"] == 0 and "aviso" in r2


def test_preco_filtrado_usa_valor_promocional():
    # Kalani 700T: 359 de tabela, 323,10 promocional -> entra em "até 330"
    ids = {p["id"] for p in tools.search_products(category="ukulele", max_price=330, limit=25)["produtos"]}
    assert 127 in ids


@pytest.mark.parametrize("q", ["Takamine GD20", "takamine gd 20", "TAKAMINE GD-20", "gd20"])
def test_get_product_tolerante(q):
    r = tools.get_product(q)
    assert r["id"] == 95
    assert r["preco_atual"] == 2199
    assert r["preco_pix_a_vista"] == pytest.approx(2089.05)
    assert "parcelamento_cartao" in r


def test_get_product_ambiguo_e_inexistente():
    assert "candidatos" in tools.get_product("Yamaha")
    assert "erro" in tools.get_product("Stradivarius 9000")


def test_get_product_descontinuado_marcado():
    assert tools.get_product(113)["disponibilidade"] == "descontinuado"


# ---------------------------------------------------------------- pedidos

def test_pedido_verificado_por_email():
    r = tools.get_order_status(1, email="PEDRO.OLIVEIRA@jmail.com")  # cliente 3
    assert r["status_codigo"] == "delivered"
    assert r["cliente"] == "Pedro"
    assert r["codigo_rastreio"] == "BRAB1234567BR"
    assert r["itens"][0]["produto"] == "Martin D-28 Dreadnought Natural"


def test_pedido_verificado_por_telefone():
    r = tools.get_order_status("#1", phone="67 98432-1098")
    assert r["pedido"] == 1


def test_pedido_de_outro_cliente_negado():
    r = tools.get_order_status(1, email="lucas.mendes@jmail.com")  # e-mail de outro cliente
    assert "erro" in r and "pedido" not in r


def test_inexistente_igual_a_verificacao_falha():
    a = tools.get_order_status(999, email="lucas.mendes@jmail.com")
    b = tools.get_order_status(1, email="lucas.mendes@jmail.com")
    assert a == b


def test_pedido_sem_verificacao():
    assert "erro" in tools.get_order_status(1)


def test_pedido_cancelado_traz_motivo():
    r = tools.get_order_status(17, email=S.customers[15].email)
    assert r["status_codigo"] == "cancelled"
    assert "observacoes" in r


# ---------------------------------------------------------------- loja

def test_horario():
    seg_10h = datetime(2026, 11, 2, 10, 0, tzinfo=TZ)
    sab_14h = datetime(2026, 11, 7, 14, 0, tzinfo=TZ)
    dom = datetime(2026, 11, 8, 11, 0, tzinfo=TZ)
    sex_19h = datetime(2026, 11, 6, 19, 0, tzinfo=TZ)
    assert tools.is_open(seg_10h)["aberta_agora"]
    assert not tools.is_open(sab_14h)["aberta_agora"]
    assert tools.is_open(sab_14h)["proxima_abertura"] == "segunda às 09:00"
    assert tools.is_open(dom)["proxima_abertura"] == "amanhã às 09:00"
    assert tools.is_open(sex_19h)["proxima_abertura"] == "amanhã às 09:00"  # sábado abre 9h


def test_calculo_parcelas_promocao():
    assert "pix" in tools.calculate_installments(500, in_promotion=True)
    assert tools.calculate_installments(1000)["pix_a_vista"] == 950


def test_busca_por_termo_em_portugues_acha_spec_em_ingles():
    r = tools.search_products(query="aço", category="violão", limit=25)
    assert r["total"] > 0
    ids = {p["id"] for p in r["produtos"]}
    assert 92 in ids and 82 not in ids  # FG800 (steel) sim; C70 (nylon) não

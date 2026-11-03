from datetime import date

from emporio.data import get_store
from emporio.returns import check_return_eligibility as chk

S = get_store()
EMAIL14 = S.customers[14].email  # dono do pedido 7 (entregue, previsão 2026-02-17)


def test_arrependimento_dentro_do_prazo():
    r = chk(7, "arrependimento", email=EMAIL14, today=date(2026, 2, 20))
    assert r["elegivel"] is True
    assert r["prazo_limite"] == "2026-02-24"
    assert r["dias_restantes"] == 4
    assert "confirmar_com_cliente" in r


def test_arrependimento_ultimo_dia_vale_e_dia_seguinte_nao():
    assert chk(7, "arrependimento", email=EMAIL14, today=date(2026, 2, 24))["elegivel"] is True
    r = chk(7, "arrependimento", email=EMAIL14, today=date(2026, 2, 25))
    assert r["elegivel"] is False and r["dias_de_atraso"] == 1


def test_arrependimento_expirado_aponta_garantia():
    r = chk(7, "arrependimento", email=EMAIL14, today=date(2026, 3, 10))
    assert r["elegivel"] is False
    assert any("garantia legal" in a.lower() for a in r["alternativas"])


def test_defeito_na_loja_ate_30_dias_da_compra():
    # compra 2026-02-03 -> limite 2026-03-05
    assert chk(7, "defeito", email=EMAIL14, today=date(2026, 3, 5))["elegivel"] is True
    r = chk(7, "defeito", email=EMAIL14, today=date(2026, 3, 10))
    assert r["elegivel"] is False
    assert r["garantia_legal_vigente_ate"] == "2026-05-18"  # 90 dias do recebimento (02-17)


def test_defeito_depois_da_garantia_legal():
    r = chk(7, "defeito", email=EMAIL14, today=date(2026, 8, 1))
    assert r["elegivel"] is False and "garantia_legal_vigente_ate" not in r
    assert "fabricante" in r["proximo_passo"]


def test_preferencia_usa_7_dias():
    assert chk(7, "preferencia", email=EMAIL14, today=date(2026, 2, 24))["elegivel"] is True
    assert chk(7, "preferencia", email=EMAIL14, today=date(2026, 2, 26))["elegivel"] is False


def test_pedido_cancelado():
    r = chk(17, "arrependimento", email=S.customers[15].email, today=date(2026, 3, 1))
    assert r["elegivel"] is False and r["situacao"] == "pedido_cancelado"


def test_pedido_em_transito_e_nao_enviado():
    r = chk(8, "arrependimento", email=S.customers[2].email, today=date(2026, 3, 1))
    assert r["situacao"] == "em_transito" and r["elegivel"] is None
    r = chk(9, "arrependimento", email=S.customers[6].email, today=date(2026, 3, 1))
    assert r["situacao"] == "ainda_nao_enviado" and r["encaminhar_para_equipe"]


def test_exige_verificacao_do_titular():
    r = chk(7, "arrependimento", email="outro@jmail.com", today=date(2026, 2, 20))
    assert "erro" in r and "elegivel" not in r
    assert "erro" in chk(7, "arrependimento", today=date(2026, 2, 20))


def test_motivo_invalido():
    assert "erro" in chk(7, "porque sim", email=EMAIL14)

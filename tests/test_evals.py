"""Testes offline do conjunto de avaliação: casos coerentes e avaliador correto."""
import re
from types import SimpleNamespace as NS

from emporio.agent import TOOL_SCHEMAS, Agent
from evals.cases import CASES, Case, money
from evals.run_evals import evaluate, run_case

TOOLS = {t["name"] for t in TOOL_SCHEMAS}


def test_casos_bem_formados():
    assert len(CASES) >= 20
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))
    for c in CASES:
        assert c.turns, c.id
        assert set(c.tools_any + c.tools_none) <= TOOLS, c.id
        for pat in c.contains + c.not_contains:
            re.compile(pat)  # regex válido


def test_money_aceita_formatos_comuns():
    for txt in ("r$ 2.199,00", "r$2199", "2.199", "2199,00"):
        assert re.search(money(2199), txt), txt
    assert re.search(money(2089.05), "fica r$ 2.089,05 no pix")
    assert not re.search(money(2089.05), "r$ 2.089,50")


def test_avaliador():
    c = Case("x", "d", ["q"], tools_any=["get_product"], tools_none=["get_order_status"],
             contains=[r"2\.?199"], not_contains=[r"martin"])
    assert evaluate(c, ["get_product"], "custa R$ 2.199,00") == []
    assert len(evaluate(c, [], "custa R$ 2.199,00")) == 1  # faltou ferramenta
    assert len(evaluate(c, ["get_product", "get_order_status"], "R$ 2.199")) == 1
    assert len(evaluate(c, ["get_product"], "o Martin custa 2.199")) == 1  # texto proibido
    assert evaluate(c, ["get_product"], "R$ 2.199")  == []


def test_acentos_sao_ignorados_na_resposta():
    c = Case("x", "d", ["q"], contains=[r"nao trabalhamos"])
    assert evaluate(c, [], "Não trabalhamos com isso") == []


def test_run_case_com_cliente_falso(monkeypatch):
    class Fake:
        def __init__(self):
            self.messages = self
            self.n = 0

        def create(self, **kw):
            self.n += 1
            if self.n == 1:
                return NS(content=[NS(type="tool_use", id="t", name="get_product", input={"name_or_id": "Takamine GD20"})])
            return NS(content=[NS(type="text", text="O Takamine GD20 custa R$ 2.199,00.")])

    case = next(c for c in CASES if c.id == "preco_takamine")
    r = run_case(case, lambda: Agent(client=Fake()))
    assert r["fails"] == [] and r["called"] == ["get_product"]


def test_run_case_restaura_data_de_referencia(monkeypatch):
    import os

    monkeypatch.delenv("EMPORIO_TODAY", raising=False)
    case = Case("x", "d", ["oi"], today="2026-02-20")

    class Fake:
        messages = None

        def __init__(self):
            self.messages = self

        def create(self, **kw):
            assert os.environ["EMPORIO_TODAY"] == "2026-02-20"
            return NS(content=[NS(type="text", text="oi")])

    run_case(case, lambda: Agent(client=Fake()))
    assert "EMPORIO_TODAY" not in os.environ

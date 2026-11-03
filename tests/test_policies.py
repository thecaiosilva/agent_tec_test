import pytest

from emporio import policies
from emporio.policies import get_index, load_chunks, search_policies


def test_chunking_cobre_manual():
    secoes = {c.section for c in load_chunks()}
    assert {"2", "3.1", "4.1", "4.2", "4.3", "4.4", "5.1", "5.2", "5.3", "6.2", "7.1", "7.3", "8.1", "9"} <= secoes
    # cabeçalho/rodapé de página não vazam
    assert all("Página" not in c.text and "Manual de Políticas" not in c.text for c in load_chunks())
    # lista numerada do fluxo (7.2) não vira seções
    assert not {"1.", "2.", "3."} & secoes
    # seção que atravessa a página (5.2 começa no fim da pág. 4) fica inteira
    c52 = next(c for c in load_chunks() if c.section == "5.2")
    assert "Jadlog" in c52.text and "SEDEX" in c52.text


def test_sem_artefatos_de_lista():
    c = next(c for c in load_chunks() if c.section == "4.1")
    assert c.text.startswith("• O cliente pode solicitar")


# (pergunta, seção esperada entre os 3 primeiros resultados)
CASOS = [
    ("Me arrependi da minha compra, posso devolver meu pedido?", "4.1"),
    ("quantos dias tenho para devolver?", "4.1"),
    ("o instrumento chegou com defeito, e agora?", "4.2"),
    ("posso trocar a cor do violão?", "4.3"),
    ("quais produtos não podem ser trocados?", "4.4"),
    ("qual o horário de funcionamento no sábado?", "2"),
    ("vocês abrem domingo?", "2"),
    ("qual o endereço da loja?", "1.2"),
    ("qual o telefone de vocês?", "1.2"),
    ("posso parcelar em 12x?", "3.1"),
    ("quais formas de pagamento vocês aceitam?", "3"),
    ("tem desconto no pix?", "3"),
    ("o frete é grátis?", "5.1"),
    ("quanto tempo demora a entrega para Dourados?", "5.2"),
    ("como rastrear meu pedido?", "5.3"),
    ("quando é a black friday?", "6.1"),
    ("posso somar o desconto do pix com a promoção?", "6.2"),
    ("vocês vendem cordas e palhetas?", "1"),
    ("como funciona a garantia?", "8.1"),
    ("quero excluir meus dados", "9"),
    ("quero fazer uma reclamação", "7.3"),
]


@pytest.mark.parametrize("pergunta,esperada", CASOS)
def test_recuperacao(pergunta, esperada):
    hits = get_index().search(pergunta, top_k=3)
    secoes = [c.section for c, _ in hits]
    assert esperada in secoes, f"{pergunta!r} -> {secoes}"


def test_fora_do_dominio_nao_retorna_nada():
    r = search_policies("qual a capital da França?")
    assert r["trechos"] == [] and "aviso" in r


def test_tool_inclui_observacao_de_parcelamento():
    r = search_policies("parcelamento em 12x")
    t = {x["secao"]: x for x in r["trechos"]}
    assert "3.1" in t and "observacao_interna" in t["3.1"]


def test_consulta_vazia():
    assert "erro" in search_policies("  ")

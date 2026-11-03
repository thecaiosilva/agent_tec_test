"""Testes do loop do agente com um cliente LLM falso (sem rede)."""
import copy
from types import SimpleNamespace as NS

from emporio import agent as agent_mod
from emporio.agent import FALLBACK, TOOL_SCHEMAS, Agent, run_tool
from emporio.data import get_store


def text(t):
    return NS(type="text", text=t)


def use(id_, name, **inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


class FakeClient:
    """Responde em sequência; guarda as chamadas recebidas."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(copy.deepcopy(kw))  # snapshot: a lista de mensagens é mutada depois
        return NS(content=self.responses.pop(0))


def test_resposta_sem_ferramenta():
    a = Agent(client=FakeClient([text("Fala! Como posso ajudar?")]))
    assert a.chat("oi") == "Fala! Como posso ajudar?"
    assert a.last_calls == []


def test_loop_executa_ferramenta_e_devolve_resultado_ao_modelo():
    fake = FakeClient(
        [use("t1", "get_product", name_or_id="Takamine GD20")],
        [text("O Takamine GD20 custa R$ 2.199,00.")],
    )
    a = Agent(client=fake)
    assert "2.199" in a.chat("quanto custa o Takamine GD20?")
    assert a.last_calls[0].result["preco_atual"] == 2199
    # 2ª chamada ao modelo carrega o tool_result
    last = fake.calls[1]["messages"][-1]
    assert last["role"] == "user" and last["content"][0]["type"] == "tool_result"
    assert last["content"][0]["tool_use_id"] == "t1"
    assert "2199" in last["content"][0]["content"]


def test_prompt_cacheavel_e_ferramentas_enviadas():
    fake = FakeClient([text("ok")])
    Agent(client=fake).chat("oi")
    kw = fake.calls[0]
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["tools"] == TOOL_SCHEMAS


def test_ferramenta_inexistente_e_argumento_invalido_nao_derrubam():
    assert "erro" in run_tool("apagar_tudo", {})
    assert "erro" in run_tool("get_product", {})  # falta argumento obrigatório
    # modelo não consegue injetar parâmetros internos
    r = run_tool("get_order_status", {"order_id": "1", "email": "x@x.com", "store": "hack"})
    assert "erro" in r


def test_limite_de_passos():
    loop = [use("t", "get_store_info")]
    a = Agent(client=FakeClient(*[loop for _ in range(agent_mod.MAX_STEPS)]))
    assert a.chat("oi") == FALLBACK
    assert a.messages[-1]["role"] == "assistant"  # turno fechado de forma consistente


def test_erro_da_api_nao_corrompe_historico():
    class Boom:
        messages = None

        def __init__(self):
            self.messages = self

        def create(self, **kw):
            raise RuntimeError("rede")

    a = Agent(client=Boom())
    try:
        a.chat("oi")
    except RuntimeError:
        pass
    assert a.messages == []


def test_pedido_de_outro_cliente_via_agente_nao_vaza():
    s = get_store()
    fake = FakeClient(
        [use("t1", "get_order_status", order_id="1", email=s.customers[1].email)],
        [text("Não encontrei esse pedido com esses dados.")],
    )
    a = Agent(client=fake)
    a.chat("status do pedido 1")
    assert "erro" in a.last_calls[0].result and "itens" not in a.last_calls[0].result


def test_reset():
    a = Agent(client=FakeClient([text("oi")]))
    a.chat("oi")
    a.reset()
    assert a.messages == []

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


# ---------------------------------------------------------------- janela e persistência

def _turno(i):
    return [
        {"role": "user", "content": f"msg{i}"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": "get_store_info", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "{}"}]},
        {"role": "assistant", "content": [{"type": "text", "text": f"r{i}"}]},
    ]


def test_janela_corta_so_em_mensagem_do_cliente():
    msgs = [m for i in range(5) for m in _turno(i)]
    w = agent_mod.window(msgs, max_turns=2)
    assert w[0] == {"role": "user", "content": "msg3"}  # nunca começa num tool_result
    assert len(w) == 8
    assert agent_mod.window(msgs, max_turns=10) is msgs


def test_sessao_salva_e_retoma(tmp_path):
    from emporio import sessions

    a = Agent(client=FakeClient([use("t1", "get_store_info")], [text("Abrimos às 9h.")]))
    a.chat("que horas abrem?")
    sessions.save("s1", a.messages, tmp_path)
    b = Agent(client=FakeClient([text("De nada!")]))
    b.messages = sessions.load("s1", tmp_path)
    assert b.chat("valeu") == "De nada!"
    assert b.messages[0]["content"] == "que horas abrem?" and len(b.messages) == 6


def test_sessao_inexistente_ou_corrompida(tmp_path):
    from emporio import sessions

    assert sessions.load("nao-existe", tmp_path) == []
    (tmp_path / "ruim.json").write_text("{quebrado", encoding="utf-8")
    assert sessions.load("ruim", tmp_path) == []


def test_id_de_sessao_nao_escapa_do_diretorio(tmp_path):
    from emporio import sessions

    p = sessions.save("../../fora", [], tmp_path)
    assert p.parent == tmp_path


# ---------------------------------------------------------------- provedor OpenAI

def _openai_resp(content=None, calls=()):
    msg = NS(content=content, tool_calls=[
        NS(id=i, function=NS(name=n, arguments=a)) for i, n, a in calls
    ] or None)
    return NS(choices=[NS(message=msg)])


class FakeOpenAI:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.chat = NS(completions=self)

    def create(self, **kw):
        self.calls.append(copy.deepcopy(kw))
        return self.responses.pop(0)


def test_openai_adapter_roda_o_loop_completo():
    from emporio.llm import OpenAIAdapter

    fake = FakeOpenAI(
        _openai_resp(calls=[("c1", "get_product", '{"name_or_id": "Takamine GD20"}')]),
        _openai_resp(content="O GD20 custa R$ 2.199,00."),
    )
    a = Agent(client=OpenAIAdapter(fake), model="gpt-x")
    assert "2.199" in a.chat("quanto custa o Takamine GD20?")
    assert a.last_calls[0].result["preco_atual"] == 2199

    first, second = fake.calls
    assert first["model"] == "gpt-x" and first["max_completion_tokens"] == agent_mod.MAX_TOKENS
    assert first["messages"][0]["role"] == "system" and "Léo" in first["messages"][0]["content"]
    assert first["tools"][0]["type"] == "function" and "parameters" in first["tools"][0]["function"]
    # 2ª chamada: assistente com tool_calls + resposta role=tool com o mesmo id
    roles = [m["role"] for m in second["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert second["messages"][2]["tool_calls"][0]["id"] == "c1"
    assert second["messages"][3]["tool_call_id"] == "c1"


def test_openai_argumentos_invalidos_viram_erro_recuperavel():
    from emporio.llm import OpenAIAdapter

    fake = FakeOpenAI(_openai_resp(calls=[("c1", "get_product", "{quebrado")]), _openai_resp(content="ok"))
    a = Agent(client=OpenAIAdapter(fake))
    assert a.chat("oi") == "ok"
    assert "erro" in a.last_calls[0].result


def test_openai_historico_salvo_no_formato_anthropic_e_reaproveitavel():
    from emporio.llm import OpenAIAdapter, to_openai_messages

    a = Agent(client=OpenAIAdapter(FakeOpenAI(
        _openai_resp(calls=[("c1", "get_store_info", "{}")]), _openai_resp(content="Abrimos às 9h."))))
    a.chat("horário?")
    assert a.messages[1]["content"][0]["type"] == "tool_use"  # histórico neutro (formato Anthropic)
    assert [m["role"] for m in to_openai_messages("sys", a.messages)] == ["system", "user", "assistant", "tool", "assistant"]


def test_escolha_do_provedor(monkeypatch):
    from emporio import llm

    for v in ("EMPORIO_PROVIDER", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "EMPORIO_MODEL"):
        monkeypatch.delenv(v, raising=False)
    assert llm.provider_name() == "anthropic"
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert llm.provider_name() == "openai" and llm.default_model() == "gpt-4o-mini"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    assert llm.provider_name() == "anthropic"  # Anthropic tem prioridade quando as duas existem
    monkeypatch.setenv("EMPORIO_PROVIDER", "openai")
    assert llm.provider_name() == "openai"
    monkeypatch.setenv("EMPORIO_MODEL", "meu-modelo")
    assert llm.default_model() == "meu-modelo"
    monkeypatch.setenv("EMPORIO_PROVIDER", "foo")
    import pytest
    with pytest.raises(RuntimeError):
        llm.provider_name()


def test_chave_ausente_gera_mensagem_clara(monkeypatch):
    import pytest
    from emporio import llm

    for v in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("EMPORIO_PROVIDER", "openai")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        llm.get_client()

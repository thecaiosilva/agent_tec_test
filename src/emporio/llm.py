"""Camada de acesso ao provedor de LLM.

O agente fala o formato de mensagens da Anthropic (blocos `text`, `tool_use`,
`tool_result`) e o histórico salvo em disco usa esse mesmo formato. Cada provedor
expõe a interface `client.messages.create(model, max_tokens, system, tools, messages)`
e devolve um objeto com `.content` (blocos). Para a Anthropic é o próprio SDK;
para a OpenAI (e qualquer API compatível) há um adaptador que traduz os formatos.

Escolha do provedor: `EMPORIO_PROVIDER=anthropic|openai`. Sem ela, usa o que tiver
chave definida (Anthropic primeiro).
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace as NS

DEFAULT_MODELS = {"anthropic": "claude-haiku-5-5", "openai": "gpt-4o-mini"}
PROVIDERS = tuple(DEFAULT_MODELS)


def provider_name() -> str:
    explicit = os.getenv("EMPORIO_PROVIDER", "").strip().lower()
    if explicit:
        if explicit not in PROVIDERS:
            raise RuntimeError(f"EMPORIO_PROVIDER inválido: '{explicit}'. Use: {', '.join(PROVIDERS)}.")
        return explicit
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "anthropic"  # sem chave nenhuma: get_client() explica o que falta


def default_model() -> str:
    return os.getenv("EMPORIO_MODEL", "").strip() or DEFAULT_MODELS[provider_name()]


def get_client():
    provider = provider_name()
    if provider == "anthropic":
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY não definida. Copie .env.example para .env e preencha "
                "(ou use EMPORIO_PROVIDER=openai com OPENAI_API_KEY)."
            )
        import anthropic  # import tardio: ferramentas/testes não exigem o SDK

        return anthropic.Anthropic()

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY não definida. Copie .env.example para .env e preencha.")
    import openai

    # OPENAI_BASE_URL (lida pelo próprio SDK) aponta para APIs compatíveis: Gemini, Groq, OpenRouter, Ollama...
    return OpenAIAdapter(openai.OpenAI())


# ---------------------------------------------------------------- OpenAI

def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {"type": "function",
         "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
        for t in tools
    ]


def to_openai_messages(system: list[dict] | str, messages: list[dict]) -> list[dict]:
    """Histórico no formato Anthropic -> formato Chat Completions."""
    sys_text = system if isinstance(system, str) else "\n\n".join(b["text"] for b in system)
    out: list[dict] = [{"role": "system", "content": sys_text}]
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
        elif m["role"] == "assistant":
            text = "".join(b["text"] for b in content if b["type"] == "text")
            calls = [
                {"id": b["id"], "type": "function",
                 "function": {"name": b["name"], "arguments": json.dumps(b["input"], ensure_ascii=False)}}
                for b in content if b["type"] == "tool_use"
            ]
            msg: dict = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:  # user com blocos: tool_result (um `tool` por resultado) e/ou texto
            for b in content:
                if b["type"] == "tool_result":
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
                elif b["type"] == "text":
                    out.append({"role": "user", "content": b["text"]})
    return out


class OpenAIAdapter:
    """Expõe `messages.create(...)` no estilo Anthropic sobre o SDK da OpenAI."""

    def __init__(self, client):
        self._client = client
        self.messages = self

    def create(self, *, model, max_tokens, system, messages, tools=None, **_ignored):
        kwargs = {"tools": to_openai_tools(tools)} if tools else {}  # a API recusa lista vazia
        resp = self._client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            messages=to_openai_messages(system, messages),
            **kwargs,
        )
        msg = resp.choices[0].message
        blocks = []
        if msg.content:
            blocks.append(NS(type="text", text=msg.content))
        for call in msg.tool_calls or []:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}  # a ferramenta devolve um erro de argumento e o modelo se corrige
            blocks.append(NS(type="tool_use", id=call.id, name=call.function.name, input=args))
        return NS(content=blocks)


# ---------------------------------------------------------------- teste de fumaça

def smoke_test() -> str:
    """Uma chamada mínima para validar chave, modelo e conectividade."""
    resp = get_client().messages.create(
        model=default_model(),
        max_tokens=50,
        system=[{"type": "text", "text": "Você é um assistente prestativo."}],
        messages=[{"role": "user", "content": "Responda apenas: olá!"}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")

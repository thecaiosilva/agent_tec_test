"""Agente: loop de function calling sobre as ferramentas da loja."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from . import config, tools
from .policies import search_policies
from .prompts import SYSTEM_PROMPT, dynamic_context
from .returns import check_return_eligibility

MAX_STEPS = 6  # idas e voltas modelo<->ferramentas por mensagem do cliente
MAX_TOKENS = 1024
MAX_TURNS = 20  # mensagens do cliente mantidas na janela enviada ao modelo
FALLBACK = (
    "Desculpa, tive um probleminha aqui para finalizar sua consulta. "
    "Pode repetir ou, se preferir, chamar a nossa equipe pelo WhatsApp (67) 3321-4500?"
)

# ---------------------------------------------------------------- ferramentas

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "search_products",
        "description": (
            "Busca instrumentos no catálogo com filtros. Use para 'quais violões até R$1000?', 'tem guitarra?', "
            "'algo para iniciante'. Por padrão só devolve itens ativos e em estoque. Preços já consideram promoção ativa. "
            "Se a categoria não existir (ex.: cordas, pedais), o retorno traz um aviso."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Termos livres: marca, modelo, cor, tipo de corda (ex.: 'yamaha', 'aço', 'sunburst')."},
                "category": {"type": "string", "description": "Tipo de instrumento: guitarra, baixo, bateria, teclado, violão, ukulele, sopro, cordas orquestrais."},
                "max_price": {"type": "number", "description": "Preço máximo em R$ (preço praticado, com promoção)."},
                "min_price": {"type": "number", "description": "Preço mínimo em R$."},
                "only_available": {"type": "boolean", "description": "true (padrão) = só itens à venda e em estoque; false para incluir esgotados/descontinuados."},
                "limit": {"type": "integer", "description": "Máximo de resultados (padrão 10)."},
            },
        },
    },
    {
        "name": "get_product",
        "description": (
            "Detalhes de UM produto por nome ou id: preço atual, promoção, preço no PIX, parcelamento, especificações e "
            "disponibilidade. Use para 'quanto custa o Takamine GD20?'. Se houver ambiguidade, devolve candidatos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name_or_id": {"type": "string", "description": "Nome (ou parte) do produto, ou id."}},
            "required": ["name_or_id"],
        },
    },
    {
        "name": "get_order_status",
        "description": (
            "Status de um pedido: situação, itens, rastreio, previsão de entrega. EXIGE verificação do titular: "
            "número do pedido + e-mail OU telefone cadastrado. Nunca chame sem esses dados."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Número do pedido."},
                "email": {"type": "string", "description": "E-mail cadastrado na compra."},
                "phone": {"type": "string", "description": "Telefone cadastrado na compra."},
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "check_return_eligibility",
        "description": (
            "Avalia se um pedido pode ser devolvido ou trocado, calculando os prazos. Use quando o cliente quiser devolver, "
            "trocar ou reclamar de defeito de um pedido. Mesma verificação de titular do get_order_status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Número do pedido."},
                "motivo": {
                    "type": "string",
                    "enum": list(("arrependimento", "defeito", "preferencia")),
                    "description": "arrependimento = desistiu da compra; defeito = problema de fabricação; preferencia = quer outra cor/modelo.",
                },
                "email": {"type": "string"},
                "phone": {"type": "string"},
            },
            "required": ["order_id", "motivo"],
        },
    },
    {
        "name": "search_policies",
        "description": (
            "Consulta as políticas da loja: trocas e devoluções, frete e prazos de entrega, formas de pagamento e "
            "parcelamento, promoções, garantia, privacidade (LGPD), diretrizes de atendimento. Use para regras gerais, "
            "não para dados de pedido ou produto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "A dúvida em linguagem natural."}},
            "required": ["query"],
        },
    },
    {
        "name": "get_store_info",
        "description": "Endereço, telefone/WhatsApp, e-mail, horários de funcionamento e se a loja está aberta agora.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "calculate_installments",
        "description": "Parcelas no cartão (sem juros, respeitando mínimos) e valor no PIX para um valor em R$.",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "Valor em R$."},
                "in_promotion": {"type": "boolean", "description": "true se o produto está em promoção (PIX sem desconto adicional)."},
            },
            "required": ["amount"],
        },
    },
]

_REGISTRY: dict[str, Callable[..., dict]] = {
    "search_products": tools.search_products,
    "get_product": tools.get_product,
    "get_order_status": tools.get_order_status,
    "check_return_eligibility": check_return_eligibility,
    "search_policies": search_policies,
    "get_store_info": tools.get_store_info,
    "calculate_installments": tools.calculate_installments,
}
_ALLOWED = {s["name"]: set(s["input_schema"].get("properties", {})) for s in TOOL_SCHEMAS}


def run_tool(name: str, args: dict[str, Any] | None) -> dict:
    """Executa uma ferramenta de forma defensiva: argumentos fora do schema são descartados
    (o modelo não consegue, p. ex., injetar `store`/`today`) e exceções viram {"erro": ...}."""
    fn = _REGISTRY.get(name)
    if fn is None:
        return {"erro": f"Ferramenta desconhecida: {name}"}
    clean = {k: v for k, v in (args or {}).items() if k in _ALLOWED[name]}
    try:
        return fn(**clean)
    except Exception as e:  # noqa: BLE001 — o modelo deve conseguir se recuperar
        return {"erro": f"Falha ao executar {name}: {type(e).__name__}: {e}"}


# ---------------------------------------------------------------- agente

@dataclass
class ToolCall:
    name: str
    args: dict
    result: dict


@dataclass
class Agent:
    client: Any = None
    model: str = config.MODEL
    messages: list[dict] = field(default_factory=list)
    last_calls: list[ToolCall] = field(default_factory=list)  # ferramentas da última mensagem (debug/exemplos)

    def _client(self):
        if self.client is None:
            from .llm import get_client

            self.client = get_client()
        return self.client

    def _system(self) -> list[dict]:
        return [
            # bloco estático primeiro e cacheável; o dinâmico (hora) vem depois
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": dynamic_context()},
        ]

    def chat(self, user_text: str) -> str:
        """Processa uma mensagem do cliente e devolve a resposta final em texto."""
        checkpoint = len(self.messages)
        self.last_calls = []
        self.messages.append({"role": "user", "content": user_text})
        try:
            for _ in range(MAX_STEPS):
                resp = self._client().messages.create(
                    model=self.model,
                    max_tokens=MAX_TOKENS,
                    system=self._system(),
                    tools=TOOL_SCHEMAS,
                    messages=window(self.messages),
                )
                blocks = [d for b in resp.content if (d := _block_to_dict(b))]
                self.messages.append({"role": "assistant", "content": blocks})

                uses = [b for b in blocks if b["type"] == "tool_use"]
                if not uses:
                    return "".join(b["text"] for b in blocks if b["type"] == "text").strip() or FALLBACK

                results = []
                for u in uses:
                    out = run_tool(u["name"], u["input"])
                    self.last_calls.append(ToolCall(u["name"], u["input"], out))
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": u["id"],
                        "content": json.dumps(out, ensure_ascii=False, default=str),
                        **({"is_error": True} if _is_failure(out) else {}),
                    })
                self.messages.append({"role": "user", "content": results})
        except Exception:
            del self.messages[checkpoint:]  # não deixa histórico quebrado (tool_use sem tool_result)
            raise

        # estourou MAX_STEPS: histórico termina em tool_result; fecha o turno de forma consistente
        self.messages.append({"role": "assistant", "content": [{"type": "text", "text": FALLBACK}]})
        return FALLBACK

    def reset(self) -> None:
        self.messages.clear()
        self.last_calls.clear()


def _is_failure(out: dict) -> bool:
    """Falha de execução (is_error). Erros de negócio, como verificação negada, não contam."""
    return str(out.get("erro", "")).startswith(("Falha ao executar", "Ferramenta desconhecida"))


def window(messages: list[dict], max_turns: int = MAX_TURNS) -> list[dict]:
    """Últimos `max_turns` turnos do cliente, cortando só em mensagem de texto do cliente
    (nunca no meio de um par tool_use/tool_result, que a API rejeita)."""
    starts = [i for i, m in enumerate(messages) if m["role"] == "user" and isinstance(m["content"], str)]
    if len(starts) <= max_turns:
        return messages
    return messages[starts[-max_turns]:]


def _block_to_dict(b) -> dict:
    if b.type == "text":
        return {"type": "text", "text": b.text}
    if b.type == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": dict(b.input)}
    return {}  # blocos que não usamos (ex.: thinking)

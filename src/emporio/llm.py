"""Camada fina de acesso ao provedor de LLM (Anthropic).

Mantida isolada para que trocar de provedor mexa em um único arquivo.
"""
from __future__ import annotations

import os

from .config import MODEL


def get_client():
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY não definida. Copie .env.example para .env e preencha."
        )
    import anthropic  # import tardio: ferramentas/testes não exigem o SDK

    return anthropic.Anthropic()


def smoke_test() -> str:
    """Uma chamada mínima para validar chave, modelo e conectividade."""
    client = get_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=50,
        messages=[{"role": "user", "content": "Responda apenas: olá!"}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")

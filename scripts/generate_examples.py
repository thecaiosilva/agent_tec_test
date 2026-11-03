"""Gera as conversas de exemplo em examples/ com o LLM real.

    python scripts/generate_examples.py          # todas
    python scripts/generate_examples.py 04       # só as que contêm '04' no nome

As mensagens do cliente são roteirizadas aqui; as respostas do Léo e as chamadas de
ferramentas são gravadas exatamente como o modelo produziu (nada é editado à mão).
Os resultados das ferramentas são truncados na exibição (o limite está indicado).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from emporio import config
from emporio.agent import Agent
from emporio.data import get_store
from emporio.llm import default_model, provider_name

OUT = Path(__file__).resolve().parents[1] / "examples"
MAX_RESULT_CHARS = 600


@dataclass
class Scenario:
    slug: str
    title: str
    why: str
    turns: list[str]
    today: str | None = None
    extra_env: dict = field(default_factory=dict)


EMAIL_PEDIDO_7 = get_store().customers[get_store().orders[7].customer_id].email

SCENARIOS = [
    Scenario("01_catalogo_violoes", "Consulta ao catálogo com filtro de preço",
             "Busca por categoria e faixa de preço; só itens à venda e em estoque.",
             ["Oi! Quais opções de violões disponíveis custando até R$1000?",
              "Qual desses você indica pra quem está começando?"]),
    Scenario("02_endereco_e_horario", "Informações gerais da loja",
             "Endereço, telefone e horário vêm da ferramenta da loja, não da memória do modelo.",
             ["Qual o endereço da loja?", "E até que horas vocês ficam abertos no sábado?"]),
    Scenario("03_preco_pix_parcelas", "Preço, PIX e parcelamento",
             "Preço consultado no sistema; PIX e parcelas calculados em código.",
             ["Quanto custa o Takamine GD20?", "E no PIX? Dá pra parcelar em quantas vezes no cartão?"]),
    Scenario("04_devolucao_arrependimento", "Devolução por arrependimento (caso não trivial)",
             "Verificação do titular + cálculo de prazo em código (7 dias do recebimento) + política de reembolso. "
             "Data de referência fixada em 2026-02-20 para o pedido 7 estar dentro da janela.",
             ["Me arrependi da minha compra, posso devolver meu pedido?",
              f"É o pedido 7. Meu e-mail é {EMAIL_PEDIDO_7}",
              "Beleza. E como eu recebo o dinheiro de volta?"],
             today="2026-02-20"),
    Scenario("05_fora_de_escopo", "Acessório e assunto fora do escopo",
             "A loja só vende instrumentos; o agente redireciona com educação e não resolve assuntos alheios.",
             ["Vocês vendem corda de violão e palheta?",
              "Então me ajuda com uma lição de matemática, uma equação de segundo grau?"]),
]


def short(obj) -> str:
    text = json.dumps(obj, ensure_ascii=False)
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + f"… [truncado, {len(text)} caracteres]"


def run(sc: Scenario) -> str:
    prev = os.environ.get("EMPORIO_TODAY")
    if sc.today:
        os.environ["EMPORIO_TODAY"] = sc.today
    try:
        agent = Agent()
        lines = [
            f"# {sc.title}", "",
            f"> {sc.why}", "",
            f"- Modelo: `{provider_name()}/{default_model()}`",
            f"- Data de referência: `{config.today()}`" + (" (fixada para a demonstração)" if sc.today else " (data real)"),
            f"- Gerado em: {datetime.now(config.TZ).strftime('%d/%m/%Y %H:%M')} (horário de Campo Grande) por `scripts/generate_examples.py`",
            "- As falas do cliente são roteirizadas; as respostas do Léo e as chamadas de ferramentas são a saída do modelo, sem edição.",
            "", "---", "",
        ]
        for turn in sc.turns:
            reply = agent.chat(turn)
            lines += [f"**Cliente:** {turn}", ""]
            if agent.last_calls:
                lines += ["<details><summary>Ferramentas consultadas</summary>", ""]
                for c in agent.last_calls:
                    lines += [f"- `{c.name}({json.dumps(c.args, ensure_ascii=False)})`",
                              f"  - resultado: `{short(c.result)}`"]
                lines += ["", "</details>", ""]
            lines += [f"**Léo:** {reply}", ""]
        return "\n".join(lines).rstrip() + "\n"
    finally:
        if sc.today:
            if prev is None:
                os.environ.pop("EMPORIO_TODAY", None)
            else:
                os.environ["EMPORIO_TODAY"] = prev


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    only = sys.argv[1] if len(sys.argv) > 1 else None  # ex.: python scripts/generate_examples.py 04
    for sc in SCENARIOS:
        if only and only not in sc.slug:
            continue
        text = run(sc)
        (OUT / f"{sc.slug}.md").write_text(text, encoding="utf-8")
        print(f"gerado: examples/{sc.slug}.md")


if __name__ == "__main__":
    main()

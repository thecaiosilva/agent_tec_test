"""Roda os casos de avaliação contra o LLM real.

    python -m evals.run_evals                 # todos
    python -m evals.run_evals -k devolucao    # filtra por id
    python -m evals.run_evals --model claude-sonnet-5-5

Gera evals/last_run.md com o resultado. Exige ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from emporio.agent import Agent
from emporio.text import normalize

from .cases import CASES, Case


def evaluate(case: Case, called: list[str], reply: str) -> list[str]:
    """Lista de falhas (vazia = passou). Função pura, testável sem LLM."""
    fails = []
    if case.tools_any and not set(case.tools_any) & set(called):
        fails.append(f"nenhuma destas ferramentas foi chamada: {case.tools_any} (chamadas: {called or 'nenhuma'})")
    for t in case.tools_none:
        if t in called:
            fails.append(f"ferramenta proibida chamada: {t}")
    text = normalize(reply)
    for pat in case.contains:
        if not re.search(pat, text):
            fails.append(f"faltou /{pat}/ na resposta")
    for pat in case.not_contains:
        if re.search(pat, text):
            fails.append(f"não deveria conter /{pat}/")
    return fails


def run_case(case: Case, agent_factory=Agent) -> dict:
    prev = os.environ.get("EMPORIO_TODAY")
    if case.today:
        os.environ["EMPORIO_TODAY"] = case.today
    try:
        agent = agent_factory()
        called: list[str] = []
        reply = ""
        for turn in case.turns:
            reply = agent.chat(turn)
            called += [c.name for c in agent.last_calls]
    finally:
        if case.today:
            if prev is None:
                os.environ.pop("EMPORIO_TODAY", None)
            else:
                os.environ["EMPORIO_TODAY"] = prev
    return {"case": case, "called": called, "reply": reply, "fails": evaluate(case, called, reply)}


def report(results: list[dict], model: str) -> str:
    ok = sum(not r["fails"] for r in results)
    lines = [f"# Avaliação do agente — {ok}/{len(results)} casos passaram", "", f"Modelo: `{model}`", "",
             "| Caso | Resultado | Ferramentas |", "|---|---|---|"]
    for r in results:
        lines.append(f"| {r['case'].id} | {'✅' if not r['fails'] else '❌'} | {', '.join(r['called']) or '—'} |")
    for r in results:
        if r["fails"]:
            lines += ["", f"## ❌ {r['case'].id} — {r['case'].desc}", "",
                      f"Pergunta(s): {r['case'].turns}", "", f"Resposta: {r['reply']}", ""]
            lines += [f"- {f}" for f in r["fails"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", help="roda só os casos cujo id contém este texto")
    ap.add_argument("--model", help="sobrescreve EMPORIO_MODEL")
    args = ap.parse_args()

    from emporio import config

    model = args.model or config.MODEL
    cases = [c for c in CASES if not args.k or args.k in c.id]
    results = []
    for c in cases:
        r = run_case(c, lambda: Agent(model=model))
        print(f"{'OK  ' if not r['fails'] else 'FAIL'} {c.id}")
        for f in r["fails"]:
            print(f"       - {f}")
        results.append(r)
    out = Path(__file__).with_name("last_run.md")
    out.write_text(report(results, model), encoding="utf-8")
    print(f"\n{sum(not r['fails'] for r in results)}/{len(results)} passaram. Relatório: {out}")
    return 0 if all(not r["fails"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

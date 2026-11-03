"""CLI do agente.

    python -m emporio            # conversa (padrão)
    python -m emporio chat --debug
    python -m emporio check      # verifica dados e conexão com o LLM
"""
from __future__ import annotations

import argparse
import json
import sys

from . import config


def check() -> None:
    from .data import load_store
    from .llm import smoke_test
    from .policies import load_chunks

    store = load_store()
    print(
        f"Dados OK: {len(store.products)} produtos, {len(store.orders)} pedidos, "
        f"{len(store.customers)} clientes, {len(load_chunks())} trechos de política. "
        f"Data de referência: {config.today()}"
    )
    try:
        print(f"LLM ({config.MODEL}) respondeu: {smoke_test()}")
    except Exception as e:  # noqa: BLE001
        print(f"LLM indisponível: {e}")


def chat(debug: bool) -> None:
    from .agent import Agent

    agent = Agent()
    print("Empório da Música — atendimento. Digite 'sair' para encerrar, 'novo' para reiniciar a conversa.\n")
    while True:
        try:
            text = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        if text.lower() in {"sair", "exit", "quit"}:
            return
        if text.lower() == "novo":
            agent.reset()
            print("(conversa reiniciada)\n")
            continue
        try:
            reply = agent.chat(text)
        except Exception as e:  # noqa: BLE001
            print(f"[erro] {type(e).__name__}: {e}\n")
            continue
        if debug:
            for c in agent.last_calls:
                print(f"  [tool] {c.name}({json.dumps(c.args, ensure_ascii=False)})")
                print(f"         -> {json.dumps(c.result, ensure_ascii=False)[:300]}")
        print(f"\nLéo: {reply}\n")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="emporio")
    sub = parser.add_subparsers(dest="cmd")
    c = sub.add_parser("chat", help="conversar com o agente")
    c.add_argument("--debug", action="store_true", help="mostra as ferramentas chamadas")
    sub.add_parser("check", help="verifica dados e conexão com o LLM")
    args = parser.parse_args()
    if args.cmd == "check":
        check()
    else:
        chat(getattr(args, "debug", False))


if __name__ == "__main__":
    main()

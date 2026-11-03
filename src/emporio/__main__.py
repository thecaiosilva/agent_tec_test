"""CLI do agente.

    python -m emporio            # conversa (padrão)
    python -m emporio chat --debug
    python -m emporio chat --session cliente1   # retoma/cria sessão com histórico salvo
    python -m emporio check      # verifica dados e conexão com o LLM
"""
from __future__ import annotations

import argparse
import json
import sys

from . import config


def check() -> None:
    from .data import load_store
    from .llm import default_model, provider_name, smoke_test
    from .policies import load_chunks

    store = load_store()
    print(
        f"Dados OK: {len(store.products)} produtos, {len(store.orders)} pedidos, "
        f"{len(store.customers)} clientes, {len(load_chunks())} trechos de política. "
        f"Data de referência: {config.today()}"
    )
    try:
        print(f"LLM ({provider_name()}/{default_model()}) respondeu: {smoke_test()}")
    except Exception as e:  # noqa: BLE001
        print(f"LLM indisponível: {e}")


HELP = "Comandos: 'novo' reinicia a conversa, 'sessoes' lista as salvas, 'sair' encerra."


def chat(debug: bool, session: str | None) -> None:
    from . import sessions
    from .agent import Agent

    agent = Agent()
    sid = session or sessions.new_session_id()
    agent.messages = sessions.load(sid)
    resumed = bool(agent.messages)
    print(f"Empório da Música — atendimento (sessão {sid}{', retomada' if resumed else ''}).
{HELP}
")
    while True:
        try:
            text = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        cmd = text.lower()
        if cmd in {"sair", "exit", "quit"}:
            return
        if cmd == "novo":
            agent.reset()
            sid = sessions.new_session_id()
            print(f"(nova conversa, sessão {sid})
")
            continue
        if cmd == "sessoes":
            print("Sessões salvas: " + (", ".join(sessions.list_sessions()) or "nenhuma") + "
")
            continue
        try:
            reply = agent.chat(text)
        except Exception as e:  # noqa: BLE001
            print(f"[erro] {type(e).__name__}: {e}
")
            continue
        sessions.save(sid, agent.messages)
        if debug:
            for c in agent.last_calls:
                print(f"  [tool] {c.name}({json.dumps(c.args, ensure_ascii=False)})")
                print(f"         -> {json.dumps(c.result, ensure_ascii=False)[:300]}")
        print(f"
Léo: {reply}
")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="emporio")
    sub = parser.add_subparsers(dest="cmd")
    c = sub.add_parser("chat", help="conversar com o agente")
    c.add_argument("--debug", action="store_true", help="mostra as ferramentas chamadas")
    c.add_argument("--session", help="id da sessão: retoma se existir, senão cria com esse nome")
    sub.add_parser("check", help="verifica dados e conexão com o LLM")
    args = parser.parse_args()
    if args.cmd == "check":
        check()
    else:
        chat(getattr(args, "debug", False), getattr(args, "session", None))


if __name__ == "__main__":
    main()

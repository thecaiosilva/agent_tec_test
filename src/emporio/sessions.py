"""Persistência do histórico de conversa em JSON (uma sessão por arquivo)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .config import ROOT

SESSIONS_DIR = ROOT / "sessions"


def new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _path(session_id: str, directory: Path) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)  # evita path traversal
    return directory / f"{safe}.json"


def save(session_id: str, messages: list[dict], directory: Path = SESSIONS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = _path(session_id, directory)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(messages, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)  # escrita atômica: arquivo nunca fica pela metade
    return path


def load(session_id: str, directory: Path = SESSIONS_DIR) -> list[dict]:
    """Histórico salvo, ou [] se a sessão não existir/estiver corrompida."""
    path = _path(session_id, directory)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def list_sessions(directory: Path = SESSIONS_DIR) -> list[str]:
    return sorted(p.stem for p in directory.glob("*.json")) if directory.exists() else []

"""Configuração central: caminhos, fuso horário e data de referência."""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:  # .env é opcional
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
TZ = ZoneInfo("America/Campo_Grande")


def today() -> date:
    """Data de referência. EMPORIO_TODAY (AAAA-MM-DD) sobrescreve a data real."""
    override = os.getenv("EMPORIO_TODAY", "").strip()
    return date.fromisoformat(override) if override else datetime.now(TZ).date()


def now() -> datetime:
    """Agora, em Campo Grande. Com EMPORIO_TODAY, a data é a fixada (hora do relógio real),
    para que dia da semana e "loja aberta?" sejam coerentes com a data de referência."""
    real = datetime.now(TZ)
    return datetime.combine(today(), real.timetz())

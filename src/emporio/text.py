"""Normalização de texto para buscas tolerantes a acento, caixa e espaçamento."""
from __future__ import annotations

import re
import unicodedata


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip()


def compact(s: str) -> str:
    """Só letras/dígitos: 'Takamine GD-20' e 'takamine gd 20' viram 'takaminegd20'."""
    return re.sub(r"[^a-z0-9]", "", normalize(s))


def tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalize(s))

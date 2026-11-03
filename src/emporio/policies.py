"""Políticas da loja: extração do PDF, chunking por seção e busca (BM25).

Por que BM25 e não embeddings?
O manual tem ~8 páginas (~30 trechos) e vocabulário bem delimitado. BM25 com
normalização, radical simples e expansão de sinônimos é offline, determinístico,
sem custo/chave de API e fácil de depurar. A interface `search_policies` esconde
o mecanismo, então trocar por embeddings (ex.: multilingual-e5 + FAISS) não
afeta o agente. Ver README.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import DATA_DIR
from .text import normalize

# ---------------------------------------------------------------- extração

_HEADER = re.compile(r"^\s*Empório da Música\s+Manual de Políticas e Procedimentos\s*$")
_FOOTER = re.compile(r"^\s*Página\s+\d+\s*$")
_H1 = re.compile(r"^(\d{1,2})\.\s+(\S.*)$")  # sem indentação: "4. Política de ..."
_H2 = re.compile(r"^(\d{1,2}\.\d{1,2})\s+(\S.*)$")  # "4.1 Direito de ..."


def find_pdf(data_dir: Path = DATA_DIR) -> Path:
    # glob evita problemas com a normalização unicode de "políticas" no nome
    matches = sorted(p for p in data_dir.glob("*.pdf") if "tica" in normalize(p.name))
    if not matches:
        raise FileNotFoundError(f"PDF de políticas não encontrado em {data_dir}")
    return matches[0]


def extract_text(pdf_path: Path) -> str:
    """Texto do PDF sem cabeçalho/rodapé repetidos, páginas concatenadas."""
    import pypdf

    lines: list[str] = []
    for page in pypdf.PdfReader(str(pdf_path)).pages:
        for line in page.extract_text(extraction_mode="layout").splitlines():
            if _HEADER.match(line) or _FOOTER.match(line):
                continue
            lines.append(line.rstrip())
    return "\n".join(lines)


# ---------------------------------------------------------------- chunking

@dataclass(frozen=True)
class Chunk:
    section: str  # "4.1"
    title: str  # "Direito de Arrependimento (Compras Online)"
    parent: str  # título da seção de nível 1
    text: str
    note: str | None = None  # observação interna de interpretação

    @property
    def heading(self) -> str:
        return f"{self.section} {self.title}"


# Resolução de inconsistências do manual (ver README).
NOTES = {
    "3": "A tabela resume o teto (12x, parcela mín. R$100). Para parcelamento valem as faixas da seção 3.1.",
    "3.1": "Faixas oficiais de parcelamento; prevalecem sobre o 'mínimo R$100' genérico da tabela da seção 3.",
    "1.2": "O e-mail correto é contato@emporiodamusica.com.br (sem acento). O telefone da loja é (67) 3341-4444.",
    "7": "O número de WhatsApp é (67) 3321-4500; o telefone fixo da loja é (67) 3341-4444.",
    "6.2": "Produto em promoção não recebe o desconto de PIX. Sempre mostrar preço original, % e preço final.",
}


def _clean(block: list[str]) -> str:
    out = []
    for line in block:
        line = line.strip()
        marker = re.match(r"^(•|\d+\.)\s+", line)  # marcador de lista não é coluna
        head = marker.group(1) + " " if marker else ""
        line = head + re.sub(r"\s{2,}", " | ", line[marker.end():] if marker else line)  # colunas de tabela
        if line:
            out.append(line)
    text = "\n".join(out)
    return re.sub(r"\n(?=[a-zà-ú(])", " ", text)  # junta quebras no meio de frases


def chunk_manual(text: str) -> list[Chunk]:
    """Divide por seção: subseções (x.y) viram trechos próprios; seções sem
    subseção viram um trecho; introdução de seção com subseções vira trecho '<n>'."""
    # 1) descobre cabeçalhos em ordem; seção de nível 1 deve ser sequencial (evita listas "1. Saudação")
    heads: list[tuple[int, str, str]] = []  # (linha, número, título)
    lines = text.splitlines()
    next_major = 1
    for i, line in enumerate(lines):
        if (m := _H1.match(line)) and int(m.group(1)) == next_major and not line.rstrip().endswith(":"):
            heads.append((i, m.group(1), m.group(2).strip()))
            next_major += 1
        elif m := _H2.match(line):
            heads.append((i, m.group(1), m.group(2).strip()))
    if not heads:
        return []

    chunks: list[Chunk] = []
    parent = ""
    for idx, (start, num, title) in enumerate(heads):
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        if "." not in num:
            parent = title
        body = _clean(lines[start + 1 : end])
        if not body:
            continue
        chunks.append(Chunk(num, title, parent, body, NOTES.get(num)))
    return chunks


@lru_cache(maxsize=1)
def load_chunks() -> tuple[Chunk, ...]:
    return tuple(chunk_manual(extract_text(find_pdf())))


# ---------------------------------------------------------------- busca BM25

_STOP = set(normalize(
    "a o as os um uma uns umas de do da dos das em no na nos nas por para com sem sobre e ou que "
    "se ao aos eu meu minha me te voce vcs voces qual quais como quando onde quanto isso esse essa "
    "este esta ser sao foi tem ter posso pode podem gostaria queria quero saber ja mais muito"
).split())

# Sinônimos/variações de cliente -> termos do manual (aplicado após normalização).
_SYNONYMS = {
    "devolver": ["devolucao", "arrependimento", "reembolso"],
    "devolucao": ["arrependimento", "reembolso"],
    "arrependi": ["devolucao", "arrependimento", "reembolso"],
    "estorno": ["reembolso", "devolucao"],
    "dinheiro": ["reembolso", "pagamento"],
    "trocar": ["troca", "defeito", "preferencia"],
    "troca": ["trocas", "defeito", "preferencia"],
    "quebrou": ["defeito", "garantia"],
    "estragou": ["defeito", "garantia"],
    "defeituoso": ["defeito", "garantia"],
    "parcelar": ["parcelamento", "parcela", "cartao", "credito"],
    "parcelas": ["parcelamento", "parcela"],
    "pagar": ["pagamento", "pix", "cartao", "boleto"],
    "pagamento": ["pix", "cartao", "boleto", "debito"],
    "cartao": ["credito", "debito", "parcelamento"],
    "entrega": ["frete", "prazo", "entregas"],
    "enviar": ["frete", "entrega", "correios", "sedex", "pac"],
    "envio": ["frete", "entrega", "correios"],
    "chega": ["entrega", "prazo", "frete"],
    "demora": ["prazo", "entrega"],
    "rastrear": ["rastreamento", "codigo"],
    "rastreio": ["rastreamento", "codigo"],
    "horario": ["funcionamento", "abre", "fecha"],
    "aberto": ["horario", "funcionamento"],
    "abre": ["horario", "funcionamento"],
    "fecha": ["horario", "funcionamento"],
    "funciona": ["horario", "funcionamento"],
    "sabado": ["horario", "funcionamento"],
    "domingo": ["horario", "funcionamento"],
    "feriado": ["horario", "funcionamento"],
    "endereco": ["rua", "localizacao", "dados", "empresa"],
    "localizacao": ["endereco", "rua", "dados"],
    "telefone": ["whatsapp", "contato", "dados"],
    "contato": ["telefone", "whatsapp", "email", "dados"],
    "email": ["contato", "dados"],
    "desconto": ["promocao", "pix", "descontos"],
    "promo": ["promocao", "promocoes"],
    "black": ["promocao", "friday"],
    "cupom": ["promocao", "desconto"],
    "reclamacao": ["reclamar", "gerencia", "retorno"],
    "reclamar": ["reclamacao", "gerencia", "retorno"],
    "acessorio": ["escopo", "acessorios", "exclusivamente"],
    "acessorios": ["escopo", "exclusivamente"],
    "cordas": ["acessorios", "escopo", "exclusivamente"],
    "palheta": ["acessorios", "escopo"],
    "cabo": ["acessorios", "escopo"],
    "pedal": ["acessorios", "escopo"],
    "amplificador": ["acessorios", "escopo"],
    "dados": ["privacidade", "lgpd"],
    "privacidade": ["lgpd", "dados"],
    "excluir": ["exclusao", "dados", "lgpd"],
    "apagar": ["exclusao", "dados", "lgpd"],
    "garantia": ["defeito", "fabricante"],
    "tom": ["voz", "atendimento"],
}


def _stem(t: str) -> str:
    return t[:5] if len(t) > 5 else t


def _tokenize(s: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", normalize(s)) if t not in _STOP and len(t) > 1]


def expand_query(query: str) -> list[str]:
    """Tokens da consulta + sinônimos (com peso menor via contagem única)."""
    base = [t for t in re.findall(r"[a-z0-9]+", normalize(query)) if t not in _STOP and len(t) > 1]
    extra: list[str] = []
    for t in base:
        for key, syns in _SYNONYMS.items():
            if t == key or (len(key) >= 5 and t.startswith(key[:5]) and t[:5] == key[:5]):
                extra.extend(syns)
    return [_stem(t) for t in base] + [_stem(normalize(e)) for e in extra]


class PolicyIndex:
    K1, B = 1.5, 0.75

    def __init__(self, chunks: list[Chunk] | tuple[Chunk, ...]):
        self.chunks = list(chunks)
        # título conta em dobro: casar com o cabeçalho é forte evidência
        docs = [_tokenize(f"{c.heading} {c.heading} {c.parent} {c.text}") for c in self.chunks]
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = sum(self.len) / max(len(self.len), 1)
        df: Counter = Counter()
        for tf in self.tf:
            df.update(tf.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, q_tokens: list[str]) -> list[float]:
        weights = Counter(q_tokens)  # termos repetidos (original + sinônimo) pesam mais
        out = []
        for tf, dl in zip(self.tf, self.len):
            s = 0.0
            for t, w in weights.items():
                f = tf.get(t, 0)
                if not f:
                    continue
                s += w * self.idf[t] * f * (self.K1 + 1) / (f + self.K1 * (1 - self.B + self.B * dl / self.avg))
            out.append(s)
        return out

    def search(self, query: str, top_k: int = 3, min_score: float = 2.0) -> list[tuple[Chunk, float]]:
        scores = self.score(expand_query(query))
        ranked = sorted(zip(self.chunks, scores), key=lambda cs: -cs[1])
        return [(c, s) for c, s in ranked[:top_k] if s >= min_score]


@lru_cache(maxsize=1)
def get_index() -> PolicyIndex:
    return PolicyIndex(load_chunks())


def search_policies(query: str, top_k: int = 3) -> dict:
    """Ferramenta: trechos do manual relevantes para a pergunta."""
    if not query or not query.strip():
        return {"erro": "Informe a pergunta ou o tema da política."}
    hits = get_index().search(query, top_k=max(1, min(top_k, 5)))
    if not hits:
        return {
            "trechos": [],
            "aviso": "Nenhuma política relevante encontrada. Não invente regras: "
            "encaminhe para a equipe/gerência se for uma dúvida de política.",
        }
    return {
        "trechos": [
            {
                "secao": c.section,
                "titulo": c.heading,
                "texto": c.text,
                **({"observacao_interna": c.note} if c.note else {}),
                "relevancia": round(s, 2),
            }
            for c, s in hits
        ],
        "instrucao": "Manual interno: parafraseie com naturalidade, sem citar números de seção ao cliente.",
    }

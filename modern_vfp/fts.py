"""
Motor de Búsqueda Full-Text (FTS) en Memoria (`modern_vfp/fts.py`) para FoxNext.
Permite indexación inversa, ponderación por relevancia TF-IDF y búsqueda textual avanzada sobre cursores.
Comandos y funciones:
- `CREATE FULLTEXT INDEX ON <alias> (<campo1> [, <campo2>])`
- `FTSSEARCH(cAlias, cQuery)` -> Retorna lista de números de registro (RECNOs) más relevantes
- `FTSMATCH(cAlias, cQuery)` -> Retorna .T. si el registro actual del cursor coincide
- `FULLTEXT SEARCH <query> IN <alias> [INTO CURSOR <res_alias>]`
"""

from __future__ import annotations
import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .cursor import Cursor, FieldDef


def _tokenize(text: Any) -> List[str]:
    """Extrae palabras normalizadas (alfanuméricas en minúsculas)."""
    if not text:
        return []
    s = str(text).lower()
    return re.findall(r"\b[A-Za-z0-9_áéíóúñÁÉÍÓÚÑ]{2,}\b", s)


class FullTextIndex:
    """Índice invertido para un conjunto de campos en un cursor específico."""

    def __init__(self, alias: str, fields: List[str]) -> None:
        self.alias = alias.lower().strip()
        self.fields = [f.lower().strip() for f in fields]
        # term -> {recno: count}
        self.inverted_index: Dict[str, Dict[int, int]] = {}
        # recno -> total_words
        self.doc_lengths: Dict[int, int] = {}
        self.total_docs = 0

    def build(self, cur: Cursor, set_deleted_on: bool = False) -> None:
        self.inverted_index.clear()
        self.doc_lengths.clear()
        vis = cur.visible_recnos(set_deleted_on)
        self.total_docs = len(vis)

        for recno in vis:
            row = cur.records[recno - 1]
            words: List[str] = []
            for f in self.fields:
                val = row.get(f)
                if val is not None:
                    words.extend(_tokenize(val))

            self.doc_lengths[recno] = len(words)
            for w in words:
                if w not in self.inverted_index:
                    self.inverted_index[w] = {}
                self.inverted_index[w][recno] = self.inverted_index[w].get(recno, 0) + 1

    def search(self, query: str) -> List[Tuple[int, float]]:
        """Busca registros relevantes usando ponderación TF-IDF."""
        q_tokens = _tokenize(query)
        if not q_tokens or not self.total_docs:
            return []

        scores: Dict[int, float] = {}
        for token in q_tokens:
            posting = self.inverted_index.get(token)
            if not posting:
                continue
            df = len(posting)
            idf = math.log(1.0 + (self.total_docs - df + 0.5) / (df + 0.5))
            for recno, tf in posting.items():
                doc_len = self.doc_lengths.get(recno, 1) or 1
                norm_tf = tf / doc_len
                scores[recno] = scores.get(recno, 0.0) + (norm_tf * idf)

        # Ordenar registros por puntaje descendente
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked

    def match_recno(self, recno: int, query: str) -> bool:
        """Verifica si un registro dado contiene los términos de la consulta."""
        q_tokens = _tokenize(query)
        if not q_tokens:
            return False
        # Coincidencia si el recno contiene al menos un término clave (o todos)
        for token in q_tokens:
            posting = self.inverted_index.get(token)
            if posting and recno in posting:
                return True
        return False


class FullTextSearchEngine:
    """Motor global de índices full-text para cursores activos."""

    def __init__(self) -> None:
        # alias -> FullTextIndex
        self._indices: Dict[str, FullTextIndex] = {}

    def create_index(self, cur: Cursor, fields: List[str], set_deleted_on: bool = False) -> FullTextIndex:
        idx = FullTextIndex(cur.alias, fields)
        idx.build(cur, set_deleted_on)
        self._indices[cur.alias.lower()] = idx
        return idx

    def get_index(self, alias: str) -> Optional[FullTextIndex]:
        return self._indices.get(alias.lower().strip())

    def search(self, cur: Cursor, query: str, set_deleted_on: bool = False) -> List[Tuple[int, float]]:
        al = cur.alias.lower()
        if al not in self._indices:
            # Auto-indexar todos los campos de texto
            char_fields = [f.name for f in cur.fields if f.ftype in ("C", "M", "V")]
            if not char_fields:
                char_fields = [f.name for f in cur.fields]
            self.create_index(cur, char_fields, set_deleted_on)
        return self._indices[al].search(query)

    def is_match(self, cur: Cursor, query: str) -> bool:
        al = cur.alias.lower()
        if al not in self._indices:
            char_fields = [f.name for f in cur.fields if f.ftype in ("C", "M", "V")]
            if not char_fields:
                char_fields = [f.name for f in cur.fields]
            self.create_index(cur, char_fields)
        return self._indices[al].match_recno(cur.recno(), query)

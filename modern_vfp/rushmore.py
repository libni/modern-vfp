"""
Motor de Optimización de Consultas Rushmore (`RushmoreEngine`) para FoxNext / Modern VFP.
Acelera drásticamente búsquedas, filtros y recorridos `FOR <condicion>` aprovechando
los árboles de índices (`INDEX ON ... TAG ...`) para evitar escaneos secuenciales completos.
Soporta niveles de optimización `Full`, `Partial` y `None`, y telemetría `SYS(3054)`.
"""

from __future__ import annotations
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .cursor import Cursor


class RushmoreEngine:
    """
    Optimizador de consultas indexadas tipo Rushmore para cursores de 64 bits.
    """

    def __init__(self) -> None:
        self.report_level: int = 0  # 0: Off, 1: Query/Filter, 11: Detallado
        self.last_optimization: Dict[str, Any] = {
            "alias": "",
            "filter": "",
            "level": "None",
            "indexed_clauses": [],
            "sequential_clauses": [],
        }

    def set_sys3054(self, level: int = 1) -> int:
        prev = self.report_level
        self.report_level = int(level)
        return prev

    def get_sys3054(self) -> int:
        return self.report_level

    def build_index_key_map(self, cur: Cursor, tag_name: str, eval_fn: Callable[[str], Any]) -> Dict[Any, List[int]]:
        """
        Construye un mapa de claves indexadas a listas de RECNOs para una etiqueta dada.
        """
        tag = tag_name.lower()
        if tag not in cur.indexes:
            return {}
        expr_str = cur.indexes[tag]
        key_map: Dict[Any, List[int]] = {}
        saved_rec = cur._recno
        try:
            for r in range(1, len(cur.records) + 1):
                cur._recno = r
                val = eval_fn(expr_str)
                # Normalizar strings con rstrip como hace VFP
                if isinstance(val, str):
                    val = val.rstrip()
                key_map.setdefault(val, []).append(r)
        finally:
            cur._recno = saved_rec
        return key_map

    def optimize_filter(
        self,
        cur: Cursor,
        for_expr: str,
        eval_fn: Callable[[str], Any],
        set_deleted: bool = False,
    ) -> Tuple[List[int], str]:
        """
        Analiza la expresión `for_expr` y aplica optimización Rushmore usando las etiquetas indexadas.
        Devuelve una tupla (lista_recnos_candidatos, nivel_opt: "Full" | "Partial" | "None").
        """
        clean_expr = for_expr.strip()
        visible_all = cur.visible_recnos(set_deleted)
        if not clean_expr:
            return visible_all, "None"

        # Si no hay índices en el cursor, no hay optimización posible
        if not cur.indexes:
            self.last_optimization = {
                "alias": cur.alias,
                "filter": clean_expr,
                "level": "None",
                "indexed_clauses": [],
                "sequential_clauses": [clean_expr],
            }
            return visible_all, "None"

        # Dividir expresiones conjuntas separadas por AND (.AND. o AND)
        clauses = re.split(r"\s+(?:AND|\.AND\.)\s+", clean_expr, flags=re.IGNORECASE)
        indexed_clauses: List[str] = []
        sequential_clauses: List[str] = []
        candidate_sets: List[Set[int]] = []

        # Buscar tags disponibles y mapear expresiones
        # tag -> expr
        tag_exprs = {tag: expr.lower().strip() for tag, expr in cur.indexes.items()}

        for clause in clauses:
            matched_tag: Optional[str] = None
            op_match = re.match(
                r"^([A-Za-z_][A-Za-z0-9_.]*)\s*(==|=|!=|<>|>=|<=|>|<)\s*(.+)$",
                clause.strip(),
            )
            if op_match:
                lhs = op_match.group(1).lower().strip()
                op = op_match.group(2)
                rhs_expr = op_match.group(3).strip()

                # Verificar si lhs coincide con algún tag indexado
                for tag, expr in tag_exprs.items():
                    if expr == lhs or tag == lhs:
                        matched_tag = tag
                        break

                if matched_tag:
                    try:
                        target_val = eval_fn(rhs_expr)
                        if isinstance(target_val, str):
                            target_val = target_val.rstrip()
                        key_map = self.build_index_key_map(cur, matched_tag, eval_fn)
                        matched_recnos: Set[int] = set()

                        if op in ("=", "=="):
                            matched_recnos = set(key_map.get(target_val, []))
                        elif op in ("!=", "<>"):
                            matched_recnos = set(
                                r for k, rlist in key_map.items() if k != target_val for r in rlist
                            )
                        elif op == ">":
                            matched_recnos = set(
                                r for k, rlist in key_map.items() if k is not None and k > target_val for r in rlist
                            )
                        elif op == ">=":
                            matched_recnos = set(
                                r for k, rlist in key_map.items() if k is not None and k >= target_val for r in rlist
                            )
                        elif op == "<":
                            matched_recnos = set(
                                r for k, rlist in key_map.items() if k is not None and k < target_val for r in rlist
                            )
                        elif op == "<=":
                            matched_recnos = set(
                                r for k, rlist in key_map.items() if k is not None and k <= target_val for r in rlist
                            )

                        candidate_sets.append(matched_recnos)
                        indexed_clauses.append(clause)
                        continue
                    except Exception:
                        pass

            sequential_clauses.append(clause)

        if not indexed_clauses:
            opt_level = "None"
            recno_candidates = visible_all
        elif not sequential_clauses:
            opt_level = "Full"
            # Intersección de todos los conjuntos indexados
            common = set(visible_all)
            for cset in candidate_sets:
                common &= cset
            recno_candidates = sorted(common)
        else:
            opt_level = "Partial"
            common = set(visible_all)
            for cset in candidate_sets:
                common &= cset
            recno_candidates = sorted(common)

        self.last_optimization = {
            "alias": cur.alias,
            "filter": clean_expr,
            "level": opt_level,
            "indexed_clauses": indexed_clauses,
            "sequential_clauses": sequential_clauses,
        }

        return recno_candidates, opt_level

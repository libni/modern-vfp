"""
Motor de Análisis Estadístico y Perfilado de Datos (`modern_vfp/analytics.py`) para FoxNext.
Proporciona análisis descriptivo profundo sobre cursores en memoria:
- Conteo de registros, valores nulos o vacíos, cardinalidad única (distinct)
- Valores mínimos, máximos, promedios y desviación estándar por columna
- Comando: `ANALYZE CURSOR <alias> [INTO CURSOR <stats_alias>]`
- Función: `ANALYZECURSOR(cAlias [, cIntoAlias])`
"""

from __future__ import annotations
import math
from typing import Any, Dict, List, Optional, Set

from .cursor import Cursor, FieldDef


def analyze_cursor(
    cur: Cursor,
    into_alias: str = "cursor_stats",
    set_deleted_on: bool = False,
) -> Cursor:
    """
    Genera un cursor de diagnóstico estadístico con métricas descriptivas para cada columna.
    """
    fields = [
        FieldDef("field_name", "C", 30, 0),
        FieldDef("field_type", "C", 5, 0),
        FieldDef("count", "I", 10, 0),
        FieldDef("nulls", "I", 10, 0),
        FieldDef("distincts", "I", 10, 0),
        FieldDef("min_value", "C", 50, 0),
        FieldDef("max_value", "C", 50, 0),
        FieldDef("avg_value", "N", 14, 2),
        FieldDef("std_dev", "N", 14, 2),
    ]

    out_cur = Cursor(into_alias.lower().strip(), fields)
    vis = cur.visible_recnos(set_deleted_on)
    total_recs = len(vis)

    for f in cur.fields:
        vals: List[Any] = []
        num_vals: List[float] = []
        null_count = 0
        seen_distinct: Set[Any] = set()

        for recno in vis:
            row = cur.records[recno - 1]
            v = row.get(f.name.lower())
            if v is None or (isinstance(v, str) and not v.strip()):
                null_count += 1
            else:
                vals.append(v)
                seen_distinct.add(v)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    num_vals.append(float(v))

        # Métricas
        distinct_count = len(seen_distinct)
        min_str = ""
        max_str = ""
        avg_val = 0.0
        std_dev = 0.0

        if vals:
            try:
                min_str = str(min(vals))[:50]
                max_str = str(max(vals))[:50]
            except Exception:
                min_str = str(vals[0])[:50]
                max_str = str(vals[-1])[:50]

        if num_vals:
            avg_val = round(sum(num_vals) / len(num_vals), 2)
            if len(num_vals) > 1:
                variance = sum((x - avg_val) ** 2 for x in num_vals) / (len(num_vals) - 1)
                std_dev = round(math.sqrt(variance), 2)

        out_cur.append_dict(
            {
                "field_name": f.name,
                "field_type": f.ftype,
                "count": total_recs - null_count,
                "nulls": null_count,
                "distincts": distinct_count,
                "min_value": min_str,
                "max_value": max_str,
                "avg_value": avg_val,
                "std_dev": std_dev,
            }
        )

    out_cur.go_top()
    return out_cur

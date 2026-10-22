"""
Motor de Tabulación Cruzada y Tablas Dinámicas (`modern_vfp/crosstab.py`) para FoxNext.
Inspirado en la utilidad estándar `_GENXTAB` / `VFPXTAB` de Visual FoxPro.
Transforma filas en columnas dinámicas (Pivot Table) agrupadas por una clave de fila,
con agregaciones matemáticas (`SUM`, `AVG`, `COUNT`, `MIN`, `MAX`).
Soporta:
  CROSSTAB <source_alias> ON <row_field> COLUMNS <col_field> VALUES <val_field> [AGGREGATE SUM|AVG|COUNT|MIN|MAX] INTO CURSOR <target_alias>
"""

from __future__ import annotations
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .cursor import Cursor, FieldDef


def _sanitize_col_name(raw: Any) -> str:
    s = str(raw).strip()
    clean = re.sub(r"[^A-Za-z0-9_]", "_", s)
    if not clean or clean[0].isdigit():
        clean = f"C_{clean}"
    return clean[:30].upper()


def crosstab(
    cur: Cursor,
    row_field: str,
    col_field: str,
    val_field: str,
    agg_func: str = "SUM",
    into_alias: str = "xtab_result",
    include_total: bool = True,
    set_deleted_on: bool = False,
) -> Cursor:
    """
    Genera un cursor de tabulación cruzada (tabla dinámica) pivotando una dimensión sobre columnas.
    """
    rf = row_field.lower().strip()
    cf = col_field.lower().strip()
    vf = val_field.lower().strip()
    agg = agg_func.upper().strip()

    # Validar que los campos existan
    existing_fields = {f.name.lower(): f for f in cur.fields}
    if rf not in existing_fields:
        raise ValueError(f"El campo de fila '{row_field}' no existe en el cursor.")
    if cf not in existing_fields:
        raise ValueError(f"El campo de columna '{col_field}' no existe en el cursor.")
    if vf not in existing_fields:
        raise ValueError(f"El campo de valor '{val_field}' no existe en el cursor.")

    row_fdef = existing_fields[rf]

    vis = cur.visible_recnos(set_deleted_on)

    # Recolectar datos y valores únicos de columnas
    distinct_cols_map: Dict[str, str] = {}  # sanitized_name -> display_name
    row_keys_ordered: List[Any] = []
    seen_row_keys: Set[Any] = set()

    # matrix[row_val][col_sanitized] = list of float values
    matrix: Dict[Any, Dict[str, List[float]]] = {}

    for recno in vis:
        rec = cur.records[recno - 1]
        r_val = rec.get(rf)
        c_raw = rec.get(cf)
        v_raw = rec.get(vf)

        if r_val not in seen_row_keys:
            seen_row_keys.add(r_val)
            row_keys_ordered.append(r_val)

        c_sanitized = _sanitize_col_name(c_raw)
        if c_sanitized not in distinct_cols_map:
            distinct_cols_map[c_sanitized] = str(c_raw)

        val_float = 0.0
        if v_raw is not None:
            try:
                val_float = float(v_raw)
            except (ValueError, TypeError):
                val_float = 1.0 if v_raw else 0.0

        matrix.setdefault(r_val, {}).setdefault(c_sanitized, []).append(val_float)

    # Ordenar columnas pivotadas
    sorted_col_names = sorted(distinct_cols_map.keys())

    # Construir definiciones de campos del cursor resultado
    out_fields: List[FieldDef] = [
        FieldDef(name=rf, ftype=row_fdef.ftype, width=row_fdef.width, decimals=row_fdef.decimals)
    ]
    for cname in sorted_col_names:
        out_fields.append(FieldDef(name=cname.lower(), ftype="N", width=14, decimals=2))

    if include_total:
        out_fields.append(FieldDef(name="total", ftype="N", width=14, decimals=2))

    # Función agregadora
    def _compute_agg(vals: List[float]) -> float:
        if not vals:
            return 0.0
        if agg == "SUM":
            return round(sum(vals), 2)
        elif agg == "AVG":
            return round(sum(vals) / len(vals), 2)
        elif agg == "COUNT":
            return float(len(vals))
        elif agg == "MAX":
            return round(max(vals), 2)
        elif agg == "MIN":
            return round(min(vals), 2)
        return round(sum(vals), 2)

    # Crear el nuevo cursor y poblarlo
    xtab_cur = Cursor(into_alias.lower().strip(), out_fields)

    for r_val in row_keys_ordered:
        row_dict: Dict[str, Any] = {rf: r_val}
        row_total_vals: List[float] = []

        for cname in sorted_col_names:
            cell_vals = matrix.get(r_val, {}).get(cname, [])
            cell_agg = _compute_agg(cell_vals)
            row_dict[cname.lower()] = cell_agg
            row_total_vals.extend(cell_vals)

        if include_total:
            row_dict["total"] = _compute_agg(row_total_vals)

        xtab_cur.append_dict(row_dict)

    xtab_cur.go_top(set_deleted_on)
    return xtab_cur

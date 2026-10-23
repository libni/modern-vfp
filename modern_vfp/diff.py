"""
Motor de Comparación y Reconciliación de Datos (Cursor Diff) (`modern_vfp/diff.py`) para FoxNext.
Compara dos versiones de un cursor o tabla mediante una clave primaria común y clasifica cada fila en:
- `ADDED`: Registro presente solo en el segundo cursor
- `DELETED`: Registro presente solo en el primer cursor
- `MODIFIED`: Registro presente en ambos con valores distintos (rastrea columnas alteradas)
- `IDENTICAL`: Registro idéntico en ambos cursores
Comando:
  `DIFF CURSOR <alias1> WITH <alias2> KEY <campo_clave> [INTO CURSOR <diff_alias>]`
Función:
  `DIFFCURSORS(cAlias1, cAlias2, cCampoClave [, cCursorDestino])`
"""

from __future__ import annotations
import json
from typing import Any, Dict, List, Optional, Set

from .cursor import Cursor, FieldDef


def diff_cursors(
    cur1: Cursor,
    cur2: Cursor,
    key_field: str,
    into_alias: str = "diff_result",
    include_identical: bool = True,
    set_deleted_on: bool = False,
) -> Cursor:
    """
    Compara dos cursores por su campo clave y genera un cursor con los deltas de cambios.
    """
    kf = key_field.lower().strip()

    cur1_fields = {f.name.lower(): f for f in cur1.fields}
    cur2_fields = {f.name.lower(): f for f in cur2.fields}

    if kf not in cur1_fields:
        raise ValueError(f"El campo clave '{key_field}' no existe en '{cur1.alias}'.")
    if kf not in cur2_fields:
        raise ValueError(f"El campo clave '{key_field}' no existe en '{cur2.alias}'.")

    # Mapear registros por clave primaria
    map1: Dict[Any, Dict[str, Any]] = {}
    for r in cur1.visible_recnos(set_deleted_on):
        row = cur1.records[r - 1]
        k = row.get(kf)
        if k is not None:
            map1[k] = row

    map2: Dict[Any, Dict[str, Any]] = {}
    for r in cur2.visible_recnos(set_deleted_on):
        row = cur2.records[r - 1]
        k = row.get(kf)
        if k is not None:
            map2[k] = row

    all_keys = sorted(
        list(set(map1.keys()).union(set(map2.keys()))),
        key=lambda x: str(x),
    )

    out_fields = [
        FieldDef("status", "C", 12, 0),
        FieldDef("key_val", "C", 50, 0),
        FieldDef("changed", "C", 120, 0),
        FieldDef("old_data", "M", 254, 0),
        FieldDef("new_data", "M", 254, 0),
    ]
    out_cur = Cursor(into_alias.lower().strip(), out_fields)

    # Campos comunes a comparar
    common_fields = sorted(list(set(cur1_fields.keys()).intersection(set(cur2_fields.keys()))))

    for k in all_keys:
        in1 = k in map1
        in2 = k in map2

        if in2 and not in1:
            out_cur.append_dict(
                {
                    "status": "ADDED",
                    "key_val": str(k),
                    "changed": "",
                    "old_data": "",
                    "new_data": json.dumps(map2[k], default=str),
                }
            )
        elif in1 and not in2:
            out_cur.append_dict(
                {
                    "status": "DELETED",
                    "key_val": str(k),
                    "changed": "",
                    "old_data": json.dumps(map1[k], default=str),
                    "new_data": "",
                }
            )
        else:
            row1 = map1[k]
            row2 = map2[k]
            diff_cols: List[str] = []
            for col in common_fields:
                if row1.get(col) != row2.get(col):
                    diff_cols.append(col)

            if diff_cols:
                out_cur.append_dict(
                    {
                        "status": "MODIFIED",
                        "key_val": str(k),
                        "changed": ",".join(diff_cols),
                        "old_data": json.dumps(row1, default=str),
                        "new_data": json.dumps(row2, default=str),
                    }
                )
            elif include_identical:
                out_cur.append_dict(
                    {
                        "status": "IDENTICAL",
                        "key_val": str(k),
                        "changed": "",
                        "old_data": json.dumps(row1, default=str),
                        "new_data": json.dumps(row2, default=str),
                    }
                )

    out_cur.go_top()
    return out_cur

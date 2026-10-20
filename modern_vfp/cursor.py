"""
Motor de Cursores 64-bit y Áreas de Trabajo (Work Areas) para FoxNext / Modern VFP.
Incluye punteros de registro, índices (INDEX ON / SEEK), relaciones (SET RELATION),
buffering transaccional (TABLEUPDATE / TABLEREVERT) y puente SQL relacional en memoria.
"""

from __future__ import annotations
import copy
import datetime
import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class FieldDef:
    name: str
    ftype: str  # I, N, F, B, Y, C, V, M, L, D, T
    width: int = 10
    decimals: int = 0

    def default_value(self) -> Any:
        t = self.ftype.upper()
        if t == "I":
            return 0
        if t in ("N", "F", "B", "Y"):
            return 0.0
        if t == "L":
            return False
        if t in ("D", "T"):
            return None
        return ""

    def coerce(self, val: Any) -> Any:
        t = self.ftype.upper()
        if val is None:
            return self.default_value() if t not in ("D", "T") else None
        if t == "I":
            try:
                return int(round(float(val)))
            except (ValueError, TypeError):
                return 0
        if t in ("N", "F", "B", "Y"):
            try:
                num = float(val)
                if t == "Y":
                    return round(num, 4)
                if self.decimals > 0:
                    return round(num, self.decimals)
                return num
            except (ValueError, TypeError):
                return 0.0
        if t == "L":
            if isinstance(val, bool):
                return val
            if isinstance(val, (int, float)):
                return val != 0
            s = str(val).strip().upper()
            return s in (".T.", "T", "TRUE", ".Y.", "Y", "1", "SI", "SÍ")
        if t == "D":
            if isinstance(val, datetime.datetime):
                return val.date()
            if isinstance(val, datetime.date):
                return val
            if isinstance(val, str):
                s = val.strip().strip("{}").lstrip("^").strip()
                if not s or s in ("/  /", "  /  /  "):
                    return None
                for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%Y%m%d"):
                    try:
                        return datetime.datetime.strptime(s[:10], fmt).date()
                    except ValueError:
                        continue
            return None
        if t == "T":
            if isinstance(val, datetime.datetime):
                return val
            if isinstance(val, datetime.date):
                return datetime.datetime.combine(val, datetime.time(0, 0, 0))
            if isinstance(val, str):
                s = val.strip().strip("{}").lstrip("^").strip()
                if not s:
                    return None
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                    try:
                        return datetime.datetime.strptime(s[:19], fmt)
                    except ValueError:
                        continue
            return None
        # Carácter / Varchar / Memo
        s = str(val)
        if t == "C" and self.width > 0:
            return s[: self.width]
        if t == "V" and self.width > 0:
            return s[: self.width]
        return s


def parse_schema_string(schema_str: str) -> List[FieldDef]:
    """
    Parsea definiciones estilo VFP:
    "id I, nombre C(50), precio N(10, 2), activo L, fecha D, notas M"
    """
    # Separar por comas que no estén dentro de paréntesis
    tokens: List[str] = []
    depth = 0
    current: List[str] = []
    for ch in schema_str:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            tokens.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current).strip())

    fields: List[FieldDef] = []
    pattern = re.compile(
        r"^([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z]+)(?:\s*\(\s*(\d+)(?:\s*,\s*(\d+))?\s*\))?",
        re.IGNORECASE,
    )
    for tok in tokens:
        if not tok:
            continue
        m = pattern.match(tok)
        if not m:
            raise ValueError(f"Definición de campo inválida en esquema: '{tok}'")
        fname = m.group(1).lower()
        raw_type = m.group(2).upper()
        # Mapear nombres SQL o VFP
        if raw_type in ("INT", "INTEGER", "I"):
            ftype = "I"
            w, d = 4, 0
        elif raw_type in ("NUMERIC", "DECIMAL", "NUMBER", "N", "FLOAT", "F", "DOUBLE", "B"):
            ftype = "N"
            w = int(m.group(3)) if m.group(3) else 12
            d = int(m.group(4)) if m.group(4) else 2
        elif raw_type in ("CURRENCY", "Y"):
            ftype = "Y"
            w, d = 14, 4
        elif raw_type in ("CHAR", "CHARACTER", "C"):
            ftype = "C"
            w = int(m.group(3)) if m.group(3) else 20
            d = 0
        elif raw_type in ("VARCHAR", "V", "TEXT", "STRING"):
            ftype = "V"
            w = int(m.group(3)) if m.group(3) else 100
            d = 0
        elif raw_type in ("MEMO", "M"):
            ftype = "M"
            w, d = 0, 0
        elif raw_type in ("LOGICAL", "BOOL", "BOOLEAN", "L"):
            ftype = "L"
            w, d = 1, 0
        elif raw_type in ("DATE", "D"):
            ftype = "D"
            w, d = 8, 0
        elif raw_type in ("DATETIME", "TIMESTAMP", "T"):
            ftype = "T"
            w, d = 19, 0
        else:
            ftype = "C"
            w = int(m.group(3)) if m.group(3) else 20
            d = 0
        fields.append(FieldDef(name=fname, ftype=ftype, width=w, decimals=d))
    return fields


class Cursor:
    """
    Representa una tabla o cursor en memoria dentro de un Área de Trabajo de FoxNext.
    """

    def __init__(self, alias: str, fields: List[FieldDef], source_path: Optional[str] = None):
        self.alias: str = alias.lower()
        self.fields: List[FieldDef] = fields
        self.field_map: Dict[str, FieldDef] = {f.name.lower(): f for f in fields}
        self.records: List[Dict[str, Any]] = []
        self.deleted_flags: List[bool] = []
        self.source_path: Optional[str] = source_path

        # Estado de navegación (1-based para RECNO)
        self._recno: int = 1
        self.bof: bool = True
        self.eof: bool = True
        self.found: bool = False

        # Índices: tag_name -> expr_str
        self.indexes: Dict[str, str] = {}
        self.active_tag: Optional[str] = None
        self._ordered_recnos: Optional[List[int]] = None

        # Relaciones hacia otros cursores: [(key_expr, target_alias)]
        self.relations: List[Tuple[str, str]] = []

        # Buffering (1 = sin buffer, 5 = buffer de tabla optimista)
        self.buffering: int = 1
        self._snapshot_records: Optional[List[Dict[str, Any]]] = None
        self._snapshot_deleted: Optional[List[bool]] = None

        # Última condición LOCATE para CONTINUE
        self._last_locate_expr: Optional[str] = None

    def set_buffering(self, mode: int) -> bool:
        self.buffering = mode
        if mode > 1:
            self._take_snapshot()
        else:
            self._snapshot_records = None
            self._snapshot_deleted = None
        return True

    def _take_snapshot(self) -> None:
        self._snapshot_records = copy.deepcopy(self.records)
        self._snapshot_deleted = list(self.deleted_flags)

    def table_update(self) -> bool:
        if self.buffering > 1:
            self._take_snapshot()
        return True

    def table_revert(self) -> bool:
        if self.buffering > 1 and self._snapshot_records is not None:
            self.records = copy.deepcopy(self._snapshot_records)
            self.deleted_flags = list(self._snapshot_deleted or [])
            self._clamp_pointer()
            return True
        return False

    def reccount(self) -> int:
        return len(self.records)

    def recno(self) -> int:
        if len(self.records) == 0:
            return 1
        return self._recno

    def is_deleted(self, recno: Optional[int] = None) -> bool:
        r = recno if recno is not None else self._recno
        if 1 <= r <= len(self.deleted_flags):
            return self.deleted_flags[r - 1]
        return False

    def visible_recnos(self, set_deleted_on: bool = False) -> List[int]:
        base = self._ordered_recnos if (self.active_tag and self._ordered_recnos is not None) else list(range(1, len(self.records) + 1))
        if not set_deleted_on:
            return base
        return [r for r in base if not self.deleted_flags[r - 1]]

    def _clamp_pointer(self, set_deleted_on: bool = False) -> None:
        vis = self.visible_recnos(set_deleted_on)
        if not vis:
            self._recno = 1
            self.bof = True
            self.eof = True
        else:
            if self._recno not in vis:
                self._recno = vis[0]
            self.bof = False
            self.eof = False

    def go_top(self, set_deleted_on: bool = False) -> None:
        vis = self.visible_recnos(set_deleted_on)
        if not vis:
            self._recno = 1
            self.bof = True
            self.eof = True
        else:
            self._recno = vis[0]
            self.bof = False
            self.eof = False

    def go_bottom(self, set_deleted_on: bool = False) -> None:
        vis = self.visible_recnos(set_deleted_on)
        if not vis:
            self._recno = 1
            self.bof = True
            self.eof = True
        else:
            self._recno = vis[-1]
            self.bof = False
            self.eof = False

    def goto(self, target_recno: int) -> None:
        if len(self.records) == 0:
            self._recno = 1
            self.bof = True
            self.eof = True
            return
        if target_recno < 1 or target_recno > len(self.records):
            raise IndexError(f"Registro fuera de rango en '{self.alias}': {target_recno} (Total: {len(self.records)})")
        self._recno = target_recno
        self.bof = False
        self.eof = False

    def skip(self, n: int = 1, set_deleted_on: bool = False) -> None:
        vis = self.visible_recnos(set_deleted_on)
        if not vis:
            self._recno = 1
            self.bof = True
            self.eof = True
            return

        if self.eof:
            if n < 0:
                idx = len(vis) + n
                if idx < 0:
                    self._recno = vis[0]
                    self.bof = True
                else:
                    self._recno = vis[idx]
                    self.eof = False
            return

        try:
            cur_pos = vis.index(self._recno)
        except ValueError:
            cur_pos = 0

        new_pos = cur_pos + n
        if new_pos >= len(vis):
            self._recno = len(self.records) + 1
            self.eof = True
            self.bof = False
        elif new_pos < 0:
            self._recno = vis[0]
            self.bof = True
            self.eof = False
        else:
            self._recno = vis[new_pos]
            self.bof = False
            self.eof = False

    def append_blank(self) -> int:
        row = {f.name: f.default_value() for f in self.fields}
        self.records.append(row)
        self.deleted_flags.append(False)
        self._recno = len(self.records)
        self.bof = False
        self.eof = False
        if self._ordered_recnos is not None:
            self._ordered_recnos.append(self._recno)
        return self._recno

    def append_dict(self, data: Dict[str, Any]) -> int:
        self.append_blank()
        for k, v in data.items():
            kl = k.lower()
            if kl in self.field_map:
                self.records[self._recno - 1][kl] = self.field_map[kl].coerce(v)
        return self._recno

    def get_field(self, field_name: str) -> Any:
        fl = field_name.lower()
        if fl not in self.field_map:
            raise KeyError(f"El campo '{field_name}' no existe en el cursor '{self.alias}'")
        if len(self.records) == 0 or self.eof or self._recno > len(self.records):
            return self.field_map[fl].default_value()
        return self.records[self._recno - 1][fl]

    def set_field(self, field_name: str, value: Any) -> None:
        fl = field_name.lower()
        if fl not in self.field_map:
            raise KeyError(f"El campo '{field_name}' no existe en el cursor '{self.alias}'")
        if len(self.records) == 0 or self.eof or self._recno > len(self.records):
            return
        self.records[self._recno - 1][fl] = self.field_map[fl].coerce(value)

    def alter_add_column(self, field_def: FieldDef) -> None:
        fl = field_def.name.lower()
        field_def.name = fl
        if fl in self.field_map:
            raise ValueError(f"La columna '{fl}' ya existe en el cursor '{self.alias}'.")
        self.fields.append(field_def)
        self.field_map[fl] = field_def
        default_v = field_def.default_value()
        for rec in self.records:
            rec[fl] = default_v

    def alter_drop_column(self, col_name: str) -> None:
        fl = col_name.strip().lower()
        if fl not in self.field_map:
            raise KeyError(f"La columna '{col_name}' no existe en el cursor '{self.alias}'.")
        self.fields = [f for f in self.fields if f.name != fl]
        self.field_map.pop(fl, None)
        for rec in self.records:
            rec.pop(fl, None)

    def copy_to_array(self, set_deleted_on: bool = False) -> List[List[Any]]:
        vis = self.visible_recnos(set_deleted_on)
        result: List[List[Any]] = []
        for r in vis:
            rec = self.records[r - 1]
            result.append([rec.get(f.name) for f in self.fields])
        return result

    def append_from_array(self, arr_data: Any) -> int:
        if not isinstance(arr_data, list) or not arr_data:
            return 0
        # Si es un arreglo 1D de valores escalares, lo tratamos como una sola fila
        rows = arr_data if isinstance(arr_data[0], (list, tuple)) else [arr_data]
        added = 0
        for row_vals in rows:
            self.append_blank()
            for idx, f in enumerate(self.fields):
                if idx < len(row_vals):
                    self.records[self._recno - 1][f.name] = f.coerce(row_vals[idx])
            added += 1
        return added

    def delete_current(self) -> None:
        if 1 <= self._recno <= len(self.deleted_flags):
            self.deleted_flags[self._recno - 1] = True

    def recall_current(self) -> None:
        if 1 <= self._recno <= len(self.deleted_flags):
            self.deleted_flags[self._recno - 1] = False

    def pack(self) -> int:
        new_recs = []
        new_dels = []
        removed = 0
        for rec, is_del in zip(self.records, self.deleted_flags):
            if is_del:
                removed += 1
            else:
                new_recs.append(rec)
                new_dels.append(False)
        self.records = new_recs
        self.deleted_flags = new_dels
        self._ordered_recnos = None
        self.go_top()
        return removed

    def zap(self) -> None:
        self.records.clear()
        self.deleted_flags.clear()
        self._ordered_recnos = None
        self._recno = 1
        self.bof = True
        self.eof = True
        self.found = False

    def build_index(self, tag_name: str, expr_str: str, eval_fn: Callable[[str], Any]) -> None:
        tag = tag_name.lower()
        self.indexes[tag] = expr_str
        self.active_tag = tag
        self.recompute_index(eval_fn)

    def recompute_index(self, eval_fn: Callable[[str], Any]) -> None:
        if not self.active_tag or self.active_tag not in self.indexes:
            self._ordered_recnos = None
            return
        expr_str = self.indexes[self.active_tag]
        saved_rec = self._recno
        saved_bof = self.bof
        saved_eof = self.eof

        keyed: List[Tuple[Any, int]] = []
        for r in range(1, len(self.records) + 1):
            self._recno = r
            self.bof = False
            self.eof = False
            val = eval_fn(expr_str)
            keyed.append((val if val is not None else "", r))

        keyed.sort(key=lambda item: (str(type(item[0])), item[0]))
        self._ordered_recnos = [r for _, r in keyed]

        self._recno = saved_rec
        self.bof = saved_bof
        self.eof = saved_eof

    def seek(self, target_val: Any, eval_fn: Callable[[str], Any], set_deleted_on: bool = False) -> bool:
        if not self.active_tag or self.active_tag not in self.indexes:
            raise RuntimeError(f"El cursor '{self.alias}' no tiene un índice activo (SET ORDER TO) para SEEK.")
        expr_str = self.indexes[self.active_tag]
        self.recompute_index(eval_fn)
        for r in self.visible_recnos(set_deleted_on):
            self._recno = r
            self.bof = False
            self.eof = False
            cur_val = eval_fn(expr_str)
            if isinstance(cur_val, str) and isinstance(target_val, str):
                match = cur_val.rstrip() == target_val.rstrip() or cur_val.startswith(target_val)
            else:
                match = cur_val == target_val
            if match:
                self.found = True
                return True
        self._recno = len(self.records) + 1
        self.eof = True
        self.found = False
        return False

    def format_browse_table(self, set_deleted_on: bool = False, max_rows: int = 100) -> str:
        """
        Genera una tabla visual enriquecida (estilo BROWSE TUI) con indicador de registro activo '>' y borrado '*'.
        """
        headers = ["Rec#", "Del"] + [f.name for f in self.fields]
        vis = self.visible_recnos(set_deleted_on)[:max_rows]

        rows_str: List[List[str]] = []
        for r in vis:
            rec = self.records[r - 1]
            is_del = self.deleted_flags[r - 1]
            pointer = ">" if (r == self._recno and not self.eof) else " "
            rec_col = f"{pointer}{r}"
            del_col = " * " if is_del else "   "
            vals = [rec_col, del_col]
            for f in self.fields:
                v = rec.get(f.name)
                if f.ftype == "L":
                    s = ".T." if v else ".F."
                elif f.ftype == "Y" and v is not None:
                    s = f"${float(v):,.2f}"
                elif f.ftype == "N" and v is not None and f.decimals > 0:
                    s = f"{float(v):.{f.decimals}f}"
                elif v is None:
                    s = ""
                else:
                    s = str(v)
                vals.append(s)
            rows_str.append(vals)

        col_widths = [len(h) for h in headers]
        for row in rows_str:
            for idx, cell in enumerate(row):
                col_widths[idx] = max(col_widths[idx], min(42, len(cell)))

        sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
        title = f" BROWSE: {self.alias.upper()} (Registros: {len(vis)}/{len(self.records)} | RECNO: {self.recno()} | EOF: {'.T.' if self.eof else '.F.'}) "
        lines = [sep, title, sep]
        header_line = "|" + "|".join(f" {headers[i]:<{col_widths[i]}} " for i in range(len(headers))) + "|"
        lines.append(header_line)
        lines.append(sep)
        if not rows_str:
            empty_msg = "(Cursor vacío)"
            total_w = max(len(empty_msg), sum(col_widths) + 3 * len(col_widths) - 1)
            lines.append(f"| {empty_msg:<{total_w - 2}} |")
        else:
            for row in rows_str:
                cells = []
                for i, cell in enumerate(row):
                    clipped = cell[:42]
                    cells.append(f" {clipped:<{col_widths[i]}} ")
                lines.append("|" + "|".join(cells) + "|")
        lines.append(sep)
        return "\n".join(lines)

    def format_structure(self) -> str:
        lines = [
            f"Estructura del Cursor: {self.alias.upper()}",
            f"Número de registros:   {self.reccount()}",
            "------------------------------------------------",
            f"{'#':<4} {'Campo':<18} {'Tipo':<8} {'Ancho':<8} {'Dec':<5}",
            "------------------------------------------------",
        ]
        for idx, f in enumerate(self.fields, start=1):
            lines.append(f"{idx:<4} {f.name:<18} {f.ftype:<8} {f.width:<8} {f.decimals:<5}")
        lines.append("------------------------------------------------")
        return "\n".join(lines)


class WorkAreaManager:
    """
    Administra las áreas de trabajo (1..32767), el cursor activo y las consultas SQL nativas.
    """

    def __init__(self) -> None:
        self.work_areas: Dict[int, Cursor] = {}
        self.alias_to_area: Dict[str, int] = {}
        self.current_area: int = 1
        self.set_deleted: bool = False  # SET DELETED OFF por defecto en VFP
        self._sql_connections: Dict[int, sqlite3.Connection] = {}
        self._next_sql_handle: int = 1
        self._txn_stack: List[Dict[int, Tuple[List[Dict[str, Any]], List[bool], int, bool, bool]]] = []
        self.sql_views: Dict[str, str] = {}

    def create_sql_view(self, view_name: str, select_sql: str, variables: Dict[str, Any]) -> Cursor:
        """
        Registra una Vista SQL parametrizada (`CREATE SQL VIEW <name> AS SELECT ...`)
        y abre/ejecuta inicialmente su cursor asociado.
        """
        vname = view_name.strip().lower()
        self.sql_views[vname] = select_sql.strip()
        return self.execute_sql_select(select_sql, vname, variables)

    def requery_view(self, alias_or_area: Any, variables: Dict[str, Any]) -> int:
        """
        Refresca dinámicamente una Vista SQL (`REQUERY([alias])`) re-evaluando sus parámetros `?var`.
        Devuelve 1 si se refrescó con éxito, 0 en caso contrario.
        """
        cur = self.get_cursor(alias_or_area) if alias_or_area is not None else self.current_cursor()
        vname = cur.alias.lower() if cur else (str(alias_or_area).strip().lower() if alias_or_area else "")
        if not vname or vname not in self.sql_views:
            return 0
        sql_def = self.sql_views[vname]
        self.execute_sql_select(sql_def, vname, variables)
        return 1

    def begin_transaction(self) -> int:
        snap: Dict[int, Tuple[List[Dict[str, Any]], List[bool], int, bool, bool]] = {}
        for area, cur in self.work_areas.items():
            snap[area] = (
                copy.deepcopy(cur.records),
                list(cur.deleted_flags),
                cur._recno,
                cur.bof,
                cur.eof,
            )
        self._txn_stack.append(snap)
        return len(self._txn_stack)

    def end_transaction(self) -> int:
        if not self._txn_stack:
            raise RuntimeError("END TRANSACTION invocado sin un BEGIN TRANSACTION activo.")
        self._txn_stack.pop()
        return len(self._txn_stack)

    def rollback(self) -> int:
        if not self._txn_stack:
            raise RuntimeError("ROLLBACK invocado sin un BEGIN TRANSACTION activo.")
        snap = self._txn_stack.pop()
        for area, state in snap.items():
            if area in self.work_areas:
                cur = self.work_areas[area]
                cur.records = state[0]
                cur.deleted_flags = state[1]
                cur._recno = state[2]
                cur.bof = state[3]
                cur.eof = state[4]
        return len(self._txn_stack)

    def txn_level(self) -> int:
        return len(self._txn_stack)

    def cursor_to_json(self, alias_or_area: Any = None) -> str:
        cur = self.get_cursor(alias_or_area) if alias_or_area is not None else self.current_cursor()
        if cur is None:
            raise RuntimeError("CURSORTOJSON requiere un cursor abierto.")
        vis = cur.visible_recnos(self.set_deleted)
        rows = []
        for r in vis:
            raw_row = cur.records[r - 1]
            clean = {}
            for f in cur.fields:
                v = raw_row.get(f.name)
                if isinstance(v, (datetime.date, datetime.datetime)):
                    clean[f.name] = v.isoformat()
                else:
                    clean[f.name] = v
            rows.append(clean)
        return json.dumps(rows, ensure_ascii=False)

    def json_to_cursor(self, json_str: str, cursor_name: str = "jsonresult") -> int:
        data = json.loads(str(json_str))
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    data = v
                    break
            else:
                data = [data]
        if not isinstance(data, list):
            raise ValueError("JSONTOCURSOR requiere un arreglo JSON de objetos.")

        col_order: List[str] = []
        sample_vals: Dict[str, Any] = {}
        for item in data:
            if isinstance(item, dict):
                for k, v in item.items():
                    kl = str(k).lower()
                    if kl not in col_order:
                        col_order.append(kl)
                    if kl not in sample_vals and v is not None:
                        sample_vals[kl] = v

        fields: List[FieldDef] = []
        for col in col_order:
            sv = sample_vals.get(col)
            if isinstance(sv, bool):
                fields.append(FieldDef(col, "L", 1, 0))
            elif isinstance(sv, int):
                fields.append(FieldDef(col, "I", 10, 0))
            elif isinstance(sv, float):
                fields.append(FieldDef(col, "N", 14, 2))
            else:
                fields.append(FieldDef(col, "V", 120, 0))

        cur = Cursor((cursor_name or "jsonresult").lower(), fields)
        for item in data:
            if isinstance(item, dict):
                cur.append_dict({str(k).lower(): v for k, v in item.items()})
        cur.go_top(self.set_deleted)
        self.open_cursor_in_current_or_new(cur, in_free_area=True)
        return cur.reccount()

    def sql_connect(self, conn_str: str = ":memory:") -> int:
        """
        Abre una conexión SQL Pass-Through (SQLCONNECT / SQLSTRINGCONNECT) y devuelve un handle entero (> 0).
        Soporta rutas a bases SQLite o cadenas estilo 'Driver=SQLite;Database=archivo.db'.
        """
        raw = str(conn_str or ":memory:").strip()
        db_target = ":memory:"
        if ";" in raw or "=" in raw:
            for part in raw.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    if k.strip().lower() in ("database", "dbq", "datasource", "data source"):
                        db_target = v.strip()
        elif raw:
            db_target = raw

        try:
            conn = sqlite3.connect(db_target)
            conn.row_factory = sqlite3.Row
            handle = self._next_sql_handle
            self._next_sql_handle += 1
            self._sql_connections[handle] = conn
            return handle
        except Exception:
            return -1

    def sql_disconnect(self, handle: int) -> int:
        h = int(handle)
        if h == 0:
            for c in self._sql_connections.values():
                c.close()
            self._sql_connections.clear()
            return 1
        conn = self._sql_connections.pop(h, None)
        if conn is None:
            return -1
        conn.close()
        return 1

    def sql_exec(self, handle: int, sql_stmt: str, cursor_name: str = "sqlresult", variables: Optional[Dict[str, Any]] = None) -> int:
        """
        Ejecuta una sentencia SQL en el servidor conectado (SQLEXEC).
        Si la consulta devuelve filas (SELECT), las carga automáticamente en el cursor `cursor_name`.
        Devuelve el número de cursores/filas afectados (>= 1 en éxito, -1 en error).
        """
        conn = self._sql_connections.get(int(handle))
        if conn is None:
            return -1
        try:
            params: Dict[str, Any] = {}
            if variables:
                for k, v in variables.items():
                    if isinstance(v, bool):
                        params[k] = 1 if v else 0
                    elif isinstance(v, (datetime.date, datetime.datetime)):
                        params[k] = v.isoformat()
                    elif isinstance(v, (int, float, str)) or v is None:
                        params[k] = v

            # Soportar parámetros estilo VFP `?variable` o `:variable`
            processed = re.sub(
                r"\?([A-Za-z_][A-Za-z0-9_]*)",
                lambda m: f":{m.group(1).lower()}",
                sql_stmt,
            )
            cur_sql = conn.execute(processed, params)
            if cur_sql.description:
                rows = cur_sql.fetchall()
                col_names = [d[0].lower() for d in cur_sql.description]
                fields: List[FieldDef] = []
                for idx, col in enumerate(col_names):
                    sample = next((r[idx] for r in rows if r[idx] is not None), None)
                    if isinstance(sample, int):
                        fields.append(FieldDef(col, "I", 10, 0))
                    elif isinstance(sample, float):
                        fields.append(FieldDef(col, "N", 14, 2))
                    else:
                        fields.append(FieldDef(col, "V", 100, 0))
                res_cur = Cursor((cursor_name or "sqlresult").lower(), fields)
                for r in rows:
                    res_cur.append_dict({col_names[i]: r[i] for i in range(len(col_names))})
                res_cur.go_top(self.set_deleted)
                self.open_cursor_in_current_or_new(res_cur, in_free_area=True)
                return 1
            else:
                conn.commit()
                return max(1, cur_sql.rowcount if cur_sql.rowcount >= 0 else 1)
        except Exception:
            return -1

    def current_cursor(self) -> Optional[Cursor]:
        return self.work_areas.get(self.current_area)

    def get_cursor(self, alias_or_area: str | int | None = None) -> Optional[Cursor]:
        if alias_or_area is None:
            return self.current_cursor()
        if isinstance(alias_or_area, int):
            return self.work_areas.get(alias_or_area)
        s = str(alias_or_area).strip()
        if s.isdigit():
            return self.work_areas.get(int(s))
        area = self.alias_to_area.get(s.lower())
        if area is not None:
            return self.work_areas.get(area)
        return None

    def next_free_area(self) -> int:
        area = 1
        while area in self.work_areas:
            area += 1
        return area

    def select_area(self, target: str | int) -> int:
        if isinstance(target, int) or (isinstance(target, str) and target.strip().isdigit()):
            num = int(target)
            if num == 0:
                self.current_area = self.next_free_area()
            else:
                self.current_area = num
            return self.current_area

        alias = str(target).strip().lower()
        if alias in self.alias_to_area:
            self.current_area = self.alias_to_area[alias]
            return self.current_area
        raise KeyError(f"El alias '{target}' no está abierto en ningún área de trabajo.")

    def open_cursor_in_current_or_new(self, cursor: Cursor, in_free_area: bool = False) -> int:
        alias = cursor.alias.lower()
        if alias in self.alias_to_area:
            old_area = self.alias_to_area[alias]
            del self.work_areas[old_area]
            del self.alias_to_area[alias]

        area = self.next_free_area() if in_free_area else self.current_area
        self.work_areas[area] = cursor
        self.alias_to_area[alias] = area
        self.current_area = area
        return area

    def close_alias(self, alias: Optional[str] = None) -> None:
        if alias is None:
            cur = self.current_cursor()
            if cur:
                del self.alias_to_area[cur.alias]
                del self.work_areas[self.current_area]
            return
        al = alias.lower()
        if al in self.alias_to_area:
            area = self.alias_to_area.pop(al)
            self.work_areas.pop(area, None)

    def close_all(self) -> None:
        self.work_areas.clear()
        self.alias_to_area.clear()
        self.current_area = 1

    def sync_relations(self, eval_fn: Callable[[str], Any]) -> None:
        """
        Sincroniza los cursores hijos cuando el cursor padre tiene SET RELATION activo.
        """
        cur = self.current_cursor()
        if not cur or not cur.relations:
            return
        saved_area = self.current_area
        try:
            for key_expr, target_alias in cur.relations:
                key_val = eval_fn(key_expr)
                target_cur = self.get_cursor(target_alias)
                if target_cur and target_cur.active_tag:
                    self.select_area(target_alias)
                    target_cur.seek(key_val, eval_fn, self.set_deleted)
                elif target_cur and isinstance(key_val, int):
                    if 1 <= key_val <= target_cur.reccount():
                        target_cur.goto(key_val)
        finally:
            self.current_area = saved_area

    def _build_sqlite_bridge(self) -> sqlite3.Connection:
        """
        Vuelca todos los cursores activos a un motor SQLite en memoria para ejecutar SQL relacional nativo.
        """
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        for alias, area in self.alias_to_area.items():
            cur = self.work_areas[area]
            col_defs = []
            for f in cur.fields:
                if f.ftype == "I":
                    sql_t = "INTEGER"
                elif f.ftype in ("N", "F", "B", "Y"):
                    sql_t = "REAL"
                elif f.ftype == "L":
                    sql_t = "INTEGER"
                else:
                    sql_t = "TEXT"
                col_defs.append(f'"{f.name}" {sql_t}')
            create_sql = f'CREATE TABLE "{alias}" ({", ".join(col_defs)})'
            conn.execute(create_sql)

            vis_recnos = cur.visible_recnos(self.set_deleted)
            if vis_recnos and cur.fields:
                placeholders = ", ".join(["?"] * len(cur.fields))
                insert_sql = f'INSERT INTO "{alias}" VALUES ({placeholders})'
                batch = []
                for r in vis_recnos:
                    row = cur.records[r - 1]
                    tup = []
                    for f in cur.fields:
                        val = row.get(f.name)
                        if f.ftype == "L":
                            tup.append(1 if val else 0)
                        elif isinstance(val, (datetime.date, datetime.datetime)):
                            tup.append(val.isoformat())
                        else:
                            tup.append(val)
                    batch.append(tuple(tup))
                conn.executemany(insert_sql, batch)
        conn.commit()
        return conn

    def execute_sql_select(
        self,
        sql_query: str,
        into_cursor_name: Optional[str],
        variables: Dict[str, Any],
    ) -> Cursor:
        """
        Ejecuta una sentencia SELECT nativa (con variables locales embebidas) y devuelve un nuevo Cursor.
        """
        conn = self._build_sqlite_bridge()
        try:
            # Sustituir variables conocidas en el SQL por parámetros seguros :var_name
            params: Dict[str, Any] = {}
            for k, v in variables.items():
                if isinstance(v, bool):
                    params[k] = 1 if v else 0
                elif isinstance(v, (datetime.date, datetime.datetime)):
                    params[k] = v.isoformat()
                elif isinstance(v, (int, float, str)) or v is None:
                    params[k] = v

            # Reemplazar prefijo ?variable o m.variable por :variable y variables sueltas
            processed_sql = re.sub(r"\?([A-Za-z_][A-Za-z0-9_]*)\b", lambda m: f":{m.group(1).lower()}", sql_query)
            processed_sql = re.sub(r"\bm\.([A-Za-z_][A-Za-z0-9_]*)\b", lambda m: f":{m.group(1).lower()}", processed_sql)
            for var_name in sorted(params.keys(), key=len, reverse=True):
                # Evitar reemplazar nombres de tablas o columnas si coinciden con un cursor
                if var_name in self.alias_to_area:
                    continue
                processed_sql = re.sub(
                    rf"(?<![:.\w])\b{re.escape(var_name)}\b(?![.\w])",
                    f":{var_name}",
                    processed_sql,
                    flags=re.IGNORECASE,
                )

            cur_sql = conn.execute(processed_sql, params)
            rows = cur_sql.fetchall()
            col_names = [desc[0].lower() for desc in (cur_sql.description or [])]

            # Inferir tipos de campo del cursor resultante
            inferred_fields: List[FieldDef] = []
            for idx, col in enumerate(col_names):
                sample_val = None
                for r in rows:
                    if r[idx] is not None:
                        sample_val = r[idx]
                        break
                if isinstance(sample_val, int):
                    inferred_fields.append(FieldDef(col, "I", 10, 0))
                elif isinstance(sample_val, float):
                    inferred_fields.append(FieldDef(col, "N", 14, 2))
                else:
                    inferred_fields.append(FieldDef(col, "V", 100, 0))

            target_alias = (into_cursor_name or "query").lower()
            result_cursor = Cursor(target_alias, inferred_fields)
            for r in rows:
                row_dict = {col_names[i]: r[i] for i in range(len(col_names))}
                result_cursor.append_dict(row_dict)
            result_cursor.go_top(self.set_deleted)
            self.open_cursor_in_current_or_new(result_cursor, in_free_area=True)
            return result_cursor
        finally:
            conn.close()

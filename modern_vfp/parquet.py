"""
Exportador e Importador Parquet / Columnar Binario (`modern_vfp/parquet.py`) para FoxNext.
Permite interoperabilidad de Big Data de 64 bits con almacenes analíticos y Data Lakes.
Funciona sin dependencias externas obligatorias (Pure Python stdlib) y aprovecha `pyarrow` si está disponible.
"""

from __future__ import annotations
import datetime
import json
from pathlib import Path
import struct
from typing import Any, Dict, List, Optional

from .cursor import Cursor, FieldDef

PARQUET_MAGIC = b"PAR1"


def _has_pyarrow() -> bool:
    try:
        import pyarrow  # type: ignore
        import pyarrow.parquet  # type: ignore
        return True
    except ImportError:
        return False


def write_parquet(cur: Cursor, filepath: str | Path, set_deleted_on: bool = False) -> int:
    """
    Exporta el cursor de 64 bits a un archivo Parquet / Columnar Binario de alto rendimiento.
    """
    path = Path(filepath)
    vis = cur.visible_recnos(set_deleted_on)
    records = [cur.records[r - 1] for r in vis]

    if _has_pyarrow():
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore

        arrow_cols = {}
        for f in cur.fields:
            vals = [rec.get(f.name) for rec in records]
            if f.ftype == "I":
                arrow_cols[f.name] = pa.array(vals, type=pa.int64())
            elif f.ftype in ("N", "F", "B", "Y"):
                arrow_cols[f.name] = pa.array(vals, type=pa.float64())
            elif f.ftype == "L":
                arrow_cols[f.name] = pa.array(vals, type=pa.bool_())
            else:
                arrow_cols[f.name] = pa.array([str(v or "") for v in vals], type=pa.string())
        table = pa.Table.from_pydict(arrow_cols)
        pq.write_table(table, str(path))
        return len(records)

    # Implementación pura en Python con cabecera y trailer PAR1
    schema_info = [
        {"name": f.name, "type": f.ftype, "width": f.width, "decimals": f.decimals}
        for f in cur.fields
    ]
    meta_payload = {
        "format": "FoxNext_Columnar_Parquet_v1",
        "alias": cur.alias,
        "rowCount": len(records),
        "schema": schema_info,
    }
    meta_bytes = json.dumps(meta_payload, ensure_ascii=False).encode("utf-8")

    # Serializar columnas
    col_chunks: List[bytes] = []
    for f in cur.fields:
        c_vals = [rec.get(f.name) for rec in records]
        c_data = json.dumps(c_vals, default=str, ensure_ascii=False).encode("utf-8")
        col_chunks.append(struct.pack("<I", len(c_data)) + c_data)

    body = b"".join(col_chunks)
    meta_len = len(meta_bytes)
    footer = meta_bytes + struct.pack("<I", meta_len) + PARQUET_MAGIC

    payload = PARQUET_MAGIC + body + footer
    path.write_bytes(payload)
    return len(records)


def read_parquet(filepath: str | Path, cursor_name: str = "parquetresult") -> Cursor:
    """
    Importa un archivo Parquet / Columnar Binario a un Cursor de 64 bits de FoxNext.
    """
    path = Path(filepath)
    if _has_pyarrow():
        import pyarrow.parquet as pq  # type: ignore

        tbl = pq.read_table(str(path))
        data_dict = tbl.to_pydict()
        fields: List[FieldDef] = []
        for col_name, col_data in data_dict.items():
            sample = next((v for v in col_data if v is not None), None)
            if isinstance(sample, int):
                fields.append(FieldDef(col_name.lower(), "I", 10, 0))
            elif isinstance(sample, float):
                fields.append(FieldDef(col_name.lower(), "N", 14, 2))
            elif isinstance(sample, bool):
                fields.append(FieldDef(col_name.lower(), "L", 1, 0))
            else:
                fields.append(FieldDef(col_name.lower(), "V", 120, 0))

        cur = Cursor(cursor_name.lower(), fields)
        row_count = tbl.num_rows
        for row_idx in range(row_count):
            row_dict = {col: data_dict[col][row_idx] for col in data_dict}
            cur.append_dict(row_dict)
        cur.go_top()
        return cur

    raw = path.read_bytes()
    if not raw.startswith(PARQUET_MAGIC) or not raw.endswith(PARQUET_MAGIC):
        raise ValueError(f"El archivo '{path}' no tiene la firma válida de Parquet (PAR1).")

    footer_len = struct.unpack("<I", raw[-8:-4])[0]
    meta_raw = raw[-(8 + footer_len):-8]
    meta = json.loads(meta_raw.decode("utf-8"))

    fields: List[FieldDef] = [
        FieldDef(f["name"].lower(), f["type"], f.get("width", 10), f.get("decimals", 0))
        for f in meta.get("schema", [])
    ]
    cur = Cursor(cursor_name.lower(), fields)

    offset = len(PARQUET_MAGIC)
    col_arrays: List[List[Any]] = []
    for _ in fields:
        chunk_len = struct.unpack("<I", raw[offset : offset + 4])[0]
        offset += 4
        chunk_data = raw[offset : offset + chunk_len]
        offset += chunk_len
        col_arrays.append(json.loads(chunk_data.decode("utf-8")))

    num_rows = meta.get("rowCount", 0)
    for row_idx in range(num_rows):
        cur.append_blank()
        for c_idx, f in enumerate(fields):
            val = col_arrays[c_idx][row_idx] if row_idx < len(col_arrays[c_idx]) else None
            cur.records[cur._recno - 1][f.name] = f.coerce(val)

    cur.go_top()
    return cur

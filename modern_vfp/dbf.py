"""
Módulo de compatibilidad DBF / CSV / JSON para FoxNext (Modern VFP).
Soporta lectura y escritura nativa de archivos .dbf (dBASE III+ / VFP) con codificación UTF-8 / CP1252,
así como importación y exportación CSV y JSON para COPY TO y APPEND FROM.
"""

from __future__ import annotations
import csv
import datetime
import json
import struct
from pathlib import Path
from typing import Any, List, Tuple, Dict


def write_dbf(filepath: str | Path, fields: List[Dict[str, Any]], rows: List[Dict[str, Any]], deleted_flags: List[bool] | None = None) -> int:
    """
    Escribe un archivo binario .dbf compatible con Visual FoxPro / dBASE III+.
    fields: lista de dicts con {"name": str, "type": str, "width": int, "decimals": int}
    rows: lista de dicts con los valores de cada fila.
    """
    path = Path(filepath)
    now = datetime.date.today()
    num_records = len(rows)
    num_fields = len(fields)

    field_specs = []
    record_len = 1  # 1 byte para el indicador de borrado (' ' o '*')
    for f in fields:
        fname = f["name"][:10].upper()
        ftype = f["type"].upper()
        width = f.get("width", 10)
        decimals = f.get("decimals", 0)

        if ftype in ("I",):
            dbf_type = b"N"
            width = max(width, 11)
            decimals = 0
        elif ftype in ("N", "F", "B", "Y"):
            dbf_type = b"N"
            width = max(width, 12)
            decimals = decimals if ftype != "Y" else 4
        elif ftype == "L":
            dbf_type = b"L"
            width = 1
            decimals = 0
        elif ftype == "D":
            dbf_type = b"D"
            width = 8
            decimals = 0
        elif ftype == "T":
            dbf_type = b"C"
            width = 19
            decimals = 0
        else:
            dbf_type = b"C"
            width = max(1, min(width, 254))
            decimals = 0

        field_specs.append((fname, dbf_type, width, decimals, f["name"]))
        record_len += width

    header_len = 32 + (32 * num_fields) + 1

    with open(path, "wb") as fp:
        header = struct.pack(
            "<BBBBIHH20x",
            0x03,
            now.year - 1900,
            now.month,
            now.day,
            num_records,
            header_len,
            record_len,
        )
        fp.write(header)

        for fname, dbf_type, width, decimals, _ in field_specs:
            name_bytes = fname.encode("ascii", errors="ignore").ljust(11, b"\x00")
            fdesc = struct.pack("<11sc4xBB14x", name_bytes, dbf_type, width, decimals)
            fp.write(fdesc)

        fp.write(b"\x0d")

        for idx, row in enumerate(rows):
            is_del = deleted_flags[idx] if deleted_flags and idx < len(deleted_flags) else False
            fp.write(b"*" if is_del else b" ")

            for fname, dbf_type, width, decimals, orig_name in field_specs:
                val = row.get(orig_name)
                if dbf_type == b"N":
                    if val is None or val == "":
                        s = " " * width
                    elif decimals > 0:
                        s = f"{float(val):>{width}.{decimals}f}"
                    else:
                        s = f"{int(round(float(val))):>{width}d}"
                    raw = s[:width].rjust(width, " ").encode("ascii", errors="replace")
                elif dbf_type == b"L":
                    raw = b"T" if bool(val) else b"F"
                elif dbf_type == b"D":
                    if isinstance(val, (datetime.date, datetime.datetime)):
                        raw = val.strftime("%Y%m%d").encode("ascii")
                    elif isinstance(val, str) and len(val) >= 8:
                        clean = val.replace("-", "").replace("/", "")[:8]
                        raw = clean.ljust(8, " ").encode("ascii")
                    else:
                        raw = b"        "
                else:
                    text = "" if val is None else str(val)
                    encoded = text.encode("utf-8", errors="replace")[:width]
                    raw = encoded.ljust(width, b" ")
                fp.write(raw)

        fp.write(b"\x1a")

    return num_records


def read_dbf(filepath: str | Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[bool]]:
    """
    Lee un archivo binario .dbf y devuelve (fields, rows, deleted_flags).
    """
    path = Path(filepath)
    with open(path, "rb") as fp:
        header = fp.read(32)
        if len(header) < 32:
            raise ValueError(f"Archivo DBF inválido o truncado: {path}")

        version, yy, mm, dd, num_records, header_len, record_len = struct.unpack("<BBBBIHH20x", header)

        fields: List[Dict[str, Any]] = []
        while True:
            peek = fp.read(1)
            if not peek or peek == b"\x0d":
                break
            rest = fp.read(31)
            fdesc = peek + rest
            name_bytes, dbf_type, width, decimals = struct.unpack("<11sc4xBB14x", fdesc)
            fname = name_bytes.split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip().lower()
            t_char = dbf_type.decode("ascii", errors="ignore").upper()

            if t_char == "N" and decimals == 0:
                vfp_type = "I"
            elif t_char in ("N", "F", "B"):
                vfp_type = "N"
            elif t_char == "L":
                vfp_type = "L"
            elif t_char == "D":
                vfp_type = "D"
            else:
                vfp_type = "C"

            fields.append({
                "name": fname,
                "type": vfp_type,
                "width": width,
                "decimals": decimals,
                "dbf_type": t_char,
            })

        fp.seek(header_len)
        rows: List[Dict[str, Any]] = []
        deleted_flags: List[bool] = []

        for _ in range(num_records):
            rec_bytes = fp.read(record_len)
            if not rec_bytes or len(rec_bytes) < record_len:
                break
            del_flag = rec_bytes[0:1] == b"*"
            deleted_flags.append(del_flag)

            offset = 1
            row: Dict[str, Any] = {}
            for f in fields:
                w = f["width"]
                chunk = rec_bytes[offset:offset + w]
                offset += w
                t_char = f["dbf_type"]
                text = chunk.decode("utf-8", errors="replace").strip()

                if t_char in ("N", "F"):
                    if not text:
                        row[f["name"]] = 0 if f["decimals"] == 0 else 0.0
                    elif f["decimals"] == 0:
                        try:
                            row[f["name"]] = int(float(text))
                        except ValueError:
                            row[f["name"]] = 0
                    else:
                        try:
                            row[f["name"]] = float(text)
                        except ValueError:
                            row[f["name"]] = 0.0
                elif t_char == "L":
                    row[f["name"]] = text.upper() in ("T", "Y", "1")
                elif t_char == "D":
                    if len(text) == 8 and text.isdigit():
                        try:
                            row[f["name"]] = datetime.date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
                        except ValueError:
                            row[f["name"]] = None
                    else:
                        row[f["name"]] = None
                else:
                    row[f["name"]] = chunk.decode("utf-8", errors="replace").rstrip(" ")

            rows.append(row)

    for f in fields:
        f.pop("dbf_type", None)

    return fields, rows, deleted_flags


def export_csv(filepath: str | Path, fields: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> int:
    path = Path(filepath)
    field_names = [f["name"] for f in fields]
    with open(path, "w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=field_names)
        writer.writeheader()
        for r in rows:
            clean = {}
            for k in field_names:
                v = r.get(k)
                if isinstance(v, (datetime.date, datetime.datetime)):
                    clean[k] = v.isoformat()
                else:
                    clean[k] = v
            writer.writerow(clean)
    return len(rows)


def import_csv(filepath: str | Path) -> List[Dict[str, Any]]:
    path = Path(filepath)
    with open(path, "r", newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        return [{k.strip().lower(): v for k, v in row.items() if k} for row in reader]


def export_json(filepath: str | Path, rows: List[Dict[str, Any]]) -> int:
    path = Path(filepath)

    def _default(obj: Any) -> Any:
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        return str(obj)

    with open(path, "w", encoding="utf-8") as fp:
        json.dump(rows, fp, ensure_ascii=False, indent=2, default=_default)
    return len(rows)


def import_json(filepath: str | Path) -> List[Dict[str, Any]]:
    path = Path(filepath)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                data = v
                break
    if not isinstance(data, list):
        raise ValueError(f"El archivo JSON '{path}' no contiene una lista de registros.")
    return [{str(k).lower(): v for k, v in item.items()} for item in data if isinstance(item, dict)]

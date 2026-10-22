"""
Generador y Lector Nativo Microsoft Excel OpenXML (.xlsx) para FoxNext / Modern VFP.
Permite exportar e importar hojas de cálculo sin dependencias de terceros (Pure Python stdlib via zipfile y XML).
Soporta:
  COPY TO <archivo.xlsx> TYPE XLSX
  APPEND FROM <archivo.xlsx> TYPE XLSX
"""

from __future__ import annotations
import datetime
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Dict, List, Optional

from .cursor import Cursor, FieldDef


def _col_num_to_letter(col_idx: int) -> str:
    """Convierte índice 0-based a letra de columna Excel (0 -> A, 1 -> B, 26 -> AA)."""
    result = ""
    col_idx += 1
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result = chr(65 + remainder) + result
    return result


def write_xlsx(cur: Cursor, filepath: str | Path, set_deleted_on: bool = False) -> int:
    """
    Exporta un cursor a un libro de Microsoft Excel (.xlsx) nativo y válido.
    """
    path = Path(filepath)
    if not path.suffix:
        path = path.with_suffix(".xlsx")

    vis = cur.visible_recnos(set_deleted_on)
    records = [cur.records[r - 1] for r in vis]

    # Construir xl/worksheets/sheet1.xml
    sheet_lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        '<sheetData>',
    ]

    # Fila 1: Encabezados de columnas
    sheet_lines.append('<row r="1">')
    for c_idx, f in enumerate(cur.fields):
        cell_ref = f"{_col_num_to_letter(c_idx)}1"
        header_val = f.name.upper()
        sheet_lines.append(f'<c r="{cell_ref}" t="inlineStr"><is><t>{header_val}</t></is></c>')
    sheet_lines.append('</row>')

    # Filas de datos
    for r_idx, rec in enumerate(records, start=2):
        sheet_lines.append(f'<row r="{r_idx}">')
        for c_idx, f in enumerate(cur.fields):
            cell_ref = f"{_col_num_to_letter(c_idx)}{r_idx}"
            v = rec.get(f.name)
            if v is None:
                continue
            if isinstance(v, bool):
                b_val = "1" if v else "0"
                sheet_lines.append(f'<c r="{cell_ref}" t="b"><v>{b_val}</v></c>')
            elif isinstance(v, (int, float)):
                sheet_lines.append(f'<c r="{cell_ref}"><v>{v}</v></c>')
            elif isinstance(v, (datetime.date, datetime.datetime)):
                sheet_lines.append(f'<c r="{cell_ref}" t="inlineStr"><is><t>{v.isoformat()}</t></is></c>')
            else:
                text_esc = str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                sheet_lines.append(f'<c r="{cell_ref}" t="inlineStr"><is><t>{text_esc}</t></is></c>')
        sheet_lines.append('</row>')

    sheet_lines.append('</sheetData>')
    sheet_lines.append('</worksheet>')
    sheet_xml = "\n".join(sheet_lines).encode("utf-8")

    # [Content_Types].xml
    content_types_xml = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""

    # _rels/.rels
    root_rels_xml = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

    # xl/workbook.xml
    workbook_xml = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

    # xl/_rels/workbook.xml.rels
    workbook_rels_xml = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""

    # Empaquetar todo en el archivo ZIP con compresión deflate
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", root_rels_xml)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)

    return len(records)


def read_xlsx(filepath: str | Path, cursor_name: str = "excelresult") -> Cursor:
    """
    Importa un archivo Excel (.xlsx) a un nuevo Cursor de 64 bits en memoria.
    """
    path = Path(filepath)
    with zipfile.ZipFile(path, "r") as zf:
        sheet_xml = zf.read("xl/worksheets/sheet1.xml")

    root = ET.fromstring(sheet_xml)
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    sheet_data = root.find("m:sheetData", ns)
    if sheet_data is None:
        sheet_data = root.find("sheetData")

    rows_els = list(sheet_data) if sheet_data is not None else []
    if not rows_els:
        return Cursor(cursor_name.lower(), [])

    # Fila 1: Nombres de columnas
    header_row = rows_els[0]
    col_names: List[str] = []
    for c in list(header_row):
        t_el = c.find(".//m:t", ns)
        if t_el is None:
            t_el = c.find(".//t")
        text_v = t_el.text if t_el is not None else (c.findtext(".//v") or "")
        cname = (text_v or f"col_{len(col_names) + 1}").lower().strip()
        col_names.append(cname)

    # Inferir tipos a partir de las filas de datos
    data_rows: List[Dict[str, Any]] = []
    for r_el in rows_els[1:]:
        row_dict: Dict[str, Any] = {}
        for c_idx, c in enumerate(list(r_el)):
            if c_idx >= len(col_names):
                break
            cname = col_names[c_idx]
            v_type = c.attrib.get("t")
            if v_type == "b":
                b_val = c.findtext(".//m:v", default="0", namespaces=ns) or c.findtext(".//v", default="0")
                row_dict[cname] = b_val == "1"
            else:
                t_el = c.find(".//m:t", ns)
                if t_el is None:
                    t_el = c.find(".//t")
                if t_el is not None:
                    row_dict[cname] = t_el.text or ""
                else:
                    raw_v = c.findtext(".//m:v", namespaces=ns) or c.findtext(".//v") or ""
                    if raw_v.isdigit():
                        row_dict[cname] = int(raw_v)
                    else:
                        try:
                            row_dict[cname] = float(raw_v)
                        except ValueError:
                            row_dict[cname] = raw_v
        data_rows.append(row_dict)

    fields: List[FieldDef] = []
    for col in col_names:
        sample = next((dr.get(col) for dr in data_rows if dr.get(col) is not None), None)
        if isinstance(sample, bool):
            fields.append(FieldDef(col, "L", 1, 0))
        elif isinstance(sample, int):
            fields.append(FieldDef(col, "I", 10, 0))
        elif isinstance(sample, float):
            fields.append(FieldDef(col, "N", 14, 2))
        else:
            fields.append(FieldDef(col, "V", 120, 0))

    cur = Cursor(cursor_name.lower(), fields)
    for rd in data_rows:
        cur.append_dict(rd)
    cur.go_top()
    return cur

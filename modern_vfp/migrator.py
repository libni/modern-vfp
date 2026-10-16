"""
Herramienta de Migración de Legado VFP 9 (`vfp2modern`) para FoxNext / Modern VFP.
Desensambla archivos de formularios (.scx) y librerías de clases visuales (.vcx) de VFP 9
(que internamente son tablas DBF) y genera archivos declarativos .foxform y .prg compatibles con Git.
"""

from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .dbf import read_dbf, write_dbf


def parse_scx_properties(prop_block: str) -> Dict[str, Any]:
    """
    Parsea el campo 'properties' de un registro .scx/.vcx de Visual FoxPro 9:
      Width = 640
      Caption = "Catálogo de Artículos"
      ControlSource = "articulos.nombre"
    """
    props: Dict[str, Any] = {}
    for raw_line in (prop_block or "").splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        val_str = v.strip()
        if (val_str.startswith('"') and val_str.endswith('"')) or (val_str.startswith("'") and val_str.endswith("'")):
            props[key] = val_str[1:-1]
        elif val_str.upper() in (".T.", "TRUE"):
            props[key] = True
        elif val_str.upper() in (".F.", "FALSE"):
            props[key] = False
        elif val_str.isdigit() or (val_str.startswith("-") and val_str[1:].isdigit()):
            props[key] = int(val_str)
        else:
            try:
                props[key] = float(val_str)
            except ValueError:
                props[key] = val_str
    return props


def parse_scx_methods(methods_block: str) -> Dict[str, str]:
    """
    Extrae bloques PROCEDURE <NombreEvento> ... ENDPROC del campo 'methods' de un .scx/.vcx.
    """
    methods: Dict[str, str] = {}
    if not methods_block:
        return methods
    pattern = re.compile(
        r"PROCEDURE\s+([A-Za-z0-9_.]+)\s*\r?\n(.*?)\r?\nENDPROC",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for m in pattern.finditer(methods_block):
        mname = m.group(1).strip()
        mbody = m.group(2).strip()
        methods[mname] = mbody
    return methods


def migrate_scx_to_foxform(scx_path: str | Path, output_foxform_path: str | Path | None = None) -> Dict[str, Any]:
    """
    Lee un archivo .scx (tabla DBF de formulario VFP9) y construye un diccionario .foxform
    declarativo y legible por Git. Si se provee `output_foxform_path`, lo guarda en disco.
    """
    path = Path(scx_path)
    _, rows, del_flags = read_dbf(path)

    form_meta: Dict[str, Any] = {
        "name": path.stem,
        "caption": path.stem,
        "width": 640,
        "height": 480,
        "dataEnvironment": {"cursors": []},
        "controls": [],
        "methods": {},
    }

    type_map = {
        "textbox": "TextBox",
        "commandbutton": "Button",
        "button": "Button",
        "checkbox": "CheckBox",
        "grid": "Grid",
        "label": "Label",
        "combobox": "ComboBox",
    }

    for idx, row in enumerate(rows):
        if idx < len(del_flags) and del_flags[idx]:
            continue
        baseclass = str(row.get("baseclass", "")).strip().lower()
        objname = str(row.get("objname", "")).strip()
        props = parse_scx_properties(str(row.get("properties", "")))
        methods = parse_scx_methods(str(row.get("methods", "")))

        if baseclass in ("dataenvironment", "header", "comment", ""):
            continue

        if baseclass == "cursor":
            alias = props.get("Alias", objname or "cur1")
            schema = props.get("Schema", "id I, nombre C(40)")
            form_meta["dataEnvironment"]["cursors"].append({"alias": str(alias).lower(), "schema": schema})
            continue

        if baseclass == "form":
            form_meta["name"] = objname or props.get("Name", path.stem)
            form_meta["caption"] = props.get("Caption", form_meta["name"])
            if "Width" in props:
                form_meta["width"] = int(props["Width"])
            if "Height" in props:
                form_meta["height"] = int(props["Height"])
            for mname, mbody in methods.items():
                form_meta["methods"][mname] = mbody
            continue

        # Control hijo dentro del formulario
        ctrl_type = type_map.get(baseclass, baseclass.capitalize() or "TextBox")
        ctrl_entry: Dict[str, Any] = {
            "type": ctrl_type,
            "name": objname or props.get("Name", f"ctrl_{idx}"),
            "caption": props.get("Caption", objname),
        }
        if "ControlSource" in props:
            ctrl_entry["controlSource"] = props["ControlSource"]
        if "RecordSource" in props:
            ctrl_entry["recordSource"] = props["RecordSource"]

        for mname, mbody in methods.items():
            ml = mname.lower()
            if ml == "click":
                ctrl_entry["onClick"] = mbody
            elif ml == "valid":
                ctrl_entry["onValid"] = mbody
            elif ml == "interactivechange":
                ctrl_entry["onInteractiveChange"] = mbody

        form_meta["controls"].append(ctrl_entry)

    result_spec = {"form": form_meta}
    if output_foxform_path is not None:
        out_p = Path(output_foxform_path)
        out_p.write_text(json.dumps(result_spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return result_spec


def create_sample_vfp9_scx(scx_path: str | Path) -> Path:
    """
    Genera un archivo binario .scx (formato tabla VFP) de prueba para validar migraciones VFP9 -> FoxNext.
    """
    path = Path(scx_path)
    fields = [
        {"name": "platform", "type": "C", "width": 8, "decimals": 0},
        {"name": "baseclass", "type": "C", "width": 20, "decimals": 0},
        {"name": "objname", "type": "C", "width": 30, "decimals": 0},
        {"name": "parent", "type": "C", "width": 30, "decimals": 0},
        {"name": "properties", "type": "C", "width": 200, "decimals": 0},
        {"name": "methods", "type": "C", "width": 200, "decimals": 0},
    ]
    rows = [
        {
            "platform": "WINDOWS",
            "baseclass": "cursor",
            "objname": "Cursor1",
            "parent": "DataEnvironment",
            "properties": 'Alias = "articulos"\nSchema = "codigo I, descripcion C(40), stock I"',
            "methods": "",
        },
        {
            "platform": "WINDOWS",
            "baseclass": "form",
            "objname": "frmInventario",
            "parent": "",
            "properties": 'Caption = "Control de Inventario VFP9"\nWidth = 700\nHeight = 450',
            "methods": "PROCEDURE Init\nINSERT INTO articulos VALUES (10, 'Teclado IBM Model M', 15)\nGO TOP\nENDPROC",
        },
        {
            "platform": "WINDOWS",
            "baseclass": "textbox",
            "objname": "txtDescripcion",
            "parent": "frmInventario",
            "properties": 'Caption = "Artículo:"\nControlSource = "articulos.descripcion"',
            "methods": "",
        },
        {
            "platform": "WINDOWS",
            "baseclass": "commandbutton",
            "objname": "btnAgregarStock",
            "parent": "frmInventario",
            "properties": 'Caption = "Sumar +5 al Stock"',
            "methods": "PROCEDURE Click\nREPLACE stock WITH stock + 5\nENDPROC",
        },
    ]
    write_dbf(path, fields, rows)
    return path

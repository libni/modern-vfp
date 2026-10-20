"""
Generador de Documentación Automática (`docgen.py`) para FoxNext / Modern VFP.
Inspecciona código fuente `.prg` y extrae Cursores, Vistas SQL, Clases OOP
(con herencia, propiedades y métodos) y Procedimientos/Funciones hacia Markdown.
"""

from __future__ import annotations
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from .cursor import parse_schema_string
from .interpreter import FoxInterpreter


def extract_doc_metadata(source: str) -> Dict[str, Any]:
    """
    Extrae metadatos estructurados de cursores, vistas SQL, clases y funciones de un `.prg`.
    """
    interp = FoxInterpreter()
    lines = interp.preprocess_code(source)
    interp._register_top_level_definitions(lines)

    cursors: List[Dict[str, Any]] = []
    views: List[Dict[str, str]] = []

    for line in lines:
        m_cur = re.match(
            r"^CREATE\s+(?:CURSOR|TABLE)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.+)\)\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_cur:
            alias = m_cur.group(1)
            fields = parse_schema_string(m_cur.group(2))
            cursors.append({
                "alias": alias,
                "fields": [
                    {"name": f.name, "type": f.ftype, "width": f.width, "decimals": f.decimals}
                    for f in fields
                ],
            })
            continue

        m_view = re.match(
            r"^CREATE\s+SQL\s+VIEW\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS\s+(SELECT\s+.+)$",
            line,
            flags=re.IGNORECASE,
        )
        if m_view:
            views.append({
                "name": m_view.group(1),
                "sql": m_view.group(2).strip(),
            })

    classes: List[Dict[str, Any]] = []
    for cname, (parent, prop_lines, methods_dict) in interp.classes.items():
        props = []
        for pl in prop_lines:
            if "=" in pl:
                k, v = pl.split("=", 1)
                props.append({"name": k.strip(), "default": v.strip()})
        methods = [
            {"name": mname, "params": params}
            for mname, (params, _) in methods_dict.items()
        ]
        classes.append({
            "name": cname,
            "parent": parent,
            "properties": props,
            "methods": methods,
        })

    procedures: List[Dict[str, Any]] = []
    for pname, (params, _) in interp.procedures.items():
        procedures.append({
            "name": pname,
            "params": params,
        })

    return {
        "cursors": cursors,
        "views": views,
        "classes": classes,
        "procedures": procedures,
    }


def generate_prg_docs(source: str, title: str = "Documentación Técnica FoxNext") -> str:
    """
    Genera un documento Markdown completo a partir del código fuente `.prg`.
    """
    meta = extract_doc_metadata(source)
    md: List[str] = [
        f"# {title}",
        "",
        "> Generado automáticamente por **FoxNext DocGen (`modern-vfp`)**.",
        "",
    ]

    if meta["cursors"]:
        md.append("## 1. Esquemas de Cursores y Tablas")
        md.append("")
        for c in meta["cursors"]:
            md.append(f"### Cursor `{c['alias']}`")
            md.append("")
            md.append("| Campo | Tipo | Ancho | Decimales |")
            md.append("| :--- | :---: | :---: | :---: |")
            for f in c["fields"]:
                md.append(f"| `{f['name']}` | `{f['type']}` | {f['width']} | {f['decimals']} |")
            md.append("")

    if meta["views"]:
        md.append("## 2. Vistas SQL Parametrizadas")
        md.append("")
        for v in meta["views"]:
            md.append(f"- **`{v['name']}`**: `{v['sql']}`")
        md.append("")

    if meta["classes"]:
        md.append("## 3. Clases Orientadas a Objetos (`DEFINE CLASS`)")
        md.append("")
        for cls in meta["classes"]:
            md.append(f"### Clase `{cls['name']}` (Hereda de `{cls['parent']}`)")
            md.append("")
            if cls["properties"]:
                md.append("**Propiedades:**")
                for p in cls["properties"]:
                    md.append(f"- `{p['name']}` = `{p['default']}`")
                md.append("")
            if cls["methods"]:
                md.append("**Métodos:**")
                for m in cls["methods"]:
                    args_str = ", ".join(m["params"])
                    md.append(f"- `{m['name']}({args_str})`")
                md.append("")

    if meta["procedures"]:
        md.append("## 4. Procedimientos y Funciones")
        md.append("")
        for proc in meta["procedures"]:
            args_str = ", ".join(proc["params"])
            md.append(f"- **`{proc['name']}({args_str})`**")
        md.append("")

    return "\n".join(md)


def generate_file_docs(src_path: str | Path, out_path: Optional[str | Path] = None) -> Path:
    src = Path(src_path)
    target = Path(out_path) if out_path else src.with_suffix(".md")
    code = src.read_text(encoding="utf-8")
    doc_md = generate_prg_docs(code, title=f"Documentación Técnica: `{src.name}`")
    target.write_text(doc_md, encoding="utf-8")
    return target

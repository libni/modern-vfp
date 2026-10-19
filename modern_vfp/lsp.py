"""
Language Server Protocol (LSP) & Analizador Estático para FoxNext / Modern VFP.
Provee extracción de símbolos (Cursores, Clases, Procedimientos, Funciones),
diagnóstico de bloques sin cerrar (IF/ENDIF, SCAN/ENDSCAN, DEFINE CLASS/ENDDEFINE)
y autocompletado inteligente sensible al contexto de cursores abiertos (`alias.campo`).
"""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Tuple

from .interpreter import FoxInterpreter


VFP_KEYWORDS = [
    "CREATE CURSOR",
    "CREATE TABLE",
    "ALTER TABLE",
    "SELECT",
    "FROM",
    "WHERE",
    "INNER JOIN",
    "GROUP BY",
    "ORDER BY",
    "INTO CURSOR",
    "INSERT INTO",
    "UPDATE",
    "DELETE FROM",
    "APPEND BLANK",
    "APPEND FROM",
    "APPEND FROM ARRAY",
    "COPY TO",
    "COPY TO ARRAY",
    "REPLACE",
    "WITH",
    "SCAN",
    "ENDSCAN",
    "LOCATE FOR",
    "CONTINUE",
    "INDEX ON",
    "TAG",
    "SET ORDER TO",
    "SEEK",
    "SET RELATION TO",
    "SET DELETED",
    "SCATTER NAME",
    "GATHER NAME",
    "CALCULATE",
    "BEGIN TRANSACTION",
    "END TRANSACTION",
    "ROLLBACK",
    "DEFINE CLASS",
    "ENDDEFINE",
    "PROCEDURE",
    "ENDPROC",
    "FUNCTION",
    "ENDFUNC",
    "IF",
    "ELSEIF",
    "ELSE",
    "ENDIF",
    "DO CASE",
    "CASE",
    "OTHERWISE",
    "ENDCASE",
    "DO WHILE",
    "ENDDO",
    "FOR",
    "ENDFOR",
    "TRY",
    "CATCH",
    "FINALLY",
    "ENDTRY",
    "TEXT TO",
    "ENDTEXT",
    "DO FORM",
    "REPORT FORM",
    "BUILD APP",
    "BROWSE",
    "LOCAL",
    "PUBLIC",
    "PRIVATE",
    "DIMENSION",
]


def analyze_fox_source(source: str) -> Dict[str, Any]:
    """
    Analiza estáticamente código fuente FoxNext (.prg) y devuelve:
    - `symbols`: lista de cursores, clases, procedimientos y funciones con su línea.
    - `diagnostics`: lista de errores de bloques no cerrados o mal anidados.
    """
    symbols: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    block_stack: List[Tuple[str, str, int]] = []  # (open_kw, expected_close, line_no)

    block_pairs = [
        (r"^IF\b", "IF", r"^ENDIF\b", "ENDIF"),
        (r"^DO\s+WHILE\b", "DO WHILE", r"^ENDDO\b", "ENDDO"),
        (r"^DO\s+CASE\b", "DO CASE", r"^ENDCASE\b", "ENDCASE"),
        (r"^FOR\b", "FOR", r"^(?:ENDFOR|NEXT)\b", "ENDFOR"),
        (r"^SCAN\b", "SCAN", r"^ENDSCAN\b", "ENDSCAN"),
        (r"^TRY\b", "TRY", r"^ENDTRY\b", "ENDTRY"),
        (r"^DEFINE\s+CLASS\b", "DEFINE CLASS", r"^ENDDEFINE\b", "ENDDEFINE"),
        (r"^(?:PROCEDURE|FUNCTION)\b", "PROCEDURE/FUNCTION", r"^(?:ENDPROC|ENDFUNC)\b", "ENDPROC/ENDFUNC"),
        (r"^TEXT\s+TO\b", "TEXT TO", r"^ENDTEXT\b", "ENDTEXT"),
    ]

    for idx, raw_line in enumerate(source.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("*") or re.match(r"^NOTE\b", line, flags=re.IGNORECASE):
            continue

        # Detectar símbolos
        m_cur = re.match(r"^CREATE\s+(?:CURSOR|TABLE)\s+([A-Za-z_][A-Za-z0-9_]*)", line, flags=re.IGNORECASE)
        if m_cur:
            symbols.append({"name": m_cur.group(1), "kind": "Cursor", "line": idx})

        m_into = re.search(r"\bINTO\s+CURSOR\s+([A-Za-z_][A-Za-z0-9_]*)", line, flags=re.IGNORECASE)
        if m_into:
            symbols.append({"name": m_into.group(1), "kind": "Cursor", "line": idx})

        m_cls = re.match(r"^DEFINE\s+CLASS\s+([A-Za-z_][A-Za-z0-9_]*)", line, flags=re.IGNORECASE)
        if m_cls:
            symbols.append({"name": m_cls.group(1), "kind": "Class", "line": idx})

        m_proc = re.match(r"^(PROCEDURE|FUNCTION)\s+([A-Za-z_][A-Za-z0-9_]*)", line, flags=re.IGNORECASE)
        if m_proc:
            kind = "Function" if m_proc.group(1).upper() == "FUNCTION" else "Procedure"
            symbols.append({"name": m_proc.group(2), "kind": kind, "line": idx})

        # Verificar apertura/cierre de bloques
        matched_open = False
        for open_pat, open_label, _, close_label in block_pairs:
            if re.match(open_pat, line, flags=re.IGNORECASE):
                block_stack.append((open_label, close_label, idx))
                matched_open = True
                break
        if matched_open:
            continue

        for _, open_label, close_pat, close_label in block_pairs:
            if re.match(close_pat, line, flags=re.IGNORECASE):
                if not block_stack:
                    diagnostics.append({
                        "line": idx,
                        "severity": "error",
                        "message": f"Cierre inesperado '{line}' sin bloque '{open_label}' abierto.",
                    })
                else:
                    top_open, top_expected, open_line = block_stack[-1]
                    if top_expected == close_label:
                        block_stack.pop()
                    else:
                        diagnostics.append({
                            "line": idx,
                            "severity": "error",
                            "message": f"Se encontró '{line}', pero se esperaba '{top_expected}' para cerrar '{top_open}' (línea {open_line}).",
                        })
                break

    for open_label, close_label, open_line in block_stack:
        diagnostics.append({
            "line": open_line,
            "severity": "error",
            "message": f"Bloque '{open_label}' abierto en la línea {open_line} no tiene su correspondiente '{close_label}'.",
        })

    return {"symbols": symbols, "diagnostics": diagnostics}


def get_completions(prefix: str, interp: Optional[FoxInterpreter] = None) -> List[Dict[str, str]]:
    """
    Devuelve sugerencias de autocompletado (comandos, funciones nativas, cursores y campos `alias.campo`).
    """
    engine = interp or FoxInterpreter()
    clean = prefix.strip()

    # Si el usuario escribe `clientes.`, autocompletar con los campos de ese cursor
    if "." in clean:
        alias_part, field_prefix = clean.rsplit(".", 1)
        cur = engine.wam.get_cursor(alias_part)
        if cur is not None:
            fp_low = field_prefix.lower()
            return [
                {
                    "label": f"{cur.alias}.{f.name}",
                    "insertText": f.name,
                    "kind": "Field",
                    "detail": f"{f.ftype}({f.width},{f.decimals})",
                }
                for f in cur.fields
                if f.name.lower().startswith(fp_low)
            ]

    up = clean.upper()
    results: List[Dict[str, str]] = []

    for kw in VFP_KEYWORDS:
        if kw.startswith(up):
            results.append({"label": kw, "kind": "Keyword", "detail": "Comando FoxNext"})

    for fn_name in sorted(engine.functions.keys()):
        if fn_name.upper().startswith(up):
            results.append({"label": f"{fn_name.upper()}()", "kind": "Function", "detail": "Función Nativa VFP"})

    for alias_name in sorted(engine.wam.alias_to_area.keys()):
        if alias_name.upper().startswith(up):
            results.append({"label": alias_name, "kind": "Cursor", "detail": "Cursor Activo"})

    return results

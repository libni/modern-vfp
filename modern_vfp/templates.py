"""
Motor de Plantillas y Generador de Documentos (`modern_vfp/templates.py`) para FoxNext.
Permite renderizar correos, contratos, documentos HTML y reportes estructurados con:
- Interpolación de expresiones: `{{ variable }}` o `{{ expr }}`
- Filtros de transformación: `{{ var | upper }}`, `{{ var | lower }}`, `{{ var | currency }}`
- Bloques condicionales: `{% if cond %} ... {% else %} ... {% endif %}`
- Bucles sobre cursores o listas: `{% for row in cursor_alias %} ... {% endfor %}`
"""

from __future__ import annotations
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union

from .cursor import Cursor


def _apply_filter(val: Any, filter_name: str) -> str:
    fn = filter_name.lower().strip()
    if val is None:
        return ""
    if fn == "upper":
        return str(val).upper()
    elif fn == "lower":
        return str(val).lower()
    elif fn == "trim":
        return str(val).strip()
    elif fn in ("currency", "money"):
        try:
            return f"${float(val):,.2f}"
        except (ValueError, TypeError):
            return str(val)
    elif fn == "title":
        return str(val).title()
    elif fn == "int":
        try:
            return str(int(float(val)))
        except (ValueError, TypeError):
            return str(val)
    return str(val)


def render_template(
    template_text: str,
    context: Dict[str, Any],
    eval_func: Optional[Any] = None,
) -> str:
    """
    Renderiza una plantilla textual resolviendo bucles, condicionales e interpolaciones.
    """
    lines = template_text.splitlines()
    output: List[str] = []

    i = 0
    n = len(lines)

    def _eval_expr(expr_str: str, local_ctx: Dict[str, Any]) -> Any:
        # Resolver en contexto local
        expr = expr_str.strip()
        if expr in local_ctx:
            return local_ctx[expr]
        if "." in expr:
            parts = expr.split(".", 1)
            obj = local_ctx.get(parts[0])
            if isinstance(obj, dict):
                return obj.get(parts[1], "")
        if eval_func:
            try:
                # Merge local context
                return eval_func(expr)
            except Exception:
                pass
        return local_ctx.get(expr, "")

    while i < n:
        line = lines[i]

        # 1. Bucle: {% for var in collection_or_cursor %}
        m_for = re.match(r"^\s*\{%\s*for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+([A-Za-z0-9_.]+)\s*%\}\s*$", line)
        if m_for:
            iter_var = m_for.group(1)
            coll_name = m_for.group(2)
            for_body: List[str] = []
            i += 1
            depth = 1
            while i < n:
                if re.match(r"^\s*\{%\s*for\b", lines[i]):
                    depth += 1
                elif re.match(r"^\s*\{%\s*endfor\s*%\}\s*$", lines[i]):
                    depth -= 1
                    if depth == 0:
                        break
                for_body.append(lines[i])
                i += 1

            coll = context.get(coll_name)
            # Si es un Cursor de FoxNext
            if isinstance(coll, Cursor):
                for row in coll.records:
                    sub_ctx = dict(context)
                    sub_ctx[iter_var] = row
                    sub_rendered = render_template("\n".join(for_body), sub_ctx, eval_func)
                    output.append(sub_rendered)
            elif isinstance(coll, (list, tuple)):
                for item in coll:
                    sub_ctx = dict(context)
                    sub_ctx[iter_var] = item
                    sub_rendered = render_template("\n".join(for_body), sub_ctx, eval_func)
                    output.append(sub_rendered)
            i += 1
            continue

        # 2. Condicional: {% if cond %} ... {% else %} ... {% endif %}
        m_if = re.match(r"^\s*\{%\s*if\s+(.+?)\s*%\}\s*$", line)
        if m_if:
            cond_expr = m_if.group(1)
            if_body: List[str] = []
            else_body: List[str] = []
            has_else = False
            i += 1
            depth = 1
            while i < n:
                if re.match(r"^\s*\{%\s*if\b", lines[i]):
                    depth += 1
                elif re.match(r"^\s*\{%\s*else\s*%\}\s*$", lines[i]) and depth == 1:
                    has_else = True
                    i += 1
                    continue
                elif re.match(r"^\s*\{%\s*endif\s*%\}\s*$", lines[i]):
                    depth -= 1
                    if depth == 0:
                        break
                if has_else:
                    else_body.append(lines[i])
                else:
                    if_body.append(lines[i])
                i += 1

            cond_val = bool(_eval_expr(cond_expr, context))
            chosen_body = if_body if cond_val else else_body
            if chosen_body:
                output.append(render_template("\n".join(chosen_body), context, eval_func))
            i += 1
            continue

        # 3. Interpolación de variables en la línea actual: {{ expr [| filter] }}
        def _replace_tag(match: re.Match) -> str:
            raw = match.group(1).strip()
            if "|" in raw:
                parts = raw.split("|", 1)
                val = _eval_expr(parts[0].strip(), context)
                return _apply_filter(val, parts[1].strip())
            val = _eval_expr(raw, context)
            return "" if val is None else str(val)

        rendered_line = re.sub(r"\{\{\s*(.+?)\s*\}\}", _replace_tag, line)
        output.append(rendered_line)
        i += 1

    return "\n".join(output)

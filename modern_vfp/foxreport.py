"""
Motor de Reportes por Bandas Declarativo (.foxreport) para FoxNext / Modern VFP.
Reemplaza los binarios .frx/.frt de VFP9 por definiciones JSON legibles en Git,
con soporte para bandas (Title, PageHeader, GroupHeader/Footer, Detail, Summary),
agrupaciones y totales automáticos (SUM, AVG, COUNT, MIN, MAX), y exportación a Texto/HTML/Markdown.
"""

from __future__ import annotations
import datetime
import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .interpreter import FoxInterpreter


class FoxReport:
    """
    Representa un reporte por bandas en FoxNext ejecutable mediante `REPORT FORM`.
    """

    def __init__(self, spec: Dict[str, Any], interpreter: FoxInterpreter):
        rep_root = spec.get("report", spec)
        self.name: str = rep_root.get("name", "rptDefault")
        self.title: str = rep_root.get("title", self.name)
        self.subtitle: str = rep_root.get("subtitle", "")
        self.alias: Optional[str] = rep_root.get("alias")
        self.group_by: Optional[Dict[str, Any]] = rep_root.get("groupBy")
        self.columns: List[Dict[str, Any]] = rep_root.get("columns", [])
        self.summary_items: List[Dict[str, Any]] = rep_root.get("summary", [])
        self.interp = interpreter

    @classmethod
    def from_file(cls, filepath: str | Path, interpreter: FoxInterpreter) -> "FoxReport":
        path = Path(filepath)
        spec = json.loads(path.read_text(encoding="utf-8"))
        return cls(spec, interpreter=interpreter)

    def _collect_rows(self, for_expr: Optional[str] = None) -> List[Dict[str, Any]]:
        cur = self.interp.wam.get_cursor(self.alias) if self.alias else self.interp.wam.current_cursor()
        if cur is None:
            raise RuntimeError(f"REPORT FORM '{self.name}' requiere un cursor abierto.")

        saved_area = self.interp.wam.current_area
        self.interp.wam.select_area(cur.alias)
        evaluated_rows: List[Dict[str, Any]] = []
        try:
            for r in cur.visible_recnos(self.interp.wam.set_deleted):
                cur.goto(r)
                self.interp.wam.sync_relations(self.interp.eval_expr)
                if for_expr and not bool(self.interp.eval_expr(for_expr)):
                    continue
                row_data: Dict[str, Any] = {"__recno__": r}
                if self.group_by and "expr" in self.group_by:
                    row_data["__group__"] = self.interp.eval_expr(self.group_by["expr"])
                for idx, col in enumerate(self.columns):
                    key = col.get("name") or f"col_{idx}"
                    row_data[key] = self.interp.eval_expr(col["expr"])
                for idx, s_item in enumerate(self.summary_items):
                    skey = f"__sum_{idx}__"
                    row_data[skey] = self.interp.eval_expr(s_item["expr"])
                evaluated_rows.append(row_data)
        finally:
            self.interp.wam.current_area = saved_area
        return evaluated_rows

    def _format_cell(self, val: Any, fmt: Optional[str] = None) -> str:
        if val is None:
            return ""
        if fmt:
            return self.interp.functions["transform"](val, fmt)
        if isinstance(val, float):
            return f"{val:,.2f}"
        if isinstance(val, bool):
            return "Sí" if val else "No"
        return str(val)

    @staticmethod
    def _compute_agg(values: List[Any], op: str) -> Any:
        nums = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        op_up = op.upper()
        if op_up == "COUNT":
            return len(values)
        if not nums:
            return 0.0
        if op_up == "SUM":
            return sum(nums)
        if op_up == "AVG":
            return sum(nums) / len(nums)
        if op_up == "MIN":
            return min(nums)
        if op_up == "MAX":
            return max(nums)
        return sum(nums)

    def render_text(self, for_expr: Optional[str] = None) -> str:
        rows = self._collect_rows(for_expr)
        col_defs = []
        for idx, col in enumerate(self.columns):
            key = col.get("name") or f"col_{idx}"
            label = col.get("label", key.upper())
            width = int(col.get("width", max(12, len(label) + 2)))
            align = col.get("align", "left").lower()
            fmt = col.get("format")
            col_defs.append((key, label, width, align, fmt))

        total_w = max(68, sum(w + 3 for _, _, w, _, _ in col_defs) + 1)
        eq_sep = "=" * total_w
        dash_sep = "-" * total_w
        today_str = datetime.date.today().isoformat()

        lines = [
            eq_sep,
            f" {self.title.upper():<{total_w - 16}} {today_str:>13} ",
        ]
        if self.subtitle:
            lines.append(f" {self.subtitle:<{total_w - 2}} ")
        lines.append(eq_sep)

        # Page Header
        hdr_cells = []
        for _, label, width, align, _ in col_defs:
            if align == "right":
                hdr_cells.append(f"{label:>{width}}")
            else:
                hdr_cells.append(f"{label:<{width}}")
        lines.append(" | ".join(hdr_cells))
        lines.append(dash_sep)

        # Detail Band (con soporte de GroupHeader / GroupFooter)
        current_group = object()
        group_rows: List[Dict[str, Any]] = []

        def _flush_group_footer(g_val: Any, g_rows: List[Dict[str, Any]]) -> None:
            if not self.group_by or not g_rows:
                return
            sub_expr = self.group_by.get("subtotalExpr")
            if sub_expr:
                # Buscar si coincide con alguna columna o summary
                vals = []
                for gr in g_rows:
                    for k, v in gr.items():
                        if isinstance(v, (int, float)) and not k.startswith("__rec"):
                            vals.append(v)
                g_label = self.group_by.get("footerLabel", f"Subtotal {g_val}")
                lines.append(f"   --> {g_label} ({len(g_rows)} reg.)")
            lines.append(dash_sep)

        for r in rows:
            if self.group_by and "expr" in self.group_by:
                g_val = r.get("__group__")
                if g_val != current_group:
                    if current_group is not object():
                        _flush_group_footer(current_group, group_rows)
                    current_group = g_val
                    group_rows = []
                    g_hdr = self.group_by.get("label", "Grupo")
                    lines.append(f"[{g_hdr}: {g_val}]")
                group_rows.append(r)

            row_cells = []
            for key, _, width, align, fmt in col_defs:
                txt = self._format_cell(r.get(key), fmt)[:width]
                if align == "right":
                    row_cells.append(f"{txt:>{width}}")
                elif align == "center":
                    row_cells.append(f"{txt:^{width}}")
                else:
                    row_cells.append(f"{txt:<{width}}")
            lines.append(" | ".join(row_cells))

        if self.group_by and group_rows:
            _flush_group_footer(current_group, group_rows)

        lines.append(eq_sep)

        # Summary Band
        if self.summary_items:
            lines.append(" RESUMEN GENERAL (SUMMARY BAND):")
            for idx, s_item in enumerate(self.summary_items):
                skey = f"__sum_{idx}__"
                op = s_item.get("op", "SUM")
                slabel = s_item.get("label", f"{op}({s_item['expr']})")
                sfmt = s_item.get("format")
                vals = [r[skey] for r in rows]
                agg_val = self._compute_agg(vals, op)
                fmt_val = self._format_cell(agg_val, sfmt)
                lines.append(f"   * {slabel:<32}: {fmt_val}")
            lines.append(eq_sep)

        return "\n".join(lines)

    def render_html(self, for_expr: Optional[str] = None) -> str:
        rows = self._collect_rows(for_expr)
        parts = [
            "<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>",
            f"<title>{html.escape(self.title)}</title>",
            "<style>",
            "body { font-family: 'Segoe UI', system-ui, sans-serif; margin: 2rem; color: #1e293b; background: #f8fafc; }",
            ".report { max-width: 920px; margin: 0 auto; background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.08); }",
            "h1 { margin: 0 0 0.25rem 0; color: #0f172a; font-size: 1.5rem; }",
            ".subtitle { color: #64748b; margin-bottom: 1.5rem; }",
            "table { width: 100%; border-collapse: collapse; margin-bottom: 1.5rem; }",
            "th { background: #1e293b; color: white; padding: 0.65rem; text-align: left; }",
            "td { padding: 0.55rem 0.65rem; border-bottom: 1px solid #e2e8f0; }",
            ".group-row td { background: #eff6ff; font-weight: 700; color: #1d4ed8; }",
            ".summary { background: #f1f5f9; padding: 1rem 1.25rem; border-radius: 6px; border-left: 4px solid #2563eb; }",
            "</style></head><body><div class='report'>",
            f"<h1>{html.escape(self.title)}</h1>",
        ]
        if self.subtitle:
            parts.append(f"<div class='subtitle'>{html.escape(self.subtitle)}</div>")

        parts.append("<table><thead><tr>")
        for idx, col in enumerate(self.columns):
            key = col.get("name") or f"col_{idx}"
            label = html.escape(col.get("label", key.upper()))
            parts.append(f"<th>{label}</th>")
        parts.append("</tr></thead><tbody>")

        current_group = object()
        for r in rows:
            if self.group_by and "expr" in self.group_by:
                g_val = r.get("__group__")
                if g_val != current_group:
                    current_group = g_val
                    g_hdr = html.escape(self.group_by.get("label", "Grupo"))
                    parts.append(
                        f"<tr class='group-row'><td colspan='{len(self.columns)}'>{g_hdr}: {html.escape(str(g_val))}</td></tr>"
                    )
            parts.append("<tr>")
            for idx, col in enumerate(self.columns):
                key = col.get("name") or f"col_{idx}"
                txt = html.escape(self._format_cell(r.get(key), col.get("format")))
                align = col.get("align", "left")
                parts.append(f"<td style='text-align:{align}'>{txt}</td>")
            parts.append("</tr>")
        parts.append("</tbody></table>")

        if self.summary_items:
            parts.append("<div class='summary'><strong>Resumen General:</strong><ul>")
            for idx, s_item in enumerate(self.summary_items):
                skey = f"__sum_{idx}__"
                op = s_item.get("op", "SUM")
                slabel = html.escape(s_item.get("label", op))
                agg_val = self._compute_agg([r[skey] for r in rows], op)
                fmt_val = html.escape(self._format_cell(agg_val, s_item.get("format")))
                parts.append(f"<li><strong>{slabel}:</strong> {fmt_val}</li>")
            parts.append("</ul></div>")

        parts.append("</div></body></html>")
        return "\n".join(parts)

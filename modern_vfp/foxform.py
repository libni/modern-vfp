"""
Motor de Formularios Declarativos RAD Git-Friendly (.foxform) para FoxNext / Modern VFP.
Reemplaza los binarios .scx/.sct de VFP9 por definiciones JSON legibles en control de versiones,
con enlace de datos bidireccional (ControlSource), DataEnvironment y eventos de ciclo de vida.
"""

from __future__ import annotations
import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .interpreter import FoxInterpreter


class FoxForm:
    """
    Representa un formulario RAD en tiempo de ejecución con su DataEnvironment,
    controles enlazados (ControlSource) y eventos (Load, Init, Click, Valid, Destroy).
    """

    def __init__(self, spec: Dict[str, Any], interpreter: Optional[FoxInterpreter] = None):
        form_root = spec.get("form", spec)
        self.name: str = form_root.get("name", "frmDefault")
        self.caption: str = form_root.get("caption", self.name)
        self.width: int = int(form_root.get("width", 640))
        self.height: int = int(form_root.get("height", 480))
        self.data_env: Dict[str, Any] = form_root.get("dataEnvironment", {})
        self.controls: List[Dict[str, Any]] = form_root.get("controls", [])
        self.methods: Dict[str, str] = {k.lower(): v for k, v in form_root.get("methods", {}).items()}
        self.interp: FoxInterpreter = interpreter or FoxInterpreter()

        # Valores en caché de controles sin ControlSource directo
        self._control_values: Dict[str, Any] = {}

    @classmethod
    def from_file(cls, filepath: str | Path, interpreter: Optional[FoxInterpreter] = None) -> "FoxForm":
        path = Path(filepath)
        spec = json.loads(path.read_text(encoding="utf-8"))
        return cls(spec, interpreter=interpreter)

    def initialize(self) -> None:
        """
        Ejecuta el ciclo de vida de apertura de un formulario VFP:
        1. Inicializa DataEnvironment (abre/crea cursores)
        2. Dispara evento Load
        3. Dispara evento Init
        """
        for cur_def in self.data_env.get("cursors", []):
            alias = cur_def.get("alias", "cur1")
            schema = cur_def.get("schema", "")
            if schema and not self.interp.wam.get_cursor(alias):
                self.interp.execute(f"CREATE CURSOR {alias} ({schema})")

        if "load" in self.methods:
            self.interp.execute(self.methods["load"])
        if "init" in self.methods:
            self.interp.execute(self.methods["init"])

    def read_control_value(self, ctrl_name: str) -> Any:
        ctrl = self._find_control(ctrl_name)
        cs = ctrl.get("controlSource")
        if cs:
            return self.interp.eval_expr(cs)
        return self._control_values.get(ctrl_name.lower(), ctrl.get("value", ""))

    def write_control_value(self, ctrl_name: str, new_value: Any) -> bool:
        """
        Actualiza el valor del control y propaga automáticamente al ControlSource (Two-Way Data Binding).
        Ejecuta `onInteractiveChange` y `onValid` si están definidos.
        """
        ctrl = self._find_control(ctrl_name)
        cs = ctrl.get("controlSource")
        if cs:
            if "." in cs:
                alias, fname = cs.split(".", 1)
                cur = self.interp.wam.get_cursor(alias)
                if cur is None:
                    raise RuntimeError(f"ControlSource '{cs}' apunta a un cursor cerrado.")
                cur.set_field(fname, new_value)
            else:
                cur = self.interp.wam.current_cursor()
                if cur and cs.lower() in cur.field_map:
                    cur.set_field(cs, new_value)
                else:
                    self.interp.set_var(cs, new_value)
        else:
            self._control_values[ctrl_name.lower()] = new_value

        if "onInteractiveChange" in ctrl:
            self.interp.execute(ctrl["onInteractiveChange"])

        if "onValid" in ctrl:
            res = self.interp.execute(ctrl["onValid"])
            if res is False:
                return False
        return True

    def trigger_click(self, ctrl_name: str) -> Any:
        ctrl = self._find_control(ctrl_name)
        code = ctrl.get("onClick", "")
        if code:
            return self.interp.execute(code)
        return None

    def _find_control(self, ctrl_name: str) -> Dict[str, Any]:
        nl = ctrl_name.lower()
        for c in self.controls:
            if c.get("name", "").lower() == nl:
                return c
        raise KeyError(f"El control '{ctrl_name}' no existe en el formulario '{self.name}'.")

    def render_tui(self) -> str:
        """
        Renderiza el formulario en modo consola (TUI) mostrando los valores actuales enlazados a los cursores.
        """
        width = 76
        border = "+" + "=" * (width - 2) + "+"
        sep = "+" + "-" * (width - 2) + "+"
        title = f"| [Form: {self.name}] {self.caption:<{width - len(self.name) - 13}} [X] |"
        lines = [border, title, sep]

        for c in self.controls:
            ctype = c.get("type", "Control")
            cname = c.get("name", "ctrl")
            cap = c.get("caption", cname)
            if ctype.lower() == "grid":
                rec_src = c.get("recordSource")
                cur = self.interp.wam.get_cursor(rec_src) if rec_src else self.interp.wam.current_cursor()
                lines.append(f"| [Grid: {cname}] (RecordSource: {rec_src or 'Actual'})".ljust(width - 1) + "|")
                if cur:
                    for bline in cur.format_browse_table(self.interp.wam.set_deleted, max_rows=10).splitlines():
                        lines.append("|   " + bline[: width - 6].ljust(width - 5) + "|")
            elif ctype.lower() == "button":
                btn_txt = f"[ {cap} ]"
                lines.append(f"|   {btn_txt:<{width - 5}}|")
            elif ctype.lower() == "checkbox":
                val = bool(self.read_control_value(cname))
                box = "[X]" if val else "[ ]"
                lines.append(f"|   {box} {cap:<{width - 9}}|")
            else:
                val = self.read_control_value(cname)
                val_str = "" if val is None else str(val)
                field_box = f"[{val_str:<32}]"
                line_content = f"   {cap:<18} {field_box}"
                lines.append(f"|{line_content:<{width - 2}}|")

        lines.append(border)
        return "\n".join(lines)

    def export_html(self, filepath: Optional[str | Path] = None) -> str:
        """
        Genera una vista HTML5 moderna del formulario con los datos actuales de su DataEnvironment.
        """
        parts = [
            "<!DOCTYPE html>",
            "<html lang='es'><head><meta charset='utf-8'>",
            f"<title>{html.escape(self.caption)}</title>",
            "<style>",
            "body { font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; padding: 2rem; }",
            ".window { max-width: 820px; margin: 0 auto; background: #1e293b; border: 1px solid #334155; border-radius: 10px; box-shadow: 0 12px 32px rgba(0,0,0,0.4); overflow: hidden; }",
            ".titlebar { background: linear-gradient(90deg, #1d4ed8, #2563eb); padding: 0.85rem 1.25rem; font-weight: 700; display: flex; justify-content: space-between; }",
            ".content { padding: 1.5rem; display: flex; flex-direction: column; gap: 1rem; }",
            ".field-row { display: flex; align-items: center; gap: 1rem; }",
            ".field-row label { width: 160px; font-weight: 600; color: #cbd5e1; }",
            ".field-row input[type='text'] { flex: 1; padding: 0.5rem 0.75rem; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: #f8fafc; }",
            "table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; font-size: 0.9rem; }",
            "th, td { border: 1px solid #334155; padding: 0.5rem 0.75rem; text-align: left; }",
            "th { background: #0f172a; color: #93c5fd; }",
            "button { align-self: flex-start; background: #2563eb; color: white; border: none; padding: 0.6rem 1.25rem; border-radius: 6px; font-weight: 600; cursor: pointer; }",
            "</style></head><body>",
            "<div class='window'>",
            f"<div class='titlebar'><span>{html.escape(self.caption)} ({html.escape(self.name)})</span><span>FoxNext RAD</span></div>",
            "<div class='content'>",
        ]

        for c in self.controls:
            ctype = c.get("type", "TextBox").lower()
            cname = c.get("name", "ctrl")
            cap = html.escape(c.get("caption", cname))
            if ctype == "grid":
                rec_src = c.get("recordSource")
                cur = self.interp.wam.get_cursor(rec_src) if rec_src else self.interp.wam.current_cursor()
                if cur:
                    parts.append("<table><thead><tr>")
                    for f in cur.fields:
                        parts.append(f"<th>{html.escape(f.name.upper())}</th>")
                    parts.append("</tr></thead><tbody>")
                    for r in cur.visible_recnos(self.interp.wam.set_deleted):
                        row = cur.records[r - 1]
                        parts.append("<tr>")
                        for f in cur.fields:
                            parts.append(f"<td>{html.escape(str(row.get(f.name, '')))}</td>")
                        parts.append("</tr>")
                    parts.append("</tbody></table>")
            elif ctype == "checkbox":
                checked = "checked" if bool(self.read_control_value(cname)) else ""
                parts.append(f"<div class='field-row'><label>{cap}</label><input type='checkbox' {checked} readonly></div>")
            elif ctype == "button":
                parts.append(f"<button type='button'>{cap}</button>")
            else:
                val = html.escape(str(self.read_control_value(cname) or ""))
                parts.append(f"<div class='field-row'><label>{cap}</label><input type='text' value='{val}' readonly></div>")

        parts.extend(["</div></div></body></html>"])
        html_doc = "\n".join(parts)
        if filepath:
            Path(filepath).write_text(html_doc, encoding="utf-8")
        return html_doc

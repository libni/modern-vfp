"""
Motor de Menús Declarativos y xBase (`FoxMenu` / `.foxmenu`) para FoxNext.
Soporta la jerarquía clásica de Visual FoxPro:
  DEFINE MENU <menu>
  DEFINE PAD <pad> OF <menu> PROMPT <caption_expr>
  ON PAD <pad> OF <menu> ACTIVATE POPUP <popup>
  DEFINE POPUP <popup>
  DEFINE BAR <n> OF <popup> PROMPT <caption_expr>
  ON SELECTION BAR <n> OF <popup> <xbase_command>
Además de renderizado en TUI (Terminal) y HTML5 para FoxNext Studio.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .interpreter import FoxInterpreter


class FoxMenu:
    """
    Representa una barra de menú empresarial estilo VFP con Pads, Popups y Bars ejecutables.
    """

    def __init__(self, name: str = "_msysmenu", interpreter: Optional[FoxInterpreter] = None):
        self.name: str = name.lower()
        self.interp: FoxInterpreter = interpreter or FoxInterpreter()
        # pads: name -> {"name": str, "prompt": str, "popup": Optional[str]}
        self.pads: Dict[str, Dict[str, Any]] = {}
        # popups: popup_name -> {bar_num: {"bar": int, "prompt": str, "command": Optional[str]}}
        self.popups: Dict[str, Dict[int, Dict[str, Any]]] = {}

    @classmethod
    def from_file(cls, path: str | Path, interpreter: Optional[FoxInterpreter] = None) -> "FoxMenu":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        menu = cls(name=raw.get("name", "_msysmenu"), interpreter=interpreter)
        for pad in raw.get("pads", []):
            pname = str(pad.get("name", f"pad_{len(menu.pads) + 1}")).lower()
            popup_name = str(pad.get("popup", pname)).lower()
            menu.define_pad(pname, str(pad.get("prompt", pname)), popup=popup_name)
            menu.define_popup(popup_name)
            for bar_item in pad.get("bars", []):
                bnum = int(bar_item.get("bar", 1))
                bprompt = str(bar_item.get("prompt", f"Opción {bnum}"))
                bcmd = bar_item.get("command")
                menu.define_bar(popup_name, bnum, bprompt)
                if bcmd:
                    menu.on_selection_bar(popup_name, bnum, str(bcmd))
        return menu

    def define_pad(self, pad_name: str, prompt: str, popup: Optional[str] = None) -> None:
        key = pad_name.strip().lower()
        self.pads[key] = {
            "name": key,
            "prompt": prompt,
            "popup": popup.strip().lower() if popup else key,
        }

    def on_pad_activate_popup(self, pad_name: str, popup_name: str) -> None:
        key = pad_name.strip().lower()
        if key in self.pads:
            self.pads[key]["popup"] = popup_name.strip().lower()
        self.define_popup(popup_name)

    def define_popup(self, popup_name: str) -> None:
        key = popup_name.strip().lower()
        if key not in self.popups:
            self.popups[key] = {}

    def define_bar(self, popup_name: str, bar_num: int, prompt: str) -> None:
        p_key = popup_name.strip().lower()
        self.define_popup(p_key)
        b_idx = int(bar_num)
        existing = self.popups[p_key].get(b_idx, {})
        self.popups[p_key][b_idx] = {
            "bar": b_idx,
            "prompt": prompt,
            "command": existing.get("command"),
        }

    def on_selection_bar(self, popup_name: str, bar_num: int, command: str) -> None:
        p_key = popup_name.strip().lower()
        self.define_popup(p_key)
        b_idx = int(bar_num)
        if b_idx not in self.popups[p_key]:
            self.popups[p_key][b_idx] = {"bar": b_idx, "prompt": f"Bar {b_idx}", "command": command}
        else:
            self.popups[p_key][b_idx]["command"] = command

    def trigger_bar(self, popup_name: str, bar_num: int) -> Any:
        """
        Ejecuta el comando xBase vinculado a `ON SELECTION BAR <bar_num> OF <popup_name>`.
        """
        p_key = popup_name.strip().lower()
        bars = self.popups.get(p_key, {})
        item = bars.get(int(bar_num))
        if not item or not item.get("command"):
            raise KeyError(f"No hay acción registrada para BAR {bar_num} OF {popup_name}")
        return self.interp.execute(str(item["command"]))

    def render_tui(self) -> str:
        pad_labels = [f"[{p['prompt']}]" for p in self.pads.values()]
        header_bar = "  ".join(pad_labels) if pad_labels else "(Menú vacío)"
        lines = [
            "╔" + "═" * 68 + "╗",
            f"║ MENU: {header_bar:<60} ║",
            "╠" + "═" * 68 + "╣",
        ]
        for pad in self.pads.values():
            popup_key = pad.get("popup") or pad["name"]
            bars = self.popups.get(popup_key, {})
            lines.append(f"║ ▾ {pad['prompt']} (Popup: {popup_key})".ljust(69) + "║")
            for bnum, binfo in sorted(bars.items()):
                cmd_desc = f" -> {binfo['command']}" if binfo.get("command") else ""
                entry = f"     {bnum}. {binfo['prompt']}{cmd_desc}"
                lines.append(f"║{entry[:68]:<68}║")
        lines.append("╚" + "═" * 68 + "╝")
        return "\n".join(lines)

    def render_html(self) -> str:
        parts = ['<nav class="foxmenu-bar" style="background:#1e293b;color:#f8fafc;padding:8px 16px;display:flex;gap:24px;font-family:sans-serif;">']
        for pad in self.pads.values():
            popup_key = pad.get("popup") or pad["name"]
            bars = self.popups.get(popup_key, {})
            parts.append('<div class="foxmenu-pad">')
            parts.append(f'<strong>{pad["prompt"]}</strong>')
            if bars:
                parts.append('<ul style="margin:4px 0 0 0;padding-left:18px;">')
                for bnum, binfo in sorted(bars.items()):
                    parts.append(f'<li data-popup="{popup_key}" data-bar="{bnum}">{binfo["prompt"]}</li>')
                parts.append("</ul>")
            parts.append("</div>")
        parts.append("</nav>")
        return "\n".join(parts)

"""
Depurador y Trazador de Ejecución (`FoxDebugger`) para FoxNext / Modern VFP.
Provee Breakpoints por línea, Watchpoints condicionales (expresiones vigiladas),
inspección de cursores paso a paso y registro completo de traza de ejecución.
"""

from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional, Set

from .interpreter import FoxInterpreter


class FoxDebugger:
    """
    Motor de depuración y traza para programas FoxNext (.prg).
    """

    def __init__(self, interpreter: Optional[FoxInterpreter] = None):
        self.interp: FoxInterpreter = interpreter or FoxInterpreter()
        self.breakpoints: Set[int] = set()
        self.watches: List[str] = []
        self.trace_log: List[Dict[str, Any]] = []
        self.breakpoint_hits: List[Dict[str, Any]] = []
        self.watch_hits: List[Dict[str, Any]] = []
        self._last_watch_values: Dict[str, Any] = {}

    def add_breakpoint(self, line_no: int) -> None:
        self.breakpoints.add(int(line_no))

    def remove_breakpoint(self, line_no: int) -> None:
        self.breakpoints.discard(int(line_no))

    def add_watch(self, expr: str) -> None:
        if expr not in self.watches:
            self.watches.append(expr)

    def evaluate_watches(self, step_no: int, current_line: str) -> Dict[str, Any]:
        results: Dict[str, Any] = {}
        for w in self.watches:
            try:
                val = self.interp.eval_expr(w)
            except Exception:
                val = None
            results[w] = val
            prev = self._last_watch_values.get(w, object())
            if prev is not object() and val != prev:
                self.watch_hits.append({
                    "step": step_no,
                    "watch": w,
                    "oldValue": prev,
                    "newValue": val,
                    "line": current_line,
                })
            self._last_watch_values[w] = val
        return results

    def run_with_trace(
        self,
        source: str,
        on_breakpoint: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Ejecuta un script registrando la traza paso a paso, evaluando Watchpoints
        y disparando callbacks cuando se alcanza un Breakpoint o `SET STEP ON`.
        """
        lines = self.interp.preprocess_code(source)
        self.interp._register_top_level_definitions(lines)
        self.trace_log.clear()
        self.breakpoint_hits.clear()
        self.watch_hits.clear()
        self._last_watch_values.clear()

        # Inicializar valores base de watches
        for w in self.watches:
            try:
                self._last_watch_values[w] = self.interp.eval_expr(w)
            except Exception:
                self._last_watch_values[w] = None

        has_structured_blocks = any(
            line.upper().startswith(("IF ", "DO WHILE", "DO CASE", "FOR ", "SCAN", "TRY", "DEFINE CLASS", "PROCEDURE", "FUNCTION", "TEXT TO"))
            for line in lines
        )

        if not has_structured_blocks:
            for idx, line in enumerate(lines, start=1):
                is_set_step = line.strip().upper().startswith("SET STEP ON")
                if idx in self.breakpoints or is_set_step:
                    cur = self.interp.wam.current_cursor()
                    bp_info = {
                        "lineNo": idx,
                        "statement": line,
                        "activeAlias": cur.alias if cur else None,
                        "recno": cur.recno() if cur else 0,
                        "vars": dict(self.interp.current_vars()),
                    }
                    self.breakpoint_hits.append(bp_info)
                    if on_breakpoint:
                        on_breakpoint(bp_info)
                    if is_set_step:
                        continue
                self.interp._exec_statement(self.interp._expand_macros(line))
                cur = self.interp.wam.current_cursor()
                watch_state = self.evaluate_watches(idx, line)
                self.trace_log.append({
                    "step": idx,
                    "statement": line,
                    "alias": cur.alias if cur else None,
                    "recno": cur.recno() if cur else 0,
                    "watches": watch_state,
                })
        else:
            for idx, line in enumerate(lines, start=1):
                is_set_step = line.strip().upper().startswith("SET STEP ON")
                if idx in self.breakpoints or is_set_step:
                    cur = self.interp.wam.current_cursor()
                    bp_info = {
                        "lineNo": idx,
                        "statement": line,
                        "activeAlias": cur.alias if cur else None,
                        "recno": cur.recno() if cur else 0,
                        "vars": dict(self.interp.current_vars()),
                    }
                    self.breakpoint_hits.append(bp_info)
                    if on_breakpoint:
                        on_breakpoint(bp_info)
            cleaned_source = "\n".join(
                line for line in source.splitlines()
                if not line.strip().upper().startswith("SET STEP ON")
            )
            self.interp.execute(cleaned_source)
            self.evaluate_watches(len(lines), lines[-1] if lines else "")

        return {
            "stepsExecuted": len(self.trace_log) or len(lines),
            "breakpointHits": self.breakpoint_hits,
            "watchHits": self.watch_hits,
            "traceLog": self.trace_log,
            "finalVars": self.interp.current_vars(),
        }


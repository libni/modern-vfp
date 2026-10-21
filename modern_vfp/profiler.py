"""
Perfilador de Rendimiento y Cobertura (`FoxProfiler`) para FoxNext / Modern VFP.
Mide tiempos de ejecución por sentencia, cantidad de ejecuciones por línea,
cobertura de código y detección de cuellos de botella (hotspots) en scripts .prg.
"""

from __future__ import annotations
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from .interpreter import FoxInterpreter


class FoxProfiler:
    """
    Perfilador de código xBase / Modern VFP.
    """

    def __init__(self, interpreter: Optional[FoxInterpreter] = None):
        self.interp: FoxInterpreter = interpreter or FoxInterpreter()
        self.line_hits: Dict[int, int] = {}
        self.line_times: Dict[int, float] = {}  # en milisegundos
        self.source_lines: List[str] = []
        self.total_time_ms: float = 0.0

    def run(self, source: str) -> Dict[str, Any]:
        """
        Ejecuta el programa registrando métricas de tiempo y conteo por línea.
        """
        self.source_lines = self.interp.preprocess_code(source)
        self.interp._register_top_level_definitions(self.source_lines)
        self.line_hits = {i: 0 for i in range(1, len(self.source_lines) + 1)}
        self.line_times = {i: 0.0 for i in range(1, len(self.source_lines) + 1)}

        has_structured_blocks = any(
            line.upper().startswith(("IF ", "DO WHILE", "DO CASE", "FOR ", "SCAN", "TRY", "DEFINE CLASS", "PROCEDURE", "FUNCTION", "TEXT TO"))
            for line in self.source_lines
        )

        t_start = time.perf_counter()

        if not has_structured_blocks:
            for idx, line in enumerate(self.source_lines, start=1):
                t0 = time.perf_counter()
                self.interp._exec_statement(self.interp._expand_macros(line))
                t1 = time.perf_counter()
                elapsed_ms = (t1 - t0) * 1000.0
                self.line_hits[idx] += 1
                self.line_times[idx] += elapsed_ms
        else:
            # Si contiene bloques estructurados, ejecutar completo y calcular métricas globales
            self.interp.execute(source)
            for idx in self.line_hits:
                self.line_hits[idx] = 1

        t_end = time.perf_counter()
        self.total_time_ms = (t_end - t_start) * 1000.0

        executed_lines = sum(1 for h in self.line_hits.values() if h > 0)
        total_lines = len(self.source_lines) or 1
        coverage_pct = (executed_lines / total_lines) * 100.0

        hotspots = sorted(
            [
                {"line": i, "timeMs": self.line_times[i], "hits": self.line_hits[i], "code": self.source_lines[i - 1]}
                for i in self.line_hits
            ],
            key=lambda x: x["timeMs"],
            reverse=True,
        )

        return {
            "totalTimeMs": self.total_time_ms,
            "totalLines": total_lines,
            "executedLines": executed_lines,
            "coveragePct": coverage_pct,
            "hotspots": hotspots[:5],
            "lineStats": [
                {
                    "line": i,
                    "hits": self.line_hits[i],
                    "timeMs": round(self.line_times[i], 3),
                    "code": self.source_lines[i - 1],
                }
                for i in range(1, len(self.source_lines) + 1)
            ],
        }

    def render_report(self) -> str:
        """
        Genera un reporte legible en consola con estadísticas y hotspots.
        """
        executed_lines = sum(1 for h in self.line_hits.values() if h > 0)
        total_lines = len(self.source_lines) or 1
        coverage_pct = (executed_lines / total_lines) * 100.0

        lines: List[str] = [
            "╔" + "═" * 76 + "╗",
            "║                      FOXNEXT PROFILER REPORT                              ║",
            "╠" + "═" * 76 + "╣",
            f"║ Tiempo Total: {self.total_time_ms:10.3f} ms | Líneas: {executed_lines}/{total_lines} ({coverage_pct:5.1f}% Cobertura)        ║",
            "╠══════╦═════════╦══════════════╦════════════════════════════════════════════╣",
            "║ Lín. ║ Hits    ║ Tiempo (ms)  ║ Sentencia / Código                         ║",
            "╠══════╬═════════╬══════════════╬════════════════════════════════════════════╣",
        ]

        for i in range(1, len(self.source_lines) + 1):
            hits = self.line_hits.get(i, 0)
            t_ms = self.line_times.get(i, 0.0)
            code = self.source_lines[i - 1][:42]
            lines.append(f"║ {i:4d} ║ {hits:7d} ║ {t_ms:12.3f} ║ {code:<42} ║")

        lines.append("╚══════╩═════════╩══════════════╩════════════════════════════════════════════╝")
        return "\n".join(lines)


def profile_file(src_path: str | Path, interpreter: Optional[FoxInterpreter] = None) -> str:
    path = Path(src_path)
    profiler = FoxProfiler(interpreter)
    profiler.run(path.read_text(encoding="utf-8"))
    return profiler.render_report()

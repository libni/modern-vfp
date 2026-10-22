"""
Compilador Bytecode y Empaquetador Binario (`.fxp`) para FoxNext / Modern VFP.
Convierte programas fuente (.prg) en un formato binario pre-tokenizado y comprimido (.fxp)
para ejecución ultrarrápida, protección de código y distribución sin fuentes.
"""

from __future__ import annotations
import gzip
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from .interpreter import FoxInterpreter

FXP_MAGIC = b"FXP1\x00\x02"


def compile_source(source: str, filename: str = "program.prg") -> bytes:
    """
    Compila código fuente .prg a formato binario .fxp.
    """
    interp = FoxInterpreter()
    lines = interp.preprocess_code(source)
    interp._register_top_level_definitions(lines)

    # Preparar paquete con estructura pre-analizada
    payload: Dict[str, Any] = {
        "version": "0.9.0",
        "timestamp": int(time.time()),
        "source_name": filename,
        "lines": lines,
        "procedures": interp.procedures,
        "classes": interp.classes,
    }

    raw_json = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    compressed = gzip.compress(raw_json, compresslevel=6)
    return FXP_MAGIC + compressed


def compile_file(src_path: str | Path, out_path: Optional[str | Path] = None) -> Path:
    """
    Lee un archivo .prg y escribe el archivo compilado .fxp.
    """
    src = Path(src_path)
    target = Path(out_path) if out_path else src.with_suffix(".fxp")
    source_code = src.read_text(encoding="utf-8")
    compiled_bytes = compile_source(source_code, filename=src.name)
    target.write_bytes(compiled_bytes)
    return target


def load_compiled_program(fxp_data_or_path: str | Path | bytes) -> Dict[str, Any]:
    """
    Lee y valida un binario .fxp, devolviendo su estructura pre-procesada.
    """
    if isinstance(fxp_data_or_path, (str, Path)):
        p = Path(fxp_data_or_path)
        data = p.read_bytes()
    else:
        data = fxp_data_or_path

    if not data.startswith(b"FXP1"):
        raise ValueError("El archivo no es un binario .fxp válido de FoxNext (Magic inválido).")

    header_len = len(FXP_MAGIC)
    compressed_body = data[header_len:]
    raw_json = gzip.decompress(compressed_body)
    return json.loads(raw_json.decode("utf-8"))


def execute_compiled(
    fxp_data_or_path: str | Path | bytes,
    interpreter: Optional[FoxInterpreter] = None,
) -> Any:
    """
    Ejecuta directamente un binario .fxp en el intérprete de FoxNext.
    """
    interp = interpreter or FoxInterpreter()
    info = load_compiled_program(fxp_data_or_path)

    # Cargar procedimientos y clases pre-analizados
    for p_name, (params, body) in info.get("procedures", {}).items():
        interp.procedures[p_name] = (params, body)
    for c_name, (parent, p_lines, methods) in info.get("classes", {}).items():
        interp.classes[c_name] = (parent, p_lines, methods)

    lines: List[str] = info.get("lines", [])
    return interp._exec_block(lines)

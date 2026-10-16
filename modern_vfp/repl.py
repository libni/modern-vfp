"""
Command Window Interactivo (REPL) y CLI Runner para FoxNext / Modern VFP.
Muestra una barra de estado en tiempo real con el Área de Trabajo activa, Alias, RECNO()/RECCOUNT() y EOF().
"""

from __future__ import annotations
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .foxform import FoxForm
from .interpreter import FoxInterpreter


BLOCK_OPENERS = ("IF ", "DO WHILE ", "DO CASE", "FOR ", "SCAN", "TRY", "PROCEDURE ", "FUNCTION ", "DEFINE CLASS ")
BLOCK_CLOSERS = ("ENDIF", "ENDDO", "ENDCASE", "ENDFOR", "NEXT", "ENDSCAN", "ENDTRY", "ENDPROC", "ENDFUNC", "ENDDEFINE")


def format_status_bar(interp: FoxInterpreter) -> str:
    cur = interp.wam.current_cursor()
    area = interp.wam.current_area
    del_state = "DEL:ON" if interp.wam.set_deleted else "DEL:OFF"
    if cur is None:
        return f"[Area:{area} | Sin Cursor | {del_state}]"
    rec = f"{cur.recno()}/{cur.reccount()}"
    eof_flag = "EOF" if cur.eof else "OK"
    tag = f" | Tag:{cur.active_tag}" if cur.active_tag else ""
    return f"[Area:{area} | Alias:{cur.alias.upper()} | Rec:{rec} ({eof_flag}){tag} | {del_state}]"


def run_repl(initial_interp: Optional[FoxInterpreter] = None) -> None:
    def _console_out(text: str, newline: bool = True) -> None:
        if newline:
            print(text)
        else:
            print(text, end="", flush=True)

    interp = initial_interp or FoxInterpreter(output_callback=_console_out)
    if interp._output_cb is None:
        interp._output_cb = _console_out

    print("=" * 72)
    print(f" FoxNext (Modern VFP) v{__version__} - Interactive Command Window (64-bit)")
    print(" Escribe comandos xBase/SQL ('HELP' para ayuda, 'QUIT' o 'EXIT' para salir)")
    print("=" * 72)

    multiline_buf: List[str] = []
    block_depth = 0

    while True:
        try:
            prompt = f"{format_status_bar(interp)}\nFoxNext> " if block_depth == 0 and not multiline_buf else "      .. "
            raw_line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print("\nSaliendo de FoxNext Command Window.")
            break

        stripped = raw_line.strip()
        if block_depth == 0 and not multiline_buf:
            if stripped.upper() in ("QUIT", "CANCEL"):
                print("Sesión finalizada.")
                break
            if stripped.upper() == "HELP":
                _print_help()
                continue
            if stripped.upper() == "STATUS":
                _print_status(interp)
                continue

        multiline_buf.append(raw_line)
        if stripped.endswith(";"):
            continue

        upper_line = stripped.upper()
        if any(upper_line.startswith(op) or upper_line == op.strip() for op in BLOCK_OPENERS):
            block_depth += 1
        elif any(upper_line.startswith(cl) for cl in BLOCK_CLOSERS):
            block_depth = max(0, block_depth - 1)

        if block_depth > 0:
            continue

        source_chunk = "\n".join(multiline_buf)
        multiline_buf.clear()

        try:
            interp.execute(source_chunk)
        except Exception as exc:
            print(f"[Error FoxNext]: {exc}")


def _print_help() -> None:
    print(
        """
Comandos Principales en FoxNext Command Window:
-----------------------------------------------
  CREATE CURSOR <alias> (id I, nombre C(40), saldo Y, activo L, fecha D)
  APPEND BLANK | INSERT INTO <alias> VALUES (...)
  REPLACE <campo> WITH <valor> [ALL] [FOR <condicion>]
  SELECT * FROM <alias> WHERE <cond> INTO CURSOR <nuevo_alias>
  BROWSE | LIST | DISPLAY STRUCTURE
  GO TOP | GO BOTTOM | GOTO <n> | SKIP [n]
  LOCATE FOR <cond> | CONTINUE
  INDEX ON <expr> TAG <nombre> | SET ORDER TO <tag> | SEEK <valor>
  DELETE [ALL] [FOR <cond>] | RECALL | PACK | ZAP | SET DELETED ON/OFF
  COPY TO <archivo.dbf | .csv | .json> [TYPE DBF|CSV|JSON]
  USE <archivo.dbf> [IN 0] [ALIAS <alias>]
  DO <archivo.prg>
  STATUS | CLEAR | QUIT
"""
    )


def _print_status(interp: FoxInterpreter) -> None:
    print("\n--- Estado de Áreas de Trabajo (Work Areas) ---")
    if not interp.wam.work_areas:
        print("  (No hay cursores abiertos)")
    for area, cur in sorted(interp.wam.work_areas.items()):
        active_mark = "*" if area == interp.wam.current_area else " "
        print(
            f" {active_mark} Area {area}: {cur.alias.upper()} "
            f"(Registros: {cur.reccount()}, RECNO: {cur.recno()}, Campos: {len(cur.fields)}, Tag: {cur.active_tag or 'Ninguno'})"
        )
    print(f"  SET DELETED: {'ON' if interp.wam.set_deleted else 'OFF'}\n")


def main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    def _console_out(text: str, newline: bool = True) -> None:
        if newline:
            print(text)
        else:
            print(text, end="", flush=True)

    interp = FoxInterpreter(output_callback=_console_out)

    if not args:
        run_repl(interp)
        return 0

    target_path = Path(args[0])
    if not target_path.exists():
        print(f"Error: El archivo '{target_path}' no existe.", file=sys.stderr)
        return 1

    if target_path.suffix.lower() == ".foxform":
        form = FoxForm.from_file(target_path, interpreter=interp)
        form.initialize()
        print(form.render_tui())
        return 0

    code = target_path.read_text(encoding="utf-8")
    interp.execute(code)
    return 0

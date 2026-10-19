"""
Servidor de Microservicios REST Basado en Cursores (`modern_vfp/apiserver.py`) para FoxNext.
Permite exponer cualquier cursor en memoria y procedimientos definidos en un `.prg`
como endpoints HTTP JSON instantáneos:
  - GET  /api/cursors            -> Lista todos los cursores activos
  - GET  /api/cursors/<alias>    -> Devuelve los registros del cursor en JSON
  - POST /api/cursors/<alias>    -> Inserta uno o varios registros JSON en el cursor
  - POST /api/rpc/<procedimiento>-> Invoca una FUNCTION/PROCEDURE de FoxNext con argumentos JSON
"""

from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional, Tuple

from .interpreter import FoxInterpreter


def dispatch_api_request(
    interp: FoxInterpreter,
    method: str,
    path: str,
    body: Optional[Dict[str, Any] | list] = None,
) -> Tuple[int, Dict[str, Any]]:
    """
    Procesa una petición REST sobre el intérprete FoxNext y devuelve `(status_code, response_dict)`.
    """
    m = method.upper()
    clean_path = path.split("?", 1)[0].rstrip("/")

    if m == "GET" and clean_path == "/api/cursors":
        cursors_info = []
        for area, cur in sorted(interp.wam.work_areas.items()):
            cursors_info.append({
                "area": area,
                "alias": cur.alias,
                "reccount": cur.reccount(),
                "fields": [f.name for f in cur.fields],
            })
        return 200, {"ok": True, "cursors": cursors_info}

    if clean_path.startswith("/api/cursors/"):
        alias = clean_path.split("/api/cursors/", 1)[1].strip().lower()
        cur = interp.wam.get_cursor(alias)
        if cur is None:
            return 404, {"ok": False, "error": f"El cursor '{alias}' no existe."}

        if m == "GET":
            rows = json.loads(interp.wam.cursor_to_json(alias))
            return 200, {"ok": True, "alias": alias, "count": len(rows), "data": rows}

        if m == "POST":
            if body is None:
                return 400, {"ok": False, "error": "Cuerpo JSON vacío."}
            items = body if isinstance(body, list) else [body]
            inserted = 0
            for item in items:
                if isinstance(item, dict):
                    cur.append_dict(item)
                    inserted += 1
            return 201, {"ok": True, "alias": alias, "inserted": inserted, "reccount": cur.reccount()}

    if m == "POST" and clean_path.startswith("/api/rpc/"):
        proc_name = clean_path.split("/api/rpc/", 1)[1].strip().lower()
        if proc_name not in interp.procedures:
            return 404, {"ok": False, "error": f"La función o procedimiento '{proc_name}' no está registrado."}
        args = []
        if isinstance(body, dict):
            args = body.get("args", [])
        elif isinstance(body, list):
            args = body
        params, proc_body = interp.procedures[proc_name]
        result = interp._invoke_Routine(params, proc_body, list(args))
        return 200, {"ok": True, "procedure": proc_name, "result": result}

    return 404, {"ok": False, "error": f"Ruta no encontrada: {method} {path}"}


def start_api_server(interp: FoxInterpreter, host: str = "127.0.0.1", port: int = 8766) -> None:
    """
    Inicia el servidor HTTP de Microservicios REST de FoxNext.
    """

    class FoxAPIHandler(BaseHTTPRequestHandler):
        def _handle(self, method: str) -> None:
            body_obj = None
            if method == "POST":
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                try:
                    body_obj = json.loads(raw)
                except json.JSONDecodeError:
                    body_obj = None

            status, payload = dispatch_api_request(interp, method, self.path, body_obj)
            resp_bytes = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = HTTPServer((host, port), FoxAPIHandler)
    print(f"FoxNext REST API Server activo en http://{host}:{port}/api/cursors")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo FoxNext REST API Server.")
    finally:
        server.server_close()

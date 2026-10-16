"""
Entorno Visual Interactivo (FoxNext Studio) para Modern VFP.
Provee una interfaz gráfica Web con Command Window acoplado, explorador de Data Session
(Áreas de Trabajo), visor BROWSE interactivo y previsualización de formularios (.foxform) y reportes (.foxreport).
"""

from __future__ import annotations
import datetime
import html
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

from .interpreter import FoxInterpreter


def serialize_session_state(interp: FoxInterpreter) -> Dict[str, Any]:
    """
    Serializa el estado actual de todas las Áreas de Trabajo (Work Areas), el cursor activo
    y la consola de salida para su visualización en FoxNext Studio.
    """
    work_areas_list: List[Dict[str, Any]] = []
    for area, cur in sorted(interp.wam.work_areas.items()):
        vis = cur.visible_recnos(interp.wam.set_deleted)
        rows_serialized: List[Dict[str, Any]] = []
        for r in vis[:250]:
            raw_row = cur.records[r - 1]
            clean_row: Dict[str, Any] = {
                "__recno__": r,
                "__deleted__": cur.deleted_flags[r - 1],
                "__current__": (r == cur.recno() and not cur.eof),
            }
            for f in cur.fields:
                v = raw_row.get(f.name)
                if isinstance(v, (datetime.date, datetime.datetime)):
                    clean_row[f.name] = v.isoformat()
                else:
                    clean_row[f.name] = v
            rows_serialized.append(clean_row)

        work_areas_list.append({
            "area": area,
            "alias": cur.alias.upper(),
            "active": area == interp.wam.current_area,
            "reccount": cur.reccount(),
            "recno": cur.recno(),
            "eof": cur.eof,
            "bof": cur.bof,
            "activeTag": cur.active_tag or "",
            "buffering": cur.buffering,
            "fields": [{"name": f.name, "type": f.ftype, "width": f.width, "decimals": f.decimals} for f in cur.fields],
            "rows": rows_serialized,
        })

    return {
        "currentArea": interp.wam.current_area,
        "setDeleted": interp.wam.set_deleted,
        "workAreas": work_areas_list,
        "consoleOutput": "\n".join(interp.output_buffer[-200:]),
    }


STUDIO_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>FoxNext Studio (Modern VFP 64-bit)</title>
<style>
  :root {
    --bg: #0f172a;
    --panel: #1e293b;
    --border: #334155;
    --accent: #3b82f6;
    --text: #f8fafc;
    --muted: #94a3b8;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: 'Inter', system-ui, sans-serif;
    background: var(--bg); color: var(--text);
    display: flex; flex-direction: column; height: 100vh;
  }
  header {
    background: linear-gradient(90deg, #1e3a8a, #2563eb);
    padding: 0.75rem 1.25rem; display: flex; justify-content: space-between; align-items: center;
    border-bottom: 1px solid var(--border);
  }
  header h1 { margin: 0; font-size: 1.1rem; font-weight: 700; letter-spacing: 0.3px; }
  .status-pill {
    background: rgba(15, 23, 42, 0.55); padding: 0.3rem 0.75rem;
    border-radius: 999px; font-family: monospace; font-size: 0.85rem;
  }
  main {
    flex: 1; display: grid; grid-template-columns: 280px 1fr 420px; gap: 1px;
    background: var(--border); overflow: hidden;
  }
  .pane { background: var(--panel); display: flex; flex-direction: column; overflow: hidden; }
  .pane-header {
    padding: 0.6rem 0.9rem; background: #0f172a; font-size: 0.8rem;
    font-weight: 700; text-transform: uppercase; letter-spacing: 0.6px; color: var(--muted);
    border-bottom: 1px solid var(--border);
  }
  .pane-body { flex: 1; padding: 0.85rem; overflow: auto; }
  .area-card {
    padding: 0.65rem 0.8rem; border: 1px solid var(--border); border-radius: 6px;
    margin-bottom: 0.5rem; cursor: pointer; background: #0f172a;
  }
  .area-card.active { border-color: var(--accent); background: rgba(59, 130, 246, 0.14); }
  .area-title { font-weight: 700; font-size: 0.95rem; display: flex; justify-content: space-between; }
  .area-meta { font-size: 0.78rem; color: var(--muted); margin-top: 0.25rem; font-family: monospace; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th, td { border: 1px solid var(--border); padding: 0.45rem 0.65rem; text-align: left; }
  th { background: #0f172a; color: #93c5fd; position: sticky; top: 0; }
  tr.current-row td { background: rgba(59, 130, 246, 0.22); font-weight: 600; }
  tr.deleted-row td { text-decoration: line-through; color: #f87171; }
  .cmd-output {
    flex: 1; background: #090d16; color: #a7f3d0; font-family: 'JetBrains Mono', monospace;
    font-size: 0.83rem; padding: 0.8rem; overflow: auto; white-space: pre-wrap;
    border-bottom: 1px solid var(--border);
  }
  .cmd-input-box { padding: 0.75rem; background: #0f172a; display: flex; flex-direction: column; gap: 0.5rem; }
  textarea {
    width: 100%; height: 95px; background: #1e293b; color: var(--text);
    border: 1px solid var(--border); border-radius: 6px; padding: 0.55rem;
    font-family: monospace; font-size: 0.88rem; resize: none;
  }
  .btn-row { display: flex; gap: 0.5rem; }
  button {
    background: var(--accent); color: white; border: none; padding: 0.48rem 0.95rem;
    border-radius: 5px; font-weight: 600; cursor: pointer; font-size: 0.83rem;
  }
  button.secondary { background: #334155; }
</style>
</head>
<body>
<header>
  <h1>FoxNext Studio · Visual Data Environment & Command Window (64-bit)</h1>
  <div class="status-pill" id="statusPill">Area: 1 | Listo</div>
</header>
<main>
  <section class="pane">
    <div class="pane-header">Data Session (Work Areas)</div>
    <div class="pane-body" id="workAreasList"></div>
  </section>
  <section class="pane">
    <div class="pane-header" id="browseHeader">BROWSE Grid</div>
    <div class="pane-body" id="browseContainer"></div>
  </section>
  <section class="pane">
    <div class="pane-header">Command Window (xBase / SQL)</div>
    <div class="cmd-output" id="consoleOutput"></div>
    <div class="cmd-input-box">
      <textarea id="cmdInput" placeholder="Escribe comandos VFP o SQL (Ej: SELECT * FROM clientes INTO CURSOR cur1)..."></textarea>
      <div class="btn-row">
        <button onclick="runCommand()">Ejecutar (Ctrl+Enter)</button>
        <button class="secondary" onclick="runPreset('DO examples/demo_ventas.prg')">Demo Ventas</button>
        <button class="secondary" onclick="runPreset('CLEAR')">Limpiar</button>
      </div>
    </div>
  </section>
</main>
<script>
let currentState = __INITIAL_STATE__;

function renderStudio(state) {
  currentState = state;
  const activeAreaObj = state.workAreas.find(w => w.active);
  const pill = document.getElementById('statusPill');
  if (activeAreaObj) {
    pill.textContent = `Area: ${activeAreaObj.area} | Alias: ${activeAreaObj.alias} | Rec: ${activeAreaObj.recno}/${activeAreaObj.reccount} | EOF: ${activeAreaObj.eof ? '.T.' : '.F.'}`;
  } else {
    pill.textContent = `Area: ${state.currentArea} | Sin Cursor Activo | DEL: ${state.setDeleted ? 'ON' : 'OFF'}`;
  }

  const waList = document.getElementById('workAreasList');
  waList.innerHTML = '';
  if (state.workAreas.length === 0) {
    waList.innerHTML = '<p style="color:#94a3b8;font-size:0.85rem;">No hay cursores abiertos en la sesión.</p>';
  }
  state.workAreas.forEach(w => {
    const div = document.createElement('div');
    div.className = 'area-card' + (w.active ? ' active' : '');
    div.onclick = () => runPreset(`SELECT ${w.alias}`);
    div.innerHTML = `
      <div class="area-title"><span>${w.alias}</span><span>#${w.area}</span></div>
      <div class="area-meta">Rec: ${w.recno}/${w.reccount} | Campos: ${w.fields.length} ${w.activeTag ? '| Tag: ' + w.activeTag : ''}</div>
    `;
    waList.appendChild(div);
  });

  const browseHdr = document.getElementById('browseHeader');
  const browseBox = document.getElementById('browseContainer');
  if (!activeAreaObj) {
    browseHdr.textContent = 'BROWSE Grid (Sin Cursor)';
    browseBox.innerHTML = '<p style="color:#94a3b8;">Selecciona o crea un cursor en la Command Window.</p>';
  } else {
    browseHdr.textContent = `BROWSE: ${activeAreaObj.alias} (${activeAreaObj.rows.length} visibles)`;
    let tbl = '<table><thead><tr><th>Rec#</th>';
    activeAreaObj.fields.forEach(f => { tbl += `<th>${f.name.toUpperCase()} (${f.type})</th>`; });
    tbl += '</tr></thead><tbody>';
    activeAreaObj.rows.forEach(r => {
      const cls = (r.__current__ ? 'current-row ' : '') + (r.__deleted__ ? 'deleted-row' : '');
      tbl += `<tr class="${cls}"><td>${r.__current__ ? '▶ ' : ''}${r.__recno__}${r.__deleted__ ? ' *' : ''}</td>`;
      activeAreaObj.fields.forEach(f => {
        const val = r[f.name] === null || r[f.name] === undefined ? '' : r[f.name];
        tbl += `<td>${String(val)}</td>`;
      });
      tbl += '</tr>';
    });
    tbl += '</tbody></table>';
    browseBox.innerHTML = tbl;
  }

  const outBox = document.getElementById('consoleOutput');
  outBox.textContent = state.consoleOutput || '(Command Window lista)';
  outBox.scrollTop = outBox.scrollHeight;
}

async function sendCommand(code) {
  const res = await fetch('/api/exec', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code })
  });
  const data = await res.json();
  renderStudio(data);
}

function runCommand() {
  const input = document.getElementById('cmdInput');
  const code = input.value.trim();
  if (!code) return;
  input.value = '';
  sendCommand(code);
}

function runPreset(code) {
  sendCommand(code);
}

document.getElementById('cmdInput').addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault();
    runCommand();
  }
});

renderStudio(currentState);
</script>
</body>
</html>
"""


def render_studio_snapshot_html(interp: FoxInterpreter) -> str:
    state_json = json.dumps(serialize_session_state(interp), ensure_ascii=False)
    return STUDIO_HTML_TEMPLATE.replace("__INITIAL_STATE__", state_json)


def start_studio_server(interp: Optional[FoxInterpreter] = None, host: str = "127.0.0.1", port: int = 8765) -> None:
    """
    Inicia el servidor interactivo de FoxNext Studio en `http://127.0.0.1:8765`.
    """
    engine = interp or FoxInterpreter()

    class StudioHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            html_payload = render_studio_snapshot_html(engine).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_payload)))
            self.end_headers()
            self.wfile.write(html_payload)

        def do_POST(self) -> None:
            if self.path == "/api/exec":
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8")
                payload = json.loads(raw or "{}")
                code = payload.get("code", "")
                if code.strip():
                    engine.emit(f"\nFoxNext> {code}")
                    try:
                        engine.execute(code)
                    except Exception as exc:
                        engine.emit(f"[Error]: {exc}")
                resp_bytes = json.dumps(serialize_session_state(engine), ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = HTTPServer((host, port), StudioHandler)
    print(f"FoxNext Studio ejecutándose en: http://{host}:{port} (Presiona Ctrl+C para detener)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo FoxNext Studio.")
    finally:
        server.server_close()

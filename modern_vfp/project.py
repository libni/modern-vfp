"""
Gestor y Empaquetador de Proyectos (.foxproj / .foxapp) para FoxNext / Modern VFP.
Reemplaza los archivos binarios .pjx/.pjt de Visual FoxPro 9 por un manifiesto JSON Git-friendly,
permitiendo compilar y empaquetar aplicaciones completas mediante `BUILD APP`.
"""

from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class FoxProject:
    """
    Representa un proyecto FoxNext (.foxproj) con su programa principal (main),
    módulos (.prg), formularios (.foxform) y reportes (.foxreport).
    """

    def __init__(self, spec: Dict[str, Any], base_dir: Optional[Path] = None):
        root = spec.get("project", spec)
        self.name: str = root.get("name", "FoxNextApp")
        self.version: str = root.get("version", "1.0.0")
        self.main: str = root.get("main", "main.prg")
        self.programs: List[str] = root.get("programs", [])
        self.forms: List[str] = root.get("forms", [])
        self.reports: List[str] = root.get("reports", [])
        self.base_dir: Path = base_dir or Path.cwd()

    @classmethod
    def from_file(cls, filepath: str | Path) -> "FoxProject":
        path = Path(filepath).resolve()
        spec = json.loads(path.read_text(encoding="utf-8"))
        return cls(spec, base_dir=path.parent)

    def _resolve_asset(self, rel_path: str) -> Path:
        p = Path(rel_path)
        if p.is_absolute():
            return p
        return (self.base_dir / p).resolve()

    def build_app(self, output_path: str | Path) -> Path:
        """
        Empaqueta todos los recursos del proyecto (.prg, .foxform, .foxreport)
        en un paquete distribuible `.foxapp` autocontenido.
        """
        main_file = self._resolve_asset(self.main)
        if not main_file.is_file():
            raise FileNotFoundError(f"El programa principal '{self.main}' no existe en '{main_file}'.")

        bundle_files: Dict[str, str] = {
            self.main: main_file.read_text(encoding="utf-8"),
        }

        for item in self.programs + self.forms + self.reports:
            asset_path = self._resolve_asset(item)
            if not asset_path.is_file():
                raise FileNotFoundError(f"El recurso '{item}' del proyecto no existe en '{asset_path}'.")
            bundle_files[item] = asset_path.read_text(encoding="utf-8")

        app_payload = {
            "foxapp": {
                "name": self.name,
                "version": self.version,
                "builtAt": datetime.datetime.now().isoformat(),
                "main": self.main,
                "assets": bundle_files,
            }
        }

        out_p = Path(output_path)
        if not out_p.suffix:
            out_p = out_p.with_suffix(".foxapp")
        out_p.write_text(json.dumps(app_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return out_p


def run_foxapp(app_path: str | Path, interpreter: Any) -> Any:
    """
    Carga y ejecuta un paquete `.foxapp` compilado con `BUILD APP`.
    """
    path = Path(app_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    app_root = payload.get("foxapp", payload)
    main_key = app_root.get("main", "")
    assets = app_root.get("assets", {})
    if main_key not in assets:
        raise RuntimeError(f"El paquete '{path}' no contiene el punto de entrada '{main_key}'.")
    return interpreter.execute(assets[main_key])

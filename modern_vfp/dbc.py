"""
Contenedor de Bases de Datos (`.dbc` / `FoxDatabase`) para FoxNext / Modern VFP.
Administra diccionarios de datos, relaciones persistentes entre tablas,
reglas de validación a nivel de campo y registro (`CHECK`), y valores por defecto.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class FoxDatabase:
    """
    Representa un Contenedor de Base de Datos (.dbc) de FoxNext.
    """

    def __init__(self, name: str, path: Optional[str | Path] = None):
        raw_name = str(name).strip()
        p = Path(path) if path else Path(raw_name)
        if not p.suffix:
            p = p.with_suffix(".dbc")
        self.path: Path = p
        self.name: str = p.stem.lower()
        # tables: table_name -> {"alias": str, "field_rules": {fname: {"rule": str, "msg": str, "default": Any}}, "table_rule": Optional[str], "table_rule_msg": str}
        self.tables: Dict[str, Dict[str, Any]] = {}
        # relations: [{"parent": str, "child": str, "parent_key": str, "child_tag": str}]
        self.relations: List[Dict[str, str]] = []

    def save(self, target_path: Optional[str | Path] = None) -> Path:
        p = Path(target_path) if target_path else self.path
        if not p.suffix:
            p = p.with_suffix(".dbc")
        payload = {
            "format": "FoxNext_DBC_v1",
            "name": self.name,
            "tables": self.tables,
            "relations": self.relations,
        }
        p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.path = p
        return p

    @classmethod
    def load(cls, file_path: str | Path) -> "FoxDatabase":
        p = Path(file_path)
        if not p.suffix:
            p = p.with_suffix(".dbc")
        raw = json.loads(p.read_text(encoding="utf-8"))
        db = cls(name=raw.get("name", p.stem), path=p)
        db.tables = raw.get("tables", {})
        db.relations = raw.get("relations", [])
        return db

    def add_table(self, table_name: str, alias: Optional[str] = None) -> None:
        t_key = table_name.lower().strip()
        self.tables[t_key] = {
            "name": t_key,
            "alias": (alias or t_key).lower().strip(),
            "field_rules": {},
            "table_rule": None,
            "table_rule_msg": "",
        }
        self.save()

    def remove_table(self, table_name: str) -> None:
        t_key = table_name.lower().strip()
        self.tables.pop(t_key, None)
        self.relations = [
            r for r in self.relations if r["parent"] != t_key and r["child"] != t_key
        ]
        self.save()

    def set_field_rule(
        self,
        table_name: str,
        field_name: str,
        rule_expr: str,
        error_msg: str = "",
        default_val: Any = None,
    ) -> None:
        t_key = table_name.lower().strip()
        f_key = field_name.lower().strip()
        if t_key not in self.tables:
            self.add_table(t_key)
        self.tables[t_key]["field_rules"][f_key] = {
            "rule": rule_expr.strip(),
            "msg": error_msg or f"Validación de campo falló en '{field_name}'",
            "default": default_val,
        }
        self.save()

    def set_table_rule(self, table_name: str, rule_expr: str, error_msg: str = "") -> None:
        t_key = table_name.lower().strip()
        if t_key not in self.tables:
            self.add_table(t_key)
        self.tables[t_key]["table_rule"] = rule_expr.strip()
        self.tables[t_key]["table_rule_msg"] = error_msg or f"Validación de registro falló en tabla '{table_name}'"
        self.save()

    def add_relation(self, parent_table: str, child_table: str, parent_key: str, child_tag: str) -> None:
        rel = {
            "parent": parent_table.lower().strip(),
            "child": child_table.lower().strip(),
            "parent_key": parent_key.strip(),
            "child_tag": child_tag.strip().lower(),
        }
        if rel not in self.relations:
            self.relations.append(rel)
            self.save()

    def validate_database(self, eval_fn: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
        """
        Verifica la integridad de las tablas y relaciones definidas en el contenedor .dbc.
        """
        issues: List[str] = []
        for t_name, t_meta in self.tables.items():
            for f_name, f_info in t_meta.get("field_rules", {}).items():
                rule = f_info.get("rule")
                if not rule:
                    issues.append(f"Regla vacía para campo '{f_name}' en tabla '{t_name}'.")

        for r in self.relations:
            if r["parent"] not in self.tables:
                issues.append(f"Tabla padre '{r['parent']}' no existe en el contenedor DBC.")
            if r["child"] not in self.tables:
                issues.append(f"Tabla hija '{r['child']}' no existe en el contenedor DBC.")

        is_valid = len(issues) == 0
        return {
            "database": self.name,
            "path": str(self.path),
            "tablesCount": len(self.tables),
            "relationsCount": len(self.relations),
            "isValid": is_valid,
            "issues": issues,
        }

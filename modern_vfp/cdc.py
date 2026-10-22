"""
Motor de Auditoría y Captura de Cambios (Change Data Capture - CDC) (`modern_vfp/cdc.py`) para FoxNext.
Permite rastrear automáticamente todas las mutaciones en cursores (INSERT, UPDATE, DELETE, RECALL):
- Registro histórico con timestamp, operación, número de registro y valores previos / posteriores
- Comando: `ENABLE AUDIT ON <alias> [TO FILE <archivo.jsonl>]`
- Comando: `DISABLE AUDIT ON <alias>`
- Función: `GETAUDITLOG([cAlias])` -> Retorna lista o Cursor con la traza de auditoría
"""

from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .cursor import Cursor, FieldDef


class AuditEntry:
    def __init__(
        self,
        alias: str,
        recno: int,
        operation: str,
        old_data: Optional[Dict[str, Any]] = None,
        new_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.timestamp = datetime.datetime.now().isoformat()
        self.alias = alias.lower().strip()
        self.recno = recno
        self.operation = operation.upper().strip()
        self.old_data = old_data or {}
        self.new_data = new_data or {}

        # Determinar campos modificados
        self.changed_fields: List[str] = []
        if self.operation == "UPDATE" and old_data and new_data:
            for k in set(old_data.keys()).union(new_data.keys()):
                if old_data.get(k) != new_data.get(k):
                    self.changed_fields.append(k)
        elif self.operation == "INSERT" and new_data:
            self.changed_fields = list(new_data.keys())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "alias": self.alias,
            "recno": self.recno,
            "operation": self.operation,
            "changed_fields": ",".join(self.changed_fields),
            "old_data": json.dumps(self.old_data, default=str),
            "new_data": json.dumps(self.new_data, default=str),
        }


class ChangeDataCaptureManager:
    """Administrador centralizado de pistas de auditoría por cursor."""

    def __init__(self) -> None:
        # alias -> list of AuditEntry
        self._entries: Dict[str, List[AuditEntry]] = {}
        # alias -> optional log file path
        self._dest_files: Dict[str, Path] = {}
        # active monitored aliases
        self._monitored: Dict[str, bool] = {}

    def enable(self, alias: str, to_file: Optional[str] = None) -> None:
        al = alias.lower().strip()
        self._monitored[al] = True
        self._entries.setdefault(al, [])
        if to_file:
            self._dest_files[al] = Path(to_file)

    def disable(self, alias: str) -> None:
        al = alias.lower().strip()
        self._monitored.pop(al, None)

    def is_monitored(self, alias: str) -> bool:
        return self._monitored.get(alias.lower().strip(), False)

    def record_change(
        self,
        alias: str,
        recno: int,
        operation: str,
        old_data: Optional[Dict[str, Any]] = None,
        new_data: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        al = alias.lower().strip()
        entry = AuditEntry(al, recno, operation, old_data, new_data)
        self._entries.setdefault(al, []).append(entry)

        # Si hay archivo de destino configurado, volcar como JSON Lines
        if al in self._dest_files:
            p = self._dest_files[al]
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")

        return entry

    def get_entries(self, alias: Optional[str] = None) -> List[AuditEntry]:
        if alias:
            return list(self._entries.get(alias.lower().strip(), []))
        all_entries: List[AuditEntry] = []
        for entries in self._entries.values():
            all_entries.extend(entries)
        all_entries.sort(key=lambda x: x.timestamp)
        return all_entries

    def create_audit_cursor(self, alias: Optional[str] = None, into_alias: str = "audit_log") -> Cursor:
        """Convierte los registros de auditoría en un Cursor de FoxNext."""
        fields = [
            FieldDef("timestamp", "C", 30, 0),
            FieldDef("alias", "C", 20, 0),
            FieldDef("recno", "I", 10, 0),
            FieldDef("operation", "C", 10, 0),
            FieldDef("changed", "C", 100, 0),
            FieldDef("old_data", "M", 254, 0),
            FieldDef("new_data", "M", 254, 0),
        ]
        cur = Cursor(into_alias.lower().strip(), fields)
        entries = self.get_entries(alias)
        for e in entries:
            d = e.to_dict()
            cur.append_dict(
                {
                    "timestamp": d["timestamp"],
                    "alias": d["alias"],
                    "recno": d["recno"],
                    "operation": d["operation"],
                    "changed": d["changed_fields"],
                    "old_data": d["old_data"],
                    "new_data": d["new_data"],
                }
            )
        cur.go_top()
        return cur

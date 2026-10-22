"""
Motor de Concurrencia y Bloqueos Multiusuario (`modern_vfp/locks.py`) para FoxNext.
Implementa el modelo estándar de Visual FoxPro:
- Bloqueo de registros individuales o múltiples: `RLOCK()`
- Bloqueo de tabla / archivo completo: `FLOCK()`
- Liberación granular o total de bloqueos: `UNLOCK`
- Banderas de configuración: `SET EXCLUSIVE ON|OFF`, `SET MULTILOCKS ON|OFF`
- Funciones de estado: `ISLOCKED([nRecno, cAlias])`, `ISREADONLY([cAlias])`
"""

from __future__ import annotations
from typing import Any, Dict, Optional, Set


class LockManager:
    """
    Administra bloqueos de tablas y registros por alias/cursor.
    """

    def __init__(self) -> None:
        # alias -> Set[recno]
        self._record_locks: Dict[str, Set[int]] = {}
        # alias -> bool (si tiene FLOCK activo)
        self._table_locks: Dict[str, bool] = {}
        self.set_exclusive: bool = False
        self.set_multilocks: bool = True

    def rlock(self, alias: str, recno: int) -> bool:
        al = alias.lower().strip()
        if not self.set_multilocks:
            self._record_locks[al] = {recno}
        else:
            self._record_locks.setdefault(al, set()).add(recno)
        return True

    def flock(self, alias: str) -> bool:
        al = alias.lower().strip()
        self._table_locks[al] = True
        return True

    def unlock(self, alias: Optional[str] = None, recno: Optional[int] = None, all_records: bool = False) -> None:
        if alias is None:
            # UNLOCK ALL
            self._record_locks.clear()
            self._table_locks.clear()
            return

        al = alias.lower().strip()
        if all_records or recno is None:
            self._record_locks.pop(al, None)
            self._table_locks.pop(al, None)
        else:
            if al in self._record_locks:
                self._record_locks[al].discard(recno)

    def is_locked(self, alias: str, recno: Optional[int] = None) -> bool:
        al = alias.lower().strip()
        if self._table_locks.get(al, False):
            return True
        if recno is not None:
            return recno in self._record_locks.get(al, set())
        return len(self._record_locks.get(al, set())) > 0

    def get_locked_records(self, alias: str) -> Set[int]:
        return set(self._record_locks.get(alias.lower().strip(), set()))

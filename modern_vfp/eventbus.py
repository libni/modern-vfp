"""
Bus de Eventos y Cola de Mensajes Asíncrona (`FoxEventBus`) para FoxNext.
Permite arquitecturas reactivas desacopladas y microservicios basados en eventos
mediante comandos nativos:
  PUBLISH EVENT <topic> [DATA <expr>]
  SUBSCRIBE EVENT <topic> WITH <nombre_procedimiento>
"""

from __future__ import annotations
import datetime
import json
from typing import Any, Callable, Dict, List, Optional


class FoxEventBus:
    """
    Bus de eventos en memoria y despachador de tópicos.
    """

    def __init__(self) -> None:
        # topic -> list of callbacks
        self._subscribers: Dict[str, List[Callable[[str, Any], None]]] = {}
        # topic -> list of procedure names in FoxInterpreter
        self._procedure_subscribers: Dict[str, List[str]] = {}
        self.history: List[Dict[str, Any]] = []

    def subscribe(self, topic: str, callback: Callable[[str, Any], None]) -> None:
        t = topic.lower().strip()
        self._subscribers.setdefault(t, []).append(callback)

    def subscribe_procedure(self, topic: str, procedure_name: str) -> None:
        t = topic.lower().strip()
        pname = procedure_name.lower().strip()
        if pname not in self._procedure_subscribers.setdefault(t, []):
            self._procedure_subscribers[t].append(pname)

    def publish(self, topic: str, data: Any = None, interpreter: Optional[Any] = None) -> int:
        t = topic.lower().strip()
        event_entry = {
            "topic": t,
            "data": data,
            "timestamp": datetime.datetime.now().isoformat(),
        }
        self.history.append(event_entry)
        dispatched = 0

        # Disparar callbacks directos
        for cb in self._subscribers.get(t, []):
            try:
                cb(t, data)
                dispatched += 1
            except Exception:
                pass

        # Disparar procedimientos VFP registrados
        if interpreter:
            for proc_name in self._procedure_subscribers.get(t, []):
                if proc_name in interpreter.procedures:
                    try:
                        interpreter._invoke_Routine(
                            interpreter.procedures[proc_name][0],
                            interpreter.procedures[proc_name][1],
                            [data] if data is not None else [],
                        )
                        dispatched += 1
                    except Exception:
                        pass
        return dispatched

    def clear(self) -> None:
        self._subscribers.clear()
        self._procedure_subscribers.clear()
        self.history.clear()

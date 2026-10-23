"""
Motor de Limitación de Tasa y Regulación de Tráfico (Rate Limiter / Token Bucket) (`modern_vfp/ratelimit.py`) para FoxNext.
Permite regular el tráfico en APIs REST, procesos batch y colas de tareas con ventanas deslizantes:
- `RATELIMIT_CHECK(cCliente, nLimitePeticiones, nSegundosVentana)` -> .T. si se permite, .F. si excede
- `RATELIMIT_REMAINING(cCliente, nLimite, nSegundos)` -> Peticiones restantes en la ventana activa
- `RATELIMIT_RESET([cCliente])` -> Reinicia el contador de peticiones
- Comando: `THROTTLE <cliente> LIMIT <n> PER <segundos> [ERROR <mensaje>]`
"""

from __future__ import annotations
import time
from typing import Dict, List, Optional


class RateLimiter:
    """Implementación de limitador de tasa mediante Ventana Deslizante (Sliding Window Log)."""

    def __init__(self) -> None:
        # key -> list of float timestamps
        self._requests: Dict[str, List[float]] = {}

    def check(self, key: str, max_requests: int, window_seconds: float) -> bool:
        """
        Evalúa si la solicitud es admitida dentro de la ventana de tiempo.
        Registra el timestamp si es admitida.
        """
        k = str(key).strip().lower()
        now = time.time()
        window = float(window_seconds)
        cutoff = now - window

        # Filtrar timestamps que cayeron fuera de la ventana
        timestamps = [t for t in self._requests.get(k, []) if t > cutoff]

        if len(timestamps) < int(max_requests):
            timestamps.append(now)
            self._requests[k] = timestamps
            return True

        self._requests[k] = timestamps
        return False

    def remaining(self, key: str, max_requests: int, window_seconds: float) -> int:
        """Devuelve el número de peticiones restantes disponibles en la ventana actual."""
        k = str(key).strip().lower()
        now = time.time()
        cutoff = now - float(window_seconds)
        timestamps = [t for t in self._requests.get(k, []) if t > cutoff]
        self._requests[k] = timestamps
        rem = int(max_requests) - len(timestamps)
        return max(0, rem)

    def reset(self, key: Optional[str] = None) -> None:
        """Reinicia el contador para una clave específica o para todas."""
        if key:
            self._requests.pop(str(key).strip().lower(), None)
        else:
            self._requests.clear()

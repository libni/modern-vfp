"""
Motor de Caché en Memoria de Alto Rendimiento con TTL y LRU (`modern_vfp/cache.py`) para FoxNext.
Permite almacenar valores calculados, consultas y tokens con expiración temporal:
- `CACHE_SET(cClave, eValor [, nSegundosTTL])`
- `CACHE_GET(cClave [, eValorDefecto])`
- `CACHE_HAS(cClave)`
- `CACHE_DELETE(cClave)`
- `CACHE_CLEAR()`
- `CACHE_STATS()`
"""

from __future__ import annotations
from collections import OrderedDict
import time
from typing import Any, Dict, Optional, Tuple


class CacheEntry:
    def __init__(self, value: Any, expires_at: Optional[float] = None) -> None:
        self.value = value
        self.expires_at = expires_at

    def is_expired(self, now: float) -> bool:
        if self.expires_at is None:
            return False
        return now >= self.expires_at


class FoxCache:
    """Caché LRU en memoria con expiración por clave (TTL)."""

    def __init__(self, max_items: int = 10000) -> None:
        self.max_items = max_items
        # key -> CacheEntry
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self.hits: int = 0
        self.misses: int = 0

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        k = str(key).strip().lower()
        now = time.time()
        exp = now + float(ttl_seconds) if ttl_seconds is not None and float(ttl_seconds) > 0 else None

        if k in self._store:
            self._store.move_to_end(k)
        elif len(self._store) >= self.max_items:
            # Evicción LRU del elemento más antiguo
            self._store.popitem(last=False)

        self._store[k] = CacheEntry(value, exp)

    def get(self, key: str, default: Any = None) -> Any:
        k = str(key).strip().lower()
        now = time.time()
        entry = self._store.get(k)
        if entry is None:
            self.misses += 1
            return default

        if entry.is_expired(now):
            del self._store[k]
            self.misses += 1
            return default

        self.hits += 1
        self._store.move_to_end(k)
        return entry.value

    def has(self, key: str) -> bool:
        k = str(key).strip().lower()
        now = time.time()
        entry = self._store.get(k)
        if entry is None:
            return False
        if entry.is_expired(now):
            del self._store[k]
            return False
        return True

    def delete(self, key: str) -> bool:
        k = str(key).strip().lower()
        if k in self._store:
            del self._store[k]
            return True
        return False

    def clear(self) -> None:
        self._store.clear()
        self.hits = 0
        self.misses = 0

    def stats(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        ratio = round((self.hits / total) * 100, 2) if total > 0 else 0.0
        return {
            "items": len(self._store),
            "hits": self.hits,
            "misses": self.misses,
            "total_requests": total,
            "hit_ratio_pct": ratio,
        }

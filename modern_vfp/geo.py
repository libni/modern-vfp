"""
Motor Geoespacial y Geocercas (`modern_vfp/geo.py`) para FoxNext / Modern VFP.
Proporciona cálculos de distancia geográfica (Haversine), geocercas poligonales y filtros de radio:
- `GEODISTANCE(lat1, lon1, lat2, lon2 [, "KM"|"MILES"])` -> Distancia superficial
- `GEOINPOLYGON(lat, lon, aPuntosPoligono)` -> .T. si el punto está dentro del polígono
- `GEOINBOUNDS(lat, lon, minLat, minLon, maxLat, maxLon)` -> .T. si está dentro del recuadro
- `FILTER GEORADIUS ON <alias> LAT <col_lat> LON <col_lon> CENTER <lat>, <lon> RADIUS <dist> [KM|MILES] [INTO CURSOR <res>]`
"""

from __future__ import annotations
import math
from typing import Any, List, Optional, Sequence, Tuple, Union

from .cursor import Cursor, FieldDef


def geodistance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    unit: str = "KM",
) -> float:
    """
    Calcula la distancia geodésica ortodrómica en superficie esférica utilizando la fórmula de Haversine.
    """
    r_earth = 6371.0 if unit.upper().strip() != "MILES" else 3958.8

    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    dist = r_earth * c
    return round(dist, 2)


def geoinpolygon(
    lat: float,
    lon: float,
    polygon_points: Sequence[Any],
) -> bool:
    """
    Determina si un punto (latitud, longitud) se encuentra dentro de un polígono
    utilizando el algoritmo de lanzamiento de rayos (Ray-Casting).
    """
    x = float(lon)
    y = float(lat)
    n = len(polygon_points)
    if n < 3:
        return False

    inside = False
    p1 = polygon_points[0]
    p1x = float(p1[1] if isinstance(p1, (list, tuple)) else p1["lon"])
    p1y = float(p1[0] if isinstance(p1, (list, tuple)) else p1["lat"])

    for i in range(1, n + 1):
        p2 = polygon_points[i % n]
        p2x = float(p2[1] if isinstance(p2, (list, tuple)) else p2["lon"])
        p2y = float(p2[0] if isinstance(p2, (list, tuple)) else p2["lat"])

        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y

    return inside


def geoinbounds(
    lat: float,
    lon: float,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
) -> bool:
    """Verifica si las coordenadas están dentro de la caja delimitadora (Bounding Box)."""
    return (
        float(min_lat) <= float(lat) <= float(max_lat)
        and float(min_lon) <= float(lon) <= float(max_lon)
    )


def filter_georadius(
    cur: Cursor,
    lat_col: str,
    lon_col: str,
    center_lat: float,
    center_lon: float,
    radius: float,
    unit: str = "KM",
    into_alias: str = "geo_result",
    set_deleted_on: bool = False,
) -> Cursor:
    """
    Filtra los registros de un cursor cuya distancia al centro esté dentro del radio especificado,
    añadiendo la columna calculada `geo_dist`.
    """
    lc = lat_col.lower().strip()
    lnc = lon_col.lower().strip()
    rad = float(radius)

    out_fields = list(cur.fields) + [FieldDef("geo_dist", "N", 10, 2)]
    out_cur = Cursor(into_alias.lower().strip(), out_fields)

    vis = cur.visible_recnos(set_deleted_on)
    matches: List[Tuple[float, Dict[str, Any]]] = []

    for r in vis:
        row = cur.records[r - 1]
        raw_lat = row.get(lc)
        raw_lon = row.get(lnc)
        if raw_lat is not None and raw_lon is not None:
            try:
                d = geodistance(float(raw_lat), float(raw_lon), center_lat, center_lon, unit)
                if d <= rad:
                    new_row = dict(row)
                    new_row["geo_dist"] = d
                    matches.append((d, new_row))
            except (ValueError, TypeError):
                continue

    # Ordenar por proximidad al centro
    matches.sort(key=lambda x: x[0])
    for _, row_dict in matches:
        out_cur.append_dict(row_dict)

    out_cur.go_top()
    return out_cur

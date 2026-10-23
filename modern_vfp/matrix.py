"""
Operaciones Matriciales y Regresión Lineal de Negocios (`modern_vfp/matrix.py`) para FoxNext.
Proporciona álgebra lineal estándar y modelos predictivos para análisis de tendencias:
- `MMULT(aMatrizA, aMatrizB [, "aMatrizResultado"])` -> Multiplicación de matrices
- `MTRANSPOSE(aMatriz [, "aMatrizResultado"])` -> Transposición de matriz
- `VDOT(aVectorA, aVectorB)` -> Producto punto de vectores
- `LINEST(aValoresY, aValoresX)` -> Regresión lineal simple (pendiente, intersección, R^2)
"""

from __future__ import annotations
import math
from typing import Any, Dict, List, Sequence, Tuple, Union


def _to_matrix(data: Any) -> List[List[float]]:
    """Convierte listas simples o bidimensionales a matriz float homogénea."""
    if not isinstance(data, (list, tuple)):
        raise TypeError("Se esperaba un arreglo o lista.")
    if not data:
        return []
    if isinstance(data[0], (list, tuple)):
        return [[float(cell) for cell in row] for row in data]
    return [[float(x) for x in data]]


def mmult(a: Any, b: Any) -> List[List[float]]:
    """Multiplicación matricial estándar C = A x B."""
    mat_a = _to_matrix(a)
    mat_b = _to_matrix(b)

    rows_a = len(mat_a)
    cols_a = len(mat_a[0]) if rows_a > 0 else 0
    rows_b = len(mat_b)
    cols_b = len(mat_b[0]) if rows_b > 0 else 0

    if cols_a != rows_b:
        raise ValueError(f"Dimensiones incompatibles para multiplicación: ({rows_a}x{cols_a}) y ({rows_b}x{cols_b}).")

    result: List[List[float]] = [[0.0 for _ in range(cols_b)] for _ in range(rows_a)]

    for i in range(rows_a):
        for j in range(cols_b):
            s = 0.0
            for k in range(cols_a):
                s += mat_a[i][k] * mat_b[k][j]
            result[i][j] = round(s, 4)

    return result


def mtranspose(a: Any) -> List[List[float]]:
    """Transpone una matriz (intercambia filas por columnas)."""
    mat = _to_matrix(a)
    if not mat:
        return []
    rows = len(mat)
    cols = len(mat[0])
    trans: List[List[float]] = [[mat[r][c] for r in range(rows)] for c in range(cols)]
    return trans


def vdot(vec1: Sequence[float], vec2: Sequence[float]) -> float:
    """Calcula el producto escalar (producto punto) entre dos vectores numéricos."""
    v1 = [float(x) for x in vec1]
    v2 = [float(x) for x in vec2]
    if len(v1) != len(v2):
        raise ValueError(f"Los vectores deben tener la misma longitud ({len(v1)} vs {len(v2)}).")
    return round(sum(x * y for x, y in zip(v1, v2)), 4)


def linest(y_vals: Sequence[float], x_vals: Sequence[float]) -> Dict[str, float]:
    """
    Calcula la regresión lineal por mínimos cuadrados ordinarios (MCO): y = slope * x + intercept.
    Retorna la pendiente, intersección y coeficiente de determinación (R²).
    """
    ys = [float(y) for y in y_vals]
    xs = [float(x) for x in x_vals]
    n = len(ys)
    if n != len(xs) or n < 2:
        raise ValueError("Se requieren al menos 2 pares de observaciones (X, Y).")

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_yy = sum((y - mean_y) ** 2 for y in ys)

    if ss_xx == 0.0:
        raise ZeroDivisionError("La varianza en X es 0; no se puede ajustar una recta.")

    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x

    # R-squared
    r2 = (ss_xy ** 2) / (ss_xx * ss_yy) if (ss_xx * ss_yy) > 0 else 0.0

    return {
        "slope": round(slope, 4),
        "intercept": round(intercept, 4),
        "r_squared": round(r2, 4),
    }

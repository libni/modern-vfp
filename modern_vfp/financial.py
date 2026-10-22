"""
Suite de Matemáticas Financieras y Actuariales (`modern_vfp/financial.py`) para FoxNext / Modern VFP.
Proporciona funciones financieras estándar compatibles con Visual FoxPro y hojas de cálculo:
- `PAYMENT(nRate, nPeriods, nPrincipal [, nFutureValue [, nType]])` -> Cuota periódica fija (PMT)
- `PV(nRate, nPeriods, nPayment [, nFutureValue [, nType]])` -> Valor Presente / Actual
- `FV(nRate, nPeriods, nPayment [, nPresentValue [, nType]])` -> Valor Futuro
- `NPV(nRate, aFlujosEfectivo)` -> Valor Presente Neto
- `IRR(aFlujosEfectivo)` -> Tasa Interna de Retorno (TIR)
"""

from __future__ import annotations
import math
from typing import Any, List, Sequence, Union


def payment(rate: float, nper: int, pv: float, fv: float = 0.0, type_: int = 0) -> float:
    """Calcula el pago o cuota de un préstamo basado en pagos y tasa de interés constantes."""
    r = float(rate)
    n = int(nper)
    p = float(pv)
    f = float(fv)
    t = int(type_)

    if n <= 0:
        return 0.0

    if r == 0.0:
        return round(-(p + f) / n, 2)

    factor = (1.0 + r) ** n
    pmt = -(p * factor + f) / ((1.0 + r * t) * (factor - 1.0) / r)
    return round(pmt, 2)


def pv(rate: float, nper: int, pmt: float, fv: float = 0.0, type_: int = 0) -> float:
    """Calcula el valor actual o presente de una inversión o anualidad."""
    r = float(rate)
    n = int(nper)
    c = float(pmt)
    f = float(fv)
    t = int(type_)

    if n <= 0:
        return 0.0

    if r == 0.0:
        return round(-f - c * n, 2)

    factor = (1.0 + r) ** n
    pv_val = (-f - c * (1.0 + r * t) * (factor - 1.0) / r) / factor
    return round(pv_val, 2)


def fv(rate: float, nper: int, pmt: float, pv: float = 0.0, type_: int = 0) -> float:
    """Calcula el valor futuro de una inversión basado en pagos periódicos."""
    r = float(rate)
    n = int(nper)
    c = float(pmt)
    p = float(pv)
    t = int(type_)

    if n <= 0:
        return 0.0

    if r == 0.0:
        return round(-p - c * n, 2)

    factor = (1.0 + r) ** n
    fv_val = -p * factor - c * (1.0 + r * t) * (factor - 1.0) / r
    return round(fv_val, 2)


def npv(rate: float, cash_flows: Sequence[float]) -> float:
    """Calcula el Valor Actual Neto (VAN / NPV) a partir de una tasa y una secuencia de flujos."""
    r = float(rate)
    total = 0.0
    for idx, cf in enumerate(cash_flows, start=1):
        total += float(cf) / ((1.0 + r) ** idx)
    return round(total, 2)


def irr(cash_flows: Sequence[float], max_iter: int = 100, tol: float = 1e-6) -> float:
    """
    Calcula la Tasa Interna de Retorno (TIR / IRR) para una serie periódica de flujos
    utilizando el método numérico de Newton-Raphson.
    """
    cfs = [float(cf) for cf in cash_flows]
    if len(cfs) < 2:
        return 0.0

    # Estimación inicial: 10%
    rate = 0.10
    for _ in range(max_iter):
        npv_val = 0.0
        d_npv = 0.0
        for t, cf in enumerate(cfs):
            denom = (1.0 + rate) ** t
            npv_val += cf / denom
            if t > 0:
                d_npv -= t * cf / ((1.0 + rate) ** (t + 1))

        if abs(npv_val) < tol:
            return round(rate, 4)
        if abs(d_npv) < 1e-12:
            break

        new_rate = rate - (npv_val / d_npv)
        if abs(new_rate - rate) < tol:
            return round(new_rate, 4)
        rate = new_rate

    return round(rate, 4)

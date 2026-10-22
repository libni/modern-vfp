"""
Motor de Enmascaramiento y Privacidad de Datos (`modern_vfp/masking.py`) para FoxNext.
Permite ofuscar datos sensibles (cumplimiento GDPR, HIPAA, PCI-DSS) en cursores en memoria:
- Correos electrónicos: `j***e@dominio.com`
- Tarjetas de crédito: `****-****-****-1234`
- Teléfonos: `***-***-5678`
- Documentos de identidad / SSN: `***-**-6789`
- Cadenas genéricas: ofuscación parcial conservando primeros y últimos caracteres
Comando:
  `MASK CURSOR <alias> FIELD <campo> TYPE (EMAIL|CARD|PHONE|SSN|CUSTOM)`
Función:
  `MASKDATA(cValor, [cTipo])`
"""

from __future__ import annotations
import re
from typing import Any, Optional

from .cursor import Cursor


def mask_email(email: str, mask_char: str = "*") -> str:
    s = str(email).strip()
    if "@" not in s:
        return mask_char * len(s)
    local, domain = s.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + mask_char
    else:
        masked_local = local[0] + (mask_char * (len(local) - 2)) + local[-1]
    return f"{masked_local}@{domain}"


def mask_card(card_number: str, mask_char: str = "*") -> str:
    s = str(card_number).strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) < 4:
        return mask_char * len(s)
    last4 = digits[-4:]
    # Preservar formato original con guiones si los tiene
    if "-" in s:
        parts = s.split("-")
        masked_parts = [mask_char * len(p) for p in parts[:-1]] + [parts[-1][-4:]]
        return "-".join(masked_parts)
    return (mask_char * (len(digits) - 4)) + last4


def mask_phone(phone: str, mask_char: str = "*") -> str:
    s = str(phone).strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) < 4:
        return mask_char * len(s)
    last4 = digits[-4:]
    return (mask_char * (len(s) - 4)) + last4


def mask_ssn(ssn: str, mask_char: str = "*") -> str:
    s = str(ssn).strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) < 4:
        return mask_char * len(s)
    last4 = digits[-4:]
    if "-" in s and len(s) == 11:
        return f"{mask_char*3}-{mask_char*2}-{last4}"
    return (mask_char * (len(digits) - 4)) + last4


def mask_custom(text: str, visible_start: int = 1, visible_end: int = 1, mask_char: str = "*") -> str:
    s = str(text).strip()
    if len(s) <= (visible_start + visible_end):
        return mask_char * len(s)
    start = s[:visible_start]
    end = s[-visible_end:] if visible_end > 0 else ""
    middle = mask_char * (len(s) - visible_start - visible_end)
    return start + middle + end


def mask_value(val: Any, mask_type: str = "EMAIL", mask_char: str = "*") -> str:
    """Aplica la regla de enmascaramiento especificada a un valor individual."""
    if val is None:
        return ""
    t = mask_type.upper().strip()
    s = str(val)
    if t == "EMAIL":
        return mask_email(s, mask_char)
    elif t in ("CARD", "CREDITCARD"):
        return mask_card(s, mask_char)
    elif t == "PHONE":
        return mask_phone(s, mask_char)
    elif t in ("SSN", "ID", "DNI"):
        return mask_ssn(s, mask_char)
    return mask_custom(s, 1, 1, mask_char)


def mask_cursor_field(
    cur: Cursor,
    field_name: str,
    mask_type: str = "EMAIL",
    mask_char: str = "*",
    set_deleted_on: bool = False,
) -> int:
    """
    Modifica in-place todos los registros visibles del cursor aplicando el enmascaramiento al campo dado.
    Devuelve la cantidad de registros transformados.
    """
    fn = field_name.lower().strip()
    if fn not in [f.name.lower() for f in cur.fields]:
        raise ValueError(f"El campo '{field_name}' no existe en el cursor '{cur.alias}'.")

    vis = cur.visible_recnos(set_deleted_on)
    for recno in vis:
        row = cur.records[recno - 1]
        orig_val = row.get(fn)
        if orig_val is not None:
            row[fn] = mask_value(orig_val, mask_type, mask_char)

    return len(vis)

"""
Validador de Esquemas JSON y Contratos de Datos (`modern_vfp/schema_validator.py`) para FoxNext.
Permite validar cursores en memoria contra especificaciones formales JSON Schema:
- Campos requeridos (`required`)
- Tipos de datos (`type`: string, number, integer, boolean)
- Restricciones de rango (`minimum`, `maximum`)
- Restricciones de longitud y formato (`minLength`, `maxLength`, `pattern`)
- Listas de valores permitidos (`enum`)
"""

from __future__ import annotations
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union

from .cursor import Cursor


class SchemaValidationError:
    def __init__(self, recno: int, field: str, rule: str, message: str, value: Any) -> None:
        self.recno = recno
        self.field = field
        self.rule = rule
        self.message = message
        self.value = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recno": self.recno,
            "field": self.field,
            "rule": self.rule,
            "message": self.message,
            "value": self.value,
        }

    def __str__(self) -> str:
        return f"[Reg #{self.recno}] Campo '{self.field}': {self.message} (Valor: {repr(self.value)})"


def _parse_schema(schema_input: Union[str, Dict[str, Any], Path]) -> Dict[str, Any]:
    if isinstance(schema_input, dict):
        return schema_input
    if isinstance(schema_input, str):
        trimmed = schema_input.strip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            return json.loads(trimmed)
        if len(schema_input) < 1024:
            p = Path(schema_input)
            if p.is_file():
                return json.loads(p.read_text(encoding="utf-8"))
        return json.loads(trimmed)
    if isinstance(schema_input, Path) and schema_input.is_file():
        return json.loads(schema_input.read_text(encoding="utf-8"))
    raise ValueError(f"Esquema JSON no válido: {schema_input}")


def validate_cursor(
    cur: Cursor,
    schema_spec: Union[str, Dict[str, Any], Path],
    set_deleted_on: bool = False,
) -> List[SchemaValidationError]:
    """
    Valida todos los registros activos del cursor contra la especificación JSON Schema.
    Devuelve la lista de violaciones encontradas.
    """
    schema = _parse_schema(schema_spec)
    errors: List[SchemaValidationError] = []

    required_fields = schema.get("required", [])
    properties: Dict[str, Any] = schema.get("properties", {})

    vis = cur.visible_recnos(set_deleted_on)

    for recno in vis:
        row = cur.records[recno - 1]

        # 1. Validar campos obligatorios
        for req in required_fields:
            val = row.get(req.lower())
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(
                    SchemaValidationError(
                        recno=recno,
                        field=req,
                        rule="required",
                        message=f"El campo requerido '{req}' está ausente o vacío.",
                        value=val,
                    )
                )

        # 2. Validar propiedades individuales
        for f_name, rules in properties.items():
            col = f_name.lower()
            val = row.get(col)
            if val is None:
                continue

            # Tipo
            expected_type = rules.get("type")
            if expected_type:
                if expected_type == "string" and not isinstance(val, str):
                    errors.append(SchemaValidationError(recno, f_name, "type", "Se esperaba tipo 'string'.", val))
                elif expected_type == "integer" and not (isinstance(val, int) and not isinstance(val, bool)):
                    errors.append(SchemaValidationError(recno, f_name, "type", "Se esperaba tipo 'integer'.", val))
                elif expected_type == "number" and not (isinstance(val, (int, float)) and not isinstance(val, bool)):
                    errors.append(SchemaValidationError(recno, f_name, "type", "Se esperaba tipo numérico.", val))
                elif expected_type == "boolean" and not isinstance(val, bool):
                    errors.append(SchemaValidationError(recno, f_name, "type", "Se esperaba tipo 'boolean'.", val))

            # Restricciones numéricas
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                if "minimum" in rules and val < rules["minimum"]:
                    errors.append(SchemaValidationError(recno, f_name, "minimum", f"Valor menor al mínimo {rules['minimum']}.", val))
                if "maximum" in rules and val > rules["maximum"]:
                    errors.append(SchemaValidationError(recno, f_name, "maximum", f"Valor mayor al máximo {rules['maximum']}.", val))

            # Restricciones de cadena
            if isinstance(val, str):
                s_val = val.strip()
                if "minLength" in rules and len(s_val) < rules["minLength"]:
                    errors.append(SchemaValidationError(recno, f_name, "minLength", f"Longitud menor a {rules['minLength']}.", val))
                if "maxLength" in rules and len(s_val) > rules["maxLength"]:
                    errors.append(SchemaValidationError(recno, f_name, "maxLength", f"Longitud mayor a {rules['maxLength']}.", val))
                if "pattern" in rules and not re.search(rules["pattern"], s_val):
                    errors.append(SchemaValidationError(recno, f_name, "pattern", f"No coincide con la expresión regular '{rules['pattern']}'.", val))

            # Enum
            if "enum" in rules and val not in rules["enum"]:
                errors.append(SchemaValidationError(recno, f_name, "enum", f"Valor no permitido. Opciones: {rules['enum']}.", val))

    return errors

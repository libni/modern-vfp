# FoxNext (`modern-vfp`) v0.2.0

> Entorno y lenguaje **Data-Centric RAD de 64 bits** inspirado en **Microsoft Visual FoxPro**, con motor de cursores en memoria, SQL relacional nativo (`SELECT ... INTO CURSOR`), compatibilidad binaria `.dbf` (UTF-8), orientación a objetos (`DEFINE CLASS`), Command Window interactivo (REPL) y formularios declarativos Git-friendly (`.foxform`).

---

## Características Implementadas

1. **Áreas de Trabajo (Work Areas 1..32767) y Cursores 64-bit (`modern_vfp/cursor.py`):**
   - `CREATE CURSOR` / `CREATE TABLE`, `SELECT <alias|area>`, `USE`, `CLOSE TABLES`.
   - Navegación completa: `GO TOP`, `GO BOTTOM`, `GOTO <n>`, `SKIP [n]`, `RECNO()`, `RECCOUNT()`, `BOF()`, `EOF()`.
   - Manipulación: `APPEND BLANK`, `INSERT INTO ... VALUES`, `REPLACE [ALL] ... WITH ... [FOR ...]`.
   - Borrado lógico y físico: `DELETE`, `RECALL`, `DELETED()`, `SET DELETED ON|OFF`, `PACK`, `ZAP`.
   - Índices y búsqueda: `INDEX ON <expr> TAG <tag>`, `SET ORDER TO <tag>`, `SEEK <expr>`, `LOCATE FOR <expr>`, `CONTINUE`, `FOUND()`.
   - Relaciones maestro-detalle: `SET RELATION TO <expr> INTO <alias>`.
   - Buffering transaccional optimista: `CURSORSETPROP("Buffering", 5)`, `TABLEUPDATE()`, `TABLEREVERT()`.
2. **SQL Relacional Nativo Embebido:**
   - Ejecución directa de `SELECT ... FROM ... INNER JOIN ... WHERE ... GROUP BY ... ORDER BY ... INTO CURSOR <alias>` integrando variables de memoria y cursores abiertos.
3. **Lenguaje xBase Estructurado y Orientado a Objetos (`modern_vfp/interpreter.py`):**
   - Estructuras de control: `IF...ELSEIF...ELSE...ENDIF`, `DO CASE...CASE...OTHERWISE...ENDCASE`, `DO WHILE...ENDDO`, `FOR...TO...STEP...ENDFOR`, `SCAN [FOR ...]...ENDSCAN`, `TRY...CATCH...FINALLY...ENDTRY`.
   - `PROCEDURE` / `FUNCTION` de usuario y sustitución de macros (`&lcVar`).
   - Clases y objetos: `DEFINE CLASS <Nombre> AS <Base> ... ENDDEFINE` y `CREATEOBJECT()`.
4. ** más de 50 Funciones Estándar de VFP (`modern_vfp/functions.py`):**
   - Strings: `ALLTRIM`, `LTRIM`, `RTRIM`, `UPPER`, `LOWER`, `PROPER`, `SUBSTR`, `LEFT`, `RIGHT`, `PADL`, `PADR`, `PADC`, `STRTRAN`, `CHRTRAN`, `STUFF`, `STR`, `VAL`, `TRANSFORM`.
   - Lógicas y Fechas: `IIF`, `ICASE`, `NVL`, `EVL`, `EMPTY`, `BETWEEN`, `INLIST`, `DATE`, `DATETIME`, `DTOC`, `DTOS`, `CTOD`, `GOMONTH`.
5. **Compatibilidad Binaria `.dbf` + Exportación CSV/JSON (`modern_vfp/dbf.py`):**
   - Lectura y escritura nativa de archivos `.dbf` (dBASE III+ / Visual FoxPro) con codificación UTF-8 (`COPY TO archivo.dbf TYPE DBF`, `USE archivo.dbf`).
6. **Formularios RAD Declarativos Git-Friendly (`modern_vfp/foxform.py`):**
   - Archivos `.foxform` en texto plano JSON con `DataEnvironment`, `ControlSource` bidireccional, eventos (`Load`, `Init`, `onClick`, `onValid`), vista TUI y exportación HTML5.

---

## Ejecución Rápida

### 1. Iniciar la Ventana de Comandos Interactiva (Command Window REPL)
```bash
python3 -m modern_vfp
```

### 2. Ejecutar un Programa `.prg`
```bash
python3 -m modern_vfp examples/demo_ventas.prg
```

### 3. Renderizar y Ejecutar un Formulario `.foxform`
```bash
python3 -m modern_vfp examples/clientes.foxform
```

### 4. Ejecutar la Suite de Pruebas Unitarias
```bash
python3 -m unittest discover -s tests -v
```

---

## Documentación Arquitectónica

- [**Plan Maestro y Roadmap (`PLAN.md`)**](./PLAN.md)
- [**Especificación Técnica del Lenguaje y Cursores (`docs/SPECIFICATION.md`)**](./docs/SPECIFICATION.md)

# FoxNext (`modern-vfp`) v0.4.0

> Entorno y lenguaje **Data-Centric RAD de 64 bits** inspirado en **Microsoft Visual FoxPro**, con motor de cursores en memoria, SQL relacional nativo (`SELECT / UPDATE / DELETE`), conectividad SQL Pass-Through (`SQLCONNECT / SQLEXEC`), transacciones multinivel (`BEGIN TRANSACTION / ROLLBACK`), intercambio `SCATTER / GATHER`, bloques `TEXT ... ENDTEXT`, conversión `CURSORTOJSON / JSONTOCURSOR`, compatibilidad binaria `.dbf` (UTF-8), orientación a objetos (`DEFINE CLASS`), formularios declarativos (`.foxform`), motor de reportes por bandas (`.foxreport`), migrador de legado VFP 9 (`vfp2modern`), empaquetador de proyectos (`BUILD APP` `.foxproj/.foxapp`) y entorno visual **FoxNext Studio**.

---

## Características Implementadas (v0.4.0)

1. **Áreas de Trabajo (Work Areas 1..32767) y Cursores 64-bit (`modern_vfp/cursor.py`):**
   - `CREATE CURSOR` / `CREATE TABLE`, `SELECT <alias|area>`, `USE`, `CLOSE TABLES`.
   - Navegación: `GO TOP`, `GO BOTTOM`, `GOTO <n>`, `SKIP [n]`, `RECNO()`, `RECCOUNT()`, `BOF()`, `EOF()`.
   - Manipulación: `APPEND BLANK`, `APPEND FROM <archivo.csv|.json|.dbf>`, `INSERT INTO ... VALUES`, `REPLACE [ALL] ... WITH ... [FOR ...]`.
   - Intercambio de objetos y agregaciones: `SCATTER NAME <loObj> [BLANK]`, `GATHER NAME <loObj>` y `CALCULATE SUM(), AVG(), COUNT(), MIN(), MAX() [FOR ...] TO ...`.
   - Borrado lógico y físico: `DELETE`, `RECALL`, `DELETED()`, `SET DELETED ON|OFF`, `PACK`, `ZAP`.
   - Índices, búsquedas y relaciones: `INDEX ON <expr> TAG <tag>`, `SET ORDER TO <tag>`, `SEEK <expr>`, `LOCATE FOR <expr>`, `CONTINUE`, `FOUND()`, `SET RELATION TO <expr> INTO <alias>`.
   - Buffering y Transacciones Multinivel: `CURSORSETPROP("Buffering", 5)`, `TABLEUPDATE()`, `TABLEREVERT()`, `BEGIN TRANSACTION`, `END TRANSACTION`, `ROLLBACK`, `TXNLEVEL()`.
2. **SQL Nativo Completo + SQL Pass-Through + Cloud/JSON:**
   - Consultas relacionales nativas: `SELECT ... FROM ... INNER JOIN ... WHERE ... GROUP BY ... ORDER BY ... INTO CURSOR <alias>`.
   - Modificación SQL directa sobre cursores: `UPDATE <alias> SET <campo> = <expr> WHERE <cond>` y `DELETE FROM <alias> WHERE <cond>`.
   - Conectividad SQL Pass-Through: `SQLCONNECT()`, `SQLSTRINGCONNECT()`, `SQLEXEC(nHandle, cSQL, cCursor)` (con parámetros `?variable`) y `SQLDISCONNECT()`.
   - Conversión directa Cursor $\leftrightarrow$ JSON y REST: `CURSORTOJSON([alias])`, `JSONTOCURSOR(lcJson, alias)`, `HTTPGET(url)`, `HTTPPOST(url, body)`.
3. **Lenguaje xBase Estructurado, `TEXT...ENDTEXT`, OOP y +55 Funciones (`modern_vfp/interpreter.py`, `modern_vfp/functions.py`):**
   - Control de flujo: `IF...ELSEIF...ELSE...ENDIF`, `DO CASE...ENDCASE`, `DO WHILE...ENDDO`, `FOR...ENDFOR`, `SCAN...ENDSCAN`, `TRY...CATCH...FINALLY...ENDTRY`.
   - Bloques `TEXT TO <lcVar> [ADDITIVE] [TEXTMERGE] [NOSHOW] ... ENDTEXT` con interpolación `<<expresion>>`.
   - Clases orientadas a objetos con `DEFINE CLASS ... AS ... ENDDEFINE`, `CREATEOBJECT()` y sustitución de macros `&lcVar`.
4. **Formularios RAD Declarativos Git-Friendly (`modern_vfp/foxform.py`):**
   - Comando `DO FORM <archivo.foxform> [TO FILE <salida.html>]`.
   - `DataEnvironment`, `ControlSource` bidireccional, eventos (`Load`, `Init`, `onClick`, `onValid`), vista TUI y exportación HTML5.
5. **Motor de Reportes por Bandas (`modern_vfp/foxreport.py`):**
   - Comando `REPORT FORM <archivo.foxreport> [FOR <cond>] [TO FILE <salida.txt | .html>]`.
   - Bandas `Title`, `PageHeader`, `GroupHeader` / `GroupFooter` y `Summary` con cálculos automáticos (`SUM`, `AVG`, `COUNT`, `MIN`, `MAX`).
6. **Migrador de Legado VFP 9 (`modern_vfp/migrator.py`) y Gestor de Proyectos (`modern_vfp/project.py`):**
   - Comando `MIGRATE SCX <archivo.scx> TO <salida.foxform>` y CLI `--migrate`.
   - Manifiesto de proyecto `.foxproj` y empaquetador `BUILD APP <salida.foxapp> FROM <proyecto.foxproj>` (y CLI `--build`).
7. **Entorno Visual Interactivo FoxNext Studio (`modern_vfp/studio.py`):**
   - Interfaz Web con explorador de Data Session (Work Areas), grilla `BROWSE` en vivo y Command Window interactiva.

---

## Ejecución Rápida

```bash
# 1. Iniciar la Ventana de Comandos Interactiva (Command Window REPL)
python3 -m modern_vfp

# 2. Iniciar el Entorno Visual FoxNext Studio (http://127.0.0.1:8765)
python3 -m modern_vfp --studio

# 3. Ejecutar el programa de demostración (.prg)
python3 -m modern_vfp examples/demo_ventas.prg

# 4. Empaquetar y ejecutar un proyecto completo (.foxproj -> .foxapp)
python3 -m modern_vfp --build examples/ventas.foxproj ventas.foxapp
python3 -m modern_vfp ventas.foxapp

# 5. Ejecutar las 18 suites de pruebas integrales
python3 -m unittest discover -s tests -v
```

---

## Documentación Arquitectónica

- [**Plan Maestro y Roadmap (`PLAN.md`)**](./PLAN.md)
- [**Especificación Técnica del Lenguaje y Cursores (`docs/SPECIFICATION.md`)**](./docs/SPECIFICATION.md)

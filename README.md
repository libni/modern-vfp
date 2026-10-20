# FoxNext (`modern-vfp`) v0.7.0

> Entorno y lenguaje **Data-Centric RAD de 64 bits** inspirado en **Microsoft Visual FoxPro**, con motor de cursores en memoria, evolución dinámica de esquemas (`ALTER TABLE`), vistas SQL parametrizadas (`CREATE SQL VIEW` / `REQUERY()`), SQL relacional nativo (`SELECT / UPDATE / DELETE`), conectividad SQL Pass-Through (`SQLCONNECT / SQLEXEC`), transacciones multinivel (`BEGIN TRANSACTION / ROLLBACK`), intercambio `SCATTER / GATHER`, arreglos y colecciones (`DIMENSION`, `COPY TO ARRAY`, `ADIR()`, `Collection`), bloques `TEXT ... ENDTEXT`, conversión `CURSORTOJSON / JSONTOCURSOR`, compatibilidad binaria `.dbf` (UTF-8), orientación a objetos con herencia multinivel (`DEFINE CLASS`, `DODEFAULT()`, `BINDEVENT()`, `RAISEEVENT()`), formularios declarativos (`.foxform`), menús empresariales (`.foxmenu` / `DEFINE MENU`), motor de reportes por bandas (`.foxreport`), migrador de legado VFP 9 (`vfp2modern`), analizador LSP (`--check`), depurador y trazador (`--debug`), transpilador `.prg` a Python (`.py`) (`--transpile`), generador de documentación (`--doc`), servidor de microservicios REST (`--api`), empaquetador de proyectos (`BUILD APP`) y entorno visual **FoxNext Studio**.

---

## Características Implementadas (v0.7.0)

1. **Áreas de Trabajo (Work Areas 1..32767) y Cursores 64-bit (`modern_vfp/cursor.py`):**
   - `CREATE CURSOR` / `CREATE TABLE`, `ALTER TABLE <alias> ADD / DROP COLUMN`, `SELECT <alias|area>`, `USE`, `CLOSE TABLES`.
   - Navegación: `GO TOP`, `GO BOTTOM`, `GOTO <n>`, `SKIP [n]`, `RECNO()`, `RECCOUNT()`, `BOF()`, `EOF()`.
   - Manipulación: `APPEND BLANK`, `APPEND FROM <archivo.csv|.json|.dbf>`, `APPEND FROM ARRAY`, `COPY TO ARRAY`, `INSERT INTO ... VALUES`, `REPLACE [ALL] ... WITH ... [FOR ...]`.
   - Intercambio de objetos y agregaciones: `SCATTER NAME <loObj> [BLANK]`, `GATHER NAME <loObj>` y `CALCULATE SUM(), AVG(), COUNT(), MIN(), MAX() [FOR ...] TO ...`.
   - Borrado lógico y físico: `DELETE`, `RECALL`, `DELETED()`, `SET DELETED ON|OFF`, `PACK`, `ZAP`.
   - Índices, búsquedas y relaciones: `INDEX ON <expr> TAG <tag>`, `SET ORDER TO <tag>`, `SEEK <expr>`, `LOCATE FOR <expr>`, `CONTINUE`, `FOUND()`, `SET RELATION TO <expr> INTO <alias>`.
   - Buffering y Transacciones Multinivel: `CURSORSETPROP("Buffering", 5)`, `TABLEUPDATE()`, `TABLEREVERT()`, `BEGIN TRANSACTION`, `END TRANSACTION`, `ROLLBACK`, `TXNLEVEL()`.
2. **SQL Nativo Completo, Vistas Reactivas (`CREATE SQL VIEW` / `REQUERY()`), SQL Pass-Through y Cloud/JSON:**
   - Consultas relacionales nativas: `SELECT ... FROM ... INNER JOIN ... WHERE ... GROUP BY ... ORDER BY ... INTO CURSOR <alias>`.
   - Vistas SQL parametrizadas: `CREATE SQL VIEW <vista> AS SELECT ... WHERE campo = ?vp_param` y refresco reactivo en vivo con `REQUERY([alias])`.
   - Modificación SQL directa sobre cursores: `UPDATE <alias> SET <campo> = <expr> WHERE <cond>` y `DELETE FROM <alias> WHERE <cond>`.
   - Conectividad SQL Pass-Through: `SQLCONNECT()`, `SQLSTRINGCONNECT()`, `SQLEXEC(nHandle, cSQL, cCursor)` (con parámetros `?variable`) y `SQLDISCONNECT()`.
   - Conversión directa Cursor $\leftrightarrow$ JSON y REST: `CURSORTOJSON([alias])`, `JSONTOCURSOR(lcJson, alias)`, `HTTPGET(url)`, `HTTPPOST(url, body)`.
3. **Lenguaje xBase, OOP Avanzado con Herencia y Eventos, Arreglos, Sistema y +80 Funciones (`modern_vfp/interpreter.py`, `modern_vfp/functions.py`):**
   - Clases orientadas a objetos con herencia multinivel (`DEFINE CLASS Sub AS Super`), invocación a superclase con `DODEFAULT(...)`, reflexión con `ADDPROPERTY()` / `PEMSTATUS()`, y delegación reactiva de eventos con `BINDEVENT()`, `RAISEEVENT()` y `UNBINDEVENTS()`.
   - Arreglos 1-based (`DIMENSION` / `DECLARE`, `ALEN()`, `ASCAN()`, `ASORT()`, `ADIR()`) y clase nativa `CREATEOBJECT("Collection")`.
   - Funciones de sistema, rutas y archivos: `FILETOSTR()`, `STRTOFILE()`, `ADIR()`, `SYS(0|5|16|2003|2015|2023)`, `GETENV()`, `JUSTFNAME()`, `JUSTEXT()`, `JUSTPATH()`, `JUSTSTEM()`, `ADDBS()`, `FORCEEXT()`.
   - Funciones de palabras y extracción: `STREXTRACT()`, `GETWORDCOUNT()`, `GETWORDNUM()`.
   - Bloques `TEXT TO <lcVar> [ADDITIVE] [TEXTMERGE] [NOSHOW] ... ENDTEXT` con interpolación `<<expresion>>`, `ASSERT <cond> [MESSAGE <msg>]` y sustitución de macros `&lcVar`.
4. **Formularios RAD (`.foxform`), Menús (`.foxmenu` / `DEFINE MENU`) y Motor de Reportes por Bandas (`.foxreport`):**
   - `DO FORM <archivo.foxform> [TO FILE <salida.html>]`, `REPORT FORM <archivo.foxreport> [FOR <cond>] [TO FILE <salida.txt | .html>]` y menús interactivos con `DEFINE MENU`, `DEFINE PAD`, `DEFINE POPUP`, `DEFINE BAR`, `ON SELECTION BAR` y `ACTIVATE POPUP`.
5. **Tooling Moderno: DocGen (`modern_vfp/docgen.py`), Depurador (`modern_vfp/debugger.py`), Transpilador Python (`modern_vfp/transpiler.py`), LSP (`modern_vfp/lsp.py`), Microservicios REST (`modern_vfp/apiserver.py`), Migrador VFP 9 y Empaquetador:**
   - Generador de documentación técnica Markdown (`--doc <archivo.prg> [salida.md]`).
   - Depurador paso a paso con Breakpoints, Watchpoints y `SET STEP ON` (`--debug <archivo.prg>`).
   - Transpilador de programas `.prg` a módulos Python 3 nativos (`.py`) (`--transpile <archivo.prg> [salida.py]`).
   - Analizador estático y autocompletado inteligente (`--check <archivo.prg>`).
   - Servidor de microservicios REST JSON (`--api <archivo.prg> [puerto]`) que expone cursores (`/api/cursors/<alias>`) y procedimientos (`/api/rpc/<func>`).
   - Migrador `MIGRATE SCX <archivo.scx> TO <salida.foxform>` y empaquetador `BUILD APP <salida.foxapp> FROM <proyecto.foxproj>`.

---

## Ejecución Rápida

```bash
# 1. Iniciar la Ventana de Comandos Interactiva (Command Window REPL)
python3 -m modern_vfp

# 2. Iniciar el Entorno Visual FoxNext Studio (http://127.0.0.1:8765)
python3 -m modern_vfp --studio

# 3. Analizar estáticamente, depurar o documentar un programa .prg
python3 -m modern_vfp --check examples/demo_ventas.prg
python3 -m modern_vfp --debug examples/demo_ventas.prg
python3 -m modern_vfp --doc examples/demo_ventas.prg

# 4. Transpilar un programa .prg a Python 3 nativo (.py)
python3 -m modern_vfp --transpile examples/demo_ventas.prg

# 5. Publicar un programa .prg y sus cursores como Microservicio REST JSON
python3 -m modern_vfp --api examples/demo_ventas.prg 8766

# 6. Ejecutar las 30 suites de pruebas integrales
python3 -m unittest discover -s tests -v
```

---

## Documentación Arquitectónica

- [**Plan Maestro y Roadmap (`PLAN.md`)**](./PLAN.md)
- [**Especificación Técnica del Lenguaje y Cursores (`docs/SPECIFICATION.md`)**](./docs/SPECIFICATION.md)

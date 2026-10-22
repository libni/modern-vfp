# FoxNext (`modern-vfp`) v1.1.0

> Entorno y lenguaje **Data-Centric RAD de 64 bits** inspirado en **Microsoft Visual FoxPro**, con motor de cursores en memoria, tecnología de optimización de búsquedas indexadas **Rushmore** (`SYS(3054)`), compilador de bytecode binario pre-tokenizado (`.fxp` / `COMPILE`), generación de ejecutables autónomos (`BUILD EXE`), contenedores de bases de datos relacionales (`.dbc` / `CREATE DATABASE` / `VALIDATE DATABASE`), exportador e importador columnar Parquet (`COPY TO ... TYPE PARQUET`), hojas de cálculo nativas Microsoft Excel OpenXML (`COPY TO ... TYPE XLSX` / `APPEND FROM`), concurrencia y bloqueos multiusuario (`RLOCK` / `FLOCK` / `UNLOCK` / `SET MULTILOCKS`), bus reactivo de eventos (`PUBLISH EVENT` / `SUBSCRIBE EVENT`), algoritmos de coincidencia fonética (`SOUNDEX` / `DIFFERENCE`), evolución dinámica de esquemas (`ALTER TABLE`), adaptador de datos OOP (`CursorAdapter`), vistas SQL parametrizadas (`CREATE SQL VIEW` / `REQUERY()`), SQL relacional nativo (`SELECT / UPDATE / DELETE`), conectividad SQL Pass-Through (`SQLCONNECT / SQLEXEC`), transacciones multinivel (`BEGIN TRANSACTION / ROLLBACK`), intercambio `SCATTER / GATHER`, serialización XML y JSON (`CURSORTOXML`, `XMLTOCURSOR`, `CURSORTOJSON`, `JSONTOCURSOR`), manejador global de errores (`ON ERROR`, `ERROR`, `AERROR()`), arreglos y colecciones (`DIMENSION`, `COPY TO ARRAY`, `ADIR()`, `Collection`), bloques `TEXT ... ENDTEXT`, compatibilidad binaria `.dbf` (UTF-8), orientación a objetos con herencia multinivel (`DEFINE CLASS`, `DODEFAULT()`, `BINDEVENT()`, `RAISEEVENT()`), formularios declarativos (`.foxform`), menús empresariales (`.foxmenu` / `DEFINE MENU`), motor de reportes por bandas (`.foxreport`), migrador de legado VFP 9 (`vfp2modern`), analizador LSP (`--check`), perfilador de rendimiento y cobertura (`--profile`), depurador y trazador (`--debug`), transpilador `.prg` a Python (`.py`) (`--transpile`), generador de documentación (`--doc`), servidor de microservicios REST (`--api`), empaquetador de proyectos (`BUILD APP`), generador de binarios autónomos (`BUILD EXE`), suite ERP empresarial y entorno visual **FoxNext Studio**.

---

## Características Implementadas (v1.1.0)

1. **Concurrencia Multiusuario, Bloqueos Granulares y Bus Reactivo (`modern_vfp/locks.py`, `modern_vfp/eventbus.py`):**
   - Sistema de Bloqueos Concurrente (`LockManager`): `RLOCK([nRecno, cAlias])` para bloqueo de registros individuales o múltiples, `FLOCK([cAlias])` para bloqueo completo de tabla, y `UNLOCK [RECORD n] [IN alias] [ALL]` para liberación granular o total.
   - Banderas de control de concurrencia: `SET EXCLUSIVE ON|OFF` y `SET MULTILOCKS ON|OFF`.
   - Funciones de diagnóstico de bloqueo: `ISLOCKED([nRecno, cAlias])` e `ISREADONLY([cAlias])`.
   - Bus de Eventos Reactivo (`FoxEventBus`): desacoplamiento de arquitectura mediante `PUBLISH EVENT <topic> [DATA <expr>]` y suscripción reactiva directa a procedimientos con `SUBSCRIBE EVENT <topic> WITH <procedimiento>`.
2. **Interoperabilidad Microsoft Excel Nativa y Búsqueda Fonética (`modern_vfp/excel.py`):**
   - Soporte nativo de hojas de cálculo Microsoft Excel OpenXML (`.xlsx`) sin dependencias de terceros (Pure Python stdlib via zipfile y XML): `COPY TO <archivo.xlsx> TYPE XLSX` y `APPEND FROM <archivo.xlsx> TYPE XLSX` con inferencia automática de tipos (lógicos, enteros, decimales, texto).
   - Algoritmos fonéticos xBase estándar: `SOUNDEX(cExp)` (generación de huella fonética de 4 caracteres) y `DIFFERENCE(cExp1, cExp2)` (grado de coincidencia fonética de 0 a 4).
3. **Optimización Rushmore, Cursores 64-bit y Bases de Datos `.dbc` (`modern_vfp/rushmore.py`, `modern_vfp/dbc.py`, `modern_vfp/cursor.py`):**
   - Tecnología de optimización Rushmore (`RushmoreEngine`): evaluación ultraveloz de filtros `FOR <condicion>` mediante conjuntos e intersecciones de índices (`INDEX ON ... TAG ...`), soporte para niveles `Full`, `Partial` y `None`, y telemetría `SYS(3054)`.
   - Contenedor de Bases de Datos (`.dbc`): comandos `CREATE DATABASE <nombre>`, `OPEN DATABASE <nombre>`, `CLOSE DATABASES`, `ADD TABLE <tabla> TO DATABASE` y `VALIDATE DATABASE` para relaciones persistentes y reglas de integridad.
   - `CREATE CURSOR` / `CREATE TABLE`, `ALTER TABLE <alias> ADD / DROP COLUMN`, `SELECT <alias|area>`, `USE`, `CLOSE TABLES`.
   - Adaptador de datos relacional OOP nativo: `CREATEOBJECT("CursorAdapter")` (`VFPCursorAdapter`) con propiedades `Alias`, `SelectCmd`, `CursorSchema`, `DataSourceType`, `KeyFieldList`, `Tables` y métodos `.CursorFill([lUseSchema])`, `.CursorRefresh()` y `.CursorDetach()`.
   - Navegación e Índices: `GO TOP [IN alias]`, `GO BOTTOM [IN alias]`, `GOTO <n> [IN alias]`, `SKIP [n]`, `RECNO()`, `RECCOUNT()`, `INDEX ON <expr> TAG <tag>`, `SET ORDER TO <tag>`, `SEEK <expr>`, `LOCATE FOR <expr>`, `CONTINUE`, `FOUND()`, `SET RELATION TO <expr> INTO <alias>`.
   - Buffering y Transacciones Multinivel: `CURSORSETPROP("Buffering", 5)`, `TABLEUPDATE()`, `TABLEREVERT()`, `BEGIN TRANSACTION`, `END TRANSACTION`, `ROLLBACK`, `TXNLEVEL()`.
4. **Big Data Parquet, SQL Nativo Completo, Vistas Reactivas, XML y Cloud/JSON:**
   - Interoperabilidad columnar Parquet / Arrow (`modern_vfp/parquet.py`): `COPY TO <archivo.parquet> TYPE PARQUET` y `APPEND FROM <archivo.parquet> TYPE PARQUET` con esquema y tipos nativos.
   - Consultas relacionales nativas: `SELECT ... FROM ... INNER JOIN ... WHERE ... GROUP BY ... ORDER BY ... INTO CURSOR <alias>`.
   - Vistas SQL parametrizadas: `CREATE SQL VIEW <vista> AS SELECT ... WHERE campo = ?vp_param` y refresco reactivo en vivo con `REQUERY([alias])`.
   - Serialización e intercambio bidireccional XML: `CURSORTOXML(cAlias [, cVarOrFile])` y `XMLTOCURSOR(eXml, cAlias)`.
   - Modificación SQL directa sobre cursores: `UPDATE <alias> SET <campo> = <expr> WHERE <cond>` y `DELETE FROM <alias> WHERE <cond>`.
   - Conectividad SQL Pass-Through: `SQLCONNECT()`, `SQLSTRINGCONNECT()`, `SQLEXEC(nHandle, cSQL, cCursor)` (con parámetros `?variable`) y `SQLDISCONNECT()`.
   - Conversión directa Cursor $\leftrightarrow$ JSON y REST: `CURSORTOJSON([alias])`, `JSONTOCURSOR(lcJson, alias)`, `HTTPGET(url)`, `HTTPPOST(url, body)`.
5. **Compilador Bytecode `.fxp`, Ejecutables Autónomos (`BUILD EXE`), Lenguaje xBase y +90 Funciones:**
   - Compilador binario pre-tokenizado (`.fxp`): `COMPILE <archivo.prg> [TO <archivo.fxp>]` y ejecución de binarios pre-compilados con `DO <archivo.fxp>`.
   - Generación de ejecutables autónomos de 64 bits: `BUILD EXE <salida> FROM <proyecto.foxproj | programa.prg>` y CLI `--build-exe`.
   - Manejador global de errores: `ON ERROR [comando]`, disparo de errores con `ERROR <expr>`, lectura de código y mensaje con `ERROR()` / `MESSAGE()` y volcado diagnóstico a matriz con `AERROR(laInfoError)`.
   - Clases orientadas a objetos con herencia multinivel (`DEFINE CLASS Sub AS Super`), invocación a superclase con `DODEFAULT(...)`, reflexión con `ADDPROPERTY()` / `PEMSTATUS()`, y delegación reactiva de eventos con `BINDEVENT()`, `RAISEEVENT()` y `UNBINDEVENTS()`.
   - Arreglos 1-based (`DIMENSION` / `DECLARE`, `ALEN()`, `ASCAN()`, `ASORT()`, `ADIR()`) y clase nativa `CREATEOBJECT("Collection")`.
   - Funciones de sistema, rutas y archivos: `FILETOSTR()`, `STRTOFILE()`, `ADIR()`, `SYS(0|5|16|2003|2015|2023|3054)`, `GETENV()`, `JUSTFNAME()`, `JUSTEXT()`, `JUSTPATH()`, `JUSTSTEM()`, `ADDBS()`, `FORCEEXT()`.
   - Bloques `TEXT TO <lcVar> [ADDITIVE] [TEXTMERGE] [NOSHOW] ... ENDTEXT` con interpolación `<<expresion>>`, `ASSERT <cond> [MESSAGE <msg>]` y sustitución de macros `&lcVar`.
6. **Formularios RAD (`.foxform`), Menús (`.foxmenu` / `DEFINE MENU`) y Motor de Reportes por Bandas (`.foxreport`):**
   - `DO FORM <archivo.foxform> [TO FILE <salida.html>]`, `REPORT FORM <archivo.foxreport> [FOR <cond>] [TO FILE <salida.txt | .html>]` y menús interactivos con `DEFINE MENU`, `DEFINE PAD`, `DEFINE POPUP`, `DEFINE BAR`, `ON SELECTION BAR` y `ACTIVATE POPUP`.
7. **Tooling Moderno: Empaquetador EXE (`--build-exe`), Compilador (`--compile`), Profiler (`--profile`), DocGen (`--doc`), Depurador (`--debug`), Transpilador Python (`--transpile`), LSP (`--check`), Microservicios REST (`--api`), Migrador VFP 9 y Empaquetador:**
   - Generador de binarios autónomos (`--build-exe <in.prg|.foxproj> [out_exe]`).
   - Compilador binario xBase (`--compile <archivo.prg> [salida.fxp]`).
   - Perfilador de rendimiento por línea, hotspots y cobertura (`--profile <archivo.prg>`).
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

# 3. Compilar a binario bytecode .fxp o generar ejecutable autónomo
python3 -m modern_vfp --compile examples/demo_ventas.prg
python3 -m modern_vfp --build-exe examples/erp_demo/empresa.foxproj erp_app

# 4. Analizar estáticamente, depurar, perfilar o documentar un programa .prg
python3 -m modern_vfp --check examples/demo_ventas.prg
python3 -m modern_vfp --debug examples/demo_ventas.prg
python3 -m modern_vfp --profile examples/demo_ventas.prg
python3 -m modern_vfp --doc examples/demo_ventas.prg

# 5. Transpilar un programa .prg a Python 3 nativo (.py)
python3 -m modern_vfp --transpile examples/demo_ventas.prg

# 6. Publicar un programa .prg y sus cursores como Microservicio REST JSON
python3 -m modern_vfp --api examples/demo_ventas.prg 8766

# 7. Ejecutar las 44 suites de pruebas integrales
python3 -m unittest discover -s tests -v
```

---

## Documentación Arquitectónica

- [**Plan Maestro y Roadmap (`PLAN.md`)**](./PLAN.md)
- [**Especificación Técnica del Lenguaje y Cursores (`docs/SPECIFICATION.md`)**](./docs/SPECIFICATION.md)

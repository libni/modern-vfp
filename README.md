# FoxNext (`modern-vfp`) v1.5.0

> Entorno y lenguaje **Data-Centric RAD de 64 bits** inspirado en **Microsoft Visual FoxPro**, con motor de cursores en memoria, tecnología de optimización de búsquedas indexadas **Rushmore** (`SYS(3054)`), compilador de bytecode binario pre-tokenizado (`.fxp` / `COMPILE`), generación de ejecutables autónomos (`BUILD EXE`), contenedores de bases de datos relacionales (`.dbc` / `CREATE DATABASE` / `VALIDATE DATABASE`), exportador e importador columnar Parquet (`COPY TO ... TYPE PARQUET`), hojas de cálculo nativas Microsoft Excel OpenXML (`COPY TO ... TYPE XLSX` / `APPEND FROM`), cálculos geoespaciales y geocercas (`GEODISTANCE` / `GEOINPOLYGON` / `FILTER GEORADIUS`), planificador de tareas y cron en memoria (`SCHEDULE TASK` / `RUN PENDING TASKS`), recorrido jerárquico y árboles BOM (`EXPLODE TREE` / `TREEPATH`), álgebra matricial y regresión lineal (`MMULT` / `LINEST`), caché en memoria con TTL y LRU (`CACHE_SET` / `CACHE_GET`), motor de plantillas y generador de documentos (`RENDER TEMPLATE`), limitador de tasa y throttling para APIs (`THROTTLE` / `RATELIMIT_CHECK`), reconciliación y diff de datos (`DIFF CURSOR`), captura de cambios y auditoría (`ENABLE AUDIT` / `GETAUDITLOG`), matemáticas financieras y actuariales (`PAYMENT`, `PV`, `FV`, `NPV`, `IRR`), enmascaramiento y privacidad de datos (`MASK CURSOR` / `MASKDATA`), perfilado estadístico de cursores (`ANALYZE CURSOR`), tabulación cruzada dinámica xBase (`CROSSTAB` / `_GENXTAB`), suite criptográfica y seguridad (`SYS(2007)`, `HASH`, `HMAC`, `ENCRYPT`, `DECRYPT`), motor de búsqueda textual Full-Text (`CREATE FULLTEXT INDEX`, `FULLTEXT SEARCH`, `FTSMATCH`), validación formal de contratos y esquemas JSON (`VALIDATE CURSOR`, `ISVALIDCURSOR`), concurrencia y bloqueos multiusuario (`RLOCK` / `FLOCK` / `UNLOCK` / `SET MULTILOCKS`), bus reactivo de eventos (`PUBLISH EVENT` / `SUBSCRIBE EVENT`), algoritmos de coincidencia fonética (`SOUNDEX` / `DIFFERENCE`), evolución dinámica de esquemas (`ALTER TABLE`), adaptador de datos OOP (`CursorAdapter`), vistas SQL parametrizadas (`CREATE SQL VIEW` / `REQUERY()`), SQL relacional nativo (`SELECT / UPDATE / DELETE`), conectividad SQL Pass-Through (`SQLCONNECT / SQLEXEC`), transacciones multinivel (`BEGIN TRANSACTION / ROLLBACK`), intercambio `SCATTER / GATHER`, serialización XML y JSON (`CURSORTOXML`, `XMLTOCURSOR`, `CURSORTOJSON`, `JSONTOCURSOR`), manejador global de errores (`ON ERROR`, `ERROR`, `AERROR()`), arreglos y colecciones (`DIMENSION`, `COPY TO ARRAY`, `ADIR()`, `Collection`), bloques `TEXT ... ENDTEXT`, compatibilidad binaria `.dbf` (UTF-8), orientación a objetos con herencia multinivel (`DEFINE CLASS`, `DODEFAULT()`, `BINDEVENT()`, `RAISEEVENT()`), formularios declarativos (`.foxform`), menús empresariales (`.foxmenu` / `DEFINE MENU`), motor de reportes por bandas (`.foxreport`), migrador de legado VFP 9 (`vfp2modern`), analizador LSP (`--check`), perfilador de rendimiento y cobertura (`--profile`), depurador y trazador (`--debug`), transpilador `.prg` a Python (`.py`) (`--transpile`), generador de documentación (`--doc`), servidor de microservicios REST (`--api`), empaquetador de proyectos (`BUILD APP`), generador de binarios autónomos (`BUILD EXE`), suite ERP empresarial y entorno visual **FoxNext Studio**.

---

## Características Implementadas (v1.5.0)

1. **Motor Geoespacial y Geocercas (`modern_vfp/geo.py`):**
   - Distancia geodésica ortodrómica de alta precisión mediante la fórmula de Haversine: `GEODISTANCE(lat1, lon1, lat2, lon2 [, "KM"|"MILES"])`.
   - Evaluación de geocercas poligonales cerradas (Ray-Casting): `GEOINPOLYGON(lat, lon, aPuntosPoligono)`.
   - Verificación de cajas delimitadoras: `GEOINBOUNDS(lat, lon, minLat, minLon, maxLat, maxLon)`.
   - Filtro de radio territorial sobre cursores: `FILTER GEORADIUS ON <alias> LAT <col_lat> LON <col_lon> CENTER <lat>, <lon> RADIUS <dist> [KM|MILES] [INTO CURSOR <res>]`.
2. **Planificador de Tareas y Cron en Memoria (`modern_vfp/cron.py`):**
   - Programación declarativa de rutinas y mantenimiento recurrente: `SCHEDULE TASK <nombre> EVERY <n> (SECONDS|MINUTES|HOURS) DO <comando>`.
   - Control del ciclo de vida: `CANCEL TASK <nombre>` y ejecución forzada con `RUN PENDING TASKS`.
   - Diagnóstico y estado de ejecución en cursores: `TASKSTATUS([cNombreTarea [, cCursorDestino]])`.
3. **Recorrido Jerárquico de Estructuras y Árboles (BOM) (`modern_vfp/graph.py`):**
   - Explotación de grafos y árboles de recursión ilimitada (planes contables, organigramas, listas de materiales de producción):
     `EXPLODE TREE <alias> PARENT <col_padre> CHILD <col_hijo> [ROOT <raiz>] [INTO CURSOR <res>]`.
   - Columnas analíticas generadas: profundidad (`depth`), ruta jerárquica (`tree_path`) y estado terminal (`is_leaf`).
   - Funciones auxiliares: `TREEPATH(cAlias, cColPadre, cColHijo, eNodo)` y `TREECHILDREN(cAlias, cColPadre, cColHijo, eNodo [, lRecursivo])`.
4. **Álgebra Matricial y Modelado Predictivo (`modern_vfp/matrix.py`):**
   - Operaciones de álgebra lineal para análisis cuantitativo: multiplicación de matrices `MMULT()`, transposición `MTRANSPOSE()` y producto escalar `VDOT()`.
   - Regresión lineal simple por mínimos cuadrados ordinarios: `LINEST(aValoresY, aValoresX)` retornando pendiente, ordenada al origen y coeficiente de determinación ($R^2$).
5. **Caché en Memoria con TTL y Evicción LRU (`modern_vfp/cache.py`):**
   - Almacenamiento clave-valor de alto rendimiento para resultados de consultas, configuraciones y sesiones.
   - Expiración temporal granular por clave y desalojo inteligente LRU cuando se alcanza la capacidad máxima.
   - Funciones nativas xBase: `CACHE_SET(cClave, eValor [, nTTL])`, `CACHE_GET(cClave [, eDefecto])`, `CACHE_HAS(cClave)`, `CACHE_DELETE(cClave)`, `CACHE_CLEAR()` y `CACHE_STATS()`.
6. **Motor de Plantillas y Generador de Documentos (`modern_vfp/templates.py`):**
   - Renderizador declarativo para correos, facturas HTML, contratos y reportes estructurados.
   - Sintaxis moderna con interpolación `{{ variable }}`, filtros (`{{ precio | currency }}`, `{{ nombre | upper }}`), condicionales `{% if cond %} ... {% endif %}` y bucles sobre cursores o listas `{% for row in cursor_alias %} ... {% endfor %}`.
   - Comando directo: `RENDER TEMPLATE <archivo|string> [WITH <alias|dict>] [TO FILE <salida>]` y función `RENDERTEMPLATE()`.
7. **Limitación de Tasa y Regulación de Tráfico (`modern_vfp/ratelimit.py`):**
   - Motor de regulación mediante ventana deslizante para microservicios REST (`--api`) y procesos batch.
   - Comando de protección: `THROTTLE <cliente> LIMIT <n> PER <segundos> [ERROR <mensaje>]`.
   - Funciones programáticas: `RATELIMIT_CHECK(cCliente, nLimite, nVentana)`, `RATELIMIT_REMAINING()` y `RATELIMIT_RESET()`.
8. **Comparación y Reconciliación de Datos (Cursor Diff) (`modern_vfp/diff.py`):**
   - Análisis de diferencias entre dos versiones de un cursor o tabla basado en una clave primaria común.
   - Comando nativo: `DIFF CURSOR <alias1> WITH <alias2> KEY <campo_clave> [INTO CURSOR <diff_alias>]`.
   - Clasificación por registro en estados formales: `ADDED` (incorporado), `DELETED` (eliminado), `MODIFIED` (alterado, con lista de campos divergentes) e `IDENTICAL`.
5. **Captura de Cambios y Pistas de Auditoría CDC (`modern_vfp/cdc.py`):**
   - Rastreo automático y transparente de mutaciones (`INSERT`, `UPDATE`, `DELETE`, `RECALL`) en cursores activos mediante `ChangeDataCaptureManager`.
   - Comandos de activación y destino: `ENABLE AUDIT ON <alias> [TO FILE <archivo.jsonl>]` y `DISABLE AUDIT ON <alias>`.
   - Generación de cursores de auditoría y telemetría histórica: `GETAUDITLOG([cAlias [, cCursorDestino]])` registrando marcas de tiempo, operación, números de registro, campos alterados y valores anteriores/posteriores.
6. **Suite de Matemáticas Financieras y Actuariales (`modern_vfp/financial.py`):**
   - Cálculo de cuotas y préstamos constantes: `PAYMENT(nRate, nPeriods, nPrincipal [, nFutureValue [, nType]])` (función PMT).
   - Valor Actual y Valor Futuro: `PV(nRate, nPeriods, nPayment [, nFV [, nType]])` y `FV(nRate, nPeriods, nPayment [, nPV [, nType]])`.
   - Evaluación de proyectos de inversión: `NPV(nRate, aFlujosEfectivo)` (Valor Presente Neto) y `IRR(aFlujosEfectivo)` (Tasa Interna de Retorno mediante Newton-Raphson).
7. **Enmascaramiento y Privacidad de Datos (`modern_vfp/masking.py`):**
   - Protección y ofuscación de datos sensibles para cumplimiento normativo (GDPR, HIPAA, PCI-DSS):
     - Correos: `MASKDATA("juan.perez@empresa.com", "EMAIL")` -> `j*********z@empresa.com`.
     - Tarjetas de crédito: `MASKDATA("4532-1234-5678-9012", "CARD")` -> `****-****-****-9012`.
     - Teléfonos y documentos: formatos `PHONE`, `SSN`, `DNI`, `ID` y `CUSTOM`.
   - Transformación directa sobre cursores: `MASK CURSOR <alias> FIELD <campo> TYPE (EMAIL|CARD|PHONE|SSN|CUSTOM)`.
8. **Perfilado y Diagnóstico Estadístico de Datos (`modern_vfp/analytics.py`):**
   - Análisis descriptivo integral de cursores en memoria: `ANALYZE CURSOR <alias> [INTO CURSOR <stats_alias>]`.
   - Genera métricas por columna: cantidad de registros no nulos, nulos, cardinalidad única (distincts), valores mínimos, máximos, promedios aritméticos y desviación estándar muestral.
9. **Criptografía, Hashing y Seguridad xBase (`modern_vfp/crypto.py`):**
   - Compatibilidad Visual FoxPro `SYS(2007, cExp [, nFlags])`: cálculo de Checksum / CRC-32 determinista en formato de cadena.
   - Resúmenes criptográficos con `HASH(cExp, [cAlgoritmo])` (soporta SHA-256, MD5, SHA-512, SHA-1).
   - Firmas digitales HMAC para APIs y webhooks: `HMAC(cMensaje, cClave, [cAlgoritmo])`.
   - Cifrado simétrico reversible con keystream pseudoaleatorio SHA-256 y empaquetado seguro Base64: `ENCRYPT(cTexto, cClave)` y `DECRYPT(cEncriptado, cClave)`.
10. **Motor de Búsqueda Full-Text (FTS) en Memoria (`modern_vfp/fts.py`):**
    - Creación de índices invertidos textuales: `CREATE FULLTEXT INDEX ON <alias> (<campo1> [, <campo2>])`.
    - Consultas con cálculo de relevancia TF-IDF: `FULLTEXT SEARCH <cQuery> IN <alias> [INTO CURSOR <resultado>]`.
    - Funciones en expresiones: `FTSSEARCH(cAlias, cQuery)` (lista de registros ordenados) y predicado `FTSMATCH(cAlias, cQuery)` para filtros `FOR` / `WHERE`.
11. **Validación de Contratos y Esquemas JSON (`modern_vfp/schema_validator.py`):**
    - Verificación de integridad de datos contra especificaciones estándar JSON Schema (tipos, campos `required`, rangos numéricos `minimum` / `maximum`, restricciones de longitud `minLength` / `maxLength`, expresiones regulares `pattern` y listas `enum`).
    - Comando directo: `VALIDATE CURSOR <alias> AGAINST SCHEMA <cJsonOrFile>`.
    - Función booleana con diagnóstico detallado: `ISVALIDCURSOR(cAlias, cJsonOrFile [, laMatrizErrores])`.
12. **Tabulación Cruzada y Tablas Dinámicas (`modern_vfp/crosstab.py`):**
    - Motor de transformación pivote inspirado en la utilidad clásica `_GENXTAB` / `VFPXTAB` de Visual FoxPro.
    - Comando nativo: `CROSSTAB <source_alias> ON <row_field> COLUMNS <col_field> VALUES <val_field> [AGGREGATE SUM|AVG|COUNT|MIN|MAX] INTO CURSOR <target_alias>`.
    - Generación dinámica de columnas sanitizadas y columna `TOTAL` acumulativa.
5. **Concurrencia Multiusuario, Bloqueos Granulares y Bus Reactivo (`modern_vfp/locks.py`, `modern_vfp/eventbus.py`):**
   - Sistema de Bloqueos Concurrente (`LockManager`): `RLOCK([nRecno, cAlias])` para bloqueo de registros individuales o múltiples, `FLOCK([cAlias])` para bloqueo completo de tabla, y `UNLOCK [RECORD n] [IN alias] [ALL]` para liberación granular o total.
   - Banderas de control de concurrencia: `SET EXCLUSIVE ON|OFF` y `SET MULTILOCKS ON|OFF`.
   - Funciones de diagnóstico de bloqueo: `ISLOCKED([nRecno, cAlias])` e `ISREADONLY([cAlias])`.
   - Bus de Eventos Reactivo (`FoxEventBus`): desacoplamiento de arquitectura mediante `PUBLISH EVENT <topic> [DATA <expr>]` y suscripción reactiva directa a procedimientos con `SUBSCRIBE EVENT <topic> WITH <procedimiento>`.
6. **Interoperabilidad Microsoft Excel Nativa y Búsqueda Fonética (`modern_vfp/excel.py`):**
   - Soporte nativo de hojas de cálculo Microsoft Excel OpenXML (`.xlsx`) sin dependencias de terceros (Pure Python stdlib via zipfile y XML): `COPY TO <archivo.xlsx> TYPE XLSX` y `APPEND FROM <archivo.xlsx> TYPE XLSX` con inferencia automática de tipos (lógicos, enteros, decimales, texto).
   - Algoritmos fonéticos xBase estándar: `SOUNDEX(cExp)` (generación de huella fonética de 4 caracteres) y `DIFFERENCE(cExp1, cExp2)` (grado de coincidencia fonética de 0 a 4).
7. **Optimización Rushmore, Cursores 64-bit y Bases de Datos `.dbc` (`modern_vfp/rushmore.py`, `modern_vfp/dbc.py`, `modern_vfp/cursor.py`):**
   - Tecnología de optimización Rushmore (`RushmoreEngine`): evaluación ultraveloz de filtros `FOR <condicion>` mediante conjuntos e intersecciones de índices (`INDEX ON ... TAG ...`), soporte para niveles `Full`, `Partial` y `None`, y telemetría `SYS(3054)`.
   - Contenedor de Bases de Datos (`.dbc`): comandos `CREATE DATABASE <nombre>`, `OPEN DATABASE <nombre>`, `CLOSE DATABASES`, `ADD TABLE <tabla> TO DATABASE` y `VALIDATE DATABASE` para relaciones persistentes y reglas de integridad.
   - `CREATE CURSOR` / `CREATE TABLE`, `ALTER TABLE <alias> ADD / DROP COLUMN`, `SELECT <alias|area>`, `USE`, `CLOSE TABLES`.
   - Adaptador de datos relacional OOP nativo: `CREATEOBJECT("CursorAdapter")` (`VFPCursorAdapter`) con propiedades `Alias`, `SelectCmd`, `CursorSchema`, `DataSourceType`, `KeyFieldList`, `Tables` y métodos `.CursorFill([lUseSchema])`, `.CursorRefresh()` y `.CursorDetach()`.
   - Navegación e Índices: `GO TOP [IN alias]`, `GO BOTTOM [IN alias]`, `GOTO <n> [IN alias]`, `SKIP [n]`, `RECNO()`, `RECCOUNT()`, `INDEX ON <expr> TAG <tag>`, `SET ORDER TO <tag>`, `SEEK <expr>`, `LOCATE FOR <expr>`, `CONTINUE`, `FOUND()`, `SET RELATION TO <expr> INTO <alias>`.
   - Buffering y Transacciones Multinivel: `CURSORSETPROP("Buffering", 5)`, `TABLEUPDATE()`, `TABLEREVERT()`, `BEGIN TRANSACTION`, `END TRANSACTION`, `ROLLBACK`, `TXNLEVEL()`.
8. **Big Data Parquet, SQL Nativo Completo, Vistas Reactivas, XML y Cloud/JSON:**
   - Interoperabilidad columnar Parquet / Arrow (`modern_vfp/parquet.py`): `COPY TO <archivo.parquet> TYPE PARQUET` y `APPEND FROM <archivo.parquet> TYPE PARQUET` con esquema y tipos nativos.
   - Consultas relacionales nativas: `SELECT ... FROM ... INNER JOIN ... WHERE ... GROUP BY ... ORDER BY ... INTO CURSOR <alias>`.
   - Vistas SQL parametrizadas: `CREATE SQL VIEW <vista> AS SELECT ... WHERE campo = ?vp_param` y refresco reactivo en vivo con `REQUERY([alias])`.
   - Serialización e intercambio bidireccional XML: `CURSORTOXML(cAlias [, cVarOrFile])` y `XMLTOCURSOR(eXml, cAlias)`.
   - Modificación SQL directa sobre cursores: `UPDATE <alias> SET <campo> = <expr> WHERE <cond>` y `DELETE FROM <alias> WHERE <cond>`.
   - Conectividad SQL Pass-Through: `SQLCONNECT()`, `SQLSTRINGCONNECT()`, `SQLEXEC(nHandle, cSQL, cCursor)` (con parámetros `?variable`) y `SQLDISCONNECT()`.
   - Conversión directa Cursor $\leftrightarrow$ JSON y REST: `CURSORTOJSON([alias])`, `JSONTOCURSOR(lcJson, alias)`, `HTTPGET(url)`, `HTTPPOST(url, body)`.
9. **Compilador Bytecode `.fxp`, Ejecutables Autónomos (`BUILD EXE`), Lenguaje xBase y +90 Funciones:**
   - Compilador binario pre-tokenizado (`.fxp`): `COMPILE <archivo.prg> [TO <archivo.fxp>]` y ejecución de binarios pre-compilados con `DO <archivo.fxp>`.
   - Generación de ejecutables autónomos de 64 bits: `BUILD EXE <salida> FROM <proyecto.foxproj | programa.prg>` y CLI `--build-exe`.
   - Manejador global de errores: `ON ERROR [comando]`, disparo de errores con `ERROR <expr>`, lectura de código y mensaje con `ERROR()` / `MESSAGE()` y volcado diagnóstico a matriz con `AERROR(laInfoError)`.
   - Clases orientadas a objetos con herencia multinivel (`DEFINE CLASS Sub AS Super`), invocación a superclase con `DODEFAULT(...)`, reflexión con `ADDPROPERTY()` / `PEMSTATUS()`, y delegación reactiva de eventos con `BINDEVENT()`, `RAISEEVENT()` y `UNBINDEVENTS()`.
   - Arreglos 1-based (`DIMENSION` / `DECLARE`, `ALEN()`, `ASCAN()`, `ASORT()`, `ADIR()`) y clase nativa `CREATEOBJECT("Collection")`.
   - Funciones de sistema, rutas y archivos: `FILETOSTR()`, `STRTOFILE()`, `ADIR()`, `SYS(0|5|16|2003|2007|2015|2023|3054)`, `GETENV()`, `JUSTFNAME()`, `JUSTEXT()`, `JUSTPATH()`, `JUSTSTEM()`, `ADDBS()`, `FORCEEXT()`.
   - Bloques `TEXT TO <lcVar> [ADDITIVE] [TEXTMERGE] [NOSHOW] ... ENDTEXT` con interpolación `<<expresion>>`, `ASSERT <cond> [MESSAGE <msg>]` y sustitución de macros `&lcVar`.
10. **Formularios RAD (`.foxform`), Menús (`.foxmenu` / `DEFINE MENU`) y Motor de Reportes por Bandas (`.foxreport`):**
    - `DO FORM <archivo.foxform> [TO FILE <salida.html>]`, `REPORT FORM <archivo.foxreport> [FOR <cond>] [TO FILE <salida.txt | .html>]` y menús interactivos con `DEFINE MENU`, `DEFINE PAD`, `DEFINE POPUP`, `DEFINE BAR`, `ON SELECTION BAR` y `ACTIVATE POPUP`.
11. **Tooling Moderno: Empaquetador EXE (`--build-exe`), Compilador (`--compile`), Profiler (`--profile`), DocGen (`--doc`), Depurador (`--debug`), Transpilador Python (`--transpile`), LSP (`--check`), Microservicios REST (`--api`), Migrador VFP 9 y Empaquetador:**
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

# 7. Ejecutar las 60 suites de pruebas integrales
python3 -m unittest discover -s tests -v
```

---

## Documentación Arquitectónica

- [**Plan Maestro y Roadmap (`PLAN.md`)**](./PLAN.md)
- [**Especificación Técnica del Lenguaje y Cursores (`docs/SPECIFICATION.md`)**](./docs/SPECIFICATION.md)

* ====================================================================
* FoxNext ERP Demo: Programa Principal (main.prg)
* Demuestra Vistas SQL, Rushmore, XML, Parquet, Reportes y Formularios
* ====================================================================

? "Iniciando FoxNext ERP v1.0.0..."

* 1. Cargar esquema de base de datos
DO "schema.prg"

* 2. Vista SQL parametrizada reactiva
vp_estado = "PENDIENTE"
CREATE SQL VIEW v_pendientes AS SELECT * FROM facturas WHERE estado == ?vp_estado
? "Facturas Pendientes iniciales: " + TRANSFORM(RECCOUNT("v_pendientes"))

* 3. Búsqueda y Optimización Rushmore
INDEX ON estado TAG tag_estado
lnPendientesRush = 0
SCAN FOR estado == "PENDIENTE"
    lnPendientesRush = lnPendientesRush + 1
ENDSCAN
? "Facturas analizadas con Rushmore: " + TRANSFORM(lnPendientesRush)

* 4. Exportar a formatos modernos (XML y Parquet)
lcXml = CURSORTOXML("facturas")
? "Longitud XML exportado: " + TRANSFORM(LEN(lcXml))

COPY TO "facturas_export.parquet" TYPE PARQUET
? "Facturas exportadas exitosamente a Parquet binario columnar."

* 5. Ejecutar reporte empresarial
REPORT FORM "facturas.foxreport"

? "FoxNext ERP Demo finalizado exitosamente."

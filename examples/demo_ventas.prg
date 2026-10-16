* ============================================================================
* DEMO_VENTAS.PRG - Ejemplo Completo de FoxNext (Modern VFP 64-bit)
* Demuestra Cursores en Memoria, Índices, SQL Nativo, SCAN y Clases OOP
* ============================================================================

CLEAR
? "=== Iniciando Sistema de Ventas en FoxNext (64-bit) ==="

* 1. Crear cursor de Clientes
CREATE CURSOR clientes (id I, nombre C(40), ciudad C(25), vip L, alta D)

INSERT INTO clientes VALUES (1, "Ada Lovelace", "Londres", .T., {^2025-01-15})
INSERT INTO clientes VALUES (2, "Alan Turing", "Manchester", .T., {^2025-03-20})
INSERT INTO clientes VALUES (3, "Grace Hopper", "Nueva York", .T., {^2025-06-10})
INSERT INTO clientes VALUES (4, "niklaus wirth", "Zurich", .F., {^2026-02-01})

* Capitalizar nombres con REPLACE ALL y PROPER()
REPLACE ALL nombre WITH PROPER(ALLTRIM(nombre))

* Crear índice por ID para búsquedas instantáneas
INDEX ON id TAG idx_id

* 2. Crear cursor de Facturas en una nueva área de trabajo
SELECT 0
CREATE CURSOR facturas (folio I, cliente_id I, concepto C(40), importe Y, pagada L)

INSERT INTO facturas VALUES (101, 1, "Servidor Cloud 64-bit", 4500.00, .T.)
INSERT INTO facturas VALUES (102, 1, "Licencia FoxNext Enterprise", 2800.50, .T.)
INSERT INTO facturas VALUES (103, 2, "Consultoría Criptografía", 6200.00, .T.)
INSERT INTO facturas VALUES (104, 3, "Compilador A-0", 9100.75, .T.)
INSERT INTO facturas VALUES (105, 4, "Soporte Anual", 1200.00, .F.)

* 3. Ejecutar SQL Nativo Relacional (JOIN + GROUP BY + Variables Locales)
LOCAL lnMinimo = 3000

SELECT c.id, c.nombre, c.ciudad, COUNT(f.folio) AS num_facturas, SUM(f.importe) AS total_ventas ;
    FROM clientes c ;
    INNER JOIN facturas f ON c.id = f.cliente_id ;
    WHERE f.pagada = 1 ;
    GROUP BY c.id, c.nombre, c.ciudad ;
    ORDER BY total_ventas DESC ;
    INTO CURSOR curRanking

? ""
? "--- Ranking de Clientes por Facturación Pagada (BROWSE) ---"
BROWSE

* 4. Recorrido con SCAN ... ENDSCAN y uso de Objetos (OOP)
loCalculadora = CREATEOBJECT("CalculadoraImpuestos", 0.16)

? ""
? "--- Detalle de Impuestos Calculados (SCAN...ENDSCAN) ---"
SCAN FOR total_ventas >= lnMinimo
    lnIva = loCalculadora.CalcularIVA(curRanking.total_ventas)
    ? "Cliente:", PADR(curRanking.nombre, 18), ;
      "| Neto: $" + ALLTRIM(STR(curRanking.total_ventas, 10, 2)), ;
      "| IVA: $" + ALLTRIM(STR(lnIva, 10, 2))
ENDSCAN

* 5. Definición de Clase Orientada a Objetos en FoxNext
DEFINE CLASS CalculadoraImpuestos AS Custom
    tasa = 0.16

    PROCEDURE Init(tnTasa)
        IF !EMPTY(tnTasa)
            THIS.tasa = tnTasa
        ENDIF
    ENDPROC

    FUNCTION CalcularIVA(tnMonto)
        RETURN ROUND(tnMonto * THIS.tasa, 2)
    ENDFUNC
ENDDEFINE

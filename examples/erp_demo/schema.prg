* ====================================================================
* FoxNext ERP Demo: Inicialización de Base de Datos Contenedora (.dbc)
* ====================================================================

CREATE DATABASE "empresa.dbc"

* 1. Definición y Carga de Clientes
CREATE CURSOR clientes (id I, rfc C(15), razon_social C(50), saldo Y, activo L)
INDEX ON id TAG tag_id
INDEX ON rfc TAG tag_rfc

INSERT INTO clientes VALUES (1, "XAXX010101000", "Tecnología Avanzada SA de CV", 15400.00, .T.)
INSERT INTO clientes VALUES (2, "XEXX010101000", "Comercializadora Global SAPI", 8750.50, .T.)
INSERT INTO clientes VALUES (3, "XUXX010101000", "Servicios Digitales del Norte", 0.00, .F.)

ADD TABLE clientes TO DATABASE

* 2. Definición y Carga de Facturas
CREATE CURSOR facturas (folio I, cliente_id I, fecha D, subtotal N(12,2), iva N(12,2), total N(12,2), estado C(10))
INDEX ON folio TAG tag_folio
INDEX ON cliente_id TAG tag_cli_id
INDEX ON estado TAG tag_estado

INSERT INTO facturas VALUES (1001, 1, {^2026-10-15}, 10000.00, 1600.00, 11600.00, "PAGADA")
INSERT INTO facturas VALUES (1002, 1, {^2026-10-18}, 3275.86, 524.14, 3800.00, "PENDIENTE")
INSERT INTO facturas VALUES (1003, 2, {^2026-10-20}, 7543.10, 1206.90, 8750.00, "PENDIENTE")

ADD TABLE facturas TO DATABASE

VALIDATE DATABASE
? "[FoxNext ERP] Base de datos 'empresa.dbc' inicializada con 2 tablas y 5 índices."

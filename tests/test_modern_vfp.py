"""
Suite de Pruebas Integrales para FoxNext / Modern VFP (64-bit).
Valida cursores, índices, relaciones, buffering, SQL nativo, DBF binario, OOP y formularios .foxform.
"""

from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

from modern_vfp.foxform import FoxForm
from modern_vfp.interpreter import FoxInterpreter


class TestModernVFP(unittest.TestCase):
    def setUp(self) -> None:
        self.interp = FoxInterpreter()

    def test_cursor_creation_and_navigation(self) -> None:
        self.interp.execute(
            """
            CREATE CURSOR productos (id I, nombre C(30), precio N(10,2), disponible L)
            APPEND BLANK
            REPLACE id WITH 10, nombre WITH "Teclado Mecánico", precio WITH 85.50, disponible WITH .T.
            INSERT INTO productos VALUES (20, "Monitor 4K", 399.99, .T.)
            INSERT INTO productos VALUES (30, "Mouse Óptico", 25.00, .F.)
            """
        )
        self.assertEqual(self.interp.eval_expr("RECCOUNT('productos')"), 3)
        self.interp.execute("GO TOP")
        self.assertEqual(self.interp.eval_expr("RECNO()"), 1)
        self.assertEqual(self.interp.eval_expr("nombre"), "Teclado Mecánico")

        self.interp.execute("SKIP 1")
        self.assertEqual(self.interp.eval_expr("id"), 20)
        self.assertAlmostEqual(self.interp.eval_expr("precio"), 399.99)

        self.interp.execute("GO BOTTOM")
        self.assertEqual(self.interp.eval_expr("id"), 30)
        self.assertFalse(self.interp.eval_expr("disponible"))

    def test_locate_continue_and_indexes(self) -> None:
        self.interp.execute(
            """
            CREATE CURSOR empleados (legajo I, apellido C(25), depto C(15))
            INSERT INTO empleados VALUES (300, "Zavala", "Ventas")
            INSERT INTO empleados VALUES (100, "Alvarez", "Sistemas")
            INSERT INTO empleados VALUES (200, "Benitez", "Ventas")

            LOCATE FOR depto = "Ventas"
            """
        )
        self.assertTrue(self.interp.eval_expr("FOUND()"))
        self.assertEqual(self.interp.eval_expr("legajo"), 300)

        self.interp.execute("CONTINUE")
        self.assertTrue(self.interp.eval_expr("FOUND()"))
        self.assertEqual(self.interp.eval_expr("legajo"), 200)

        # Indexar por legajo y buscar con SEEK
        self.interp.execute(
            """
            INDEX ON legajo TAG idx_leg
            SEEK 100
            """
        )
        self.assertTrue(self.interp.eval_expr("FOUND()"))
        self.assertEqual(self.interp.eval_expr("apellido"), "Alvarez")

    def test_delete_recall_pack_and_set_deleted(self) -> None:
        self.interp.execute(
            """
            CREATE CURSOR items (id I, texto C(10))
            INSERT INTO items VALUES (1, "Uno")
            INSERT INTO items VALUES (2, "Dos")
            INSERT INTO items VALUES (3, "Tres")
            GOTO 2
            DELETE
            """
        )
        self.assertTrue(self.interp.eval_expr("DELETED()"))

        self.interp.execute(
            """
            SET DELETED ON
            LOCAL lnConteo = 0
            SCAN
                lnConteo = lnConteo + 1
            ENDSCAN
            """
        )
        self.assertEqual(self.interp.eval_expr("lnConteo"), 2)

        self.interp.execute(
            """
            SET DELETED OFF
            PACK
            """
        )
        self.assertEqual(self.interp.eval_expr("RECCOUNT()"), 2)

    def test_table_buffering_commit_and_revert(self) -> None:
        self.interp.execute(
            """
            CREATE CURSOR cuentas (id I, saldo Y)
            INSERT INTO cuentas VALUES (1, 1000.00)
            CURSORSETPROP("Buffering", 5, "cuentas")
            REPLACE saldo WITH 5000.00
            """
        )
        self.assertEqual(self.interp.eval_expr("saldo"), 5000.00)
        # Revertir cambios no confirmados
        self.interp.execute("TABLEREVERT(.T., 'cuentas')")
        self.assertEqual(self.interp.eval_expr("saldo"), 1000.00)

        # Modificar y confirmar con TABLEUPDATE
        self.interp.execute(
            """
            REPLACE saldo WITH 2500.00
            TABLEUPDATE(.T., .T., "cuentas")
            TABLEREVERT(.T., "cuentas")
            """
        )
        self.assertEqual(self.interp.eval_expr("saldo"), 2500.00)

    def test_native_sql_join_and_scan(self) -> None:
        self.interp.execute(
            """
            CREATE CURSOR clientes (id I, nombre C(30))
            INSERT INTO clientes VALUES (1, "Ada")
            INSERT INTO clientes VALUES (2, "Alan")

            SELECT 0
            CREATE CURSOR pedidos (id I, cliente_id I, monto N(10,2))
            INSERT INTO pedidos VALUES (10, 1, 150.00)
            INSERT INTO pedidos VALUES (11, 1, 350.00)
            INSERT INTO pedidos VALUES (12, 2, 200.00)

            LOCAL lnMin = 250
            SELECT c.nombre, SUM(p.monto) AS total ;
                FROM clientes c ;
                INNER JOIN pedidos p ON c.id = p.cliente_id ;
                GROUP BY c.nombre ;
                ORDER BY total DESC ;
                INTO CURSOR curTotales

            LOCAL lcGanador = ""
            SCAN FOR total > lnMin
                lcGanador = curTotales.nombre
            ENDSCAN
            """
        )
        self.assertEqual(self.interp.eval_expr("RECCOUNT('curTotales')"), 2)
        self.assertEqual(self.interp.eval_expr("lcGanador"), "Ada")

    def test_set_relation_synchronization(self) -> None:
        self.interp.execute(
            """
            CREATE CURSOR categorias (cat_id I, descripcion C(20))
            INSERT INTO categorias VALUES (10, "Hardware")
            INSERT INTO categorias VALUES (20, "Software")
            INDEX ON cat_id TAG idx_cat

            SELECT 0
            CREATE CURSOR articulos (art_id I, cat_id I, titulo C(25))
            INSERT INTO articulos VALUES (1, 20, "Compilador FoxNext")
            INSERT INTO articulos VALUES (2, 10, "Tarjeta NVMe")

            SET RELATION TO cat_id INTO categorias
            GO TOP
            """
        )
        self.assertEqual(self.interp.eval_expr("categorias.descripcion"), "Software")
        self.interp.execute("SKIP 1")
        self.assertEqual(self.interp.eval_expr("categorias.descripcion"), "Hardware")

    def test_oop_define_class_and_methods(self) -> None:
        self.interp.execute(
            """
            DEFINE CLASS Facturador AS Custom
                prefijo = "FAC-"
                impuesto = 0.21

                PROCEDURE Init(tcPrefijo)
                    IF !EMPTY(tcPrefijo)
                        THIS.prefijo = tcPrefijo
                    ENDIF
                ENDPROC

                FUNCTION FormatearTotal(tnNumero, tnSubTotal)
                    LOCAL lnFinal = ROUND(tnSubTotal * (1 + THIS.impuesto), 2)
                    RETURN THIS.prefijo + PADL(tnNumero, 4, "0") + ":" + ALLTRIM(STR(lnFinal, 10, 2))
                ENDFUNC
            ENDDEFINE

            loFac = CREATEOBJECT("Facturador", "INV-")
            lcResultado = loFac.FormatearTotal(7, 100)
            """
        )
        self.assertEqual(self.interp.eval_expr("lcResultado"), "INV-0007:121.00")

    def test_dbf_binary_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dbf_path = Path(tmpdir) / "agenda.dbf"
            self.interp.execute(
                f"""
                CREATE CURSOR agenda (id I, nombre C(30), vip L, fecha D)
                INSERT INTO agenda VALUES (1, "Grace Hopper", .T., {{^2026-10-16}})
                INSERT INTO agenda VALUES (2, "John Backus", .F., {{^2025-05-01}})
                COPY TO "{dbf_path}" TYPE DBF
                CLOSE TABLES
                USE "{dbf_path}" ALIAS agenda_leida
                """
            )
            self.assertTrue(dbf_path.is_file())
            self.assertEqual(self.interp.eval_expr("RECCOUNT('agenda_leida')"), 2)
            self.interp.execute("GO TOP")
            self.assertEqual(self.interp.eval_expr("nombre"), "Grace Hopper")
            self.assertTrue(self.interp.eval_expr("vip"))

    def test_foxform_declarative_binding(self) -> None:
        form_path = Path(__file__).resolve().parent.parent / "examples" / "clientes.foxform"
        form = FoxForm.from_file(form_path, interpreter=self.interp)
        form.initialize()

        # El primer registro en clientes debe ser Ada Lovelace
        self.assertEqual(form.read_control_value("txtNombre"), "Ada Lovelace")

        # Modificar el valor del control actualiza el cursor subyacente automáticamente
        form.write_control_value("txtNombre", "Ada Byron Lovelace")
        self.assertEqual(self.interp.eval_expr("clientes.nombre"), "Ada Byron Lovelace")

        # Confirmar con el botón btnGuardar
        form.trigger_click("btnGuardar")
        tui = form.render_tui()
        self.assertIn("Ada Byron Lovelace", tui)


if __name__ == "__main__":
    unittest.main()

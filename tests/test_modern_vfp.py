"""
Suite de Pruebas Integrales para FoxNext / Modern VFP (64-bit) v0.4.0.
Valida cursores, índices, relaciones, buffering, transacciones (BEGIN/END/ROLLBACK),
SCATTER/GATHER, CALCULATE, TEXT...ENDTEXT, CURSORTOJSON/JSONTOCURSOR,
SQL nativo (SELECT/UPDATE/DELETE), SQL Pass-Through (SQLCONNECT/SQLEXEC),
APPEND FROM, DBF binario, OOP, .foxform, .foxreport, migrador .scx, .foxproj/.foxapp y Studio.
"""

from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

from modern_vfp.foxform import FoxForm
from modern_vfp.interpreter import FoxInterpreter
from modern_vfp.migrator import create_sample_vfp9_scx
from modern_vfp.project import run_foxapp
from modern_vfp.studio import render_studio_snapshot_html, serialize_session_state


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
        self.interp.execute("TABLEREVERT(.T., 'cuentas')")
        self.assertEqual(self.interp.eval_expr("saldo"), 1000.00)

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

    def test_sql_update_delete_and_append_from(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_file = Path(tmpdir) / "importar.csv"
            self.interp.execute(
                f"""
                CREATE CURSOR origen (id I, nombre C(25), puntos I)
                INSERT INTO origen VALUES (1, "Alfa", 10)
                INSERT INTO origen VALUES (2, "Beta", 20)
                INSERT INTO origen VALUES (3, "Gamma", 30)
                COPY TO "{csv_file}" TYPE CSV

                CREATE CURSOR destino (id I, nombre C(25), puntos I)
                APPEND FROM "{csv_file}" TYPE CSV

                UPDATE destino SET puntos = puntos * 2, nombre = UPPER(nombre) WHERE id >= 2
                DELETE FROM destino WHERE id = 1
                SET DELETED ON
                """
            )
            self.interp.execute("SELECT destino\nGO TOP")
            self.assertEqual(self.interp.eval_expr("id"), 2)
            self.assertEqual(self.interp.eval_expr("nombre"), "BETA")
            self.assertEqual(self.interp.eval_expr("puntos"), 40)

    def test_sql_pass_through_sqlconnect_sqlexec(self) -> None:
        self.interp.execute(
            """
            lnHandle = SQLCONNECT(":memory:")
            =SQLEXEC(lnHandle, "CREATE TABLE sucursales (id INT, ciudad TEXT, meta REAL)")
            =SQLEXEC(lnHandle, "INSERT INTO sucursales VALUES (1, 'Madrid', 95000.50)")
            =SQLEXEC(lnHandle, "INSERT INTO sucursales VALUES (2, 'Bogotá', 82000.00)")

            LOCAL lcCiudadFiltro = "Madrid"
            lnRes = SQLEXEC(lnHandle, "SELECT * FROM sucursales WHERE ciudad = ?lcCiudadFiltro", "curRemoto")
            =SQLDISCONNECT(lnHandle)
            """
        )
        self.assertEqual(self.interp.eval_expr("lnRes"), 1)
        self.assertEqual(self.interp.eval_expr("RECCOUNT('curRemoto')"), 1)
        self.assertEqual(self.interp.eval_expr("curRemoto.ciudad"), "Madrid")
        self.assertAlmostEqual(self.interp.eval_expr("curRemoto.meta"), 95000.50)

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

    def test_foxform_and_do_form_command(self) -> None:
        form_path = Path(__file__).resolve().parent.parent / "examples" / "clientes.foxform"
        with tempfile.TemporaryDirectory() as tmpdir:
            html_out = Path(tmpdir) / "clientes.html"
            self.interp.execute(f'DO FORM "{form_path}" TO FILE "{html_out}"')
            self.assertTrue(html_out.is_file())
            self.assertIn("Ada Lovelace", html_out.read_text(encoding="utf-8"))

            form_obj: FoxForm = self.interp.eval_expr("frmClientes")
            form_obj.write_control_value("txtNombre", "Ada Byron Lovelace")
            self.assertEqual(self.interp.eval_expr("clientes.nombre"), "Ada Byron Lovelace")

    def test_foxreport_and_report_form_command(self) -> None:
        root_dir = Path(__file__).resolve().parent.parent
        demo_prg = root_dir / "examples" / "demo_ventas.prg"
        report_file = root_dir / "examples" / "ventas.foxreport"
        with tempfile.TemporaryDirectory() as tmpdir:
            txt_out = Path(tmpdir) / "reporte.txt"
            html_out = Path(tmpdir) / "reporte.html"
            self.interp.execute(
                f"""
                DO "{demo_prg}"
                REPORT FORM "{report_file}" TO FILE "{txt_out}"
                REPORT FORM "{report_file}" FOR total_ventas > 7000 TO FILE "{html_out}"
                """
            )
            txt_content = txt_out.read_text(encoding="utf-8")
            html_content = html_out.read_text(encoding="utf-8")
            self.assertIn("REPORTE EJECUTIVO DE FACTURACIÓN POR CLIENTE", txt_content)
            self.assertIn("$22,601.25", txt_content)
            self.assertIn("Grace Hopper", html_content)
            self.assertNotIn("Alan Turing", html_content)

    def test_vfp9_scx_migrator_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scx_file = Path(tmpdir) / "inventario.scx"
            foxform_file = Path(tmpdir) / "inventario.foxform"
            create_sample_vfp9_scx(scx_file)

            self.interp.execute(
                f"""
                MIGRATE SCX "{scx_file}" TO "{foxform_file}"
                DO FORM "{foxform_file}"
                """
            )
            self.assertTrue(foxform_file.is_file())
            self.assertEqual(self.interp.eval_expr("articulos.descripcion"), "Teclado IBM Model M")
            self.assertEqual(self.interp.eval_expr("articulos.stock"), 15)

            frm: FoxForm = self.interp.eval_expr("frmInventario")
            frm.trigger_click("btnAgregarStock")
            self.assertEqual(self.interp.eval_expr("articulos.stock"), 20)

    def test_studio_session_serialization(self) -> None:
        self.interp.execute(
            """
            CREATE CURSOR test_studio (id I, titulo C(20))
            INSERT INTO test_studio VALUES (1, "FoxNext Studio")
            """
        )
        state = serialize_session_state(self.interp)
        self.assertEqual(len(state["workAreas"]), 1)
        self.assertEqual(state["workAreas"][0]["alias"], "TEST_STUDIO")
        html_snap = render_studio_snapshot_html(self.interp)
        self.assertIn("FoxNext Studio", html_snap)

    def test_scatter_gather_and_calculate(self) -> None:
        self.interp.execute(
            """
            CREATE CURSOR nomina (id I, empleado C(30), sueldo N(10,2))
            INSERT INTO nomina VALUES (1, "Carlos", 3000.00)
            INSERT INTO nomina VALUES (2, "Elena", 4500.00)
            INSERT INTO nomina VALUES (3, "Marcos", 2500.00)

            GO TOP
            SCATTER NAME loEmp
            loEmp.sueldo = 3800.00
            loEmp.empleado = "Carlos Actualizado"
            GATHER NAME loEmp

            SCATTER NAME loNuevo BLANK
            loNuevo.id = 4
            loNuevo.empleado = "Lucia"
            loNuevo.sueldo = 5200.00
            APPEND BLANK
            GATHER NAME loNuevo

            CALCULATE SUM(sueldo), AVG(sueldo), COUNT(), MAX(sueldo) FOR sueldo >= 3500 TO lnSuma, lnProm, lnCant, lnMax
            """
        )
        self.interp.execute("GO TOP")
        self.assertEqual(self.interp.eval_expr("empleado"), "Carlos Actualizado")
        self.assertEqual(self.interp.eval_expr("sueldo"), 3800.00)
        self.assertEqual(self.interp.eval_expr("RECCOUNT()"), 4)
        self.assertAlmostEqual(self.interp.eval_expr("lnSuma"), 13500.00)
        self.assertAlmostEqual(self.interp.eval_expr("lnProm"), 4500.00)
        self.assertEqual(self.interp.eval_expr("lnCant"), 3)
        self.assertAlmostEqual(self.interp.eval_expr("lnMax"), 5200.00)

    def test_text_endtext_textmerge(self) -> None:
        self.interp.execute(
            """
            LOCAL lcTabla = "clientes"
            LOCAL lnLimite = 5000
            TEXT TO lcConsulta TEXTMERGE NOSHOW
SELECT id, nombre
FROM <<lcTabla>>
WHERE total_ventas >= <<lnLimite>>
            ENDTEXT
            """
        )
        expected = "SELECT id, nombre\nFROM clientes\nWHERE total_ventas >= 5000"
        self.assertEqual(self.interp.eval_expr("lcConsulta"), expected)

    def test_multilevel_transactions_and_json_cursor(self) -> None:
        self.interp.execute(
            """
            CREATE CURSOR bancos (id I, titular C(25), balance N(12,2))
            INSERT INTO bancos VALUES (1, "Cuenta Principal", 10000.00)

            BEGIN TRANSACTION
            REPLACE balance WITH 8000.00
            lnNivel1 = TXNLEVEL()

            BEGIN TRANSACTION
            REPLACE balance WITH 100.00
            lnNivel2 = TXNLEVEL()
            ROLLBACK

            lnBalanceTrasRollbackInterno = bancos.balance
            END TRANSACTION

            lcJson = CURSORTOJSON("bancos")
            =JSONTOCURSOR(lcJson, "bancos_clon")
            """
        )
        self.assertEqual(self.interp.eval_expr("lnNivel1"), 1)
        self.assertEqual(self.interp.eval_expr("lnNivel2"), 2)
        self.assertEqual(self.interp.eval_expr("TXNLEVEL()"), 0)
        self.assertEqual(self.interp.eval_expr("lnBalanceTrasRollbackInterno"), 8000.00)
        self.assertEqual(self.interp.eval_expr("bancos_clon.balance"), 8000.00)
        self.assertEqual(self.interp.eval_expr("bancos_clon.titular"), "Cuenta Principal")

    def test_project_build_app_and_execution(self) -> None:
        root_dir = Path(__file__).resolve().parent.parent
        proj_file = root_dir / "examples" / "ventas.foxproj"
        with tempfile.TemporaryDirectory() as tmpdir:
            app_out = Path(tmpdir) / "ventas.foxapp"
            self.interp.execute(f'BUILD APP "{app_out}" FROM "{proj_file}"')
            self.assertTrue(app_out.is_file())

            fresh_interp = FoxInterpreter()
            run_foxapp(app_out, fresh_interp)
            self.assertEqual(fresh_interp.eval_expr("RECCOUNT('curRanking')"), 3)


if __name__ == "__main__":
    unittest.main()

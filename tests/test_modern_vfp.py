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

    def test_arrays_and_collections(self) -> None:
        self.interp.execute(
            """
            DIMENSION laPrecios[3]
            laPrecios[1] = 300
            laPrecios[2] = 100
            laPrecios[3] = 200
            =ASORT(laPrecios)
            lnPos = ASCAN(laPrecios, 200)
            lnTotalElem = ALEN(laPrecios)

            CREATE CURSOR orig_arr (id I, etiqueta C(15))
            INSERT INTO orig_arr VALUES (1, "Uno")
            INSERT INTO orig_arr VALUES (2, "Dos")
            COPY TO ARRAY laCopia

            CREATE CURSOR dest_arr (id I, etiqueta C(15))
            APPEND FROM ARRAY laCopia

            loCol = CREATEOBJECT("Collection")
            loCol.Add("Valor A", "clave_a")
            loCol.Add("Valor B", "clave_b")
            lcItemA = loCol.Item("clave_a")
            lnColCount = loCol.Count

            lcExtraido = STREXTRACT("<tag>FoxNext 64</tag>", "<tag>", "</tag>")
            lcPalabra2 = GETWORDNUM("Visual FoxPro Moderno", 2)
            """
        )
        self.assertEqual(self.interp.eval_expr("lnPos"), 2)
        self.assertEqual(self.interp.eval_expr("lnTotalElem"), 3)
        self.assertEqual(self.interp.eval_expr("RECCOUNT('dest_arr')"), 2)
        self.assertEqual(self.interp.eval_expr("lcItemA"), "Valor A")
        self.assertEqual(self.interp.eval_expr("lnColCount"), 2)
        self.assertEqual(self.interp.eval_expr("lcExtraido"), "FoxNext 64")
        self.assertEqual(self.interp.eval_expr("lcPalabra2"), "FoxPro")

    def test_alter_table_add_drop_column(self) -> None:
        self.interp.execute(
            """
            CREATE CURSOR clientes_alt (id I, nombre C(25))
            INSERT INTO clientes_alt VALUES (1, "Ada Lovelace")

            ALTER TABLE clientes_alt ADD COLUMN email C(50)
            ALTER TABLE clientes_alt ADD COLUMN puntos I
            REPLACE email WITH "ada@foxnext.dev", puntos WITH 100

            ALTER TABLE clientes_alt DROP COLUMN nombre
            """
        )
        self.assertEqual(self.interp.eval_expr("FCOUNT('clientes_alt')"), 3)
        self.assertEqual(self.interp.eval_expr("clientes_alt.email"), "ada@foxnext.dev")
        self.assertEqual(self.interp.eval_expr("clientes_alt.puntos"), 100)

    def test_lsp_static_analysis_and_completions(self) -> None:
        from modern_vfp.lsp import analyze_fox_source, get_completions

        valid_code = """
        CREATE CURSOR productos (id I, descripcion C(40), precio N(10,2))
        FUNCTION CalcularDescuento(tnPrecio)
            IF tnPrecio > 100
                RETURN tnPrecio * 0.90
            ENDIF
            RETURN tnPrecio
        ENDFUNC
        """
        analysis = analyze_fox_source(valid_code)
        self.assertEqual(len(analysis["diagnostics"]), 0)
        kinds = {s["name"]: s["kind"] for s in analysis["symbols"]}
        self.assertEqual(kinds.get("productos"), "Cursor")
        self.assertEqual(kinds.get("CalcularDescuento"), "Function")

        broken_code = "IF x > 10\n  ? 'Hola'\nENDSCAN"
        broken_res = analyze_fox_source(broken_code)
        self.assertGreaterEqual(len(broken_res["diagnostics"]), 1)

        self.interp.execute("CREATE CURSOR clientes (id I, nombre C(30), saldo Y)")
        comps = get_completions("clientes.n", self.interp)
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0]["insertText"], "nombre")

    def test_rest_api_microservice_dispatcher(self) -> None:
        from modern_vfp.apiserver import dispatch_api_request

        self.interp.execute(
            """
            CREATE CURSOR catalogo (id I, producto C(30), precio N(10,2))
            INSERT INTO catalogo VALUES (1, "Lapiz", 1.50)

            FUNCTION SumarValores(a, b)
                RETURN a + b
            ENDFUNC
            """
        )
        status, list_resp = dispatch_api_request(self.interp, "GET", "/api/cursors")
        self.assertEqual(status, 200)
        self.assertEqual(len(list_resp["cursors"]), 1)

        status, post_resp = dispatch_api_request(
            self.interp,
            "POST",
            "/api/cursors/catalogo",
            {"id": 2, "producto": "Cuaderno", "precio": 4.25},
        )
        self.assertEqual(status, 201)
        self.assertEqual(post_resp["reccount"], 2)

        status, get_resp = dispatch_api_request(self.interp, "GET", "/api/cursors/catalogo")
        self.assertEqual(status, 200)
        self.assertEqual(get_resp["count"], 2)

        status, rpc_resp = dispatch_api_request(
            self.interp,
            "POST",
            "/api/rpc/SumarValores",
            {"args": [15, 27]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(rpc_resp["result"], 42)

    def test_oop_inheritance_dodefault_and_reflection(self) -> None:
        self.interp.execute(
            """
            DEFINE CLASS EmpleadoBase AS Custom
                SalarioBase = 1000
                Departamento = "General"

                FUNCTION CalcularBono(tnFactor)
                    RETURN THIS.SalarioBase * tnFactor
                ENDFUNC
            ENDDEFINE

            DEFINE CLASS Gerente AS EmpleadoBase
                BonoGerencial = 500

                FUNCTION CalcularBono(tnFactor)
                    lnBase = DODEFAULT(tnFactor)
                    RETURN lnBase + THIS.BonoGerencial
                ENDFUNC
            ENDDEFINE

            loGerente = CREATEOBJECT("Gerente")
            lnTotalBono = loGerente.CalcularBono(2)
            =ADDPROPERTY(loGerente, "CodigoEjecutivo", "EXEC-99")
            llTieneMetodo = PEMSTATUS(loGerente, "CalcularBono", 5)
            llTieneProp = PEMSTATUS(loGerente, "CodigoEjecutivo", 5)
            """
        )
        self.assertEqual(self.interp.eval_expr("lnTotalBono"), 2500)
        self.assertEqual(self.interp.eval_expr("loGerente.Departamento"), "General")
        self.assertEqual(self.interp.eval_expr("loGerente.CodigoEjecutivo"), "EXEC-99")
        self.assertTrue(self.interp.eval_expr("llTieneMetodo"))
        self.assertTrue(self.interp.eval_expr("llTieneProp"))

    def test_bindevent_raiseevent_and_unbindevents(self) -> None:
        self.interp.execute(
            """
            DEFINE CLASS EmisorPedido AS Custom
                UltimoTotal = 0
                FUNCTION AlConfirmar(tnMonto)
                    THIS.UltimoTotal = tnMonto
                ENDFUNC
            ENDDEFINE

            DEFINE CLASS AuditorEventos AS Custom
                EventosRecibidos = 0
                MontoAuditado = 0
                FUNCTION RegistrarAuditoria(tnMonto)
                    THIS.EventosRecibidos = THIS.EventosRecibidos + 1
                    THIS.MontoAuditado = tnMonto
                ENDFUNC
            ENDDEFINE

            loEmisor = CREATEOBJECT("EmisorPedido")
            loAuditor = CREATEOBJECT("AuditorEventos")

            =BINDEVENT(loEmisor, "AlConfirmar", loAuditor, "RegistrarAuditoria")
            =RAISEEVENT(loEmisor, "AlConfirmar", 750)

            lnAntesUnbind = loAuditor.EventosRecibidos
            =UNBINDEVENTS(loEmisor)
            =RAISEEVENT(loEmisor, "AlConfirmar", 999)
            lnDespuesUnbind = loAuditor.EventosRecibidos
            """
        )
        self.assertEqual(self.interp.eval_expr("loEmisor.UltimoTotal"), 999)
        self.assertEqual(self.interp.eval_expr("loAuditor.MontoAuditado"), 750)
        self.assertEqual(self.interp.eval_expr("lnAntesUnbind"), 1)
        self.assertEqual(self.interp.eval_expr("lnDespuesUnbind"), 1)

    def test_debugger_breakpoints_watchpoints_and_assert(self) -> None:
        from modern_vfp.debugger import FoxDebugger

        dbg = FoxDebugger(self.interp)
        dbg.add_breakpoint(2)
        dbg.add_watch("lnContador")

        res = dbg.run_with_trace(
            """
            lnContador = 10
            lnContador = 25
            SET STEP ON
            lnContador = 50
            """
        )
        self.assertEqual(len(res["breakpointHits"]), 2)
        self.assertGreaterEqual(len(res["watchHits"]), 2)
        self.assertEqual(self.interp.eval_expr("lnContador"), 50)

        # Verificar ASSERT cuando SET ASSERTS ON está activo
        self.interp.execute("SET ASSERTS ON")
        self.interp.execute("ASSERT 2 + 2 == 4 MESSAGE 'Matemática válida'")
        with self.assertRaises(AssertionError):
            self.interp.execute("ASSERT 1 == 2 MESSAGE 'Fallo de aserción esperado'")

    def test_prg_to_python_transpiler(self) -> None:
        from modern_vfp.transpiler import transpile_prg_to_python

        prg_code = """
        CREATE CURSOR items_py (id I, valor I)
        INSERT INTO items_py VALUES (1, 40)
        INSERT INTO items_py VALUES (2, 60)
        CALCULATE SUM(valor) TO lnSumaPy
        """
        py_source = transpile_prg_to_python(prg_code)
        self.assertIn("def run_fox_program", py_source)
        self.assertIn("FoxInterpreter", py_source)

        namespace: dict = {}
        exec(py_source, namespace)
        fox_instance = namespace["run_fox_program"]()
        self.assertEqual(fox_instance.eval_expr("lnSumaPy"), 100)

    def test_sql_views_and_requery(self) -> None:
        self.interp.execute(
            """
            CREATE CURSOR empleados_v (id I, nombre C(30), depto C(20), salario I)
            INSERT INTO empleados_v VALUES (1, "Ana", "IT", 3500)
            INSERT INTO empleados_v VALUES (2, "Luis", "Ventas", 2800)
            INSERT INTO empleados_v VALUES (3, "Marta", "IT", 4200)

            vp_depto = "IT"
            CREATE SQL VIEW v_por_depto AS SELECT * FROM empleados_v WHERE depto = ?vp_depto
            lnCountIT = RECCOUNT("v_por_depto")

            vp_depto = "Ventas"
            =REQUERY("v_por_depto")
            lnCountVentas = RECCOUNT("v_por_depto")
            """
        )
        self.assertEqual(self.interp.eval_expr("lnCountIT"), 2)
        self.assertEqual(self.interp.eval_expr("lnCountVentas"), 1)
        self.assertEqual(self.interp.eval_expr("v_por_depto.nombre"), "Luis")

    def test_system_file_and_adir_functions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sample_file = Path(tmpdir) / "reporte_anual.txt"
            self.interp.set_var("lcRutaArchivo", str(sample_file))
            self.interp.set_var("lcMascara", f"{tmpdir}/*.txt")
            self.interp.execute(
                """
                =STRTOFILE("Linea 1 - FoxNext", lcRutaArchivo)
                lcLeido = FILETOSTR(lcRutaArchivo)
                lcNombre = JUSTFNAME(lcRutaArchivo)
                lcStem = JUSTSTEM(lcRutaArchivo)
                lcExt = JUSTEXT(lcRutaArchivo)
                lcNuevaExt = FORCEEXT(lcRutaArchivo, "bak")
                lcUnico = SYS(2015)
                lnTotalArchivos = ADIR(laDirInfo, lcMascara)
                lcPrimerArchivo = laDirInfo[1, 1]
                """
            )
            self.assertEqual(self.interp.eval_expr("lcLeido"), "Linea 1 - FoxNext")
            self.assertEqual(self.interp.eval_expr("lcNombre"), "reporte_anual.txt")
            self.assertEqual(self.interp.eval_expr("lcStem"), "reporte_anual")
            self.assertEqual(self.interp.eval_expr("lcExt"), "txt")
            self.assertTrue(str(self.interp.eval_expr("lcNuevaExt")).endswith(".bak"))
            self.assertTrue(str(self.interp.eval_expr("lcUnico")).startswith("_"))
            self.assertEqual(self.interp.eval_expr("lnTotalArchivos"), 1)
            self.assertEqual(self.interp.eval_expr("lcPrimerArchivo"), "reporte_anual.txt")

    def test_foxmenu_and_xbase_menu_commands(self) -> None:
        self.interp.execute(
            """
            lnAccionEjecutada = 0
            DEFINE MENU mnuPrincipal
            DEFINE PAD padArchivo OF mnuPrincipal PROMPT "Archivo"
            ON PAD padArchivo OF mnuPrincipal ACTIVATE POPUP popArchivo
            DEFINE POPUP popArchivo
            DEFINE BAR 1 OF popArchivo PROMPT "Nuevo Documento"
            DEFINE BAR 2 OF popArchivo PROMPT "Cerrar Sesión"
            ON SELECTION BAR 1 OF popArchivo lnAccionEjecutada = 101
            ON SELECTION BAR 2 OF popArchivo lnAccionEjecutada = 202

            ACTIVATE POPUP popArchivo BAR 1
            """
        )
        self.assertEqual(self.interp.eval_expr("lnAccionEjecutada"), 101)
        menu_obj = self.interp.menus["mnuprincipal"]
        tui_str = menu_obj.render_tui()
        html_str = menu_obj.render_html()
        self.assertIn("Nuevo Documento", tui_str)
        self.assertIn("foxmenu-bar", html_str)

    def test_docgen_markdown_generation(self) -> None:
        from modern_vfp.docgen import generate_prg_docs

        sample_prg = """
        CREATE CURSOR facturas (id I, cliente C(40), total Y)
        CREATE SQL VIEW v_altas AS SELECT * FROM facturas WHERE total > 1000

        DEFINE CLASS ServicioFacturacion AS Custom
            Impuesto = 0.16
            FUNCTION EmitirFactura(tnId, tcCliente)
                RETURN .T.
            ENDFUNC
        ENDDEFINE

        FUNCTION FormatearMoneda(tnMonto)
            RETURN TRANSFORM(tnMonto)
        ENDFUNC
        """
        md = generate_prg_docs(sample_prg, title="Manual de Facturación")
        self.assertIn("# Manual de Facturación", md)
        self.assertIn("Cursor `facturas`", md)
        self.assertIn("`v_altas`", md)
        self.assertIn("Clase `serviciofacturacion`", md)
        self.assertIn("`formatearmoneda(tnmonto)`", md)

    def test_cursor_adapter_object(self) -> None:
        self.interp.execute(
            """
            CREATE CURSOR articulos_orig (id I, descrip C(30), costo N(10,2))
            INSERT INTO articulos_orig VALUES (1, "Teclado", 45.50)
            INSERT INTO articulos_orig VALUES (2, "Mouse", 20.00)

            loCA = CREATEOBJECT("CursorAdapter")
            loCA.Alias = "articulos_ca"
            loCA.SelectCmd = "SELECT * FROM articulos_orig WHERE costo > 25"
            loCA.CursorSchema = "id I, descrip C(30), costo N(10,2)"
            llOk = loCA.CursorFill(.T.)
            lnRegs = RECCOUNT("articulos_ca")
            lcArticulo = articulos_ca.descrip

            llDetached = loCA.CursorDetach()
            """
        )
        self.assertTrue(self.interp.eval_expr("llOk"))
        self.assertEqual(self.interp.eval_expr("lnRegs"), 1)
        self.assertEqual(self.interp.eval_expr("lcArticulo"), "Teclado")
        self.assertTrue(self.interp.eval_expr("llDetached"))

    def test_xml_cursor_interchange(self) -> None:
        self.interp.execute(
            """
            CREATE CURSOR productos_xml (id I, nombre C(30), precio N(8,2), disponible L)
            INSERT INTO productos_xml VALUES (101, "Monitor 4K", 399.99, .T.)
            INSERT INTO productos_xml VALUES (102, "Cable HDMI", 12.50, .F.)

            lcXmlGenerado = CURSORTOXML("productos_xml")
            lnRecsCargados = XMLTOCURSOR(lcXmlGenerado, "productos_desde_xml")
            lnTotalXML = RECCOUNT("productos_desde_xml")
            lcNombreP1 = productos_desde_xml.nombre
            llDispP1 = productos_desde_xml.disponible
            """
        )
        self.assertIn("<VFPData>", str(self.interp.eval_expr("lcXmlGenerado")))
        self.assertEqual(self.interp.eval_expr("lnRecsCargados"), 2)
        self.assertEqual(self.interp.eval_expr("lnTotalXML"), 2)
        self.assertEqual(self.interp.eval_expr("lcNombreP1"), "Monitor 4K")
        self.assertTrue(self.interp.eval_expr("llDispP1"))

    def test_on_error_and_aerror(self) -> None:
        self.interp.execute(
            """
            lnErrorCapturado = 0
            ON ERROR lnErrorCapturado = ERROR()

            ERROR 1502
            =AERROR(laInfoError)
            lnCodErrorArr = laInfoError[1]
            """
        )
        self.assertEqual(self.interp.eval_expr("lnErrorCapturado"), 1502)
        self.assertEqual(self.interp.eval_expr("lnCodErrorArr"), 1502)

        # Probar limpieza de ON ERROR
        self.interp.execute("ON ERROR")
        self.assertIsNone(self.interp.on_error_cmd)

    def test_fox_profiler(self) -> None:
        from modern_vfp.profiler import FoxProfiler

        profiler = FoxProfiler(self.interp)
        sample_code = """
        x = 10
        y = 20
        z = x + y
        """
        stats = profiler.run(sample_code)
        self.assertGreaterEqual(stats["totalTimeMs"], 0.0)
        self.assertEqual(stats["executedLines"], 3)
        self.assertEqual(stats["coveragePct"], 100.0)
        rep = profiler.render_report()
        self.assertIn("FOXNEXT PROFILER REPORT", rep)

    def test_fxp_bytecode_compilation_and_execution(self) -> None:
        from modern_vfp.compiler import compile_file, load_compiled_program

        with tempfile.TemporaryDirectory() as tmpdir:
            prg_file = Path(tmpdir) / "test_calc.prg"
            fxp_file = Path(tmpdir) / "test_calc.fxp"
            prg_file.write_text(
                """
                FUNCTION Multiplicar(a, b)
                    RETURN a * b
                ENDFUNC
                lnResultadoFXP = Multiplicar(6, 7)
                """,
                encoding="utf-8",
            )
            compile_file(prg_file, fxp_file)
            self.assertTrue(fxp_file.is_file())
            info = load_compiled_program(fxp_file)
            self.assertEqual(info["version"], "0.9.0")
            self.assertIn("multiplicar", info["procedures"])

            # Ejecutar con DO <archivo.fxp>
            self.interp.execute(f"DO '{fxp_file}'")
            self.assertEqual(self.interp.eval_expr("lnResultadoFXP"), 42)

    def test_rushmore_indexed_query_optimization(self) -> None:
        self.interp.execute(
            """
            CREATE CURSOR empleados_rush (id I, depto C(10), sueldo I)
            INSERT INTO empleados_rush VALUES (1, "IT", 3000)
            INSERT INTO empleados_rush VALUES (2, "VENTAS", 2000)
            INSERT INTO empleados_rush VALUES (3, "IT", 4000)
            INSERT INTO empleados_rush VALUES (4, "RRHH", 2500)
            INSERT INTO empleados_rush VALUES (5, "IT", 3500)

            INDEX ON depto TAG tag_depto
            lnTotalIT = 0
            SCAN FOR depto == "IT"
                lnTotalIT = lnTotalIT + 1
            ENDSCAN
            """
        )
        self.assertEqual(self.interp.eval_expr("lnTotalIT"), 3)
        opt_info = self.interp.rushmore.last_optimization
        self.assertEqual(opt_info["level"], "Full")
        self.assertEqual(opt_info["alias"], "empleados_rush")

    def test_dbc_database_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dbc_path = Path(tmpdir) / "ventas_corp.dbc"
            self.interp.execute(
                f"""
                CREATE DATABASE '{dbc_path}'
                ADD TABLE clientes_db TO DATABASE
                VALIDATE DATABASE
                CLOSE DATABASES
                """
            )
            self.assertTrue(dbc_path.is_file())
            from modern_vfp.dbc import FoxDatabase

            db = FoxDatabase.load(dbc_path)
            self.assertIn("clientes_db", db.tables)
            db.set_field_rule("clientes_db", "saldo", "saldo >= 0", "Saldo no puede ser negativo")
            db.add_relation("clientes_db", "facturas_db", "id", "tag_cliente")
            val_res = db.validate_database()
            self.assertFalse(val_res["isValid"])  # facturas_db aún no agregada
            db.add_table("facturas_db")
            self.assertTrue(db.validate_database()["isValid"])

    def test_parquet_columnar_export_and_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pq_file = Path(tmpdir) / "datos.parquet"
            self.interp.execute(
                f"""
                CREATE CURSOR orig_pq (id I, producto C(25), precio N(10,2), activo L)
                INSERT INTO orig_pq VALUES (1, "Laptop Pro", 1299.50, .T.)
                INSERT INTO orig_pq VALUES (2, "Mouse USB", 25.00, .F.)

                COPY TO '{pq_file}' TYPE PARQUET

                CREATE CURSOR dest_pq (id I, producto C(25), precio N(10,2), activo L)
                APPEND FROM '{pq_file}' TYPE PARQUET
                lnDestRecs = RECCOUNT("dest_pq")
                lcProd1 = dest_pq.producto
                llActivo1 = dest_pq.activo
                """
            )
            self.assertTrue(pq_file.is_file())
            self.assertEqual(self.interp.eval_expr("lnDestRecs"), 2)
            self.assertEqual(self.interp.eval_expr("lcProd1"), "Laptop Pro")
            self.assertTrue(self.interp.eval_expr("llActivo1"))

    def test_build_standalone_exe_and_project_exe(self) -> None:
        from modern_vfp.project import build_standalone_exe

        with tempfile.TemporaryDirectory() as tmpdir:
            src_prg = Path(tmpdir) / "app_calculo.prg"
            out_exe = Path(tmpdir) / "app_calculo_bin"
            src_prg.write_text(
                """
                x = 100
                y = 250
                z = x + y
                ? 'Calculado: ' + TRANSFORM(z)
                """,
                encoding="utf-8",
            )
            built = build_standalone_exe(src_prg, out_exe)
            self.assertTrue(built.is_file())
            content = built.read_text(encoding="utf-8")
            self.assertIn("#!/usr/bin/env python3", content)
            self.assertIn("FoxInterpreter", content)

    def test_erp_demo_suite_integration(self) -> None:
        erp_dir = Path(__file__).parent.parent / "examples" / "erp_demo"
        schema_prg = erp_dir / "schema.prg"
        main_prg = erp_dir / "main.prg"
        self.assertTrue(schema_prg.is_file())
        self.assertTrue(main_prg.is_file())

        # Ejecutar la suite de demostración completa
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_cwd = Path.cwd()
            try:
                import os

                os.chdir(tmpdir)
                demo_interp = self.interp
                # Copiar assets
                for f in erp_dir.iterdir():
                    if f.is_file():
                        (Path(tmpdir) / f.name).write_bytes(f.read_bytes())
                demo_interp.execute((Path(tmpdir) / "main.prg").read_text(encoding="utf-8"))
                self.assertEqual(demo_interp.eval_expr("lnPendientesRush"), 2)
                self.assertTrue((Path(tmpdir) / "facturas_export.parquet").is_file())
            finally:
                os.chdir(orig_cwd)


if __name__ == "__main__":
    unittest.main()


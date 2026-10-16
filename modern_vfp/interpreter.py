"""
Intérprete y Evaluador del Lenguaje FoxNext (Modern VFP).
Soporta programación estructurada, orientación a objetos (DEFINE CLASS / CREATEOBJECT),
manipulación directa de cursores y SQL relacional embebido.
"""

from __future__ import annotations
import datetime
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .cursor import Cursor, FieldDef, WorkAreaManager, parse_schema_string
from .dbf import export_csv, export_json, import_csv, import_json, read_dbf, write_dbf
from .functions import build_vfp_functions
from .migrator import migrate_scx_to_foxform


class _LoopExit(Exception):
    pass


class _LoopContinue(Exception):
    pass


class _ReturnSignal(Exception):
    def __init__(self, value: Any = None):
        self.value = value


class VFPObject:
    """
    Instancia de una clase definida con DEFINE CLASS o CREATEOBJECT("Empty").
    """

    def __init__(self, class_name: str, properties: Dict[str, Any], methods: Dict[str, Tuple[List[str], List[str]]], interpreter: "FoxInterpreter"):
        self.__vfp_class__ = class_name
        self._props: Dict[str, Any] = {k.lower(): v for k, v in properties.items()}
        self._methods = methods
        self._interp = interpreter

    def get_prop(self, name: str) -> Any:
        nl = name.lower()
        if nl == "class":
            return self.__vfp_class__
        return self._props.get(nl)

    def set_prop(self, name: str, value: Any) -> None:
        self._props[name.lower()] = value

    def call_method(self, name: str, *args: Any) -> Any:
        nl = name.lower()
        if nl not in self._methods:
            raise AttributeError(f"El método '{name}' no existe en la clase '{self.__vfp_class__}'")
        params, body = self._methods[nl]
        return self._interp._invoke_Routine(params, body, list(args), this_obj=self)

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_"):
            raise AttributeError(item)
        nl = item.lower()
        if nl in self._methods:
            return lambda *a: self.call_method(nl, *a)
        if nl in self._props:
            return self._props[nl]
        raise AttributeError(f"Propiedad o método '{item}' no encontrado en '{self.__vfp_class__}'")

    def __repr__(self) -> str:
        return f"<Object:{self.__vfp_class__} {self._props}>"


class _AliasProxy:
    """
    Permite resolver expresiones del tipo `clientes.nombre` o `THIS.propiedad` dentro del evaluador.
    """

    def __init__(self, cursor: Cursor):
        self._cursor = cursor

    def __getattr__(self, item: str) -> Any:
        return self._cursor.get_field(item)


class _MemoryProxy:
    """
    Permite resolver explícitamente variables de memoria con el prefijo `m.variable`.
    """

    def __init__(self, env: Dict[str, Any]):
        self._env = env

    def __getattr__(self, item: str) -> Any:
        kl = item.lower()
        if kl in self._env:
            return self._env[kl]
        raise NameError(f"Variable de memoria 'm.{item}' no encontrada.")


class _EvalNamespace(dict):
    """
    Espacio de nombres dinámico e insensible a mayúsculas/minúsculas que implementa
    la jerarquía de resolución de Visual FoxPro:
    1. Funciones nativas y de usuario
    2. Alias abiertos (`clientes.campo`) y `m.variable`
    3. Campos del cursor activo (`SELECT()`)
    4. Variables de memoria locales/privadas/públicas
    """

    def __init__(self, interp: "FoxInterpreter"):
        super().__init__()
        self.interp = interp

    def __getitem__(self, key: str) -> Any:
        kl = key.lower()
        if kl in ("true", "false", "none", "__builtins__"):
            return {"true": True, "false": False, "none": None, "__builtins__": {}}[kl]

        # 1. Palabras reservadas de objetos
        if kl == "this" and self.interp._this_stack:
            return self.interp._this_stack[-1]
        if kl == "m":
            return _MemoryProxy(self.interp.current_vars())

        # 2. Funciones nativas o procedimientos de usuario
        if kl in self.interp.functions:
            return self.interp.functions[kl]
        if kl in self.interp.procedures:
            params, body = self.interp.procedures[kl]
            return lambda *a: self.interp._invoke_Routine(params, body, list(a))

        # 3. Campo del cursor activo (prioridad de VFP sobre variables sin m.)
        cur = self.interp.wam.current_cursor()
        if cur and kl in cur.field_map:
            return cur.get_field(kl)

        # 4. Alias de otro cursor abierto (para `clientes.nombre`)
        other_cur = self.interp.wam.get_cursor(kl)
        if other_cur is not None:
            return _AliasProxy(other_cur)

        # 5. Variables de memoria (alcance local -> global)
        env = self.interp.current_vars()
        if kl in env:
            return env[kl]

        raise NameError(f"No se encontró la variable o campo '{key}'.")


class FoxInterpreter:
    """
    Motor de ejecución de código FoxNext / Modern VFP.
    """

    def __init__(self, output_callback: Optional[Callable[[str, bool], None]] = None):
        self.wam = WorkAreaManager()
        self.functions = build_vfp_functions(self.wam)
        self.functions["createobject"] = self.create_object
        self.functions["evaluate"] = self.eval_expr
        self.functions["sqlexec"] = self.sql_exec

        self.global_vars: Dict[str, Any] = {}
        self.call_stack: List[Dict[str, Any]] = []
        self._this_stack: List[VFPObject] = []

        # Procedimientos / Funciones definidas por el usuario: name -> (params, body_lines)
        self.procedures: Dict[str, Tuple[List[str], List[str]]] = {}
        # Clases definidas con DEFINE CLASS: name -> (parent, props_lines, methods_dict)
        self.classes: Dict[str, Tuple[str, List[str], Dict[str, Tuple[List[str], List[str]]]]] = {}

        self.output_buffer: List[str] = []
        self._output_cb = output_callback

    def sql_exec(self, handle: int, sql_stmt: str, cursor_name: str = "sqlresult") -> int:
        return self.wam.sql_exec(handle, sql_stmt, cursor_name, self.current_vars())

    def emit(self, text: str, newline: bool = True) -> None:
        if self._output_cb:
            self._output_cb(text, newline)
        if newline:
            self.output_buffer.append(text)
        else:
            if self.output_buffer:
                self.output_buffer[-1] += text
            else:
                self.output_buffer.append(text)

    def current_vars(self) -> Dict[str, Any]:
        merged = dict(self.global_vars)
        if self.call_stack:
            merged.update(self.call_stack[-1])
        return merged

    def set_var(self, name: str, val: Any, scope: str = "auto") -> None:
        nl = name.strip().lower()
        if nl.startswith("m."):
            nl = nl[2:]

        # Soporte para THIS.propiedad = valor
        if nl.startswith("this.") and self._this_stack:
            prop_name = nl.split(".", 1)[1]
            self._this_stack[-1].set_prop(prop_name, val)
            return

        # Soporte para obj.propiedad = valor
        if "." in nl:
            obj_name, prop_name = nl.split(".", 1)
            env = self.current_vars()
            target = env.get(obj_name)
            if isinstance(target, VFPObject):
                target.set_prop(prop_name, val)
                return
            if isinstance(target, dict):
                target[prop_name] = val
                return

        if scope == "local" and self.call_stack:
            self.call_stack[-1][nl] = val
        elif scope == "public":
            self.global_vars[nl] = val
        else:
            if self.call_stack and nl in self.call_stack[-1]:
                self.call_stack[-1][nl] = val
            elif self.call_stack:
                self.call_stack[-1][nl] = val
            else:
                self.global_vars[nl] = val

    def create_object(self, class_name: str, *args: Any) -> VFPObject:
        cl = class_name.strip().lower()
        if cl == "empty":
            return VFPObject("Empty", {}, {}, self)
        if cl not in self.classes:
            raise ValueError(f"La clase '{class_name}' no está definida.")
        parent, prop_lines, methods = self.classes[cl]
        obj = VFPObject(class_name, {}, methods, self)
        self._this_stack.append(obj)
        try:
            for pline in prop_lines:
                if "=" in pline:
                    k, v_expr = pline.split("=", 1)
                    obj.set_prop(k.strip(), self.eval_expr(v_expr.strip()))
            if "init" in methods:
                obj.call_method("init", *args)
        finally:
            self._this_stack.pop()
        return obj

    # -------------------------------------------------------------------------
    # Traducción y Evaluación de Expresiones VFP
    # -------------------------------------------------------------------------
    def _translate_vfp_expr(self, expr: str) -> str:
        """
        Convierte una expresión en sintaxis VFP a una expresión evaluable en Python,
        protegiendo literales de cadena y transformando operadores y literales FoxPro.
        """
        strings: List[str] = []

        def _save_str(s: str) -> str:
            idx = len(strings)
            strings.append(s)
            return f"__STR_LIT_{idx}__"

        # Extraer literales de fecha {^YYYY-MM-DD} o {^YYYY-MM-DD HH:MM:SS}
        def _replace_date(m: re.Match) -> str:
            inner = m.group(1).strip().lstrip("^").strip()
            if not inner:
                return "None"
            parts = re.split(r"[-/\s:]+", inner)
            if len(parts) >= 6:
                return f"datetime({int(parts[0])}, {int(parts[1])}, {int(parts[2])}, {int(parts[3])}, {int(parts[4])}, {int(parts[5])})"
            if len(parts) >= 3:
                return f"date({int(parts[0])}, {int(parts[1])}, {int(parts[2])})"
            return "None"

        s = re.sub(r"\{\s*(\^?[0-9/\-:\s]*)\}", _replace_date, expr)

        # Extraer cadenas delimitadas por "...", '...'
        out_chars: List[str] = []
        i = 0
        n = len(s)
        while i < n:
            ch = s[i]
            if ch in ('"', "'"):
                quote = ch
                j = i + 1
                buf = []
                while j < n and s[j] != quote:
                    if s[j] == "\\" and j + 1 < n:
                        buf.append(s[j : j + 2])
                        j += 2
                    else:
                        buf.append(s[j])
                        j += 1
                lit = quote + "".join(buf) + quote
                out_chars.append(_save_str(lit))
                i = j + 1
            else:
                out_chars.append(ch)
                i += 1
        s = "".join(out_chars)

        # Reemplazar flecha de alias `alias->campo` por `alias.campo`
        s = s.replace("->", ".")

        # Literales lógicos y nulos de VFP
        s = re.sub(r"\.(?:T|Y)\.", " True ", s, flags=re.IGNORECASE)
        s = re.sub(r"\.(?:F|N)\.", " False ", s, flags=re.IGNORECASE)
        s = re.sub(r"\.NULL\.", " None ", s, flags=re.IGNORECASE)

        # Operadores lógicos VFP
        s = re.sub(r"\.AND\.|\bAND\b", " and ", s, flags=re.IGNORECASE)
        s = re.sub(r"\.OR\.|\bOR\b", " or ", s, flags=re.IGNORECASE)
        s = re.sub(r"\.NOT\.|\bNOT\b", " not ", s, flags=re.IGNORECASE)

        # Operador de desigualdad <> y #
        s = s.replace("<>", "!=")
        s = re.sub(r"(?<![A-Za-z0-9_])#(?![A-Za-z0-9_])", "!=", s)

        # Operador de potencia ^ -> **
        s = s.replace("^", "**")

        # Operador ! como NOT unario (pero sin romper !=)
        s = re.sub(r"!(?!=)", " not ", s)

        # Operador de comparación = simple a == en expresiones booleanas
        s = re.sub(r"(?<![=!<>])=(?!=)", "==", s)

        # Operador $ (subcadena contenida en cadena: "a" $ "abc" -> ("a" in "abc"))
        s = re.sub(r"\$", " in ", s)

        # Restaurar literales de cadena
        for idx, lit in enumerate(strings):
            s = s.replace(f"__STR_LIT_{idx}__", lit)

        return s

    def eval_expr(self, expr: str) -> Any:
        clean = expr.strip()
        if not clean:
            return None
        # Sustitución de macros &lcVar si existe
        clean = self._expand_macros(clean)
        py_expr = self._translate_vfp_expr(clean)
        ns = _EvalNamespace(self)
        return eval(py_expr, {"__builtins__": {}}, ns)

    def _expand_macros(self, line: str) -> str:
        """
        Expande variables precedidas por `&` (Macro Substitution de VFP: `&lcFiltro`).
        """
        if "&" not in line:
            return line
        env = self.current_vars()

        def _repl(m: re.Match) -> str:
            var_name = m.group(1).lower()
            if var_name in env:
                return str(env[var_name])
            return m.group(0)

        return re.sub(r"&([A-Za-z_][A-Za-z0-9_]*)\.? ?", _repl, line)

    # -------------------------------------------------------------------------
    # Preprocesador de Líneas (Continuación `;` y Comentarios `*`, `&&`, `NOTE`)
    # -------------------------------------------------------------------------
    def preprocess_code(self, source: str) -> List[str]:
        raw_lines = source.splitlines()
        logical_lines: List[str] = []
        buffer = ""

        for raw in raw_lines:
            # Eliminar comentarios inline && fuera de comillas
            line = self._strip_inline_comment(raw).strip()
            if not line:
                continue
            if line.startswith("*") or re.match(r"^NOTE\b", line, flags=re.IGNORECASE):
                continue

            if line.endswith(";"):
                buffer += line[:-1].rstrip() + " "
            else:
                full_line = (buffer + line).strip()
                buffer = ""
                if full_line:
                    logical_lines.append(full_line)

        if buffer.strip():
            logical_lines.append(buffer.strip())

        return logical_lines

    @staticmethod
    def _strip_inline_comment(line: str) -> str:
        in_quote: Optional[str] = None
        i = 0
        n = len(line)
        while i < n:
            ch = line[i]
            if in_quote:
                if ch == in_quote:
                    in_quote = None
            else:
                if ch in ('"', "'"):
                    in_quote = ch
                elif ch == "&" and i + 1 < n and line[i + 1] == "&":
                    return line[:i]
            i += 1
        return line

    # -------------------------------------------------------------------------
    # Ejecución de Bloques y Estructuras de Control
    # -------------------------------------------------------------------------
    def execute(self, source: str) -> Any:
        lines = self.preprocess_code(source)
        self._register_top_level_definitions(lines)
        try:
            return self._exec_block(lines)
        except _ReturnSignal as ret:
            return ret.value

    def _register_top_level_definitions(self, lines: List[str]) -> None:
        """
        Escanea y registra bloques PROCEDURE/FUNCTION y DEFINE CLASS antes de ejecutar.
        """
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            m_proc = re.match(
                r"^(?:PROCEDURE|FUNCTION)\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*\((.*?)\))?",
                line,
                flags=re.IGNORECASE,
            )
            if m_proc:
                name = m_proc.group(1).lower()
                inline_params = m_proc.group(2)
                params: List[str] = []
                if inline_params:
                    params = [p.strip().lower() for p in inline_params.split(",") if p.strip()]
                body: List[str] = []
                i += 1
                while i < n and not re.match(r"^(?:ENDPROC|ENDFUNC)\b", lines[i], flags=re.IGNORECASE):
                    m_lparam = re.match(r"^(?:LPARAMETERS|PARAMETERS)\s+(.*)$", lines[i], flags=re.IGNORECASE)
                    if m_lparam and not params:
                        params = [p.strip().lower() for p in m_lparam.group(1).split(",") if p.strip()]
                    else:
                        body.append(lines[i])
                    i += 1
                self.procedures[name] = (params, body)
                i += 1
                continue

            m_cls = re.match(
                r"^DEFINE\s+CLASS\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS\s+([A-Za-z_][A-Za-z0-9_]*)",
                line,
                flags=re.IGNORECASE,
            )
            if m_cls:
                cls_name = m_cls.group(1).lower()
                parent_name = m_cls.group(2).lower()
                prop_lines: List[str] = []
                methods: Dict[str, Tuple[List[str], List[str]]] = {}
                i += 1
                while i < n and not re.match(r"^ENDDEFINE\b", lines[i], flags=re.IGNORECASE):
                    m_mth = re.match(
                        r"^(?:PROCEDURE|FUNCTION)\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*\((.*?)\))?",
                        lines[i],
                        flags=re.IGNORECASE,
                    )
                    if m_mth:
                        mname = m_mth.group(1).lower()
                        mparams: List[str] = []
                        if m_mth.group(2):
                            mparams = [p.strip().lower() for p in m_mth.group(2).split(",") if p.strip()]
                        mbody: List[str] = []
                        i += 1
                        while i < n and not re.match(r"^(?:ENDPROC|ENDFUNC)\b", lines[i], flags=re.IGNORECASE):
                            m_lp = re.match(r"^(?:LPARAMETERS|PARAMETERS)\s+(.*)$", lines[i], flags=re.IGNORECASE)
                            if m_lp and not mparams:
                                mparams = [p.strip().lower() for p in m_lp.group(1).split(",") if p.strip()]
                            else:
                                mbody.append(lines[i])
                            i += 1
                        methods[mname] = (mparams, mbody)
                    else:
                        prop_lines.append(lines[i])
                    i += 1
                self.classes[cls_name] = (parent_name, prop_lines, methods)
                i += 1
                continue

            i += 1

    def _invoke_Routine(
        self,
        params: List[str],
        body: List[str],
        args: List[Any],
        this_obj: Optional[VFPObject] = None,
    ) -> Any:
        frame: Dict[str, Any] = {}
        for idx, pname in enumerate(params):
            frame[pname] = args[idx] if idx < len(args) else False
        self.call_stack.append(frame)
        if this_obj is not None:
            self._this_stack.append(this_obj)
        try:
            self._exec_block(body)
            return True
        except _ReturnSignal as ret:
            return ret.value
        finally:
            if this_obj is not None:
                self._this_stack.pop()
            self.call_stack.pop()

    def _exec_block(self, lines: List[str]) -> Any:
        i = 0
        n = len(lines)
        while i < n:
            line = self._expand_macros(lines[i]).strip()
            if not line:
                i += 1
                continue

            # Saltar bloques PROCEDURE / FUNCTION / DEFINE CLASS ya registrados
            if re.match(r"^(?:PROCEDURE|FUNCTION)\s+", line, flags=re.IGNORECASE):
                i += 1
                while i < n and not re.match(r"^(?:ENDPROC|ENDFUNC)\b", lines[i], flags=re.IGNORECASE):
                    i += 1
                i += 1
                continue

            if re.match(r"^DEFINE\s+CLASS\s+", line, flags=re.IGNORECASE):
                i += 1
                while i < n and not re.match(r"^ENDDEFINE\b", lines[i], flags=re.IGNORECASE):
                    i += 1
                i += 1
                continue

            # Estructura IF ... ELSEIF ... ELSE ... ENDIF
            if re.match(r"^IF\b", line, flags=re.IGNORECASE):
                end_idx, branches, else_block = self._collect_if_block(lines, i)
                executed = False
                for cond_expr, blk in branches:
                    if bool(self.eval_expr(cond_expr)):
                        self._exec_block(blk)
                        executed = True
                        break
                if not executed and else_block is not None:
                    self._exec_block(else_block)
                i = end_idx + 1
                continue

            # Estructura DO CASE ... CASE ... OTHERWISE ... ENDCASE
            if re.match(r"^DO\s+CASE\b", line, flags=re.IGNORECASE):
                end_idx, cases, otherwise_blk = self._collect_case_block(lines, i)
                executed = False
                for cond_expr, blk in cases:
                    if bool(self.eval_expr(cond_expr)):
                        self._exec_block(blk)
                        executed = True
                        break
                if not executed and otherwise_blk is not None:
                    self._exec_block(otherwise_blk)
                i = end_idx + 1
                continue

            # Estructura DO WHILE ... ENDDO
            m_while = re.match(r"^DO\s+WHILE\s+(.*)$", line, flags=re.IGNORECASE)
            if m_while:
                cond_expr = m_while.group(1).strip()
                end_idx, body = self._collect_delimited_block(lines, i, r"^DO\s+WHILE\b", r"^ENDDO\b")
                while bool(self.eval_expr(cond_expr)):
                    try:
                        self._exec_block(body)
                    except _LoopContinue:
                        continue
                    except _LoopExit:
                        break
                i = end_idx + 1
                continue

            # Estructura FOR var = start TO end [STEP s] ... ENDFOR / NEXT
            m_for = re.match(
                r"^FOR\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s+TO\s+(.+?)(?:\s+STEP\s+(.+))?$",
                line,
                flags=re.IGNORECASE,
            )
            if m_for:
                var_name = m_for.group(1)
                start_val = self.eval_expr(m_for.group(2))
                end_val = self.eval_expr(m_for.group(3))
                step_val = self.eval_expr(m_for.group(4)) if m_for.group(4) else 1
                end_idx, body = self._collect_delimited_block(lines, i, r"^FOR\b", r"^(?:ENDFOR|NEXT)\b")

                cur_val = start_val
                self.set_var(var_name, cur_val)
                while (step_val >= 0 and cur_val <= end_val) or (step_val < 0 and cur_val >= end_val):
                    try:
                        self._exec_block(body)
                    except _LoopContinue:
                        pass
                    except _LoopExit:
                        break
                    cur_val = self.eval_expr(var_name) + step_val
                    self.set_var(var_name, cur_val)
                i = end_idx + 1
                continue

            # Estructura SCAN [FOR expr] ... ENDSCAN
            m_scan = re.match(r"^SCAN(?:\s+FOR\s+(.*))?$", line, flags=re.IGNORECASE)
            if m_scan:
                for_expr = m_scan.group(1).strip() if m_scan.group(1) else None
                end_idx, body = self._collect_delimited_block(lines, i, r"^SCAN\b", r"^ENDSCAN\b")
                cur = self.wam.current_cursor()
                if cur is None:
                    raise RuntimeError("SCAN ejecutado sin ningún cursor activo en el área de trabajo.")
                scan_area = self.wam.current_area
                vis_recnos = list(cur.visible_recnos(self.wam.set_deleted))
                for r in vis_recnos:
                    self.wam.current_area = scan_area
                    cur.goto(r)
                    self.wam.sync_relations(self.eval_expr)
                    if for_expr and not bool(self.eval_expr(for_expr)):
                        continue
                    try:
                        self._exec_block(body)
                    except _LoopContinue:
                        continue
                    except _LoopExit:
                        break
                self.wam.current_area = scan_area
                cur._recno = len(cur.records) + 1
                cur.eof = True
                i = end_idx + 1
                continue

            # Estructura TRY ... CATCH ... FINALLY ... ENDTRY
            if re.match(r"^TRY\b", line, flags=re.IGNORECASE):
                end_idx, try_blk, catch_var, catch_blk, finally_blk = self._collect_try_block(lines, i)
                try:
                    self._exec_block(try_blk)
                except (_ReturnSignal, _LoopExit, _LoopContinue):
                    raise
                except Exception as exc:
                    if catch_blk is not None:
                        if catch_var:
                            err_obj = VFPObject("Exception", {"message": str(exc), "errorno": 1098}, {}, self)
                            self.set_var(catch_var, err_obj)
                        self._exec_block(catch_blk)
                    else:
                        raise
                finally:
                    if finally_blk is not None:
                        self._exec_block(finally_blk)
                i = end_idx + 1
                continue

            # Ejecutar sentencia individual
            self._exec_statement(line)
            i += 1
        return None

    def _collect_delimited_block(
        self, lines: List[str], start_idx: int, open_pat: str, close_pat: str
    ) -> Tuple[int, List[str]]:
        depth = 0
        body: List[str] = []
        i = start_idx
        n = len(lines)
        while i < n:
            ln = lines[i].strip()
            if re.match(open_pat, ln, flags=re.IGNORECASE):
                if depth > 0:
                    body.append(lines[i])
                depth += 1
            elif re.match(close_pat, ln, flags=re.IGNORECASE):
                depth -= 1
                if depth == 0:
                    return i, body
                body.append(lines[i])
            else:
                body.append(lines[i])
            i += 1
        raise SyntaxError(f"Bloque sin cerrar (se esperaba {close_pat}) iniciado en: {lines[start_idx]}")

    def _collect_if_block(
        self, lines: List[str], start_idx: int
    ) -> Tuple[int, List[Tuple[str, List[str]]], Optional[List[str]]]:
        first_cond = re.sub(r"^IF\s+", "", lines[start_idx].strip(), flags=re.IGNORECASE)
        first_cond = re.sub(r"\s+THEN$", "", first_cond, flags=re.IGNORECASE).strip()

        branches: List[Tuple[str, List[str]]] = []
        cur_cond: Optional[str] = first_cond
        cur_blk: List[str] = []
        else_blk: Optional[List[str]] = None

        depth = 1
        i = start_idx + 1
        n = len(lines)
        while i < n:
            ln = lines[i].strip()
            if re.match(r"^IF\b", ln, flags=re.IGNORECASE):
                depth += 1
                if else_blk is not None:
                    else_blk.append(lines[i])
                else:
                    cur_blk.append(lines[i])
            elif re.match(r"^ENDIF\b", ln, flags=re.IGNORECASE):
                depth -= 1
                if depth == 0:
                    if cur_cond is not None:
                        branches.append((cur_cond, cur_blk))
                    return i, branches, else_blk
                if else_blk is not None:
                    else_blk.append(lines[i])
                else:
                    cur_blk.append(lines[i])
            elif depth == 1 and re.match(r"^ELSEIF\b", ln, flags=re.IGNORECASE):
                if cur_cond is not None:
                    branches.append((cur_cond, cur_blk))
                cur_cond = re.sub(r"^ELSEIF\s+", "", ln, flags=re.IGNORECASE).strip()
                cur_blk = []
            elif depth == 1 and re.match(r"^ELSE\b", ln, flags=re.IGNORECASE):
                if cur_cond is not None:
                    branches.append((cur_cond, cur_blk))
                    cur_cond = None
                else_blk = []
            else:
                if else_blk is not None:
                    else_blk.append(lines[i])
                else:
                    cur_blk.append(lines[i])
            i += 1
        raise SyntaxError("Bloque IF sin ENDIF correspondiente.")

    def _collect_case_block(
        self, lines: List[str], start_idx: int
    ) -> Tuple[int, List[Tuple[str, List[str]]], Optional[List[str]]]:
        cases: List[Tuple[str, List[str]]] = []
        cur_cond: Optional[str] = None
        cur_blk: List[str] = []
        otherwise_blk: Optional[List[str]] = None

        depth = 1
        i = start_idx + 1
        n = len(lines)
        while i < n:
            ln = lines[i].strip()
            if re.match(r"^DO\s+CASE\b", ln, flags=re.IGNORECASE):
                depth += 1
                if otherwise_blk is not None:
                    otherwise_blk.append(lines[i])
                elif cur_cond is not None:
                    cur_blk.append(lines[i])
            elif re.match(r"^ENDCASE\b", ln, flags=re.IGNORECASE):
                depth -= 1
                if depth == 0:
                    if cur_cond is not None:
                        cases.append((cur_cond, cur_blk))
                    return i, cases, otherwise_blk
                if otherwise_blk is not None:
                    otherwise_blk.append(lines[i])
                elif cur_cond is not None:
                    cur_blk.append(lines[i])
            elif depth == 1 and re.match(r"^CASE\b", ln, flags=re.IGNORECASE):
                if cur_cond is not None:
                    cases.append((cur_cond, cur_blk))
                cur_cond = re.sub(r"^CASE\s+", "", ln, flags=re.IGNORECASE).strip()
                cur_blk = []
            elif depth == 1 and re.match(r"^OTHERWISE\b", ln, flags=re.IGNORECASE):
                if cur_cond is not None:
                    cases.append((cur_cond, cur_blk))
                    cur_cond = None
                otherwise_blk = []
            else:
                if otherwise_blk is not None:
                    otherwise_blk.append(lines[i])
                elif cur_cond is not None:
                    cur_blk.append(lines[i])
            i += 1
        raise SyntaxError("Bloque DO CASE sin ENDCASE correspondiente.")

    def _collect_try_block(
        self, lines: List[str], start_idx: int
    ) -> Tuple[int, List[str], Optional[str], Optional[List[str]], Optional[List[str]]]:
        try_blk: List[str] = []
        catch_var: Optional[str] = None
        catch_blk: Optional[List[str]] = None
        finally_blk: Optional[List[str]] = None
        mode = "try"
        depth = 1
        i = start_idx + 1
        n = len(lines)
        while i < n:
            ln = lines[i].strip()
            if re.match(r"^TRY\b", ln, flags=re.IGNORECASE):
                depth += 1
            elif re.match(r"^ENDTRY\b", ln, flags=re.IGNORECASE):
                depth -= 1
                if depth == 0:
                    return i, try_blk, catch_var, catch_blk, finally_blk
            elif depth == 1 and re.match(r"^CATCH\b", ln, flags=re.IGNORECASE):
                m_c = re.match(r"^CATCH(?:\s+TO\s+([A-Za-z_][A-Za-z0-9_]*))?", ln, flags=re.IGNORECASE)
                catch_var = m_c.group(1) if m_c and m_c.group(1) else None
                catch_blk = []
                mode = "catch"
                i += 1
                continue
            elif depth == 1 and re.match(r"^FINALLY\b", ln, flags=re.IGNORECASE):
                finally_blk = []
                mode = "finally"
                i += 1
                continue

            if mode == "try":
                try_blk.append(lines[i])
            elif mode == "catch" and catch_blk is not None:
                catch_blk.append(lines[i])
            elif mode == "finally" and finally_blk is not None:
                finally_blk.append(lines[i])
            i += 1
        raise SyntaxError("Bloque TRY sin ENDTRY correspondiente.")

    # -------------------------------------------------------------------------
    # Ejecutor de Sentencias y Comandos VFP
    # -------------------------------------------------------------------------
    def _exec_statement(self, line: str) -> None:
        # 1. Impresión en consola: ? y ??
        if line.startswith("??"):
            expr_part = line[2:].strip()
            text = self._eval_print_list(expr_part) if expr_part else ""
            self.emit(text, newline=False)
            return

        if line.startswith("?"):
            expr_part = line[1:].strip()
            text = self._eval_print_list(expr_part) if expr_part else ""
            self.emit(text, newline=True)
            return

        # 2. Control de saltos: EXIT, LOOP, RETURN
        if re.match(r"^EXIT\b", line, flags=re.IGNORECASE):
            raise _LoopExit()
        if re.match(r"^LOOP\b", line, flags=re.IGNORECASE):
            raise _LoopContinue()
        m_ret = re.match(r"^RETURN(?:\s+(.*))?$", line, flags=re.IGNORECASE)
        if m_ret:
            val = self.eval_expr(m_ret.group(1)) if m_ret.group(1) else True
            raise _ReturnSignal(val)

        # 3. Declaración de Variables: LOCAL, PRIVATE, PUBLIC, STORE, RELEASE
        m_decl = re.match(r"^(LOCAL|PRIVATE|PUBLIC)\s+(.*)$", line, flags=re.IGNORECASE)
        if m_decl:
            scope = m_decl.group(1).lower()
            rest = m_decl.group(2).strip()
            # Soporte para `LOCAL lnEdad = 30` o `LOCAL a, b, c AS Integer`
            if "=" in rest and "," not in rest.split("=", 1)[0]:
                vname, vexpr = rest.split("=", 1)
                vname = re.sub(r"\s+AS\s+[A-Za-z0-9_]+$", "", vname.strip(), flags=re.IGNORECASE)
                self.set_var(vname.strip(), self.eval_expr(vexpr.strip()), scope=scope)
            else:
                for raw_v in self._split_top_level(rest, ","):
                    clean_v = re.sub(r"\s+AS\s+[A-Za-z0-9_]+$", "", raw_v.strip(), flags=re.IGNORECASE)
                    if "=" in clean_v:
                        vn, ve = clean_v.split("=", 1)
                        self.set_var(vn.strip(), self.eval_expr(ve.strip()), scope=scope)
                    elif clean_v:
                        self.set_var(clean_v.strip(), False, scope=scope)
            return

        m_store = re.match(r"^STORE\s+(.+?)\s+TO\s+(.+)$", line, flags=re.IGNORECASE)
        if m_store:
            val = self.eval_expr(m_store.group(1))
            for target in m_store.group(2).split(","):
                self.set_var(target.strip(), val)
            return

        # 4. CREATE CURSOR / CREATE TABLE
        m_cc = re.match(
            r"^CREATE\s+(?:CURSOR|TABLE)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_cc:
            alias = m_cc.group(1).lower()
            schema_str = m_cc.group(2)
            fields = parse_schema_string(schema_str)
            cur = Cursor(alias, fields)
            self.wam.open_cursor_in_current_or_new(cur, in_free_area=False)
            return

        # 5. SQL Nativo: SELECT ... FROM ... [INTO CURSOR alias]
        if re.match(r"^SELECT\s+.+\bFROM\b", line, flags=re.IGNORECASE):
            m_into = re.search(r"\bINTO\s+(?:CURSOR|TABLE)\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+READWRITE|\s+NOFILTER)*\s*$", line, flags=re.IGNORECASE)
            into_alias = None
            sql_part = line
            if m_into:
                into_alias = m_into.group(1)
                sql_part = line[: m_into.start()].strip()
            res_cur = self.wam.execute_sql_select(sql_part, into_alias, self.current_vars())
            if into_alias is None:
                self.emit(res_cur.format_browse_table(self.wam.set_deleted))
            return

        # 6. SELECT <alias | work_area> (Cambiar área de trabajo activa)
        m_sel = re.match(r"^SELECT\s+([A-Za-z0-9_]+)\s*$", line, flags=re.IGNORECASE)
        if m_sel:
            self.wam.select_area(m_sel.group(1))
            return

        # 7. USE [archivo_dbf] [IN area] [ALIAS alias]
        m_use = re.match(r"^USE(?:\s+(.*))?$", line, flags=re.IGNORECASE)
        if m_use:
            args_str = (m_use.group(1) or "").strip()
            if not args_str:
                self.wam.close_alias()
                return
            in_Zero = bool(re.search(r"\bIN\s+0\b", args_str, flags=re.IGNORECASE))
            m_alias = re.search(r"\bALIAS\s+([A-Za-z_][A-Za-z0-9_]*)", args_str, flags=re.IGNORECASE)
            tokens = args_str.split()
            target_file = tokens[0].strip("\"'")
            path = Path(target_file)
            if not path.suffix:
                path = path.with_suffix(".dbf")
            alias = m_alias.group(1).lower() if m_alias else path.stem.lower()
            raw_fields, rows, del_flags = read_dbf(path)
            fdefs = [FieldDef(f["name"], f["type"], f["width"], f["decimals"]) for f in raw_fields]
            cur = Cursor(alias, fdefs, source_path=str(path))
            for r in rows:
                cur.append_dict(r)
            cur.deleted_flags = del_flags
            cur.go_top(self.wam.set_deleted)
            self.wam.open_cursor_in_current_or_new(cur, in_free_area=in_Zero)
            return

        # 8. CLOSE TABLES / CLOSE DATABASES / CLEAR
        if re.match(r"^CLOSE\s+(?:TABLES|DATABASES|ALL)\b", line, flags=re.IGNORECASE):
            self.wam.close_all()
            return

        if re.match(r"^CLEAR\b", line, flags=re.IGNORECASE):
            self.output_buffer.clear()
            return

        # 9. APPEND BLANK
        if re.match(r"^APPEND\s+BLANK\b", line, flags=re.IGNORECASE):
            cur = self._require_cursor("APPEND BLANK")
            cur.append_blank()
            return

        # 10. INSERT INTO alias [(cols)] VALUES (vals)
        m_ins = re.match(
            r"^INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\((.*?)\))?\s*VALUES\s*\((.*)\)\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_ins:
            alias = m_ins.group(1).lower()
            cols_str = m_ins.group(2)
            vals_str = m_ins.group(3)
            cur = self.wam.get_cursor(alias)
            if cur is None:
                raise RuntimeError(f"El cursor '{alias}' no existe para INSERT INTO.")
            vals = [self.eval_expr(v) for v in self._split_top_level(vals_str, ",")]
            if cols_str:
                cols = [c.strip().lower() for c in cols_str.split(",") if c.strip()]
            else:
                cols = [f.name for f in cur.fields]
            data = {cols[idx]: vals[idx] for idx in range(min(len(cols), len(vals)))}
            cur.append_dict(data)
            return

        # 11. REPLACE [ALL] f1 WITH v1 [, f2 WITH v2] [FOR cond] [IN alias]
        m_rep = re.match(r"^REPLACE\s+(.*)$", line, flags=re.IGNORECASE)
        if m_rep:
            self._exec_replace(m_rep.group(1))
            return

        # 12. Navegación de Puntero: GO TOP, GO BOTTOM, GOTO n, SKIP [n]
        if re.match(r"^GO(?:\s+TO)?\s+TOP\b", line, flags=re.IGNORECASE):
            cur = self._require_cursor("GO TOP")
            cur.go_top(self.wam.set_deleted)
            self.wam.sync_relations(self.eval_expr)
            return

        if re.match(r"^GO(?:\s+TO)?\s+BOTTOM\b", line, flags=re.IGNORECASE):
            cur = self._require_cursor("GO BOTTOM")
            cur.go_bottom(self.wam.set_deleted)
            self.wam.sync_relations(self.eval_expr)
            return

        m_goto = re.match(r"^(?:GOTO|GO)\s+(\d+)\s*$", line, flags=re.IGNORECASE)
        if m_goto:
            cur = self._require_cursor("GOTO")
            cur.goto(int(m_goto.group(1)))
            self.wam.sync_relations(self.eval_expr)
            return

        m_skip = re.match(r"^SKIP(?:\s+([+-]?\d+))?$", line, flags=re.IGNORECASE)
        if m_skip:
            cur = self._require_cursor("SKIP")
            step = int(m_skip.group(1)) if m_skip.group(1) else 1
            cur.skip(step, self.wam.set_deleted)
            self.wam.sync_relations(self.eval_expr)
            return

        # 13. Búsqueda e Índices: LOCATE, CONTINUE, INDEX ON, SET ORDER TO, SEEK
        m_loc = re.match(r"^LOCATE\s+FOR\s+(.*)$", line, flags=re.IGNORECASE)
        if m_loc:
            cur = self._require_cursor("LOCATE")
            cond_expr = m_loc.group(1).strip()
            cur._last_locate_expr = cond_expr
            cur.found = False
            for r in cur.visible_recnos(self.wam.set_deleted):
                cur.goto(r)
                if bool(self.eval_expr(cond_expr)):
                    cur.found = True
                    self.wam.sync_relations(self.eval_expr)
                    return
            cur._recno = len(cur.records) + 1
            cur.eof = True
            return

        if re.match(r"^CONTINUE\b", line, flags=re.IGNORECASE):
            cur = self._require_cursor("CONTINUE")
            if not cur._last_locate_expr:
                raise RuntimeError("CONTINUE invocado sin un LOCATE previo.")
            vis = cur.visible_recnos(self.wam.set_deleted)
            start_rec = cur.recno()
            cur.found = False
            for r in vis:
                if r <= start_rec:
                    continue
                cur.goto(r)
                if bool(self.eval_expr(cur._last_locate_expr)):
                    cur.found = True
                    self.wam.sync_relations(self.eval_expr)
                    return
            cur._recno = len(cur.records) + 1
            cur.eof = True
            return

        m_idx = re.match(r"^INDEX\s+ON\s+(.+?)\s+TAG\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", line, flags=re.IGNORECASE)
        if m_idx:
            cur = self._require_cursor("INDEX ON")
            cur.build_index(m_idx.group(2), m_idx.group(1).strip(), self.eval_expr)
            return

        m_ord = re.match(r"^SET\s+ORDER\s+TO(?:\s+([A-Za-z_][A-Za-z0-9_]*))?\s*$", line, flags=re.IGNORECASE)
        if m_ord:
            cur = self._require_cursor("SET ORDER TO")
            tag = m_ord.group(1).lower() if m_ord.group(1) else None
            if tag:
                if tag not in cur.indexes:
                    raise KeyError(f"El TAG de índice '{tag}' no existe en '{cur.alias}'.")
                cur.active_tag = tag
                cur.recompute_index(self.eval_expr)
            else:
                cur.active_tag = None
                cur._ordered_recnos = None
            return

        m_seek = re.match(r"^SEEK\s+(.*)$", line, flags=re.IGNORECASE)
        if m_seek:
            cur = self._require_cursor("SEEK")
            target_val = self.eval_expr(m_seek.group(1).strip())
            cur.seek(target_val, self.eval_expr, self.wam.set_deleted)
            self.wam.sync_relations(self.eval_expr)
            return

        # 14. Relaciones: SET RELATION TO expr INTO alias
        m_rel = re.match(
            r"^SET\s+RELATION\s+TO(?:\s+(.+?)\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*))?\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_rel:
            cur = self._require_cursor("SET RELATION")
            if m_rel.group(1) and m_rel.group(2):
                cur.relations = [(m_rel.group(1).strip(), m_rel.group(2).lower())]
                self.wam.sync_relations(self.eval_expr)
            else:
                cur.relations.clear()
            return

        # 15. Borrado lógico y físico: DELETE, RECALL, PACK, ZAP, SET DELETED
        m_del_set = re.match(r"^SET\s+DELETED\s+(ON|OFF)\s*$", line, flags=re.IGNORECASE)
        if m_del_set:
            self.wam.set_deleted = m_del_set.group(1).upper() == "ON"
            return

        m_del = re.match(r"^DELETE(?:\s+ALL)?(?:\s+FOR\s+(.*))?$", line, flags=re.IGNORECASE)
        if m_del and not re.match(r"^DELETE\s+FROM\b", line, flags=re.IGNORECASE):
            cur = self._require_cursor("DELETE")
            is_all = bool(re.match(r"^DELETE\s+ALL\b", line, flags=re.IGNORECASE))
            for_expr = m_del.group(1).strip() if m_del.group(1) else None
            if is_all or for_expr:
                for r in list(cur.visible_recnos(self.wam.set_deleted)):
                    cur.goto(r)
                    if for_expr is None or bool(self.eval_expr(for_expr)):
                        cur.delete_current()
                cur.go_top(self.wam.set_deleted)
            else:
                cur.delete_current()
            return

        m_recall = re.match(r"^RECALL(?:\s+ALL)?(?:\s+FOR\s+(.*))?$", line, flags=re.IGNORECASE)
        if m_recall:
            cur = self._require_cursor("RECALL")
            is_all = bool(re.match(r"^RECALL\s+ALL\b", line, flags=re.IGNORECASE))
            for_expr = m_recall.group(1).strip() if m_recall.group(1) else None
            if is_all or for_expr:
                for r in range(1, cur.reccount() + 1):
                    cur.goto(r)
                    if for_expr is None or bool(self.eval_expr(for_expr)):
                        cur.recall_current()
                cur.go_top(self.wam.set_deleted)
            else:
                cur.recall_current()
            return

        if re.match(r"^PACK\b", line, flags=re.IGNORECASE):
            cur = self._require_cursor("PACK")
            cur.pack()
            return

        if re.match(r"^ZAP\b", line, flags=re.IGNORECASE):
            cur = self._require_cursor("ZAP")
            cur.zap()
            return

        # 16. Visualización y Exportación: BROWSE, LIST, DISPLAY STRUCTURE, COPY TO
        if re.match(r"^(?:BROWSE|LIST)\b", line, flags=re.IGNORECASE):
            cur = self._require_cursor("BROWSE")
            self.emit(cur.format_browse_table(self.wam.set_deleted))
            return

        if re.match(r"^DISPLAY\s+STRUCTURE\b", line, flags=re.IGNORECASE):
            cur = self._require_cursor("DISPLAY STRUCTURE")
            self.emit(cur.format_structure())
            return

        m_copy = re.match(
            r"^COPY\s+TO\s+([^\s]+)(?:\s+TYPE\s+(CSV|JSON|DBF|FOX2X))?\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_copy:
            cur = self._require_cursor("COPY TO")
            raw_target = m_copy.group(1).strip("\"'")
            fmt = (m_copy.group(2) or "").upper()
            path = Path(raw_target)
            if not fmt:
                ext = path.suffix.lower()
                if ext == ".csv":
                    fmt = "CSV"
                elif ext == ".json":
                    fmt = "JSON"
                else:
                    fmt = "DBF"
                    if not ext:
                        path = path.with_suffix(".dbf")

            vis = cur.visible_recnos(self.wam.set_deleted)
            vis_rows = [cur.records[r - 1] for r in vis]
            vis_dels = [cur.deleted_flags[r - 1] for r in vis]
            fdicts = [{"name": f.name, "type": f.ftype, "width": f.width, "decimals": f.decimals} for f in cur.fields]

            if fmt == "CSV":
                export_csv(path, fdicts, vis_rows)
            elif fmt == "JSON":
                export_json(path, vis_rows)
            else:
                write_dbf(path, fdicts, vis_rows, vis_dels)
            return

        # 16b. APPEND FROM <archivo> [TYPE CSV|JSON|DBF]
        m_app_from = re.match(
            r"^APPEND\s+FROM\s+([^\s]+)(?:\s+TYPE\s+(CSV|JSON|DBF))?\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_app_from:
            cur = self._require_cursor("APPEND FROM")
            raw_src = m_app_from.group(1).strip("\"'")
            fmt = (m_app_from.group(2) or "").upper()
            path = Path(raw_src)
            if not fmt:
                ext = path.suffix.lower()
                if ext == ".csv":
                    fmt = "CSV"
                elif ext == ".json":
                    fmt = "JSON"
                else:
                    fmt = "DBF"
                    if not ext:
                        path = path.with_suffix(".dbf")
            if fmt == "CSV":
                rows = import_csv(path)
            elif fmt == "JSON":
                rows = import_json(path)
            else:
                _, rows, _ = read_dbf(path)
            for r in rows:
                cur.append_dict(r)
            return

        # 16c. SQL Nativo: UPDATE <alias> SET col1 = expr1 [, col2 = expr2] [WHERE cond]
        m_upd = re.match(
            r"^UPDATE\s+([A-Za-z_][A-Za-z0-9_]*)\s+SET\s+(.+?)(?:\s+WHERE\s+(.+))?\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_upd:
            alias = m_upd.group(1).lower()
            set_part = m_upd.group(2).strip()
            where_part = m_upd.group(3).strip() if m_upd.group(3) else None
            cur = self.wam.get_cursor(alias)
            if cur is None:
                raise RuntimeError(f"El cursor '{alias}' no existe para UPDATE.")
            assignments: List[Tuple[str, str]] = []
            for item in self._split_top_level(set_part, ","):
                if "=" not in item:
                    raise SyntaxError(f"Asignación inválida en UPDATE SET: '{item}'")
                k, v = item.split("=", 1)
                assignments.append((k.strip().split(".")[-1], v.strip()))

            saved_area = self.wam.current_area
            self.wam.select_area(cur.alias)
            try:
                for r in list(cur.visible_recnos(self.wam.set_deleted)):
                    cur.goto(r)
                    if where_part is None or bool(self.eval_expr(where_part)):
                        for col_name, val_expr in assignments:
                            cur.set_field(col_name, self.eval_expr(val_expr))
            finally:
                self.wam.current_area = saved_area
            return

        # 16d. SQL Nativo: DELETE FROM <alias> [WHERE cond]
        m_del_sql = re.match(
            r"^DELETE\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+WHERE\s+(.+))?\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_del_sql:
            alias = m_del_sql.group(1).lower()
            where_part = m_del_sql.group(2).strip() if m_del_sql.group(2) else None
            cur = self.wam.get_cursor(alias)
            if cur is None:
                raise RuntimeError(f"El cursor '{alias}' no existe para DELETE FROM.")
            saved_area = self.wam.current_area
            self.wam.select_area(cur.alias)
            try:
                for r in list(cur.visible_recnos(self.wam.set_deleted)):
                    cur.goto(r)
                    if where_part is None or bool(self.eval_expr(where_part)):
                        cur.delete_current()
                cur.go_top(self.wam.set_deleted)
            finally:
                self.wam.current_area = saved_area
            return

        # 16e. DO FORM <archivo.foxform> [TO FILE <salida.html>]
        m_do_form = re.match(
            r"^DO\s+FORM\s+([^\s]+)(?:\s+TO\s+FILE\s+([^\s]+))?\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_do_form:
            from .foxform import FoxForm

            raw_form = m_do_form.group(1).strip("\"'")
            out_file = m_do_form.group(2).strip("\"'") if m_do_form.group(2) else None
            fpath = Path(raw_form)
            if not fpath.suffix:
                fpath = fpath.with_suffix(".foxform")
            form = FoxForm.from_file(fpath, interpreter=self)
            form.initialize()
            self.set_var(form.name, form, scope="public")
            if out_file:
                form.export_html(out_file)
            else:
                self.emit(form.render_tui())
            return

        # 16f. REPORT FORM <archivo.foxreport> [FOR <cond>] [TO FILE <salida.html|.txt>]
        m_rep_form = re.match(
            r"^REPORT\s+FORM\s+([^\s]+)(?:\s+FOR\s+(.+?))?(?:\s+TO\s+FILE\s+([^\s]+))?\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_rep_form:
            from .foxreport import FoxReport

            raw_rep = m_rep_form.group(1).strip("\"'")
            for_expr = m_rep_form.group(2).strip() if m_rep_form.group(2) else None
            out_file = m_rep_form.group(3).strip("\"'") if m_rep_form.group(3) else None
            rpath = Path(raw_rep)
            if not rpath.suffix:
                rpath = rpath.with_suffix(".foxreport")
            report = FoxReport.from_file(rpath, interpreter=self)
            if out_file:
                out_p = Path(out_file)
                if out_p.suffix.lower() in (".html", ".htm"):
                    out_p.write_text(report.render_html(for_expr), encoding="utf-8")
                else:
                    out_p.write_text(report.render_text(for_expr), encoding="utf-8")
            else:
                self.emit(report.render_text(for_expr))
            return

        # 16g. MIGRATE SCX <archivo.scx> TO <salida.foxform>
        m_mig = re.match(
            r"^MIGRATE\s+SCX\s+([^\s]+)\s+TO\s+([^\s]+)\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_mig:
            scx_in = m_mig.group(1).strip("\"'")
            ff_out = m_mig.group(2).strip("\"'")
            migrate_scx_to_foxform(scx_in, ff_out)
            self.emit(f"[vfp2modern] Migrado '{scx_in}' -> '{ff_out}'")
            return

        # 17. DO <procedimiento | archivo.prg> [WITH a, b]
        m_do = re.match(r'^DO\s+([^\s]+)(?:\s+WITH\s+(.*))?$', line, flags=re.IGNORECASE)
        if m_do and not re.match(r"^DO\s+(?:WHILE|CASE|FORM)\b", line, flags=re.IGNORECASE):
            target = m_do.group(1).strip("\"'")
            args: List[Any] = []
            if m_do.group(2):
                args = [self.eval_expr(a) for a in self._split_top_level(m_do.group(2), ",")]
            tl = target.lower()
            if tl in self.procedures:
                params, body = self.procedures[tl]
                self._invoke_Routine(params, body, args)
                return
            prg_path = Path(target)
            if not prg_path.suffix:
                prg_path = prg_path.with_suffix(".prg")
            if prg_path.is_file():
                code = prg_path.read_text(encoding="utf-8")
                self.execute(code)
                return
            raise RuntimeError(f"No se encontró el procedimiento o programa '{target}'.")

        # 18. Asignación de Variable / Propiedad (`x = expr`)
        m_assign = re.match(r"^([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(.+)$", line)
        if m_assign:
            lhs = m_assign.group(1).strip()
            rhs_val = self.eval_expr(m_assign.group(2).strip())
            self.set_var(lhs, rhs_val)
            return

        # 19. Evaluación directa de llamada a función o método (incluyendo prefijo clásico VFP `=FUNC()`)
        expr_stmt = line[1:].strip() if line.startswith("=") else line
        self.eval_expr(expr_stmt)

    def _exec_replace(self, body: str) -> None:
        # Extraer cláusula IN <alias>
        target_alias: Optional[str] = None
        m_in = re.search(r"\s+IN\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", body, flags=re.IGNORECASE)
        if m_in:
            target_alias = m_in.group(1)
            body = body[: m_in.start()].strip()

        # Extraer cláusula FOR <cond>
        for_expr: Optional[str] = None
        m_for = re.search(r"\s+FOR\s+(.+)$", body, flags=re.IGNORECASE)
        if m_for:
            for_expr = m_for.group(1).strip()
            body = body[: m_for.start()].strip()

        is_all = False
        if re.match(r"^ALL\s+", body, flags=re.IGNORECASE):
            is_all = True
            body = re.sub(r"^ALL\s+", "", body, flags=re.IGNORECASE).strip()

        cur = self.wam.get_cursor(target_alias) if target_alias else self.wam.current_cursor()
        if cur is None:
            raise RuntimeError("REPLACE ejecutado sin cursor activo.")

        # Parsear pares `campo WITH expresion` separados por coma
        pairs: List[Tuple[str, str]] = []
        for item in self._split_top_level(body, ","):
            m_with = re.match(r"^([A-Za-z_][A-Za-z0-9_.]*)\s+WITH\s+(.+)$", item.strip(), flags=re.IGNORECASE)
            if not m_with:
                raise SyntaxError(f"Sintaxis inválida en REPLACE: '{item}'")
            fname = m_with.group(1).split(".")[-1]
            pairs.append((fname, m_with.group(2).strip()))

        if is_all or for_expr:
            saved_area = self.wam.current_area
            self.wam.select_area(cur.alias)
            try:
                for r in list(cur.visible_recnos(self.wam.set_deleted)):
                    cur.goto(r)
                    if for_expr is None or bool(self.eval_expr(for_expr)):
                        for fname, vexpr in pairs:
                            cur.set_field(fname, self.eval_expr(vexpr))
            finally:
                self.wam.current_area = saved_area
        else:
            for fname, vexpr in pairs:
                cur.set_field(fname, self.eval_expr(vexpr))

    def _eval_print_list(self, expr_list_str: str) -> str:
        parts = self._split_top_level(expr_list_str, ",")
        vals = [self.functions["transform"](self.eval_expr(p)) for p in parts if p.strip()]
        return " ".join(vals)

    def _require_cursor(self, cmd_name: str) -> Cursor:
        cur = self.wam.current_cursor()
        if cur is None:
            raise RuntimeError(f"El comando '{cmd_name}' requiere un cursor abierto en el área de trabajo actual.")
        return cur

    @staticmethod
    def _split_top_level(text: str, sep: str = ",") -> List[str]:
        items: List[str] = []
        buf: List[str] = []
        depth = 0
        in_quote: Optional[str] = None
        for ch in text:
            if in_quote:
                buf.append(ch)
                if ch == in_quote:
                    in_quote = None
            else:
                if ch in ('"', "'"):
                    in_quote = ch
                    buf.append(ch)
                elif ch in ("(", "["):
                    depth += 1
                    buf.append(ch)
                elif ch in (")", "]"):
                    depth = max(0, depth - 1)
                    buf.append(ch)
                elif ch == sep and depth == 0:
                    items.append("".join(buf).strip())
                    buf = []
                else:
                    buf.append(ch)
        if buf:
            items.append("".join(buf).strip())
        return items

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
    Soporta herencia multinivel (DODEFAULT), introspección (PEMSTATUS / ADDPROPERTY)
    y enlace dinámico de eventos (BINDEVENT / RAISEEVENT).
    """

    def __init__(
        self,
        class_name: str,
        properties: Dict[str, Any],
        methods: Dict[str, Tuple[List[str], List[str]]],
        interpreter: "FoxInterpreter",
        parent_class: str = "Custom",
        parent_methods: Optional[Dict[str, Tuple[List[str], List[str]]]] = None,
    ):
        self.__vfp_class__ = class_name
        self._parent_class = parent_class
        self._props: Dict[str, Any] = {k.lower(): v for k, v in properties.items()}
        self._methods = methods
        self._parent_methods = parent_methods or {}
        self._bound_events: Dict[str, List[Tuple["VFPObject", str]]] = {}
        self._interp = interpreter

    def get_prop(self, name: str) -> Any:
        nl = name.lower()
        if nl == "class":
            return self.__vfp_class__
        if nl == "parentclass":
            return self._parent_class
        return self._props.get(nl)

    def set_prop(self, name: str, value: Any) -> None:
        self._props[name.lower()] = value

    def has_member(self, name: str) -> bool:
        nl = name.lower()
        return nl in self._props or nl in self._methods or nl in ("class", "parentclass")

    def call_method(self, name: str, *args: Any) -> Any:
        nl = name.lower()
        if nl not in self._methods:
            raise AttributeError(f"El método '{name}' no existe en la clase '{self.__vfp_class__}'")
        params, body = self._methods[nl]
        self._interp._method_stack.append((self, nl))
        try:
            res = self._interp._invoke_Routine(params, body, list(args), this_obj=self)
        finally:
            self._interp._method_stack.pop()

        # Disparar delegados registrados con BINDEVENT
        for delegate_obj, delegate_method in list(self._bound_events.get(nl, [])):
            delegate_obj.call_method(delegate_method, *args)
        return res

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_"):
            raise AttributeError(item)
        nl = item.lower()
        if nl == "class":
            return self.__vfp_class__
        if nl == "parentclass":
            return self._parent_class
        if nl in self._methods:
            return lambda *a: self.call_method(nl, *a)
        if nl in self._props:
            return self._props[nl]
        raise AttributeError(f"Propiedad o método '{item}' no encontrado en '{self.__vfp_class__}'")

    def __repr__(self) -> str:
        return f"<Object:{self.__vfp_class__} {self._props}>"


class VFPCollection:
    """
    Implementación de la clase nativa CREATEOBJECT('Collection') de Visual FoxPro.
    Soporta .Add(val [, key]), .Item(idx_or_key), .Remove(idx_or_key), .GetKey(idx) y .Count.
    """

    def __init__(self) -> None:
        self.__vfp_class__ = "Collection"
        self._items: List[Any] = []
        self._keys: List[Optional[str]] = []

    @property
    def count(self) -> int:
        return len(self._items)

    def add(self, item: Any, key: Optional[str] = None) -> int:
        if key is not None:
            k_str = str(key)
            if k_str in self._keys:
                raise KeyError(f"La clave '{k_str}' ya existe en la colección.")
            self._keys.append(k_str)
        else:
            self._keys.append(None)
        self._items.append(item)
        return len(self._items)

    def item(self, idx_or_key: int | str) -> Any:
        if isinstance(idx_or_key, int):
            idx = idx_or_key - 1  # 1-based en VFP
            if 0 <= idx < len(self._items):
                return self._items[idx]
            raise IndexError(f"Índice de colección fuera de rango: {idx_or_key}")
        k_str = str(idx_or_key)
        if k_str in self._keys:
            return self._items[self._keys.index(k_str)]
        raise KeyError(f"Clave '{k_str}' no encontrada en la colección.")

    def remove(self, idx_or_key: int | str) -> int:
        if idx_or_key == -1:
            self._items.clear()
            self._keys.clear()
            return 0
        if isinstance(idx_or_key, int):
            idx = idx_or_key - 1
            if 0 <= idx < len(self._items):
                self._items.pop(idx)
                self._keys.pop(idx)
                return len(self._items)
            raise IndexError(f"Índice fuera de rango en Remove: {idx_or_key}")
        k_str = str(idx_or_key)
        if k_str in self._keys:
            pos = self._keys.index(k_str)
            self._items.pop(pos)
            self._keys.pop(pos)
            return len(self._items)
        raise KeyError(f"Clave '{k_str}' no encontrada en Remove.")

    def getkey(self, idx: int) -> str:
        pos = int(idx) - 1
        if 0 <= pos < len(self._keys):
            return self._keys[pos] or ""
        return ""

    def __getattr__(self, name: str) -> Any:
        nl = name.lower()
        if nl == "count":
            return self.count
        if nl == "add":
            return self.add
        if nl == "item":
            return self.item
        if nl == "remove":
            return self.remove
        if nl == "getkey":
            return self.getkey
        raise AttributeError(f"Miembro '{name}' no existe en Collection.")


class VFPCursorAdapter(VFPObject):
    """
    Implementación de la clase nativa CREATEOBJECT('CursorAdapter') de Visual FoxPro.
    Soporta Alias, SelectCmd, CursorSchema, DataSourceType, KeyFieldList, Tables,
    y los métodos .CursorFill([lUseSchema]), .CursorRefresh() y .CursorDetach().
    """

    def __init__(self, interpreter: "FoxInterpreter"):
        super().__init__(
            "CursorAdapter",
            {
                "alias": "cur_adapter",
                "selectcmd": "",
                "cursorschema": "",
                "datasourcetype": "Native",
                "keyfieldlist": "",
                "tables": "",
                "sendupdates": False,
                "detached": False,
            },
            {},
            interpreter,
        )

    def cursorfill(self, use_cursor_schema: bool = False) -> bool:
        alias = str(self._props.get("alias") or "cur_adapter").strip().lower()
        select_cmd = str(self._props.get("selectcmd") or "").strip()
        schema_str = str(self._props.get("cursorschema") or "").strip()
        if not select_cmd:
            return False
        try:
            cur = self._interp.wam.execute_sql_select(select_cmd, alias, self._interp.current_vars())
            if use_cursor_schema and schema_str:
                explicit_fields = parse_schema_string(schema_str)
                cur.fields = explicit_fields
                cur.field_map = {f.name: f for f in explicit_fields}
                for row in cur.records:
                    for f in explicit_fields:
                        row[f.name] = f.coerce(row.get(f.name))
            return True
        except Exception as exc:
            self._interp.last_error = (1098, str(exc), select_cmd)
            return False

    def cursorrefresh(self) -> bool:
        return self.cursorfill(bool(self._props.get("cursorschema")))

    def cursordetach(self) -> bool:
        self._props["detached"] = True
        return True

    def __getattr__(self, item: str) -> Any:
        il = item.lower()
        if il == "cursorfill":
            return self.cursorfill
        if il == "cursorrefresh":
            return self.cursorrefresh
        if il == "cursordetach":
            return self.cursordetach
        return super().__getattr__(item)


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
        self.functions["dodefault"] = self.do_default
        self.functions["addproperty"] = self.add_property
        self.functions["pemstatus"] = self.pem_status
        self.functions["bindevent"] = self.bind_event
        self.functions["unbindevents"] = self.unbind_events
        self.functions["raiseevent"] = self.raise_event
        self.functions["requery"] = self.requery
        self.functions["adir"] = self.adir
        self.functions["cursortoxml"] = self.cursor_to_xml
        self.functions["xmltocursor"] = self.xml_to_cursor
        self.functions["error"] = self.fn_error_num
        self.functions["message"] = self.fn_error_msg
        self.functions["aerror"] = self.fn_aerror
        self.functions["__vfp_idx__"] = self._vfp_array_index

        self.global_vars: Dict[str, Any] = {}
        self.call_stack: List[Dict[str, Any]] = []
        self._this_stack: List[VFPObject] = []
        self._method_stack: List[Tuple[VFPObject, str]] = []
        self.asserts_enabled: bool = True
        self.menus: Dict[str, Any] = {}
        self.on_error_cmd: Optional[str] = None
        self.last_error: Tuple[int, str, str] = (0, "", "")
        self._try_depth: int = 0
        self._in_error_handler: bool = False

        # Procedimientos / Funciones definidas por el usuario: name -> (params, body_lines)
        self.procedures: Dict[str, Tuple[List[str], List[str]]] = {}
        # Clases definidas con DEFINE CLASS: name -> (parent, props_lines, methods_dict)
        self.classes: Dict[str, Tuple[str, List[str], Dict[str, Tuple[List[str], List[str]]]]] = {}

        self.output_buffer: List[str] = []
        self._output_cb = output_callback

    def sql_exec(self, handle: int, sql_stmt: str, cursor_name: str = "sqlresult") -> int:
        return self.wam.sql_exec(handle, sql_stmt, cursor_name, self.current_vars())

    def requery(self, alias_or_area: Any = None) -> int:
        return self.wam.requery_view(alias_or_area, self.current_vars())

    def adir(self, array_name_or_ref: Any, skeleton: str = "*") -> int:
        p_skel = Path(str(skeleton or "*"))
        base_dir = p_skel.parent if str(p_skel.parent) != "." else Path(".")
        pattern = p_skel.name or "*"
        matches = sorted(base_dir.glob(pattern), key=lambda p: p.name.lower())
        rows: List[List[Any]] = []
        for item in matches:
            try:
                st = item.stat()
                dt = datetime.datetime.fromtimestamp(st.st_mtime)
                attr = "D" if item.is_dir() else "A"
                rows.append([
                    item.name,
                    int(st.st_size),
                    dt.date(),
                    dt.strftime("%H:%M:%S"),
                    attr,
                ])
            except OSError:
                continue
        if isinstance(array_name_or_ref, str):
            self.set_var(array_name_or_ref, rows)
        elif isinstance(array_name_or_ref, list):
            array_name_or_ref.clear()
            array_name_or_ref.extend(rows)
        return len(rows)

    def cursor_to_xml(self, alias_or_area: Any = None, out_target: Optional[str] = None) -> Any:
        xml_str = self.wam.cursor_to_xml(alias_or_area)
        if out_target:
            target_str = str(out_target).strip()
            if "/" in target_str or "\\" in target_str or target_str.lower().endswith(".xml"):
                Path(target_str).write_text(xml_str, encoding="utf-8")
                return len(xml_str.encode("utf-8"))
            self.set_var(target_str, xml_str)
            return len(xml_str)
        return xml_str

    def xml_to_cursor(self, xml_source: Any, cursor_name: str = "xmlresult") -> int:
        return self.wam.xml_to_cursor(str(xml_source), cursor_name)

    def fn_error_num(self) -> int:
        return self.last_error[0]

    def fn_error_msg(self) -> str:
        return self.last_error[1]

    def fn_aerror(self, array_name_or_ref: Any) -> int:
        errno, errmsg, errstmt = self.last_error
        if errno == 0 and not errmsg:
            return 0
        row = [errno, errmsg, errstmt, "", "", "", ""]
        if isinstance(array_name_or_ref, str):
            self.set_var(array_name_or_ref, [row])
        elif isinstance(array_name_or_ref, list):
            array_name_or_ref.clear()
            array_name_or_ref.append(row)
        return 1

    @staticmethod
    def _vfp_array_index(arr: Any, idx1: Any, idx2: Any = None) -> Any:
        if isinstance(arr, list):
            i1 = int(idx1) - 1
            if idx2 is not None:
                i2 = int(idx2) - 1
                return arr[i1][i2]
            if arr and isinstance(arr[0], list):
                flat = [item for sub in arr for item in (sub if isinstance(sub, list) else [sub])]
                if 0 <= i1 < len(flat):
                    return flat[i1]
            return arr[i1]
        return arr[idx1]

    def do_default(self, *args: Any) -> Any:
        if not self._method_stack:
            return True
        obj, method_name = self._method_stack[-1]
        if method_name in obj._parent_methods:
            params, body = obj._parent_methods[method_name]
            return self._invoke_Routine(params, body, list(args), this_obj=obj)
        return True

    @staticmethod
    def add_property(obj: Any, prop_name: str, initial_val: Any = False) -> bool:
        if isinstance(obj, VFPObject):
            obj.set_prop(prop_name, initial_val)
            return True
        return False

    @staticmethod
    def pem_status(obj: Any, member_name: str, attribute: int = 5) -> Any:
        if not isinstance(obj, VFPObject):
            return False
        attr = int(attribute)
        ml = member_name.strip().lower()
        if attr == 5:
            return obj.has_member(ml)
        if attr == 3:
            return "Method" if ml in obj._methods else "Property"
        return obj.has_member(ml)

    @staticmethod
    def bind_event(src_obj: Any, event_name: str, delegate_obj: Any, delegate_method: str, flags: int = 0) -> int:
        if not isinstance(src_obj, VFPObject) or not isinstance(delegate_obj, VFPObject):
            raise TypeError("BINDEVENT requiere instancias de objetos VFPObject válidos.")
        ev = event_name.strip().lower()
        dm = delegate_method.strip().lower()
        src_obj._bound_events.setdefault(ev, []).append((delegate_obj, dm))
        return 1

    @staticmethod
    def unbind_events(src_obj: Any, event_name: Optional[str] = None) -> int:
        if not isinstance(src_obj, VFPObject):
            return 0
        if event_name:
            removed = len(src_obj._bound_events.pop(event_name.strip().lower(), []))
            return removed
        total = sum(len(v) for v in src_obj._bound_events.values())
        src_obj._bound_events.clear()
        return total

    @staticmethod
    def raise_event(src_obj: Any, event_name: str, *args: Any) -> Any:
        if not isinstance(src_obj, VFPObject):
            raise TypeError("RAISEEVENT requiere una instancia de VFPObject.")
        ev = event_name.strip().lower()
        if ev in src_obj._methods:
            return src_obj.call_method(ev, *args)
        for delegate_obj, delegate_method in list(src_obj._bound_events.get(ev, [])):
            delegate_obj.call_method(delegate_method, *args)
        return True

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

    def create_object(self, class_name: str, *args: Any) -> Any:
        cl = class_name.strip().lower()
        if cl == "empty":
            return VFPObject("Empty", {}, {}, self)
        if cl == "collection":
            return VFPCollection()
        if cl == "cursoradapter":
            return VFPCursorAdapter(self)
        if cl not in self.classes:
            raise ValueError(f"La clase '{class_name}' no está definida.")

        # Resolver cadena de herencia desde la clase base hasta la subclase
        chain: List[str] = []
        curr: Optional[str] = cl
        while curr and curr in self.classes:
            chain.append(curr)
            parent_n = self.classes[curr][0].lower()
            curr = parent_n if parent_n in self.classes and parent_n not in chain else None
        chain.reverse()

        merged_prop_lines: List[str] = []
        merged_methods: Dict[str, Tuple[List[str], List[str]]] = {}
        parent_methods: Dict[str, Tuple[List[str], List[str]]] = {}

        for idx, c_key in enumerate(chain):
            _, p_lines, c_methods = self.classes[c_key]
            merged_prop_lines.extend(p_lines)
            if idx < len(chain) - 1:
                parent_methods.update(c_methods)
            merged_methods.update(c_methods)

        immediate_parent = self.classes[cl][0]
        obj = VFPObject(
            class_name,
            {},
            merged_methods,
            self,
            parent_class=immediate_parent,
            parent_methods=parent_methods,
        )
        self._this_stack.append(obj)
        try:
            for pline in merged_prop_lines:
                if "=" in pline:
                    k, v_expr = pline.split("=", 1)
                    obj.set_prop(k.strip(), self.eval_expr(v_expr.strip()))
            if "init" in merged_methods:
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

        # Auto-entrecomillar nombre de arreglo en ADIR(laArr, ...)
        s = re.sub(
            r"\bADIR\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*([,)])",
            lambda m: f'ADIR("{m.group(1)}"{m.group(2)}',
            s,
            flags=re.IGNORECASE,
        )

        # Auto-entrecomillar nombre de arreglo en AERROR(laErr)
        s = re.sub(
            r"\bAERROR\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)",
            lambda m: f'AERROR("{m.group(1)}")',
            s,
            flags=re.IGNORECASE,
        )

        # Auto-entrecomillar segundo argumento en CURSORTOXML(alias, lcVar) si es identificador sin comillas
        s = re.sub(
            r"\bCURSORTOXML\s*\(\s*([^\s,]+)\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)",
            lambda m: f'CURSORTOXML({m.group(1)}, "{m.group(2)}")',
            s,
            flags=re.IGNORECASE,
        )

        # Traducir acceso a elementos de arreglo 1-based `laArr[i]` o `laArr[r, c]` a `__vfp_idx__(laArr, i, c)`
        s = re.sub(
            r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*([^\],]+?)(?:\s*,\s*([^\]]+?))?\s*\]",
            lambda m: (
                f"__vfp_idx__({m.group(1)}, {m.group(2)}, {m.group(3)})"
                if m.group(3)
                else f"__vfp_idx__({m.group(1)}, {m.group(2)})"
            ),
            s,
        )

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
        in_text_block = False

        for raw in raw_lines:
            stripped_raw = raw.strip()
            if in_text_block:
                if re.match(r"^ENDTEXT\b", stripped_raw, flags=re.IGNORECASE):
                    in_text_block = False
                    logical_lines.append("ENDTEXT")
                else:
                    logical_lines.append(raw)
                continue

            if re.match(r"^TEXT\s+TO\b", stripped_raw, flags=re.IGNORECASE):
                if buffer.strip():
                    logical_lines.append(buffer.strip())
                    buffer = ""
                logical_lines.append(stripped_raw)
                in_text_block = True
                continue

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
                self._try_depth += 1
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
                    self._try_depth -= 1
                    if finally_blk is not None:
                        self._exec_block(finally_blk)
                i = end_idx + 1
                continue

            # Estructura TEXT TO <var> [ADDITIVE] [TEXTMERGE] [NOSHOW] ... ENDTEXT
            m_txt = re.match(
                r"^TEXT\s+TO\s+([A-Za-z_][A-Za-z0-9_]*)(.*)$",
                line,
                flags=re.IGNORECASE,
            )
            if m_txt:
                var_name = m_txt.group(1)
                flags_str = (m_txt.group(2) or "").upper()
                is_additive = "ADDITIVE" in flags_str
                is_textmerge = "TEXTMERGE" in flags_str
                is_noshow = "NOSHOW" in flags_str
                text_lines: List[str] = []
                i += 1
                while i < n and not re.match(r"^ENDTEXT\b", lines[i].strip(), flags=re.IGNORECASE):
                    raw_tl = lines[i]
                    if is_textmerge or ("<<" in raw_tl and ">>" in raw_tl):
                        raw_tl = re.sub(
                            r"<<(.+?)>>",
                            lambda m: self.functions["transform"](self.eval_expr(m.group(1).strip())),
                            raw_tl,
                        )
                    text_lines.append(raw_tl)
                    i += 1
                merged_text = "\n".join(text_lines)
                if is_additive:
                    prev = str(self.current_vars().get(var_name.lower(), "") or "")
                    merged_text = prev + merged_text
                self.set_var(var_name, merged_text)
                if not is_noshow:
                    self.emit(merged_text)
                i += 1
                continue

            # Ejecutar sentencia individual
            try:
                self._exec_statement(line)
            except (_ReturnSignal, _LoopExit, _LoopContinue):
                raise
            except Exception as exc:
                if self._try_depth > 0:
                    raise
                self.last_error = (getattr(exc, "vfp_errno", 1098), str(exc), line)
                if self.on_error_cmd and not self._in_error_handler:
                    self._in_error_handler = True
                    try:
                        self.execute(self.on_error_cmd)
                    finally:
                        self._in_error_handler = False
                else:
                    raise
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

        # 16h. SCATTER NAME <obj_var> [BLANK]
        m_scatter = re.match(
            r"^SCATTER\s+NAME\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+(BLANK))?\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_scatter:
            cur = self._require_cursor("SCATTER")
            obj_var = m_scatter.group(1)
            is_blank = bool(m_scatter.group(2))
            props: Dict[str, Any] = {}
            for f in cur.fields:
                props[f.name] = f.default_value() if is_blank else cur.get_field(f.name)
            scatter_obj = VFPObject("ScatterRecord", props, {}, self)
            self.set_var(obj_var, scatter_obj)
            return

        # 16i. GATHER NAME <obj_var>
        m_gather = re.match(
            r"^GATHER\s+NAME\s+([A-Za-z_][A-Za-z0-9_]*)\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_gather:
            cur = self._require_cursor("GATHER")
            obj_var = m_gather.group(1)
            src_obj = self.eval_expr(obj_var)
            if isinstance(src_obj, VFPObject):
                for f in cur.fields:
                    if f.name in src_obj._props:
                        cur.set_field(f.name, src_obj._props[f.name])
            elif isinstance(src_obj, dict):
                for f in cur.fields:
                    if f.name in src_obj:
                        cur.set_field(f.name, src_obj[f.name])
            else:
                raise TypeError(f"GATHER NAME requiere un objeto válido en '{obj_var}'.")
            return

        # 16j. CALCULATE <agg_list> [FOR <cond>] TO <var_list>
        m_calc = re.match(
            r"^CALCULATE\s+(.+?)(?:\s+FOR\s+(.+?))?\s+TO\s+(.+)$",
            line,
            flags=re.IGNORECASE,
        )
        if m_calc:
            cur = self._require_cursor("CALCULATE")
            agg_specs = self._split_top_level(m_calc.group(1).strip(), ",")
            for_expr = m_calc.group(2).strip() if m_calc.group(2) else None
            target_vars = [v.strip() for v in self._split_top_level(m_calc.group(3).strip(), ",")]

            parsed_aggs: List[Tuple[str, Optional[str]]] = []
            for spec in agg_specs:
                m_fn = re.match(r"^(SUM|AVG|COUNT|MIN|MAX|CNT)\s*\((.*)\)\s*$", spec.strip(), flags=re.IGNORECASE)
                if not m_fn:
                    raise SyntaxError(f"Expresión de agregación inválida en CALCULATE: '{spec}'")
                op = m_fn.group(1).upper()
                if op == "CNT":
                    op = "COUNT"
                inner = m_fn.group(2).strip() or None
                parsed_aggs.append((op, inner))

            buckets: List[List[Any]] = [[] for _ in parsed_aggs]
            saved_area = self.wam.current_area
            self.wam.select_area(cur.alias)
            try:
                for r in cur.visible_recnos(self.wam.set_deleted):
                    cur.goto(r)
                    if for_expr and not bool(self.eval_expr(for_expr)):
                        continue
                    for idx, (op, inner) in enumerate(parsed_aggs):
                        if op == "COUNT" and not inner:
                            buckets[idx].append(1)
                        else:
                            val = self.eval_expr(inner or "1")
                            if val is not None:
                                buckets[idx].append(val)
            finally:
                self.wam.current_area = saved_area

            for idx, (op, _) in enumerate(parsed_aggs):
                if idx >= len(target_vars):
                    break
                vals = buckets[idx]
                if op == "COUNT":
                    res = len(vals)
                elif not vals:
                    res = 0
                elif op == "SUM":
                    res = sum(vals)
                elif op == "AVG":
                    res = sum(vals) / len(vals)
                elif op == "MIN":
                    res = min(vals)
                elif op == "MAX":
                    res = max(vals)
                else:
                    res = 0
                self.set_var(target_vars[idx], res)
            return

        # 16k. Transacciones: BEGIN TRANSACTION, END TRANSACTION, ROLLBACK
        if re.match(r"^BEGIN\s+TRANSACTION\b", line, flags=re.IGNORECASE):
            self.wam.begin_transaction()
            return

        if re.match(r"^END\s+TRANSACTION\b", line, flags=re.IGNORECASE):
            self.wam.end_transaction()
            return

        if re.match(r"^ROLLBACK\b", line, flags=re.IGNORECASE):
            self.wam.rollback()
            return

        # 16l. BUILD APP <salida.foxapp> FROM <proyecto.foxproj>
        m_build = re.match(
            r"^BUILD\s+APP\s+([^\s]+)\s+FROM\s+([^\s]+)\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_build:
            from .project import FoxProject

            app_out = m_build.group(1).strip("\"'")
            proj_in = m_build.group(2).strip("\"'")
            proj = FoxProject.from_file(proj_in)
            built_path = proj.build_app(app_out)
            self.emit(f"[FoxProject] Aplicación empaquetada en '{built_path}'")
            return

        # 16m. DIMENSION / DECLARE laArr[n] o laMat[r, c]
        m_dim = re.match(r"^(?:DIMENSION|DECLARE)\s+(.*)$", line, flags=re.IGNORECASE)
        if m_dim:
            for item in self._split_top_level(m_dim.group(1).strip(), ","):
                m_a = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*[\[\(]\s*(\d+)(?:\s*,\s*(\d+))?\s*[\]\)]$", item.strip())
                if not m_a:
                    raise SyntaxError(f"Declaración DIMENSION inválida: '{item}'")
                aname = m_a.group(1)
                rows_n = int(m_a.group(2))
                cols_n = int(m_a.group(3)) if m_a.group(3) else 0
                if cols_n > 0:
                    arr_val: Any = [[False for _ in range(cols_n)] for _ in range(rows_n)]
                else:
                    arr_val = [False for _ in range(rows_n)]
                self.set_var(aname, arr_val)
            return

        # 16n. COPY TO ARRAY <arr_name>
        m_cta = re.match(r"^COPY\s+TO\s+ARRAY\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", line, flags=re.IGNORECASE)
        if m_cta:
            cur = self._require_cursor("COPY TO ARRAY")
            self.set_var(m_cta.group(1), cur.copy_to_array(self.wam.set_deleted))
            return

        # 16o. APPEND FROM ARRAY <arr_name>
        m_afa = re.match(r"^APPEND\s+FROM\s+ARRAY\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", line, flags=re.IGNORECASE)
        if m_afa:
            cur = self._require_cursor("APPEND FROM ARRAY")
            arr_data = self.eval_expr(m_afa.group(1))
            cur.append_from_array(arr_data)
            return

        # 16p. ALTER TABLE / ALTER CURSOR <alias> ADD COLUMN / DROP COLUMN
        m_alt_add = re.match(
            r"^ALTER\s+(?:TABLE|CURSOR)\s+([A-Za-z_][A-Za-z0-9_]*)\s+ADD\s+(?:COLUMN\s+)?(.+)$",
            line,
            flags=re.IGNORECASE,
        )
        if m_alt_add:
            cur = self.wam.get_cursor(m_alt_add.group(1))
            if cur is None:
                raise RuntimeError(f"El cursor '{m_alt_add.group(1)}' no existe para ALTER TABLE.")
            for fdef in parse_schema_string(m_alt_add.group(2).strip()):
                cur.alter_add_column(fdef)
            return

        m_alt_drop = re.match(
            r"^ALTER\s+(?:TABLE|CURSOR)\s+([A-Za-z_][A-Za-z0-9_]*)\s+DROP\s+(?:COLUMN\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_alt_drop:
            cur = self.wam.get_cursor(m_alt_drop.group(1))
            if cur is None:
                raise RuntimeError(f"El cursor '{m_alt_drop.group(1)}' no existe para ALTER TABLE.")
            cur.alter_drop_column(m_alt_drop.group(2))
            return

        # 16q. SET ASSERTS ON|OFF y ASSERT <cond> [MESSAGE <msg>]
        m_set_ass = re.match(r"^SET\s+ASSERTS?\s+(ON|OFF)\s*$", line, flags=re.IGNORECASE)
        if m_set_ass:
            self.asserts_enabled = m_set_ass.group(1).upper() == "ON"
            return

        m_assert = re.match(r"^ASSERT\s+(.+?)(?:\s+MESSAGE\s+(.+))?\s*$", line, flags=re.IGNORECASE)
        if m_assert:
            if self.asserts_enabled and not bool(self.eval_expr(m_assert.group(1).strip())):
                msg = str(self.eval_expr(m_assert.group(2).strip())) if m_assert.group(2) else f"Fallo en ASSERT: {m_assert.group(1)}"
                raise AssertionError(msg)
            return

        # 16r. Vistas SQL Parametrizadas: CREATE SQL VIEW <vista> AS SELECT ...
        m_view = re.match(
            r"^CREATE\s+SQL\s+VIEW\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS\s+(SELECT\s+.+)$",
            line,
            flags=re.IGNORECASE,
        )
        if m_view:
            self.wam.create_sql_view(m_view.group(1), m_view.group(2).strip(), self.current_vars())
            return

        # 16s. Comandos de Menús: DEFINE MENU, DEFINE PAD, ON PAD, DEFINE POPUP, DEFINE BAR, ON SELECTION BAR, ACTIVATE POPUP
        m_def_menu = re.match(r"^DEFINE\s+MENU\s+([A-Za-z_][A-Za-z0-9_]*)\b", line, flags=re.IGNORECASE)
        if m_def_menu:
            from .foxmenu import FoxMenu

            mname = m_def_menu.group(1).lower()
            self.menus[mname] = FoxMenu(name=mname, interpreter=self)
            return

        m_def_pad = re.match(
            r"^DEFINE\s+PAD\s+([A-Za-z_][A-Za-z0-9_]*)\s+OF\s+([A-Za-z_][A-Za-z0-9_]*)\s+PROMPT\s+(.+)$",
            line,
            flags=re.IGNORECASE,
        )
        if m_def_pad:
            from .foxmenu import FoxMenu

            pad_name = m_def_pad.group(1).lower()
            menu_name = m_def_pad.group(2).lower()
            prompt_val = str(self.eval_expr(m_def_pad.group(3).strip()))
            menu_obj = self.menus.setdefault(menu_name, FoxMenu(name=menu_name, interpreter=self))
            menu_obj.define_pad(pad_name, prompt_val)
            return

        m_on_pad = re.match(
            r"^ON\s+PAD\s+([A-Za-z_][A-Za-z0-9_]*)\s+OF\s+([A-Za-z_][A-Za-z0-9_]*)\s+ACTIVATE\s+POPUP\s+([A-Za-z_][A-Za-z0-9_]*)\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_on_pad:
            from .foxmenu import FoxMenu

            pad_name = m_on_pad.group(1).lower()
            menu_name = m_on_pad.group(2).lower()
            popup_name = m_on_pad.group(3).lower()
            menu_obj = self.menus.setdefault(menu_name, FoxMenu(name=menu_name, interpreter=self))
            menu_obj.on_pad_activate_popup(pad_name, popup_name)
            return

        m_def_popup = re.match(r"^DEFINE\s+POPUP\s+([A-Za-z_][A-Za-z0-9_]*)\b", line, flags=re.IGNORECASE)
        if m_def_popup:
            from .foxmenu import FoxMenu

            popup_name = m_def_popup.group(1).lower()
            menu_obj = next(iter(self.menus.values()), None)
            if menu_obj is None:
                menu_obj = FoxMenu(name="_msysmenu", interpreter=self)
                self.menus["_msysmenu"] = menu_obj
            menu_obj.define_popup(popup_name)
            return

        m_def_bar = re.match(
            r"^DEFINE\s+BAR\s+(\d+)\s+OF\s+([A-Za-z_][A-Za-z0-9_]*)\s+PROMPT\s+(.+)$",
            line,
            flags=re.IGNORECASE,
        )
        if m_def_bar:
            from .foxmenu import FoxMenu

            bar_num = int(m_def_bar.group(1))
            popup_name = m_def_bar.group(2).lower()
            prompt_val = str(self.eval_expr(m_def_bar.group(3).strip()))
            menu_obj = next(iter(self.menus.values()), None)
            if menu_obj is None:
                menu_obj = FoxMenu(name="_msysmenu", interpreter=self)
                self.menus["_msysmenu"] = menu_obj
            menu_obj.define_bar(popup_name, bar_num, prompt_val)
            return

        m_on_sel_bar = re.match(
            r"^ON\s+SELECTION\s+BAR\s+(\d+)\s+OF\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.+)$",
            line,
            flags=re.IGNORECASE,
        )
        if m_on_sel_bar:
            from .foxmenu import FoxMenu

            bar_num = int(m_on_sel_bar.group(1))
            popup_name = m_on_sel_bar.group(2).lower()
            cmd_str = m_on_sel_bar.group(3).strip()
            menu_obj = next(iter(self.menus.values()), None)
            if menu_obj is None:
                menu_obj = FoxMenu(name="_msysmenu", interpreter=self)
                self.menus["_msysmenu"] = menu_obj
            menu_obj.on_selection_bar(popup_name, bar_num, cmd_str)
            return

        m_act_popup = re.match(
            r"^ACTIVATE\s+POPUP\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+BAR\s+(\d+))?\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m_act_popup:
            popup_name = m_act_popup.group(1).lower()
            bar_num_str = m_act_popup.group(2)
            for menu_obj in self.menus.values():
                if popup_name in menu_obj.popups:
                    if bar_num_str:
                        menu_obj.trigger_bar(popup_name, int(bar_num_str))
                    else:
                        self.emit(menu_obj.render_tui())
                    break
            return

        # 16t. ON ERROR [comando]
        m_on_err = re.match(r"^ON\s+ERROR(?:\s+(.*))?$", line, flags=re.IGNORECASE)
        if m_on_err:
            cmd = m_on_err.group(1).strip() if m_on_err.group(1) else ""
            self.on_error_cmd = cmd if cmd else None
            return

        # 16u. ERROR <expr>
        m_err_cmd = re.match(r"^ERROR\s+(.+)$", line, flags=re.IGNORECASE)
        if m_err_cmd and not re.match(r"^ERROR\s*\(", line, flags=re.IGNORECASE):
            raw_val = self.eval_expr(m_err_cmd.group(1).strip())
            if isinstance(raw_val, int):
                self.last_error = (raw_val, f"Error {raw_val}", line)
            else:
                self.last_error = (1098, str(raw_val), line)
            if self.on_error_cmd and not self._in_error_handler:
                self._in_error_handler = True
                try:
                    self.execute(self.on_error_cmd)
                finally:
                    self._in_error_handler = False
                return
            raise RuntimeError(self.last_error[1])

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

        # 18a. Asignación de elemento de arreglo 1-based (`laArr[1] = expr` o `laMat[2, 1] = expr`)
        m_arr_set = re.match(
            r"^([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*(.+?)(?:\s*,\s*(.+?))?\s*\]\s*=\s*(.+)$",
            line,
        )
        if m_arr_set:
            aname = m_arr_set.group(1).lower()
            idx1 = int(self.eval_expr(m_arr_set.group(2))) - 1
            idx2 = int(self.eval_expr(m_arr_set.group(3))) - 1 if m_arr_set.group(3) else None
            rhs_val = self.eval_expr(m_arr_set.group(4))
            arr_obj = self.current_vars().get(aname)
            if not isinstance(arr_obj, list):
                raise TypeError(f"'{aname}' no es un arreglo dimensionado.")
            if idx2 is not None:
                arr_obj[idx1][idx2] = rhs_val
            else:
                arr_obj[idx1] = rhs_val
            return

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

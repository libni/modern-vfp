"""
Biblioteca Estándar de Funciones Nativas de Visual FoxPro para FoxNext (Modern VFP).
"""

from __future__ import annotations
import calendar
import datetime
import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .cursor import WorkAreaManager


def build_vfp_functions(wam: WorkAreaManager) -> Dict[str, Callable[..., Any]]:
    """
    Construye el diccionario de funciones nativas (case-insensitive) vinculadas al WorkAreaManager.
    """

    def _resolve_cursor(alias_or_area: Any = None):
        if alias_or_area is None:
            return wam.current_cursor()
        return wam.get_cursor(alias_or_area)

    # --- Funciones de Cadenas (Strings) ---
    def fn_alltrim(s: Any, *chars: str) -> str:
        text = "" if s is None else str(s)
        if chars:
            return text.strip("".join(chars))
        return text.strip()

    def fn_ltrim(s: Any) -> str:
        return ("" if s is None else str(s)).lstrip()

    def fn_rtrim(s: Any) -> str:
        return ("" if s is None else str(s)).rstrip()

    def fn_upper(s: Any) -> str:
        return ("" if s is None else str(s)).upper()

    def fn_lower(s: Any) -> str:
        return ("" if s is None else str(s)).lower()

    def fn_proper(s: Any) -> str:
        return ("" if s is None else str(s)).title()

    def fn_len(s: Any) -> int:
        if isinstance(s, (list, dict, str)):
            return len(s)
        return len(str(s or ""))

    def fn_substr(s: Any, start: int, length: Optional[int] = None) -> str:
        text = "" if s is None else str(s)
        idx = max(0, int(start) - 1)  # VFP es 1-indexed
        if length is None:
            return text[idx:]
        return text[idx : idx + int(length)]

    def fn_left(s: Any, length: int) -> str:
        return ("" if s is None else str(s))[: max(0, int(length))]

    def fn_right(s: Any, length: int) -> str:
        n = max(0, int(length))
        if n == 0:
            return ""
        return ("" if s is None else str(s))[-n:]

    def fn_at(sub: Any, s: Any, occurrence: int = 1) -> int:
        needle = str(sub)
        haystack = str(s)
        if not needle:
            return 0
        pos = -1
        for _ in range(max(1, int(occurrence))):
            pos = haystack.find(needle, pos + 1)
            if pos == -1:
                return 0
        return pos + 1

    def fn_atc(sub: Any, s: Any, occurrence: int = 1) -> int:
        return fn_at(str(sub).lower(), str(s).lower(), occurrence)

    def fn_strtran(s: Any, old: Any, new: Any = "") -> str:
        return str(s).replace(str(old), str(new))

    def fn_chrtran(s: Any, from_chars: Any, to_chars: Any = "") -> str:
        src = str(from_chars)
        dst = str(to_chars)
        out = []
        for ch in str(s):
            idx = src.find(ch)
            if idx == -1:
                out.append(ch)
            elif idx < len(dst):
                out.append(dst[idx])
        return "".join(out)

    def fn_stuff(s: Any, start: int, delete_count: int, insert_str: Any) -> str:
        text = str(s)
        idx = max(0, int(start) - 1)
        del_n = max(0, int(delete_count))
        return text[:idx] + str(insert_str) + text[idx + del_n :]

    def fn_padl(val: Any, length: int, pad_char: str = " ") -> str:
        ch = (str(pad_char) or " ")[0]
        return str(val).rjust(int(length), ch)[: int(length)]

    def fn_padr(val: Any, length: int, pad_char: str = " ") -> str:
        ch = (str(pad_char) or " ")[0]
        return str(val).ljust(int(length), ch)[: int(length)]

    def fn_padc(val: Any, length: int, pad_char: str = " ") -> str:
        ch = (str(pad_char) or " ")[0]
        return str(val).center(int(length), ch)[: int(length)]

    def fn_space(n: int) -> str:
        return " " * max(0, int(n))

    def fn_replicate(s: Any, n: int) -> str:
        return str(s) * max(0, int(n))

    def fn_chr(code: int) -> str:
        return chr(int(code))

    def fn_asc(s: Any) -> int:
        text = str(s)
        return ord(text[0]) if text else 0

    def fn_str(num: Any, length: int = 10, decimals: int = 0) -> str:
        val = float(num or 0)
        w = int(length)
        d = int(decimals)
        if d > 0:
            return f"{val:>{w}.{d}f}"
        return f"{int(round(val)):>{w}d}"

    def fn_val(s: Any) -> float | int:
        if isinstance(s, (int, float)):
            return s
        text = str(s or "").strip()
        if not text:
            return 0
        m = []
        dot_seen = False
        for i, ch in enumerate(text):
            if ch in "+-" and i == 0:
                m.append(ch)
            elif ch.isdigit():
                m.append(ch)
            elif ch == "." and not dot_seen:
                dot_seen = True
                m.append(ch)
            else:
                break
        num_str = "".join(m)
        if not num_str or num_str in ("+", "-", "."):
            return 0
        f = float(num_str)
        return int(f) if not dot_seen else f

    def fn_transform(val: Any, fmt: Optional[str] = None) -> str:
        if val is None:
            return ".NULL."
        if isinstance(val, bool):
            return ".T." if val else ".F."
        if isinstance(val, datetime.date) and not isinstance(val, datetime.datetime):
            return val.isoformat()
        if isinstance(val, datetime.datetime):
            return val.strftime("%Y-%m-%d %H:%M:%S")
        if fmt:
            f_up = fmt.strip().upper()
            if f_up == "@!":
                return str(val).upper()
            if "$" in f_up or "9" in f_up or "," in f_up:
                try:
                    num = float(val)
                    decs = len(f_up.split(".")[1]) if "." in f_up else 2
                    prefix = "$" if "$" in f_up else ""
                    return f"{prefix}{num:,.{decs}f}"
                except (ValueError, TypeError):
                    pass
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        return str(val)

    # --- Funciones Numéricas ---
    def fn_round(num: Any, decimals: int = 0) -> float | int:
        d = int(decimals)
        r = round(float(num), d)
        return int(r) if d <= 0 else r

    def fn_int(num: Any) -> int:
        return int(float(num))

    def fn_abs(num: Any) -> float | int:
        return abs(num)

    def fn_mod(a: Any, b: Any) -> float | int:
        return a % b

    def fn_sqrt(num: Any) -> float:
        return math.sqrt(float(num))

    def fn_max(*args: Any) -> Any:
        return max(args)

    def fn_min(*args: Any) -> Any:
        return min(args)

    # --- Funciones Lógicas y Condicionales ---
    def fn_iif(cond: Any, true_val: Any, false_val: Any = False) -> Any:
        return true_val if bool(cond) else false_val

    def fn_icase(*args: Any) -> Any:
        for i in range(0, len(args) - 1, 2):
            if bool(args[i]):
                return args[i + 1]
        if len(args) % 2 == 1:
            return args[-1]
        return None

    def fn_nvl(val: Any, fallback: Any) -> Any:
        return fallback if val is None else val

    def fn_evl(val: Any, fallback: Any) -> Any:
        return fallback if fn_empty(val) else val

    def fn_isnull(val: Any) -> bool:
        return val is None

    def fn_empty(val: Any) -> bool:
        if val is None:
            return True
        if isinstance(val, bool):
            return not val
        if isinstance(val, (int, float)):
            return val == 0
        if isinstance(val, str):
            return len(val.strip()) == 0
        if isinstance(val, (list, dict, tuple, set)):
            return len(val) == 0
        return False

    def fn_between(val: Any, low: Any, high: Any) -> bool:
        return low <= val <= high

    def fn_inlist(val: Any, *candidates: Any) -> bool:
        return val in candidates

    def fn_isdigit(s: Any) -> bool:
        text = str(s or "").lstrip()
        return bool(text) and text[0].isdigit()

    def fn_isalpha(s: Any) -> bool:
        text = str(s or "").lstrip()
        return bool(text) and text[0].isalpha()

    def fn_vartype(val: Any) -> str:
        if val is None:
            return "X"
        if isinstance(val, bool):
            return "L"
        if isinstance(val, (int, float)):
            return "N"
        if isinstance(val, str):
            return "C"
        if isinstance(val, datetime.datetime):
            return "T"
        if isinstance(val, datetime.date):
            return "D"
        if isinstance(val, (dict, list)) or hasattr(val, "__vfp_class__"):
            return "O"
        return "U"

    # --- Funciones de Fecha y Hora ---
    def fn_date(year: Optional[int] = None, month: Optional[int] = None, day: Optional[int] = None) -> datetime.date:
        if year is not None and month is not None and day is not None:
            return datetime.date(int(year), int(month), int(day))
        return datetime.date.today()

    def fn_datetime(
        year: Optional[int] = None,
        month: Optional[int] = None,
        day: Optional[int] = None,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
    ) -> datetime.datetime:
        if year is not None and month is not None and day is not None:
            return datetime.datetime(int(year), int(month), int(day), int(hour), int(minute), int(second))
        return datetime.datetime.now().replace(microsecond=0)

    def fn_year(d: Any) -> int:
        return d.year if isinstance(d, (datetime.date, datetime.datetime)) else 0

    def fn_month(d: Any) -> int:
        return d.month if isinstance(d, (datetime.date, datetime.datetime)) else 0

    def fn_day(d: Any) -> int:
        return d.day if isinstance(d, (datetime.date, datetime.datetime)) else 0

    def fn_dow(d: Any) -> int:
        if not isinstance(d, (datetime.date, datetime.datetime)):
            return 0
        # En VFP: Domingo = 1, Lunes = 2, ..., Sábado = 7
        return ((d.weekday() + 1) % 7) + 1

    def fn_cdow(d: Any) -> str:
        if not isinstance(d, (datetime.date, datetime.datetime)):
            return ""
        return calendar.day_name[d.weekday()]

    def fn_cmonth(d: Any) -> str:
        if not isinstance(d, (datetime.date, datetime.datetime)):
            return ""
        return calendar.month_name[d.month]

    def fn_dtoc(d: Any) -> str:
        if isinstance(d, (datetime.date, datetime.datetime)):
            return d.strftime("%Y-%m-%d")
        return "  /  /  "

    def fn_dtos(d: Any) -> str:
        if isinstance(d, (datetime.date, datetime.datetime)):
            return d.strftime("%Y%m%d")
        return "        "

    def fn_ctod(s: Any) -> Optional[datetime.date]:
        text = str(s or "").strip().strip("{}").lstrip("^").strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d"):
            try:
                return datetime.datetime.strptime(text[:10], fmt).date()
            except ValueError:
                continue
        return None

    def fn_gomonth(d: Any, months: int) -> Optional[datetime.date]:
        if not isinstance(d, (datetime.date, datetime.datetime)):
            return None
        base = d.date() if isinstance(d, datetime.datetime) else d
        total_m = (base.year * 12 + (base.month - 1)) + int(months)
        ny = total_m // 12
        nm = (total_m % 12) + 1
        max_day = calendar.monthrange(ny, nm)[1]
        return datetime.date(ny, nm, min(base.day, max_day))

    # --- Funciones de Cursor y Área de Trabajo ---
    def fn_recno(alias: Any = None) -> int:
        cur = _resolve_cursor(alias)
        return cur.recno() if cur else 0

    def fn_reccount(alias: Any = None) -> int:
        cur = _resolve_cursor(alias)
        return cur.reccount() if cur else 0

    def fn_eof(alias: Any = None) -> bool:
        cur = _resolve_cursor(alias)
        return cur.eof if cur else True

    def fn_bof(alias: Any = None) -> bool:
        cur = _resolve_cursor(alias)
        return cur.bof if cur else True

    def fn_found(alias: Any = None) -> bool:
        cur = _resolve_cursor(alias)
        return cur.found if cur else False

    def fn_deleted(alias: Any = None) -> bool:
        cur = _resolve_cursor(alias)
        return cur.is_deleted() if cur else False

    def fn_used(alias: Any = None) -> bool:
        return _resolve_cursor(alias) is not None

    def fn_alias(area: Any = None) -> str:
        cur = _resolve_cursor(area)
        return cur.alias.upper() if cur else ""

    def fn_select(mode: int = 0) -> int:
        if int(mode) == 1:
            return wam.next_free_area()
        return wam.current_area

    def fn_fcount(alias: Any = None) -> int:
        cur = _resolve_cursor(alias)
        return len(cur.fields) if cur else 0

    def fn_field(num: int, alias: Any = None) -> str:
        cur = _resolve_cursor(alias)
        idx = int(num) - 1
        if cur and 0 <= idx < len(cur.fields):
            return cur.fields[idx].name.upper()
        return ""

    def fn_cursorsetprop(prop: str, value: Any = None, alias: Any = None) -> bool:
        cur = _resolve_cursor(alias)
        if not cur:
            return False
        if prop.strip().lower() == "buffering":
            return cur.set_buffering(int(value or 1))
        return True

    def fn_cursorgetprop(prop: str, alias: Any = None) -> Any:
        cur = _resolve_cursor(alias)
        if not cur:
            return None
        if prop.strip().lower() == "buffering":
            return cur.buffering
        return None

    def fn_tableupdate(rows_mode: Any = True, force: Any = True, alias: Any = None) -> bool:
        cur = _resolve_cursor(alias)
        return cur.table_update() if cur else False

    def fn_tablerevert(all_rows: Any = True, alias: Any = None) -> bool:
        cur = _resolve_cursor(alias)
        return cur.table_revert() if cur else False

    # --- Funciones de Archivos y JSON ---
    def fn_file(filepath: Any) -> bool:
        return Path(str(filepath)).is_file()

    def fn_filetostr(filepath: Any) -> str:
        return Path(str(filepath)).read_text(encoding="utf-8")

    def fn_strtofile(content: Any, filepath: Any, additive: Any = False) -> int:
        p = Path(str(filepath))
        text = str(content)
        mode = "a" if bool(additive) else "w"
        with open(p, mode, encoding="utf-8") as fp:
            fp.write(text)
        return len(text.encode("utf-8"))

    def fn_json_encode(obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False, default=str)

    def fn_json_decode(s: Any) -> Any:
        return json.loads(str(s))

    def fn_messagebox(msg: Any, flags: int = 0, title: str = "FoxNext") -> int:
        print(f"\n[MESSAGEBOX - {title}]: {msg}")
        return 1  # IDOK

    raw_map = {
        "alltrim": fn_alltrim,
        "trim": fn_rtrim,
        "ltrim": fn_ltrim,
        "rtrim": fn_rtrim,
        "upper": fn_upper,
        "lower": fn_lower,
        "proper": fn_proper,
        "len": fn_len,
        "substr": fn_substr,
        "left": fn_left,
        "right": fn_right,
        "at": fn_at,
        "atc": fn_atc,
        "strtran": fn_strtran,
        "chrtran": fn_chrtran,
        "stuff": fn_stuff,
        "padl": fn_padl,
        "padr": fn_padr,
        "padc": fn_padc,
        "space": fn_space,
        "replicate": fn_replicate,
        "chr": fn_chr,
        "asc": fn_asc,
        "str": fn_str,
        "val": fn_val,
        "transform": fn_transform,
        "round": fn_round,
        "int": fn_int,
        "abs": fn_abs,
        "mod": fn_mod,
        "sqrt": fn_sqrt,
        "max": fn_max,
        "min": fn_min,
        "iif": fn_iif,
        "icase": fn_icase,
        "nvl": fn_nvl,
        "evl": fn_evl,
        "isnull": fn_isnull,
        "empty": fn_empty,
        "between": fn_between,
        "inlist": fn_inlist,
        "isdigit": fn_isdigit,
        "isalpha": fn_isalpha,
        "vartype": fn_vartype,
        "type": fn_vartype,
        "date": fn_date,
        "datetime": fn_datetime,
        "year": fn_year,
        "month": fn_month,
        "day": fn_day,
        "dow": fn_dow,
        "cdow": fn_cdow,
        "cmonth": fn_cmonth,
        "dtoc": fn_dtoc,
        "dtos": fn_dtos,
        "ctod": fn_ctod,
        "gomonth": fn_gomonth,
        "recno": fn_recno,
        "reccount": fn_reccount,
        "eof": fn_eof,
        "bof": fn_bof,
        "found": fn_found,
        "deleted": fn_deleted,
        "used": fn_used,
        "alias": fn_alias,
        "select": fn_select,
        "fcount": fn_fcount,
        "fldcount": fn_fcount,
        "field": fn_field,
        "cursorsetprop": fn_cursorsetprop,
        "cursorgetprop": fn_cursorgetprop,
        "tableupdate": fn_tableupdate,
        "tablerevert": fn_tablerevert,
        "file": fn_file,
        "filetostr": fn_filetostr,
        "strtofile": fn_strtofile,
        "jsonencode": fn_json_encode,
        "jsondecode": fn_json_decode,
        "messagebox": fn_messagebox,
    }
    return raw_map

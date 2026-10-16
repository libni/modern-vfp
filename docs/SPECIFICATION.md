# Especificación Técnica de FoxNext (Modern VFP)

## 1. Arquitectura de Áreas de Trabajo (Work Areas) y Cursores

En Visual FoxPro clásico, el corazón del entorno de datos son las **Áreas de Trabajo (Work Areas)** numeradas del `1` al `32767`, cada una asociada a un **Alias** (por ejemplo, `clientes`, `facturas`, `curResumen`).

En **FoxNext**, este modelo se preserva al 100% pero sobre memoria de 64 bits y respaldado por un motor SQL relacional en memoria:

### 1.1. Tipos de Datos Nativos del Cursor
| Código | Tipo VFP | Representación en FoxNext (64-bit) | Valor por Defecto (`APPEND BLANK`) |
| :---: | :--- | :--- | :--- |
| `I` | Integer | `int64` (Sin límite de 32-bit) | `0` |
| `N(w,d)` / `F` / `B` | Numeric / Float / Double | `float64` / `Decimal` exacto | `0.0` |
| `Y` | Currency | `Decimal` (4 decimales fijos sin error de punto flotante) | `0.0000` |
| `C(n)` / `V(n)` | Character / Varchar | `str` UTF-8 nativo | `""` |
| `M` | Memo | `str` UTF-8 de longitud arbitraria (sin archivo `.fpt` frágil) | `""` |
| `L` | Logical | `bool` (`.T.` / `.F.`) | `.F.` (`False`) |
| `D` | Date | `datetime.date` (`{^YYYY-MM-DD}`) | `None` (Fecha vacía `{  /  /  }`) |
| `T` | DateTime | `datetime.datetime` ISO-8601 | `None` |
| `J` | JSON (Extensión Moderna) | `dict` / `list` nativo serializable | `{}` |

### 1.2. Estados del Puntero de Registro
Cada cursor mantiene su propio estado de navegación:
- `RECNO()`: Número de registro físico actual (1-based). Si el cursor está vacío, devuelve `1`; si está en `EOF()`, devuelve `RECCOUNT() + 1`.
- `RECCOUNT()`: Total de registros físicos en el cursor.
- `BOF()` y `EOF()`: Indicadores de principio y fin de archivo.
- `FOUND()`: Resultado booleano de la última operación `LOCATE`, `CONTINUE` o `SEEK`.
- `DELETED()`: Estado de borrado lógico del registro actual (respeta `SET DELETED ON | OFF`).

### 1.3. Buffering Transaccional (`CURSORSETPROP`)
Soporte para almacenamiento en búfer optimista de registros y tablas:
- `Buffering = 1` (Directo: los cambios con `REPLACE` se aplican inmediatamente).
- `Buffering = 5` (Optimista de Tabla: los cambios quedan en memoria intermedia hasta invocar `TABLEUPDATE(.T.)`, o se descartan con `TABLEREVERT(.T.)`).

---

## 2. Gramática del Lenguaje (xBase Modernizado)

### 2.1. Reglas Léxicas
- **Insensibilidad a mayúsculas/minúsculas** en palabras clave, comandos, funciones, nombres de variables y campos (`SELECT`, `Select`, `select` son idénticos).
- **Continuación de línea:** El carácter `;` al final de una línea concatena la siguiente línea física en una sola instrucción lógica.
- **Comentarios:**
  - Línea completa que comienza con `*` o `NOTE`.
  - Comentario en línea iniciado con `&&`.
- **Literales Especiales:**
  - Booleanos: `.T.`, `.t.`, `.Y.`, `.F.`, `.f.`, `.N.`.
  - Nulo: `.NULL.`.
  - Fechas estrictas Year-2000+: `{^2026-10-16}` o `{^2026-10-16 14:30:00}`.
  - Cadenas: delimitadas por `"..."`, `'...'` o `[...]`.
- **Sustitución de Macros:** `&lcVariable` expande el contenido de `lcVariable` en tiempo de ejecución antes de evaluar la sentencia.

### 2.2. Acceso a Campos vs. Variables
FoxNext respeta la regla de resolución de nombres de VFP:
1. Si se especifica `alias.campo` o `alias->campo`, se accede directamente al campo del cursor `alias`.
2. Si se especifica `m.variable`, se accede inequívocamente a la variable de memoria (`m.` = memory).
3. Si se escribe un identificador simple `nombre`:
   - Primero se busca si existe un campo `nombre` en el cursor del área de trabajo activa (`SELECT()`).
   - Si no existe en el cursor activo, se resuelve como variable en el alcance local/privado/público.

---

## 3. Especificación de Formularios `.foxform`

Los archivos `.foxform` reemplazan a los binarios `.scx`/`.sct` con un documento estructurado legible por Git:

```json
{
  "form": {
    "name": "frmClientes",
    "caption": "Gestión de Clientes - FoxNext",
    "width": 720,
    "height": 480,
    "dataEnvironment": {
      "cursors": [
        {
          "alias": "clientes",
          "schema": "id I, nombre C(60), email C(80), saldo Y, activo L"
        }
      ]
    },
    "controls": [
      {
        "type": "TextBox",
        "name": "txtNombre",
        "caption": "Nombre:",
        "controlSource": "clientes.nombre"
      },
      {
        "type": "CheckBox",
        "name": "chkActivo",
        "caption": "Cliente Activo",
        "controlSource": "clientes.activo"
      },
      {
        "type": "Grid",
        "name": "grdClientes",
        "recordSource": "clientes"
      },
      {
        "type": "Button",
        "name": "btnGuardar",
        "caption": "Guardar Cambios",
        "onClick": "TABLEUPDATE(.T., .T., 'clientes')"
      }
    ],
    "methods": {
      "Init": "SELECT clientes\nGO TOP",
      "Valid": "RETURN !EMPTY(clientes.nombre)"
    }
  }
}
```

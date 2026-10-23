"""
Motor de Recorrido Jerárquico y Árboles (Bill of Materials / BOM) (`modern_vfp/graph.py`) para FoxNext.
Permite explotar estructuras jerárquicas (planes contables, organigramas, recetas de producción):
- Genera cursores planos con `depth`, `path` jerárquico y bandera `is_leaf`
- Comando: `EXPLODE TREE <alias> PARENT <col_padre> CHILD <col_hijo> [ROOT <nodo_raiz>] [INTO CURSOR <res_alias>]`
- Función: `TREEPATH(cAlias, cColPadre, cColHijo, eNodo)` -> "/1/4/9"
- Función: `TREECHILDREN(cAlias, cColPadre, cColHijo, eNodo [, lRecursivo])`
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple

from .cursor import Cursor, FieldDef


def explode_tree(
    cur: Cursor,
    parent_col: str,
    child_col: str,
    root_val: Any = None,
    into_alias: str = "tree_result",
    set_deleted_on: bool = False,
) -> Cursor:
    """
    Realiza un recorrido en profundidad (DFS) de una estructura jerárquica y construye
    un nuevo cursor con profundidad (`depth`), ruta (`path`) y estado (`is_leaf`).
    """
    p_col = parent_col.lower().strip()
    c_col = child_col.lower().strip()

    # Mapear hijos por padre: parent_val -> list of record dicts
    children_map: Dict[Any, List[Dict[str, Any]]] = {}
    all_parents: Set[Any] = set()
    all_children: Set[Any] = set()

    vis = cur.visible_recnos(set_deleted_on)
    for r in vis:
        row = dict(cur.records[r - 1])
        p_val = row.get(p_col)
        c_val = row.get(c_col)

        # Normalizar 0 o "" a None si representan la raíz
        if p_val in (0, "", "0"):
            p_val = None

        children_map.setdefault(p_val, []).append(row)
        if p_val is not None:
            all_parents.add(p_val)
        if c_val is not None:
            all_children.add(c_val)

    # Identificar raíces
    if root_val is not None:
        roots = children_map.get(root_val, [])
    else:
        # Aquellos cuyo padre es None o cuyo padre no existe como hijo en ninguna fila
        roots = list(children_map.get(None, []))
        for p, rows in children_map.items():
            if p is not None and p not in all_children:
                roots.extend(rows)

    out_fields = [
        FieldDef("depth", "I", 10, 0),
        FieldDef("tree_path", "C", 100, 0),
        FieldDef("is_leaf", "L", 1, 0),
    ] + list(cur.fields)
    out_cur = Cursor(into_alias.lower().strip(), out_fields)

    def _traverse(node_row: Dict[str, Any], current_depth: int, parent_path: str) -> None:
        c_val = node_row.get(c_col)
        curr_path = f"{parent_path}/{c_val}"
        kids = children_map.get(c_val, [])
        is_leaf = len(kids) == 0

        row_data = dict(node_row)
        row_data["depth"] = current_depth
        row_data["tree_path"] = curr_path
        row_data["is_leaf"] = is_leaf
        out_cur.append_dict(row_data)

        for k in kids:
            _traverse(k, current_depth + 1, curr_path)

    for r_node in roots:
        _traverse(r_node, 1, "")

    out_cur.go_top()
    return out_cur


def get_tree_path(
    cur: Cursor,
    parent_col: str,
    child_col: str,
    node_val: Any,
    set_deleted_on: bool = False,
) -> str:
    """Reconstruye la ruta ascendente desde un nodo hacia la raíz."""
    p_col = parent_col.lower().strip()
    c_col = child_col.lower().strip()

    # child -> parent map
    child_to_parent: Dict[Any, Any] = {}
    for r in cur.visible_recnos(set_deleted_on):
        row = cur.records[r - 1]
        c = row.get(c_col)
        p = row.get(p_col)
        if c is not None:
            child_to_parent[c] = p

    path_nodes: List[str] = []
    curr: Any = node_val
    visited: Set[Any] = set()

    while curr is not None and curr not in visited and curr in child_to_parent:
        visited.add(curr)
        path_nodes.append(str(curr))
        curr = child_to_parent.get(curr)
        if curr in (0, "", "0"):
            break

    path_nodes.reverse()
    return "/" + "/".join(path_nodes) if path_nodes else f"/{node_val}"


def get_tree_children(
    cur: Cursor,
    parent_col: str,
    child_col: str,
    node_val: Any,
    recursive: bool = True,
    set_deleted_on: bool = False,
) -> List[Any]:
    """Obtiene la lista de identificadores descendientes de un nodo."""
    p_col = parent_col.lower().strip()
    c_col = child_col.lower().strip()

    parent_to_children: Dict[Any, List[Any]] = {}
    for r in cur.visible_recnos(set_deleted_on):
        row = cur.records[r - 1]
        p = row.get(p_col)
        c = row.get(c_col)
        if p is not None and c is not None:
            parent_to_children.setdefault(p, []).append(c)

    results: List[Any] = []

    def _collect(curr_val: Any) -> None:
        direct = parent_to_children.get(curr_val, [])
        for d in direct:
            results.append(d)
            if recursive:
                _collect(d)

    _collect(node_val)
    return results

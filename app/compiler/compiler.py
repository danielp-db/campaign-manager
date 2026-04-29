"""Compile a no-code DAG to a single Databricks SQL statement.

Each node becomes a CTE. The final node's SQL is emitted as the SELECT (for preview)
or wrapped in CREATE OR REPLACE TABLE (for materialization).

This is a demo compiler: predicates and expressions are pasted into SQL verbatim.
A production compiler would parse and re-emit them with proper sanitization.
"""
from __future__ import annotations

import re
from collections import defaultdict, deque

from app.compiler.dag import Dag, Node


class CompileError(ValueError):
    pass


_FORBIDDEN_TOKENS = (";", "--")


def _check_safe(text: str, label: str) -> None:
    for tok in _FORBIDDEN_TOKENS:
        if tok in text:
            raise CompileError(f"forbidden token {tok!r} in {label}")


def _topo_sort(dag: Dag) -> list[Node]:
    indeg: dict[str, int] = defaultdict(int)
    children: dict[str, list[str]] = defaultdict(list)
    for n in dag.nodes:
        indeg.setdefault(n.id, 0)
    for e in dag.edges:
        indeg[e.target] += 1
        children[e.source].append(e.target)

    q = deque([nid for nid, d in indeg.items() if d == 0])
    out: list[Node] = []
    while q:
        nid = q.popleft()
        out.append(dag.by_id(nid))
        for c in children[nid]:
            indeg[c] -= 1
            if indeg[c] == 0:
                q.append(c)
    if len(out) != len(dag.nodes):
        raise CompileError("DAG contains a cycle")
    return out


def _cte_name(node_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", node_id)
    return f"n_{safe}"


def _source_uc_sql(node: Node) -> str:
    table = node.config.get("table_fqn") or ""
    if not re.fullmatch(r"[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+", table):
        raise CompileError(f"source_uc {node.id}: invalid table_fqn {table!r}")
    return f"SELECT * FROM {table}"


def _source_file_sql(node: Node) -> str:
    path = node.config.get("volume_path") or ""
    fmt = (node.config.get("file_format") or "csv").lower()
    if not path.startswith("/Volumes/"):
        raise CompileError(f"source_file {node.id}: volume_path must start with /Volumes/")
    if fmt not in {"csv", "xlsx"}:
        raise CompileError(f"source_file {node.id}: unsupported format {fmt}")
    _check_safe(path, f"source_file {node.id} path")

    options_map = {"header": "true"}
    if fmt == "csv":
        options_map["inferSchema"] = "true"
    extra = node.config.get("options") or {}
    for k, v in extra.items():
        _check_safe(str(k), f"source_file {node.id} option key")
        _check_safe(str(v), f"source_file {node.id} option value")
        options_map[str(k)] = str(v)

    options_clause = ", ".join(f"{k} => '{v}'" for k, v in options_map.items())
    return f"SELECT * FROM read_files('{path}', format => '{fmt}', {options_clause})"


def _filter_sql(node: Node, parent_cte: str) -> str:
    predicate = node.config.get("predicate") or "TRUE"
    _check_safe(predicate, f"filter {node.id} predicate")
    return f"SELECT * FROM {parent_cte} WHERE {predicate}"


def _derive_sql(node: Node, parent_cte: str) -> str:
    columns = node.config.get("columns") or []
    if not columns:
        return f"SELECT * FROM {parent_cte}"
    parts = ["*"]
    for col in columns:
        name = col.get("name", "")
        expr = col.get("expression", "")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise CompileError(f"derive {node.id}: invalid column name {name!r}")
        _check_safe(expr, f"derive {node.id} expression for {name}")
        parts.append(f"({expr}) AS {name}")
    return f"SELECT {', '.join(parts)} FROM {parent_cte}"


def _rewrite_join_aliases(text: str) -> str:
    """Users write `left.col` / `right.col`; Spark reserves those words.
    Rewrite to `lhs.col` / `rhs.col` for emission."""
    out = re.sub(r"\bleft\.", "lhs.", text)
    out = re.sub(r"\bright\.", "rhs.", out)
    return out


def _join_sql(node: Node, left_cte: str, right_cte: str) -> str:
    join_type = (node.config.get("join_type") or "inner").upper()
    if join_type not in {"INNER", "LEFT", "RIGHT", "FULL"}:
        raise CompileError(f"join {node.id}: invalid join_type")
    on_clause = node.config.get("on") or ""
    if not on_clause:
        raise CompileError(f"join {node.id}: missing on clause")
    _check_safe(on_clause, f"join {node.id} on clause")
    select_cols = node.config.get("select_columns") or "*"
    _check_safe(select_cols, f"join {node.id} select_columns")
    on_rewritten = _rewrite_join_aliases(on_clause)
    select_rewritten = _rewrite_join_aliases(select_cols)
    return (
        f"SELECT {select_rewritten} FROM {left_cte} AS lhs "
        f"{join_type} JOIN {right_cte} AS rhs ON {on_rewritten}"
    )


def _sink_sql(parent_cte: str) -> str:
    return f"SELECT * FROM {parent_cte}"


def _node_to_cte(node: Node, parent_ctes: list[tuple[str, str | None]]) -> str:
    """parent_ctes is a list of (cte_name, side) tuples."""
    if node.type == "source_uc":
        return _source_uc_sql(node)
    if node.type == "source_file":
        return _source_file_sql(node)

    if node.type == "filter":
        if len(parent_ctes) != 1:
            raise CompileError(f"filter {node.id} requires exactly 1 input")
        return _filter_sql(node, parent_ctes[0][0])

    if node.type == "derive":
        if len(parent_ctes) != 1:
            raise CompileError(f"derive {node.id} requires exactly 1 input")
        return _derive_sql(node, parent_ctes[0][0])

    if node.type == "join":
        if len(parent_ctes) != 2:
            raise CompileError(f"join {node.id} requires exactly 2 inputs")
        sides = {p[1]: p[0] for p in parent_ctes}
        if "left" not in sides or "right" not in sides:
            raise CompileError(f"join {node.id} edges must declare side=left and side=right")
        return _join_sql(node, sides["left"], sides["right"])

    if node.type == "sink":
        if len(parent_ctes) != 1:
            raise CompileError(f"sink {node.id} requires exactly 1 input")
        return _sink_sql(parent_ctes[0][0])

    raise CompileError(f"unknown node type {node.type}")


def _validate(dag: Dag) -> None:
    ids = [n.id for n in dag.nodes]
    if len(set(ids)) != len(ids):
        raise CompileError("duplicate node ids")
    nodes_by_id = {n.id: n for n in dag.nodes}
    for e in dag.edges:
        if e.source not in nodes_by_id:
            raise CompileError(f"edge references unknown source {e.source}")
        if e.target not in nodes_by_id:
            raise CompileError(f"edge references unknown target {e.target}")
        target = nodes_by_id[e.target]
        if target.type == "join" and e.side not in {"left", "right"}:
            raise CompileError(f"edge into join {target.id} missing side")


def _build_with_clause(ordered: list[Node], dag: Dag) -> tuple[str, str]:
    """Returns (with_sql, terminal_cte_name)."""
    cte_lines: list[str] = []
    for node in ordered:
        if node.type == "sink":
            continue  # sink is wrapped externally
        parents = [
            (_cte_name(e.source), e.side) for e in dag.parents(node.id)
        ]
        body = _node_to_cte(node, parents)
        cte_lines.append(f"{_cte_name(node.id)} AS (\n  {body}\n)")
    terminal = ordered[-1]
    if terminal.type == "sink":
        parents = [(_cte_name(e.source), e.side) for e in dag.parents(terminal.id)]
        terminal_cte = parents[0][0]
    else:
        terminal_cte = _cte_name(terminal.id)
    with_sql = "WITH " + ",\n".join(cte_lines) if cte_lines else ""
    return with_sql, terminal_cte


def compile_preview(dag: Dag, limit: int = 200) -> str:
    """Compile to a SELECT statement (no materialization). Used for previews."""
    _validate(dag)
    ordered = _topo_sort(dag)
    # Strip sink for preview
    ordered_no_sink = [n for n in ordered if n.type != "sink"]
    if not ordered_no_sink:
        raise CompileError("DAG has no executable nodes")
    with_sql, terminal_cte = _build_with_clause(ordered_no_sink, dag)
    return f"{with_sql}\nSELECT * FROM {terminal_cte} LIMIT {int(limit)}".strip()


def compile_dag(dag: Dag, results_table: str) -> str:
    """Compile to a CREATE OR REPLACE TABLE statement that materializes the sink."""
    _validate(dag)
    if not re.fullmatch(r"[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+", results_table):
        raise CompileError(f"invalid results_table {results_table!r}")

    sinks = [n for n in dag.nodes if n.type == "sink"]
    if len(sinks) != 1:
        raise CompileError(f"DAG must have exactly one sink (found {len(sinks)})")

    ordered = _topo_sort(dag)
    with_sql, terminal_cte = _build_with_clause(ordered, dag)
    body = f"{with_sql}\nSELECT * FROM {terminal_cte}".strip()
    return f"CREATE OR REPLACE TABLE {results_table} AS\n{body}"

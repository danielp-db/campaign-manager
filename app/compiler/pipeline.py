"""Pipeline model + SQL compiler.

A Pipeline is an ordered list of named Steps. Each Step compiles to one CTE in
the final SQL statement; the last Step's output is what gets materialized.

Steps reference earlier Steps by name — no edges, no graph topology, just a
list. Validation enforces that every reference points to an earlier Step.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class CompileError(ValueError):
    pass


# --- step models ----------------------------------------------------------


class _StepBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str = Field(..., min_length=1)


class DatasetStep(_StepBase):
    op: Literal["dataset"] = "dataset"
    source: Literal["uc", "file"]
    table_fqn: str | None = None
    file_path: str | None = None
    file_format: Literal["csv", "xlsx"] = "csv"


class FilterStep(_StepBase):
    op: Literal["filter"] = "filter"
    from_: str = Field(..., alias="from")
    column: str
    operator: Literal[">", ">=", "<", "<=", "=", "!=", "LIKE", "IS NULL", "IS NOT NULL", "IN"]
    value: str = ""


class FieldStep(_StepBase):
    op: Literal["field"] = "field"
    from_: str = Field(..., alias="from")
    new_field_name: str
    expression: str


class SelectColumn(BaseModel):
    column: str
    alias: str = ""


class SelectStep(_StepBase):
    op: Literal["select"] = "select"
    from_: str = Field(..., alias="from")
    columns: list[SelectColumn]


class JoinKey(BaseModel):
    left: str
    right: str


class JoinStep(_StepBase):
    op: Literal["join"] = "join"
    left: str
    right: str
    join_type: Literal["INNER", "LEFT", "RIGHT", "FULL"] = "INNER"
    keys: list[JoinKey]


class UnionStep(_StepBase):
    op: Literal["union"] = "union"
    left: str
    right: str


Step = Annotated[
    Union[DatasetStep, FilterStep, FieldStep, SelectStep, JoinStep, UnionStep],
    Field(discriminator="op"),
]


class Pipeline(BaseModel):
    steps: list[Step] = Field(default_factory=list)

    def names(self) -> list[str]:
        return [s.name for s in self.steps]

    def by_name(self, name: str) -> Step | None:
        return next((s for s in self.steps if s.name == name), None)


# --- compilation helpers --------------------------------------------------


_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FQN_RE = re.compile(r"^[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")
_FORBIDDEN = (";", "--")


def _check_safe(text: str, label: str) -> None:
    for tok in _FORBIDDEN:
        if tok in (text or ""):
            raise CompileError(f"forbidden token {tok!r} in {label}")


def _check_ident(name: str, label: str) -> None:
    if not _NAME_RE.match(name or ""):
        raise CompileError(f"invalid identifier ({label}): {name!r}")


def _quote_literal(v: str) -> str:
    s = (v or "").strip()
    if s == "":
        return "''"
    if re.match(r"^-?\d+(\.\d+)?$", s):
        return s
    if s.upper() in ("TRUE", "FALSE", "NULL"):
        return s.upper()
    return "'" + s.replace("'", "''") + "'"


def _step_sql(step: Step) -> str:
    if isinstance(step, DatasetStep):
        if step.source == "uc":
            if not step.table_fqn or not _FQN_RE.match(step.table_fqn):
                raise CompileError(
                    f"dataset {step.name}: invalid table_fqn {step.table_fqn!r}"
                )
            return f"SELECT * FROM {step.table_fqn}"
        if not step.file_path or not step.file_path.startswith("/Volumes/"):
            raise CompileError(
                f"dataset {step.name}: file_path must start with /Volumes/"
            )
        _check_safe(step.file_path, "file_path")
        opts = "header => 'true'"
        if step.file_format == "csv":
            opts += ", inferSchema => 'true'"
        return (
            f"SELECT * FROM read_files('{step.file_path}', "
            f"format => '{step.file_format}', {opts})"
        )

    if isinstance(step, FilterStep):
        _check_ident(step.column, f"filter {step.name} column")
        _check_ident(step.from_, f"filter {step.name} from")
        if step.operator in ("IS NULL", "IS NOT NULL"):
            return f"SELECT * FROM {step.from_} WHERE {step.column} {step.operator}"
        if step.operator == "IN":
            _check_safe(step.value, f"filter {step.name} value")
            return f"SELECT * FROM {step.from_} WHERE {step.column} IN ({step.value})"
        return (
            f"SELECT * FROM {step.from_} "
            f"WHERE {step.column} {step.operator} {_quote_literal(step.value)}"
        )

    if isinstance(step, FieldStep):
        _check_ident(step.new_field_name, f"field {step.name} new_field_name")
        _check_ident(step.from_, f"field {step.name} from")
        _check_safe(step.expression, f"field {step.name} expression")
        if not step.expression.strip():
            raise CompileError(f"field {step.name}: expression is empty")
        return (
            f"SELECT *, ({step.expression}) AS {step.new_field_name} FROM {step.from_}"
        )

    if isinstance(step, SelectStep):
        _check_ident(step.from_, f"select {step.name} from")
        if not step.columns:
            raise CompileError(f"select {step.name}: must select at least one column")
        cols: list[str] = []
        for c in step.columns:
            _check_ident(c.column, f"select {step.name} column")
            if c.alias:
                _check_ident(c.alias, f"select {step.name} alias")
                cols.append(f"{c.column} AS {c.alias}")
            else:
                cols.append(c.column)
        return f"SELECT {', '.join(cols)} FROM {step.from_}"

    if isinstance(step, JoinStep):
        _check_ident(step.left, f"join {step.name} left")
        _check_ident(step.right, f"join {step.name} right")
        if not step.keys:
            raise CompileError(f"join {step.name}: must specify at least one join key")
        on_parts: list[str] = []
        for k in step.keys:
            _check_ident(k.left, f"join {step.name} key.left")
            _check_ident(k.right, f"join {step.name} key.right")
            on_parts.append(f"lhs.{k.left} = rhs.{k.right}")
        return (
            f"SELECT lhs.*, rhs.* FROM {step.left} AS lhs "
            f"{step.join_type} JOIN {step.right} AS rhs ON {' AND '.join(on_parts)}"
        )

    if isinstance(step, UnionStep):
        _check_ident(step.left, f"union {step.name} left")
        _check_ident(step.right, f"union {step.name} right")
        return f"SELECT * FROM {step.left} UNION ALL SELECT * FROM {step.right}"

    raise CompileError(f"unknown step type: {type(step).__name__}")


def _validate(p: Pipeline) -> None:
    if not p.steps:
        raise CompileError("Pipeline has no steps.")
    seen: set[str] = set()
    for s in p.steps:
        _check_ident(s.name, "step name")
        if s.name in seen:
            raise CompileError(f"duplicate step name: {s.name}")
        seen.add(s.name)
    upstream: set[str] = set()
    for s in p.steps:
        refs: list[tuple[str, str]] = []
        if isinstance(s, (FilterStep, FieldStep, SelectStep)):
            refs.append(("from", s.from_))
        elif isinstance(s, (JoinStep, UnionStep)):
            refs.append(("left", s.left))
            refs.append(("right", s.right))
        for kind, ref in refs:
            if ref not in upstream:
                raise CompileError(
                    f"step {s.name}: {kind} references unknown step {ref!r} "
                    f"(must be defined earlier)"
                )
        upstream.add(s.name)


# --- public entry points --------------------------------------------------


def _cte_block(steps: list[Step]) -> str:
    cte_lines = [f"  {s.name} AS (\n    {_step_sql(s)}\n  )" for s in steps]
    return "WITH\n" + ",\n".join(cte_lines)


def compile_pipeline(p: Pipeline, results_table: str) -> str:
    """Compile to a CREATE OR REPLACE TABLE statement."""
    _validate(p)
    if not _FQN_RE.match(results_table):
        raise CompileError(f"invalid results_table: {results_table!r}")
    last = p.steps[-1]
    return (
        f"CREATE OR REPLACE TABLE {results_table} AS\n"
        f"{_cte_block(p.steps)}\n"
        f"SELECT * FROM {last.name}"
    )


def compile_pipeline_preview(
    p: Pipeline, target_step: str | None = None, limit: int = 200
) -> str:
    """Compile to a SELECT preview ending at `target_step` (default: last)."""
    _validate(p)
    if target_step is None:
        sub = p.steps
    else:
        idx = next((i for i, s in enumerate(p.steps) if s.name == target_step), -1)
        if idx == -1:
            raise CompileError(f"unknown step: {target_step}")
        sub = p.steps[: idx + 1]
    return (
        f"{_cte_block(sub)}\n"
        f"SELECT * FROM {sub[-1].name} LIMIT {int(limit)}"
    )

"""Resolve the column list of any TemporaryDataSet (step) in a pipeline.

Two paths:
  - Fast: Dataset on UC → query information_schema (cheap).
  - Slow: anything else → compile pipeline up to and including the step,
    add LIMIT 0, run on the warehouse, read the description.

Used by the Logic-tab forms to populate column dropdowns.
"""
from __future__ import annotations

import logging

from app.compiler import Pipeline, compile_pipeline_preview
from app.compiler.pipeline import CompileError
from app.services import uc

log = logging.getLogger(__name__)


def get_step_columns(pipeline_data: dict | None, step_name: str | None) -> list[str]:
    if not pipeline_data or not step_name:
        return []
    steps = pipeline_data.get("steps") or []
    target = next((s for s in steps if s.get("name") == step_name), None)
    if not target:
        return []

    # Fast path: UC dataset
    if target.get("op") == "dataset" and target.get("source") == "uc":
        table = target.get("table_fqn")
        if not table:
            return []
        try:
            cols = uc.list_columns(table)
            return [c["column_name"] for c in cols]
        except Exception as exc:
            log.warning("columns: list_columns(%s) failed: %s", table, exc)
            return []

    # Slow path: compile and LIMIT 0
    try:
        pipeline = Pipeline.model_validate(pipeline_data)
        sql = compile_pipeline_preview(pipeline, target_step=step_name, limit=0)
    except (CompileError, Exception) as exc:
        log.info("columns: compile preview for %r failed: %s", step_name, exc)
        return []
    try:
        df = uc.query_df(sql)
        return df.columns.tolist()
    except Exception as exc:
        log.warning("columns: warehouse fetch for %r failed: %s", step_name, exc)
        return []

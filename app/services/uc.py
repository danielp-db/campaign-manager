"""Unity Catalog access via the SQL warehouse.

Used for: source tables (read), per-campaign result tables (write/read), and
information_schema introspection. All app metadata lives in Lakebase
(see `app.services.metadata`).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import pandas as pd
from databricks import sql
from databricks.sdk.core import Config

from app.config import SETTINGS


@contextmanager
def warehouse_connection() -> Iterator[Any]:
    cfg = Config()
    conn = sql.connect(
        server_hostname=cfg.host.replace("https://", "").rstrip("/"),
        http_path=f"/sql/1.0/warehouses/{SETTINGS.warehouse_id}",
        credentials_provider=lambda: cfg.authenticate,
    )
    try:
        yield conn
    finally:
        conn.close()


def query_df(sql_text: str, params: tuple | None = None) -> pd.DataFrame:
    with warehouse_connection() as conn, conn.cursor() as cur:
        cur.execute(sql_text, params)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
    return pd.DataFrame(rows, columns=cols)


def execute(sql_text: str, params: tuple | None = None) -> None:
    with warehouse_connection() as conn, conn.cursor() as cur:
        cur.execute(sql_text, params)


def list_tables_in_schema(catalog: str, schema: str) -> list[str]:
    df = query_df(
        f"SELECT table_name FROM {catalog}.information_schema.tables "
        f"WHERE table_schema = '{schema}' AND table_type IN ('MANAGED', 'EXTERNAL') "
        "ORDER BY table_name"
    )
    return df["table_name"].tolist() if not df.empty else []


def list_columns(table_fqn: str) -> list[dict]:
    catalog, schema, table = table_fqn.split(".")
    df = query_df(
        f"SELECT column_name, data_type, ordinal_position "
        f"FROM {catalog}.information_schema.columns "
        f"WHERE table_schema = '{schema}' AND table_name = '{table}' "
        "ORDER BY ordinal_position"
    )
    return df.to_dict("records") if not df.empty else []

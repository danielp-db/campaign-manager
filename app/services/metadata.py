"""All ProspectorPro app metadata in Lakebase (Postgres) for low-latency reads.

UC Delta + warehouse stays for source tables and per-campaign result tables —
those are analytical workloads and benefit from the warehouse. App metadata
(campaigns, approvals, audit, pipeline definitions, uploads) is OLTP-shaped;
serving it from Lakebase removes the warehouse cold-start tax on every page load.
"""
from __future__ import annotations

import json
import uuid

import pandas as pd
from psycopg.rows import dict_row

from app.services.lakebase import lakebase_connection

SCHEMA = "prospectorpro"

T_CAMPAIGNS = f"{SCHEMA}.campaigns"
T_PIPELINE_DEFS = f"{SCHEMA}.pipeline_definitions"
T_APPROVALS = f"{SCHEMA}.approvals"
T_AUDIT = f"{SCHEMA}.audit_log"
T_UPLOADS = f"{SCHEMA}.uploads"


# --- low-level helpers ----------------------------------------------------


def _query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    with lakebase_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return pd.DataFrame(rows)


def _execute(sql: str, params: tuple = ()) -> None:
    with lakebase_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        conn.commit()


# --- bootstrap ------------------------------------------------------------


def ensure_tables() -> None:
    with lakebase_connection() as conn, conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {T_CAMPAIGNS} (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                priority        TEXT,
                organization    TEXT,
                owner           TEXT,
                status          TEXT,
                run_mode        TEXT NOT NULL DEFAULT 'ad_hoc',
                schedule_cron   TEXT,
                lead_count      BIGINT,
                sub_account_count BIGINT,
                results_table   TEXT,
                last_run_at     TIMESTAMPTZ,
                last_run_status TEXT,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        # Migration: add run_mode for tables created before this column existed.
        cur.execute(
            f"ALTER TABLE {T_CAMPAIGNS} ADD COLUMN IF NOT EXISTS run_mode TEXT NOT NULL DEFAULT 'ad_hoc'"
        )
        # Backfill run_mode from any campaigns that had a cron or scheduled status.
        cur.execute(
            f"UPDATE {T_CAMPAIGNS} SET run_mode = 'scheduled' "
            "WHERE (schedule_cron IS NOT NULL AND schedule_cron <> '') "
            "OR status = 'scheduled'"
        )
        # 'scheduled' is no longer a status — it's a run_mode. Demote those.
        cur.execute(
            f"UPDATE {T_CAMPAIGNS} SET status = 'approved' WHERE status = 'scheduled'"
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {T_PIPELINE_DEFS} (
                campaign_id TEXT NOT NULL,
                version     INT NOT NULL,
                dag_json    JSONB NOT NULL,
                created_by  TEXT,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (campaign_id, version)
            )
            """
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {T_APPROVALS} (
                approval_id UUID PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                status      TEXT NOT NULL,
                reviewer    TEXT,
                comment     TEXT,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {T_AUDIT} (
                id          UUID PRIMARY KEY,
                campaign_id TEXT,
                actor       TEXT,
                action      TEXT,
                payload     JSONB,
                ts          TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS audit_campaign_idx ON {T_AUDIT} (campaign_id, ts DESC)"
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {T_UPLOADS} (
                upload_id   UUID PRIMARY KEY,
                file_name   TEXT,
                volume_path TEXT,
                file_format TEXT,
                inferred_schema JSONB,
                uploaded_by TEXT,
                uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        # Demo grant — both the app SP and any human user (Daniel) need access.
        cur.execute(f"GRANT ALL ON SCHEMA {SCHEMA} TO PUBLIC")
        cur.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA {SCHEMA} TO PUBLIC")
        conn.commit()


# --- campaigns ------------------------------------------------------------


def list_campaigns(filter_value: str | None = None) -> pd.DataFrame:
    """`filter_value` is a tab name. 'scheduled' filters by run_mode; everything else by status."""
    if filter_value == "scheduled":
        return _query_df(
            f"SELECT * FROM {T_CAMPAIGNS} WHERE run_mode = 'scheduled' ORDER BY updated_at DESC"
        )
    if filter_value == "ad_hoc":
        return _query_df(
            f"SELECT * FROM {T_CAMPAIGNS} WHERE run_mode = 'ad_hoc' ORDER BY updated_at DESC"
        )
    if filter_value:
        return _query_df(
            f"SELECT * FROM {T_CAMPAIGNS} WHERE status = %s ORDER BY updated_at DESC",
            (filter_value,),
        )
    return _query_df(f"SELECT * FROM {T_CAMPAIGNS} ORDER BY updated_at DESC")


def get_campaign(campaign_id: str) -> dict | None:
    df = _query_df(f"SELECT * FROM {T_CAMPAIGNS} WHERE id = %s LIMIT 1", (campaign_id,))
    return df.iloc[0].to_dict() if not df.empty else None


def insert_campaign(c: dict) -> None:
    cols = [k for k in c.keys() if c[k] is not None or k in ("schedule_cron",)]
    placeholders = ", ".join(["%s"] * len(cols))
    update_clause = ", ".join(f"{k} = EXCLUDED.{k}" for k in cols if k != "id")
    _execute(
        f"INSERT INTO {T_CAMPAIGNS} ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT (id) DO UPDATE SET {update_clause}, updated_at = now()",
        tuple(c[k] for k in cols),
    )


def update_campaign_status(campaign_id: str, status: str) -> None:
    _execute(
        f"UPDATE {T_CAMPAIGNS} SET status = %s, updated_at = now() WHERE id = %s",
        (status, campaign_id),
    )


def update_campaign_info(
    campaign_id: str, name: str, priority: str, organization: str, owner: str
) -> None:
    _execute(
        f"UPDATE {T_CAMPAIGNS} SET name = %s, priority = %s, organization = %s, "
        "owner = %s, updated_at = now() WHERE id = %s",
        (name, priority, organization, owner, campaign_id),
    )


def update_campaign_schedule(campaign_id: str, cron: str | None) -> None:
    """Set the schedule cron. Does NOT change run_mode — caller's responsibility."""
    _execute(
        f"UPDATE {T_CAMPAIGNS} SET schedule_cron = %s::TEXT, updated_at = now() WHERE id = %s",
        (cron, campaign_id),
    )


def update_campaign_run_mode(campaign_id: str, mode: str) -> None:
    """Switch a campaign's run mode. ad_hoc clears schedule_cron."""
    if mode not in ("ad_hoc", "scheduled"):
        raise ValueError(f"invalid run_mode: {mode}")
    if mode == "ad_hoc":
        _execute(
            f"UPDATE {T_CAMPAIGNS} SET run_mode = 'ad_hoc', schedule_cron = NULL, "
            "updated_at = now() WHERE id = %s",
            (campaign_id,),
        )
    else:
        _execute(
            f"UPDATE {T_CAMPAIGNS} SET run_mode = 'scheduled', updated_at = now() WHERE id = %s",
            (campaign_id,),
        )


def update_campaign_run_result(
    campaign_id: str,
    results_table: str,
    lead_count: int,
    sub_account_count: int,
    last_run_status: str,
    new_status: str | None = None,
) -> None:
    if new_status:
        _execute(
            f"UPDATE {T_CAMPAIGNS} SET results_table = %s, lead_count = %s, "
            "sub_account_count = %s, last_run_at = now(), last_run_status = %s, "
            "status = %s, updated_at = now() WHERE id = %s",
            (
                results_table,
                lead_count,
                sub_account_count,
                last_run_status,
                new_status,
                campaign_id,
            ),
        )
    else:
        _execute(
            f"UPDATE {T_CAMPAIGNS} SET results_table = %s, lead_count = %s, "
            "sub_account_count = %s, last_run_at = now(), last_run_status = %s, "
            "updated_at = now() WHERE id = %s",
            (results_table, lead_count, sub_account_count, last_run_status, campaign_id),
        )


# --- pipeline definitions -------------------------------------------------


def save_pipeline_definition(campaign_id: str, dag: dict, created_by: str) -> int:
    df = _query_df(
        f"SELECT COALESCE(MAX(version), 0) AS v FROM {T_PIPELINE_DEFS} WHERE campaign_id = %s",
        (campaign_id,),
    )
    next_version = int(df.iloc[0]["v"]) + 1
    _execute(
        f"INSERT INTO {T_PIPELINE_DEFS} (campaign_id, version, dag_json, created_by) "
        "VALUES (%s, %s, %s::jsonb, %s)",
        (campaign_id, next_version, json.dumps(dag), created_by),
    )
    return next_version


def get_latest_pipeline_definition(campaign_id: str) -> dict | None:
    df = _query_df(
        f"SELECT dag_json, version FROM {T_PIPELINE_DEFS} "
        "WHERE campaign_id = %s ORDER BY version DESC LIMIT 1",
        (campaign_id,),
    )
    if df.empty:
        return None
    raw = df.iloc[0]["dag_json"]
    dag = raw if isinstance(raw, dict) else json.loads(raw)
    return {"dag": dag, "version": int(df.iloc[0]["version"])}


# --- approvals ------------------------------------------------------------


def append_approval(
    campaign_id: str, status: str, reviewer: str, comment: str = ""
) -> None:
    _execute(
        f"INSERT INTO {T_APPROVALS} (approval_id, campaign_id, status, reviewer, comment) "
        "VALUES (%s, %s, %s, %s, %s)",
        (str(uuid.uuid4()), campaign_id, status, reviewer, comment),
    )


def list_approvals(campaign_id: str) -> pd.DataFrame:
    return _query_df(
        f"SELECT * FROM {T_APPROVALS} WHERE campaign_id = %s ORDER BY created_at DESC",
        (campaign_id,),
    )


# --- audit ----------------------------------------------------------------


def append_audit(
    campaign_id: str | None, actor: str, action: str, payload: dict | None = None
) -> None:
    _execute(
        f"INSERT INTO {T_AUDIT} (id, campaign_id, actor, action, payload) "
        "VALUES (%s, %s, %s, %s, %s::jsonb)",
        (str(uuid.uuid4()), campaign_id, actor, action, json.dumps(payload or {})),
    )


def query_audit_log(limit: int = 200) -> pd.DataFrame:
    return _query_df(
        f"SELECT ts, campaign_id, actor, action, payload FROM {T_AUDIT} "
        "ORDER BY ts DESC LIMIT %s",
        (limit,),
    )


def recent_runs(campaign_id: str, limit: int = 10) -> pd.DataFrame:
    return _query_df(
        f"""
        SELECT ts, action, payload
        FROM {T_AUDIT}
        WHERE campaign_id = %s AND action LIKE 'pipeline_run_%%'
        ORDER BY ts DESC LIMIT %s
        """,
        (campaign_id, limit),
    )


# --- uploads --------------------------------------------------------------


def append_upload(
    file_name: str,
    volume_path: str,
    file_format: str,
    inferred_schema: list,
    uploaded_by: str,
) -> str:
    upload_id = str(uuid.uuid4())
    _execute(
        f"INSERT INTO {T_UPLOADS} (upload_id, file_name, volume_path, file_format, "
        "inferred_schema, uploaded_by) VALUES (%s, %s, %s, %s, %s::jsonb, %s)",
        (upload_id, file_name, volume_path, file_format, json.dumps(inferred_schema), uploaded_by),
    )
    return upload_id


def list_uploads() -> pd.DataFrame:
    return _query_df(f"SELECT * FROM {T_UPLOADS} ORDER BY uploaded_at DESC")


# --- migration -----------------------------------------------------------


def migrate_drop_legacy_dag_definitions() -> int:
    """If any pipeline_definitions are in the legacy DAG (nodes/edges) format,
    wipe campaign metadata so demo_seed.seed_if_empty re-populates with the
    new step-list pipeline format. Returns the number of legacy rows found.
    """
    df = _query_df(
        f"SELECT campaign_id, dag_json FROM {T_PIPELINE_DEFS} LIMIT 50"
    )
    if df.empty:
        return 0
    legacy = 0
    for _, r in df.iterrows():
        raw = r["dag_json"]
        obj = raw if isinstance(raw, dict) else json.loads(raw)
        if "nodes" in obj or "edges" in obj:
            legacy += 1
    if legacy == 0:
        return 0
    with lakebase_connection() as conn, conn.cursor() as cur:
        cur.execute(f"DELETE FROM {T_PIPELINE_DEFS}")
        cur.execute(f"DELETE FROM {T_APPROVALS}")
        cur.execute(f"DELETE FROM {T_AUDIT}")
        cur.execute(f"DELETE FROM {T_UPLOADS}")
        cur.execute(f"DELETE FROM {T_CAMPAIGNS}")
        conn.commit()
    return legacy

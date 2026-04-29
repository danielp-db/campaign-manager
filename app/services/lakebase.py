"""Lakebase (managed Postgres) connection — sessions only.

Lakebase uses short-lived OAuth tokens, not static passwords. We always mint a token
via `WorkspaceClient.database.generate_database_credential()` and pass it as PGPASSWORD.

When deployed as a Databricks App with a `valueFrom` Lakebase resource binding, the
platform injects PGHOST/PGPORT/PGUSER/PGDATABASE. Locally, we look up the instance
by name from SETTINGS.
"""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Iterator

import psycopg
from databricks.sdk import WorkspaceClient

from app.config import SETTINGS

SESSION_TTL = timedelta(hours=12)


def _resolve_connection_kwargs() -> dict:
    w = WorkspaceClient()
    instance_name = os.getenv("PROSPECTORPRO_LAKEBASE_INSTANCE_NAME") or SETTINGS.lakebase_instance
    # If PGHOST is injected by the platform, prefer it; else look up the instance.
    host = os.getenv("PGHOST")
    user = os.getenv("PGUSER")
    if not host:
        inst = w.database.get_database_instance(name=instance_name)
        host = inst.read_write_dns
    if not user:
        user = w.current_user.me().user_name or "app"

    cred = w.database.generate_database_credential(
        instance_names=[instance_name],
        request_id=str(uuid.uuid4()),
    )
    return {
        "host": host,
        "port": int(os.getenv("PGPORT", "5432")),
        "dbname": os.getenv("PGDATABASE", "databricks_postgres"),
        "user": user,
        "password": cred.token,
        "sslmode": "require",
    }


@contextmanager
def lakebase_connection() -> Iterator[psycopg.Connection]:
    kwargs = _resolve_connection_kwargs()
    conn = psycopg.connect(**kwargs)
    try:
        yield conn
    finally:
        conn.close()


def ensure_session_table() -> None:
    with lakebase_connection() as conn, conn.cursor() as cur:
        # The app's service principal has CREATE on its own schema but not on `public`.
        # Create a dedicated schema and put the table there.
        cur.execute("CREATE SCHEMA IF NOT EXISTS prospectorpro")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS prospectorpro.sessions (
                session_id   TEXT PRIMARY KEY,
                user_email   TEXT NOT NULL,
                role         TEXT NOT NULL,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                expires_at   TIMESTAMPTZ NOT NULL,
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.commit()


_SESSIONS_TABLE = "prospectorpro.sessions"


def create_session(user_email: str, role: str) -> str:
    session_id = str(uuid.uuid4())
    expires = datetime.utcnow() + SESSION_TTL
    with lakebase_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO prospectorpro.sessions (session_id, user_email, role, expires_at) "
            "VALUES (%s, %s, %s, %s)",
            (session_id, user_email, role, expires),
        )
        conn.commit()
    return session_id


def get_session(session_id: str) -> dict | None:
    with lakebase_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT session_id, user_email, role, expires_at FROM prospectorpro.sessions "
            "WHERE session_id = %s AND expires_at > now()",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            "UPDATE prospectorpro.sessions SET last_seen_at = now() WHERE session_id = %s",
            (session_id,),
        )
        conn.commit()
    return {
        "session_id": row[0],
        "user_email": row[1],
        "role": row[2],
        "expires_at": row[3],
    }


def update_session_role(session_id: str, role: str) -> None:
    with lakebase_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE prospectorpro.sessions SET role = %s WHERE session_id = %s",
            (role, session_id),
        )
        conn.commit()

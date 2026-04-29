"""Dash entry point for ProspectorPro."""
from __future__ import annotations

import logging
import os
import sys
import uuid

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html, no_update
from flask import request

# Ensure project root is on sys.path when launched as `python -m app.main`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.auth import (
    ROLE_COMPLIANCE,
    ROLE_MARKETER,
    VALID_ROLES,
    current_user_email,
)
from app.components.navbar import navbar
from app.config import SETTINGS
from app.services import demo_seed, lakebase, metadata

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("prospectorpro")


def _bootstrap() -> None:
    """Lazy bootstrap: create Lakebase metadata + session tables, seed demo if empty."""
    try:
        lakebase.ensure_session_table()
    except Exception as exc:
        log.warning("could not ensure Lakebase session table: %s", exc)
    try:
        metadata.ensure_tables()
    except Exception as exc:
        log.warning("could not ensure Lakebase metadata tables: %s", exc)
    try:
        n = demo_seed.seed_if_empty()
        if n:
            log.info("seeded %d demo campaigns", n)
    except Exception as exc:
        log.warning("demo seed failed: %s", exc)


_bootstrap()


app = dash.Dash(
    __name__,
    use_pages=True,
    pages_folder=os.path.join(os.path.dirname(__file__), "pages"),
    external_stylesheets=[dbc.themes.FLATLY, dbc.icons.BOOTSTRAP],
    title="ProspectorPro",
    update_title=None,
    suppress_callback_exceptions=True,
)
server = app.server


app.layout = html.Div(
    [
        dcc.Location(id="url", refresh=False),
        dcc.Store(id="session-store", storage_type="local"),
        navbar(),
        dbc.Container(dash.page_container, fluid=True, className="pb-5"),
    ]
)


@callback(
    Output("session-store", "data"),
    Output("user-email", "children"),
    Input("url", "pathname"),
    State("session-store", "data"),
)
def _ensure_session(_path, session):
    headers = dict(request.headers) if request else {}
    email = current_user_email(headers)
    if session and session.get("session_id") and session.get("user_email") == email:
        return no_update, email
    # Create a new local session entry. We persist client-side via storage_type='local'.
    new_session = {
        "session_id": session.get("session_id") if session else str(uuid.uuid4()),
        "user_email": email,
        "role": (session or {}).get("role") or ROLE_MARKETER,
    }
    try:
        lakebase.create_session(email, new_session["role"])
    except Exception as exc:
        log.warning("Lakebase session insert failed (using local-only): %s", exc)
    return new_session, email


@callback(
    Output("session-store", "data", allow_duplicate=True),
    Input("role-switcher", "value"),
    State("session-store", "data"),
    prevent_initial_call=True,
)
def _switch_role(role, session):
    if role not in VALID_ROLES or not session:
        return no_update
    if session.get("role") == role:
        return no_update
    if session.get("session_id"):
        try:
            lakebase.update_session_role(session["session_id"], role)
        except Exception as exc:
            log.warning("Lakebase update_session_role failed: %s", exc)
    return {**session, "role": role}


@callback(
    Output("role-switcher", "value"),
    Input("session-store", "data"),
)
def _hydrate_role_switcher(session):
    return (session or {}).get("role") or ROLE_MARKETER


def main() -> None:
    log.info("ProspectorPro starting on port %d", SETTINGS.app_port)
    log.info("UC schema: %s", SETTINGS.schema_fqn)
    log.info("Lakebase instance: %s", SETTINGS.lakebase_instance)
    app.run(host="0.0.0.0", port=SETTINGS.app_port, debug=False)


if __name__ == "__main__":
    main()

"""Campaign detail page — Info / Logic / Analytics tabs.

Logic tab uses the new step-list pipeline editor (`logic_panel`) — buttons add
typed steps via a shared modal; each step is a named CTE in the compiled SQL.
"""
from __future__ import annotations

import re
import uuid

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from app.auth import ROLE_COMPLIANCE, ROLE_MARKETER
from app.components.analytics_panel import analytics_panel
from app.components.info_panel import info_panel
from app.components.logic_panel import logic_panel, step_list
from app.components.step_forms import OP_LABELS, render_form_body
from app.compiler import Pipeline, compile_pipeline, compile_pipeline_preview
from app.compiler.pipeline import CompileError
from app.config import SETTINGS
from app.services import ai_cron, columns, genie, metadata, runner, uc

dash.register_page(__name__, path_template="/campaign/<campaign_id>", name="Campaign")


# --- page lifecycle ------------------------------------------------------


def _new_campaign_skeleton(campaign_id: str, owner: str) -> dict:
    return {
        "id": campaign_id,
        "name": "New campaign",
        "priority": "medium",
        "organization": "",
        "owner": owner,
        "status": "draft",
        "run_mode": "ad_hoc",
        "schedule_cron": None,
        "lead_count": None,
        "sub_account_count": None,
        "results_table": None,
        "last_run_at": None,
        "last_run_status": None,
    }


def _load_or_create(campaign_id: str, owner: str) -> tuple[dict, dict, bool]:
    """Returns (campaign, pipeline_data, was_created)."""
    if campaign_id == "new":
        cid = str(uuid.uuid4())[:8]
        c = _new_campaign_skeleton(cid, owner)
        metadata.insert_campaign(c)
        return metadata.get_campaign(cid) or c, {"steps": []}, True
    c = metadata.get_campaign(campaign_id) or _new_campaign_skeleton(campaign_id, owner)
    pdef = metadata.get_latest_pipeline_definition(campaign_id)
    pipeline_data = pdef["dag"] if pdef else {"steps": []}
    if not isinstance(pipeline_data, dict) or "steps" not in pipeline_data:
        pipeline_data = {"steps": []}
    return c, pipeline_data, False


def layout(campaign_id: str = "new", **_):
    return html.Div(
        [
            dcc.Store(id="campaign-id-store", data=campaign_id),
            dcc.Store(id="campaign-refresh", data=0),
            dcc.Loading(html.Div(id="campaign-shell"), type="dot"),
        ]
    )


@callback(
    Output("campaign-shell", "children"),
    Output("campaign-id-store", "data", allow_duplicate=True),
    Input("campaign-id-store", "data"),
    Input("campaign-refresh", "data"),
    Input("session-store", "data"),
    prevent_initial_call="initial_duplicate",
)
def _render_detail(campaign_id: str, _refresh, session: dict | None):
    role = (session or {}).get("role", ROLE_MARKETER)
    owner = (session or {}).get("user_email", "demo@databricks.com")
    campaign, pipeline_data, was_created = _load_or_create(campaign_id, owner)
    cid = campaign["id"]
    # Pin the id store to the real id so subsequent re-renders don't keep
    # spawning new draft campaigns from /campaign/new.
    new_id_store = cid if was_created else no_update
    approvals = metadata.list_approvals(cid)
    recent = metadata.recent_runs(cid, limit=10)

    info = info_panel(campaign, approvals, role, recent_runs=recent)
    editor = logic_panel(pipeline_data)
    analytics = analytics_panel(campaign)

    tabs = dbc.Tabs(
        id="campaign-tabs",
        active_tab="info",
        children=[
            dbc.Tab(html.Div(info, className="pt-3"), label="Info", tab_id="info"),
            dbc.Tab(html.Div(editor, className="pt-3"), label="Logic", tab_id="logic"),
            dbc.Tab(html.Div(analytics, className="pt-3"), label="Analytics", tab_id="analytics"),
        ],
    )

    shell = html.Div(
        [
            dcc.Store(id="campaign-loaded-id", data=cid),
            dbc.Breadcrumb(
                items=[
                    {"label": "Campaigns", "href": "/"},
                    {"label": campaign["name"] or cid, "active": True},
                ]
            ),
            tabs,
        ]
    )
    return shell, new_id_store


# --- Logic tab: load UC tables once on mount ----------------------------


@callback(
    Output("uc-tables-store", "data"),
    Input("campaign-loaded-id", "data"),
    State("uc-tables-store", "data"),
)
def _load_uc_tables(_id, current):
    if current:
        return no_update
    try:
        return uc.list_tables_in_catalog(SETTINGS.catalog)
    except Exception:
        return []


# --- Logic tab: render step list reactively -----------------------------


@callback(
    Output("pipeline-step-list", "children"),
    Input("pipeline-store", "data"),
    Input("expanded-step", "data"),
)
def _render_step_list(pipeline, expanded):
    return step_list(pipeline, expanded)


@callback(
    Output("expanded-step", "data"),
    Input({"role": "step-cols", "name": ALL}, "n_clicks"),
    State("expanded-step", "data"),
    State("pipeline-store", "data"),
    prevent_initial_call=True,
)
def _toggle_step_columns(_clicks, current, pipeline_data):
    triggered = ctx.triggered_id
    if not isinstance(triggered, dict):
        return no_update
    value = ctx.triggered[0].get("value")
    if not value:
        return no_update
    name = triggered.get("name")
    if current and current.get("name") == name:
        return None  # collapse
    cols = columns.get_step_columns(pipeline_data, name)
    return {"name": name, "columns": cols}


@callback(
    Output("expanded-step", "data", allow_duplicate=True),
    Input("pipeline-store", "data"),
    State("expanded-step", "data"),
    prevent_initial_call=True,
)
def _refresh_expanded_columns(pipeline_data, current):
    """When the pipeline changes, refresh columns for whatever's expanded so
    the badge list stays accurate."""
    if not current or not current.get("name"):
        return no_update
    cols = columns.get_step_columns(pipeline_data, current["name"])
    return {"name": current["name"], "columns": cols}


# --- Logic tab: open / cancel / submit modal ----------------------------


@callback(
    Output("step-modal-state", "data"),
    Input({"role": "open-modal", "op": ALL}, "n_clicks"),
    Input({"role": "step-edit", "name": ALL}, "n_clicks"),
    Input("step-modal-cancel", "n_clicks"),
    State("pipeline-store", "data"),
    prevent_initial_call=True,
)
def _modal_state_router(_opens, _edits, _cancel, pipeline):
    triggered = ctx.triggered_id
    if not triggered:
        return no_update

    if triggered == "step-modal-cancel":
        return None

    # Pattern-matching trigger: dict with role + extra
    if isinstance(triggered, dict):
        role = triggered.get("role")
        if role == "open-modal":
            # n_clicks may be None on initial fire; ignore that
            value = ctx.triggered[0].get("value")
            if not value:
                return no_update
            return {"op": triggered["op"], "editing": None}
        if role == "step-edit":
            value = ctx.triggered[0].get("value")
            if not value:
                return no_update
            name = triggered["name"]
            steps = (pipeline or {}).get("steps") or []
            step = next((s for s in steps if s["name"] == name), None)
            if not step:
                return no_update
            return {"op": step["op"], "editing": name}
    return no_update


@callback(
    Output("step-modal", "is_open"),
    Output("step-modal-title", "children"),
    Output("step-modal-body", "children"),
    Input("step-modal-state", "data"),
    State("pipeline-store", "data"),
    State("uc-tables-store", "data"),
)
def _render_modal(state, pipeline, uc_tables):
    if not state:
        return False, "", html.Div()
    op = state["op"]
    editing = state.get("editing")
    title = f"Edit {OP_LABELS.get(op, op).removeprefix('Add ')}" if editing else OP_LABELS.get(op, op)

    step_dict: dict | None = None
    steps = (pipeline or {}).get("steps") or []
    if editing:
        step_dict = next((s for s in steps if s["name"] == editing), None)

    # Available "from" / "left" / "right" names: any step defined BEFORE the
    # currently-edited step (or all of them, if adding new).
    if editing and step_dict:
        idx = next((i for i, s in enumerate(steps) if s["name"] == editing), len(steps))
        names = [s["name"] for s in steps[:idx]]
    else:
        names = [s["name"] for s in steps]

    # Pre-compute columns for any pre-set from/left/right so dropdowns are populated on open.
    columns_for: dict[str, list[str]] = {}
    if step_dict:
        if op in ("filter", "field", "select", "aggregate") and step_dict.get("from"):
            columns_for["from"] = columns.get_step_columns(pipeline, step_dict["from"])
        if op == "join":
            if step_dict.get("left"):
                columns_for["left"] = columns.get_step_columns(pipeline, step_dict["left"])
            if step_dict.get("right"):
                columns_for["right"] = columns.get_step_columns(pipeline, step_dict["right"])

    body = render_form_body(op, names, uc_tables or [], step_dict, columns_for)
    return True, title, body


# --- Logic tab: dataset source toggle (UC vs File) ----------------------


@callback(
    Output("dataset-uc-block", "style"),
    Output("dataset-file-block", "style"),
    Input({"role": "step-form", "key": "source"}, "value"),
    prevent_initial_call=True,
)
def _toggle_dataset_source(source):
    if source == "file":
        return {"display": "none"}, {"display": "block"}
    return {"display": "block"}, {"display": "none"}


# --- Logic tab: live column dropdown updates ---------------------------


_KEY_TO_DEPENDENTS = {
    "from": {"column", "group_by"},
    "left": {"left_key"},
    "right": {"right_key"},
}


@callback(
    Output({"role": "step-form", "key": ALL}, "options"),
    Input({"role": "step-form", "key": ALL}, "value"),
    State({"role": "step-form", "key": ALL}, "id"),
    State("pipeline-store", "data"),
    prevent_initial_call=True,
)
def _update_column_options(_values, ids, pipeline_data):
    triggered = ctx.triggered_id
    n = len(ids)
    if not isinstance(triggered, dict):
        return [no_update] * n
    key = triggered.get("key")
    dependents = _KEY_TO_DEPENDENTS.get(key)
    if not dependents:
        return [no_update] * n

    # The triggering field's current value (where the user picked a dataset).
    triggered_value = next(
        (v for v, idobj in zip(_values, ids) if idobj["key"] == key), None
    )
    cols = columns.get_step_columns(pipeline_data, triggered_value) if triggered_value else []
    new_options = [{"label": c, "value": c} for c in cols]
    return [
        new_options if idobj["key"] in dependents else no_update for idobj in ids
    ]


# --- Logic tab: dataset preview (top 10 rows of selected UC table) ------


@callback(
    Output("dataset-preview-area", "children"),
    Input({"role": "step-form", "key": "table_fqn"}, "value"),
    prevent_initial_call=True,
)
def _preview_dataset(table_fqn):
    if not table_fqn:
        return html.Div()
    try:
        df = uc.query_df(f"SELECT * FROM {table_fqn} LIMIT 10")
    except Exception as exc:
        return dbc.Alert(
            f"Could not preview {table_fqn}: {exc}", color="warning", className="small mb-0"
        )
    if df.empty:
        return html.Div(f"({table_fqn} is empty)", className="text-muted small")
    return html.Div(
        [
            html.Div("Preview · top 10 rows", className="small text-muted mb-1"),
            html.Div(
                dbc.Table.from_dataframe(
                    df.head(10), striped=True, hover=True, responsive=True, size="sm"
                ),
                style={"max-height": "260px", "overflow": "auto"},
            ),
        ]
    )


# --- Logic tab: run preview SQL and render rows -------------------------


@callback(
    Output("pipeline-action-output", "children", allow_duplicate=True),
    Input("pipeline-preview-rows", "n_clicks"),
    State("pipeline-store", "data"),
    prevent_initial_call=True,
)
def _preview_pipeline_rows(_n, pipeline_data):
    if not _n:
        return no_update
    steps = (pipeline_data or {}).get("steps") or []
    if not steps:
        return dbc.Alert(
            "Pipeline is empty — add at least one step.", color="warning", duration=3000
        )
    try:
        pipeline = Pipeline.model_validate(pipeline_data)
    except Exception as exc:
        return dbc.Alert(f"Invalid pipeline: {exc}", color="danger")
    try:
        sql = compile_pipeline_preview(pipeline, limit=50)
    except CompileError as exc:
        return dbc.Alert(f"Compile error: {exc}", color="danger")
    try:
        df = uc.query_df(sql)
    except Exception as exc:
        return dbc.Alert(f"Preview failed: {exc}", color="danger")
    last_step = steps[-1]["name"]
    if df.empty:
        return dbc.Alert(
            f"Pipeline compiled successfully but produced 0 rows from `{last_step}`.",
            color="info",
        )
    return dbc.Card(
        [
            dbc.CardHeader(
                f"Preview · final step `{last_step}` · top {len(df)} rows of "
                f"{', '.join(df.columns[:6])}{' ...' if len(df.columns) > 6 else ''}"
            ),
            dbc.CardBody(
                dbc.Table.from_dataframe(
                    df, striped=True, hover=True, responsive=True, size="sm"
                ),
                style={"max-height": "500px", "overflow": "auto"},
            ),
        ]
    )


# --- Logic tab: submit step --------------------------------------------


def _parse_columns_text(text: str) -> list[dict]:
    out: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = re.split(r"\s+AS\s+", line, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 2:
            out.append({"column": parts[0].strip(), "alias": parts[1].strip()})
        else:
            out.append({"column": line})
    return out


def _parse_keys_text(text: str) -> list[dict]:
    out: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or "=" not in line:
            continue
        left, right = line.split("=", 1)
        out.append({"left": left.strip(), "right": right.strip()})
    return out


def _build_step(op: str, fields: dict) -> dict:
    name = (fields.get("name") or "").strip()
    if op == "dataset":
        source = fields.get("source") or "uc"
        step = {"op": "dataset", "name": name, "source": source}
        if source == "uc":
            step["table_fqn"] = (fields.get("table_fqn") or "").strip()
        else:
            step["file_path"] = (fields.get("file_path") or "").strip()
            step["file_format"] = fields.get("file_format") or "csv"
        return step
    if op == "filter":
        return {
            "op": "filter",
            "name": name,
            "from": (fields.get("from") or "").strip(),
            "column": (fields.get("column") or "").strip(),
            "operator": fields.get("operator") or "=",
            "value": fields.get("value") or "",
        }
    if op == "field":
        return {
            "op": "field",
            "name": name,
            "from": (fields.get("from") or "").strip(),
            "new_field_name": (fields.get("new_field_name") or "").strip(),
            "expression": (fields.get("expression") or "").strip(),
        }
    if op == "select":
        return {
            "op": "select",
            "name": name,
            "from": (fields.get("from") or "").strip(),
            "columns": _parse_columns_text(fields.get("columns_text", "")),
        }
    if op == "join":
        primary = []
        lkey = (fields.get("left_key") or "").strip()
        rkey = (fields.get("right_key") or "").strip()
        if lkey and rkey:
            primary.append({"left": lkey, "right": rkey})
        primary.extend(_parse_keys_text(fields.get("extra_keys_text", "")))
        return {
            "op": "join",
            "name": name,
            "left": (fields.get("left") or "").strip(),
            "right": (fields.get("right") or "").strip(),
            "join_type": fields.get("join_type") or "INNER",
            "keys": primary,
        }
    if op == "union":
        return {
            "op": "union",
            "name": name,
            "left": (fields.get("left") or "").strip(),
            "right": (fields.get("right") or "").strip(),
        }
    if op == "aggregate":
        agg_lines = [
            line.strip()
            for line in (fields.get("aggregations_text") or "").splitlines()
            if line.strip()
        ]
        gb = fields.get("group_by") or []
        if isinstance(gb, str):
            gb = [gb]
        return {
            "op": "aggregate",
            "name": name,
            "from": (fields.get("from") or "").strip(),
            "group_by": [c for c in gb if c],
            "aggregations": agg_lines,
        }
    if op == "custom":
        return {
            "op": "custom",
            "name": name,
            "sql": (fields.get("sql") or "").strip(),
        }
    raise ValueError(f"unknown op: {op}")


@callback(
    Output("pipeline-store", "data"),
    Output("step-modal-state", "data", allow_duplicate=True),
    Output("pipeline-action-output", "children"),
    Input("step-modal-submit", "n_clicks"),
    State("step-modal-state", "data"),
    State({"role": "step-form", "key": ALL}, "value"),
    State({"role": "step-form", "key": ALL}, "id"),
    State("pipeline-store", "data"),
    prevent_initial_call=True,
)
def _submit_step(_n, state, values, ids, pipeline):
    if not _n or not state:
        return no_update, no_update, no_update
    fields = {idobj["key"]: v for v, idobj in zip(values, ids)}
    try:
        step = _build_step(state["op"], fields)
    except Exception as exc:
        return (
            no_update,
            no_update,
            dbc.Alert(f"Could not build step: {exc}", color="danger"),
        )

    if not step["name"]:
        return no_update, no_update, dbc.Alert("Step name is required.", color="warning")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", step["name"]):
        return (
            no_update,
            no_update,
            dbc.Alert(
                "Step name must start with a letter/underscore and contain only "
                "letters, digits, and underscores.",
                color="warning",
            ),
        )

    steps = list((pipeline or {}).get("steps") or [])
    editing = state.get("editing")
    if editing:
        new_steps = [step if s["name"] == editing else s for s in steps]
    else:
        if any(s["name"] == step["name"] for s in steps):
            return (
                no_update,
                no_update,
                dbc.Alert(
                    f"A step named '{step['name']}' already exists.", color="warning"
                ),
            )
        new_steps = steps + [step]

    return (
        {"steps": new_steps},
        None,
        dbc.Alert(
            f"{'Updated' if editing else 'Added'} step {step['name']}.",
            color="success",
            duration=3000,
        ),
    )


# --- Logic tab: delete step --------------------------------------------


@callback(
    Output("pipeline-store", "data", allow_duplicate=True),
    Output("pipeline-action-output", "children", allow_duplicate=True),
    Input({"role": "step-delete", "name": ALL}, "n_clicks"),
    State("pipeline-store", "data"),
    prevent_initial_call=True,
)
def _delete_step(_clicks, pipeline):
    triggered = ctx.triggered_id
    if not isinstance(triggered, dict):
        return no_update, no_update
    value = ctx.triggered[0].get("value")
    if not value:
        return no_update, no_update
    name = triggered.get("name")
    steps = list((pipeline or {}).get("steps") or [])
    new_steps = [s for s in steps if s["name"] != name]
    if len(new_steps) == len(steps):
        return no_update, no_update
    return (
        {"steps": new_steps},
        dbc.Alert(f"Removed step {name}.", color="success", duration=3000),
    )


# --- Logic tab: action bar (Save / Preview / Run) ----------------------


@callback(
    Output("pipeline-action-output", "children", allow_duplicate=True),
    Output("campaign-refresh", "data", allow_duplicate=True),
    Input("pipeline-save", "n_clicks"),
    Input("pipeline-preview", "n_clicks"),
    Input("pipeline-run", "n_clicks"),
    State("pipeline-store", "data"),
    State("campaign-loaded-id", "data"),
    State("session-store", "data"),
    State("campaign-refresh", "data"),
    prevent_initial_call=True,
)
def _pipeline_action(_s, _p, _r, pipeline_data, campaign_id, session, refresh):
    triggered_n = ctx.triggered[0].get("value") if ctx.triggered else None
    if not triggered_n:
        # Spurious fire from layout re-render — only act on real clicks.
        return no_update, no_update
    triggered = ctx.triggered_id
    user = (session or {}).get("user_email", "demo@databricks.com")
    steps = (pipeline_data or {}).get("steps") or []
    if not steps:
        return dbc.Alert("Pipeline is empty — add at least one step.", color="warning"), no_update
    try:
        pipeline = Pipeline.model_validate(pipeline_data)
    except Exception as exc:
        return dbc.Alert(f"Invalid pipeline: {exc}", color="danger"), no_update

    if triggered == "pipeline-save":
        version = metadata.save_pipeline_definition(campaign_id, pipeline_data, user)
        metadata.append_audit(campaign_id, user, "pipeline_save", {"version": version})
        return (
            dbc.Alert(f"Saved pipeline definition v{version}.", color="success", duration=4000),
            (refresh or 0) + 1,
        )

    if triggered == "pipeline-preview":
        try:
            sql = compile_pipeline_preview(pipeline, limit=200)
        except CompileError as exc:
            return dbc.Alert(f"Compile error: {exc}", color="danger"), no_update
        return (
            dbc.Card(
                [
                    dbc.CardHeader("Preview SQL"),
                    dbc.CardBody(html.Pre(sql, style={"white-space": "pre-wrap", "font-size": 13})),
                ]
            ),
            no_update,
        )

    if triggered == "pipeline-run":
        latest = metadata.get_latest_pipeline_definition(campaign_id)
        if not latest:
            metadata.save_pipeline_definition(campaign_id, pipeline_data, user)
        try:
            result = runner.run_campaign(campaign_id, user)
        except Exception as exc:
            return (
                dbc.Alert(f"Run failed: {exc}", color="danger"),
                (refresh or 0) + 1,
            )
        return (
            dbc.Alert(
                f"Pipeline ran in {result['elapsed_s']}s — "
                f"{result['lead_count']:,} rows in {result['results_table']}.",
                color="success",
            ),
            (refresh or 0) + 1,
        )

    return no_update, no_update


# --- Approvals callbacks ---------------------------------------------------


@callback(
    Output("approval-result", "children"),
    Output("campaign-refresh", "data"),
    Input("approval-submit", "n_clicks"),
    Input("approval-approve", "n_clicks"),
    Input("approval-reject", "n_clicks"),
    State("approval-comment", "value"),
    State("campaign-loaded-id", "data"),
    State("session-store", "data"),
    State("campaign-refresh", "data"),
    prevent_initial_call=True,
)
def _approval_action(_s, _a, _r, comment, campaign_id, session, refresh):
    triggered_n = ctx.triggered[0].get("value") if ctx.triggered else None
    if not triggered_n:
        return no_update, no_update
    triggered = ctx.triggered_id
    user = (session or {}).get("user_email", "demo@databricks.com")
    role = (session or {}).get("role", ROLE_MARKETER)

    if triggered == "approval-submit" and role == ROLE_MARKETER:
        new_status, msg = "pending_approval", "Submitted for compliance review."
    elif triggered == "approval-approve" and role == ROLE_COMPLIANCE:
        new_status, msg = "approved", "Approved."
    elif triggered == "approval-reject" and role == ROLE_COMPLIANCE:
        new_status, msg = "rejected", "Rejected."
    else:
        return dbc.Alert("Action not permitted for your role.", color="warning"), no_update

    metadata.update_campaign_status(campaign_id, new_status)
    metadata.append_approval(campaign_id, new_status, user, comment or "")
    metadata.append_audit(campaign_id, user, f"approval_{new_status}", {"comment": comment or ""})
    return dbc.Alert(msg, color="success", duration=3000), (refresh or 0) + 1


# --- Info tab callbacks ----------------------------------------------------


@callback(
    Output("ci-save-alert", "children"),
    Output("campaign-refresh", "data", allow_duplicate=True),
    Input("ci-save", "n_clicks"),
    State("ci-name", "value"),
    State("ci-priority", "value"),
    State("ci-organization", "value"),
    State("ci-owner", "value"),
    State("campaign-loaded-id", "data"),
    State("campaign-refresh", "data"),
    prevent_initial_call=True,
)
def _save_info(_n, name, priority, organization, owner, campaign_id, refresh):
    if not _n:
        return no_update, no_update
    metadata.update_campaign_info(campaign_id, name, priority, organization, owner)
    return (
        dbc.Alert("Saved.", color="success", duration=2500, className="mt-2"),
        (refresh or 0) + 1,
    )


@callback(
    Output("info-run-output", "children"),
    Output("campaign-refresh", "data", allow_duplicate=True),
    Input("info-run-now", "n_clicks"),
    State("campaign-loaded-id", "data"),
    State("session-store", "data"),
    State("campaign-refresh", "data"),
    prevent_initial_call=True,
)
def _run_now(_n, campaign_id, session, refresh):
    if not _n or not campaign_id:
        return no_update, no_update
    user = (session or {}).get("user_email", "demo@databricks.com")
    role = (session or {}).get("role", ROLE_MARKETER)
    campaign = metadata.get_campaign(campaign_id) or {}
    status = (campaign.get("status") or "").lower()

    # Compliance: read-only preview, no UC write.
    if role == ROLE_COMPLIANCE:
        pdef = metadata.get_latest_pipeline_definition(campaign_id)
        if not pdef:
            return (
                dbc.Alert("No pipeline saved yet — nothing to preview.", color="warning"),
                no_update,
            )
        try:
            pipeline = Pipeline.model_validate(pdef["dag"])
            sql = compile_pipeline_preview(pipeline, limit=50)
            df = uc.query_df(sql)
        except Exception as exc:
            return dbc.Alert(f"Preview failed: {exc}", color="danger"), no_update
        if df.empty:
            return (
                dbc.Alert(
                    "Pipeline compiled successfully but produced 0 rows.",
                    color="info",
                ),
                no_update,
            )
        return (
            dbc.Card(
                [
                    dbc.CardHeader(
                        f"Compliance preview · top {len(df)} rows · NOT written to UC"
                    ),
                    dbc.CardBody(
                        dbc.Table.from_dataframe(
                            df, striped=True, hover=True, responsive=True, size="sm"
                        ),
                        style={"max-height": "440px", "overflow": "auto"},
                    ),
                ]
            ),
            no_update,
        )

    # Marketer: must be approved before running for real.
    if status != "approved":
        return (
            dbc.Alert(
                "Run is disabled until the campaign is approved by Compliance "
                f"(current status: {status or 'unknown'}).",
                color="warning",
            ),
            no_update,
        )
    try:
        result = runner.run_campaign(campaign_id, user)
    except ValueError as e:
        return dbc.Alert(str(e), color="warning", duration=4000), no_update
    except Exception as e:
        return (
            dbc.Alert(f"Run failed: {e}", color="danger"),
            (refresh or 0) + 1,
        )
    return (
        dbc.Alert(
            f"Pipeline ran in {result['elapsed_s']}s — "
            f"{result['lead_count']:,} rows in {result['results_table']}.",
            color="success",
            duration=6000,
        ),
        (refresh or 0) + 1,
    )


# --- Genie: open / close / ask / use ------------------------------------


@callback(
    Output("genie-modal", "is_open"),
    Output("genie-result", "children", allow_duplicate=True),
    Output("genie-sql-store", "data", allow_duplicate=True),
    Output("genie-question", "value"),
    Input("open-genie-modal", "n_clicks"),
    Input("genie-modal-close", "n_clicks"),
    State("genie-modal", "is_open"),
    prevent_initial_call=True,
)
def _toggle_genie_modal(_open_n, _close_n, is_open):
    triggered = ctx.triggered_id
    triggered_n = ctx.triggered[0].get("value") if ctx.triggered else None
    if not triggered_n:
        return no_update, no_update, no_update, no_update
    if triggered == "open-genie-modal":
        return True, html.Div(), None, ""
    return False, no_update, no_update, no_update


@callback(
    Output("genie-result", "children"),
    Output("genie-sql-store", "data"),
    Output("genie-use", "disabled"),
    Input("genie-ask", "n_clicks"),
    State("genie-question", "value"),
    prevent_initial_call=True,
)
def _genie_ask(_n, question):
    if not _n:
        return no_update, no_update, no_update
    if not (question or "").strip():
        return (
            dbc.Alert("Type a description first.", color="warning", duration=3000),
            None,
            True,
        )
    try:
        result = genie.ask(question)
    except genie.GenieError as exc:
        return dbc.Alert(f"Genie: {exc}", color="danger"), None, True
    sql = result["sql"]
    title = result.get("title") or ""
    descr = result.get("description") or ""
    body = [
        html.Div(
            [
                dbc.Badge("Genie ✨", color="info", className="me-2"),
                html.Strong(title or "Generated SQL"),
            ],
            className="mb-2",
        ),
    ]
    if descr:
        body.append(html.Div(descr, className="text-muted small mb-2"))
    body.append(
        html.Pre(
            sql,
            style={
                "white-space": "pre-wrap",
                "font-size": 13,
                "background": "#f8f9fa",
                "padding": "12px",
                "border-radius": "6px",
                "max-height": "320px",
                "overflow": "auto",
            },
        )
    )
    return html.Div(body), sql, False


@callback(
    Output("pipeline-store", "data", allow_duplicate=True),
    Output("genie-modal", "is_open", allow_duplicate=True),
    Output("pipeline-action-output", "children", allow_duplicate=True),
    Input("genie-use", "n_clicks"),
    State("genie-sql-store", "data"),
    State("genie-step-name", "value"),
    State("pipeline-store", "data"),
    prevent_initial_call=True,
)
def _genie_use(_n, sql, name, pipeline):
    if not _n or not sql:
        return no_update, no_update, no_update
    safe_name = (name or "genie_step").strip() or "genie_step"
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", safe_name):
        return (
            no_update,
            no_update,
            dbc.Alert(
                f"Invalid step name: {safe_name!r}. Letters, digits, underscores only.",
                color="danger",
            ),
        )
    steps = list((pipeline or {}).get("steps") or [])
    # Auto-disambiguate if name collides
    base = safe_name
    n = 2
    existing = {s["name"] for s in steps}
    while safe_name in existing:
        safe_name = f"{base}_{n}"
        n += 1
    new_step = {"op": "custom", "name": safe_name, "sql": sql.strip()}
    return (
        {"steps": steps + [new_step]},
        False,
        dbc.Alert(
            f"Added step '{safe_name}' from Genie. Save the pipeline when ready.",
            color="success",
            duration=4500,
        ),
    )


# --- Schedule builder: visibility of conditional fields ----------------


@callback(
    Output("sb-hour-col", "style"),
    Output("sb-dow-col", "style"),
    Output("sb-dom-col", "style"),
    Input("sb-frequency", "value"),
    prevent_initial_call=False,
)
def _toggle_schedule_fields(frequency):
    show = {"display": "block"}
    hide = {"display": "none"}
    if frequency == "hourly":
        return hide, hide, hide
    if frequency == "daily":
        return show, hide, hide
    if frequency == "weekly":
        return show, show, hide
    if frequency == "monthly":
        return show, hide, show
    return show, show, show


# --- Schedule cron: derive from active tab -----------------------------


@callback(
    Output("info-cron-store", "data"),
    Output("info-cron-preview", "children"),
    Input("sb-tabs", "active_tab"),
    Input("sb-frequency", "value"),
    Input("sb-hour", "value"),
    Input("sb-minute", "value"),
    Input("sb-dow", "value"),
    Input("sb-dom", "value"),
    Input("sb-custom-cron", "value"),
    Input("sb-ai-output", "children"),
    State("info-cron-store", "data"),
)
def _derive_cron(active_tab, freq, hour, minute, dow, dom, custom, ai_output, current):
    cron: str | None = current
    try:
        if active_tab == "builder":
            cron = ai_cron.build_cron(
                freq or "daily",
                minute=minute or 0,
                hour=hour or 0,
                day_of_week=dow or "MON",
                day_of_month=dom or 1,
            )
        elif active_tab == "custom":
            cron = (custom or "").strip() or None
        elif active_tab == "ai":
            # AI tab cron is set when sb-ai-convert finishes; preserve current.
            cron = current
    except Exception:
        cron = current
    return cron, (cron or "(none)")


# --- Schedule: AI text-to-cron --------------------------------------------


@callback(
    Output("sb-ai-output", "children"),
    Output("info-cron-store", "data", allow_duplicate=True),
    Output("info-cron-preview", "children", allow_duplicate=True),
    Input("sb-ai-convert", "n_clicks"),
    State("sb-ai-text", "value"),
    prevent_initial_call=True,
)
def _ai_convert(_n, description):
    if not _n:
        return no_update, no_update, no_update
    if not (description or "").strip():
        return (
            dbc.Alert("Describe a schedule first.", color="warning", duration=3000),
            no_update,
            no_update,
        )
    try:
        cron = ai_cron.text_to_cron(description)
    except ai_cron.AiCronError as exc:
        return (
            dbc.Alert(f"AI conversion failed: {exc}", color="danger"),
            no_update,
            no_update,
        )
    return (
        dbc.Alert(
            ["Got it: ", html.Code(cron)], color="success", duration=4000
        ),
        cron,
        cron,
    )


# --- Schedule: Save / Clear --------------------------------------------


@callback(
    Output("info-schedule-collapse", "is_open"),
    Output("info-run-output", "children", allow_duplicate=True),
    Output("campaign-refresh", "data", allow_duplicate=True),
    Input("info-run-mode", "value"),
    State("campaign-loaded-id", "data"),
    State("session-store", "data"),
    State("campaign-refresh", "data"),
    prevent_initial_call=True,
)
def _set_run_mode(mode, campaign_id, session, refresh):
    if not campaign_id or mode not in ("ad_hoc", "scheduled"):
        return no_update, no_update, no_update
    role = (session or {}).get("role", ROLE_MARKETER)
    if role != ROLE_MARKETER:
        return no_update, no_update, no_update
    user = (session or {}).get("user_email", "demo@databricks.com")
    metadata.update_campaign_run_mode(campaign_id, mode)
    metadata.append_audit(campaign_id, user, "run_mode_updated", {"mode": mode})
    msg = (
        "Switched to Ad Hoc — schedule cleared." if mode == "ad_hoc" else "Switched to Scheduled mode."
    )
    return (
        mode == "scheduled",
        dbc.Alert(msg, color="info", duration=2500),
        (refresh or 0) + 1,
    )


@callback(
    Output("info-run-output", "children", allow_duplicate=True),
    Output("campaign-refresh", "data", allow_duplicate=True),
    Input("info-cron-save", "n_clicks"),
    Input("info-cron-clear", "n_clicks"),
    State("info-cron-store", "data"),
    State("campaign-loaded-id", "data"),
    State("session-store", "data"),
    State("campaign-refresh", "data"),
    prevent_initial_call=True,
)
def _save_schedule(_save, _clear, cron, campaign_id, session, refresh):
    triggered_n = ctx.triggered[0].get("value") if ctx.triggered else None
    if not triggered_n or not campaign_id:
        return no_update, no_update
    role = (session or {}).get("role", ROLE_MARKETER)
    if role != ROLE_MARKETER:
        return (
            dbc.Alert("Compliance role can't edit the schedule.", color="warning", duration=3000),
            no_update,
        )
    triggered = ctx.triggered_id
    user = (session or {}).get("user_email", "demo@databricks.com")
    if triggered == "info-cron-clear":
        cron = None
    else:
        cron = (cron or "").strip() or None
    metadata.update_campaign_schedule(campaign_id, cron)
    metadata.append_audit(campaign_id, user, "schedule_updated", {"cron": cron})
    msg = f"Schedule set: {cron}" if cron else "Schedule cleared."
    return (
        dbc.Alert(msg, color="success", duration=3500),
        (refresh or 0) + 1,
    )

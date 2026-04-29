"""Campaign detail page — Info / Logic / Analytics tabs."""
from __future__ import annotations

import json
import uuid

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from app.auth import ROLE_COMPLIANCE, ROLE_MARKETER
from app.components.analytics_panel import analytics_panel
from app.components.cytoscape_editor import (
    cytoscape_editor,
    dag_to_cytoscape_elements,
)
from app.components.info_panel import info_panel
from app.components.properties import (
    render_edge_properties,
    render_node_properties,
)
from app.compiler import Dag, compile_preview
from app.compiler.compiler import CompileError
from app.services import metadata, runner

dash.register_page(__name__, path_template="/campaign/<campaign_id>", name="Campaign")


def _new_campaign_skeleton(campaign_id: str, owner: str) -> dict:
    return {
        "id": campaign_id,
        "name": "New campaign",
        "priority": "medium",
        "organization": "",
        "owner": owner,
        "status": "draft",
        "schedule_cron": None,
        "lead_count": None,
        "sub_account_count": None,
        "results_table": None,
        "last_run_at": None,
        "last_run_status": None,
    }


def _load_or_create(campaign_id: str, owner: str) -> tuple[dict, dict]:
    if campaign_id == "new":
        cid = str(uuid.uuid4())[:8]
        c = _new_campaign_skeleton(cid, owner)
        metadata.insert_campaign(c)
        return metadata.get_campaign(cid) or c, {"nodes": [], "edges": []}
    c = metadata.get_campaign(campaign_id) or _new_campaign_skeleton(campaign_id, owner)
    pdef = metadata.get_latest_pipeline_definition(campaign_id)
    return c, (pdef["dag"] if pdef else {"nodes": [], "edges": []})


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
    Input("campaign-id-store", "data"),
    Input("campaign-refresh", "data"),
    State("session-store", "data"),
)
def _render_detail(campaign_id: str, _refresh, session: dict | None):
    role = (session or {}).get("role", ROLE_MARKETER)
    owner = (session or {}).get("user_email", "demo@databricks.com")
    campaign, dag_state = _load_or_create(campaign_id, owner)
    cid = campaign["id"]
    approvals = metadata.list_approvals(cid)
    recent = metadata.recent_runs(cid, limit=10)

    info = info_panel(campaign, approvals, role, recent_runs=recent)
    editor = cytoscape_editor(dag_state)
    analytics = analytics_panel(campaign)

    tabs = dbc.Tabs(
        id="campaign-tabs",
        active_tab="info",
        children=[
            dbc.Tab(html.Div(info, className="pt-3"), label="Info", tab_id="info"),
            dbc.Tab(
                html.Div(editor, className="pt-3"),
                label="Logic",
                tab_id="logic",
            ),
            dbc.Tab(html.Div(analytics, className="pt-3"), label="Analytics", tab_id="analytics"),
        ],
    )

    return html.Div(
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


# --- DAG editor callbacks ---------------------------------------------------


@callback(
    Output("dag-store", "data"),
    Input("dag-add-node", "n_clicks"),
    State("dag-new-id", "value"),
    State("dag-new-type", "value"),
    State("dag-store", "data"),
    prevent_initial_call=True,
)
def _add_node(_n, node_id, node_type, store):
    if not node_id or not node_type:
        return no_update
    nodes = (store or {}).get("nodes", []) or []
    if any(n["id"] == node_id for n in nodes):
        return no_update
    nodes = nodes + [{"id": node_id, "type": node_type, "label": node_id, "config": {}}]
    return {"nodes": nodes, "edges": (store or {}).get("edges", [])}


@callback(
    Output("dag-store", "data", allow_duplicate=True),
    Input("dag-add-edge", "n_clicks"),
    State("dag-edge-source", "value"),
    State("dag-edge-target", "value"),
    State("dag-edge-side", "value"),
    State("dag-store", "data"),
    prevent_initial_call=True,
)
def _add_edge(_n, src, tgt, side, store):
    if not src or not tgt:
        return no_update
    edges = (store or {}).get("edges", []) or []
    if any(e["source"] == src and e["target"] == tgt and e.get("side") == side for e in edges):
        return no_update
    edges = edges + [{"source": src, "target": tgt, "side": side or None}]
    return {"nodes": (store or {}).get("nodes", []), "edges": edges}


def _parse_edge_key(edge_key: str) -> tuple[str, str, str | None]:
    parts = edge_key.split("__")
    src, tgt = parts[0], parts[1]
    side = parts[2] if len(parts) > 2 else None
    return src, tgt, side


def _edge_matches(e: dict, src: str, tgt: str, side: str | None) -> bool:
    return (
        e["source"] == src
        and e["target"] == tgt
        and (e.get("side") or None) == (side or None)
    )


@callback(
    Output("dag-cytoscape", "elements"),
    Output("dag-edge-source", "options"),
    Output("dag-edge-target", "options"),
    Input("dag-store", "data"),
)
def _sync_cytoscape(store):
    elements = dag_to_cytoscape_elements(store)
    nodes = (store or {}).get("nodes", []) or []
    opts = [{"label": n["id"], "value": n["id"]} for n in nodes]
    return elements, opts, opts


@callback(
    Output("dag-selected", "data"),
    Output("dag-properties", "children"),
    Input("dag-cytoscape", "tapNodeData"),
    State("dag-store", "data"),
    prevent_initial_call=True,
)
def _on_node_tap(tap_data, store):
    if not tap_data:
        return no_update, no_update
    node_id = tap_data.get("id")
    nodes = (store or {}).get("nodes", []) or []
    node = next((n for n in nodes if n["id"] == node_id), None)
    return node_id, render_node_properties(node)


@callback(
    Output("dag-selected", "data", allow_duplicate=True),
    Output("dag-properties", "children", allow_duplicate=True),
    Input("dag-cytoscape", "tapEdgeData"),
    State("dag-store", "data"),
    prevent_initial_call=True,
)
def _on_edge_tap(tap_data, store):
    if not tap_data:
        return no_update, no_update
    edge_id = tap_data.get("id") or ""
    src, tgt, side = _parse_edge_key(edge_id)
    edges = (store or {}).get("edges", []) or []
    nodes = (store or {}).get("nodes", []) or []
    edge = next((e for e in edges if _edge_matches(e, src, tgt, side)), None)
    if not edge:
        return no_update, no_update
    target_node = next((n for n in nodes if n["id"] == tgt), None)
    target_is_join = bool(target_node and target_node.get("type") == "join")
    return edge_id, render_edge_properties(edge, target_is_join)


@callback(
    Output("dag-store", "data", allow_duplicate=True),
    Output("dag-action-output", "children", allow_duplicate=True),
    Input("prop-apply", "n_clicks"),
    State("prop-current-id", "data"),
    State("prop-current-type", "data"),
    State("prop-current-kind", "data"),
    State({"role": "prop", "key": ALL}, "value"),
    State({"role": "prop", "key": ALL}, "id"),
    State("dag-store", "data"),
    prevent_initial_call=True,
)
def _apply_properties(_n, current_id, current_type, kind, values, ids, store):
    if not current_id or not store:
        return no_update, no_update

    field_values: dict = {}
    for v, idobj in zip(values, ids):
        field_values[idobj["key"]] = v

    if kind == "node":
        label = field_values.pop("_label", None)
        cfg: dict = {}
        for key, v in field_values.items():
            if key == "columns":
                try:
                    cfg[key] = json.loads(v) if v else []
                except json.JSONDecodeError:
                    return no_update, dbc.Alert("Invalid JSON in 'columns'", color="danger")
            else:
                cfg[key] = v
        new_nodes = []
        for n in store.get("nodes", []):
            if n["id"] == current_id:
                updated = {**n, "config": cfg}
                if label is not None:
                    updated["label"] = label
                new_nodes.append(updated)
            else:
                new_nodes.append(n)
        return (
            {"nodes": new_nodes, "edges": store.get("edges", [])},
            dbc.Alert(f"Updated {current_id}", color="success", duration=3000),
        )

    if kind == "edge":
        src, tgt, old_side = _parse_edge_key(current_id)
        new_side = field_values.get("_side") or None
        new_edges = []
        for e in store.get("edges", []):
            if _edge_matches(e, src, tgt, old_side):
                new_edges.append({**e, "side": new_side})
            else:
                new_edges.append(e)
        return (
            {"nodes": store.get("nodes", []), "edges": new_edges},
            dbc.Alert(f"Updated edge {src} → {tgt}", color="success", duration=3000),
        )

    return no_update, no_update


@callback(
    Output("dag-store", "data", allow_duplicate=True),
    Output("dag-properties", "children", allow_duplicate=True),
    Output("dag-action-output", "children", allow_duplicate=True),
    Input("prop-delete", "n_clicks"),
    State("prop-current-id", "data"),
    State("prop-current-kind", "data"),
    State("dag-store", "data"),
    prevent_initial_call=True,
)
def _delete_via_properties(_n, current_id, kind, store):
    if not current_id or not store:
        return no_update, no_update, no_update
    nodes = list(store.get("nodes", []))
    edges = list(store.get("edges", []))
    if kind == "node":
        nodes = [n for n in nodes if n["id"] != current_id]
        edges = [e for e in edges if e["source"] != current_id and e["target"] != current_id]
        msg = f"Deleted node {current_id} and its connecting edges."
    elif kind == "edge":
        src, tgt, side = _parse_edge_key(current_id)
        edges = [e for e in edges if not _edge_matches(e, src, tgt, side)]
        msg = f"Deleted edge {src} → {tgt}."
    else:
        return no_update, no_update, no_update
    cleared = html.Div("Select a node or edge to edit it.", className="text-muted small")
    return (
        {"nodes": nodes, "edges": edges},
        cleared,
        dbc.Alert(msg, color="success", duration=3000),
    )


@callback(
    Output("dag-action-output", "children"),
    Output("campaign-refresh", "data", allow_duplicate=True),
    Input("dag-save", "n_clicks"),
    Input("dag-preview", "n_clicks"),
    Input("dag-run", "n_clicks"),
    State("dag-store", "data"),
    State("campaign-loaded-id", "data"),
    State("session-store", "data"),
    State("campaign-refresh", "data"),
    prevent_initial_call=True,
)
def _editor_action(_s, _p, _r, store, campaign_id, session, refresh):
    triggered = ctx.triggered_id
    user = (session or {}).get("user_email", "demo@databricks.com")
    if not store or not (store.get("nodes") or []):
        return dbc.Alert("DAG is empty.", color="warning", duration=3000), no_update
    try:
        dag = Dag.model_validate(store)
    except Exception as exc:
        return dbc.Alert(f"Invalid DAG: {exc}", color="danger"), no_update

    if triggered == "dag-save":
        version = metadata.save_pipeline_definition(campaign_id, store, user)
        metadata.append_audit(campaign_id, user, "pipeline_save", {"version": version})
        return (
            dbc.Alert(f"Saved pipeline definition v{version}.", color="success", duration=4000),
            (refresh or 0) + 1,
        )

    if triggered == "dag-preview":
        try:
            sql = compile_preview(dag, limit=200)
        except CompileError as e:
            return dbc.Alert(f"Compile error: {e}", color="danger"), no_update
        return (
            dbc.Card(
                [
                    dbc.CardHeader("Preview SQL"),
                    dbc.CardBody(html.Pre(sql, style={"white-space": "pre-wrap", "font-size": 13})),
                ]
            ),
            no_update,
        )

    if triggered == "dag-run":
        # Save first if there's no saved definition yet
        latest = metadata.get_latest_pipeline_definition(campaign_id)
        if not latest:
            metadata.save_pipeline_definition(campaign_id, store, user)
        try:
            result = runner.run_campaign(campaign_id, user)
        except Exception as e:
            return dbc.Alert(f"Run failed: {e}", color="danger"), (refresh or 0) + 1
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
    triggered = ctx.triggered_id
    user = (session or {}).get("user_email", "demo@databricks.com")
    role = (session or {}).get("role", ROLE_MARKETER)

    if triggered == "approval-submit" and role == ROLE_MARKETER:
        new_status = "pending_approval"
        msg = "Submitted for compliance review."
    elif triggered == "approval-approve" and role == ROLE_COMPLIANCE:
        new_status = "approved"
        msg = "Approved."
    elif triggered == "approval-reject" and role == ROLE_COMPLIANCE:
        new_status = "rejected"
        msg = "Rejected."
    else:
        return dbc.Alert("Action not permitted for your role.", color="warning"), no_update

    metadata.update_campaign_status(campaign_id, new_status)
    metadata.append_approval(campaign_id, new_status, user, comment or "")
    metadata.append_audit(campaign_id, user, f"approval_{new_status}", {"comment": comment or ""})
    return dbc.Alert(msg, color="success", duration=3000), (refresh or 0) + 1


# --- Info save callback ----------------------------------------------------


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
    metadata.update_campaign_info(campaign_id, name, priority, organization, owner)
    return (
        dbc.Alert("Saved.", color="success", duration=2500, className="mt-2"),
        (refresh or 0) + 1,
    )


# --- Run Now / Schedule callbacks (Info tab) -------------------------------


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
    if not campaign_id:
        return no_update, no_update
    user = (session or {}).get("user_email", "demo@databricks.com")
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


@callback(
    Output("info-run-output", "children", allow_duplicate=True),
    Output("campaign-refresh", "data", allow_duplicate=True),
    Input("info-cron-save", "n_clicks"),
    State("info-cron", "value"),
    State("campaign-loaded-id", "data"),
    State("session-store", "data"),
    State("campaign-refresh", "data"),
    prevent_initial_call=True,
)
def _save_schedule(_n, cron, campaign_id, session, refresh):
    if not campaign_id:
        return no_update, no_update
    user = (session or {}).get("user_email", "demo@databricks.com")
    cron = (cron or "").strip() or None
    metadata.update_campaign_schedule(campaign_id, cron)
    metadata.append_audit(
        campaign_id, user, "schedule_updated", {"cron": cron}
    )
    msg = f"Schedule set: {cron}" if cron else "Schedule cleared."
    return (
        dbc.Alert(msg, color="success", duration=3500),
        (refresh or 0) + 1,
    )

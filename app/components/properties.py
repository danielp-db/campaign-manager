"""Render the properties panel for a selected DAG node OR edge."""
from __future__ import annotations

import json

import dash_bootstrap_components as dbc
from dash import dcc, html


def render_node_properties(node: dict | None) -> html.Div:
    if not node:
        return html.Div("Select a node or edge to edit it.", className="text-muted small")

    node_type = node["type"]
    node_id = node["id"]
    cfg = node.get("config") or {}
    label = node.get("label") or node_id

    header = html.Div(
        [
            html.Div(
                f"NODE · {node_type.replace('_', ' ').title()}",
                className="text-uppercase small text-muted",
            ),
            html.H5(node_id, className="mb-3"),
        ]
    )

    label_field = [
        dbc.Label("Display label", className="small"),
        dbc.Input(id={"role": "prop", "key": "_label"}, value=label, placeholder="Shown on canvas"),
    ]

    if node_type == "source_uc":
        body = [
            dbc.Label("Table FQN", className="mt-2"),
            dbc.Input(
                id={"role": "prop", "key": "table_fqn"},
                value=cfg.get("table_fqn", ""),
                placeholder="catalog.schema.table",
            ),
            html.Div(
                "e.g. att_log_anomaly_catalog.prospector_pro.ProspectorPro_subscribers",
                className="form-text",
            ),
        ]
    elif node_type == "source_file":
        body = [
            dbc.Label("Volume Path", className="mt-2"),
            dbc.Input(
                id={"role": "prop", "key": "volume_path"},
                value=cfg.get("volume_path", ""),
                placeholder="/Volumes/<catalog>/<schema>/<volume>/<file>",
            ),
            dbc.Label("Format", className="mt-2"),
            dcc.Dropdown(
                id={"role": "prop", "key": "file_format"},
                options=[
                    {"label": "CSV", "value": "csv"},
                    {"label": "Excel (.xlsx)", "value": "xlsx"},
                ],
                value=cfg.get("file_format", "csv"),
                clearable=False,
            ),
        ]
    elif node_type == "filter":
        body = [
            dbc.Label("Predicate (SQL WHERE clause)", className="mt-2"),
            dbc.Textarea(
                id={"role": "prop", "key": "predicate"},
                value=cfg.get("predicate", ""),
                placeholder="age > 30 AND region = 'TX'",
                style={"font-family": "monospace", "font-size": 13},
                rows=3,
            ),
        ]
    elif node_type == "derive":
        body = [
            dbc.Label("Computed Columns (JSON)", className="mt-2"),
            dbc.Textarea(
                id={"role": "prop", "key": "columns"},
                value=json.dumps(cfg.get("columns", []), indent=2),
                placeholder='[{"name": "ltv", "expression": "arpu * tenure_months"}]',
                style={"font-family": "monospace", "font-size": 13},
                rows=6,
            ),
            html.Div("List of {name, expression} objects.", className="form-text"),
        ]
    elif node_type == "join":
        body = [
            dbc.Label("Join Type", className="mt-2"),
            dcc.Dropdown(
                id={"role": "prop", "key": "join_type"},
                options=[
                    {"label": "Inner", "value": "inner"},
                    {"label": "Left", "value": "left"},
                    {"label": "Right", "value": "right"},
                    {"label": "Full", "value": "full"},
                ],
                value=cfg.get("join_type", "inner"),
                clearable=False,
            ),
            dbc.Label("ON clause", className="mt-2"),
            dbc.Input(
                id={"role": "prop", "key": "on"},
                value=cfg.get("on", ""),
                placeholder="left.account_id = right.account_id",
            ),
            dbc.Label("Select columns (default *)", className="mt-2"),
            dbc.Input(
                id={"role": "prop", "key": "select_columns"},
                value=cfg.get("select_columns", "*"),
                placeholder="left.col1, right.col2, ...",
            ),
            html.Div("Use 'left.' and 'right.' to disambiguate columns.", className="form-text"),
        ]
    elif node_type == "sink":
        body = [
            html.Div(
                "Sink writes the final result to a table named after the campaign. No config needed.",
                className="text-muted small mt-2",
            )
        ]
    else:
        body = [html.Div(f"Unknown node type: {node_type}", className="text-danger")]

    return html.Div(
        [
            header,
            *label_field,
            *body,
            html.Div(
                [
                    dbc.Button("Apply", id="prop-apply", color="primary", size="sm", className="me-2"),
                    dbc.Button(
                        "Delete Node",
                        id="prop-delete",
                        color="danger",
                        outline=True,
                        size="sm",
                    ),
                ],
                className="mt-3",
            ),
            dcc.Store(id="prop-current-id", data=node_id),
            dcc.Store(id="prop-current-type", data=node_type),
            dcc.Store(id="prop-current-kind", data="node"),
        ]
    )


def render_edge_properties(edge: dict | None, target_is_join: bool) -> html.Div:
    if not edge:
        return html.Div("Select a node or edge to edit it.", className="text-muted small")

    side_options = [
        {"label": "(none)", "value": ""},
        {"label": "Left", "value": "left"},
        {"label": "Right", "value": "right"},
    ]

    return html.Div(
        [
            html.Div("EDGE", className="text-uppercase small text-muted"),
            html.H5(f"{edge['source']} → {edge['target']}", className="mb-3"),
            dbc.Label("From", className="small"),
            dbc.Input(value=edge["source"], disabled=True, className="mb-2"),
            dbc.Label("To", className="small"),
            dbc.Input(value=edge["target"], disabled=True, className="mb-2"),
            dbc.Label("Side", className="small"),
            dcc.Dropdown(
                id={"role": "prop", "key": "_side"},
                options=side_options,
                value=edge.get("side") or "",
                clearable=False,
                disabled=not target_is_join,
            ),
            html.Div(
                "Side is only meaningful when the target is a join node."
                if not target_is_join
                else "Choose which input feeds the join's left or right side.",
                className="form-text",
            ),
            html.Div(
                [
                    dbc.Button("Apply", id="prop-apply", color="primary", size="sm", className="me-2"),
                    dbc.Button(
                        "Delete Edge",
                        id="prop-delete",
                        color="danger",
                        outline=True,
                        size="sm",
                    ),
                ],
                className="mt-3",
            ),
            dcc.Store(id="prop-current-id", data=_edge_key(edge)),
            dcc.Store(id="prop-current-type", data="edge"),
            dcc.Store(id="prop-current-kind", data="edge"),
        ]
    )


def _edge_key(edge: dict) -> str:
    """Stable identifier for an edge — matches `dag_to_cytoscape_elements`."""
    eid = f"{edge['source']}__{edge['target']}"
    if edge.get("side"):
        eid += f"__{edge['side']}"
    return eid


# Backward-compat shim: pages/campaign.py used to call render_properties(node)
def render_properties(node: dict | None) -> html.Div:
    return render_node_properties(node)

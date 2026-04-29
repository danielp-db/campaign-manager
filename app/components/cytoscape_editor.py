"""Visual DAG editor backed by dash-cytoscape.

State is held in a `dcc.Store(id='dag-store')` with the shape:
    {"nodes": [{id, type, label, config}], "edges": [{source, target, side?}]}
Cytoscape elements are derived from this state on every render.
"""
from __future__ import annotations

import dash_bootstrap_components as dbc
import dash_cytoscape as cyto
from dash import dcc, html

NODE_TYPES = [
    ("source_uc", "Source · UC Table", "#1f77b4"),
    ("source_file", "Source · File", "#9467bd"),
    ("filter", "Filter", "#2ca02c"),
    ("derive", "Derive", "#ff7f0e"),
    ("join", "Join", "#d62728"),
    ("sink", "Sink", "#7f7f7f"),
]

CYTOSCAPE_STYLESHEET = [
    {
        "selector": "node",
        "style": {
            "background-color": "data(color)",
            "label": "data(label)",
            "color": "#fff",
            "text-valign": "center",
            "text-halign": "center",
            "text-outline-color": "#222",
            "text-outline-width": 1,
            "font-size": 11,
            "width": 140,
            "height": 50,
            "shape": "round-rectangle",
            "border-width": 2,
            "border-color": "#222",
        },
    },
    {
        "selector": "node:selected",
        "style": {"border-color": "#ffd166", "border-width": 4},
    },
    {
        "selector": "edge",
        "style": {
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "line-color": "#888",
            "target-arrow-color": "#888",
            "width": 2,
            "label": "data(side)",
            "font-size": 10,
            "color": "#333",
            "text-background-color": "#fff",
            "text-background-opacity": 0.9,
            "text-background-padding": 2,
        },
    },
]


def dag_to_cytoscape_elements(state: dict) -> list[dict]:
    nodes = state.get("nodes", []) if state else []
    edges = state.get("edges", []) if state else []
    color_by_type = {t[0]: t[2] for t in NODE_TYPES}
    out: list[dict] = []
    for n in nodes:
        out.append(
            {
                "data": {
                    "id": n["id"],
                    "label": n.get("label") or n["id"],
                    "node_type": n["type"],
                    "color": color_by_type.get(n["type"], "#666"),
                }
            }
        )
    for e in edges:
        eid = f"{e['source']}__{e['target']}"
        if e.get("side"):
            eid += f"__{e['side']}"
        out.append(
            {
                "data": {
                    "id": eid,
                    "source": e["source"],
                    "target": e["target"],
                    "side": e.get("side") or "",
                }
            }
        )
    return out


def add_node_form() -> dbc.Card:
    return dbc.Card(
        [
            dbc.CardHeader("Add Node"),
            dbc.CardBody(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Input(id="dag-new-id", placeholder="Node ID (e.g. subs)"),
                                md=4,
                            ),
                            dbc.Col(
                                dcc.Dropdown(
                                    id="dag-new-type",
                                    options=[{"label": l, "value": t} for t, l, _ in NODE_TYPES],
                                    value="source_uc",
                                    clearable=False,
                                ),
                                md=4,
                            ),
                            dbc.Col(
                                dbc.Button(
                                    "Add Node", id="dag-add-node", color="primary", className="w-100"
                                ),
                                md=4,
                            ),
                        ],
                        className="g-2",
                    ),
                ]
            ),
        ],
        className="mb-2",
    )


def add_edge_form() -> dbc.Card:
    return dbc.Card(
        [
            dbc.CardHeader("Add Edge"),
            dbc.CardBody(
                [
                    dbc.Row(
                        [
                            dbc.Col(dcc.Dropdown(id="dag-edge-source", placeholder="From"), md=4),
                            dbc.Col(dcc.Dropdown(id="dag-edge-target", placeholder="To"), md=4),
                            dbc.Col(
                                dcc.Dropdown(
                                    id="dag-edge-side",
                                    placeholder="Side (joins only)",
                                    options=[
                                        {"label": "Left", "value": "left"},
                                        {"label": "Right", "value": "right"},
                                    ],
                                ),
                                md=2,
                            ),
                            dbc.Col(
                                dbc.Button(
                                    "Connect", id="dag-add-edge", color="secondary", className="w-100"
                                ),
                                md=2,
                            ),
                        ],
                        className="g-2",
                    ),
                ]
            ),
        ],
        className="mb-2",
    )


def properties_panel() -> dbc.Card:
    return dbc.Card(
        [
            dbc.CardHeader("Node Properties"),
            dbc.CardBody(
                html.Div(
                    id="dag-properties",
                    children=html.Div(
                        "Select a node to edit its config.", className="text-muted small"
                    ),
                ),
                style={"min-height": "260px"},
            ),
        ],
        className="h-100",
    )


def action_bar() -> html.Div:
    return html.Div(
        [
            dbc.Button("💾 Save Pipeline", id="dag-save", color="primary", className="me-2"),
            dbc.Button("🔍 Preview SQL", id="dag-preview", color="info", className="me-2"),
            dbc.Button("▶ Run Now", id="dag-run", color="success", className="me-2"),
            html.Span(
                "Tap a node or edge to edit it.",
                className="text-muted small ms-2",
            ),
            html.Div(id="dag-action-output", className="mt-3"),
        ],
        className="mt-3",
    )


def cytoscape_editor(initial_state: dict | None = None) -> html.Div:
    state = initial_state or {"nodes": [], "edges": []}
    return html.Div(
        [
            dcc.Store(id="dag-store", data=state),
            dcc.Store(id="dag-selected", data=None),
            dbc.Row(
                [
                    dbc.Col([add_node_form(), add_edge_form()], md=8),
                    dbc.Col(properties_panel(), md=4),
                ],
                className="g-2",
            ),
            cyto.Cytoscape(
                id="dag-cytoscape",
                layout={"name": "breadthfirst", "directed": True, "spacingFactor": 1.4},
                style={"width": "100%", "height": "440px", "border": "1px solid #dee2e6"},
                elements=dag_to_cytoscape_elements(state),
                stylesheet=CYTOSCAPE_STYLESHEET,
            ),
            action_bar(),
        ]
    )

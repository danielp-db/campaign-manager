"""Logic tab UI — form-driven pipeline editor.

Layout:
    [+ Dataset] [+ Filter] [+ Field] [+ Select Field] [+ Join] [+ Union]
    ┌─ Step #1 · DATASET · subs ─────────────────┐
    │  cat.sch.ProspectorPro_subscribers         │
    │                              [Edit] [✕]    │
    └────────────────────────────────────────────┘
    ┌─ Step #2 · FILTER · tx_subs ──────────────┐
    │  from subs · region = 'Texas'             │
    │                              [Edit] [✕]   │
    └───────────────────────────────────────────┘
    ...
    [💾 Save Pipeline] [🔍 Preview SQL] [▶ Run Now]

The shared modal swaps its body when a different button is clicked.
"""
from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html

from app.components.step_forms import OP_BADGE_COLORS, OP_LABELS

OP_BUTTONS = [
    ("dataset", "+ Dataset", "primary"),
    ("filter", "+ Filter", "warning"),
    ("field", "+ Field", "info"),
    ("select", "+ Select Field", "secondary"),
    ("join", "+ Join", "danger"),
    ("union", "+ Union", "success"),
    ("aggregate", "+ Aggregate", "dark"),
    ("custom", "+ Custom Transformation", "secondary"),
]


def _step_summary(step: dict) -> str:
    op = step.get("op")
    if op == "dataset":
        if step.get("source") == "uc":
            return f"SELECT * FROM {step.get('table_fqn', '?')}"
        return f"read_files('{step.get('file_path', '?')}', format => '{step.get('file_format', '?')}')"
    if op == "filter":
        col = step.get("column", "?")
        operator = step.get("operator", "=")
        v = step.get("value", "")
        if operator in ("IS NULL", "IS NOT NULL"):
            tail = ""
        else:
            tail = f" {v}"
        return f"from {step.get('from', '?')} · WHERE {col} {operator}{tail}"
    if op == "field":
        return (
            f"from {step.get('from', '?')} · + ({step.get('expression', '?')}) "
            f"AS {step.get('new_field_name', '?')}"
        )
    if op == "select":
        cols = step.get("columns") or []
        bits = []
        for c in cols[:4]:
            if c.get("alias"):
                bits.append(f"{c['column']} AS {c['alias']}")
            else:
                bits.append(c.get("column", "?"))
        more = f" + {len(cols) - 4} more" if len(cols) > 4 else ""
        return f"from {step.get('from', '?')} · SELECT {', '.join(bits)}{more}"
    if op == "join":
        keys = step.get("keys") or []
        on = " AND ".join(f"{k.get('left', '?')}={k.get('right', '?')}" for k in keys)
        return f"{step.get('left', '?')} {step.get('join_type', '?')} JOIN {step.get('right', '?')} ON {on}"
    if op == "union":
        return f"{step.get('left', '?')} UNION ALL {step.get('right', '?')}"
    if op == "aggregate":
        gb = ", ".join(step.get("group_by") or []) or "(no group)"
        aggs = step.get("aggregations") or []
        bits = aggs[:2]
        more = f" + {len(aggs) - 2} more" if len(aggs) > 2 else ""
        return f"from {step.get('from', '?')} · GROUP BY {gb} · {' | '.join(bits)}{more}"
    if op == "custom":
        sql = (step.get("sql") or "").splitlines()
        first = sql[0].strip() if sql else "(empty)"
        return first[:80] + ("..." if len(first) > 80 else "")
    return ""


def _step_card(step: dict, idx: int, total: int) -> dbc.Card:
    op = step.get("op", "?")
    color = OP_BADGE_COLORS.get(op, "secondary")
    is_last = idx == total - 1
    return dbc.Card(
        dbc.CardBody(
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.Div(
                                [
                                    dbc.Badge(
                                        f"#{idx + 1} · {op.upper()}",
                                        color=color,
                                        className="me-2",
                                    ),
                                    html.Strong(step.get("name", ""), className="me-2"),
                                    (
                                        dbc.Badge("OUTPUT", color="dark", className="ms-1")
                                        if is_last
                                        else None
                                    ),
                                ],
                                className="mb-1",
                            ),
                            html.Code(_step_summary(step), className="small text-muted"),
                        ],
                        md=10,
                    ),
                    dbc.Col(
                        [
                            dbc.Button(
                                "Edit",
                                id={"role": "step-edit", "name": step["name"]},
                                color="link",
                                size="sm",
                                className="me-1",
                            ),
                            dbc.Button(
                                "✕",
                                id={"role": "step-delete", "name": step["name"]},
                                color="link",
                                size="sm",
                                style={"color": "#dc3545"},
                            ),
                        ],
                        md=2,
                        className="text-end",
                    ),
                ],
                className="align-items-center",
            )
        ),
        className="mb-2",
    )


def step_list(pipeline: dict) -> html.Div:
    steps = (pipeline or {}).get("steps") or []
    if not steps:
        return dbc.Alert(
            "No steps yet. Click any of the buttons above to add a Dataset, Filter, "
            "Field, Select, Join, or Union step.",
            color="light",
            className="text-center",
        )
    return html.Div([_step_card(s, i, len(steps)) for i, s in enumerate(steps)])


def step_modal() -> dbc.Modal:
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(id="step-modal-title")),
            dbc.ModalBody(id="step-modal-body"),
            dbc.ModalFooter(
                [
                    dbc.Button("Cancel", id="step-modal-cancel", color="secondary", outline=True),
                    dbc.Button("Save Step", id="step-modal-submit", color="primary"),
                ]
            ),
        ],
        id="step-modal",
        is_open=False,
        size="lg",
        backdrop="static",
    )


def add_step_buttons() -> html.Div:
    return html.Div(
        [
            dbc.Button(
                label,
                id={"role": "open-modal", "op": op},
                color=color,
                outline=(op != "dataset"),
                className="me-2 mb-2",
            )
            for op, label, color in OP_BUTTONS
        ],
        className="mb-3",
    )


def action_bar() -> html.Div:
    return html.Div(
        [
            dbc.Button("💾 Save Pipeline", id="pipeline-save", color="primary", className="me-2"),
            dbc.Button("🔍 Preview SQL", id="pipeline-preview", color="info", className="me-2"),
            dbc.Button(
                "👁 Preview Logic",
                id="pipeline-preview-rows",
                color="info",
                outline=True,
                className="me-2",
            ),
            dbc.Button("▶ Run Now", id="pipeline-run", color="success", className="me-2"),
            html.Span(
                "The last step's output is what gets materialized.",
                className="text-muted small ms-2",
            ),
            dcc.Loading(html.Div(id="pipeline-action-output", className="mt-3"), type="dot"),
        ],
        className="mt-3",
    )


def logic_panel(pipeline: dict | None = None) -> html.Div:
    return html.Div(
        [
            dcc.Store(id="pipeline-store", data=pipeline or {"steps": []}),
            # Holds {"op": "<op>", "editing": "<step_name_or_null>"} when modal open.
            dcc.Store(id="step-modal-state", data=None),
            # UC tables list, populated on first render.
            dcc.Store(id="uc-tables-store", data=[]),
            add_step_buttons(),
            html.Div(id="pipeline-step-list", children=step_list(pipeline)),
            action_bar(),
            step_modal(),
        ]
    )

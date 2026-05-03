"""Modal form bodies for adding/editing pipeline steps.

Each `*_form` returns the modal body for one operation type. Inputs use
pattern-matching IDs so a single submit callback can read all values:
    {"role": "step-form", "key": "<field_name>"}
"""
from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html


OP_LABELS = {
    "dataset": "Add Dataset",
    "filter": "Add Filter",
    "field": "Add Field",
    "select": "Select Field",
    "join": "Add Join",
    "union": "Add Union",
}

OP_BADGE_COLORS = {
    "dataset": "primary",
    "filter": "warning",
    "field": "info",
    "select": "secondary",
    "join": "danger",
    "union": "success",
}

FILTER_OPERATORS = [
    {"label": "= (equals)", "value": "="},
    {"label": "≠ (not equals)", "value": "!="},
    {"label": "> (greater than)", "value": ">"},
    {"label": "≥ (greater or equal)", "value": ">="},
    {"label": "< (less than)", "value": "<"},
    {"label": "≤ (less or equal)", "value": "<="},
    {"label": "LIKE (pattern match)", "value": "LIKE"},
    {"label": "IS NULL", "value": "IS NULL"},
    {"label": "IS NOT NULL", "value": "IS NOT NULL"},
    {"label": "IN (comma-separated)", "value": "IN"},
]

JOIN_TYPES = [
    {"label": "INNER", "value": "INNER"},
    {"label": "LEFT", "value": "LEFT"},
    {"label": "RIGHT", "value": "RIGHT"},
    {"label": "FULL", "value": "FULL"},
]


def _name_field(value: str = "") -> dbc.Row:
    return dbc.Row(
        [
            dbc.Col(dbc.Label("Output TemporaryDataSet name", className="small"), md=12),
            dbc.Col(
                dbc.Input(
                    id={"role": "step-form", "key": "name"},
                    value=value,
                    placeholder="e.g. tx_high_value_subscribers",
                ),
                md=12,
            ),
        ],
        className="mb-3 g-2",
    )


def _from_dropdown(label: str, key: str, names: list[str], value: str = "") -> list:
    return [
        dbc.Label(label, className="small"),
        dcc.Dropdown(
            id={"role": "step-form", "key": key},
            options=[{"label": n, "value": n} for n in names],
            value=value or None,
            placeholder=f"Select a {label.lower()}",
        ),
    ]


def dataset_form(uc_tables: list[str], step: dict | None = None) -> html.Div:
    s = step or {}
    return html.Div(
        [
            _name_field(s.get("name", "")),
            dbc.Label("Source type", className="small"),
            dcc.Dropdown(
                id={"role": "step-form", "key": "source"},
                options=[
                    {"label": "Unity Catalog table", "value": "uc"},
                    {"label": "Uploaded file (CSV / XLSX)", "value": "file"},
                ],
                value=s.get("source", "uc"),
                clearable=False,
                className="mb-2",
            ),
            html.Div(
                [
                    dbc.Label("Table", className="small"),
                    dcc.Dropdown(
                        id={"role": "step-form", "key": "table_fqn"},
                        options=[{"label": t, "value": t} for t in uc_tables],
                        value=s.get("table_fqn") or None,
                        placeholder="Pick a UC table",
                    ),
                    dcc.Loading(
                        html.Div(id="dataset-preview-area", className="mt-3"),
                        type="dot",
                    ),
                ],
                id="dataset-uc-block",
                style={"display": "block" if s.get("source", "uc") == "uc" else "none"},
            ),
            html.Div(
                [
                    dbc.Label("Volume path", className="small"),
                    dbc.Input(
                        id={"role": "step-form", "key": "file_path"},
                        value=s.get("file_path", ""),
                        placeholder="/Volumes/cat/sch/vol/leads.csv",
                    ),
                    dbc.Label("Format", className="small mt-2"),
                    dcc.Dropdown(
                        id={"role": "step-form", "key": "file_format"},
                        options=[
                            {"label": "CSV", "value": "csv"},
                            {"label": "Excel (.xlsx)", "value": "xlsx"},
                        ],
                        value=s.get("file_format", "csv"),
                        clearable=False,
                    ),
                    html.Div(
                        "Upload via the volume directly: databricks fs cp localfile dbfs:/Volumes/...",
                        className="form-text",
                    ),
                ],
                id="dataset-file-block",
                style={"display": "block" if s.get("source") == "file" else "none"},
            ),
        ]
    )


def filter_form(names: list[str], step: dict | None = None) -> html.Div:
    s = step or {}
    return html.Div(
        [
            _name_field(s.get("name", "")),
            dbc.Row(
                [
                    dbc.Col(_from_dropdown("From", "from", names, s.get("from", "")), md=6),
                    dbc.Col(
                        [
                            dbc.Label("Column", className="small"),
                            dbc.Input(
                                id={"role": "step-form", "key": "column"},
                                value=s.get("column", ""),
                                placeholder="column_name",
                            ),
                        ],
                        md=6,
                    ),
                ],
                className="g-2 mb-3",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label("Operator", className="small"),
                            dcc.Dropdown(
                                id={"role": "step-form", "key": "operator"},
                                options=FILTER_OPERATORS,
                                value=s.get("operator", "="),
                                clearable=False,
                            ),
                        ],
                        md=4,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("Value", className="small"),
                            dbc.Input(
                                id={"role": "step-form", "key": "value"},
                                value=s.get("value", ""),
                                placeholder="literal value",
                            ),
                            html.Div(
                                "Numbers stay unquoted. IS NULL / IS NOT NULL ignore the value. "
                                "IN expects a comma-separated list (already quoted if needed).",
                                className="form-text",
                            ),
                        ],
                        md=8,
                    ),
                ],
                className="g-2",
            ),
        ]
    )


def field_form(names: list[str], step: dict | None = None) -> html.Div:
    s = step or {}
    return html.Div(
        [
            _name_field(s.get("name", "")),
            dbc.Row(
                [
                    dbc.Col(_from_dropdown("From", "from", names, s.get("from", "")), md=6),
                    dbc.Col(
                        [
                            dbc.Label("New field name", className="small"),
                            dbc.Input(
                                id={"role": "step-form", "key": "new_field_name"},
                                value=s.get("new_field_name", ""),
                                placeholder="ltv_estimate",
                            ),
                        ],
                        md=6,
                    ),
                ],
                className="g-2 mb-3",
            ),
            dbc.Label("SQL expression", className="small"),
            dbc.Textarea(
                id={"role": "step-form", "key": "expression"},
                value=s.get("expression", ""),
                placeholder="arpu * tenure_months",
                style={"font-family": "monospace", "font-size": 13},
                rows=3,
            ),
            html.Div(
                "Any valid Spark SQL expression referencing columns from the input dataset.",
                className="form-text",
            ),
        ]
    )


def select_form(names: list[str], step: dict | None = None) -> html.Div:
    s = step or {}
    columns_text = ""
    for c in s.get("columns") or []:
        if c.get("alias"):
            columns_text += f"{c['column']} AS {c['alias']}\n"
        else:
            columns_text += f"{c['column']}\n"
    return html.Div(
        [
            _name_field(s.get("name", "")),
            *_from_dropdown("From", "from", names, s.get("from", "")),
            html.Div(className="mb-3"),
            dbc.Label("Columns (one per line, optionally `column AS alias`)", className="small"),
            dbc.Textarea(
                id={"role": "step-form", "key": "columns_text"},
                value=columns_text.strip(),
                placeholder="subscriber_id\narpu AS monthly_revenue\nregion",
                style={"font-family": "monospace", "font-size": 13},
                rows=6,
            ),
        ]
    )


def join_form(names: list[str], step: dict | None = None) -> html.Div:
    s = step or {}
    keys = s.get("keys") or [{"left": "", "right": ""}]
    keys_text = "\n".join(f"{k.get('left', '')} = {k.get('right', '')}" for k in keys)
    return html.Div(
        [
            _name_field(s.get("name", "")),
            dbc.Row(
                [
                    dbc.Col(_from_dropdown("Left", "left", names, s.get("left", "")), md=4),
                    dbc.Col(_from_dropdown("Right", "right", names, s.get("right", "")), md=4),
                    dbc.Col(
                        [
                            dbc.Label("Join type", className="small"),
                            dcc.Dropdown(
                                id={"role": "step-form", "key": "join_type"},
                                options=JOIN_TYPES,
                                value=s.get("join_type", "INNER"),
                                clearable=False,
                            ),
                        ],
                        md=4,
                    ),
                ],
                className="g-2 mb-3",
            ),
            dbc.Label("Join keys (one per line, `left_col = right_col`)", className="small"),
            dbc.Textarea(
                id={"role": "step-form", "key": "keys_text"},
                value=keys_text.strip(),
                placeholder="account_id = account_id\nregion = region",
                style={"font-family": "monospace", "font-size": 13},
                rows=4,
            ),
        ]
    )


def union_form(names: list[str], step: dict | None = None) -> html.Div:
    s = step or {}
    return html.Div(
        [
            _name_field(s.get("name", "")),
            dbc.Row(
                [
                    dbc.Col(_from_dropdown("Left", "left", names, s.get("left", "")), md=6),
                    dbc.Col(_from_dropdown("Right", "right", names, s.get("right", "")), md=6),
                ],
                className="g-2",
            ),
            html.Div(
                "Both datasets must produce the same columns in the same order. "
                "UNION ALL keeps duplicates.",
                className="form-text",
            ),
        ]
    )


def render_form_body(
    op: str,
    pipeline_names: list[str],
    uc_tables: list[str],
    step: dict | None = None,
) -> html.Div:
    if op == "dataset":
        return dataset_form(uc_tables, step)
    if op == "filter":
        return filter_form(pipeline_names, step)
    if op == "field":
        return field_form(pipeline_names, step)
    if op == "select":
        return select_form(pipeline_names, step)
    if op == "join":
        return join_form(pipeline_names, step)
    if op == "union":
        return union_form(pipeline_names, step)
    return html.Div(f"Unknown operation: {op}", className="text-danger")

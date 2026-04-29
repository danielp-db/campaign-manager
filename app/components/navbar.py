"""Top navbar with brand, role switcher, user identity."""
from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html

from app.auth import ROLE_COMPLIANCE, ROLE_MARKETER


def navbar() -> dbc.Navbar:
    return dbc.Navbar(
        dbc.Container(
            [
                dbc.NavbarBrand(
                    [
                        html.Span("ProspectorPro", className="fw-bold"),
                        html.Span(
                            " · Telco Campaign Studio",
                            className="text-light-emphasis ms-2 small",
                        ),
                    ],
                    href="/",
                    className="text-white",
                ),
                dbc.Nav(
                    [
                        dbc.NavItem(
                            dbc.NavLink("Campaigns", href="/", className="text-white-50"),
                            className="me-2",
                        ),
                        dbc.NavItem(
                            dbc.NavLink("Audit Log", href="/audit", className="text-white-50"),
                            className="me-3",
                        ),
                    ],
                    navbar=True,
                ),
                dbc.Nav(
                    [
                        html.Span("Role", className="text-white-50 me-2"),
                        dcc.Dropdown(
                            id="role-switcher",
                            options=[
                                {"label": "Marketer", "value": ROLE_MARKETER},
                                {"label": "Compliance Approver", "value": ROLE_COMPLIANCE},
                            ],
                            clearable=False,
                            value=ROLE_MARKETER,
                            style={"width": "220px"},
                        ),
                        html.Span(id="user-email", className="text-white-50 ms-3 small"),
                    ],
                    className="d-flex align-items-center",
                ),
            ],
            fluid=True,
        ),
        color="dark",
        dark=True,
        className="mb-4",
    )

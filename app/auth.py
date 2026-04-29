"""Session/role helper. Lakebase-backed.

For the demo, role is selectable via UI dropdown; in production this would come from
group membership on the OBO token (`x-forwarded-access-token`).
"""
from __future__ import annotations

import os

from app.services import lakebase

ROLE_MARKETER = "marketer"
ROLE_COMPLIANCE = "compliance_approver"
VALID_ROLES = (ROLE_MARKETER, ROLE_COMPLIANCE)


def current_user_email(request_headers: dict | None = None) -> str:
    """Pull user email from Databricks Apps OBO header, or fall back to local user."""
    if request_headers:
        email = request_headers.get("x-forwarded-email") or request_headers.get("X-Forwarded-Email")
        if email:
            return email
    return os.getenv("USER_EMAIL", "daniel.perez@databricks.com")


def ensure_session(session_id: str | None, user_email: str, default_role: str = ROLE_MARKETER) -> dict:
    if session_id:
        existing = lakebase.get_session(session_id)
        if existing:
            return existing
    new_id = lakebase.create_session(user_email, default_role)
    return lakebase.get_session(new_id) or {
        "session_id": new_id,
        "user_email": user_email,
        "role": default_role,
    }

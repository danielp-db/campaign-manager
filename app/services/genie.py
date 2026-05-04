"""Ask a Genie Space a natural-language question, get back SQL we can paste into a CTE."""
from __future__ import annotations

import logging
import os

from databricks.sdk import WorkspaceClient

log = logging.getLogger(__name__)


class GenieError(RuntimeError):
    pass


def _space_id() -> str:
    sid = os.getenv("PROSPECTORPRO_GENIE_SPACE_ID")
    if not sid:
        raise GenieError(
            "PROSPECTORPRO_GENIE_SPACE_ID not configured. Set it in app.yaml."
        )
    return sid


def ask(question: str) -> dict:
    """Send `question` to Genie, return {sql, description, conversation_id, error}."""
    if not (question or "").strip():
        raise GenieError("Question is empty.")
    space_id = _space_id()
    w = WorkspaceClient()
    try:
        msg = w.genie.start_conversation_and_wait(space_id=space_id, content=question)
    except Exception as exc:
        raise GenieError(f"Genie call failed: {exc}") from exc

    if msg.error:
        raise GenieError(f"Genie returned an error: {msg.error}")

    sql: str | None = None
    description: str | None = None
    title: str | None = None
    text_response: str | None = None
    for att in msg.attachments or []:
        if att.query and att.query.query:
            sql = att.query.query
            description = att.query.description
            title = att.query.title
            break
        if att.text and att.text.content:
            text_response = att.text.content

    if not sql:
        raise GenieError(
            text_response
            or "Genie didn't return a SQL query. Try a more specific question."
        )

    return {
        "sql": sql.strip(),
        "description": description or "",
        "title": title or "",
        "conversation_id": msg.conversation_id,
        "message_id": msg.id,
    }

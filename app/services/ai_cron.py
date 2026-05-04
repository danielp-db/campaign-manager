"""Convert plain-English schedule descriptions to Quartz cron via Databricks ai_query."""
from __future__ import annotations

import re

from app.services import uc

DEFAULT_MODEL = "databricks-meta-llama-3-3-70b-instruct"

_PROMPT = (
    "You convert natural-language schedule descriptions into Quartz cron expressions. "
    "Quartz cron has 7 fields: seconds minutes hours day-of-month month day-of-week year. "
    "Use ? for unused day-of-month or day-of-week. Day-of-week values are SUN MON TUE WED THU FRI SAT. "
    "Hours are 24h (0-23). Examples: "
    "'every day at 6am' -> 0 0 6 * * ?; "
    "'every Monday at 9am' -> 0 0 9 ? * MON; "
    "'every 15 minutes' -> 0 */15 * * * ?; "
    "'1st of each month at midnight' -> 0 0 0 1 * ?. "
    "Output ONLY the cron expression — no explanation, no quotes, no extra whitespace, no labels. "
    "If the description is ambiguous, pick the most reasonable interpretation. "
    "Description: "
)

_CRON_RE = re.compile(r"^[0-9*?,\-/ \tA-Z]+$")


class AiCronError(RuntimeError):
    pass


def text_to_cron(description: str, model: str | None = None) -> str:
    """Returns a Quartz cron string. Raises AiCronError on failure."""
    desc = (description or "").strip()
    if not desc:
        raise AiCronError("Description is empty.")
    if "'" in desc:
        # Avoid breaking the SQL literal; the LLM wouldn't need it anyway.
        desc = desc.replace("'", "")

    full_prompt = _PROMPT + desc
    safe_prompt = full_prompt.replace("'", "''")
    sql = (
        f"SELECT ai_query('{model or DEFAULT_MODEL}', '{safe_prompt}') AS cron"
    )
    try:
        df = uc.query_df(sql)
    except Exception as exc:
        raise AiCronError(f"ai_query call failed: {exc}") from exc
    if df.empty:
        raise AiCronError("ai_query returned no rows.")
    raw = str(df.iloc[0]["cron"]).strip()
    cron = raw.strip().strip("`").strip("'").strip('"').splitlines()[0].strip()
    # Strip common LLM lead-ins.
    cron = re.sub(r"^(cron[: ]|expression[: ])", "", cron, flags=re.IGNORECASE).strip()
    if not cron or not _CRON_RE.match(cron):
        raise AiCronError(f"Model returned an invalid cron: {raw!r}")
    return cron


# --- builder helpers ----------------------------------------------------


DAYS_OF_WEEK = [
    {"label": "Monday", "value": "MON"},
    {"label": "Tuesday", "value": "TUE"},
    {"label": "Wednesday", "value": "WED"},
    {"label": "Thursday", "value": "THU"},
    {"label": "Friday", "value": "FRI"},
    {"label": "Saturday", "value": "SAT"},
    {"label": "Sunday", "value": "SUN"},
]

FREQUENCIES = [
    {"label": "Hourly", "value": "hourly"},
    {"label": "Daily", "value": "daily"},
    {"label": "Weekly", "value": "weekly"},
    {"label": "Monthly", "value": "monthly"},
]


def build_cron(
    frequency: str,
    minute: int = 0,
    hour: int = 6,
    day_of_week: str = "MON",
    day_of_month: int = 1,
) -> str:
    """Build a Quartz cron from builder inputs."""
    minute = max(0, min(59, int(minute)))
    hour = max(0, min(23, int(hour)))
    day_of_month = max(1, min(31, int(day_of_month)))
    if frequency == "hourly":
        return f"0 {minute} * * * ?"
    if frequency == "daily":
        return f"0 {minute} {hour} * * ?"
    if frequency == "weekly":
        if day_of_week not in {d["value"] for d in DAYS_OF_WEEK}:
            day_of_week = "MON"
        return f"0 {minute} {hour} ? * {day_of_week}"
    if frequency == "monthly":
        return f"0 {minute} {hour} {day_of_month} * ?"
    raise ValueError(f"unknown frequency: {frequency}")

"""Demo seed campaigns. Importable by main.py (auto-seed on bootstrap) or
the CLI script (`data/seed_demo.py`) for full materialization."""
from __future__ import annotations

from app.config import SETTINGS
from app.services import metadata

SUBSCRIBERS = SETTINGS.table("subscribers")
ACCOUNTS = SETTINGS.table("accounts")


CAMPAIGN_DRAFT = {
    "id": "C0001",
    "name": "Holiday Upsell Wave 1",
    "priority": "high",
    "organization": "Consumer Marketing",
    "owner": "marketing-ops@att.com",
    "status": "draft",
    "schedule_cron": None,
}

CAMPAIGN_PENDING = {
    "id": "C0002",
    "name": "Texas High-Value Retention",
    "priority": "high",
    "organization": "Customer Success",
    "owner": "retention-ops@att.com",
    "status": "pending_approval",
    "schedule_cron": None,
}

CAMPAIGN_APPROVED = {
    "id": "C0003",
    "name": "Enterprise Upgrade Eligibility Q3",
    "priority": "medium",
    "organization": "Enterprise Marketing",
    "owner": "enterprise-marketing@att.com",
    "status": "approved",
    "schedule_cron": None,
}

CAMPAIGN_SCHEDULED = {
    "id": "C0004",
    "name": "Daily Churn-Risk Refresh",
    "priority": "medium",
    "organization": "Data Science",
    "owner": "ds-marketing@att.com",
    "status": "scheduled",
    "schedule_cron": "0 0 6 * * ?",
}


DAG_PENDING = {
    "nodes": [
        {"id": "subs", "type": "source_uc", "label": "Subscribers", "config": {"table_fqn": SUBSCRIBERS}},
        {
            "id": "f_tx",
            "type": "filter",
            "label": "TX residents",
            "config": {"predicate": "region = 'Texas' AND arpu >= 80"},
        },
        {"id": "sink", "type": "sink", "label": "Output", "config": {}},
    ],
    "edges": [
        {"source": "subs", "target": "f_tx"},
        {"source": "f_tx", "target": "sink"},
    ],
}

DAG_APPROVED = {
    "nodes": [
        {"id": "subs", "type": "source_uc", "label": "Subscribers", "config": {"table_fqn": SUBSCRIBERS}},
        {"id": "accts", "type": "source_uc", "label": "Accounts", "config": {"table_fqn": ACCOUNTS}},
        {
            "id": "elig",
            "type": "filter",
            "label": "Upgrade-eligible",
            "config": {"predicate": "tenure_months >= 24 AND segment = 'Enterprise'"},
        },
        {
            "id": "join",
            "type": "join",
            "label": "Add account info",
            "config": {
                "join_type": "left",
                "on": "left.account_id = right.account_id",
                "select_columns": "left.subscriber_id, left.account_id, left.plan, left.arpu, left.tenure_months, "
                "left.region, left.segment, right.industry, right.employee_count",
            },
        },
        {
            "id": "ltv",
            "type": "derive",
            "label": "Compute LTV",
            "config": {
                "columns": [{"name": "ltv_estimate", "expression": "arpu * tenure_months * 1.0"}]
            },
        },
        {"id": "sink", "type": "sink", "label": "Output", "config": {}},
    ],
    "edges": [
        {"source": "subs", "target": "elig"},
        {"source": "elig", "target": "join", "side": "left"},
        {"source": "accts", "target": "join", "side": "right"},
        {"source": "join", "target": "ltv"},
        {"source": "ltv", "target": "sink"},
    ],
}

DAG_SCHEDULED = {
    "nodes": [
        {"id": "subs", "type": "source_uc", "label": "Subscribers", "config": {"table_fqn": SUBSCRIBERS}},
        {
            "id": "risk",
            "type": "filter",
            "label": "Churn risk > 0.6",
            "config": {"predicate": "churn_score > 0.6"},
        },
        {"id": "sink", "type": "sink", "label": "Output", "config": {}},
    ],
    "edges": [
        {"source": "subs", "target": "risk"},
        {"source": "risk", "target": "sink"},
    ],
}


def seed_if_empty() -> int:
    """If no campaigns exist yet, insert the 4 demo campaigns + DAGs.

    Returns the number of campaigns inserted (0 if already seeded).
    Does NOT run pipelines — that's the user's job in the demo.
    """
    df = metadata.list_campaigns()
    if not df.empty:
        return 0

    metadata.insert_campaign(CAMPAIGN_DRAFT)

    metadata.insert_campaign(CAMPAIGN_PENDING)
    metadata.save_pipeline_definition(
        CAMPAIGN_PENDING["id"], DAG_PENDING, CAMPAIGN_PENDING["owner"]
    )
    metadata.append_approval(
        CAMPAIGN_PENDING["id"],
        "pending_approval",
        CAMPAIGN_PENDING["owner"],
        "Submitted for review",
    )

    metadata.insert_campaign(CAMPAIGN_APPROVED)
    metadata.save_pipeline_definition(
        CAMPAIGN_APPROVED["id"], DAG_APPROVED, CAMPAIGN_APPROVED["owner"]
    )
    metadata.append_approval(
        CAMPAIGN_APPROVED["id"], "approved", "compliance@att.com", "LGTM, no PII concerns"
    )

    metadata.insert_campaign(CAMPAIGN_SCHEDULED)
    metadata.save_pipeline_definition(
        CAMPAIGN_SCHEDULED["id"], DAG_SCHEDULED, CAMPAIGN_SCHEDULED["owner"]
    )
    metadata.append_approval(
        CAMPAIGN_SCHEDULED["id"], "approved", "compliance@att.com", "Auto-approved (low risk)"
    )
    return 4

"""Demo seed campaigns. Importable by main.py (auto-seed on bootstrap) or
the CLI script (`data/seed_demo.py`) for full materialization.

Pipelines use the new step-list (CTE) format from `app.compiler.pipeline`.
"""
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
    "run_mode": "ad_hoc",
    "schedule_cron": None,
}

CAMPAIGN_PENDING = {
    "id": "C0002",
    "name": "Texas High-Value Retention",
    "priority": "high",
    "organization": "Customer Success",
    "owner": "retention-ops@att.com",
    "status": "pending_approval",
    "run_mode": "ad_hoc",
    "schedule_cron": None,
}

CAMPAIGN_APPROVED = {
    "id": "C0003",
    "name": "Enterprise Upgrade Eligibility Q3",
    "priority": "medium",
    "organization": "Enterprise Marketing",
    "owner": "enterprise-marketing@att.com",
    "status": "approved",
    "run_mode": "ad_hoc",
    "schedule_cron": None,
}

CAMPAIGN_SCHEDULED = {
    "id": "C0004",
    "name": "Daily Churn-Risk Refresh",
    "priority": "medium",
    "organization": "Data Science",
    "owner": "ds-marketing@att.com",
    "status": "approved",
    "run_mode": "scheduled",
    "schedule_cron": "0 0 6 * * ?",
}


PIPELINE_PENDING = {
    "steps": [
        {"op": "dataset", "name": "subscribers", "source": "uc", "table_fqn": SUBSCRIBERS},
        {
            "op": "filter",
            "name": "tx_high_value",
            "from": "subscribers",
            "column": "region",
            "operator": "=",
            "value": "Texas",
        },
        {
            "op": "filter",
            "name": "tx_high_value_arpu",
            "from": "tx_high_value",
            "column": "arpu",
            "operator": ">=",
            "value": "80",
        },
    ]
}


PIPELINE_APPROVED = {
    "steps": [
        {"op": "dataset", "name": "subscribers", "source": "uc", "table_fqn": SUBSCRIBERS},
        {"op": "dataset", "name": "accounts", "source": "uc", "table_fqn": ACCOUNTS},
        {
            "op": "filter",
            "name": "enterprise_subs",
            "from": "subscribers",
            "column": "segment",
            "operator": "=",
            "value": "Enterprise",
        },
        {
            "op": "filter",
            "name": "tenured_enterprise",
            "from": "enterprise_subs",
            "column": "tenure_months",
            "operator": ">=",
            "value": "24",
        },
        {
            "op": "join",
            "name": "with_accounts",
            "left": "tenured_enterprise",
            "right": "accounts",
            "join_type": "LEFT",
            "keys": [{"left": "account_id", "right": "account_id"}],
        },
        {
            "op": "field",
            "name": "with_ltv",
            "from": "with_accounts",
            "new_field_name": "ltv_estimate",
            "expression": "arpu * tenure_months",
        },
    ]
}


PIPELINE_SCHEDULED = {
    "steps": [
        {"op": "dataset", "name": "subscribers", "source": "uc", "table_fqn": SUBSCRIBERS},
        {
            "op": "filter",
            "name": "high_churn_risk",
            "from": "subscribers",
            "column": "churn_score",
            "operator": ">",
            "value": "0.6",
        },
    ]
}


def seed_if_empty() -> int:
    df = metadata.list_campaigns()
    if not df.empty:
        return 0

    metadata.insert_campaign(CAMPAIGN_DRAFT)

    metadata.insert_campaign(CAMPAIGN_PENDING)
    metadata.save_pipeline_definition(
        CAMPAIGN_PENDING["id"], PIPELINE_PENDING, CAMPAIGN_PENDING["owner"]
    )
    metadata.append_approval(
        CAMPAIGN_PENDING["id"],
        "pending_approval",
        CAMPAIGN_PENDING["owner"],
        "Submitted for review",
    )

    metadata.insert_campaign(CAMPAIGN_APPROVED)
    metadata.save_pipeline_definition(
        CAMPAIGN_APPROVED["id"], PIPELINE_APPROVED, CAMPAIGN_APPROVED["owner"]
    )
    metadata.append_approval(
        CAMPAIGN_APPROVED["id"], "approved", "compliance@att.com", "LGTM, no PII concerns"
    )

    metadata.insert_campaign(CAMPAIGN_SCHEDULED)
    metadata.save_pipeline_definition(
        CAMPAIGN_SCHEDULED["id"], PIPELINE_SCHEDULED, CAMPAIGN_SCHEDULED["owner"]
    )
    metadata.append_approval(
        CAMPAIGN_SCHEDULED["id"], "approved", "compliance@att.com", "Auto-approved (low risk)"
    )
    return 4

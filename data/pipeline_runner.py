# Databricks notebook source
"""Run a single campaign — thin wrapper around app.services.runner.

Used by the parameterized Job (`ProspectorPro_pipeline_runner`) and as a CLI tool.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.services import runner  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m data.pipeline_runner <campaign_id>", file=sys.stderr)
        sys.exit(2)
    out = runner.run_campaign(sys.argv[1], actor="cli")
    print(out)


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
# Bootstrap the ProspectorPro demo end-to-end:
#   1. Create UC schema + metadata tables
#   2. Generate synthetic Telco data
#   3. Seed demo campaigns
#   4. (Optional) databricks bundle deploy && bundle run

set -euo pipefail

PROFILE="${DATABRICKS_PROFILE:-fevm-att-log-anomaly}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Activating venv"
if [[ ! -d .venv ]]; then
  uv venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing dependencies (offline if cached)"
uv pip install --offline -e . || uv pip install -e .

echo "==> Generating synthetic data"
DATABRICKS_CONFIG_PROFILE="$PROFILE" python -m data.synthetic_data_gen

echo "==> Seeding demo campaigns"
DATABRICKS_CONFIG_PROFILE="$PROFILE" python -m data.seed_demo

echo "==> Bootstrap complete."
echo "Run the app locally:    DATABRICKS_CONFIG_PROFILE=$PROFILE python -m app.main"
echo "Deploy via DAB:         databricks bundle deploy --profile $PROFILE"

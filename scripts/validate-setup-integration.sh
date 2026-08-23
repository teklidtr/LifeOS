#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"

python scripts/validate_manual_links.py
PYTHONPATH=src python -m pytest -q \
  tests/integration/test_fresh_vault_setup.py \
  tests/integration/test_study_learning_workflow.py

if python -c 'import mcp' >/dev/null 2>&1; then
  PYTHONPATH=src python -m pytest -q \
    tests/mcp/test_server.py \
    tests/mcp/test_stdio.py \
    tests/integration/test_mcp_ingestion_lifecycle.py
elif [[ "${LIFEOS_REQUIRE_MCP:-0}" == "1" ]]; then
  echo "MCP integration dependency is required but not installed." >&2
  exit 2
else
  echo "MCP SDK not installed; skipping real STDIO handshake. Run the Docker clean-room gate to require it." >&2
fi

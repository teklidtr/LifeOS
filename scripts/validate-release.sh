#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"
python3 scripts/validate_manual_links.py
PYTHONPATH=src python3 - <<'PY'
import json, pathlib, tomllib
from lifeos.bridge.protocol import PROTOCOL_VERSION
from lifeos.versioning import (
    DESKTOP_RUNTIME_SCHEMA_VERSION,
    MINIMUM_PLUGIN_VERSION,
    PYTHON_PACKAGE_VERSION,
)

def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split('.'))

py=tomllib.loads(pathlib.Path('pyproject.toml').read_text())
pkg=json.loads(pathlib.Path('packages/obsidian-plugin/package.json').read_text())
lock=json.loads(pathlib.Path('packages/obsidian-plugin/package-lock.json').read_text())
manifest=json.loads(pathlib.Path('packages/obsidian-plugin/manifest.json').read_text())
protocol_source=pathlib.Path('packages/obsidian-plugin/src/protocol.ts').read_text()
assert py['project']['version']==PYTHON_PACKAGE_VERSION
assert pkg['version']==manifest['version']==lock['version']==lock['packages']['']['version']
assert version_tuple(pkg['version']) >= version_tuple(MINIMUM_PLUGIN_VERSION)
assert PROTOCOL_VERSION.split('.')[0]=='1'
assert f'PROTOCOL_VERSION = "{PROTOCOL_VERSION}"' in protocol_source
assert f'RUNTIME_SCHEMA_VERSION = {DESKTOP_RUNTIME_SCHEMA_VERSION}' in protocol_source
assert DESKTOP_RUNTIME_SCHEMA_VERSION == 1
print('Release versions, protocol, and runtime schema are compatible.')
PY
PYTHONPATH=src python3 -m pytest --import-mode=importlib \
  tests/copilot tests/e2e/test_goal_plan_copilot.py -q
./scripts/validate-first-class-reviews.sh
npm --prefix packages/obsidian-plugin ci
npm --prefix packages/obsidian-plugin run lint
npm --prefix packages/obsidian-plugin run typecheck
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run build
rm -rf packages/obsidian-plugin/dist-test
git diff --check

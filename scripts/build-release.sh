#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"
./scripts/validate-release.sh
mkdir -p dist
rm -f dist/lifeos-obsidian-plugin.zip dist/lifeos-python-source.zip
(cd packages/obsidian-plugin/build && zip -q -X -r ../../../dist/lifeos-obsidian-plugin.zip .)
git archive --format=zip --prefix=lifeos/ -o dist/lifeos-python-source.zip HEAD src pyproject.toml uv.lock docs scripts
sha256sum dist/lifeos-obsidian-plugin.zip dist/lifeos-python-source.zip > dist/SHA256SUMS

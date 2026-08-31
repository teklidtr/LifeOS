#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"

docker buildx build \
  --platform linux/arm64 \
  --file deploy/home-node/Dockerfile \
  --output type=cacheonly \
  .

echo "Home-node ARM64 image build passed."

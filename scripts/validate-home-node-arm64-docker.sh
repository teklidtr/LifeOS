#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"

image="lifeos-home-node-arm64:${LIFEOS_HOME_NODE_ARM64_TAG:-local}"
docker buildx build \
  --platform linux/arm64 \
  --file deploy/home-node/Dockerfile \
  --tag "$image" \
  --load \
  .

architecture="$(docker image inspect "$image" --format '{{.Architecture}}')"
if [[ "$architecture" != "arm64" ]]; then
  echo "Expected arm64 image, got $architecture" >&2
  exit 1
fi

echo "Home-node ARM64 image build passed."

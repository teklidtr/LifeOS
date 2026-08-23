#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"

image="lifeos-setup-integration:${LIFEOS_SETUP_IMAGE_TAG:-local}"
docker build -f tests/integration/docker/Dockerfile.setup -t "$image" .
docker run --rm "$image"

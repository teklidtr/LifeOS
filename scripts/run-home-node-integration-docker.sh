#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"

image="lifeos-home-node-integration:${LIFEOS_HOME_NODE_IMAGE_TAG:-local}"
container="lifeos-home-node-integration-$$"
tmp="$(mktemp -d)"
vault="$tmp/vault"
runtime="$tmp/runtime"
token_file="$tmp/service-token"

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT

mkdir -p "$vault" "$runtime"
python3 - <<'PY' > "$token_file"
import secrets
print(secrets.token_urlsafe(48))
PY
chmod 0444 "$token_file"

docker build -f deploy/home-node/Dockerfile -t "$image" .
docker run --rm --user 0:0 --entrypoint lifeos \
  -v "$vault:/vault" \
  "$image" init /vault
docker run --rm --user 0:0 --entrypoint sh \
  -v "$vault:/vault" \
  "$image" -c 'chown -R 10001:10001 /vault'
chmod 0777 "$runtime"

canonical_snapshot() {
  python3 - "$vault" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
rows: list[tuple[str, str]] = []
for path in root.rglob("*"):
    if not path.is_file():
        continue
    relative = path.relative_to(root)
    if relative.parts and relative.parts[0] == ".lifeos":
        continue
    rows.append((relative.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
for relative, digest in sorted(rows):
    print(f"{digest}  {relative}")
PY
}

before="$(canonical_snapshot)"

start_node() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker run -d --name "$container" \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --tmpfs /tmp:rw,nosuid,nodev,size=64m \
    -p 127.0.0.1::8000 \
    -v "$vault:/vault" \
    -v "$runtime:/vault/.lifeos" \
    -v "$token_file:/run/secrets/lifeos_service_token:ro" \
    -e LIFEOS_SERVICE_TOKEN_FILE=/run/secrets/lifeos_service_token \
    "$image" \
    serve --config /vault/lifeos.yml \
    --actor-id integration-home-node \
    --host 0.0.0.0 \
    --port 8000 \
    --allowed-host '127.0.0.1:*' >/dev/null
}

host_port() {
  docker port "$container" 8000/tcp | awk -F: 'NR == 1 {print $NF}'
}

wait_for_status() {
  local path="$1"
  local expected="$2"
  local port="$3"
  local attempt
  for attempt in $(seq 1 60); do
    if python3 - "$path" "$expected" "$port" "$token_file" <<'PY'
import sys
import urllib.error
import urllib.request
from pathlib import Path

path, expected, port, token_file = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
headers: dict[str, str] = {}
if path == "/readyz":
    token = Path(token_file).read_text(encoding="utf-8").strip()
    headers["Authorization"] = f"Bearer {token}"
request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
try:
    response = urllib.request.urlopen(request, timeout=2)
    status = response.status
except urllib.error.HTTPError as error:
    status = error.code
except OSError:
    raise SystemExit(1)
raise SystemExit(0 if status == expected else 1)
PY
    then
      return 0
    fi
    sleep 0.25
  done
  echo "Timed out waiting for $path to return HTTP $expected" >&2
  docker logs "$container" >&2 || true
  return 1
}

refresh_registry_over_mcp() {
  docker exec -i "$container" python - <<'PY'
import asyncio
from pathlib import Path

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    token = Path("/run/secrets/lifeos_service_token").read_text(encoding="utf-8").strip()
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    ) as http_client:
        async with streamable_http_client(
            "http://127.0.0.1:8000/mcp",
            http_client=http_client,
        ) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool("registry_refresh", arguments={})
                if result.isError:
                    raise RuntimeError("registry_refresh returned an MCP tool error")


asyncio.run(main())
PY
}

start_node
port="$(host_port)"
wait_for_status /healthz 200 "$port"
wait_for_status /readyz 200 "$port"
wait_for_status /mcp 401 "$port"

if docker logs "$container" 2>&1 | grep -Fq "$(cat "$token_file")"; then
  echo "Service token leaked into container logs" >&2
  exit 1
fi

docker restart "$container" >/dev/null
port="$(host_port)"
wait_for_status /healthz 200 "$port"
wait_for_status /readyz 200 "$port"

docker rm -f "$container" >/dev/null
rm -rf "$runtime"
mkdir -p "$runtime"
chmod 0777 "$runtime"

start_node
port="$(host_port)"
wait_for_status /healthz 200 "$port"
wait_for_status /readyz 200 "$port"
refresh_registry_over_mcp
if [[ ! -s "$runtime/registry.db" ]]; then
  echo "Authenticated registry_refresh did not recreate runtime registry.db" >&2
  exit 1
fi

after="$(canonical_snapshot)"
if [[ "$before" != "$after" ]]; then
  echo "Canonical vault/Git state changed across service restart or runtime rebuild" >&2
  diff -u <(printf '%s\n' "$before") <(printf '%s\n' "$after") >&2 || true
  exit 1
fi

echo "Home-node Docker integration passed: auth boundary, readiness, restart, and runtime rebuild."

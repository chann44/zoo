#!/usr/bin/env bash
# Runs the end-to-end suite against a running stack: waits for the API, signs up a throwaway user, makes an API key
# and runs `pytest -m e2e`. With ZOO_E2E_SERVER set to a POST /servers body (JSON), it registers that server first
# and runs macos/windows sandboxes on it.
#
#   ZOO_RUNTIME=runc docker compose up -d && scripts/e2e.sh
set -euo pipefail

URL="${ZOO_E2E_URL:-http://localhost:8000}"
EMAIL="e2e-$(date +%s)@example.com"
PASSWORD="e2e-$(openssl rand -hex 12)"

json() { python3 -c "import json, sys; print(json.load(sys.stdin)$1)"; }

for _ in $(seq 1 90); do
    curl -fsS "$URL/healthz" >/dev/null 2>&1 && break
    sleep 2
done
curl -fsS "$URL/healthz" >/dev/null || { echo "API at $URL isn't up" >&2; exit 1; }

token=$(curl -fsS -X POST "$URL/auth/signup" -H 'Content-Type: application/json' \
    -d "{\"email\": \"$EMAIL\", \"password\": \"$PASSWORD\", \"name\": \"e2e\"}" | json '["access_token"]')
auth=(-H "Authorization: Bearer $token" -H 'Content-Type: application/json')
key=$(curl -fsS -X POST "$URL/api-keys" "${auth[@]}" -d '{"name": "e2e"}' | json '["key"]')

if [ -n "${ZOO_E2E_SERVER:-}" ]; then
    ZOO_E2E_SERVER_ID=$(curl -fsS -X POST "$URL/servers" "${auth[@]}" -d "$ZOO_E2E_SERVER" | json '["id"]')
    export ZOO_E2E_SERVER_ID
fi

export ZOO_E2E_URL="$URL" ZOO_E2E_API_KEY="$key"
exec uv run pytest -m e2e tests/e2e -v "$@"

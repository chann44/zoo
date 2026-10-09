#!/usr/bin/env bash
# Runs the end-to-end suite against a running stack: waits for the API, signs up a throwaway user, checks the sandbox
# lifecycle over plain curl (including a boot that survives an API restart), then makes an API key and runs
# `pytest -m e2e`. With ZOO_E2E_SERVER set to a POST /servers body (JSON), it registers that server first and runs
# macos/windows sandboxes on it.
#
#   ZOO_RUNTIME=runc docker compose up -d && scripts/e2e.sh
set -euo pipefail

URL="${ZOO_E2E_URL:-http://localhost:8000}"
EMAIL="e2e-$(date +%s)@example.com"
PASSWORD="e2e-$(openssl rand -hex 12)"

json() { python3 -c "import json, sys; print(json.load(sys.stdin)$1)"; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

for _ in $(seq 1 90); do
    curl -fsS "$URL/healthz" >/dev/null 2>&1 && break
    sleep 2
done
curl -fsS "$URL/healthz" >/dev/null || { echo "API at $URL isn't up" >&2; exit 1; }

token=$(curl -fsS -X POST "$URL/auth/signup" -H 'Content-Type: application/json' \
    -d "{\"email\": \"$EMAIL\", \"password\": \"$PASSWORD\", \"name\": \"e2e\"}" | json '["access_token"]')
auth=(-H "Authorization: Bearer $token" -H 'Content-Type: application/json')

status_of() {
    local code
    # a deleted sandbox 404s (owned() refuses deleted ones), which is the status the pollers wait for
    code=$(curl -sS -o "$WORK/body.json" -w '%{http_code}' "$URL/sandboxes/$1" "${auth[@]}") || code="000"
    if [ "$code" = "404" ]; then
        echo deleted
    elif [ "$code" = "200" ]; then
        json '["status"]' <"$WORK/body.json"
    else
        echo "http-$code"
    fi
}

wait_status() { # <sandbox id> <wanted status> <timeout seconds>
    for _ in $(seq 1 $(( $3 / 2 ))); do
        [ "$(status_of "$1")" = "$2" ] && return 0
        sleep 2
    done
    echo "sandbox $1 didn't reach '$2' within ${3}s (last: $(status_of "$1"))" >&2
    exit 1
}

echo "== sandbox lifecycle (curl) =="
sandbox=$(curl -fsS -X POST "$URL/sandboxes" "${auth[@]}" -d '{"kind": "code"}' | json '["id"]')
wait_status "$sandbox" running 240
out=$(curl -fsS -X POST "$URL/sandboxes/$sandbox/exec" "${auth[@]}" -d '{"command": "echo ok"}' | json '["stdout"]')
[ "$out" = "ok" ] || { echo "exec returned '$out'" >&2; exit 1; }
curl -fsS -X POST "$URL/sandboxes/$sandbox/stop" "${auth[@]}" >/dev/null
wait_status "$sandbox" stopped 60
curl -fsS -X DELETE "$URL/sandboxes/$sandbox" "${auth[@]}" >/dev/null
wait_status "$sandbox" deleted 60

echo "== a boot survives a restart of the API and the worker =="
sandbox=$(curl -fsS -X POST "$URL/sandboxes" "${auth[@]}" -d '{"kind": "code"}' | json '["id"]')
sleep 3 # let the boot job start on a worker, then pull it out from under it
docker compose restart api worker >/dev/null
for _ in $(seq 1 90); do
    curl -fsS "$URL/healthz" >/dev/null 2>&1 && break
    sleep 2
done
wait_status "$sandbox" running 300
out=$(curl -fsS -X POST "$URL/sandboxes/$sandbox/exec" "${auth[@]}" -d '{"command": "echo ok"}' | json '["stdout"]')
[ "$out" = "ok" ] || { echo "exec after restart returned '$out'" >&2; exit 1; }
curl -fsS -X DELETE "$URL/sandboxes/$sandbox" "${auth[@]}" >/dev/null
wait_status "$sandbox" deleted 60

key=$(curl -fsS -X POST "$URL/api-keys" "${auth[@]}" -d '{"name": "e2e"}' | json '["key"]')

if [ -n "${ZOO_E2E_SERVER:-}" ]; then
    ZOO_E2E_SERVER_ID=$(curl -fsS -X POST "$URL/servers" "${auth[@]}" -d "$ZOO_E2E_SERVER" | json '["id"]')
    export ZOO_E2E_SERVER_ID
fi

export ZOO_E2E_URL="$URL" ZOO_E2E_API_KEY="$key"
# the suite imports tests/conftest.py, which builds a scratch app of its own on Postgres
export ZOO_TEST_DATABASE_URL="${ZOO_TEST_DATABASE_URL:-postgresql://zoo:zoo@localhost:5432/postgres}"
exec uv run pytest -m e2e tests/e2e -v "$@"

#!/bin/sh
# The API image's command: migrates the database, then starts Zoo. `start.sh migrate` only migrates; ZOO_MIGRATE=0
# skips it.
set -eu
if [ "${ZOO_MIGRATE:-1}" != 0 ]; then
    # under an advisory lock, since every Zoo pod migrates as it starts
    uv run --no-sync python -m db.migrate
fi
[ "${1:-}" = migrate ] && exit 0
exec uv run --no-sync python main.py

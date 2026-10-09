# Zoo: Postgres-only, teams, limits — execution plan

Do the steps in order. Finish each step's "Done when" before starting the next. Do not skip ahead.

## Rules (read before every step)

1. **Postgres only.** After step 4, the words `sqlite`, `DB_PATH`, `local.db`, `zoo_now`, `zoo_rowid`, `postgres_sql`
   must not appear anywhere in the repo outside this file. No "if postgres else sqlite" branches. No compatibility shims.
2. **No fallbacks.** If a required thing is missing (DATABASE_URL, ZOO_OBJECT_STORE, a runtime that can't enforce a
   limit), fail loudly at startup or return an HTTP 400/409 with a clear message. Never silently degrade.
3. **Object storage is required** (S3 API: AWS S3, R2, SeaweedFS). No local-disk storage path for profiles, agent screenshots
   or backups. Local dev uses SeaweedFS from compose.
4. **Fresh database.** The old SQLite and old Postgres schemas are thrown away. There is no data migration and no
   `zoo migrate-db` tool. Existing installs start from an empty database.
5. **No new unit tests.** Each step ends with an end-to-end check (compose + curl). Delete tests that only exist for
   SQLite. The existing test suite must still run against Postgres at the end (step 6, step 28).
6. **Do not commit, push, or create branches.** Leave changes in the working tree. The user commits.
7. **Do not test in a browser.** For UI steps: make it build (`cd web && bun run build`) and stop. The user checks UI.
8. Match the existing code style: same naming, same comment density, docstrings like the surrounding files.
9. After every step run: `uv run ruff check . && uv run ruff format --check . && uv run basedpyright`. Fix what you broke.
10. If a step says "grep", actually run the grep and handle every hit. Do not guess.

## Map of the code you will touch

| Area | Files |
|---|---|
| DB connection | `db/connection.py`, `db/migrate.py` |
| Schema / queries | `db/migrations/` (SQLite, delete), `db/postgres/` (old PG baseline, delete), `db/query.sql`, `sqlc.yml`, `db/generated/` (generated, never hand-edit) |
| Startup | `scripts/start.sh`, `Dockerfile.api`, `compose.yml`, `.env.example`, `makefile` |
| Background work | `server/workers.py` (ZOO_ROLE, leases), `server/jobs.py` (jobs queue) |
| Agent runs | `server/agent_api.py` (`Run`, `follow()` polls the DB every 0.5 s) |
| In-memory state | `server/tickets.py` (VNC/terminal tickets), `server/docker.py` (`owners`, `remotes`) |
| Ownership | `server/auth_api.py` (`personal_workspace`, API key auth ~line 179), `server/sandbox_api.py`, `server/servers_api.py`, `server/vault_api.py`, `server/agent_api.py` |
| Storage | `server/objects.py` (S3 presign), `PROFILE_DIR` in `server/sandbox_api.py`/`server/servers_api.py`, `SCREEN_DIR` in `server/agent_api.py`, backups in `server/admin_api.py` |
| Container limits | `server/docker.py:run_container` (hardcoded `mem_limit="2g"`, `nano_cpus=2_000_000_000`), `server/kube.py`, `server/sandbox_api.py:226` |
| Telemetry | `server/telemetry.py` (SQLite3Instrumentor) |
| Tests | `tests/conftest.py`, `tests/test_migrations.py`, `.github/workflows/ci.yml` (`python`, `postgres`, `schema` jobs) |
| Helm | `deploy/helm/zoo/` (already Postgres via CloudNativePG; keep working) |

---

## Part A — Postgres only

### Step 1. Postgres and object storage in compose — DONE

`compose.yml` already has `postgres` (postgres:17) and `seaweedfs` (S3 API on `seaweedfs:8333`) plus a one-shot
`seaweedfs-init` that creates the `zoo` bucket. MinIO is not used: it no longer publishes images. Do not add it back.
To list objects in any later step: `echo 'fs.ls /buckets/zoo/<prefix>' | docker compose exec -T seaweedfs weed shell`.

### Step 2. One Postgres-native schema

- Delete `db/migrations/*.sql` (SQLite) and `db/postgres/` entirely. Delete `scripts/postgres_schema.py`.
- Create `db/migrations/<timestamp>_baseline.sql` (goose format, `-- +goose Up` / `-- +goose Down`). Start from the
  tables in the old `db/postgres/20261013120000_baseline.sql` (read it before deleting — copy it to the scratch area
  first) and apply these rules to every table:
  - Drop the `zoo_rowid BIGSERIAL` column. Drop the `zoo_now()` function.
  - Every timestamp column (`*_at`, `expires_at`, `started_at`, etc., currently `TEXT`) → `TIMESTAMPTZ`.
    Defaults `zoo_now()` → `now()`.
  - Columns that are 0/1 flags (grep the old SQLite migrations for `INTEGER` columns with `DEFAULT 0`/`DEFAULT 1` or
    `CHECK (x IN (0, 1))`) → `BOOLEAN` with `DEFAULT false/true`.
  - Counters/sizes stay `BIGINT`. `REAL` stays `DOUBLE PRECISION`.
  - JSON stored as text (`config`, `resources`, `metadata`, `scopes`, `capabilities`, ...) stays `TEXT`. Do not switch
    to JSONB in this plan.
  - Keep all PKs, FKs, UNIQUEs, CHECKs and indexes.
  - Tables that were ordered by `rowid` (`jobs`, `pool_sandboxes`, `agent_runs`, `snapshots`, `agent_messages`, the
    tables behind `db/query.sql` lines with `ORDER BY ... rowid`) get `seq BIGINT GENERATED ALWAYS AS IDENTITY` and a
    unique index on it, used as the tiebreaker.
- `sqlc.yml`: `schema: "db/migrations"`, `engine: "postgresql"`, and set the plugin `driver` option to what
  sqlc-gen-python expects for Postgres (check the plugin README for 1.3.0; if `driver` has no Postgres value, remove it).

Done when: `goose -dir db/migrations postgres "$DATABASE_URL" up` succeeds on an empty database, then `down-to 0`, then
`up` again.

### Step 3. Rewrite queries for Postgres

- `db/query.sql` (244 queries): convert to Postgres.
  - `?` placeholders → `$1, $2, ...` (or sqlc's `sqlc.arg(name)`; pick one style and use it everywhere).
  - `rowid` → `seq`.
  - Two-argument `MAX(a, b)` / `MIN(a, b)` → `GREATEST` / `LEAST`. One-argument aggregates stay.
  - `datetime('now', ...)`, `strftime`, `julianday` → `now()`, `now() - interval '...'`, `extract(epoch from ...)`.
  - `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING`; `INSERT OR REPLACE` → `ON CONFLICT (...) DO UPDATE`.
  - `IFNULL` → `COALESCE`. `GROUP_CONCAT` → `string_agg`.
  - Integer booleans in WHERE clauses (`= 1`, `= 0`) → `true`/`false` for columns converted to BOOLEAN.
  - **Every claim query** (an `UPDATE`/`DELETE ... WHERE id = (SELECT ... LIMIT 1)` that picks a job, a queued agent
    run, a pool sandbox): add `FOR UPDATE SKIP LOCKED` inside the subquery explicitly. The old shim in
    `db/connection.py:postgres_sql` did this automatically; that shim is being deleted.
- Run `sqlc generate`. It must succeed with zero errors. Commit nothing; just check `db/generated/` changed.

Done when: `sqlc generate` passes and `grep -nE '\?|rowid|datetime\(|IFNULL|GROUP_CONCAT|INSERT OR' db/query.sql`
returns nothing (except `?` inside string literals, if any).

### Step 4. Postgres-only connection, startup and tooling

- `db/connection.py`: rewrite to Postgres only.
  - Delete `SqliteConn`, `_greatest`, `postgres_sql`, `_postgres_adapters` (the bool-as-int dumper), the `sqlite3`
    import, `_db_path`, the `postgres` property, and the SQLite branch of `get_client`.
  - `IntegrityError = psycopg.IntegrityError` (import psycopg unconditionally).
  - `init_db(url=None)`: read `DATABASE_URL`; if missing or not `postgres://`/`postgresql://`, raise `RuntimeError`.
  - The conn wrapper converts sqlc's placeholders to psycopg's: `$N` → `%(pN)s` (and `%` → `%%` first), pass the dict
    straight through. Cache the conversion with `@cache`.
  - Keep a `numeric` loader only if SUM results otherwise come back as `Decimal` and break callers; otherwise delete.
  - Set the session timezone to UTC in the pool `configure` callback (`SET TIME ZONE 'UTC'`).
  - `execute()` docstring: "in Postgres's dialect".
- `db/migrate.py`: point goose at `db/migrations`.
- `scripts/start.sh`: always run `python -m db.migrate`; delete the SQLite branch.
- `Dockerfile.api`: remove `DB_PATH`, `BACKUP_DIR`, `PROFILE_DIR`, `ZOO_AGENT_DIR` from `ENV`; install
  `postgresql-client` (needed for `pg_dump` in step 27); fix the comment above `start.sh`.
- `makefile`: `up/down/status/reset` use `goose -dir db/migrations postgres "$$DATABASE_URL"`. Delete `DB_FILE`.
- `server/telemetry.py` + `pyproject.toml`: replace `opentelemetry-instrumentation-sqlite3` with
  `opentelemetry-instrumentation-psycopg` and instrument psycopg. `uv lock`.
- `server/admin_api.py`: delete the SQLite file backup code in `POST/GET /admin/backups` (replaced in step 27). Have
  both routes return 501 until then.
- `main.py` and anything calling `db_manager.init_db(db_path=...)` or `db_manager.postgres`: fix.
- Delete `local.db` from the repo root if it is tracked; add `*.db` to `.gitignore` if not there.

Done when: `grep -rniE 'sqlite|DB_PATH|local\.db|zoo_now|zoo_rowid|postgres_sql|db_manager\.postgres' --exclude-dir=web
--exclude-dir=site --exclude-dir=.venv --exclude-dir=node_modules --exclude=PLAN.md .` returns nothing except docs
(fixed in step 29).

### Step 5. Fix Python for the new column types

Generated models now return `datetime` for timestamps and `bool` for flags instead of `str`/`int`.

- Run `uv run basedpyright`. Every new error is a call site to fix. Work through them all.
- Also grep for code that builds or compares timestamp strings: `server/jobs.py:stamp`, `strftime("%Y-%m-%d %H:%M:%S")`
  in `server/nodes.py`, `server/vault_api.py` (`TIMESTAMP`), and any `< ` / `>` comparison between a model's `*_at`
  field and a string. Pass `datetime` objects (timezone-aware, UTC) to queries instead of strings.
- API responses that return timestamps: keep the JSON format the web app already expects. Check how the web parses
  dates (`grep -rn "_at" web/src | head`) and serialize so the output string is unchanged, or update the web to match.
- Flags: replace `== 1` / `== 0` / `int(flag)` on converted columns with plain booleans.

Done when: basedpyright reports no new errors versus `.basedpyright/baseline.json`, and the API boots:
`docker compose up -d --build api` → `curl -fsS localhost:8000/healthz`.

### Step 6. Tests and CI on Postgres only

- `tests/conftest.py`: delete the SQLite path. Tests require `ZOO_TEST_DATABASE_URL`; fail at collection if unset. Each
  test gets a fresh database migrated from `db/migrations`. Delete the helper that translated `datetime('now', ...)`.
- Delete `tests/test_migrations.py` (it only checks SQLite upgrades).
- `.github/workflows/ci.yml`: merge the `python` and `postgres` jobs into one that runs the suite against the Postgres
  service. In the `schema` job, replace the `sqlite3` goose lines with `postgres` against a Postgres service, and keep the
  check that `sqlc generate` produces no diff.

Done when: `ZOO_TEST_DATABASE_URL=postgresql://zoo:zoo@localhost:5432/postgres uv run pytest -x -q` runs (fix failures
caused by steps 2–5; do not delete tests to make them pass unless they test SQLite).

### Step 7. End-to-end check for Part A

With `docker compose up -d --build`:
1. Register a user and log in (routes in `server/auth_api.py`), keep the token.
2. `POST /sandboxes` with `{"kind": "code"}` → wait until `GET /sandboxes/{id}` shows `running`.
3. `POST /sandboxes/{id}/exec` runs `echo ok` → output contains `ok`.
4. `POST /sandboxes/{id}/stop`, then `DELETE /sandboxes/{id}` → status `deleted`.
5. `docker compose restart api` mid-boot of a second sandbox → the boot job resumes and finishes (jobs table survives).

Write the exact curl commands you used into `scripts/e2e.sh` (extend the existing file; it is reused by later steps).

---

## Part B — State out of the process

### Step 8. Object storage for profiles and agent screenshots

- `server/objects.py`: add server-side `put(key, data: bytes)`, `get(key) -> bytes`, `delete(key)` using the existing
  presign helpers + `httpx`. At import/startup, if `ZOO_OBJECT_STORE` is not an `s3://` URL, raise `RuntimeError`.
- Profiles: replace every read/write of `PROFILE_DIR/{version_id}.tar` (`server/servers_api.py` ~263, ~340, ~641;
  `server/sandbox_api.py` ~1037; `server/rotate_secrets.py`) with `objects.put/get/delete("profiles/{version_id}.tar")`.
  Data stays encrypted with `encrypt_bytes` before upload. Delete `PROFILE_DIR` and `write_private` uses for profiles.
- Agent screenshots: `SCREEN_DIR` in `server/agent_api.py` → `objects.put("agent/{run_id}/{message_id}.png.enc")`;
  the screenshot GET route reads from the store.
- `server/security.py` rotate path that rewrites profile files: rewrite through the store.

Done when: save a profile and load it into a new sandbox (curl, routes in `servers_api.py`/`sandbox_api.py`); the object
is listed under `/buckets/zoo/profiles` (see step 1); `docker compose down api && up api` (container filesystem gone) and
the profile still loads.

### Step 9. VNC / terminal tickets in Postgres

- New migration: table `tickets (ticket_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE
  CASCADE, target TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL)`.
- Queries: `create_ticket`, `redeem_ticket` (`DELETE ... WHERE ticket_hash = $1 AND target = $2 AND expires_at > now()
  RETURNING user_id` — single statement, so it is spent exactly once), `purge_tickets` (expired).
- `server/tickets.py`: same `issue()` / `redeem()` signatures, backed by the DB. Store the SHA-256 of the ticket, not the
  ticket. Purge expired rows inside `issue()`. Delete the `_tickets` dict and update the module docstring.

Done when: get a VNC ticket from one API container and open the websocket on a different one (step 12 gives you two);
for now: get a ticket, `docker compose restart api`, redeem it within 30 s → works; redeem twice → second fails.

### Step 10. Remove the Docker `owners` cache

- `server/docker.py`: `container(container_id)` must find the client from the DB, not from `owners` or a scan of every
  client. Look up the sandbox by `runtime_id`, then its `server_id`, then `client_for(server)`. Delete `owners` and the
  loop that probes every client. `remotes` stays (it is a connection cache, not state).
- Grep `owners` in `server/` — no hits left.

Done when: the step-7 e2e passes, including on a sandbox created before an API restart.

### Step 11. Agent run events through LISTEN/NOTIFY

- Wherever `Run.emit()` stores an agent message or updates run usage/state in the DB (`server/agent_api.py`), also run
  `SELECT pg_notify('agent_run', $1)` with the run id, in the same transaction (add a query `notify_agent_run`).
- `follow(run_id)`: replace the 0.5 s sleep loop with a dedicated async psycopg connection (`psycopg.AsyncConnection`,
  autocommit) that `LISTEN agent_run`; on each notification for this run id, read new messages/usage from the DB exactly
  like today. Keep one initial read before waiting so nothing is missed. Close the connection when the stream ends.
- One listening connection per open stream is fine at this scale. Do not add Redis.
- The local `Run.listeners` path for runs executing in the same process can be deleted: every API process uses
  `follow()`, so `ZOO_ROLE=all` and split roles behave the same.

Done when: start an agent run, stream `GET /sandboxes/{id}/agent/stream` with `curl -N`, and events arrive with no 0.5 s
batching; this works in step 12 with the run executing in the worker container and the stream served by the API container.

### Step 12. Separate worker process in compose

The code already supports it (`server/workers.py`, `ZOO_ROLE=api|worker|gateway`).

- `compose.yml`: `api` runs with `ZOO_ROLE=api`; add a `worker` service (same image, same env, `ZOO_ROLE=worker`,
  `ZOO_MIGRATE=0`, no ports, same Docker socket and volumes). Check `server/gateway.py`: if the API and worker need the
  `gateway` role for guest/node connections in a split setup, add a `gateway` service with `ZOO_ROLE=gateway` and set
  `ZOO_GATEWAY` on the others exactly as the module docstring says.
- Confirm job claims and agent run claims use `FOR UPDATE SKIP LOCKED` (step 3) so two workers never take the same row.

Done when: `docker compose up -d --scale worker=2` → run the step-7 e2e plus an agent run; `docker compose logs worker`
shows the jobs split across both workers and no job ran twice.

### Step 13. End-to-end check for Part B

Run all of `scripts/e2e.sh` against `api` + 2× `worker`. Then `docker compose restart api worker` while a sandbox is
booting and an agent run is streaming → boot finishes, the stream can be reopened and continues.

---

## Part C — Teams

### Step 14. Schema for teams

New migration:
- `workspace_members.role` CHECK → `('owner', 'admin', 'member', 'viewer')`; `workspace_invitations.role` CHECK →
  `('admin', 'member', 'viewer')`.
- Add `workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE` to `servers`, `profiles`,
  `vault_secrets`, `nodes`/`node_tokens` (if they are per user today), `agent_channels` if per user. Keep `created_by` /
  `user_id` as "who made it", not "who owns it". Fresh DB, so no backfill.
- `api_keys`: add `sandbox_id TEXT REFERENCES sandboxes(id) ON DELETE CASCADE` (null = whole workspace) and
  `read_only BOOLEAN NOT NULL DEFAULT false`. `expires_at` already exists.
- Indexes on every new `workspace_id` column and on `audit_logs (workspace_id, created_at DESC)`.
- Change the list/get queries: `list_*_by_user(created_by|user_id)` → `list_*_by_workspace(workspace_id)`;
  `get_vault_secret_by_name(user_id, name)` → `(workspace_id, name)`; `find_profile(user_id, ...)` → workspace. Add
  member/invitation queries that don't exist yet (list members, update role, remove member, list invitations, revoke
  invitation, list workspaces for user). `sqlc generate`.

Done when: migration applies on a fresh DB and `sqlc generate` passes.

### Step 15. Workspace context and role checks

- `server/auth_api.py`: add a FastAPI dependency `current_workspace` that returns `(user, workspace_id, role)`.
  - Workspace comes from header `X-Zoo-Workspace`. Missing header → the user's personal workspace
    (`personal_workspace`). That is the defined default, not a fallback.
  - User not an active member → 404 (don't reveal it exists).
  - For an API key, the workspace is the key's `workspace_id`; a header naming a different workspace → 403.
- Role rules, one helper `require(role, minimum)` with order `viewer < member < admin < owner`:
  - viewer: all GETs, open viewer (VNC read-only if supported; otherwise view is allowed and input is refused).
  - member: create/start/stop/delete sandboxes, run tools/exec/agent, use profiles and secrets.
  - admin: manage servers/nodes, vault secrets, profiles, API keys, invitations, members (except owners), quotas,
    workspace settings.
  - owner: everything, including changing/removing admins and deleting the workspace. A workspace always has ≥1 owner.
- Replace every ownership check listed in "Map of the code" (`created_by != user.id`, `user_id != user.id`,
  `list_*_by_user`, `personal_workspace(user, db)`) with the workspace from `current_workspace` + `require`. Grep:
  `grep -rn "created_by != \|user_id != user.id\|_by_user(\|personal_workspace(" server` → only creation-time
  `created_by=user.id` and the default inside `current_workspace` remain.
- `sandbox_members` stays for per-sandbox grants but no longer gates ownership. If nothing uses it after this step,
  leave the table; do not build features on it.

Done when: user A creates a sandbox in workspace W; user B (not a member) gets 404 on it; after B joins W as viewer, B
can GET it but `POST /sandboxes/{id}/exec` returns 403; as member, exec works.

### Step 16. Workspace, member and invitation API

New file `server/workspaces_api.py`, wired like the other `*_api.py` modules in `server/server.py`:
- `GET /workspaces` (mine, with my role), `POST /workspaces` (creator becomes owner), `PATCH /workspaces/{id}` (name),
  `DELETE /workspaces/{id}` (owner; refuse personal workspace and refuse while sandboxes are running).
- `GET /workspaces/{id}/members`, `PATCH /workspaces/{id}/members/{user_id}` (role), `DELETE .../members/{user_id}`.
  Enforce the role rules and the last-owner rule.
- `POST /workspaces/{id}/invitations` → returns the invite token once (store only `token_hash`, expiry 7 days);
  `GET` list; `DELETE` revoke; `POST /invitations/{token}/accept` (logged-in user, email must match).
- No email sending. The UI shows the invite link to copy.

Done when: curl flow — A creates workspace, invites B as member, B accepts, B lists members, A promotes B to admin, A
removes B → B gets 404 on the workspace.

### Step 17. Scoped API keys

- `POST /api-keys` takes `name`, `sandbox_id?`, `read_only`, `expires_at?`. Keys are created in the current workspace;
  only admins can create them. A `sandbox_id` must belong to that workspace.
- Key auth (`server/auth_api.py` ~179): reject revoked or expired keys (401). Update `last_used_at` at most once a minute.
- Enforcement in `current_workspace` / a route dependency:
  - `read_only` → only `GET`/`HEAD` (plus websocket viewers that don't send input); anything else 403.
  - `sandbox_id` set → any route with a `{sandbox_id}` path param must match it; listing routes return only that
    sandbox; routes for other resources (servers, vault, members, keys) → 403.
- The key acts with the role `member` (or `viewer` when read-only) in its workspace, never admin.

Done when: a read-only key can `GET /sandboxes` but `POST /sandboxes` is 403; a sandbox-scoped key can exec in its
sandbox and gets 403 on another sandbox; an expired key gets 401.

### Step 18. Audit log for every write

- Add a middleware in `server/server.py` (or the router) that, after any non-GET request returns 2xx, writes one
  `audit_logs` row: `workspace_id`, `actor_id` (user, or null + API key id in metadata), `action` = `METHOD route
  template` (e.g. `POST /sandboxes/{sandbox_id}/stop`), `resource_type` (first path segment), `resource_id` (the path
  id), `sandbox_id` when the route has one, `metadata` = JSON with `api_key_id`, `ip`, `status`. Never log request bodies
  (secrets).
- Keep the existing specific audit writes (`server/security.py` vault events) — they are richer; don't double-write for
  those routes (skip them in the middleware by route).
- Background actions with no request (idle stop in step 25, scheduled backups in step 27) write their own rows with
  `actor_id` null and `metadata.source = "system"`.
- API: `GET /audit-logs?actor=&action=&resource_type=&sandbox_id=&from=&to=&cursor=` (admin+), paginated by
  `(created_at, id)`; `GET /audit-logs/export?...same filters` streams CSV.

Done when: do the step-16 flow plus a sandbox create/stop; `GET /audit-logs` shows each write with the right actor;
filtering by `sandbox_id` works; export returns CSV with the same rows.

### Step 19. Web UI for teams

In `web/` (TanStack Start). Follow existing page and API-client patterns; read two existing pages first.
- Workspace switcher in the app shell; selected workspace stored per browser and sent as `X-Zoo-Workspace` on every API
  call (one place: the API client).
- Settings → Members: list, change role, remove, invite (shows link to copy), pending invitations with revoke.
- Accept-invite page at the link from step 16.
- API keys page: sandbox scope select, read-only toggle, expiry date.
- Audit log page: table with the filters from step 18 and an Export CSV button.
- Hide actions the current role can't do (the API still enforces).

Done when: `cd web && bun run build` passes. Stop there; the user checks the UI.

### Step 20. End-to-end check for Part C

Extend `scripts/e2e.sh` with the curl flows from steps 15–18, using two users and one shared workspace. Run it.

---

## Part D — Limits and lifecycle

### Step 21. Configurable sandbox size

- New migration: `sandboxes` gets `cpus DOUBLE PRECISION NOT NULL DEFAULT 2`, `memory_mb BIGINT NOT NULL DEFAULT 2048`,
  `disk_gb BIGINT NOT NULL DEFAULT 20`. (The `resources` TEXT column: if nothing reads it, drop it in the same
  migration.)
- `CreateSandboxRequest` (`server/sandbox_api.py:150`): add `cpus`, `memory_mb`, `disk_gb` with bounds from env
  `ZOO_MAX_SANDBOX_CPUS`, `ZOO_MAX_SANDBOX_MEMORY_MB`, `ZOO_MAX_SANDBOX_DISK_GB` (422 when above).
- `server/docker.py:run_container`: take the three values; `mem_limit=f"{memory_mb}m"`, `nano_cpus=int(cpus * 1e9)`,
  `storage_opt={"size": f"{disk_gb}G"}`. If Docker rejects `storage_opt` (storage driver doesn't support quotas), the
  boot fails with that error. No retry without the limit.
- `server/kube.py`: pod `resources.requests` and `limits` for cpu/memory, PVC size = `disk_gb`.
- macOS / Windows (`server/macos.py`, `server/windows.py`): if the request sets a non-default size, return 400
  "sizing is supported on Linux sandboxes only". Do not half-apply.
- Placement by free memory (`server/sandbox_api.py:226`) uses the sandbox's `memory_mb`, not the old constant.
- Upgrade/move must keep the size.

Done when: create a `code` sandbox with `cpus=1, memory_mb=1024` → `docker inspect` shows `NanoCpus=1000000000`,
`Memory=1073741824`; on the kind/k8s setup the pod shows matching limits.

### Step 22. Workspace quotas

- New migration: `workspace_quotas (workspace_id PK FK, max_running_sandboxes BIGINT, max_cpus DOUBLE PRECISION,
  max_memory_mb BIGINT, max_storage_gb BIGINT)` — null column = unlimited. Defaults for new workspaces from env
  `ZOO_DEFAULT_QUOTA_*` (written into the row when the workspace is created).
- Query `workspace_usage(workspace_id)`: count running/provisioning sandboxes and sum their cpus/memory; storage = sum of
  `disk_gb` over non-deleted sandboxes + profile versions + snapshots (sizes you already record; if size isn't recorded
  for profiles/snapshots, record it now on write).
- Enforce on sandbox create and start, inside one transaction: `SELECT ... FROM workspaces WHERE id = $1 FOR UPDATE`
  first (serializes concurrent creates in a workspace), then usage, then compare, then insert/update. Over quota → 409
  with which limit and current usage.
- API: `GET /workspaces/{id}/quota` (usage + limits, members), `PUT` (instance admins only — `ADMIN_EMAILS` — not
  workspace admins).
- UI: show usage vs limits on the workspace settings page; build only.

Done when: set `max_running_sandboxes=1`, start one sandbox, the second create returns 409; fire 5 creates in parallel
(`xargs -P5 curl ...`) on an empty workspace with limit 2 → exactly 2 succeed.

### Step 23. Idle auto-stop and maximum lifetime

- New migration: `sandboxes` gets `last_activity_at TIMESTAMPTZ`, `idle_timeout_minutes BIGINT` (null = use workspace
  default), `max_lifetime_minutes BIGINT` (null = workspace default). `workspaces` gets `default_idle_timeout_minutes`
  and `default_max_lifetime_minutes` (null = never).
- Activity = tool call, exec, agent step, or an open viewer. Update `last_activity_at = now()`:
  - on every tool/exec/agent action (one place: where `tool_executions` rows are written),
  - while a VNC/terminal websocket is open: on connect, then every 60 s from the websocket handler.
  Throttle writes to once per 30 s per sandbox (`WHERE last_activity_at < now() - interval '30 seconds'`).
- A loop in the worker (`server/workers.py` pattern: run only where `works()`, guard with `hold("idle-stop", ...)`)
  every 60 s: find running sandboxes where `COALESCE(last_activity_at, started_at) < now() - idle timeout` or
  `started_at < now() - max lifetime`, and enqueue a normal stop job (same path as `POST /stop`). Write an audit row
  with `metadata.reason = "idle"|"lifetime"`.
- Expose the two settings on create/PATCH sandbox and on workspace settings; show them in the UI (build only).

Done when: set workspace idle timeout to 2 minutes, start a sandbox, do nothing → stopped within ~3 minutes with an
audit row; a sandbox with an open `curl -N` viewer stream or a tool call every minute stays running; max lifetime of
3 minutes stops it even while active.

### Step 24. Home volume snapshots to object storage

Check how snapshots work today (`/sandboxes/{id}/snapshots` in `server/sandbox_api.py`, `snapshots` table) and where the
data ends up. If it lands on the host disk, change it so the snapshot is uploaded to
`objects.put("snapshots/{snapshot_id}...")` (stream with a presigned PUT from the host/zoo-node like `server/macos.py`
move does, not through the API process) and restore downloads from there. Record the size in `snapshots`.

Done when: snapshot a sandbox, delete the sandbox's volume, restore the snapshot into a new sandbox → files are back;
the object is listed under `/buckets/zoo/snapshots` (see step 1).

### Step 25. Scheduled backups to object storage

- Worker loop under lease `hold("backups", ...)` every `ZOO_BACKUP_INTERVAL` (default 24h; `0` disables — that is
  configuration, not a fallback):
  1. `pg_dump --format=custom "$DATABASE_URL"` → upload to `backups/db/{timestamp}.dump`.
  2. For every running or stopped sandbox, take a home snapshot (step 24) tagged `scheduled`.
  3. Keep the last `ZOO_BACKUP_KEEP` (default 7) DB dumps and scheduled snapshots per sandbox; delete older objects.
  4. Audit row per run with `source = "system"`.
- `POST /admin/backups` (instance admin) triggers a run now; `GET /admin/backups` lists DB dumps from the store.
- Restore command: `python -m server.restore db <key>` downloads the dump and runs
  `pg_restore --clean --if-exists --no-owner -d "$DATABASE_URL"`. Document it in `docs/` next to existing backup docs.
  Sandbox homes restore through the existing snapshot restore route.

Done when: trigger a backup, create a user after it, run the restore command → that user is gone and earlier data is
back; listing shows the dump.

### Step 26. CI: tested restore

New job in `.github/workflows/ci.yml` with `postgres` and `seaweedfs` services (same image and S3 config as compose):
1. migrate, seed a few rows (register a user, create a workspace) through the API or SQL,
2. run the backup once (`python -m server.backup` — expose the worker's backup function as a module entry point),
3. drop and recreate the database,
4. run the restore command,
5. assert the seeded rows exist (`psql -c "SELECT count(*) ..."`).

Done when: the job's commands pass locally against compose's postgres + seaweedfs (run them by hand in order).

---

## Part E — Finish

### Step 27. Helm chart

`deploy/helm/zoo/`: remove any SQLite/PVC-for-db options; require `database` and object storage values (fail template
rendering with `required` if missing); add env for the new settings (`ZOO_MAX_SANDBOX_*`, `ZOO_DEFAULT_QUOTA_*`,
`ZOO_BACKUP_INTERVAL`, `ZOO_BACKUP_KEEP`); worker Deployment already exists — make sure it runs the backup/idle loops
(it does if `ZOO_ROLE=worker`).

Done when: `helm lint deploy/helm/zoo` and `helm template deploy/helm/zoo` pass; rendering without a database value
fails with a clear message.

### Step 28. Full suite and e2e

- `ZOO_TEST_DATABASE_URL=... uv run pytest -q` — fix failures caused by this plan.
- `scripts/e2e.sh` against `docker compose up -d --build --scale worker=2` — everything passes.
- ruff + basedpyright clean.

### Step 29. Docs and leftovers

- README, `docs/`, `site/` content, `.env.example`, `TODO.md`: remove every SQLite mention; document Postgres + S3 as
  required, the worker service, teams/roles, scoped keys, audit log, sizes, quotas, idle stop, backups and restore.
- Final grep from step 4 across the whole repo (including `docs/` and `site/`) → only this file matches.
- Tick the items in `TODO.md` that this plan delivered. `zoo migrate-db` is dropped (rule 4) — remove that line.

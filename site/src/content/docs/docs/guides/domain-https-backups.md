---
title: Custom domain, HTTPS, backups and observability
description: Serve the dashboard over your own domain with Caddy, back up sandboxes and the database, and watch the stack in Grafana.
---

## Custom domain and HTTPS

The `domain` compose profile adds Caddy on ports 80 and 443:

```bash
ADMIN_EMAILS=you@example.com ZOO_PUBLIC_IP=<server ip> docker compose --profile domain up -d --build
```

1. Point an A record at the server.
2. Add the hostname under **Profile → Domains** (admins only). The card shows whether DNS
   resolves to `ZOO_PUBLIC_IP` (IPv4 or IPv6); after changing the record, **Check DNS
   again**.
3. Open `https://your.domain`. Caddy gets a Let's Encrypt certificate on the first
   request.

Caddy only issues certificates for hostnames listed in the database, or for `ZOO_DOMAIN`.
It checks with `GET /domains/check?domain=<host>` — case and a trailing dot don't matter;
anything else gets 404, so nobody can make the server request certificates for names it
doesn't serve. On a custom domain the dashboard calls the API at `https://your.domain/api`,
so you don't need to rebuild the web image or configure CORS.

## Backups and restore

- **Sandbox files**: the **Backup** button (or `GET /sandboxes/{id}/backup`) downloads
  `/home/zoo` as a tar; `POST /sandboxes/{id}/restore` with the tar as the body restores
  it. For keeping copies on the same server, [snapshots](#snapshots-and-backups) are the
  faster mechanism.
- **Database**: `zoo backup` (or `POST /admin/backups`) writes a consistent SQLite copy to
  `/opt/zoo/backups`; `zoo restore FILE` puts one back and restarts the API.
  On Postgres (Kubernetes), `/admin/backups` refuses — back up with the database itself.

### Snapshots and backups

A snapshot copies a sandbox's home disk and keeps it on the same server (the **Snapshots**
tab, or `POST /sandboxes/{id}/snapshots`). Linux copies the home volume; macOS clones the
VM bundle as an APFS clone; Windows copies the VM's differencing disk — the latter two
while stopped. Restoring replaces the disk and needs the sandbox stopped. A sandbox keeps
up to `ZOO_MAX_SNAPSHOTS` (10) snapshots. The tar backup stays as an **export format**,
for taking a home folder elsewhere.

## Observability

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to export OpenTelemetry traces, metrics and logs. You
get spans for HTTP requests, tool calls (`tool <name>`, with sandbox, user and channel)
and SQLite queries. Application logs go to the same endpoint.

Metrics (Prometheus names):

| Metric | Labels | |
| --- | --- | --- |
| `zoo_sandboxes` | `status`, `kind` | Sandboxes by state (take the max across API processes) |
| `zoo_job_duration_seconds` | `kind`, `outcome` | How long each attempt of a boot, stop, delete or move ran |
| `zoo_job_wait_seconds` | `kind` | Time from when a job was due to when it started |
| `zoo_tool_duration_seconds` | `tool`, `channel`, `outcome` | Tool call latency |
| `zoo_errors_total` | `source` | Errors from `job`, `tool`, `agent`, `chat`, `vault` and `http` (5xx) |
| `zoo_agent_runs_total`, `zoo_agent_tokens_total` | `outcome` | Finished agent tasks and the tokens they used |

The `observability` profile runs Grafana with Tempo, Loki and Prometheus
(`grafana/otel-lgtm`):

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318 docker compose --profile observability up -d
```

Grafana is at `http://localhost:3001` (admin/admin), or at `ZOO_GRAFANA_DOMAIN` behind
Caddy. The **Zoo** dashboard (Dashboards → Zoo, or `/d/zoo-overview`) is provisioned from
`deploy/grafana`: sandbox states, lifecycle job latency and queue wait, tool latency and
error ratio, errors by source, agent tasks and tokens, and error logs.

# Configuration and observability

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `JWT_SECRET` | required | Signs sessions |
| `ZOO_SECRETS_KEY` | required for new installs | Encrypts secrets, agent keys, app profiles and VNC passwords. The API won't start without it unless users already exist; those older installs fall back to a key derived from `JWT_SECRET` until they set one and run `make rotate-secrets`. |
| `ZOO_SECRETS_KEY_PREVIOUS` | unset | Old keys, comma-separated, kept only until `make rotate-secrets` has run |
| `ZOO_KMS` | unset | Wrap workspace data keys with an external KMS instead of `ZOO_SECRETS_KEY`: `aws:<key ARN>`, `gcp:projects/…/cryptoKeys/<key>` or `vault:<transit mount>/<key>`. See `server/kms.py` for the credentials each one reads. Run `make rotate-secrets` after changing it. |
| `ZOO_OBJECT_STORE` | unset | `s3://<bucket>[/<prefix>]` for moving sandboxes between servers: macOS and Windows disks need it, and Linux homes go through it too when it is set, instead of through the API. Use `ZOO_S3_ENDPOINT` for an S3-compatible store and `ZOO_S3_REGION` for the region; credentials come from `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, or the pod's identity on EKS (IRSA or EKS Pod Identity). See `macos/README.md` and [Windows sandboxes](windows.md). |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies whose `X-Forwarded-For` the API trusts. Behind Caddy, set it to Caddy's address on the `zoo` network, or every client shares Caddy's per-IP rate limit. |
| `ADMIN_EMAILS` | empty | Comma-separated emails allowed to use `/admin/*` and Domains |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Allowed dashboard origins |
| `ZOO_API_URL` | `http://localhost:8000` | API URL the dashboard calls, read at container start (`VITE_API_URL` is the fallback for `bun dev`). The API puts it in installer commands and zoo-node join tokens, so set it to an address the hosts can reach. |
| `DATABASE_URL` | required | A `postgresql://` URL; `scripts/start.sh` migrates it from `db/migrations` |
| `ZOO_OBJECT_STORE` | required | `s3://bucket[/prefix]`: profiles, agent screenshots, snapshots, backups and moves (with `ZOO_S3_ENDPOINT` for SeaweedFS, MinIO, R2) |
| `ZOO_MAX_SANDBOX_CPUS` / `_MEMORY_MB` / `_DISK_GB` | `8` / `16384` / `200` | The largest sandbox anyone may create |
| `ZOO_DEFAULT_QUOTA_RUNNING_SANDBOXES` / `_CPUS` / `_MEMORY_MB` / `_STORAGE_GB` | unset | Quota every new workspace starts with; unset is no limit |
| `ZOO_BACKUP_INTERVAL_HOURS` / `ZOO_BACKUP_KEEP` | `24` / `7` | Scheduled backups to object storage; `0` hours turns them off |
| `ZOO_DB_POOL_SIZE` | `20` | Postgres connections each process keeps at most |
| `ZOO_MIGRATE` | `1` | `0` skips the migrations `scripts/start.sh` runs before the API starts |
| `ZOO_ROLE` | `all` | `all` serves the API and runs background work (lifecycle jobs, agent tasks, the warm pool, the Discord bot); `api` only serves requests; `worker` runs the background work. Scale out with any number of `api` replicas behind one `worker`. `gateway` holds the guest and node connections for the others ([Kubernetes](kubernetes.md)). |
| `ZOO_GATEWAY` | unset | The gateway's internal URL (`http://host:8000`): this process reaches guests and zoo-nodes through it instead of holding them |
| `ZOO_METRICS_PORT` | unset | Serves Prometheus metrics on this port at `/metrics` |
| `ZOO_NODE_PORT` | `7443` | Where each API process listens for [zoo-node](nodes.md) streams (gRPC with mTLS); `off` turns it off. Publish it directly, not through the HTTP proxy. |
| `ZOO_NODE_ENDPOINTS` | the host of `ZOO_API_URL` on `ZOO_NODE_PORT` | Comma-separated `host:port` addresses nodes dial, one per API process. Nodes pick up changes on their next connection. |
| `ZOO_NODE_DIST` | `node/dist` | zoo-node builds served to installers and pushed to nodes on another version (`make node-dist`; the API image has them) |
| `ZOO_MAX_SNAPSHOTS` | `10` | Snapshots kept per sandbox |
| `ZOO_KUBERNETES_NAMESPACE` | unset | Runs this machine's Linux sandboxes as pods in this namespace ([Kubernetes](kubernetes.md)). Zoo uses its service account in a cluster, else `KUBECONFIG` and `ZOO_KUBERNETES_CONTEXT` |
| `ZOO_KUBERNETES_RUNTIME_CLASS` | `kata` | The sandboxes' RuntimeClass; empty for the cluster's default |
| `ZOO_KUBERNETES_STORAGE_CLASS` | unset | StorageClass of the home claims; the cluster's default when unset |
| `ZOO_KUBERNETES_HOME_SIZE` | `10Gi` | Size of each home claim |
| `ZOO_KUBERNETES_SNAPSHOT_CLASS` | unset | A VolumeSnapshotClass: snapshots become CSI volume snapshots instead of copies |
| `ZOO_KUBERNETES_IMAGE_PULL_SECRET` | unset | Pull secret for sandbox and helper pods |
| `ZOO_KUBERNETES_EGRESS_SELECTOR` | `app.kubernetes.io/component=egress` | Label selector of the egress daemon's pods (`ZOO_KUBERNETES_EGRESS_NAMESPACE`, default the sandbox namespace) |
| `ZOO_KUBERNETES_PROBE_IMAGE` | `registry.k8s.io/pause:3.10` | What the requirements check starts on each node |
| `ZOO_AGENT_MODEL` | `anthropic/claude-sonnet-5-5` | The agent's model for workspaces that haven't picked one |
| `ZOO_AGENT_MAX_STEPS`, `ZOO_AGENT_MAX_SECONDS`, `ZOO_AGENT_MAX_TOKENS` | `100`, `1800`, `2000000` | Caps on each agent task's actions, wall-clock seconds and model tokens. Workspaces can set lower limits. |
| `ZOO_AGENT_PARALLEL` | `4` | Agent tasks one worker process runs at once |
| `ZOO_NETWORK` | unset | Docker network shared by the API and sandboxes. Compose sets it to `zoo`. |
| `ZOO_RUNTIME` | `kata` | Docker runtime for sandboxes. `runc` runs plain containers without VM isolation. |
| `ZOO_GUEST_URL` | unset | Websocket URL Linux sandboxes on the API's docker host dial to reach the API (`/guest/connect`). Compose sets it to `ws://api:8000/guest/connect`. Unset, tool calls use `docker exec`. |
| `ZOO_GUEST_REMOTE_URL` | unset | The same for sandboxes on remote servers, e.g. `wss://zoo.example.com/guest/connect`. Required for Windows sandboxes, whose tools all go through the guest. |
| `ZOO_MACOS_BASE` | `zoo-macos-base` | zoovm VM that macOS sandboxes are cloned from |
| `ZOO_MACOS_USER` | `admin` | Guest user for macOS sandboxes |
| `ZOO_MACOS_CPUS`, `ZOO_MACOS_MEMORY_MB` | `4`, `8192` | Size of each macOS sandbox |
| `ZOO_WINDOWS_BASE` | `zoo-windows-base` | Hyper-V VM that Windows sandboxes are cloned from |
| `ZOO_WINDOWS_CPUS`, `ZOO_WINDOWS_MEMORY_MB` | `4`, `8192` | Size of each Windows sandbox |
| `ZOO_WINDOWS_MAX_VMS` | `4` | Windows sandboxes running at once on each server |
| `ZOO_VERSION` | `latest` | Release whose images compose runs. `install.sh` pins it and `zoo upgrade` moves it. |
| `ZOO_REGISTRY` | `docker.io/chann44` | Where compose pulls images from |
| `ZOO_SANDBOX_IMAGE` | `$ZOO_REGISTRY/zoo-sandbox-desktop:$ZOO_VERSION` | Image for `desktop` and `browser` sandboxes |
| `ZOO_CODE_IMAGE` | `$ZOO_REGISTRY/zoo-sandbox-code:$ZOO_VERSION` | Image for `code` sandboxes |
| `ZOO_BROWSER_HOME` | `https://duckduckgo.com` | Start page for `browser` sandboxes |
| `ZOO_SSH_DIR` | `~/.ssh` | SSH keys mounted into the API container (compose) |
| `ZOO_DOMAIN` | unset | Always-allowed domain for Caddy |
| `ZOO_PUBLIC_IP` | unset | This server's public address (or several, comma-separated, IPv4 and IPv6), used to check that a domain's DNS points here |
| `ZOO_GRAFANA_DOMAIN` | `grafana.localhost` | Grafana hostname behind Caddy |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Enables telemetry |
| `OTEL_SERVICE_NAME` | `zoo-api` | Service name in traces |
| `HOST`, `PORT`, `RELOAD` | `127.0.0.1`, `8000`, `1` | API server. The API image sets `HOST=0.0.0.0` and `RELOAD=0`. |

## Observability

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to export OpenTelemetry traces, metrics and logs. You get spans for HTTP requests, tool calls (`tool <name>`, with sandbox, user and channel) and database queries. Application logs go to the same endpoint.

Metrics (Prometheus names):

| Metric | Labels | |
| --- | --- | --- |
| `zoo_sandboxes` | `status`, `kind` | Sandboxes by state (every API process reports it; take the max) |
| `zoo_job_duration_seconds` | `kind`, `outcome` | How long each attempt of a boot, stop, delete or move ran |
| `zoo_job_wait_seconds` | `kind` | Time from when a job was due to when it started |
| `zoo_tool_duration_seconds` | `tool`, `channel`, `outcome` | Tool call latency |
| `zoo_errors_total` | `source` | Errors from `job`, `tool`, `agent`, `chat`, `vault` and `http` (5xx) |
| `zoo_agent_runs_total`, `zoo_agent_tokens_total` | `outcome` | Finished agent tasks and the tokens they used |

The `observability` profile runs Grafana with Tempo, Loki and Prometheus (`grafana/otel-lgtm`):

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318 docker compose --profile observability up -d
```

Grafana is at http://localhost:3001 (admin/admin), or at `ZOO_GRAFANA_DOMAIN` behind Caddy. The **Zoo** dashboard (Dashboards → Zoo, or `/d/zoo-overview`) is provisioned from `deploy/grafana`: sandbox states, lifecycle job latency and queue wait, tool latency and error ratio, errors by source, agent tasks and tokens, and error logs.

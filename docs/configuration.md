# Configuration and observability

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `JWT_SECRET` | required | Signs sessions |
| `ZOO_SECRETS_KEY` | required for new installs | Encrypts secrets, agent keys, app profiles and VNC passwords. The API won't start without it unless users already exist; those older installs fall back to a key derived from `JWT_SECRET` until they set one and run `make rotate-secrets`. |
| `ZOO_SECRETS_KEY_PREVIOUS` | unset | Old keys, comma-separated, kept only until `make rotate-secrets` has run |
| `ZOO_KMS` | unset | Wrap workspace data keys with an external KMS instead of `ZOO_SECRETS_KEY`: `aws:<key ARN>`, `gcp:projects/…/cryptoKeys/<key>` or `vault:<transit mount>/<key>`. See `server/kms.py` for the credentials each one reads. Run `make rotate-secrets` after changing it. |
| `ZOO_OBJECT_STORE` | unset | `s3://<bucket>[/<prefix>]` for moving macOS and Windows sandboxes between servers. Use `ZOO_S3_ENDPOINT` for an S3-compatible store and `ZOO_S3_REGION` for the region; credentials come from `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. See `macos/README.md` and [Windows sandboxes](windows.md). |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies whose `X-Forwarded-For` the API trusts. Behind Caddy, set it to Caddy's address on the `zoo` network, or every client shares Caddy's per-IP rate limit. |
| `ADMIN_EMAILS` | empty | Comma-separated emails allowed to use `/admin/*` and Domains |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Allowed dashboard origins |
| `ZOO_API_URL` | `http://localhost:8000` | API URL the dashboard calls, read at container start. `VITE_API_URL` is the fallback for `bun dev`. |
| `DB_PATH` | `./local.db` | SQLite file |
| `BACKUP_DIR` | `./backups` | DB backups |
| `PROFILE_DIR` | `data/profiles` | Saved app profiles |
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
| `ZOO_PUBLIC_IP` | unset | Used to check domain DNS |
| `ZOO_GRAFANA_DOMAIN` | `grafana.localhost` | Grafana hostname behind Caddy |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Enables telemetry |
| `OTEL_SERVICE_NAME` | `zoo-api` | Service name in traces |
| `HOST`, `PORT`, `RELOAD` | `127.0.0.1`, `8000`, `1` | API server. The API image sets `HOST=0.0.0.0` and `RELOAD=0`. |

## Observability

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to export OpenTelemetry traces and logs. You get spans for HTTP requests, tool calls (`tool <name>`, with sandbox, user and channel) and SQLite queries. Application logs go to the same endpoint.

The `observability` profile runs Grafana with Tempo, Loki and Prometheus (`grafana/otel-lgtm`):

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318 docker compose --profile observability up -d
```

Grafana is at http://localhost:3001 (admin/admin), or at `ZOO_GRAFANA_DOMAIN` behind Caddy.

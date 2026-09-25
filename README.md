# Zoo

Self-hosted sandboxes for AI agents. Each sandbox is a Docker container with a Linux desktop, browser or shell that agents control over REST, MCP or a Python SDK. People watch and take over through a live VNC view in the dashboard.

Linux hosts only.

![Zoo](assets/screenshot.png)

## Contents

- [Quickstart](#quickstart)
- [Sandbox types](#sandbox-types)
- [Security model](#security-model)
- [Using it from agents](#using-it-from-agents): MCP, REST, Python SDK, computer-use agent, Claude Code
- [Remote servers](#remote-servers)
- [App profiles](#app-profiles)
- [Backups](#backups)
- [Custom domain and HTTPS](#custom-domain-and-https)
- [Observability](#observability)
- [Configuration](#configuration)
- [Local development](#local-development)
- [Project layout](#project-layout)
- [Known limitations](#known-limitations)

## Quickstart

Requires Docker with Compose v2.

```bash
cp .env.example .env        # set JWT_SECRET to a long random string
docker compose up -d --build
```

- Dashboard: http://localhost:3000
- API: http://localhost:8000 (OpenAPI docs at `/docs`)

Sign up, create a sandbox, then create an API key under **Profile → API keys**. The key is shown once.

Compose builds three images:

| Image | Used for |
| --- | --- |
| `zoo-sandbox:latest` | `desktop` and `browser` sandboxes (Debian, XFCE, Firefox, noVNC) |
| `zoo-code:latest` | `code` sandboxes (Python 3.12, Node 20, git, ripgrep, Claude Code) |
| API and web | the FastAPI server and the TanStack Start dashboard |

The API talks to Docker through `/var/run/docker.sock` and stores its SQLite database in the `zoo-data` volume. Migrations run on boot.

## Sandbox types

| Type | Display | Tools available | Notes |
| --- | --- | --- | --- |
| `desktop` | XFCE, 1280x720 | all | Firefox, terminal, file manager |
| `browser` | XFCE, 1280x720 | observe, mouse, keyboard, windows, browser | Firefox opens on start (`ZOO_BROWSER_HOME`). No shell. |
| `code` | none | shell, files, `fetch_url` | Claude Code is preinstalled |

Every sandbox:

- runs its processes as the unprivileged user `zoo` (uid 1000);
- keeps `/home/zoo` on its own Docker volume (`zoo-home-<id>`), so files survive stop and start;
- is limited to 2 GB memory, 2 CPUs and 1024 processes, with `no-new-privileges`;
- is reached only through the API. Desktop ports are bound to `127.0.0.1`, or to the compose network.

Stop removes the container and keeps the volume. Start creates a fresh container on the current image and mounts the same volume. Delete removes both.

A container reported as running in the DB but gone from Docker is marked stopped within 15 seconds.

## Security model

Policies are set per sandbox in the dashboard or through the API.

| Control | How it is enforced |
| --- | --- |
| Tool permissions (`shell.exec`, `screen.read`, `input.control`, `files.read`, `files.write`) | Checked by the API before every tool call. A denied call returns 403. |
| Network policy (default allow/deny, DNS on/off, domain, IP and CIDR rules) | iptables `OUTPUT` rules inside the container, applied as root. The agent user can't change them. |
| App policy | The app's binary is made executable only by root (`chmod 700`), so `zoo` can't launch it. |
| Secrets | Fernet-encrypted in the DB (key derived from `JWT_SECRET`) and injected as environment variables when the sandbox starts. |
| Audit | Every tool call is stored with its input, output and status, and shown in the Activity tab. |

Policy changes apply immediately to a running sandbox and are applied again on every start. Secret changes apply on the next start.

## Using it from agents

Every tool is registered once in `server/registry.py` and exposed the same way over REST, MCP and the SDK. `GET /tools?kind=desktop` returns names, parameters and required permissions.

| Category | Tools |
| --- | --- |
| observe | `screenshot` |
| mouse | `click`, `double_click`, `scroll`, `drag` |
| keyboard | `type_text`, `press_key`, `hotkey` |
| windows | `windows_list`, `window_focus`, `window_minimize`, `window_restore`, `window_maximize`, `window_unmaximize`, `window_close` |
| apps | `installed_apps`, `open_app`, `close_app` |
| browser | `open_url` |
| web | `fetch_url` |
| shell | `execute_command` |
| files | `list_files`, `get_file_info`, `read_file`, `write_file`, `create_directory`, `delete_file`, `move_file`, `copy_file` |

### MCP

The MCP server is at `/mcp/` (streamable HTTP) and requires an API key.

```json
{
  "mcpServers": {
    "zoo": {
      "type": "http",
      "url": "http://localhost:8000/mcp/",
      "headers": { "Authorization": "Bearer zoo_..." }
    }
  }
}
```

It exposes every tool, each taking a `sandbox_id`, plus `list_sandboxes`, `create_sandbox` and `get_sandbox`.

### REST

```bash
curl -X POST localhost:8000/sandboxes/$ID/tools/type_text \
  -H "Authorization: Bearer $ZOO_API_KEY" -H "content-type: application/json" \
  -d '{"text": "hello"}'
```

Main endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET/POST /sandboxes`, `GET/DELETE /sandboxes/{id}` | list, create, get, delete |
| `POST /sandboxes/{id}/start`, `/stop`, `/move` | lifecycle and moving between servers |
| `POST /sandboxes/{id}/tools/{name}` | call a tool with a JSON body of arguments |
| `POST /sandboxes/{id}/screenshot`, `/exec` | shortcuts that return PNG bytes and a shell result |
| `GET /sandboxes/{id}/executions` | tool call log |
| `GET /sandboxes/{id}/backup`, `POST /sandboxes/{id}/restore` | tar of `/home/zoo` |
| `/sandboxes/{id}/permissions`, `/network`, `/network/rules`, `/apps`, `/secrets` | policies |
| `/sandboxes/{id}/profiles`, `/profiles` | app profiles |
| `/servers` | remote servers |
| `/api-keys` | API keys |
| `/monitoring` | host and container metrics |
| `/admin/users`, `/admin/sandboxes`, `/admin/backups`, `/admin/domains` | admin only, set by `ADMIN_EMAILS` |

### Python SDK

```bash
pip install ./sdk/python
```

```python
from zoo_sdk import Zoo

zoo = Zoo()                                  # reads ZOO_API_KEY and ZOO_URL
box = zoo.create("research", kind="desktop") # waits until running
box.open_app(command="firefox-esr")
box.click(x=640, y=360)
box.type_text(text="hello")
print(box.exec("ls ~")["stdout"])
open("screen.png", "wb").write(box.screenshot())

box.set_secret("GITHUB_TOKEN", "...")
box.set_network("deny")
box.add_rule("domain", "github.com")
box.backup("box.tar")
box.stop()
```

Any tool can be called as a method (`box.window_focus(window_id=...)`) or with `box.tool(name, **args)`.

### Computer-use agent

A Claude computer-use loop that drives a sandbox.

Python:

```bash
pip install "./sdk/python[agent]"
```

```python
from zoo_sdk import Zoo
from zoo_sdk.agent import Agent

box = Zoo().create("cua")
print(Agent(box, model="claude-sonnet-5").run("Open Firefox and find the weather in Paris"))
```

TypeScript (`examples/cua-ts`), with the same loop written against the REST API:

```bash
cd examples/cua-ts && bun install
ZOO_API_KEY=zoo_... ANTHROPIC_API_KEY=sk-ant-... bun agent.ts "Open Firefox and find the weather in Paris"
```

Both default to the `computer_20251124` tool with the `computer-use-2025-11-24` beta. If your model uses a different version, override it: `tool_version` and `beta` in Python, `TOOL_VERSION` and `BETA` env vars in TypeScript.

### Claude Code in a code sandbox

```python
box = zoo.create("coder", kind="code", wait=False)
box.set_secret("ANTHROPIC_API_KEY", "sk-ant-...")
box.wait(); box.stop(); box.start()          # restart so the secret is injected
box.exec("git clone https://github.com/you/repo ~/work/repo", timeout=120)
result = box.claude("fix the failing test", cwd="~/work/repo", timeout=900)
print(result["result"])
```

`box.claude()` runs `claude -p ... --output-format json --dangerously-skip-permissions` as the `zoo` user and returns the parsed JSON. `examples/claude_code.py` is the full version, with a deny-by-default network that only allows Anthropic, GitHub, PyPI and npm.

## Remote servers

Sandboxes can run on other Linux machines. The API reaches their Docker daemon over SSH.

On each machine:

1. Install Docker and add an SSH user to the `docker` group.
2. Make sure the API host can SSH in with a key and no password prompt. In compose, `ZOO_SSH_DIR` (default `~/.ssh`) is mounted read-only into the API container.

Then add the machine under **Remote Servers**:

- **Docker URL**: `ssh://user@10.0.0.5`, or `tcp://host:2376` for a TLS-configured daemon.
- **Address**: an IP the API can reach, such as a LAN or Tailscale IP. Desktop ports are published on this address, so keep it on a private network.

If a server doesn't have the sandbox image, the API pulls it, or copies it over from the main host.

When creating a sandbox you can pick a server or **Least busy server**. To move a stopped sandbox, use the **Server** tab or `POST /sandboxes/{id}/move`. Its home volume is copied to the target and removed from the source. A server can only be removed once no sandboxes are on it.

## App profiles

Save an app's profile directory (logins, cookies, settings) from a running sandbox and load it into others.

| App | Directory |
| --- | --- |
| `firefox` | `~/.mozilla` |
| `chromium` | `~/.config/chromium` |
| `chrome` | `~/.config/google-chrome` |
| `vscode` | `~/.config/Code` |

Save and load profiles in the sandbox's **Profiles** tab, or choose one in the create dialog to have it loaded before the desktop starts. Profiles are stored as tar files in `PROFILE_DIR`. Close the app before loading a profile into a running sandbox.

## Backups

- **Sandbox files**: the **Backup** button (or `GET /sandboxes/{id}/backup`) downloads `/home/zoo` as a tar. `POST /sandboxes/{id}/restore` with the tar as the body restores it.
- **Database**: `POST /admin/backups` writes a consistent SQLite copy to `BACKUP_DIR`. `GET /admin/backups` lists them.

## Custom domain and HTTPS

The `domain` compose profile adds Caddy on ports 80 and 443.

```bash
ADMIN_EMAILS=you@example.com ZOO_PUBLIC_IP=<server ip> docker compose --profile domain up -d --build
```

1. Point an A record at the server.
2. Add the hostname under **Profile → Domains** (admins only). The card shows whether DNS resolves to `ZOO_PUBLIC_IP`.
3. Open `https://your.domain`. Caddy gets a Let's Encrypt certificate on the first request.

Caddy only issues certificates for hostnames listed in the DB, or for `ZOO_DOMAIN`. It checks with `GET /domains/check`. On a custom domain the dashboard calls the API at `https://your.domain/api`, so you don't need to rebuild the web image or configure CORS.

## Observability

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to export OpenTelemetry traces and logs. You get spans for HTTP requests, tool calls (`tool <name>`, with sandbox, user and channel) and SQLite queries. Application logs go to the same endpoint.

The `observability` profile runs Grafana with Tempo, Loki and Prometheus (`grafana/otel-lgtm`):

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318 docker compose --profile observability up -d
```

Grafana is at http://localhost:3001 (admin/admin), or at `ZOO_GRAFANA_DOMAIN` behind Caddy.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `JWT_SECRET` | required | Signs sessions and derives the secrets encryption key. Changing it makes stored secrets unreadable. |
| `ADMIN_EMAILS` | empty | Comma-separated emails allowed to use `/admin/*` and Domains |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Allowed dashboard origins |
| `VITE_API_URL` | `http://localhost:8000` | API URL built into the dashboard (build arg) |
| `DB_PATH` | `./local.db` | SQLite file |
| `BACKUP_DIR` | `./backups` | DB backups |
| `PROFILE_DIR` | `data/profiles` | Saved app profiles |
| `ZOO_NETWORK` | unset | Docker network shared by the API and sandboxes. Compose sets it to `zoo`. |
| `ZOO_CODE_IMAGE` | `zoo-code:latest` | Image for `code` sandboxes |
| `ZOO_BROWSER_HOME` | `https://duckduckgo.com` | Start page for `browser` sandboxes |
| `ZOO_SSH_DIR` | `~/.ssh` | SSH keys mounted into the API container (compose) |
| `ZOO_DOMAIN` | unset | Always-allowed domain for Caddy |
| `ZOO_PUBLIC_IP` | unset | Used to check domain DNS |
| `ZOO_GRAFANA_DOMAIN` | `grafana.localhost` | Grafana hostname behind Caddy |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Enables telemetry |
| `OTEL_SERVICE_NAME` | `zoo-api` | Service name in traces |
| `HOST`, `PORT`, `RELOAD` | `127.0.0.1`, `8000`, `1` | API server. The API image sets `HOST=0.0.0.0` and `RELOAD=0`. |

## Local development

Requires Python 3.12 with [uv](https://docs.astral.sh/uv/), [bun](https://bun.sh), [goose](https://github.com/pressly/goose) and Docker.

```bash
docker build -t zoo-sandbox:latest .
docker build -f Dockerfile.code -t zoo-code:latest .
make up                         # migrations + sqlc generate
JWT_SECRET=dev uv run python main.py
cd web && bun install && bun run dev
```

To change the schema, add a migration with `make create name=...` and queries in `db/query.sql`, then run `make up`. The DB client in `db/generated` is generated by sqlc. Don't edit it by hand.

## Project layout

```
server/            FastAPI app
  sandbox_api.py   sandbox lifecycle, tool calls, VNC proxy, reconcile loop
  policy_api.py    permissions, network, apps, secrets
  servers_api.py   remote servers and app profiles
  admin_api.py     admin, DB backups, domains
  registry.py      tool registry and sandbox types
  tools.py         tool implementations (xdotool, wmctrl, docker exec)
  docker.py        containers, volumes, iptables, multi-host clients
  telemetry.py     OpenTelemetry setup
mcp_tools/         MCP server built from the registry
db/                migrations, queries, generated client
sdk/python/        zoo_sdk and zoo_sdk.agent
examples/          claude_code.py, cua-ts/
web/               dashboard (TanStack Start, React Query, shadcn)
Dockerfile         desktop sandbox image
Dockerfile.code    code sandbox image
Dockerfile.api     API image
Caddyfile          reverse proxy with on-demand TLS
```

![Architecture](assets/architecture.png)

## Known limitations

- Linux Docker hosts only.
- Domain network rules are resolved to IPs when the rule is applied. If a site changes IPs, re-apply the policy or restart the sandbox.
- Sandboxes created before the `zoo` user and iptables were added must be stopped and started once to pick up the new image. Until then, policies and the Apps tab fail with an "outdated image" error.
- On remote servers the noVNC port is published on the address you configure. The API proxies it with auth, but anything that can reach that address can reach the port.
- Moving a sandbox copies its whole home directory through the API host.
- SQLite with a single API process. Not built for horizontal scaling of the API itself.

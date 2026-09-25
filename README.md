# Zoo

Zoo is a self-hostable sandbox platform that gives AI agents real computers: isolated Linux desktops they can drive over an API, with a live VNC view for humans.

![Zoo](assets/screenshot.png)

## ✨ Features

- **Sandboxes**: Isolated Linux desktops (XFCE, Firefox, terminal) in Docker, one per agent. The desktop runs as an unprivileged `zoo` user.
- **Persistence**: Each sandbox's `/home/zoo` lives on its own volume, so it survives stop and start. Tar backup and restore are included.
- **Sandbox types**: `desktop` (full XFCE), `browser` (Firefox and browser tools only), `code` (shell and files, no display, Python and Node).
- **Tools API**: 29 tools (mouse, keyboard, windows, apps, browser, shell, files, screenshot) through one registry, over REST and MCP.
- **Permissions**: Per-sandbox allow/deny for shell, screen, input, file read and file write. Every call is logged to the Activity tab.
- **Network policy**: Default allow/deny, DNS toggle, and domain/IP/CIDR rules, enforced with iptables inside the sandbox.
- **App policy**: Block any installed GUI app for the agent user.
- **Secrets**: Encrypted at rest and injected as environment variables on start.
- **API keys**: `zoo_...` keys for the REST API, the SDK and MCP.
- **Monitoring**: Host and per-sandbox CPU, memory and network. Container state is synced to the DB every 15s.
- **Remote servers**: Run sandboxes on other Linux machines over SSH, place them automatically on the least busy server, and move a stopped sandbox with its data between servers.
- **App profiles**: Save Firefox, Chromium, Chrome or VS Code profiles (logins, cookies, settings) and load them into any sandbox, or at create time.
- **Observability**: OpenTelemetry traces for requests, tool calls and SQL, plus logs, shipped to Grafana (LGTM stack).
- **Custom domain**: Caddy with automatic HTTPS in front of the UI and API.
- **Live view**: A full-screen noVNC desktop in the browser, behind auth.

## 🚀 Quickstart

```bash
cp .env.example .env   # set JWT_SECRET
docker compose up --build
```

Open http://localhost:3000, sign up, create a sandbox, and create an API key under **Profile → API keys**.

### MCP (Claude, Cursor, ...)

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

### Python SDK

```bash
pip install ./sdk/python
```

```python
from zoo_sdk import Zoo

zoo = Zoo(api_key="zoo_...")
box = zoo.create("research")
box.set_secret("GITHUB_TOKEN", "...")
box.open_app(command="firefox-esr")
box.click(x=640, y=360)
print(box.exec("ls ~")["stdout"])
open("screen.png", "wb").write(box.screenshot())
```

Computer-use agent loop (Claude drives the sandbox):

```bash
pip install "./sdk/python[agent]"   # needs ANTHROPIC_API_KEY
```

```python
from zoo_sdk.agent import run

print(run(zoo.create("cua"), "Open Firefox and find the weather in Paris"))
```

### Examples

- `examples/claude_code.py`: a `code` sandbox running Claude Code headless. The API key is stored as a sandbox secret, the network is locked to Anthropic, GitHub and the package registries, and the diff is printed at the end.

  ```bash
  ZOO_API_KEY=zoo_... ANTHROPIC_API_KEY=sk-ant-... python examples/claude_code.py
  ```

  Or from your own code: `zoo.create(kind="code").claude("fix the failing test", cwd="~/work/repo")`.

- `examples/cua-ts`: the computer-use agent loop in TypeScript with `@anthropic-ai/sdk`, calling the zoo REST API.

  ```bash
  cd examples/cua-ts && bun install
  ZOO_API_KEY=zoo_... ANTHROPIC_API_KEY=sk-ant-... bun agent.ts "Open Firefox and find the weather in Paris"
  ```

### Remote servers

On each machine: install Docker, build the image (`docker build -t zoo-sandbox .`, or let zoo copy it over), and allow SSH key login for a user in the `docker` group. Then add it under **Remote Servers** with `ssh://user@host` and an address that the API can reach, such as a LAN or Tailscale IP. The noVNC ports are published on that address, so keep it on a private network.

### Domain and HTTPS

```bash
ADMIN_EMAILS=you@example.com ZOO_PUBLIC_IP=<server ip> docker compose --profile domain up -d --build
```

Point an A record at the server, then add the hostname under **Profile → Domains**. Caddy issues the certificate on the first visit, and the dashboard calls the API on the same domain at `/api`.

### Grafana

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318 docker compose --profile observability up -d
```

Grafana runs on http://localhost:3001 (admin/admin). Traces are in Tempo and logs are in Loki.

### REST

```bash
curl -X POST localhost:8000/sandboxes/$ID/tools/type_text \
  -H "Authorization: Bearer $ZOO_API_KEY" -H "content-type: application/json" \
  -d '{"text": "hello"}'
```

`GET /tools` lists every tool and its parameters.

### Local development

```bash
docker build -t zoo-sandbox:latest .
make up
uv run python main.py
cd web && bun install && bun run dev
```

## Architecture

![Zoo architecture](assets/architecture.png)

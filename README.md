# Zoo

Zoo is a self-hostable sandbox platform that gives AI agents real computers: isolated Linux desktops they can drive over an API, with a live VNC view for humans.

![Zoo](assets/screenshot.png)

## ✨ Features

- **Sandboxes**: Isolated Linux desktops (XFCE, Firefox, terminal) in Docker, one per agent. The desktop runs as an unprivileged `zoo` user.
- **Persistence**: Each sandbox's `/home/zoo` lives on its own volume, so it survives stop and start. Tar backup and restore are included.
- **Tools API**: 27 tools (mouse, keyboard, windows, apps, shell, files, screenshot) through one registry, over REST and MCP.
- **Permissions**: Per-sandbox allow/deny for shell, screen, input, file read and file write. Every call is logged to the Activity tab.
- **Network policy**: Default allow/deny, DNS toggle, and domain/IP/CIDR rules, enforced with iptables inside the sandbox.
- **App policy**: Block any installed GUI app for the agent user.
- **Secrets**: Encrypted at rest and injected as environment variables on start.
- **API keys**: `zoo_...` keys for the REST API, the SDK and MCP.
- **Monitoring**: Host and per-sandbox CPU, memory and network. Container state is synced to the DB every 15s.
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

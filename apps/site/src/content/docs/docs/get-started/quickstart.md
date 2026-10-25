---
title: Quickstart
description: Install Zoo, create a sandbox, and run your first tool.
---

## 1. Prepare a host

Any Debian/Ubuntu Linux host works; Mac and Windows need a Linux Docker engine (Docker
Desktop). Hosts with KVM get a separate guest kernel per sandbox via Kata; `ZOO_ISOLATION=auto`
falls back to ordinary containers when Kata is absent.

## 2. Install

```bash
curl -fsSL https://github.com/chann44/zoo/releases/latest/download/install.sh | sudo bash -s -- --admin-email you@example.com
```

This installs Docker, Postgres, object storage, the gateway, the API/worker and the
dashboard, then prints the dashboard URL — normally `http://HOST:3000`. Requirements and
every installer option: [Install](/docs/get-started/install/). Kubernetes is an explicit
separate choice, not a fallback.

## 3. Create a sandbox

Open the dashboard URL and sign up (accounts in `ADMIN_EMAILS` are administrators), create
a desktop, browser or code sandbox, then create an API key under your profile. macOS and
Windows sandboxes need an enrolled VM host first: [Remote servers](/docs/guides/remote-servers/).

Or do both from the CLI:

```bash
pip install 'zoo-sdk[cli]'
zoo login --url http://localhost:8000     # paste your API key
zoo create --kind code
zoo ls
```

## 4. Run a tool

```bash
zoo exec SANDBOX_ID -- uname -a
```

```python
from zoo_sdk import Zoo

zoo = Zoo()  # reads ZOO_API_KEY and ZOO_URL
with zoo.sandbox(kind="desktop") as box:  # deleted on exit, also on error
    png = box.screenshot()  # a PNG of the sandbox screen
```

The SDK adds the `/v1` prefix itself. Point Claude Code, Claude Desktop or any MCP client
at Zoo with [the MCP guide](/docs/get-started/mcp/).

## Next steps

- [Your first sandbox](/docs/get-started/first-sandbox/) — kinds, tools, stop and resume
- [Connect Claude Code or Claude Desktop](/docs/get-started/mcp/)
- [Install](/docs/get-started/install/) — requirements, options, offline bundles
- [Remote servers](/docs/guides/remote-servers/) — add Linux, Mac and Windows hosts

:::note
Zoo supplies sandboxes and tools — it does not host a model, planner, task runner or chat
integration. [Performance](/docs/reference/performance/) figures are targets, not
benchmark results.
:::

---
title: Connect Claude Code or Claude Desktop
description: Point any MCP client at Zoo's MCP endpoint and it gets every sandbox tool — with an API key, over streamable HTTP.
---

Zoo's MCP server speaks streamable HTTP at `/mcp/` and requires an API key. It exposes
every [sandbox tool](/docs/reference/tools/), each taking a `sandbox_id`, plus
`list_sandboxes`, `create_sandbox` and `get_sandbox` — so the agent can get its own
computer.

| Setup | URL |
| --- | --- |
| Local install | `http://localhost:8000/mcp/` |
| Behind [Caddy](/docs/guides/domain-https-backups/) | `https://your.domain/api/mcp/` |

## Claude Desktop

Add Zoo to `claude_desktop_config.json`:

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

## Claude Code

Claude Code reads the same `mcpServers` shape from a `.mcp.json` at the project root, so
every session in that project gets the tools:

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

## Try it

Ask the agent:

```text
list the sandboxes, then create a code sandbox and run uname -a in it
```

It will call `list_sandboxes`, `create_sandbox`, then `execute_command` with the new
sandbox's ID. Everything the agent does shows up in the dashboard's **Activity** tab.

Replace `zoo_...` with an API key from **Profile → API keys**. Every other MCP client that
speaks streamable HTTP works the same way — the URL and the `Authorization` header are all
it needs.

## What the agent can do

Tools are grouped by category — observe, mouse, keyboard, windows, apps, browser, web,
shell and files — and each is gated by the sandbox's [permissions](/docs/guides/policies/#tool-permissions).
The full list, with arguments, permissions and which sandbox kinds support each tool, is
generated from the code: [Tools reference](/docs/reference/tools/).

:::note
The MCP server serves the same tools as the REST API and the Python SDK — one registry,
three doors. Administrative deployment and offline restore are separate operations.
:::

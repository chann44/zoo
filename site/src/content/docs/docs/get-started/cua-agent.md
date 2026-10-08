---
title: A computer-use agent in 5 minutes
description: Run a Claude computer-use loop on your machine — in Python or TypeScript — that drives a Zoo sandbox.
---

A computer-use agent runs on **your machine**, plans steps with Claude, and carries them
out inside a Zoo sandbox: screenshot, click, type, repeat. The sandbox is the agent's
computer; your machine just holds the loop.

## Python

```bash
pip install "./sdk/python[agent]"
```

```python
from zoo_sdk import Zoo
from zoo_sdk.agent import Agent

box = Zoo().create("cua")
print(Agent(box, model="claude-sonnet-5").run("Open Firefox and find the weather in Paris"))
```

`Zoo()` reads `ZOO_API_KEY` and `ZOO_URL` from the environment. `create()` waits until the
sandbox is running; on a [warm pool](/docs/concepts/architecture/#the-warm-pool) host that
takes about a second.

## TypeScript

The same loop, written against the REST API, is in `examples/cua-ts`:

```bash
cd examples/cua-ts && bun install
ZOO_API_KEY=zoo_... ANTHROPIC_API_KEY=sk-ant-... bun agent.ts "Open Firefox and find the weather in Paris"
```

## Versions

Both default to the `computer_20251124` tool with the `computer-use-2025-11-24` beta. If
your model uses a different version, override it: `tool_version` and `beta` in Python,
`TOOL_VERSION` and `BETA` environment variables in TypeScript.

## Server-side alternative

You don't need a local loop: every desktop, browser, macOS and Windows sandbox has a
computer-use agent **on the server**, reachable from the dashboard's Agent tab, over the
REST API, or from Slack, Discord and WhatsApp. See
[The built-in agent and chat channels](/docs/guides/chat-channels/) — or stream its events
from the SDK:

```python
for event in Zoo().sandbox(sandbox_id).ask("Open Firefox and find the weather in Paris"):
    print(event["type"], event.get("text", ""))
```

The local loop is for when you want the conversation and the screenshots on your side of
the wire; the built-in agent keeps tasks running even when the client disconnects.

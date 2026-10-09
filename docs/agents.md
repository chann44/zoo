# Using Zoo from agents

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

zoo = Zoo()  # reads ZOO_API_KEY and ZOO_URL
box = zoo.create("research", kind="desktop")  # waits until running
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

### CUA agent (built in)

Every desktop, browser, macOS and Windows sandbox has a [CUA](https://github.com/trycua/cua) computer-use agent on the server. Chat with it from the **Agent** tab on the sandbox page, over the REST API, or from Slack, Discord and WhatsApp. Its actions go through the same tools, permissions and Activity log as API and MCP calls.

Pick the provider and model under **Agent → Model** (per workspace, `PUT /agent/settings`). The provider key lives in the vault: type it in and it's saved as `AGENT_<PROVIDER>_API_KEY`, or pick any vault secret. Without settings the agent uses the server default: `ZOO_AGENT_MODEL` as a [CUA model string](https://cua.ai/docs) (default `anthropic/claude-sonnet-5-5`) with `ANTHROPIC_API_KEY` (or the key for whichever provider it uses) from the API's environment.

Every task has limits, and the agent stops with an error when it reaches one:

| Limit | Server cap (environment) | Default |
| --- | --- | --- |
| Actions | `ZOO_AGENT_MAX_STEPS` | 100 |
| Wall-clock time | `ZOO_AGENT_MAX_SECONDS` | 1800 (30 minutes) |
| Model tokens | `ZOO_AGENT_MAX_TOKENS` | 2,000,000 |

A workspace can set lower limits in its agent settings, never higher ones. The Agent tab shows the running task's actions, tokens, time and cost against its limits.

Tasks are durable. A task is a row in `agent_runs`; a worker process claims it and keeps a heartbeat on it. If the API restarts mid-task, a graceful shutdown pauses the task and the next start resumes it; a crash is noticed within 30 seconds and the task resumes on the next worker. The agent continues from the conversation so far with a fresh screenshot, and the conversation notes the restart. A task interrupted three times fails with an error instead of looping.

Every action is stored with the screenshot the agent saw before it (encrypted, in object storage), so a task can be replayed step by step: click **Screen** next to an action in the Agent tab, or fetch `GET /sandboxes/{id}/agent/messages/{message_id}/screenshot`. Clearing the conversation deletes them, and so does deleting the sandbox.

| Endpoint | |
| --- | --- |
| `POST /sandboxes/{id}/agent` | `{"message": "...", "model": null, "stream": true}`. Streams server-sent events: `user`, `reasoning`, `action`, `text`, `status` and `error` (each with the message `id`; actions say whether they have a `screenshot`), a `usage` event after each model call (`steps`, `tokens`, `cost`, `elapsed` and the limits), then `done` with the task's `state`. With `"stream": false` it returns the `run_id` and all the events once the task is finished. |
| `GET /sandboxes/{id}/agent` | The conversation so far, whether a task is running, and the latest task (`run`) with its usage and limits |
| `GET /sandboxes/{id}/agent/messages/{message_id}/screenshot` | The screen an action was decided on |
| `GET/PUT/DELETE /agent/settings` | The workspace's provider, model, key (a vault secret: `api_key` saves a typed key, `api_key_secret_id` picks one) and limits (`max_steps`, `max_seconds`, `max_tokens`) |
| `GET /sandboxes/{id}/agent/stream` | Attach to the running task's stream (replays it from the start) |
| `POST /sandboxes/{id}/agent/stop` | Cancel the running task |
| `DELETE /sandboxes/{id}/agent` | Clear the conversation |
| `GET/POST/PATCH/DELETE /sandboxes/{id}/agent/channels` | Link Slack and Discord channels (with `allowed_users`) and WhatsApp numbers |

One task runs per sandbox at a time, and it keeps going if the client that started it disconnects. Follow-up messages see the earlier turns as text.

```bash
curl -N -X POST localhost:8000/sandboxes/$ID/agent -H "Authorization: Bearer $ZOO_API_KEY" \
  -H 'Content-Type: application/json' -d '{"message": "Open Firefox and find the weather in Paris"}'
```

```python
for event in Zoo().sandbox(sandbox_id).ask("Open Firefox and find the weather in Paris"):
    print(event["type"], event.get("text", ""))
```

#### Slack, Discord and WhatsApp

Link a channel or phone number to a sandbox under **Agent → Chat channels**. Messages from there start tasks and the agent's progress streams back: Slack and Discord edit one reply as the agent works, and WhatsApp, which can't edit messages, gets a message per step. Send `stop` to cancel and `reset` to clear the conversation.

Only allowed users can command a sandbox. A Slack or Discord link takes a list of user IDs (Slack `U0123ABCD`; in Discord, Developer Mode → right-click a user → Copy User ID), or `*` for anyone in the channel; anyone else gets a reply with their ID to pass to the owner. Links made before allowlists existed allow `*` until you edit them. A WhatsApp link is one phone number and only answers that number.

Webhook signatures are checked on every request (Slack's signing secret, with requests older than five minutes refused; WhatsApp's app secret). Each platform event is recorded the first time it arrives, so platform retries and duplicate deliveries never start a task twice, on any replica. Calls back to Slack and WhatsApp retry with backoff on rate limits, server errors and dropped connections, honouring `Retry-After`. The Discord bot runs in exactly one worker process (whichever holds its lease), so scaling the API out never double-replies.

| Platform | Environment | Setup |
| --- | --- | --- |
| Slack | `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` | Bot scopes `chat:write`, `channels:history`, `groups:history`; subscribe to `message.channels` and `message.groups` at `<api>/integrations/slack/events`; invite the bot to the channel. Link by channel ID. |
| Discord | `DISCORD_BOT_TOKEN` | Enable the Message Content intent; invite the bot with Send Messages and Read Message History. Link by channel ID. |
| WhatsApp | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` | Cloud API webhook at `<api>/integrations/whatsapp/webhook`, subscribed to `messages`. Link the sender's number. |

### Computer-use agent (client side)

A Claude computer-use loop that runs on your machine and drives a sandbox.

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
box.wait()
box.stop()
box.start()  # restart so the secret is injected
box.exec("git clone https://github.com/you/repo ~/work/repo", timeout=120)
result = box.claude("fix the failing test", cwd="~/work/repo", timeout=900)
print(result["result"])
```

`box.claude()` runs `claude -p ... --output-format json --dangerously-skip-permissions` as the `zoo` user and returns the parsed JSON. `examples/claude_code.py` is the full version, with a deny-by-default network that only allows Anthropic, GitHub, PyPI and npm.

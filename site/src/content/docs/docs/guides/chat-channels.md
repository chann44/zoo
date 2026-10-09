---
title: The built-in agent and chat channels
description: A computer-use agent on every sandbox, driven from the dashboard, the API — or Slack, Discord and WhatsApp.
---

Every desktop, browser, macOS and Windows sandbox has a
[CUA](https://github.com/trycua/cua) computer-use agent on the server. Chat with it from
the **Agent** tab on the sandbox page, over the REST API, or from Slack, Discord and
WhatsApp. Its actions go through the same tools, permissions and Activity log as API and
MCP calls — policies hold, and everything is audited.

## Model and limits

Pick the provider and model under **Agent → Model** (per workspace, `PUT /agent/settings`).
The provider key lives in the vault: type it in and it's saved as
`AGENT_<PROVIDER>_API_KEY`, or pick any vault secret. Without settings the agent uses
`ZOO_AGENT_MODEL` (default `anthropic/claude-sonnet-5-5`) with `ANTHROPIC_API_KEY` from
the API's environment.

Every task has limits, and the agent stops with an error when it reaches one:

| Limit | Server cap (environment) | Default |
| --- | --- | --- |
| Actions | `ZOO_AGENT_MAX_STEPS` | 100 |
| Wall-clock time | `ZOO_AGENT_MAX_SECONDS` | 1800 (30 minutes) |
| Model tokens | `ZOO_AGENT_MAX_TOKENS` | 2,000,000 |

A workspace can set lower limits in its agent settings, never higher ones. The Agent tab
shows the running task's actions, tokens, time and cost against its limits.

## Durable tasks

A task is a row in `agent_runs`; a worker process claims it and keeps a heartbeat on it.
If the API restarts mid-task, a graceful shutdown pauses it and the next start resumes it;
a crash is noticed within 30 seconds and the task resumes on the next worker — the agent
continues from the conversation so far with a fresh screenshot. A task interrupted three
times fails with an error instead of looping. One task runs per sandbox at a time, and it
keeps going if the client that started it disconnects.

Every action is stored with the screenshot the agent saw before it (encrypted, in
object storage): click **Screen** next to an action in the Agent tab, or fetch
`GET /sandboxes/{id}/agent/messages/{message_id}/screenshot`. Clearing the conversation
deletes them, and so does deleting the sandbox.

## From the API and SDK

```bash
curl -N -X POST localhost:8000/sandboxes/$ID/agent -H "Authorization: Bearer $ZOO_API_KEY" \
  -H 'Content-Type: application/json' -d '{"message": "Open Firefox and find the weather in Paris"}'
```

The stream sends server-sent events: `user`, `reasoning`, `action`, `text`, `status` and
`error`, a `usage` event after each model call (steps, tokens, cost, elapsed, limits), then
`done` with the task's state. With `"stream": false` it returns the `run_id` and all the
events once the task is finished.

```python
for event in Zoo().sandbox(sandbox_id).ask("Open Firefox and find the weather in Paris"):
    print(event["type"], event.get("text", ""))
```

`POST /sandboxes/{id}/agent/stop` cancels the running task;
`GET /sandboxes/{id}/agent/stream` attaches to a running task's stream, replaying it from
the start; `DELETE /sandboxes/{id}/agent` clears the conversation.

## Slack, Discord and WhatsApp

Link a channel or phone number to a sandbox under **Agent → Chat channels**. Messages from
there start tasks and the agent's progress streams back: Slack and Discord edit one reply
as the agent works; WhatsApp, which can't edit messages, gets a message per step. Send
`stop` to cancel and `reset` to clear the conversation.

Only allowed users can command a sandbox. A Slack or Discord link takes a list of user IDs
(Slack `U0123ABCD`; in Discord, Developer Mode → right-click a user → Copy User ID), or
`*` for anyone in the channel; anyone else gets a reply with their ID to pass to the
owner. A WhatsApp link is one phone number and only answers that number.

Webhook signatures are checked on every request (Slack's signing secret, with requests
older than five minutes refused; WhatsApp's app secret). Each platform event is recorded
the first time it arrives, so retries and duplicate deliveries never start a task twice,
on any replica. The Discord bot runs in exactly one worker process (whichever holds its
lease), so scaling the API out never double-replies.

| Platform | Environment | Setup |
| --- | --- | --- |
| Slack | `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` | Bot scopes `chat:write`, `channels:history`, `groups:history`; subscribe to `message.channels` and `message.groups` at `<api>/integrations/slack/events`; invite the bot to the channel. Link by channel ID. |
| Discord | `DISCORD_BOT_TOKEN` | Enable the Message Content intent; invite the bot with Send Messages and Read Message History. Link by channel ID. |
| WhatsApp | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` | Cloud API webhook at `<api>/integrations/whatsapp/webhook`, subscribed to `messages`. Link the sender's number. |

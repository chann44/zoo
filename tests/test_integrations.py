"""Contract tests for the chat platforms, with payloads recorded from Slack, WhatsApp and Discord."""

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from integrations import discord, relay, slack, whatsapp
from tests import fake_model
from tests.conftest import sql
from tests.fake_model import click, say

FIXTURES = Path(__file__).parent / "fixtures" / "chat"
SLACK_SECRET = "8f742231b10e8888abcd99yyyzzz85a5"
WHATSAPP_SECRET = "app-secret-123"


def recorded(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def platforms(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SLACK_SECRET)
    for name, value in {
        "WHATSAPP_TOKEN": "wa-token",
        "WHATSAPP_PHONE_NUMBER_ID": "106540352242922",
        "WHATSAPP_VERIFY_TOKEN": "verify-me",
        "WHATSAPP_APP_SECRET": WHATSAPP_SECRET,
    }.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def handled(monkeypatch):
    """Messages the webhooks hand to the relay, as the arguments relay.handle got."""
    calls: list[tuple] = []

    async def record(*args):
        calls.append(args)

    spawned: list = []
    monkeypatch.setattr(relay, "handle", record)
    monkeypatch.setattr(relay, "spawn", spawned.append)

    def run() -> list[tuple]:
        for coroutine in spawned:
            asyncio.run(coroutine)
        spawned.clear()
        return calls

    return run


def slack_post(
    client, body: bytes, timestamp: int | None = None, signature: str | None = None, headers: dict | None = None
):
    timestamp = int(time.time()) if timestamp is None else timestamp
    if signature is None:
        signature = slack.sign(SLACK_SECRET, str(timestamp), body)
    return client.post(
        slack.WEBHOOK_PATH,
        content=body,
        headers={"X-Slack-Request-Timestamp": str(timestamp), "X-Slack-Signature": signature, **(headers or {})},
    )


def whatsapp_post(client, body: bytes, signature: str | None = None):
    if signature is None:
        signature = whatsapp.sign(WHATSAPP_SECRET, body)
    return client.post(whatsapp.WEBHOOK_PATH, content=body, headers={"X-Hub-Signature-256": signature})


# Slack


def test_slack_url_verification(client, platforms):
    res = slack_post(client, recorded("slack_url_verification.json"))
    assert res.status_code == 200
    assert res.json() == {"challenge": json.loads(recorded("slack_url_verification.json"))["challenge"]}


def test_slack_rejects_bad_signatures_and_replays(client, platforms, handled):
    body = recorded("slack_message.json")
    assert slack_post(client, body, signature="v0=" + "0" * 64).status_code == 401
    # a signature over a different body
    assert slack_post(client, body, signature=slack.sign(SLACK_SECRET, str(int(time.time())), b"{}")).status_code == 401
    # signed with another app's secret
    now = int(time.time())
    assert slack_post(client, body, now, slack.sign("other-secret", str(now), body)).status_code == 401
    # a captured request replayed later
    old = int(time.time()) - slack.MAX_AGE - 10
    assert slack_post(client, body, old).status_code == 401
    assert slack_post(client, body, signature="").status_code == 401
    assert handled() == []


def test_slack_is_unavailable_until_configured(client, monkeypatch):
    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
    assert client.post(slack.WEBHOOK_PATH, content=b"{}").status_code == 503


def test_slack_message_reaches_the_relay_once(client, platforms, handled):
    assert slack_post(client, recorded("slack_message.json")).status_code == 200
    # Slack retries when it doesn't get its 200 in time, and sends app_mention for the same message
    assert slack_post(client, recorded("slack_message.json"), headers={"X-Slack-Retry-Num": "1"}).status_code == 200
    assert slack_post(client, recorded("slack_app_mention.json")).status_code == 200
    calls = handled()
    assert len(calls) == 1
    _, platform, channel, author, text, _send, edit, limit = calls[0]
    assert (platform, channel, author, text, limit) == (
        "slack",
        "C0SANDBOX1",
        "U0ALICE01",
        "open firefox and search for zoo",
        slack.LIMIT,
    )
    assert edit is not None


def test_slack_thread_replies_go_to_the_thread(client, platforms, handled):
    slack_post(client, recorded("slack_thread_reply.json"))
    [call] = handled()
    assert call[3] == "U0BOB0002" and call[4] == "stop"


@pytest.mark.parametrize("name", ["slack_bot_message.json", "slack_message_changed.json"])
def test_slack_ignores_bots_and_edits(client, platforms, handled, name):
    assert slack_post(client, recorded(name)).status_code == 200
    assert handled() == []


def test_slack_parse_of_recorded_payloads():
    message = slack.incoming(json.loads(recorded("slack_message.json")))
    assert message == slack.Incoming(
        "C0SANDBOX1:1728388800.000100",
        "C0SANDBOX1",
        "1728388800.000100",
        "U0ALICE01",
        "open firefox and search for zoo",
    )
    reply = slack.incoming(json.loads(recorded("slack_thread_reply.json")))
    assert reply is not None and reply.thread == "1728388800.000100"
    assert slack.incoming(json.loads(recorded("slack_url_verification.json"))) is None


# WhatsApp


def test_whatsapp_subscription(client, platforms):
    params = {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "1158201444"}
    res = client.get(whatsapp.WEBHOOK_PATH, params=params)
    assert res.status_code == 200 and res.text == "1158201444"
    assert client.get(whatsapp.WEBHOOK_PATH, params={**params, "hub.verify_token": "wrong"}).status_code == 403


def test_whatsapp_rejects_bad_signatures(client, platforms, handled):
    body = recorded("whatsapp_text.json")
    assert whatsapp_post(client, body, signature="sha256=" + "0" * 64).status_code == 401
    assert whatsapp_post(client, body, signature=whatsapp.sign("other", body)).status_code == 401
    assert whatsapp_post(client, body, signature="").status_code == 401
    assert handled() == []


def test_whatsapp_text_reaches_the_relay_once(client, platforms, handled):
    assert whatsapp_post(client, recorded("whatsapp_text.json")).status_code == 200
    assert whatsapp_post(client, recorded("whatsapp_text.json")).status_code == 200
    [call] = handled()
    _, platform, external_id, author, text, _send, edit, limit = call
    assert (platform, external_id, author, text, edit, limit) == (
        "whatsapp",
        "15551234567",
        "15551234567",
        "open firefox",
        None,
        whatsapp.LIMIT,
    )


@pytest.mark.parametrize("name", ["whatsapp_image.json", "whatsapp_status.json"])
def test_whatsapp_ignores_media_and_statuses(client, platforms, handled, name):
    assert whatsapp_post(client, recorded(name)).status_code == 200
    assert handled() == []


# Discord


def discord_message(data: dict, bot_id: int):
    author = SimpleNamespace(id=int(data["author"]["id"]), bot=data["author"]["bot"])
    replies: list[str] = []

    async def reply(content, mention_author=False):
        replies.append(content)
        return SimpleNamespace(edit=None)

    return SimpleNamespace(
        id=int(data["id"]),
        content=data["content"],
        author=author,
        channel=SimpleNamespace(id=int(data["channel_id"])),
        reply=reply,
    )


def test_discord_message_reaches_the_relay_once(handled):
    data = json.loads(recorded("discord_message.json"))
    client = discord.build(agent=None)
    bot_id = int(data["bot_user_id"])
    client._connection.user = SimpleNamespace(id=bot_id, mention=f"<@{bot_id}>")  # type: ignore[assignment]
    message = discord_message(data, bot_id)
    asyncio.run(client.on_message(message))  # type: ignore[attr-defined]
    asyncio.run(client.on_message(message))  # type: ignore[attr-defined]
    [call] = handled()
    _, platform, channel, author, text, *_ = call
    assert (platform, channel, author, text) == ("discord", data["channel_id"], data["author"]["id"], "open firefox")


def test_discord_ignores_bots(handled):
    data = json.loads(recorded("discord_message.json"))
    data["author"]["bot"] = True
    client = discord.build(agent=None)
    asyncio.run(client.on_message(discord_message(data, 1)))  # type: ignore[attr-defined]
    assert handled() == []


def test_the_discord_bot_runs_only_where_the_lease_is_held(monkeypatch):
    from server import workers

    started: list[str] = []

    async def fake_run(agent):
        started.append(workers.WORKER_ID)
        await asyncio.Event().wait()

    monkeypatch.setattr(discord, "run", fake_run)
    monkeypatch.setattr(discord, "RENEW_SECONDS", 0.01)

    async def scenario():
        mine = asyncio.create_task(discord.supervise(None))
        await asyncio.sleep(0.05)
        # another worker can't take the lease while this one renews it
        monkeypatch.setattr(workers, "WORKER_ID", "other-worker")
        assert workers.hold(discord.LEASE, discord.LEASE_SECONDS) is False
        monkeypatch.undo()
        mine.cancel()
        await asyncio.gather(mine, return_exceptions=True)

    asyncio.run(scenario())
    assert len(started) == 1
    # released on shutdown, so the next worker takes over at once
    monkeypatch.setattr(workers, "WORKER_ID", "next-worker")
    assert workers.hold(discord.LEASE, discord.LEASE_SECONDS) is True


# Relay: allowlist, commands and a full run


class Chat:
    def __init__(self):
        self.sent: list[str] = []
        self.edits: dict[int, str] = {}

    async def send(self, text: str) -> int:
        self.sent.append(text)
        return len(self.sent) - 1

    async def edit(self, ref: int, text: str):
        self.edits[ref] = text


def link(client, headers, sandbox_id, platform="slack", external_id="C0SANDBOX1", allowed=("U0ALICE01",)):
    res = client.post(
        f"/sandboxes/{sandbox_id}/agent/channels",
        json={"platform": platform, "external_id": external_id, "allowed_users": list(allowed)},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def relay_message(zoo, author, text, platform="slack", external_id="C0SANDBOX1"):
    chat = Chat()
    edit = chat.edit if platform != "whatsapp" else None
    asyncio.run(relay.handle(zoo.agent_api, platform, external_id, author, text, chat.send, edit, 4000))
    return chat


def test_only_allowed_users_can_command_a_sandbox(client, alice, sandbox, zoo):
    link(client, alice, sandbox["id"])
    chat = relay_message(zoo, "U0MALLORY", "delete everything")
    assert chat.sent == ["You aren't allowed to command this sandbox. Ask its owner to add your user ID (U0MALLORY)."]
    chat = relay_message(zoo, "U0ALICE01", "help")
    assert chat.sent == [relay.HELP]


def test_a_star_lets_anyone_in_the_channel(client, alice, sandbox, zoo):
    link(client, alice, sandbox["id"], allowed=["*"])
    assert relay_message(zoo, "U0ANYONE", "help").sent == [relay.HELP]


def test_unlinked_channels_are_ignored(client, alice, sandbox, zoo):
    assert relay_message(zoo, "U0ALICE01", "help", external_id="C0OTHER").sent == []


def test_a_whatsapp_link_is_its_own_allowlist(client, alice, sandbox, zoo):
    link(client, alice, sandbox["id"], platform="whatsapp", external_id="+1 555 123 4567", allowed=[])
    assert relay_message(zoo, "15551234567", "help", "whatsapp", "15551234567").sent == [relay.HELP]


def test_a_full_run_from_slack(client, alice, sandbox, zoo, monkeypatch):
    link(client, alice, sandbox["id"])
    monkeypatch.setattr("server.agent_api.MODEL", fake_model.MODEL)
    fake_model.reset([click(4, 4)], [say("All done.")])
    chat = relay_message(zoo, "U0ALICE01", "open firefox")
    assert chat.sent == ["Working…"]
    assert chat.edits[0] == "› click 4, 4\nAll done."
    assert relay_message(zoo, "U0ALICE01", "stop").sent == ["Nothing is running."]
    assert relay_message(zoo, "U0ALICE01", "reset").sent == ["Conversation cleared."]
    fake_model.reset()


def test_a_full_run_from_whatsapp_sends_a_message_per_step(client, alice, sandbox, zoo, monkeypatch):
    link(client, alice, sandbox["id"], platform="whatsapp", external_id="15551234567", allowed=[])
    monkeypatch.setattr("server.agent_api.MODEL", fake_model.MODEL)
    fake_model.reset([click(4, 4)], [say("All done.")])
    chat = relay_message(zoo, "15551234567", "open firefox", "whatsapp", "15551234567")
    assert chat.sent == ["› click 4, 4\nAll done."]
    fake_model.reset()


# Channel links


def test_slack_and_discord_links_need_an_allowlist(client, alice, sandbox):
    sid = sandbox["id"]
    res = client.post(
        f"/sandboxes/{sid}/agent/channels", json={"platform": "slack", "external_id": "c0abc"}, headers=alice
    )
    assert res.status_code == 422
    channel = link(client, alice, sid, external_id="c0abc", allowed=["<@u0alice01>", "U0BOB0002", "U0BOB0002"])
    assert channel["external_id"] == "C0ABC" and channel["allowed_users"] == ["U0ALICE01", "U0BOB0002"]
    res = client.post(
        f"/sandboxes/{sid}/agent/channels",
        json={"platform": "discord", "external_id": "123", "allowed_users": ["alice"]},
        headers=alice,
    )
    assert res.status_code == 422
    discord_link = link(client, alice, sid, platform="discord", external_id="123", allowed=["<@!813847561029384222>"])
    assert discord_link["allowed_users"] == ["813847561029384222"]


def test_update_an_allowlist(client, alice, bob, sandbox):
    sid = sandbox["id"]
    channel = link(client, alice, sid)
    url = f"/sandboxes/{sid}/agent/channels/{channel['id']}"
    res = client.patch(url, json={"allowed_users": ["*"]}, headers=alice)
    assert res.status_code == 200 and res.json()["allowed_users"] == ["*"]
    assert client.patch(url, json={"allowed_users": []}, headers=alice).status_code == 422
    assert client.patch(url, json={"allowed_users": [" "]}, headers=alice).status_code == 422
    assert client.patch(url, json={"allowed_users": ["*"]}, headers=bob).status_code == 404
    wa = link(client, alice, sid, platform="whatsapp", external_id="15551234567", allowed=[])
    assert wa["allowed_users"] == []
    res = client.patch(f"/sandboxes/{sid}/agent/channels/{wa['id']}", json={"allowed_users": ["*"]}, headers=alice)
    assert res.status_code == 400


# Retries


@pytest.fixture
def no_wait(monkeypatch):
    monkeypatch.setattr(relay, "MAX_DELAY", 0)
    monkeypatch.setattr(relay.random, "uniform", lambda a, b: 0)


def respond(monkeypatch, *responses: httpx.Response):
    """Serves platform API calls from `responses` in order and returns the requests made."""
    requests: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return queue.pop(0)

    monkeypatch.setattr(relay, "transport", httpx.MockTransport(handler))
    return requests


def test_slack_calls_retry_rate_limits_and_server_errors(platforms, monkeypatch, no_wait):
    requests = respond(
        monkeypatch,
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(503),
        httpx.Response(200, json={"ok": False, "error": "ratelimited"}),
        httpx.Response(200, json={"ok": True, "ts": "1.2"}),
    )
    assert asyncio.run(slack.call("chat.postMessage", {"channel": "C1", "text": "hi"}))["ts"] == "1.2"
    assert len(requests) == 4
    assert requests[0].headers["Authorization"] == "Bearer xoxb-test"


def test_slack_calls_give_up_after_the_last_attempt(platforms, monkeypatch, no_wait):
    requests = respond(monkeypatch, *[httpx.Response(500) for _ in range(relay.ATTEMPTS)])
    with pytest.raises(relay.Retryable):
        asyncio.run(slack.call("chat.update", {}))
    assert len(requests) == relay.ATTEMPTS


def test_slack_errors_that_wont_change_are_not_retried(platforms, monkeypatch, no_wait):
    requests = respond(monkeypatch, httpx.Response(200, json={"ok": False, "error": "channel_not_found"}))
    with pytest.raises(RuntimeError, match="channel_not_found"):
        asyncio.run(slack.call("chat.postMessage", {}))
    assert len(requests) == 1


def test_whatsapp_sends_retry(platforms, monkeypatch, no_wait):
    requests = respond(monkeypatch, httpx.Response(502), httpx.Response(200, json={"messages": [{"id": "x"}]}))
    asyncio.run(whatsapp.send_text("15551234567", "hello"))
    assert len(requests) == 2
    assert json.loads(requests[-1].content)["text"] == {"body": "hello"}
    respond(monkeypatch, httpx.Response(400, json={"error": {"message": "bad number"}}))
    with pytest.raises(RuntimeError, match="bad number"):
        asyncio.run(whatsapp.send_text("1", "x"))


def test_network_errors_are_retried(platforms, monkeypatch, no_wait):
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) < 3:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(relay, "transport", httpx.MockTransport(handler))
    assert asyncio.run(slack.call("chat.update", {}))["ok"] is True
    assert len(attempts) == 3


def test_old_events_are_purged(client):
    assert relay.first_time("slack", "C1:1") is True
    assert relay.first_time("slack", "C1:1") is False
    assert relay.first_time("discord", "C1:1") is True
    sql("UPDATE chat_events SET created_at = now() - interval '2 days'")
    relay.purge_events()
    assert relay.first_time("slack", "C1:1") is True

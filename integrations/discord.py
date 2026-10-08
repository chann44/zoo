"""Discord bot: messages in a linked channel drive that sandbox's agent. The bot replies once and edits that
message as the agent works.

Setup: create a bot in the Discord developer portal, enable the Message Content intent, invite it to your
server with Send Messages and Read Message History, and set DISCORD_BOT_TOKEN. Link a channel by its ID
(Developer Mode → right-click the channel → Copy Channel ID), and allow the Discord user IDs that may command the
sandbox (right-click a user → Copy User ID), or "*" for everyone in the channel.

The bot runs in a worker process (server/workers.py), and only in the one holding the `discord` lease, so API
replicas and extra workers never connect a second bot and reply twice. discord.py retries rate-limited and failed
API calls itself.
"""

import asyncio
import os

import discord

from integrations import relay
from logger.logger import logger
from server import workers

LIMIT = 2000
LEASE = "discord"
LEASE_SECONDS = 45
RENEW_SECONDS = 15


def configured() -> bool:
    return bool(os.environ.get("DISCORD_BOT_TOKEN"))


def build(agent) -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        logger.info("discord bot connected", extra={"user": str(client.user)})

    @client.event
    async def on_message(message: discord.Message):
        if message.author.bot or not message.content:
            return
        text = message.content
        if client.user is not None:
            text = text.replace(client.user.mention, "").replace(f"<@!{client.user.id}>", "").strip()
        # a gateway resume can deliver a message again
        if not text or not relay.first_time("discord", str(message.id)):
            return

        async def send(content: str) -> discord.Message:
            return await message.reply(content, mention_author=False)

        async def edit(reply: discord.Message, content: str):
            await reply.edit(content=content)

        relay.spawn(
            relay.handle(agent, "discord", str(message.channel.id), str(message.author.id), text, send, edit, LIMIT)
        )

    return client


async def run(agent):
    """Runs the bot until cancelled."""
    client = build(agent)
    try:
        await client.start(os.environ["DISCORD_BOT_TOKEN"])
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error("discord bot stopped", extra={"error": repr(e)})
    finally:
        if not client.is_closed():
            await client.close()


async def supervise(agent):
    """Keeps the bot running in exactly one worker: this one while it holds the lease. Started from the API's
    lifespan in worker processes when DISCORD_BOT_TOKEN is set."""
    bot: asyncio.Task | None = None
    try:
        while True:
            try:
                held = await asyncio.to_thread(workers.hold, LEASE, LEASE_SECONDS)
            except Exception as e:
                logger.error("discord lease check failed", extra={"error": repr(e)})
                held = False
            if held and (bot is None or bot.done()):
                logger.info("discord bot starting", extra={"worker": workers.WORKER_ID})
                bot = asyncio.create_task(run(agent))
            elif not held and bot is not None:
                bot.cancel()
                await asyncio.gather(bot, return_exceptions=True)
                bot = None
            await asyncio.sleep(RENEW_SECONDS)
    finally:
        if bot is not None:
            bot.cancel()
            await asyncio.gather(bot, return_exceptions=True)
        await asyncio.to_thread(workers.release, LEASE)

"""Discord bot: messages in a linked channel drive that sandbox's agent. The bot replies once and edits that
message as the agent works.

Setup: create a bot in the Discord developer portal, enable the Message Content intent, invite it to your
server with Send Messages and Read Message History, and set DISCORD_BOT_TOKEN. Link a channel by its ID
(Developer Mode → right-click the channel → Copy Channel ID)."""

import asyncio
import os

import discord

from integrations import relay
from logger.logger import logger

LIMIT = 2000


def configured() -> bool:
    return bool(os.environ.get("DISCORD_BOT_TOKEN"))


def build(agent) -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    tasks: set[asyncio.Task] = set()

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
        if not text:
            return

        async def send(content: str) -> discord.Message:
            return await message.reply(content, mention_author=False)

        async def edit(reply: discord.Message, content: str):
            await reply.edit(content=content)

        task = asyncio.create_task(relay.handle(agent, "discord", str(message.channel.id), text, send, edit, LIMIT))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    return client


async def run(agent):
    """Runs the bot until cancelled. Started from the API's lifespan when DISCORD_BOT_TOKEN is set."""
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

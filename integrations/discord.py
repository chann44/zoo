import os
import asyncio
import sys
import discord
from discord.ext import commands


DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "YOUR_DISCORD_BOT_TOKEN")
TARGET_CHANNEL_ID = 123456789012345678  

intents = discord.Intents.default()
intents.message_content = True  

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Bot logged in as: {bot.user}")
    print(f"Monitoring Channel ID: {TARGET_CHANNEL_ID}")
    print("-" * 50)
    print("Option A: To reply inside Discord, type: !reply [your message]")
    print("Option B: To send a message from this terminal, just type text and press Enter.")
    print("-" * 50)
    
    asyncio.create_task(terminal_agent_input_loop())


@bot.event
async def on_message(message):
    """
    AGENT READS MESSAGES: Intercepts and shows messages instantly in the console.
    """
    if message.author == bot.user:
        return

    if message.channel.id == TARGET_CHANNEL_ID:
        print(f"\n[LIVE MESSAGE] @{message.author.name}: {message.content}")

    await bot.process_commands(message)



@bot.command(name="reply")
async def agent_reply_command(ctx, *, reply_content: str):
    """
    AGENT REPLIES VIA DISCORD: Triggered by typing "!reply [text]" inside Discord chat.
    """
    print(f"\n[AGENT REPLY IN CHAT] Handled by @{ctx.author.name}: {reply_content}")

    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass

    embed = discord.Embed(
        title="Agent Official Reply",
        description=reply_content,
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Handled by Agent: {ctx.author.name}")
    await ctx.send(embed=embed)



async def terminal_agent_input_loop():
    """
    AGENT SENDS/REPLIES VIA TERMINAL: Reads standard input line-by-line 
    without blocking Discord's core network cycle.
    """
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            break
            
        agent_text = line.decode().strip()
        
        if agent_text:
            channel = bot.get_channel(TARGET_CHANNEL_ID)
            if channel:
                await channel.send(f"Agent Update (via Console):** {agent_text}")
                print(f"[SENT FROM CONSOLE] -> {agent_text}")
            else:
                print("Error: Target channel could not be resolved. Verify your TARGET_CHANNEL_ID.")



if __name__ == "__main__":
    if DISCORD_BOT_TOKEN == "YOUR_DISCORD_BOT_TOKEN":
        print("Error: Please update the DISCORD_BOT_TOKEN variable before running.")
        sys.exit(1)
        
    bot.run(DISCORD_BOT_TOKEN)

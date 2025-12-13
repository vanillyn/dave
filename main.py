import discord
from discord.ext import commands
import os
from pathlib import Path
from dotenv import load_dotenv

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready() -> None:
    print(f"logged in as {bot.user}")
    await bot.tree.sync()
    print("slash commands synced")


async def load_cogs() -> None:
    cogs_dir = Path("cogs")
    if not cogs_dir.exists():
        cogs_dir.mkdir()
        return

    for file in cogs_dir.glob("*.py"):
        if file.stem != "__init__":
            try:
                await bot.load_extension(f"cogs.{file.stem}")
                print(f"loaded cog: {file.stem}")
            except Exception as e:
                print(f"failed to load {file.stem}: {e}")


async def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN environment variable is not set")
    async with bot:
        await load_cogs()
        await bot.start(token)
        await bot.start(token)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

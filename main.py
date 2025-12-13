import discord
from discord.ext import commands
import os
from pathlib import Path

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
    async with bot:
        await load_cogs()
        await bot.start(os.getenv("DISCORD_TOKEN", ""))


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

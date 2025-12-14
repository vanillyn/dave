import discord
from discord.ext import commands, tasks
import random
import json
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict


class MarkovCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.data_file = Path("data/markov.json")
        self.data_file.parent.mkdir(exist_ok=True)

        self.chains: Dict[int, Dict[str, List[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self.load_data()

        self.random_message.start()

    def load_data(self) -> None:
        if self.data_file.exists():
            try:
                with open(self.data_file, "r") as f:
                    data = json.load(f)
                    for guild_id, chain in data.items():
                        self.chains[int(guild_id)] = defaultdict(list, chain)
            except Exception as e:
                print(f"failed to load markov data: {e}")

    def save_data(self) -> None:
        try:
            with open(self.data_file, "w") as f:
                json.dump({str(k): dict(v) for k, v in self.chains.items()}, f)
        except Exception as e:
            print(f"failed to save markov data: {e}")

    def is_allowed_channel(self, channel_id: int, guild_id: int) -> bool:
        config_cog = self.bot.get_cog("Config")
        if not config_cog:
            return True

        allowed_channels = config_cog.get_markov_channels(guild_id)
        if not allowed_channels:
            return True

        return channel_id in allowed_channels

    def add_message(self, guild_id: int, text: str) -> None:
        if len(text) < 10 or text.startswith(("!", "/", "http")):
            return

        words = text.split()
        if len(words) < 3:
            return

        chain = self.chains[guild_id]

        chain["__START__"].append(words[0])

        for i in range(len(words) - 1):
            chain[words[i]].append(words[i + 1])

        chain[words[-1]].append("__END__")

    def generate_message(self, guild_id: int) -> Optional[str]:
        chain = self.chains.get(guild_id)
        if not chain or "__START__" not in chain:
            return None

        words = []
        current = random.choice(chain["__START__"])

        for _ in range(50):
            words.append(current)

            if current not in chain or not chain[current]:
                break

            next_word = random.choice(chain[current])
            if next_word == "__END__":
                break

            current = next_word

        if len(words) < 3:
            return None

        return " ".join(words)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        if not self.is_allowed_channel(message.channel.id, message.guild.id):
            return

        if self.bot.user in message.mentions:
            content = message.content
            for mention in message.mentions:
                content = content.replace(f"<@{mention.id}>", "")
                content = content.replace(f"<@!{mention.id}>", "")

            if not content.strip():
                response = self.generate_message(message.guild.id)
                if response:
                    try:
                        await message.channel.send(response)
                    except Exception:
                        pass
                return

        self.add_message(message.guild.id, message.content)

        if random.random() < 0.05:
            self.save_data()

    @tasks.loop(minutes=random.randint(15, 45))
    async def random_message(self) -> None:
        await self.bot.wait_until_ready()

        for guild in self.bot.guilds:
            if random.random() > 0.2:
                continue

            config_cog = self.bot.get_cog("Config")
            allowed_channels = []

            if config_cog:
                allowed_channel_ids = config_cog.get_markov_channels(guild.id)
                if allowed_channel_ids:
                    allowed_channels = [
                        c
                        for c in guild.text_channels
                        if c.id in allowed_channel_ids
                        and c.permissions_for(guild.me).send_messages
                    ]

            if not allowed_channels:
                allowed_channels = [
                    c
                    for c in guild.text_channels
                    if c.permissions_for(guild.me).send_messages
                ]

            if not allowed_channels:
                continue

            channel = random.choice(allowed_channels[:5])

            message = self.generate_message(guild.id)
            if message:
                try:
                    await channel.send(message)
                except Exception:
                    pass

    @random_message.before_loop
    async def before_random_message(self) -> None:
        await self.bot.wait_until_ready()

    def cog_unload(self) -> None:
        self.random_message.cancel()
        self.save_data()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarkovCog(bot))

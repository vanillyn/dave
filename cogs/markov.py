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

        self.add_message(message.guild.id, message.content)

        if random.random() < 0.05:
            self.save_data()

    @tasks.loop(minutes=random.randint(15, 45))
    async def random_message(self) -> None:
        await self.bot.wait_until_ready()

        for guild in self.bot.guilds:
            if random.random() > 0.2:
                continue

            channels = [
                c
                for c in guild.text_channels
                if c.permissions_for(guild.me).send_messages
            ]
            if not channels:
                continue

            channel = random.choice(channels[:5])

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

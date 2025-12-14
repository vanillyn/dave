import discord
from discord import app_commands
from discord.ext import commands
import json
import os


class Config(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = "data/config.json"
        os.makedirs("data", exist_ok=True)
        self.config = self.load_config()

    def load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, "r") as f:
                return json.load(f)
        return {}

    def save_config(self):
        with open(self.config_file, "w") as f:
            json.dump(self.config, f, indent=4)

    def get_guild_config(self, guild_id):
        guild_id = str(guild_id)
        if guild_id not in self.config:
            self.config[guild_id] = {}
        return self.config[guild_id]

    def get_markov_channels(self, guild_id):
        guild_config = self.get_guild_config(guild_id)
        return guild_config.get("markov_channels", [])

    @app_commands.command(name="config", description="configure bot settings")
    @app_commands.describe(
        key="the setting to configure", channels="channels to use (for markov channels)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_command(
        self, interaction: discord.Interaction, key: str, channels: str = None
    ):
        guild_config = self.get_guild_config(interaction.guild_id)

        key_lower = key.lower().replace(" ", "_")

        if key_lower == "markov_channels":
            if not channels:
                await interaction.response.send_message(
                    "you need to specify channels", ephemeral=True
                )
                return

            channel_ids = []
            for mention in channels.split():
                mention = mention.strip("<>#")
                if mention.isdigit():
                    channel_ids.append(int(mention))

            if not channel_ids:
                await interaction.response.send_message(
                    "couldn't find any valid channels", ephemeral=True
                )
                return

            guild_config["markov_channels"] = channel_ids
            self.save_config()

            channel_mentions = [f"<#{cid}>" for cid in channel_ids]
            await interaction.response.send_message(
                f"okay, markov will now only use these channels:\n{', '.join(channel_mentions)}"
            )
        else:
            await interaction.response.send_message(
                f"don't know what '{key}' is", ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(Config(bot))

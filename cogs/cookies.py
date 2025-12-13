import discord
from discord import app_commands
from discord.ext import commands
import json
import re
from pathlib import Path
from typing import Dict, Optional


class CookiesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.data_file = Path("data/cookies.json")
        self.data_file.parent.mkdir(exist_ok=True)

        self.cookies: Dict[int, Dict[int, int]] = {}
        self.load_data()

        self.thank_patterns = [
            r"\bthank",
            r"\bthanks",
            r"\bthx",
            r"\bty\b",
            r"\btyvm",
            r"\btysm",
            r"\bthank you",
            r"\bthanku",
            r"\bthnks",
            r"\bgracias",
            r"\bmerci",
            r"\bdanke",
            r"\barigato",
            r"\bthankies",
            r"\bthxie",
            r"\btanks",
        ]
        self.pattern = re.compile("|".join(self.thank_patterns), re.IGNORECASE)

    def load_data(self) -> None:
        if self.data_file.exists():
            try:
                with open(self.data_file, "r") as f:
                    data = json.load(f)
                    self.cookies = {
                        int(k): {int(u): c for u, c in v.items()}
                        for k, v in data.items()
                    }
            except Exception as e:
                print(f"failed to load cookie data: {e}")

    def save_data(self) -> None:
        try:
            with open(self.data_file, "w") as f:
                json.dump(
                    {
                        str(k): {str(u): c for u, c in v.items()}
                        for k, v in self.cookies.items()
                    },
                    f,
                )
        except Exception as e:
            print(f"failed to save cookie data: {e}")

    def get_cookies(self, guild_id: int, user_id: int) -> int:
        return self.cookies.get(guild_id, {}).get(user_id, 0)

    def add_cookie(self, guild_id: int, user_id: int) -> None:
        if guild_id not in self.cookies:
            self.cookies[guild_id] = {}

        self.cookies[guild_id][user_id] = self.cookies[guild_id].get(user_id, 0) + 1
        self.save_data()

    def remove_cookie(self, guild_id: int, user_id: int) -> bool:
        if guild_id not in self.cookies or user_id not in self.cookies[guild_id]:
            return False

        if self.cookies[guild_id][user_id] <= 0:
            return False

        self.cookies[guild_id][user_id] -= 1
        self.save_data()
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        if not self.pattern.search(message.content):
            return

        recipients = []

        for user in message.mentions:
            if user != message.author and not user.bot:
                recipients.append(user)

        if message.reference and message.reference.resolved:
            ref = message.reference.resolved
            if isinstance(ref, discord.Message):
                if ref.author != message.author and not ref.author.bot:
                    recipients.append(ref.author)

        words = message.content.lower().split()
        for member in message.guild.members:
            if member == message.author or member.bot:
                continue

            name_lower = member.name.lower()
            display_lower = member.display_name.lower()

            if name_lower in words or display_lower in words:
                recipients.append(member)

        for user in set(recipients):
            self.add_cookie(message.guild.id, user.id)

    @app_commands.command(
        name="cookies", description="check how many cookies you or someone else has"
    )
    async def check_cookies(
        self, interaction: discord.Interaction, user: Optional[discord.Member] = None
    ) -> None:
        target = user or interaction.user
        count = self.get_cookies(interaction.guild_id, target.id)

        if target == interaction.user:
            await interaction.response.send_message(
                f"you have **{count}** cookie{'s' if count != 1 else ''}"
            )
        else:
            await interaction.response.send_message(
                f"{target.mention} has **{count}** cookie{'s' if count != 1 else ''}"
            )

    @app_commands.command(name="eat", description="eat one of your cookies")
    async def eat_cookie(self, interaction: discord.Interaction) -> None:
        if not self.remove_cookie(interaction.guild_id, interaction.user.id):
            await interaction.response.send_message(
                "you don't have any cookies to eat...", ephemeral=True
            )
            return

        remaining = self.get_cookies(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(
            f"\*munch nom om onomosngon\*\n you have **{remaining}** cookie{'s' if remaining != 1 else ''} left"
        )

    @app_commands.command(name="give", description="give a cookie to someone")
    async def give_cookie(
        self, interaction: discord.Interaction, recipient: discord.Member
    ) -> None:
        if recipient == interaction.user:
            await interaction.response.send_message(
                "you can't give yourself a cookie...", ephemeral=True
            )
            return

        if recipient.bot:
            await interaction.response.send_message(
                "bots don't need cookies...", ephemeral=True
            )
            return

        if not self.remove_cookie(interaction.guild_id, interaction.user.id):
            await interaction.response.send_message(
                "you don't have any cookies to give...", ephemeral=True
            )
            return

        self.add_cookie(interaction.guild_id, recipient.id)

        giver_remaining = self.get_cookies(interaction.guild_id, interaction.user.id)
        recipient_total = self.get_cookies(interaction.guild_id, recipient.id)

        await interaction.response.send_message(
            f"gave a cookie to {recipient.mention}\n"
            f"you have **{giver_remaining}** left, they now have **{recipient_total}**"
        )

    @app_commands.command(
        name="leaderboard", description="see who has the most cookies"
    )
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        guild_cookies = self.cookies.get(interaction.guild_id, {})

        if not guild_cookies:
            await interaction.response.send_message("no one has any cookies yet...")
            return

        sorted_users = sorted(guild_cookies.items(), key=lambda x: x[1], reverse=True)[
            :10
        ]

        lines = []
        for i, (user_id, count) in enumerate(sorted_users, 1):
            member = interaction.guild.get_member(user_id)
            name = member.mention if member else f"<@{user_id}>"
            lines.append(f"{i}. {name} — **{count}** cookie{'s' if count != 1 else ''}")

        embed = discord.Embed(
            title="cookie leaderboard",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CookiesCog(bot))

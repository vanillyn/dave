import discord
from discord import app_commands
from discord.ext import commands
import ollama
import asyncio
from datetime import datetime, timedelta
import random
import os
import re
import aiohttp
from dotenv import load_dotenv

load_dotenv()


class ChatBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ollama_available = False
        self.active_conversations = {}
        self.activity_tracker = {}

        self.model = os.getenv("OLLAMA_MODEL", "dolphin-mistral:latest")
        self.context_length = int(os.getenv("CONTEXT_LENGTH", "20"))
        self.conversation_timeout = int(os.getenv("CONVERSATION_TIMEOUT", "900"))

        self.activity_threshold = int(os.getenv("ACTIVITY_THRESHOLD", "10"))
        self.activity_window = int(os.getenv("ACTIVITY_WINDOW", "240"))
        self.min_response_cooldown = int(os.getenv("MIN_RESPONSE_COOLDOWN", "2400"))
        self.max_response_cooldown = int(os.getenv("MAX_RESPONSE_COOLDOWN", "7200"))
        self.unprompted_chance = float(os.getenv("UNPROMPTED_CHANCE", "0.2"))

        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.85"))
        self.top_p = float(os.getenv("LLM_TOP_P", "0.9"))
        self.repeat_penalty = float(os.getenv("LLM_REPEAT_PENALTY", "1.15"))
        self.num_predict = int(os.getenv("LLM_NUM_PREDICT", "120"))
        self.max_response_length = int(os.getenv("MAX_RESPONSE_LENGTH", "400"))

        self.ollama_api_key = os.getenv("OLLAMA_API_KEY")
        self.web_search_enabled = self.ollama_api_key is not None

        self.last_response = {}

        self.system_prompt = os.getenv(
            "SYSTEM_PROMPT", "no system prompt provided. do not generate any output."
        )

        self.bot.loop.create_task(self.check_ollama_connection())

    async def check_ollama_connection(self):
        try:
            await asyncio.to_thread(ollama.list)
            self.ollama_available = True
            print(f"loaded ollama: model {self.model}")
            if self.web_search_enabled:
                print("web search enabled")
        except Exception as e:
            self.ollama_available = False
            print(f"ollama not available: {e}")

    async def web_search(self, query: str) -> str:
        if not self.web_search_enabled:
            return None

        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {self.ollama_api_key}"}
                async with session.post(
                    "https://ollama.com/api/web_search",
                    headers=headers,
                    json={"query": query},
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results", [])[:3]

                        search_context = "web search results:\n"
                        for r in results:
                            search_context += (
                                f"- {r['title']}: {r['content'][:200]}...\n"
                            )

                        return search_context
        except Exception as e:
            print(f"web search error: {e}")

        return None

    def is_conversation_active(self, channel_id, user_id):
        key = (channel_id, user_id)
        if key not in self.active_conversations:
            return False

        last_message_time = self.active_conversations[key]["last_message"]
        time_since_last = datetime.now() - last_message_time

        if time_since_last.total_seconds() > self.conversation_timeout:
            del self.active_conversations[key]
            return False

        return True

    def start_conversation(self, channel_id, user_id):
        key = (channel_id, user_id)
        self.active_conversations[key] = {
            "messages": [],
            "last_message": datetime.now(),
        }

    def add_to_conversation(self, channel_id, user_id, role, content, author_name=None):
        key = (channel_id, user_id)

        if key not in self.active_conversations:
            return

        if role == "user" and author_name:
            message = {"role": "user", "content": f"{author_name}: {content}"}
        else:
            message = {"role": role, "content": content}

        self.active_conversations[key]["messages"].append(message)
        self.active_conversations[key]["last_message"] = datetime.now()

        if len(self.active_conversations[key]["messages"]) > self.context_length:
            self.active_conversations[key]["messages"] = self.active_conversations[key][
                "messages"
            ][-self.context_length :]

    def parse_actions(self, response_text):
        actions = {"reactions": [], "embeds": [], "typing": 0}

        react_pattern = r"\[REACT:([^\]]+)\]"
        reactions = re.findall(react_pattern, response_text)
        actions["reactions"] = [r.strip() for r in reactions]
        response_text = re.sub(react_pattern, "", response_text)

        embed_pattern = r"\[EMBED:([^:]+):([^\]]+)\]"
        embeds = re.findall(embed_pattern, response_text)
        for title, desc in embeds:
            actions["embeds"].append(
                {"title": title.strip(), "description": desc.strip()}
            )
        response_text = re.sub(embed_pattern, "", response_text)

        typing_pattern = r"\[TYPING:(\d+)\]"
        typing_match = re.search(typing_pattern, response_text)
        if typing_match:
            actions["typing"] = int(typing_match.group(1))
        response_text = re.sub(typing_pattern, "", response_text)

        response_text = response_text.strip()

        if len(response_text) > self.max_response_length:
            response_text = response_text[: self.max_response_length] + "..."

        return response_text, actions

    async def should_search(self, message_content: str) -> bool:
        search_keywords = [
            "search",
            "look up",
            "find",
            "what is",
            "who is",
            "latest",
            "recent",
            "current",
            "news",
            "today",
        ]
        return any(kw in message_content.lower() for kw in search_keywords)

    async def generate_response(self, channel_id, user_id, message_content=""):
        if not self.ollama_available:
            await self.check_ollama_connection()
            if not self.ollama_available:
                return None, {}

        try:
            key = (channel_id, user_id)
            context = self.active_conversations[key]["messages"]

            additional_context = ""
            if self.web_search_enabled and await self.should_search(message_content):
                search_results = await self.web_search(message_content)
                if search_results:
                    additional_context = f"\n\n{search_results}"

            messages = [
                {"role": "system", "content": self.system_prompt + additional_context}
            ]
            messages.extend(context)

            response = await asyncio.to_thread(
                ollama.chat,
                model=self.model,
                messages=messages,
                options={
                    "temperature": self.temperature,
                    "top_p": self.top_p,
                    "repeat_penalty": self.repeat_penalty,
                    "num_predict": self.num_predict,
                },
            )

            response_text = response["message"]["content"]
            clean_text, actions = self.parse_actions(response_text)

            if clean_text:
                self.add_to_conversation(channel_id, user_id, "dave", clean_text)

            return clean_text, actions

        except ollama.ResponseError as e:
            print(f"ollama response error: {e}")
            if "model" in str(e).lower():
                print(f"model {self.model} might not be available")
                self.ollama_available = False
            return None, {}

        except Exception as e:
            print(f"error generating response: {e}")
            self.ollama_available = False
            return None, {}

    def should_respond_unprompted(self, channel_id):
        if channel_id not in self.activity_tracker:
            return False

        if channel_id in self.last_response:
            time_since_last = datetime.now() - self.last_response[channel_id]
            required_cooldown = random.randint(
                self.min_response_cooldown, self.max_response_cooldown
            )

            if time_since_last.total_seconds() < required_cooldown:
                return False

        cutoff_time = datetime.now() - timedelta(seconds=self.activity_window)
        recent_messages = [
            ts for ts in self.activity_tracker[channel_id] if ts > cutoff_time
        ]
        self.activity_tracker[channel_id] = recent_messages

        has_enough_activity = len(recent_messages) >= self.activity_threshold
        random_check = random.random() < self.unprompted_chance

        return has_enough_activity and random_check

    def is_bot_mentioned(self, message):
        if self.bot.user in message.mentions:
            return True

        if message.reference and message.reference.resolved:
            if message.reference.resolved.author == self.bot.user:
                return True

        return False

    def clean_bot_mention(self, content):
        for mention in [f"<@{self.bot.user.id}>", f"<@!{self.bot.user.id}>"]:
            content = content.replace(mention, "")
        return content.strip()

    async def execute_actions(self, message, actions):
        for emoji in actions["reactions"]:
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException:
                pass

        for embed_data in actions["embeds"]:
            try:
                embed = discord.Embed(
                    title=embed_data["title"],
                    description=embed_data["description"],
                    color=discord.Color.blue(),
                )
                await message.channel.send(embed=embed)
            except discord.HTTPException:
                pass

        if actions["typing"] > 0:
            await asyncio.sleep(min(actions["typing"], 5))

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        if not message.guild:
            return

        if message.author.bot:
            return

        channel_id = message.channel.id
        user_id = message.author.id

        if channel_id not in self.activity_tracker:
            self.activity_tracker[channel_id] = []

        bot_mentioned = self.is_bot_mentioned(message)

        if bot_mentioned:
            if not self.is_conversation_active(channel_id, user_id):
                self.start_conversation(channel_id, user_id)

            content = self.clean_bot_mention(message.content)

            if not content:
                content = "hey"

            self.add_to_conversation(
                channel_id, user_id, "user", content, message.author.display_name
            )

            if self.ollama_available:
                async with message.channel.typing():
                    response, actions = await self.generate_response(
                        channel_id, user_id, content
                    )

                    if response:
                        try:
                            sent_message = await message.reply(
                                response, mention_author=False
                            )
                            await self.execute_actions(sent_message, actions)
                        except discord.HTTPException as e:
                            print(f"failed to send message: {e}")
                    else:
                        await message.reply("ai is offline", mention_author=False)
        else:
            self.activity_tracker[channel_id].append(datetime.now())

            if self.should_respond_unprompted(channel_id) and self.ollama_available:
                self.start_conversation(channel_id, user_id)
                self.add_to_conversation(
                    channel_id,
                    user_id,
                    "user",
                    message.content,
                    message.author.display_name,
                )

                async with message.channel.typing():
                    response, actions = await self.generate_response(
                        channel_id, user_id, message.content
                    )

                    if response:
                        try:
                            sent_message = await message.channel.send(response)
                            await self.execute_actions(sent_message, actions)
                            self.last_response[channel_id] = datetime.now()
                        except discord.HTTPException as e:
                            print(f"failed to send message: {e}")

    @app_commands.command(name="botstatus", description="check ollama bot status")
    async def check_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not await self.bot.is_owner(interaction.user):
            await interaction.followup.send(
                "you don't have permission to use this command", ephemeral=True
            )
            return

        await self.check_ollama_connection()

        if self.ollama_available:
            try:
                response = await asyncio.to_thread(ollama.list)
                models = response.get("models", [])
                model_list = [m.get("name", m.get("model", "unknown")) for m in models]

                status_msg = "ollama online\n"
                status_msg += f"model: **{self.model}**\n"
                status_msg += f"web search: {'enabled' if self.web_search_enabled else 'disabled'}\n"
                status_msg += f"available: {', '.join(model_list[:5])}"

                await interaction.followup.send(status_msg, ephemeral=True)
            except Exception as e:
                await interaction.followup.send(
                    f"ollama available but error: {e}", ephemeral=True
                )
        else:
            await interaction.followup.send("ollama offline", ephemeral=True)

    @app_commands.command(name="search", description="manually perform a web search")
    async def manual_search(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(ephemeral=True)

        if not await self.bot.is_owner(interaction.user):
            await interaction.followup.send(
                "you don't have permission to use this command", ephemeral=True
            )
            return

        if not self.web_search_enabled:
            await interaction.followup.send(
                "web search not enabled (need OLLAMA_API_KEY)", ephemeral=True
            )
            return

        results = await self.web_search(query)
        if results:
            await interaction.followup.send(results, ephemeral=True)
        else:
            await interaction.followup.send("no results found", ephemeral=True)

    @app_commands.command(
        name="resetconvo", description="reset your current conversation with the bot"
    )
    async def reset_conversation(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not await self.bot.is_owner(interaction.user):
            await interaction.followup.send(
                "you don't have permission to use this command", ephemeral=True
            )
            return

        key = (interaction.channel.id, interaction.user.id)

        if key in self.active_conversations:
            del self.active_conversations[key]
            await interaction.followup.send("conversation reset", ephemeral=True)
        else:
            await interaction.followup.send("no active conversation", ephemeral=True)

    @app_commands.command(
        name="debugcontext", description="debug: show current conversation context"
    )
    async def debug_context(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not await self.bot.is_owner(interaction.user):
            await interaction.followup.send(
                "you don't have permission to use this command", ephemeral=True
            )
            return

        key = (interaction.channel.id, interaction.user.id)

        if key not in self.active_conversations:
            await interaction.followup.send("no active conversation", ephemeral=True)
            return

        context = self.active_conversations[key]["messages"]
        context_str = "\n\n".join(
            [f"**{msg['role']}**: {msg['content']}" for msg in context]
        )

        if len(context_str) > 1900:
            context_str = context_str[:1900] + "..."

        await interaction.followup.send(f"**context:**\n{context_str}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ChatBot(bot))

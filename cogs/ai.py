import discord
from discord import app_commands
from discord.ext import commands
import ollama
import asyncio
from datetime import datetime, timedelta
import os
import re
from dotenv import load_dotenv

load_dotenv()

class ChatBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ollama_available = False
        self.active_conversations = {}

        self.model = os.getenv("OLLAMA_MODEL", "vanillyn:latest")
        self.context_length = 15
        self.num_ctx = 8192

        self.llm_options = {
            "mirostat": 2,
            "mirostat_tau": 4.0,
            "mirostat_eta": 0.1,
            "num_ctx": 8192,
            "temperature": 0.8,
            "repeat_penalty": 1.1,
            "num_predict": 120,
            "num_thread": 8,
            "stop": ["<|im_start|>", "<|im_end|>", "User:", "Vanillyn:", "\n\n"]
        }

        self.system_prompt = (
            "You are Vanillyn, a real person on Discord. "
            "IMPORTANT: Do not continue the user's text. Do not predict what the user will say. "
            "Only generate YOUR response. If you try to speak for the user, you fail. "
            "Style: casual, lowercase, short, human-like."
        )

        self.bot.loop.create_task(self.check_ollama_connection())

    async def check_ollama_connection(self):
        try:
            await asyncio.to_thread(ollama.list)
            self.ollama_available = True
            print(f"Ollama connected: {self.model}")
        except Exception as e:
            self.ollama_available = False
            print(f"Ollama connection error: {e}")

    def is_conversation_active(self, channel_id, user_id):
        key = (channel_id, user_id)
        if key not in self.active_conversations: return False
        last_message_time = self.active_conversations[key]["last_message"]
        if (datetime.now() - last_message_time).total_seconds() > 900:
            del self.active_conversations[key]
            return False
        return True

    def start_conversation(self, channel_id, user_id):
        self.active_conversations[(channel_id, user_id)] = {
            "messages": [],
            "last_message": datetime.now(),
        }

    def add_to_conversation(self, channel_id, user_id, role, content):
        key = (channel_id, user_id)
        if key not in self.active_conversations: return

        self.active_conversations[key]["messages"].append({"role": role, "content": content})
        self.active_conversations[key]["last_message"] = datetime.now()

        if len(self.active_conversations[key]["messages"]) > self.context_length:
            self.active_conversations[key]["messages"] = self.active_conversations[key]["messages"][-self.context_length:]

    def parse_actions(self, text):
        text = re.sub(r"^(Vanillyn|Assistant|User|System):\s*", "", text, flags=re.IGNORECASE | re.MULTILINE)

        stop_indicators = [r"\n\w+:", r"###", r"User:", r"\[", r"MESSAGE FROM"]
        for pattern in stop_indicators:
            text = re.split(pattern, text)[0]

        text = re.sub(r"(?<!\[REACT:):[a-zA-Z0-9_]+:(?!\])", "", text)

        return text.strip(), {"reactions": re.findall(r"\[REACT:([^\]]+)\]", text)}

    async def generate_response(self, channel_id, user_id):
        if not self.ollama_available: return None, {}

        try:
            history = self.active_conversations[(channel_id, user_id)]["messages"]
            messages = [{"role": "system", "content": self.system_prompt}] + history

            try:
                response = await asyncio.to_thread(
                    ollama.chat,
                    model=self.model,
                    messages=messages,
                    options=self.llm_options
                )
            except Exception as e:
                print(f"Ollama Options Error, falling back to Safe Mode: {e}")
                response = await asyncio.to_thread(
                    ollama.chat,
                    model=self.model,
                    messages=messages,
                    options={
                        "num_ctx": 4096,
                        "temperature": 0.7,
                        "stop": ["User:", "\n\n"]
                    }
                )

            raw_text = response["message"]["content"]
            clean_text, actions = self.parse_actions(raw_text)

            if clean_text:
                self.add_to_conversation(channel_id, user_id, "assistant", clean_text)

            return clean_text, actions

        except Exception as e:
            print(f"Critical Generation error: {e}")
            return None, {}

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild: return

        is_mentioned = self.bot.user in message.mentions or (
            message.reference and message.reference.resolved and
            message.reference.resolved.author == self.bot.user
        )

        if is_mentioned:
            cid, uid = message.channel.id, message.author.id
            if not self.is_conversation_active(cid, uid):
                self.start_conversation(cid, uid)

            clean_input = message.content.replace(f"<@{self.bot.user.id}>", "").strip() or "hey"
            user_payload = f"{message.author.display_name}: {clean_input}"

            self.add_to_conversation(cid, uid, "user", user_payload)

            async with message.channel.typing():
                response, actions = await self.generate_response(cid, uid)
                if response:
                    try:
                        sent = await message.reply(response, mention_author=False)
                        for emoji in actions["reactions"]:
                            try: await sent.add_reaction(emoji.strip())
                            except: pass
                    except Exception as e:
                        print(f"Send error: {e}")

    @app_commands.command(name="vanstatus", description="Hardware utilization check")
    async def check_status(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"**Vanillyn AI Node**\n"
            f"Model: `{self.model}`\n"
            f"Threads: `{self.llm_options['num_thread']}`\n"
            f"Status: `🟢 Monitoring`",
            ephemeral=True
        )

async def setup(bot):
    await bot.add_cog(ChatBot(bot))

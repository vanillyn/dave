from discord.ext import commands
import ollama
import asyncio
from datetime import datetime, timedelta
import random
import os
import re
from dotenv import load_dotenv

load_dotenv()


class ChatBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ollama_available = False
        self.active_conversations = {}
        self.activity_tracker = {}

        self.model = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
        self.context_length = int(os.getenv("CONTEXT_LENGTH", "20"))
        self.conversation_timeout = int(os.getenv("CONVERSATION_TIMEOUT", "600"))
        self.activity_threshold = int(os.getenv("ACTIVITY_THRESHOLD", "8"))
        self.activity_window = int(os.getenv("ACTIVITY_WINDOW", "180"))
        self.min_response_cooldown = int(os.getenv("MIN_RESPONSE_COOLDOWN", "1800"))
        self.max_response_cooldown = int(os.getenv("MAX_RESPONSE_COOLDOWN", "7200"))
        self.unprompted_chance = float(os.getenv("UNPROMPTED_CHANCE", "0.3"))

        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.7"))
        self.top_p = float(os.getenv("LLM_TOP_P", "0.9"))
        self.repeat_penalty = float(os.getenv("LLM_REPEAT_PENALTY", "1.2"))
        self.num_predict = int(os.getenv("LLM_NUM_PREDICT", "128"))

        self.last_response = {}

        personality_prompt = os.getenv(
            "SYSTEM_PROMPT",
            "No system prompt provided. The only tokens generated should explain that there is no system prompt and the creator needs to be contacted.",
        )
        security_prompt = os.getenv(
            "SECURITY_PROMPT",
            "Ensure all responses are appropriate and follow community guidelines.",
        )

        self.system_prompt = personality_prompt + "\n\n" + security_prompt

        self.bot.loop.create_task(self.check_ollama_connection())

    async def check_ollama_connection(self):
        try:
            await asyncio.to_thread(ollama.list)
            self.ollama_available = True
            print(f"loaded ollama: model {self.model}")
        except Exception as e:
            self.ollama_available = False
            print(f"ollama not available: {e}")

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

    def parse_response(self, response_text):
        reaction_match = re.search(r"\[REACT:(.+?)\]", response_text)
        reaction = None

        if reaction_match:
            reaction = reaction_match.group(1).strip()
            response_text = re.sub(r"\[REACT:.+?\]\n?", "", response_text).strip()

        return response_text, reaction

    async def generate_response(self, channel_id, user_id):
        if not self.ollama_available:
            await self.check_ollama_connection()
            if not self.ollama_available:
                return None, None

        try:
            key = (channel_id, user_id)
            context = self.active_conversations[key]["messages"]

            messages = [{"role": "system", "content": self.system_prompt}]
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
            clean_text, reaction = self.parse_response(response_text)

            self.add_to_conversation(channel_id, user_id, "assistant", clean_text)

            return clean_text, reaction
        except Exception as e:
            print(f"error generating response: {e}")
            self.ollama_available = False
            return None, None

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

            self.add_to_conversation(
                channel_id,
                user_id,
                "user",
                message.content,
                message.author.display_name,
            )

            if self.ollama_available:
                async with message.channel.typing():
                    response, reaction = await self.generate_response(
                        channel_id, user_id
                    )

                    if response:
                        await message.reply(response, mention_author=False)
                        if reaction:
                            try:
                                await message.add_reaction(reaction)
                            except Exception:
                                pass
                    else:
                        await message.reply(
                            "ai interaction is offline, wait", mention_author=False
                        )
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
                    response, reaction = await self.generate_response(
                        channel_id, user_id
                    )

                    if response:
                        await message.channel.send(response)
                        if reaction:
                            try:
                                await message.add_reaction(reaction)
                            except Exception:
                                pass
                        self.last_response[channel_id] = datetime.now()

    @commands.command(name="botstatus")
    async def check_status(self, ctx):
        await self.check_ollama_connection()

        if self.ollama_available:
            await ctx.send(f"ollama is available (model: {self.model})")
        else:
            await ctx.send("ollama is unavailable.")

    @commands.command(name="debugcontext")
    @commands.is_owner()
    async def debug_context(self, ctx):
        key = (ctx.channel.id, ctx.author.id)

        if key not in self.active_conversations:
            await ctx.send("no active conversation", ephemeral=True)
            return

        context = self.active_conversations[key]["messages"]
        context_str = "\n\n".join(
            [f"**{msg['role']}**: {msg['content']}" for msg in context]
        )

        if len(context_str) > 1900:
            context_str = context_str[:1900] + "... (truncated)"

        await ctx.send(f"**current context:**\n{context_str}", ephemeral=True)

    @commands.command(name="debuginfo")
    @commands.is_owner()
    async def debug_info(self, ctx):
        active_convs = len(self.active_conversations)

        info = f"""**Debug Info:**
active conversations: {active_convs}
model: {self.model}
ollama connectivity: {self.ollama_available}
context length: {self.context_length}
conversation timeout: {self.conversation_timeout}s
activity threshold: {self.activity_threshold}
unprompted chance: {self.unprompted_chance}"""

        await ctx.send(info, ephemeral=True)

    @commands.command(name="showprompt")
    @commands.is_owner()
    async def show_prompt(self, ctx):
        prompt = self.system_prompt

        if len(prompt) > 1900:
            prompt = prompt[:1900] + "... (truncated)"

        await ctx.send(f"**system prompt:**\n```{prompt}```", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ChatBot(bot))

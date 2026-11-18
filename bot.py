"""nikobot: the !ip command, plus a parody AI-assistant persona via a local LLM."""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import random
import time
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands

import chime
import persona
import safety
from llm import LLMError, LLMTimeout, Ollama

log = logging.getLogger("nikobot")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
MODEL = os.environ.get("NIKOBOT_MODEL", "").strip() or "local-chat:latest"
CHIME_CHANNELS = chime.parse_channel_ids(os.environ.get("NIKOBOT_CHIME_CHANNELS"))
DATA_DIR = Path(os.environ.get("NIKOBOT_DATA_DIR", "/data"))
# Deliberately outside the code directory: see main()
SECRETS_PATH = Path(os.environ.get("NIKOBOT_SECRETS", "/app/secrets.py"))

MAX_WAITING = 3  # chat requests allowed to queue for the model before "busy"
BLOCKLIST_SCAN = 15  # messages the blocklist checks before any chime-in
HUSH_DAYS = 7
CHAT_TYPES = (discord.MessageType.default, discord.MessageType.reply)
DIG = ["dig", "-4", "+short", "myip.opendns.com", "@resolver1.opendns.com"]


def guild_ids(*values) -> frozenset[int]:
    """Normalise configured guild IDs (int or numeric str); drops blanks and junk."""
    out = set()
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            out.add(int(str(value).strip()))
        except ValueError:
            continue
    return frozenset(out)


def ip_allowed(guild_id: int | None, allowed: frozenset[int]) -> bool:
    """!ip works only inside one of the allowed guilds, never in DMs."""
    return guild_id is not None and guild_id in allowed


def load_secrets(path: Path):
    # Loaded by path under a private name, so the file never has to be importable
    # as `secrets` (which would shadow the standard library module).
    spec = importlib.util.spec_from_file_location("nikobot_secrets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def lookup_ip() -> str:
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *DIG, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
    except (OSError, asyncio.TimeoutError):
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        return ""
    if proc.returncode != 0:
        return ""
    return out.decode(errors="replace").strip()


@commands.command(name="ip", help="Post this server's public IP")
async def ip_command(ctx: commands.Context) -> None:
    if ctx.guild is None:
        await ctx.send("That only works in a server, not in DMs.")
        return
    if not ip_allowed(ctx.guild.id, ctx.bot.ip_guilds):
        await ctx.send("Command does not work in this server")
        return
    ip = await lookup_ip()
    await ctx.send(ip or "Couldn't look up the IP right now.")


@commands.command(name="hush", help=f"Stop unprompted chime-ins for {HUSH_DAYS} days")
@commands.guild_only()
async def hush_command(ctx: commands.Context) -> None:
    ctx.bot.gate.state.hush(time.time(), days=HUSH_DAYS)
    log.info("chime: hushed for %d days", HUSH_DAYS)
    await ctx.send(persona.HUSH_LINE.format(days=HUSH_DAYS))


class Nikobot(commands.Bot):
    def __init__(self, ip_guilds: frozenset[int]):
        intents = discord.Intents.default()
        intents.message_content = True  # privileged: enable it in the developer portal
        super().__init__(
            command_prefix="!",
            intents=intents,
            activity=discord.Activity(
                type=discord.ActivityType.watching, name="the ever-evolving landscape"
            ),
            # whatever the model writes, it can never ping @everyone, roles or users
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=False, replied_user=True
            ),
        )
        self.ip_guilds = ip_guilds
        self.gate = chime.ChimeGate(CHIME_CHANNELS, chime.ChimeState(DATA_DIR / "chime_state.json"))
        self.llm_lock = asyncio.Lock()
        self.waiting = 0
        self.http_session: aiohttp.ClientSession | None = None
        self.llm: Ollama | None = None
        self.add_command(ip_command)
        self.add_command(hush_command)

    async def setup_hook(self) -> None:
        self.http_session = aiohttp.ClientSession()
        self.llm = Ollama(OLLAMA_URL, MODEL, self.http_session)

    async def close(self) -> None:
        await super().close()
        if self.http_session is not None:
            await self.http_session.close()

    async def on_ready(self) -> None:
        log.info(
            "logged in as %s (discord.py %s); model %s; chime-ins %s",
            self.user,
            discord.__version__,
            MODEL,
            f"allowed in {len(CHIME_CHANNELS)} channel(s)" if CHIME_CHANNELS else "off",
        )

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send("That only works in a server, not in DMs.")
            return
        log.error("command %s failed: %s", ctx.command, type(error).__name__)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.webhook_id is not None:
            return
        if message.type not in CHAT_TYPES:
            return
        if message.content.startswith(self.command_prefix):
            await self.process_commands(message)
            return
        if self.addressed(message):
            await self.chat(message)
            return
        await self.maybe_chime(message)

    # --- talking -----------------------------------------------------------

    def addressed(self, message: discord.Message) -> bool:
        replied_to = None
        ref = message.reference
        if ref is not None and isinstance(ref.resolved, discord.Message):
            replied_to = ref.resolved.author.id
        role = message.guild.self_role if message.guild is not None else None
        return persona.is_addressed(
            self.user.id,
            message.raw_mentions,
            message.raw_role_mentions,
            role.id if role is not None else None,
            replied_to,
        )

    def to_line(self, message: discord.Message) -> persona.Line | None:
        if message.type not in CHAT_TYPES:
            return None
        names = {u.id: u.display_name for u in message.mentions}
        text = persona.clean_text(message.content, self.user.id, names)
        if not text and (message.attachments or message.stickers):
            text = "[sent an attachment]"
        if not text:
            return None
        return persona.Line(message.author.display_name, text, message.author.id == self.user.id)

    async def recent_lines(self, channel, limit: int, before=None) -> list[persona.Line]:
        try:
            history = [m async for m in channel.history(limit=limit, before=before)]
        except discord.HTTPException:
            history = []
        history.reverse()
        return [line for m in history if (line := self.to_line(m)) is not None]

    async def generate(self, messages: list[dict], canned_errors: bool = True) -> str:
        """Run one reply. Errors become a canned line, or "" when not canned."""
        async with self.llm_lock:
            started = time.monotonic()
            try:
                reply = await self.llm.chat(messages)
            except LLMTimeout:
                log.warning("llm: timed out after %.0fs", time.monotonic() - started)
                return random.choice(persona.LOADING_LINES) if canned_errors else ""
            except (LLMError, aiohttp.ClientError, ValueError) as exc:
                log.warning("llm: %s %s", type(exc).__name__, exc if isinstance(exc, LLMError) else "")
                return random.choice(persona.BROKEN_LINES) if canned_errors else ""
        text = persona.tidy_reply(reply.text, reply.truncated)
        log.info("llm: %d chars in %.1fs", len(text), time.monotonic() - started)
        if not text and canned_errors:
            return random.choice(persona.EMPTY_LINES)
        return text

    async def clears_serious_check(self, lines: list[persona.Line]) -> bool:
        """Ask the model whether the latest lines are fine to joke about.

        Only an exact NO clears them; a timeout or error counts as serious.
        """
        prompt = safety.build_serious_check_messages(persona.transcript_lines(lines))
        async with self.llm_lock:
            try:
                answer = await self.llm.classify(prompt)
            except (LLMTimeout, LLMError, aiohttp.ClientError, ValueError) as exc:
                log.warning("serious check failed (%s); treating as serious", type(exc).__name__)
                return False
        return safety.serious_check_clears(answer)

    async def send(self, channel, text: str, reply_to: discord.Message | None = None) -> None:
        try:
            if reply_to is not None:
                await channel.send(text, reference=reply_to.to_reference(fail_if_not_exists=False))
            else:
                await channel.send(text)
        except discord.HTTPException as exc:
            log.warning("could not send message (HTTP %s)", exc.status)

    async def chat(self, message: discord.Message) -> None:
        trigger = self.to_line(message) or persona.Line(message.author.display_name, "*pokes you*")
        if safety.is_crisis(trigger.text):
            log.info("chat: crisis language, sent fixed support line")
            await self.send(message.channel, safety.CRISIS_LINE, message)
            return
        if self.waiting >= MAX_WAITING:
            log.info("chat: too many queued, sent busy line")
            await self.send(message.channel, random.choice(persona.BUSY_LINES), message)
            return
        self.waiting += 1
        try:
            async with message.channel.typing():
                lines = await self.recent_lines(
                    message.channel, persona.MAX_CONTEXT_MESSAGES - 1, before=message
                )
                lines.append(trigger)
                if not await self.clears_serious_check(lines):
                    log.info("chat: serious check did not clear, sent fixed bow-out")
                    text = random.choice(safety.BOW_OUT_LINES)
                else:
                    prompt = persona.build_chat_messages(
                        lines, serious_hint=safety.is_serious([trigger.text])
                    )
                    text = await self.generate(prompt)
        finally:
            self.waiting -= 1
        await self.send(message.channel, text, message)

    # --- unprompted chime-ins ---------------------------------------------

    async def maybe_chime(self, message: discord.Message) -> None:
        if message.guild is None or message.channel.id not in self.gate.channels:
            return
        channel = message.channel
        now = time.time()
        self.gate.tracker.record(channel.id, message.author.id, now)
        lines: list[persona.Line] = []

        async def recent_texts() -> list[str]:
            lines[:] = await self.recent_lines(channel, BLOCKLIST_SCAN)
            return [line.text for line in lines]

        async def classify() -> bool:
            async with self.llm_lock:
                answer = await self.llm.classify(persona.build_classifier_messages(lines))
            return persona.classifier_says_yes(answer)

        decision = await self.gate.evaluate(
            channel.id,
            False,
            now,
            recent_texts=recent_texts,
            model_ready=self.llm.model_loaded,
            classify=classify,
            llm_busy=lambda: self.llm_lock.locked() or self.waiting > 0,
        )
        if not decision.ok:
            return
        async with channel.typing():
            prompt = persona.build_chat_messages(lines, direction=persona.CHIME_DIRECTION)
            text = await self.generate(prompt, canned_errors=False)
        if not text:
            log.info("chime: nothing usable generated; not posting")
            return
        await self.send(channel, text)
        log.info("chime: posted")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # discord.py 2.x calls the stdlib secrets.randbits() on every send. A
    # secrets.py sitting next to bot.py would be imported in its place and break
    # every message, so refuse to start rather than fail on the first reply.
    import secrets as stdlib_secrets

    if not hasattr(stdlib_secrets, "randbits"):
        raise SystemExit("a secrets.py beside bot.py shadows the stdlib; set NIKOBOT_SECRETS")
    secrets = load_secrets(SECRETS_PATH)
    ip_guilds = guild_ids(
        getattr(secrets, "guild_permission", None), getattr(secrets, "guild_permission2", None)
    )
    Nikobot(ip_guilds).run(secrets.token, log_handler=None)


if __name__ == "__main__":
    main()

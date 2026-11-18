"""nikobot: the !ip command, plus a parody AI-assistant persona via a local LLM.

Rules this file enforces (the owner's, 2026-11-18):
- It only ever speaks when asked: an @mention or reply to it, or `!ip`.
  Nothing unprompted. The chime-in code in chime.py is not wired up.
- Only in the owner's own servers (the guild IDs in secrets.py). It ignores
  every other server and leaves any new one it gets added to.
- Never in DMs: a DM gets no reply and never reaches the model.
- It logs every message it sees (DMs included) to /data/messages.log*, as
  JSON lines, rotated. It never logs to stdout, so chat text stays out of
  Loki/Grafana.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import logging.handlers
import os
import random
import time
from datetime import date
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands, tasks

import persona
import safety
from llm import LLMError, LLMTimeout, Ollama

log = logging.getLogger("nikobot")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
MODEL = os.environ.get("NIKOBOT_MODEL", "").strip() or "local-chat:latest"
DATA_DIR = Path(os.environ.get("NIKOBOT_DATA_DIR", "/data"))
# Deliberately outside the code directory: see main()
SECRETS_PATH = Path(os.environ.get("NIKOBOT_SECRETS", "/app/secrets.py"))

MAX_WAITING = 3  # chat requests allowed to queue for the model before "busy"
CHAT_COOLDOWN_S = 20  # per person: extra pings inside this window are ignored
MESSAGE_LOG_BYTES = 10 * 1024 * 1024  # per file; 10 rotated files kept
MESSAGE_LOG_FILES = 10
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
    """A guild the bot may act in: one of the owner's, never a DM (None)."""
    return guild_id is not None and guild_id in allowed


_ACTIVITY_TYPES = {
    "watching": discord.ActivityType.watching,
    "listening": discord.ActivityType.listening,
    "playing": discord.ActivityType.playing,
    "competing": discord.ActivityType.competing,
}


def activity_for(kind: str, text: str) -> discord.BaseActivity:
    """A Discord presence for one of persona.STATUSES."""
    if kind == "custom":
        return discord.CustomActivity(name=text)
    return discord.Activity(type=_ACTIVITY_TYPES[kind], name=text)


class Cooldown:
    """At most one chat per person per window; extra pings are dropped silently."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self.last: dict[int, float] = {}

    def allow(self, user_id: int, now: float) -> bool:
        last = self.last.get(user_id)
        if last is not None and now - last < self.seconds:
            return False
        self.last[user_id] = now
        if len(self.last) > 1000:  # forget old entries so this can't grow forever
            cutoff = now - self.seconds
            self.last = {k: v for k, v in self.last.items() if v >= cutoff}
        return True


def message_record(message) -> str:
    """One JSON line describing a message, for the message log."""
    guild = message.guild
    channel = message.channel
    return json.dumps(
        {
            "at": message.created_at.isoformat(),
            "guild": guild.name if guild is not None else None,
            "guild_id": guild.id if guild is not None else None,
            "channel": getattr(channel, "name", None) or "DM",
            "channel_id": channel.id,
            "author": str(message.author),
            "author_id": message.author.id,
            "bot": bool(message.author.bot),
            "content": message.content,
            "attachments": [a.url for a in message.attachments],
        },
        ensure_ascii=False,
    )


def make_message_log(path: Path) -> logging.Logger | None:
    """A file-only logger for message content; None if the file can't be opened."""
    logger = logging.getLogger("nikobot.messages")
    logger.propagate = False  # never to stdout, so never to Loki
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        try:
            handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=MESSAGE_LOG_BYTES, backupCount=MESSAGE_LOG_FILES, encoding="utf-8"
            )
        except OSError as exc:
            log.warning("message log disabled: can't open %s (%s)", path, type(exc).__name__)
            return None
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    return logger


def load_secrets(path: Path):
    # Loaded by path under a private name, so the file never has to be importable
    # as `secrets` (which would shadow the standard library module).
    spec = importlib.util.spec_from_file_location("nikobot_secrets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def lookup_ip() -> str:
    # Fixed argument list, no shell, no user input: nothing to inject into.
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
    # on_message already drops DMs and other servers; this is a second guard.
    if not ip_allowed(ctx.guild.id if ctx.guild is not None else None, ctx.bot.allowed_guilds):
        return
    ip = await lookup_ip()
    await ctx.send(ip or "Couldn't look up the IP right now.")


class Nikobot(commands.Bot):
    def __init__(self, allowed_guilds: frozenset[int]):
        intents = discord.Intents.default()
        intents.message_content = True  # privileged: enable it in the developer portal
        super().__init__(
            command_prefix="!",
            help_command=None,  # no !help: the bot answers nothing it wasn't built for
            intents=intents,
            # today's parody status; daily_status swaps it when the date changes
            activity=activity_for(*persona.status_for(date.today())),
            # whatever the model writes, it can never ping @everyone, roles or users
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=False, replied_user=True
            ),
        )
        self.allowed_guilds = allowed_guilds
        self.status_day = date.today()
        self.cooldown = Cooldown(CHAT_COOLDOWN_S)
        self.message_log = make_message_log(DATA_DIR / "messages.log")
        self.llm_lock = asyncio.Lock()
        self.waiting = 0
        self.http_session: aiohttp.ClientSession | None = None
        self.llm: Ollama | None = None
        self.add_command(ip_command)

    async def setup_hook(self) -> None:
        self.http_session = aiohttp.ClientSession()
        self.llm = Ollama(OLLAMA_URL, MODEL, self.http_session)
        self.daily_status.start()

    @tasks.loop(minutes=15)
    async def daily_status(self) -> None:
        """Swap to the next parody status once the local date changes."""
        today = date.today()
        if today == self.status_day:
            return
        kind, text = persona.status_for(today)
        try:
            await self.change_presence(activity=activity_for(kind, text))
        except discord.HTTPException as exc:
            log.warning("status change failed (HTTP %s); will retry", exc.status)
            return
        self.status_day = today
        log.info("status for %s: %s %r", today, kind, text)

    @daily_status.before_loop
    async def before_daily_status(self) -> None:
        await self.wait_until_ready()

    async def close(self) -> None:
        await super().close()
        if self.http_session is not None:
            await self.http_session.close()

    async def on_ready(self) -> None:
        log.info(
            "logged in as %s (discord.py %s); model %s; %d allowed guild(s); message log %s",
            self.user,
            discord.__version__,
            MODEL,
            len(self.allowed_guilds),
            "on" if self.message_log is not None else "OFF",
        )
        log.info("status for %s: %s %r", self.status_day, *persona.status_for(self.status_day))
        for guild in self.guilds:
            log.info(
                "in guild %s (%s): %s",
                guild.id,
                guild.name,
                "allowed" if guild.id in self.allowed_guilds else "NOT allowed - ignoring it",
            )

    async def on_guild_join(self, guild: discord.Guild) -> None:
        # Someone added the bot to a server that isn't the owner's: leave at once.
        if guild.id not in self.allowed_guilds:
            log.warning("added to unknown guild %s (%s); leaving", guild.id, guild.name)
            try:
                await guild.leave()
            except discord.HTTPException as exc:
                log.warning("could not leave guild %s (HTTP %s)", guild.id, exc.status)

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, (commands.CommandNotFound, commands.NoPrivateMessage)):
            return
        log.error("command %s failed: %s", ctx.command, type(error).__name__)

    async def on_message(self, message: discord.Message) -> None:
        self.record(message)
        if message.guild is None:
            return  # DMs: logged, never answered, never sent to the model
        if not ip_allowed(message.guild.id, self.allowed_guilds):
            return  # not one of the owner's servers
        if message.author.bot or message.webhook_id is not None:
            return
        if message.type not in CHAT_TYPES:
            return
        if message.content.startswith(self.command_prefix):
            await self.process_commands(message)
            return
        if self.addressed(message):
            await self.chat(message)

    def record(self, message: discord.Message) -> None:
        if self.message_log is None:
            return
        try:
            self.message_log.info(message_record(message))
        except Exception as exc:  # noqa: BLE001 - logging must never break the bot
            log.warning("message log write failed: %s", type(exc).__name__)

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

    async def generate(self, messages: list[dict]) -> str:
        """Run one reply. Errors become a canned in-character line."""
        async with self.llm_lock:
            started = time.monotonic()
            try:
                reply = await self.llm.chat(messages)
            except LLMTimeout:
                log.warning("llm: timed out after %.0fs", time.monotonic() - started)
                return random.choice(persona.LOADING_LINES)
            except (LLMError, aiohttp.ClientError, ValueError) as exc:
                log.warning("llm: %s %s", type(exc).__name__, exc if isinstance(exc, LLMError) else "")
                return random.choice(persona.BROKEN_LINES)
        if persona.leaked_reasoning(reply.text):
            log.info("llm: stripped the model's planning from the start of its reply")
        text = persona.tidy_reply(reply.text, reply.truncated)
        log.info("llm: %d chars in %.1fs", len(text), time.monotonic() - started)
        return text or random.choice(persona.EMPTY_LINES)

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

    async def send(self, channel, text: str, reply_to: discord.Message) -> None:
        try:
            await channel.send(text, reference=reply_to.to_reference(fail_if_not_exists=False))
        except discord.HTTPException as exc:
            log.warning("could not send message (HTTP %s)", exc.status)

    async def chat(self, message: discord.Message) -> None:
        if not self.cooldown.allow(message.author.id, time.monotonic()):
            log.info("chat: same person pinged again within %ds; ignored", CHAT_COOLDOWN_S)
            return
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
                    # The owner's rule: when it's serious, say nothing at all,
                    # even though the bot was pinged.
                    log.info("chat: serious check did not clear; staying silent")
                    return
                prompt = persona.build_chat_messages(
                    lines, serious_hint=safety.is_serious([trigger.text])
                )
                text = await self.generate(prompt)
        finally:
            self.waiting -= 1
        await self.send(message.channel, text, message)


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
    allowed = guild_ids(
        getattr(secrets, "guild_permission", None), getattr(secrets, "guild_permission2", None)
    )
    if not allowed:
        raise SystemExit("no guild IDs in secrets.py (guild_permission/guild_permission2); refusing to start")
    Nikobot(allowed).run(secrets.token, log_handler=None)


if __name__ == "__main__":
    main()

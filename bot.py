"""nikobot: the !ip command, a parody AI-assistant persona via a local LLM,
and go-live posts for the owner's friends' Twitch channels.

Rules this file enforces (the owner's, 2026-11-18):
- It only ever speaks when asked: an @mention or reply to it, or `!ip`.
  The one exception is the go-live post (streams.py): a fixed template, never
  model text, only in the one configured channel, never pinging anyone. The
  chime-in code in chime.py is not wired up.
- It shows no Discord status (the owner removed it, 2026-11-18).
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
from dataclasses import dataclass
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands, tasks

import persona
import safety
import streams
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
STREAM_POLL_S = 60


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


@dataclass(frozen=True)
class StreamConfig:
    channel_id: int
    logins: tuple[str, ...]
    client_id: str
    client_secret: str


def stream_config(secrets) -> tuple[StreamConfig | None, str]:
    """Go-live settings from secrets.py, or (None, what's missing)."""
    channel = guild_ids(getattr(secrets, "stream_channel", None))
    logins = streams.parse_logins(getattr(secrets, "twitch_streamers", None))
    client_id = str(getattr(secrets, "twitch_client_id", "") or "").strip()
    client_secret = str(getattr(secrets, "twitch_client_secret", "") or "").strip()
    missing = [
        name
        for name, ok in (
            ("stream_channel", len(channel) == 1),
            ("twitch_streamers", bool(logins)),
            ("twitch_client_id", bool(client_id)),
            ("twitch_client_secret", bool(client_secret)),
        )
        if not ok
    ]
    if missing:
        return None, "missing " + ", ".join(missing)
    return StreamConfig(next(iter(channel)), logins, client_id, client_secret), "ok"


def context_without_serious(lines: list[persona.Line]) -> list[persona.Line]:
    """Earlier messages for the joke's context, minus any on serious topics."""
    return [line for line in lines if not safety.is_serious([line.text])]


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
    def __init__(
        self,
        allowed_guilds: frozenset[int],
        stream_settings: StreamConfig | None = None,
        stream_note: str = "not configured",
    ):
        intents = discord.Intents.default()
        intents.message_content = True  # privileged: enable it in the developer portal
        super().__init__(
            command_prefix="!",
            help_command=None,  # no !help: the bot answers nothing it wasn't built for
            intents=intents,
            # whatever the model writes, it can never ping @everyone, roles or users
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=False, replied_user=True
            ),
        )
        self.allowed_guilds = allowed_guilds
        self.stream_settings = stream_settings
        self.stream_note = stream_note
        self.stream_state: streams.StreamState | None = None
        self.twitch: streams.Twitch | None = None
        self.stream_errors = 0
        self.stream_channel_problem: str | None = None
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
        if self.stream_settings is not None:
            self.stream_state = streams.StreamState(DATA_DIR / "stream_state.json")
            self.twitch = streams.Twitch(
                self.stream_settings.client_id, self.stream_settings.client_secret, self.http_session
            )
            self.stream_watch.start()

    # --- go-live posts -----------------------------------------------------

    @tasks.loop(seconds=STREAM_POLL_S)
    async def stream_watch(self) -> None:
        try:
            await self.check_streams()
        except Exception as exc:  # noqa: BLE001 - an exception would stop this loop for good
            log.warning("streams: %s", type(exc).__name__)

    @stream_watch.before_loop
    async def before_stream_watch(self) -> None:
        await self.wait_until_ready()

    def stream_channel(self) -> discord.abc.Messageable | None:
        """The configured go-live channel, if it's usable; logs a problem once."""
        channel = self.get_channel(self.stream_settings.channel_id)
        problem = None
        if channel is None or not isinstance(channel, discord.TextChannel):
            problem = "the stream_channel isn't a text channel the bot can see"
        elif channel.guild.id not in self.allowed_guilds:
            problem = "the stream_channel isn't in one of the owner's servers"
        else:
            perms = channel.permissions_for(channel.guild.me)
            if not (perms.view_channel and perms.send_messages):
                problem = f"no permission to post in #{channel.name}"
        if problem != self.stream_channel_problem:
            if problem:
                log.warning("streams: %s; go-live posts paused", problem)
            elif self.stream_channel_problem:
                log.info("streams: channel usable again")
            self.stream_channel_problem = problem
        return None if problem else channel

    async def check_streams(self) -> None:
        channel = self.stream_channel()
        if channel is None or self.stream_state is None or self.twitch is None:
            return
        try:
            live = await self.twitch.live(self.stream_settings.logins)
        except streams.TwitchError as exc:
            self.stream_errors += 1
            if self.stream_errors in (1, 10) or self.stream_errors % 60 == 0:
                log.warning("streams: Twitch check failed (%s), %d in a row", exc, self.stream_errors)
            return
        if self.stream_errors:
            log.info("streams: Twitch reachable again after %d failure(s)", self.stream_errors)
            self.stream_errors = 0
        for stream in self.stream_state.update(live, time.time()):
            text = streams.announcement(stream)
            try:
                await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException as exc:
                log.warning("streams: could not post for %s (HTTP %s)", stream.login, exc.status)
                continue
            log.info("streams: posted go-live for %s", stream.login)

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
        if self.stream_settings is not None:
            channel = self.get_channel(self.stream_settings.channel_id)
            log.info(
                "go-live posts: %d Twitch channel(s) -> #%s",
                len(self.stream_settings.logins),
                getattr(channel, "name", "?"),
            )
        else:
            log.info("go-live posts off (%s)", self.stream_note)
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

    async def reply_clears(self, text: str) -> bool:
        """Ask the model whether a reply it wrote is fine to post.

        The model is uncensored, so this is what keeps slurs, hate and sexual
        content out of the channel. Only an exact NO clears it; a timeout or
        error counts as not cleared.
        """
        async with self.llm_lock:
            try:
                answer = await self.llm.classify(safety.build_reply_check_messages(text))
            except (LLMTimeout, LLMError, aiohttp.ClientError, ValueError) as exc:
                log.warning("reply check failed (%s); holding the reply", type(exc).__name__)
                return False
        return safety.reply_check_clears(answer)

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
                # Only the message that pinged the bot decides whether it's
                # serious; earlier messages don't (a "laid off" two messages
                # ago shouldn't silence an unrelated ping).
                if not await self.clears_serious_check([trigger]):
                    # The owner's rule: when it's serious, say nothing at all,
                    # even though the bot was pinged.
                    log.info("chat: serious check did not clear; staying silent")
                    return
                # Context for the joke: recent messages, minus any that hit the
                # serious-topic list, so it can't riff on someone's bad news.
                history = await self.recent_lines(
                    message.channel, persona.MAX_CONTEXT_MESSAGES - 1, before=message
                )
                lines = context_without_serious(history) + [trigger]
                prompt = persona.build_chat_messages(
                    lines, serious_hint=safety.is_serious([trigger.text])
                )
                text = await self.generate(prompt)
                if text not in persona.CANNED_LINES and not await self.reply_clears(text):
                    log.info("chat: reply check did not clear; sent a held line")
                    text = random.choice(persona.HELD_LINES)
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
    settings, note = stream_config(secrets)
    Nikobot(allowed, settings, note).run(secrets.token, log_handler=None)


if __name__ == "__main__":
    main()

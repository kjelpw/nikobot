"""nikobot: the !ip command, a parody AI-assistant persona via a local LLM,
and go-live posts for the owner's friends' Twitch channels.

Rules this file enforces (the owner's, 2026-11-18):
- It only ever speaks when asked: an @mention or reply to it, or `!ip`.
  A ping always gets an answer, serious topic or not (crisis language gets
  the fixed support line; a serious-looking ping gets a plain answer).
  The ping reply is filtered for slurs and prompt leaks only (2026-11-19); a
  chime-in must also pass the full reply check (reply_clears).
  Two exceptions: the go-live post (streams.py), a fixed template, never
  model text, only in the one configured channel, never pinging anyone; and
  rare chime-ins (chime.py, the owner's ask 2026-11-19), only in the servers
  in chime_guilds, at most one a day, censored by the full reply check, and
  silenced for a week by !hush.
- It shows no Discord status (the owner removed it, 2026-11-18).
- Only in the owner's own servers (the guild IDs in secrets.py). It ignores
  every other server and leaves any new one it gets added to.
- Never in DMs: a DM gets no reply and never reaches the model.
- It logs every message it sees (DMs included) to /data/messages.log*, as
  JSON lines, rotated. It never logs to stdout, so chat text stays out of
  Loki/Grafana.
- Pictures (the owner's ask, 2026-11-19): images and GIFs in a reply's
  context are described by the small vision model (images.py) and become
  "[image: ...]" in the chat line. Only when a reply or chime-in is being
  built, only from Discord's own hosts, never stored, captions never logged,
  and a failure or a slow caption only ever gives "[image]".
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
import chime
import images
import streams
from llm import LLMError, LLMTimeout, Ollama

log = logging.getLogger("nikobot")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
MODEL = os.environ.get("NIKOBOT_MODEL", "").strip() or "local-chat:latest"
# The vision model for image captions; "off" turns captions off ("[image]").
# local-small is already loaded beside local-chat, so this adds no third model.
CAPTION_MODEL = os.environ.get("NIKOBOT_CAPTION_MODEL", "").strip() or "local-small:latest"
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
BLOCKLIST_SCAN = 15  # messages the serious-topic list checks before a chime-in
HUSH_DAYS = 7
MAX_CHIME_CHANCE = 0.25
EMBED_WAIT_S = 1.5  # Discord adds a link's embed a moment after the message


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


@dataclass(frozen=True)
class ChimeConfig:
    guilds: frozenset[int]
    chance: float


def chime_config(secrets, allowed: frozenset[int]) -> tuple[ChimeConfig | None, str]:
    """Chime-in settings from secrets.py (chime_guilds, chime_chance), or (None, why not)."""
    raw = getattr(secrets, "chime_guilds", None)
    guilds = guild_ids(*raw) if isinstance(raw, (list, tuple, set, frozenset)) else guild_ids(raw)
    if not guilds:
        return None, "no chime_guilds"
    if not guilds <= allowed:
        return None, "chime_guilds lists a server that isn't one of the owner's"
    try:
        chance = float(getattr(secrets, "chime_chance", 0.02))
    except (TypeError, ValueError):
        return None, "chime_chance isn't a number"
    if not 0 < chance <= MAX_CHIME_CHANCE:
        return None, f"chime_chance must be above 0 and at most {MAX_CHIME_CHANCE}"
    return ChimeConfig(guilds, chance), "ok"


def focus(lines: list[persona.Line], is_reply: bool) -> list[persona.Line]:
    """Just the ping, when it clearly stands on its own (the owner's ask, 2026-11-19).

    Earlier messages are background, not the topic. A plain word check, no
    model call, so it costs nothing; any hint the ping refers back keeps them.
    """
    *history, trigger = lines
    if history and not persona.needs_context(trigger.text, is_reply):
        log.info("chat: the ping stands on its own; answering it without earlier messages")
        return [trigger]
    return lines


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


@commands.command(name="hush", help=f"Stop unprompted chime-ins for {HUSH_DAYS} days")
async def hush_command(ctx: commands.Context) -> None:
    gate = ctx.bot.gate
    if gate is None or ctx.guild is None or ctx.guild.id not in gate.guilds:
        return  # only where chime-ins are on
    gate.state.hush(time.time(), days=HUSH_DAYS)
    log.info("chime: hushed for %d days", HUSH_DAYS)
    await ctx.send(persona.HUSH_LINE.format(days=HUSH_DAYS))


class Nikobot(commands.Bot):
    def __init__(
        self,
        allowed_guilds: frozenset[int],
        stream_settings: StreamConfig | None = None,
        stream_note: str = "not configured",
        chime_settings: ChimeConfig | None = None,
        chime_note: str = "not configured",
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
        self.captioner: images.Captioner | None = None
        self.add_command(ip_command)
        self.chime_note = chime_note
        self.gate: chime.ChimeGate | None = None
        if chime_settings is not None:
            self.gate = chime.ChimeGate(
                frozenset(),
                chime.ChimeState(DATA_DIR / "chime_state.json"),
                chance=chime_settings.chance,
                guilds=chime_settings.guilds,
            )
            self.add_command(hush_command)

    async def setup_hook(self) -> None:
        self.http_session = aiohttp.ClientSession()
        self.llm = Ollama(OLLAMA_URL, MODEL, self.http_session)
        if CAPTION_MODEL.lower() != "off":
            vision = Ollama(OLLAMA_URL, CAPTION_MODEL, self.http_session)

            async def describe(image_b64: str) -> str:
                reply = await vision.describe(images.CAPTION_PROMPT, image_b64, images.CAPTION_TOKENS)
                return reply.text

            self.captioner = images.Captioner(
                fetch=lambda urls: images.fetch_first(self.http_session, urls),
                describe=describe,
                ready=vision.model_loaded,
            )
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
        log.info("image captions %s", f"on ({CAPTION_MODEL})" if self.captioner is not None else "off")
        if self.stream_settings is not None:
            channel = self.get_channel(self.stream_settings.channel_id)
            log.info(
                "go-live posts: %d Twitch channel(s) -> #%s",
                len(self.stream_settings.logins),
                getattr(channel, "name", "?"),
            )
        else:
            log.info("go-live posts off (%s)", self.stream_note)
        if self.gate is not None:
            log.info(
                "chime-ins on in %d server(s), %.0f%% per eligible message, at most one a day",
                len(self.gate.guilds),
                self.gate.chance * 100,
            )
        else:
            log.info("chime-ins off (%s)", self.chime_note)
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
        chiming = self.gate is not None and self.gate.allowed_here(message.channel.id, message.guild.id)
        if chiming:
            self.gate.tracker.record(message.channel.id, message.author.id, time.time())
        if message.content.startswith(self.command_prefix):
            await self.process_commands(message)
            return
        if self.addressed(message):
            await self.chat(message)
            return
        if chiming:
            await self.maybe_chime(message)

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

    def to_line(
        self, message: discord.Message, captions: dict[str, str | None] | None = None
    ) -> persona.Line | None:
        """A message as a chat line. Pictures become "[image: caption]" (or "[image]")."""
        if message.type not in CHAT_TYPES:
            return None
        names = {u.id: u.display_name for u in message.mentions}
        text = persona.clean_text(message.content, self.user.id, names)
        text = images.line_text(
            text,
            images.refs_in(message),
            captions,
            stickers=[s.name for s in message.stickers],
            has_attachments=bool(message.attachments),
        )
        if not text:
            return None
        return persona.Line(message.author.display_name, text, message.author.id == self.user.id)

    def to_lines(self, messages, captions: dict[str, str | None] | None = None) -> list[persona.Line]:
        return [line for m in messages if (line := self.to_line(m, captions)) is not None]

    async def recent_messages(self, channel, limit: int, before=None) -> list[discord.Message]:
        """The channel's last few messages, oldest first."""
        try:
            history = [m async for m in channel.history(limit=limit, before=before)]
        except discord.HTTPException:
            history = []
        history.reverse()
        return history

    async def captions(self, messages, deadline: float) -> dict[str, str | None]:
        """Captions for the pictures in these messages: the ones a reply's context shows.

        Lazy (only called while a reply or chime-in is being built), never past
        the deadline (time.monotonic()), and it never raises: whatever fails
        is just "[image]".
        """
        if self.captioner is None:
            return {}
        groups = [refs for m in messages if m.type in CHAT_TYPES and (refs := images.refs_in(m))]
        if not groups:
            return {}
        try:
            return await self.captioner.captions_for(groups, deadline - time.monotonic())
        except Exception as exc:  # noqa: BLE001 - a picture must never break a reply
            log.warning("images: %s; using [image]", type(exc).__name__)
            return {}

    async def with_embeds(self, message: discord.Message) -> discord.Message:
        """The message, with its link's image/GIF embed if Discord has added it by now.

        Discord adds a link's embed a moment after the message is created, so
        a ping that carries a Tenor link may not have it yet.
        """
        if self.captioner is None or message.embeds or not images.may_embed(message.content):
            return message
        await asyncio.sleep(EMBED_WAIT_S)
        if message.embeds:  # discord.py updates the cached message in place
            return message
        try:
            return await message.channel.fetch_message(message.id)
        except discord.HTTPException:
            return message

    async def generate(self, messages: list[dict], canned_errors: bool = True) -> str:
        """Run one reply. Errors become a canned in-character line, or "" if not canned."""
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
        if persona.leaked_reasoning(reply.text):
            log.info("llm: stripped the model's planning from the start of its reply")
        text = persona.tidy_reply(reply.text, reply.truncated)
        log.info("llm: %d chars in %.1fs", len(text), time.monotonic() - started)
        return text or (random.choice(persona.EMPTY_LINES) if canned_errors else "")

    async def reply_clears(self, text: str) -> bool:
        """The full reply check, for chime-ins only.

        The owner's rule (2026-11-19): a ping reply only goes through the slur
        filter, but an unprompted chime-in must also pass this: the model says
        whether the text has slurs, hate, sexual content or cruelty. Only an
        exact OK clears it; a timeout or error counts as not cleared.
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
                # No serious check: a direct ping always gets an answer (the
                # owner's rule, 2026-11-18). A serious-looking ping gets the
                # persona's "drop the parody, answer plainly" hint below.
                # Context for the joke: recent messages, minus any that hit the
                # serious-topic list, so it can't riff on someone's bad news.
                # Pictures in it are captioned first (at most images.BUDGET_S),
                # so a caption that hits the list keeps its line out too.
                started = time.monotonic()
                history, current = await asyncio.gather(
                    self.recent_messages(message.channel, persona.MAX_CONTEXT_MESSAGES - 1, before=message),
                    self.with_embeds(message),
                )
                captions = await self.captions(history + [current], started + images.BUDGET_S)
                trigger = self.to_line(current, captions) or trigger
                lines = context_without_serious(self.to_lines(history, captions)) + [trigger]
                lines = focus(lines, is_reply=message.reference is not None)
                prompt = persona.build_chat_messages(
                    lines, serious_hint=safety.is_serious([trigger.text])
                )
                text = await self.generate(prompt)
                # A ping reply is filtered for slurs and prompt leaks, nothing
                # else (the owner's rules, 2026-11-19). The full reply check is
                # for chime-ins.
                if text not in persona.CANNED_LINES:
                    if safety.has_slur(text):
                        log.info("chat: reply had a slur; sent a held line")
                        text = random.choice(persona.HELD_LINES)
                    elif safety.echoes_prompt(text, persona.prompt_texts()):
                        log.info("chat: reply repeated the persona prompt; sent a decoy line")
                        text = random.choice(persona.LEAK_LINES)
        finally:
            self.waiting -= 1
        await self.send(message.channel, text, message)

    # --- unprompted chime-ins ---------------------------------------------

    async def maybe_chime(self, message: discord.Message) -> None:
        """Rare, gated, censored chime-ins (the owner's ask, 2026-11-19).

        Every gate in chime.py must pass, and the text must then clear the slur
        filter, the prompt-leak check and the full LLM reply check. Nothing is
        posted on any failure: no canned lines, no pings.
        """
        channel = message.channel
        now = time.time()
        lines: list[persona.Line] = []

        async def recent_texts() -> list[str]:
            history = await self.recent_messages(channel, BLOCKLIST_SCAN)
            # captions only for what the model will see, the last few lines;
            # the blocklist and the classifier then see them too
            shown = [m for m in history if self.to_line(m) is not None][-persona.MAX_CONTEXT_MESSAGES:]
            captions = await self.captions(shown, time.monotonic() + images.BUDGET_S)
            lines[:] = self.to_lines(history, captions)
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
            guild_id=message.guild.id,
        )
        if not decision.ok:
            return
        async with channel.typing():
            prompt = persona.build_chat_messages(lines, direction=persona.CHIME_DIRECTION)
            text = await self.generate(prompt, canned_errors=False)
            if not text:
                log.info("chime: nothing usable generated; not posting")
                return
            if safety.has_slur(text) or safety.echoes_prompt(text, persona.prompt_texts()):
                log.info("chime: slur or prompt leak; not posting")
                return
            if not await self.reply_clears(text):
                log.info("chime: reply check did not clear; not posting")
                return
        try:
            await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            log.warning("chime: could not post (HTTP %s)", exc.status)
            return
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
    allowed = guild_ids(
        getattr(secrets, "guild_permission", None), getattr(secrets, "guild_permission2", None)
    )
    if not allowed:
        raise SystemExit("no guild IDs in secrets.py (guild_permission/guild_permission2); refusing to start")
    settings, note = stream_config(secrets)
    chimes, chime_note = chime_config(secrets, allowed)
    Nikobot(allowed, settings, note, chimes, chime_note).run(secrets.token, log_handler=None)


if __name__ == "__main__":
    main()

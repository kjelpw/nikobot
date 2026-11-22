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
- A ping reply can come with a generated image (imagine.py, the owner's ask
  2026-11-19): when the ping asks for a picture, or at image_chance otherwise.
  "Mostly SFW except where it's funny", in every channel: the request and the
  image prompt get the slur filter, and the prompt gets the leak check and an
  image check (PG-13 crude humor yes; explicit sex or nudity, sexualized real
  people, gore and hate no). One job at a time, a cooldown per person, an
  hourly cap. Chime-ins stay text-only.
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
- Lore (lore.py, the owner's ask 2026-11-19: a personality that evolves),
  only when `evolve` is on in secrets.py: once a day at a quiet hour, the idle
  model turns the last day of chat (the owner's servers, public non-NSFW
  channels, nothing serious) into a few running jokes, which ping replies and
  chime-ins get as flavor. The model's answer is untrusted and every bullet is
  checked. It never makes a reply wait: a reply cancels the update. `!lore`
  shows it, `!forget` (Manage Server only) clears it, and it never reaches
  stdout.
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
import imagine
import lore
import streams
from llm import LLMError, LLMTimeout, ModelLock, Ollama

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


@dataclass(frozen=True)
class ImageConfig:
    url: str
    chance: float


def image_config(secrets, url: str) -> tuple[ImageConfig | None, str]:
    """Image replies: the imagegen URL (IMAGEGEN_URL) and image_chance from secrets.py."""
    url = (url or "").strip()
    if not url:
        return None, "IMAGEGEN_URL is empty"
    if not url.startswith(("http://", "https://")):
        return None, "IMAGEGEN_URL isn't an http(s) URL"
    try:
        chance = float(getattr(secrets, "image_chance", imagine.DEFAULT_CHANCE))
    except (TypeError, ValueError):
        return None, "image_chance isn't a number"
    if not 0 <= chance <= imagine.MAX_CHANCE:  # also rejects NaN
        return None, f"image_chance must be from 0 to {imagine.MAX_CHANCE}"
    return ImageConfig(url, chance), "ok"


_ON = ("1", "true", "yes", "on")
_OFF = ("", "0", "false", "no", "off", "none")


def lore_config(secrets) -> tuple[bool, str]:
    """Lore (an evolving personality): `evolve` in secrets.py. Off unless it's set on."""
    raw = getattr(secrets, "evolve", None)
    value = str(raw).strip().lower() if isinstance(raw, (bool, int, str)) or raw is None else "?"
    if raw is None or value in _OFF:
        return False, "evolve is off"
    if value in _ON:
        return True, "ok"
    return False, "evolve isn't True or False"


def context_without_serious(lines: list[persona.Line]) -> list[persona.Line]:
    """Earlier messages for the joke's context, minus any on serious topics.

    Also minus the bot's own replies in another script: it once slipped into
    Arabic, and those replies in the context kept it there (2026-11-19, 2 of 5
    replies still Arabic with "Write in English" in the prompt; 0 of 5 without
    them). People's own messages always stay.
    """
    return [
        line
        for line in lines
        if not safety.is_serious([line.text]) and not (line.is_self and persona.mostly_foreign(line.text))
    ]


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


def channel_nsfw(channel) -> bool:
    """Age-restricted? (A thread follows its parent; a DM has no such flag.)"""
    check = getattr(channel, "is_nsfw", None)
    try:
        return bool(check()) if callable(check) else False
    except Exception:  # noqa: BLE001 - a missing parent and the like
        return False


def lore_channel(channel, everyone) -> bool:
    """A channel lore may learn from: not NSFW, and readable by everyone in the server.

    Lore shows up in every channel (and in !lore), so it must not carry a
    private channel's chat into public ones.
    """
    if channel_nsfw(channel) or getattr(channel, "type", None) == discord.ChannelType.private_thread:
        return False
    try:
        return bool(channel.permissions_for(everyone).view_channel)
    except Exception:  # noqa: BLE001 - categories, missing parents: not learnable
        return False


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
            "nsfw": channel_nsfw(channel),
            "author": str(message.author),
            "author_id": message.author.id,
            "name": getattr(message.author, "display_name", None),
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


def lore_here(ctx: commands.Context):
    """!lore and !forget: this server's own lore store, or None (off, a DM, not the owner's).

    Each server has its own lore and never sees another's (the owner, 2026-11-20:
    bleeding between servers "would be VERY bad").
    """
    guild_id = ctx.guild.id if ctx.guild is not None else None
    if not ip_allowed(guild_id, ctx.bot.allowed_guilds):
        return None
    return (getattr(ctx.bot, "lore_stores", None) or {}).get(guild_id)


@commands.command(name="lore", help="Show the running jokes the bot has picked up")
async def lore_command(ctx: commands.Context) -> None:
    store = lore_here(ctx)
    if store is None:
        return
    await ctx.send(lore.show(store.current()), allowed_mentions=discord.AllowedMentions.none())


@commands.command(name="forget", help="Clear the bot's lore (Manage Server only)")
async def forget_command(ctx: commands.Context) -> None:
    store = lore_here(ctx)
    if store is None:
        return
    perms = getattr(ctx.author, "guild_permissions", None)
    if not getattr(perms, "manage_guild", False):
        log.info("lore: !forget refused (no Manage Server)")
        await ctx.send(lore.NOT_ALLOWED_LINE, allowed_mentions=discord.AllowedMentions.none())
        return
    saved = store.forget(lore.local_now())
    log.info("lore: cleared by !forget%s", "" if saved else " (in memory only: its lore file is not writable)")
    line = lore.FORGOT_LINE if saved else lore.FORGOT_UNSAVED_LINE
    await ctx.send(line, allowed_mentions=discord.AllowedMentions.none())


class Nikobot(commands.Bot):
    def __init__(
        self,
        allowed_guilds: frozenset[int],
        stream_settings: StreamConfig | None = None,
        stream_note: str = "not configured",
        chime_settings: ChimeConfig | None = None,
        chime_note: str = "not configured",
        image_settings: ImageConfig | None = None,
        lore_on: bool = False,
        lore_note: str = "not configured",
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
        # a reply always gets it: the lore update gives way (llm.ModelLock)
        self.llm_lock = ModelLock()
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
        self.image_replies = imagine.Images(image_settings.url, image_settings.chance) if image_settings else None
        self.lore_note = lore_note
        # One lore per server, each learned only from that server's channels
        # and used only there (lore-<guild id>.json in the bot's volume).
        self.lore_stores: dict[int, lore.LoreStore] = {}
        self.lore_schedules: dict[int, lore.Schedule] = {}
        if lore_on:
            for guild_id in sorted(allowed_guilds):
                store = lore.LoreStore(DATA_DIR / f"lore-{guild_id}.json")
                self.lore_stores[guild_id] = store
                self.lore_schedules[guild_id] = lore.Schedule.for_store(store)
            self.add_command(lore_command)
            self.add_command(forget_command)

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
        if self.lore_stores:
            self.lore_watch.start()

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

    # --- lore: the daily update ---------------------------------------------

    @tasks.loop(minutes=lore.TICK_MINUTES)
    async def lore_watch(self) -> None:
        for guild_id, schedule in self.lore_schedules.items():  # one server at a time
            try:
                await lore.tick(
                    schedule, lore.local_now(), self.lore_idle, lambda gid=guild_id: self.lore_update(gid)
                )
            except Exception as exc:  # noqa: BLE001 - an exception would stop this loop for good
                log.warning("lore: %s", type(exc).__name__)

    @lore_watch.before_loop
    async def before_lore_watch(self) -> None:
        await self.wait_until_ready()

    async def lore_idle(self) -> bool:
        """Nobody is using the model, nobody is waiting for it, and it's already loaded."""
        if self.llm_lock.locked() or self.waiting > 0:
            return False
        try:
            return await self.llm.model_loaded()
        except Exception:  # noqa: BLE001 - unreachable counts as busy
            return False

    def lore_channels(self, guild_id: int) -> frozenset[int]:
        """The channels of this one server that lore may learn from, as Discord sees them now."""
        ids = set()
        for guild in self.guilds:
            if guild.id != guild_id or guild.id not in self.allowed_guilds:
                continue
            for channel in [*guild.channels, *guild.threads]:
                if lore_channel(channel, guild.default_role):
                    ids.add(channel.id)
        return frozenset(ids)

    async def lore_update(self, guild_id: int) -> str:
        """Read one server's last day of chat and ask the model for its new lore (lore.update).

        Only that server's messages (guild filter) from its own channels (channel
        filter): two separate fences, so nothing from another server gets in.
        """
        now = lore.local_now()
        started = time.monotonic()
        store = self.lore_stores[guild_id]
        chat = await asyncio.to_thread(
            lore.read_chat, DATA_DIR, now, frozenset({guild_id}), self.user.id,
            self.lore_channels(guild_id), store.read_since(), MESSAGE_LOG_FILES,
        )
        log.info(
            "lore: %d usable of %d message(s) in the last day, %d chars, read in %.1fs (left out: %s)",
            len(chat.entries), chat.read, chat.chars, time.monotonic() - started,
            ", ".join(f"{k} {v}" for k, v in sorted(chat.left_out.items())) or "none",
        )

        async def ask(messages: list[dict]) -> str:
            async with self.llm_lock.background():
                reply = await self.llm.chat(
                    messages, num_predict=lore.UPDATE_TOKENS, temperature=lore.UPDATE_TEMPERATURE,
                    timeout=lore.UPDATE_TIMEOUT_S,
                )
            return reply.text

        return await lore.update(store, chat, ask, now)

    def lore_for(self, guild_id: int | None, text: str | None = None) -> tuple[str, ...]:
        """This server's lore for a prompt: none when it's off, or for a serious-looking ping."""
        store = self.lore_stores.get(guild_id) if guild_id is not None else None
        if store is None or (text is not None and safety.is_serious([text])):
            return ()
        return store.current()

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
        if self.lore_stores:
            for guild_id, store in self.lore_stores.items():
                log.info("lore on in guild %s (%s)", guild_id, store.status())
        else:
            log.info("lore off (%s)", self.lore_note)
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

    async def generate(self, messages: list[dict], canned_errors: bool = True, caps=None) -> str:
        """Run one reply. Errors become a canned in-character line, or "" if not canned.

        caps is (max lines, max chars), from persona.reply_caps; the default is the widest.
        """
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
        max_lines, max_chars = caps or (persona.MAX_REPLY_LINES, persona.MAX_REPLY_CHARS)
        text = persona.tidy_reply(reply.text, reply.truncated, max_lines, max_chars)
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

    async def send(self, channel, text: str, reply_to: discord.Message) -> discord.Message | None:
        try:
            return await channel.send(text, reference=reply_to.to_reference(fail_if_not_exists=False))
        except discord.HTTPException as exc:
            log.warning("could not send message (HTTP %s)", exc.status)
            return None

    async def send_image(self, channel, reply_to: discord.Message, text=None, fp=None, filename=None):
        """For imagine.py: an image file or a short line, as a reply that pings nobody.

        Returns the sent message (for edit_image), or None.
        """
        extra = {"file": discord.File(fp, filename=filename)} if fp is not None else {}
        try:
            return await channel.send(
                text,
                reference=reply_to.to_reference(fail_if_not_exists=False),
                allowed_mentions=discord.AllowedMentions.none(),
                **extra,
            )
        except discord.HTTPException as exc:
            log.warning("image: could not send (HTTP %s)", exc.status)
            return None

    async def edit_image(self, msg: discord.Message, text=None, fp=None, filename=None) -> bool:
        """For imagine.py: turn one of the bot's messages into the picture (or a new line)."""
        changes = {"allowed_mentions": discord.AllowedMentions.none()}
        if text is not None:
            changes["content"] = text
        if fp is not None:
            changes["attachments"] = [discord.File(fp, filename=filename)]
        try:
            await msg.edit(**changes)
        except discord.HTTPException as exc:
            log.warning("image: could not edit (HTTP %s)", exc.status)
            return False
        return True

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
        asked_image = False
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
                # An asked-for picture is the whole reply: one "painting…"
                # message that becomes the picture (the owner, 2026-11-19:
                # "it replied twice"), so no text reply is written for it.
                asked_image = self.image_replies is not None and self.image_replies.asked(message, self.user.id)
                text = None
                if not asked_image:
                    voice, serious = persona.pick_voice(random), safety.is_serious([trigger.text])
                    prompt = persona.build_chat_messages(
                        lines,
                        serious_hint=serious,
                        voice=voice,
                        lore=self.lore_for(message.guild.id, trigger.text),  # none on a serious-looking ping
                    )
                    text = await self.generate(prompt, caps=persona.reply_caps(voice, serious))
                # A ping reply is filtered for slurs and prompt leaks, nothing
                # else (the owner's rules, 2026-11-19). The full reply check is
                # for chime-ins.
                if text is not None and text not in persona.CANNED_LINES:
                    if safety.has_slur(text):
                        log.info("chat: reply had a slur; sent a held line")
                        text = random.choice(persona.HELD_LINES)
                    elif safety.echoes_prompt(text, persona.prompt_texts()):
                        log.info("chat: reply repeated the persona prompt; sent a decoy line")
                        text = random.choice(persona.LEAK_LINES)
        finally:
            self.waiting -= 1
        if asked_image:
            await self.image_replies.follow_up(self, message, lines, None)
            return
        sent = await self.send(message.channel, text, message)
        if self.image_replies is not None:  # now and then a picture, attached to that reply
            await self.image_replies.follow_up(self, message, lines, text, reply_msg=sent)

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
            voice = persona.pick_voice(random)
            prompt = persona.build_chat_messages(
                lines, direction=persona.CHIME_DIRECTION, voice=voice, lore=self.lore_for(message.guild.id),
            )
            text = await self.generate(prompt, canned_errors=False, caps=persona.reply_caps(voice))
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
    replies, replies_note = image_config(secrets, imagine.IMAGEGEN_URL)
    lore_on, lore_note = lore_config(secrets)
    if replies is not None:
        log.info("image replies on: when asked, and %.0f%% of other ping replies", replies.chance * 100)
    else:
        log.info("image replies off (%s)", replies_note)
    Nikobot(allowed, settings, note, chimes, chime_note, replies, lore_on, lore_note).run(
        secrets.token, log_handler=None
    )


if __name__ == "__main__":
    main()

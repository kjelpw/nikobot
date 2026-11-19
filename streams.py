"""Go-live posts: when one of the configured Twitch channels starts streaming,
post once in the configured Discord channel.

The one exception to "only speaks when asked" (the owner's request, 2026-11-18).
It is a fixed template, never model output, so nothing the LLM writes is ever
posted unprompted.

Twitch is asked directly (Helix "Get Streams", an app token from the client
credentials flow). Discord's purple "Streaming" status was not used: it needs
Streamer Mode and a linked account, misses non-affiliates, and can show while
nobody is live.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import aiohttp

log = logging.getLogger("nikobot.streams")

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
STREAMS_URL = "https://api.twitch.tv/helix/streams"
HTTP_TIMEOUT_S = 15
# A new stream within this long of the last time we saw them live is a
# reconnect (stream crashed, OBS restarted), not a new stream: no second post.
REJOIN_GAP_S = 60 * 60
MAX_LOGINS = 100  # one Helix request takes up to 100 user_login values
TITLE_CHARS = 140
GAME_CHARS = 60

# Twitch logins: 4-25 letters, digits and underscores (a few legacy ones are 3).
_LOGIN = re.compile(r"^[a-z0-9_]{3,25}$")

INTROS = (
    "Certainly! 🚀 **{name}** has embarked on a journey. It's not just a stream — it's a tapestry.",
    "Great question! 🎥 **{name}** is live. The result? Pure synergy. ✨",
    "Breaking: **{name}** is delving into the vibrant realm of streaming. 🚀",
    "As an AI language model, I can confirm **{name}** is live, and it's a game-changer. 🎯",
    "In today's fast-paced world, **{name}** went live. Let's delve in. ✨",
    "**{name}** is live — leveraging content to unlock the potential of your evening. 💡",
)
PLAIN_INTRO = "**{name}** is live on Twitch."


class TwitchError(Exception):
    pass


@dataclass(frozen=True)
class Stream:
    login: str
    name: str
    title: str
    game: str
    stream_id: str

    @property
    def url(self) -> str:
        return f"https://www.twitch.tv/{self.login}"


def parse_logins(values: Iterable[str] | str | None) -> tuple[str, ...]:
    """Configured Twitch logins: lowercased, deduplicated, junk dropped.

    Accepts a list, or a comma/space separated string; full twitch.tv URLs too.
    """
    if values is None:
        return ()
    if isinstance(values, str):
        values = re.split(r"[\s,]+", values)
    out: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        login = value.strip().lower().rstrip("/")
        login = re.sub(r"^(?:https?://)?(?:www\.)?twitch\.tv/", "", login)
        if _LOGIN.match(login) and login not in out:
            out.append(login)
    return tuple(out[:MAX_LOGINS])


def stream_from_api(item: dict) -> Stream | None:
    """One Helix stream object, or None if it isn't a usable live stream."""
    login = str(item.get("user_login") or "").lower()
    stream_id = str(item.get("id") or "")
    if item.get("type") != "live" or not _LOGIN.match(login) or not stream_id:
        return None
    return Stream(
        login=login,
        name=str(item.get("user_name") or login),
        title=str(item.get("title") or ""),
        game=str(item.get("game_name") or ""),
        stream_id=stream_id,
    )


class Twitch:
    """Just enough of Helix: an app token and "which of these are live"."""

    def __init__(self, client_id: str, client_secret: str, session: aiohttp.ClientSession):
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = session
        self._token: str | None = None
        self._token_expires = 0.0

    async def _app_token(self, force: bool = False) -> str:
        if not force and self._token and time.time() < self._token_expires - 600:
            return self._token
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }
        try:
            # form body, not query string: the secret never sits in a URL that
            # could end up in an exception or log line
            async with self.session.post(
                TOKEN_URL, data=params, timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
            ) as resp:
                if resp.status != 200:
                    # 400/403 here means a wrong client ID or secret
                    raise TwitchError(f"token: HTTP {resp.status}")
                data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise TwitchError(f"token: {type(exc).__name__}") from exc
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise TwitchError("token: no access_token in reply")
        self._token = token
        self._token_expires = time.time() + float(data.get("expires_in") or 3600)
        return token

    async def live(self, logins: tuple[str, ...]) -> dict[str, Stream]:
        """login -> Stream for every configured login that is live right now."""
        if not logins:
            return {}
        params = [("user_login", login) for login in logins[:MAX_LOGINS]]
        params += [("type", "live"), ("first", "100")]
        for attempt in (1, 2):
            token = await self._app_token(force=attempt == 2)
            headers = {"Client-Id": self.client_id, "Authorization": f"Bearer {token}"}
            try:
                async with self.session.get(
                    STREAMS_URL,
                    params=params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S),
                ) as resp:
                    if resp.status == 401 and attempt == 1:
                        continue  # token expired or revoked: get a new one, once
                    if resp.status != 200:
                        raise TwitchError(f"streams: HTTP {resp.status}")
                    data = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise TwitchError(f"streams: {type(exc).__name__}") from exc
            wanted = set(logins)
            out = {}
            for item in data.get("data") or []:
                stream = stream_from_api(item) if isinstance(item, dict) else None
                if stream is not None and stream.login in wanted:
                    out[stream.login] = stream
            return out
        raise TwitchError("streams: still unauthorized after a new token")


class StreamState:
    """Per login: the last stream ID we handled and when we last saw them live.

    Persisted, so a restart never posts the same stream twice. Fails closed: if
    the file can't be written, nothing is posted (a crash loop could otherwise
    post on every restart).
    """

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.seen: dict[str, dict] = {}
        self.writable = True
        # after a corrupt file, the first poll only records who is live
        self.quiet_next = False
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
            seen = {}
            for login, rec in (data.get("seen") or {}).items():
                last_live = float(rec["last_live"])
                if not math.isfinite(last_live):
                    raise ValueError("non-finite timestamp")
                seen[str(login)] = {"stream_id": str(rec["stream_id"]), "last_live": last_live}
            self.seen = seen
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            # Corrupt: treat everyone as just seen live, so nothing that is live
            # right now is (re)posted. Real new streams later still are.
            log.warning("stream state unreadable; starting fresh without posting current streams")
            self.seen = {}
            self.quiet_next = True
        self.writable = self.save()

    def save(self) -> bool:
        payload = json.dumps({"seen": self.seen}, sort_keys=True)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".streams-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(payload)
                os.replace(tmp, self.path)
            except BaseException:
                os.unlink(tmp)
                raise
        except OSError as exc:
            log.warning("stream state not writable (%s); go-live posts disabled", type(exc).__name__)
            self.writable = False
            return False
        self.writable = True
        return True

    def update(self, live: dict[str, Stream], now: float) -> list[Stream]:
        """Record this poll and return the streams to post about.

        Only call with a successful poll: a failed poll is "unknown", not
        "everyone went offline".
        """
        quiet, self.quiet_next = self.quiet_next, False
        new: list[Stream] = []
        for login, stream in sorted(live.items()):
            rec = self.seen.get(login)
            if rec is not None and rec["stream_id"] == stream.stream_id:
                rec["last_live"] = now
                continue
            rejoin = rec is not None and now - rec["last_live"] < REJOIN_GAP_S
            self.seen[login] = {"stream_id": stream.stream_id, "last_live": now}
            if not rejoin and not quiet:
                new.append(stream)
        if not self.save():
            return []
        return new


def _escape(text: str) -> str:
    """Neutralise Discord markdown and mentions in Twitch-supplied text."""
    import discord  # local: keeps this module importable without discord for tests

    text = discord.utils.escape_markdown(text)
    return discord.utils.escape_mentions(text)


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def announcement(stream: Stream, serious: bool, rng: random.Random | None = None) -> str:
    """The go-live post. Plain (no parody) when the title looks serious."""
    rng = rng or random
    name = _escape(_clip(stream.name, 40))
    intro = (PLAIN_INTRO if serious else rng.choice(INTROS)).format(name=name)
    details = " · ".join(
        _escape(_clip(part, limit))
        for part, limit in ((stream.title, TITLE_CHARS), (stream.game, GAME_CHARS))
        if part.strip()
    )
    lines = ["🔴 " + intro]
    if details:
        lines.append("> " + details)
    lines.append(stream.url)  # bare link, so Discord shows the Twitch preview
    return "\n".join(lines)

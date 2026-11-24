"""History: each server's last two years of chat, for the remix voice and the lore seed.

The owner, 2026-11-23: "You can go through message history in discord to
quickly build up the lore files too", and "last 2 years" for how far back.
The live message log only goes back to 2026-11-18 (a few hundred messages),
far too little for remix.py to stitch from.

- One file per server, /data/history-<guild id>.jsonl, in the message log's
  JSON format (bot.message_dict) plus the message id. A server's file is only
  ever written with that server's messages, and every read checks the server
  again, so nothing crosses between servers (the owner, 2026-11-20).
- Which channels (bot.remix_channel): every channel of that server the bot can
  read, role-gated and private ones too (the owner, 2026-11-23: "All channels
  mix"), NSFW ones only in the servers in lore_nsfw_guilds, never private
  threads. Lore still reads only the public ones (its own channel filter).
  Bots (this one too) and webhooks are not kept.
- The backfill runs in the background, newest messages first, one channel at
  a time. Progress is saved per channel in history-<guild id>.state.json, so
  a restart carries on where it stopped, and a finished channel is never
  fetched again; each start only fetches channels it hasn't finished (new
  ones, or ones the fence newly allows). New messages are appended live
  (bot.on_message).
- Logs carry counts only, never content.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

import discord

log = logging.getLogger("nikobot.history")

WINDOW = timedelta(days=2 * 365)  # the owner: "last 2 years"
BATCH = 500  # records written (and progress saved) per batch
PAUSE_S = 1.0  # between batches; discord.py also waits out any rate limit


def corpus_path(directory: Path, guild_id: int) -> Path:
    return Path(directory) / f"history-{int(guild_id)}.jsonl"


def state_path(directory: Path, guild_id: int) -> Path:
    return Path(directory) / f"history-{int(guild_id)}.state.json"


def cutoff(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) - WINDOW


def keep(record: dict | None, guild_id: int) -> bool:
    """Worth storing for this server: its own message, from a person, with something in it."""
    if not isinstance(record, dict) or record.get("guild_id") != guild_id:
        return False
    if record.get("webhook") or record.get("bot"):
        return False  # every bot, this one too: its old replies are the LLM voice remix replaces
    return bool((record.get("content") or "").strip() or record.get("attachments"))


def append(path: Path, records: Iterable[dict]) -> int:
    lines = [json.dumps(r, ensure_ascii=False) + "\n" for r in records]
    if not lines:
        return 0
    with open(path, "a", encoding="utf-8") as f:
        f.writelines(lines)
    return len(lines)


def _when(value) -> datetime | None:
    try:
        at = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo is not None else None


def read(path: Path, guild_id: int, since: datetime | None = None, until: datetime | None = None) -> list[dict]:
    """This server's records from the file, deduplicated by message id, newest first.

    Checks the server on every record: a record from anywhere else is dropped.
    """
    found: dict[object, tuple[datetime, dict]] = {}
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    except OSError as exc:
        log.warning("history: can't read a history file (%s)", type(exc).__name__)
        return []
    with handle:
        for n, raw in enumerate(handle):
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(rec, dict) or rec.get("guild_id") != guild_id:
                continue
            at = _when(rec.get("at"))
            if at is None or (since is not None and at < since) or (until is not None and at >= until):
                continue
            found[rec.get("id") or ("line", n)] = (at, rec)
    return [rec for _, rec in sorted(found.values(), key=lambda pair: pair[0], reverse=True)]


def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".history-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@dataclass
class BackfillState:
    """Per channel: the oldest message id fetched so far, whether it's finished, and a count."""

    path: Path
    channels: dict[str, dict] = field(default_factory=dict)
    done: bool = False

    @classmethod
    def load(cls, path: Path) -> "BackfillState":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(Path(path))
        except (OSError, ValueError) as exc:
            log.warning("history: progress file unreadable (%s); starting over", type(exc).__name__)
            return cls(Path(path))
        channels = data.get("channels") if isinstance(data, dict) else None
        return cls(Path(path), channels if isinstance(channels, dict) else {}, bool(data.get("done")))

    def save(self) -> None:
        try:
            _atomic_write(self.path, json.dumps({"done": self.done, "channels": self.channels}).encode())
        except OSError as exc:
            log.warning("history: can't save progress (%s)", type(exc).__name__)

    def channel(self, channel_id: int) -> dict:
        return self.channels.setdefault(str(channel_id), {"before": None, "done": False, "count": 0})

    @property
    def count(self) -> int:
        return sum(int(c.get("count") or 0) for c in self.channels.values())


async def backfill_channel(channel, state: BackfillState, corpus: Path, since: datetime,
                           to_record: Callable[[object], dict | None], guild_id: int,
                           pause: Callable[[], object] | None = None) -> str:
    """Fetch one channel's history (newest first) into the corpus. Returns what happened.

    "done" when it reached `since` or the channel's start, "forbidden" when the
    bot can't read it (counted as done), "error" to try again later.
    """
    entry = state.channel(channel.id)
    if entry.get("done"):
        return "done"
    before = discord.Object(id=entry["before"]) if entry.get("before") else None
    batch: list[dict] = []

    def flush() -> None:
        entry["count"] = int(entry.get("count") or 0) + append(corpus, batch)
        batch.clear()
        state.save()

    try:
        async for message in channel.history(limit=None, before=before, after=since, oldest_first=False):
            record = to_record(message)
            if keep(record, guild_id):
                batch.append(record)
            entry["before"] = message.id
            if len(batch) >= BATCH:
                flush()
                if pause is not None:
                    await pause()
    except discord.Forbidden:
        entry["done"] = True
        entry["skipped"] = "forbidden"
        flush()
        return "forbidden"
    except (discord.HTTPException, OSError) as exc:
        log.warning("history: a channel's history failed (%s); will retry", type(exc).__name__)
        flush()
        return "error"
    entry["done"] = True
    flush()
    return "done"

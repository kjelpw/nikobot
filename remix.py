"""Remix: replies stitched together from the server's own chat, the way cutebot talks.

The owner, 2026-11-23: the LLM's jokes still come off "as cringe reddit
millenial rather than actually funny", with cutebot (a friend's bot) as the
model of funny: "never taunt me....im sensitive 👉👈", "Its astounding
honestly", a replayed cat picture, and a stitched-up run-on about input lag,
button mappings and feet. The owner picked "remix the server's chat" over
retuning the LLM.

Three kinds of reply, all from one server's history (history.py), never another's:
- stitch: a real line that jumps into another real line at a shared word,
  one to three times. It ends where the last line ended, so it ends naturally.
- replay: a short real line, as is.
- reaction: a GIF link someone posted (from NSFW channels too, where they're allowed).
Pictures are never re-posted as they were. The server's pictures (non-NSFW
channels only) are kept as sources for imagine.py, which remixes one with the
image model (the owner, 2026-11-23: "nikobots images should be remixed images").

What goes in (clean_line): no bots, no commands, nothing that hits the
serious-topic list, the crisis list or the slur filter, no emails or
phone-like numbers, no code blocks. Mentions become plain names (nobody is
pinged; the bot's allowed_mentions forbid it anyway), links go (GIF links are
kept apart as reactions), the server's custom emoji stay.

Pure: no Discord, no network, so it is unit tested. Memory stays small (the
container has 256 MB): lines as strings plus a word -> line-id index, capped
at MAX_LINES lines per server.
"""
from __future__ import annotations

import json
import logging
import math
import re
import string
from array import array
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import persona
import safety

log = logging.getLogger("nikobot.remix")

# --- the mix (stitch takes the rest) -----------------------------------------------
REPLAY_SHARE = 0.28
REACTION_SHARE = 0.12
TOPIC_SHARE = 0.7  # how often a reply starts from a word in the ping, when it can
# "Slightly weight the messages towards something that makes more sense rather
# than just pulling random" (the owner, 2026-11-23): a few candidates are made
# and one is drawn with weight exp(score), the score counting words shared with
# the ping and smooth joins (two words overlap where it jumps). Still a draw,
# never the single best.
CANDIDATES = 6
RELEVANCE_WEIGHT = 1.0  # per word shared with the ping (at most 3 count)
SMOOTH_WEIGHT = 0.7  # per two-word join
SPLICE_COST = 0.4  # per jump past the first
LONG_WORDS = 20  # longer than this costs a little
JOIN_LOOKS = 12  # lines looked at for a two-word join at each jump
# Emoji reactions (bot.maybe_react, the owner 2026-11-23: "it should also
# sometimes react to messages ... a separate roll"): the server's own emoji,
# preferring ones used next to the message's words.
RELATED_EMOJI_SHARE = 0.7
TOP_EMOJI = 15

# --- sizes ----------------------------------------------------------------------------
MAX_LINES = 60_000  # most recent usable lines kept per server
MIN_LINES = 200  # fewer: not ready, the LLM answers instead
MAX_LINE_WORDS = 40
MAX_WORDS = 30  # a stitched reply's cap (cutebot's long one was ~35)
SHORT_WORDS = 8  # a replay is at most this long
# Fewer GIFs than this: no reactions, or the same one keeps coming back (live
# 2026-11-23: Ⅶ had one reaction picture in two years and 4 GIFs).
MIN_REACTIONS = 20
MAX_SPLICES = 3
TRIES = 8
COMMON_SHARE = 0.02  # a ping word in more lines than this is too common to be a topic

_USER_MENTION = re.compile(r"<@!?(\d+)>")
_OTHER_MENTION = re.compile(r"<@&\d+>|<#\d+>|@(?:everyone|here)\b")
# Discord's GIF picker moved from Tenor to Klipy in 2026 (Tenor's API shut down on
# 2026-06-30), so newer reaction GIFs are klipy.com/gifs/... links (42 in Ⅶ by 2026-11-23).
# Only links people posted are replayed: no Klipy API calls (its terms want a
# bot's server-side requests approved first).
_GIF_LINK = re.compile(
    r"https?://(?:www\.)?(?:tenor\.com/view/|media\d*\.tenor\.com/|c\.tenor\.com/|giphy\.com/gifs/"
    r"|media\d*\.giphy\.com/|klipy\.com/gifs/|static\.klipy\.com/)[^\s<>]+",
    re.IGNORECASE,
)
_COMMAND = re.compile(r"^\s*[!/$?;+\-.]\w")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_PHONE = re.compile(r"\d[\d\s().-]{7,}\d")  # 9+ digits-ish: phone numbers, IDs, card numbers
GRID_SQUARES = frozenset(chr(c) for c in range(0x1F7E0, 0x1F7EC)) | {"⬛", "⬜"}
_CUSTOM_EMOJI_CODE = re.compile(r"<a?:\w{2,32}:\d{15,21}>")
_IMAGE_URL = re.compile(r"\.(?:png|jpe?g|gif|webp)(?:\?|$)", re.IGNORECASE)
_SPACES = re.compile(r"\s+")
_EMOJI_PART = r"[\u2600-\u27BF\U0001F300-\U0001FAFF][\uFE0F\U0001F3FB-\U0001F3FF]?"
EMOJI = re.compile(
    rf"<a?:\w{{2,32}}:\d{{15,21}}>|[\U0001F1E6-\U0001F1FF]{{2}}|{_EMOJI_PART}(?:\u200D{_EMOJI_PART})*"
)
_PUNCT = string.punctuation + "“”‘’…"
_STOP = frozenset(
    "a an the i im i'm me my you your u ur he she it its it's we they them is are was were be been am do does did "
    "to of in on at for and or but so if not no yes ok okay lol lmao that this what who how why when where with "
    "just like get got go going have has had can could would should will gonna wanna there here then than too "
    "very really about from up out one all some any".split()
)


def key(token: str) -> str:
    """A word as the index sees it: lowercase, without the punctuation around it."""
    return token.lower().strip(_PUNCT)


def gif_link(content: str | None) -> str | None:
    """The GIF link when a message is nothing but one (a reaction GIF), else None."""
    text = (content or "").strip()
    m = _GIF_LINK.fullmatch(text)
    return m.group(0) if m else None


def clean_line(content: str | None, names: dict[int, str] | None = None) -> str:
    """One message as a remixable line, or "" when it can't be one."""
    text = content or ""
    if not text.strip() or _COMMAND.match(text) or "```" in text:
        return ""
    names = names or {}
    text = _USER_MENTION.sub(lambda m: names.get(int(m.group(1)), ""), text)
    text = _OTHER_MENTION.sub("", text)
    text = persona.strip_links(text)
    text = _SPACES.sub(" ", text).strip()
    probe = _CUSTOM_EMOJI_CODE.sub(" ", text)  # a custom emoji's 18-digit id isn't a phone number
    if not text or _EMAIL.search(probe) or _PHONE.search(probe):
        return ""
    if safety.is_crisis(text) or safety.is_serious([text]) or safety.has_slur(text):
        return ""
    if len(text.split()) > MAX_LINE_WORDS:
        return ""
    return text


@dataclass(frozen=True)
class Reply:
    kind: str  # "stitch", "replay" or "gif"
    text: str | None = None


@dataclass
class Remix:
    """One server's remix material. Build it with build(); add() takes live messages."""

    guild_id: int
    lines: list[str] = field(default_factory=list)
    index: dict[str, array] = field(default_factory=dict)
    short: array = field(default_factory=lambda: array("I"))  # ids of replayable lines
    gifs: list[str] = field(default_factory=list)
    emoji: Counter = field(default_factory=Counter)  # emoji -> times used in chat
    emoji_near: dict[str, Counter] = field(default_factory=dict)  # word -> emoji used in its lines
    images: list[tuple[int, int]] = field(default_factory=list)  # (channel, message): remix sources

    @property
    def ready(self) -> bool:
        return len(self.lines) >= MIN_LINES

    def _add_line(self, text: str) -> None:
        line_id = len(self.lines)
        self.lines.append(text)
        for k in {key(t) for t in text.split()} - {""}:
            self.index.setdefault(k, array("I")).append(line_id)
        if len(text.split()) <= SHORT_WORDS:
            self.short.append(line_id)
        # each emoji once per line, and no game-grid squares (Wordle results made 🟩 the
        # server's "favourite" emoji, 2026-11-23)
        found = sorted(set(EMOJI.findall(text)) - GRID_SQUARES)
        if found:
            self.emoji.update(found)
            for w in content_words(text):
                self.emoji_near.setdefault(w, Counter()).update(found)

    def add(self, record: dict, names: dict[int, str] | None = None, nsfw_ok: bool = False) -> bool:
        """Take one message record (history.py / the message log format). True if it was used."""
        if not usable(record, self.guild_id, nsfw_ok):
            return False
        content = record.get("content") or ""
        gif = gif_link(content)
        if gif is not None:
            # A GIF link is public Tenor/GIPHY content, so it counts wherever chat
            # does (NSFW channels only where allowed: usable() above). Ⅶ's chat is
            # nearly all in NSFW channels: 281 GIF links there, 4 elsewhere (2026-11-23).
            self.gifs.append(gif)
            return True
        used = False
        pictures = [u for u in record.get("attachments") or () if isinstance(u, str) and _IMAGE_URL.search(u)]
        if (pictures and record.get("id") and not record.get("nsfw")
                and (not content.strip() or clean_line(content, names))):
            self.images.append((int(record["channel_id"]), int(record["id"])))
            used = True
        text = clean_line(content, names)
        if text:
            self._add_line(text)
            used = True
        return used

    @classmethod
    def build(cls, records: list[dict], guild_id: int, nsfw_ok: bool = False) -> "Remix":
        """From records newest first (history.read): up to MAX_LINES lines, newest first."""
        names = names_in(records)
        remix = cls(guild_id)
        for rec in records:
            if len(remix.lines) >= MAX_LINES:
                break
            remix.add(rec, names, nsfw_ok)
        return remix

    @classmethod
    def load(cls, path: Path, guild_id: int, nsfw_ok: bool = False) -> "Remix":
        """From a history file, in two streaming passes so a big server never sits in memory whole.

        Pass one notes each usable record's time and the display names; pass
        two adds the ones at or after the MAX_LINES-th newest time, each message
        id once. (The file isn't in time order: the backfill goes channel by
        channel, and live messages are appended.)
        """
        stamps, names = [], {}
        for rec in _records(path, guild_id):
            if usable(rec, guild_id, nsfw_ok) and isinstance(rec.get("at"), str):
                stamps.append(f"{rec['at']} {rec.get('id')}")  # a resumed batch can repeat a message
                if rec.get("author_id") is not None and rec.get("name"):
                    names[rec["author_id"]] = str(rec["name"])
        stamps = sorted(set(stamps), reverse=True)  # ISO times in UTC sort as text
        since = stamps[min(len(stamps), MAX_LINES) - 1].split(" ")[0] if stamps else ""
        del stamps
        remix, seen = cls(guild_id), set()
        for rec in _records(path, guild_id):
            if not isinstance(rec.get("at"), str) or rec["at"] < since or rec.get("id") in seen:
                continue
            if rec.get("id") is not None:
                seen.add(rec["id"])
            remix.add(rec, names, nsfw_ok)
        return remix

    # --- making a reply -------------------------------------------------------------

    def topic(self, ping: str | None, rng) -> str | None:
        """A word from the ping to start from: in the index, not a stopword, not too common."""
        limit = max(10, int(len(self.lines) * COMMON_SHARE))
        words = [k for k in {key(t) for t in (ping or "").split()} if k and k not in _STOP and len(k) > 1]
        found = [k for k in words if 0 < len(self.index.get(k, ())) <= limit]
        return rng.choice(sorted(found)) if found else None

    def reply(self, ping: str | None, rng, reactions: bool = True) -> Reply | None:
        """A reply to a ping, or None when there isn't enough material."""
        if not self.ready:
            return None
        roll = rng.random()
        if reactions and roll < REACTION_SHARE and len(self.gifs) >= MIN_REACTIONS:
            return Reply("gif", text=rng.choice(self.gifs))
        topic = self.topic(ping, rng) if rng.random() < TOPIC_SHARE else None
        if roll < REACTION_SHARE + REPLAY_SHARE:
            text = self.replay(topic, rng, ping)
            if text:
                return Reply("replay", text=text)
        text = self.stitch(topic, rng, ping)
        return Reply("stitch", text=text) if text else Reply("replay", text=self.replay(None, rng, ping))

    def replay(self, topic: str | None, rng, ping: str | None = None) -> str | None:
        """A short real line, drawn with a lean toward ones that share words with the ping."""
        if not self.short:
            return None
        wanted = content_words(ping)
        pool: set[int] = set()
        for w in ([topic] if topic else []) + sorted(wanted):
            ids = self.index.get(w, ())
            for _ in range(min(len(ids), 8)):
                i = ids[rng.randrange(len(ids))]
                if len(self.lines[i].split()) <= SHORT_WORDS:
                    pool.add(i)
        pool.update(self.short[rng.randrange(len(self.short))] for _ in range(CANDIDATES))
        ids = sorted(pool)
        weights = [math.exp(RELEVANCE_WEIGHT * min(3, len(content_words(self.lines[i]) & wanted))) for i in ids]
        return self.lines[rng.choices(ids, weights)[0]]

    def stitch(self, topic: str | None, rng, ping: str | None = None) -> str | None:
        """A line that jumps into other lines at shared words, drawn from a few with a lean
        toward ones that share words with the ping and join smoothly. None if none jumped."""
        wanted = content_words(ping)
        found = [c for c in (self._stitch_once(topic, rng) for _ in range(CANDIDATES)) if c is not None]
        if not found:
            return None
        weights = [math.exp(self._score(text, smooth, jumps, wanted)) for text, smooth, jumps in found]
        return rng.choices(found, weights)[0][0]

    @staticmethod
    def _score(text: str, smooth: int, jumps: int, wanted: set[str]) -> float:
        return (RELEVANCE_WEIGHT * min(3, len(content_words(text) & wanted)) + SMOOTH_WEIGHT * smooth
                - SPLICE_COST * max(0, jumps - 1) - 0.5 * (len(text.split()) > LONG_WORDS))

    def _join(self, current: list[str], i: int, used: set[int], rng) -> tuple[int, int, bool] | None:
        """Where to jump from current[i]: (line, position, smooth). Smooth means the word
        before matches too, so the join reads like a two-word overlap."""
        k = key(current[i])
        ids = self.index.get(k)
        if not ids or len(ids) < 2:
            return None
        before = key(current[i - 1]) if i > 0 else None
        plain = None
        for _ in range(JOIN_LOOKS):
            other = ids[rng.randrange(len(ids))]
            if other in used:
                continue
            words = self.lines[other].split()
            spots = [j for j, t in enumerate(words) if key(t) == k]
            if not spots:
                continue
            smooth = [j for j in spots if j > 0 and key(words[j - 1]) == before]
            if smooth:
                return other, rng.choice(smooth), True
            if plain is None:
                plain = (other, rng.choice(spots), False)
        return plain

    def _stitch_once(self, topic: str | None, rng) -> tuple[str, int, int] | None:
        """One stitched line: (text, smooth joins, jumps), or None."""
        for _ in range(TRIES):
            if topic is not None and self.index.get(topic):
                ids = self.index[topic]
                start = ids[rng.randrange(len(ids))]
            else:
                start = rng.randrange(len(self.lines))
            words = self.lines[start].split()
            if len(words) < 2:
                continue
            used, out, current, smooth = {start}, [], words, 0
            for _ in range(rng.randint(1, MAX_SPLICES)):
                cuts = [i for i in range(1, len(current)) if len(self.index.get(key(current[i]), ())) > 1]
                rng.shuffle(cuts)
                jumped = False
                for i in cuts[:4]:
                    join = self._join(current, i, used, rng)
                    if join is None:
                        continue
                    other, j, was_smooth = join
                    out.extend(current[:i])
                    current = self.lines[other].split()[j:]
                    used.add(other)
                    smooth += was_smooth
                    jumped = True
                    break
                if not jumped or len(out) >= MAX_WORDS:
                    break
            out.extend(current)
            text = " ".join(_trim(out, MAX_WORDS))
            if len(used) < 2 or any(text == self.lines[u] for u in used):
                continue  # never jumped, or jumped between copies of one line ("lol", "same")
            return text, smooth, len(used) - 1
        return None

    # --- reactions ----------------------------------------------------------------------

    def react_emoji(self, text: str | None, rng) -> str | None:
        """An emoji this server uses, leaning toward ones used next to the message's words."""
        if not self.emoji:
            return None
        near = Counter()
        for w in content_words(text):
            near.update(self.emoji_near.get(w, {}))
        pool = near if near and rng.random() < RELATED_EMOJI_SHARE else Counter(dict(self.emoji.most_common(TOP_EMOJI)))
        emoji = sorted(pool)
        return rng.choices(emoji, [pool[e] for e in emoji])[0]


def content_words(text: str | None) -> set[str]:
    """The words that carry meaning: indexed form, no stopwords, longer than two letters."""
    return {k for k in (key(t) for t in (text or "").split()) if len(k) > 2 and k not in _STOP}


def _trim(words: list[str], limit: int) -> list[str]:
    """At most `limit` words, ending on a sentence end when one is in the last third."""
    if len(words) <= limit:
        return words
    cut = words[:limit]
    for i in range(limit - 1, limit * 2 // 3, -1):
        if cut[i][-1:] in ".!?…":
            return cut[: i + 1]
    return cut


def usable(record: dict, guild_id: int, nsfw_ok: bool) -> bool:
    """A person's message from this server (and its NSFW channels only when allowed)."""
    if not isinstance(record, dict) or record.get("guild_id") != guild_id:
        return False
    if record.get("bot") or record.get("webhook"):
        return False
    if record.get("nsfw") and not nsfw_ok:
        return False
    return True


def names_in(records: list[dict]) -> dict[int, str]:
    """author id -> display name, the newest name winning (records newest first).

    People only: a bot's mention (pings to this one, mostly) is dropped, not named.
    """
    names: dict[int, str] = {}
    for rec in reversed(records):
        if rec.get("author_id") is not None and rec.get("name") and not rec.get("bot"):
            names[rec["author_id"]] = str(rec["name"])
    return names


def _records(path: Path, guild_id: int):
    """This server's records from a history file, one at a time; anything else is skipped."""
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return
    except OSError as exc:
        log.warning("remix: can't read the history file (%s)", type(exc).__name__)
        return
    with handle:
        for raw in handle:
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("guild_id") == guild_id:
                yield rec

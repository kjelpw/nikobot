"""Gates for unprompted chime-ins. Every gate must pass, and every failure is a no.

Order is cheapest first: allowlist, hush, daily cap, banter, dice, then (only
for the rare survivor) the blocklist on recent messages, a check that the model
is already loaded, and finally the LLM classifier.

The owner's rule (2026-11-19): chime-ins are censored. Whatever text a chime-in
would post must pass both safety.has_slur and the full LLM reply check
(Nikobot.reply_clears) first. Ping replies only get the slur filter.
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from safety import is_serious

log = logging.getLogger("nikobot.chime")

DAY = 24 * 60 * 60


def parse_channel_ids(raw: str | None) -> frozenset[int]:
    """NIKOBOT_CHIME_CHANNELS: comma-separated channel IDs. Junk is ignored."""
    out = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return frozenset(out)


class ChimeState:
    """Persisted timestamps: the last chime-in and the !hush expiry.

    Fails closed: if the file is corrupt the cap restarts from now, and if it
    cannot be written chime-ins are disabled until restart.
    """

    def __init__(self, path: str | os.PathLike, now: float | None = None):
        self.path = Path(path)
        self.last_chime = 0.0
        self.hush_until = 0.0
        self.writable = True
        self._load(time.time() if now is None else now)

    def _load(self, now: float) -> None:
        try:
            data = json.loads(self.path.read_text())
            last_chime = float(data.get("last_chime", 0.0))
            hush_until = float(data.get("hush_until", 0.0))
            if not (math.isfinite(last_chime) and math.isfinite(hush_until)):
                raise ValueError("non-finite timestamp")
            self.last_chime, self.hush_until = last_chime, hush_until
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, AttributeError):
            log.warning("chime state unreadable; treating the daily cap as just used")
            self.last_chime = now
        # probe writability now, so a read-only /data disables chimes up front
        self.save()

    def save(self) -> bool:
        payload = json.dumps({"last_chime": self.last_chime, "hush_until": self.hush_until})
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".chime-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(payload)
                os.replace(tmp, self.path)
            except BaseException:
                os.unlink(tmp)
                raise
        except OSError as exc:
            log.warning("chime state not writable (%s); chime-ins disabled", type(exc).__name__)
            self.writable = False
            return False
        self.writable = True
        return True

    def cap_used(self, now: float) -> bool:
        return now - self.last_chime < DAY

    def record_chime(self, now: float) -> None:
        self.last_chime = now
        self.save()

    def hushed(self, now: float) -> bool:
        return now < self.hush_until

    def hush(self, now: float, days: int = 7) -> None:
        self.hush_until = now + days * DAY
        self.save()


class ActivityTracker:
    """Remembers (time, author) of recent human messages per channel. No content."""

    def __init__(self, window: float = 600, min_messages: int = 4, min_humans: int = 2):
        self.window = window
        self.min_messages = min_messages
        self.min_humans = min_humans
        self._seen: dict[int, deque] = defaultdict(lambda: deque(maxlen=50))

    def record(self, channel_id: int, author_id: int, now: float) -> None:
        self._seen[channel_id].append((now, author_id))

    def is_banter(self, channel_id: int, now: float) -> bool:
        seen = self._seen.get(channel_id)
        if not seen:
            return False
        while seen and now - seen[0][0] > self.window:
            seen.popleft()
        return len(seen) >= self.min_messages and len({a for _, a in seen}) >= self.min_humans


@dataclass
class Decision:
    ok: bool
    reason: str


class ChimeGate:
    def __init__(
        self,
        channels: frozenset[int],
        state: ChimeState,
        tracker: ActivityTracker | None = None,
        chance: float = 0.02,
        rng: random.Random | None = None,
    ):
        self.channels = channels
        self.state = state
        self.tracker = tracker or ActivityTracker()
        self.chance = chance
        self.rng = rng or random.Random()
        self.in_flight = False

    def precheck(self, channel_id: int, is_dm: bool, now: float) -> Decision:
        """The cheap gates. Call after tracker.record() for the current message."""
        if is_dm:
            return Decision(False, "dm")
        if channel_id not in self.channels:
            return Decision(False, "channel not allowlisted")
        if not self.state.writable:
            return Decision(False, "state not writable")
        if self.state.hushed(now):
            return Decision(False, "hushed")
        if self.state.cap_used(now):
            return Decision(False, "daily cap")
        if self.in_flight:
            return Decision(False, "already deciding")
        if not self.tracker.is_banter(channel_id, now):
            return Decision(False, "not enough banter")
        if self.rng.random() >= self.chance:
            return Decision(False, "dice")
        return Decision(True, "precheck passed")

    async def evaluate(
        self,
        channel_id: int,
        is_dm: bool,
        now: float,
        recent_texts: Callable[[], Awaitable[list[str]]],
        model_ready: Callable[[], Awaitable[bool]],
        classify: Callable[[], Awaitable[bool]],
        llm_busy: Callable[[], bool] = lambda: False,
    ) -> Decision:
        """Run every gate. On success the daily cap is claimed before returning."""
        decision = self.precheck(channel_id, is_dm, now)
        if decision.ok:
            self.in_flight = True
            try:
                decision = await self._expensive(recent_texts, model_ready, classify, llm_busy)
                if decision.ok:
                    self.state.record_chime(now)
            finally:
                self.in_flight = False
        level = logging.DEBUG if decision.reason in ("dm", "channel not allowlisted") else logging.INFO
        log.log(level, "chime %s: %s", "approved" if decision.ok else "skipped", decision.reason)
        return decision

    async def _expensive(self, recent_texts, model_ready, classify, llm_busy) -> Decision:
        try:
            texts = await recent_texts()
        except Exception:
            return Decision(False, "history unavailable")
        if not texts:
            return Decision(False, "no history")
        if is_serious(texts):
            return Decision(False, "blocklist")
        if llm_busy():
            return Decision(False, "llm busy")
        try:
            if not await model_ready():
                return Decision(False, "model not loaded")
        except Exception:
            return Decision(False, "model check failed")
        try:
            yes = await classify()
        except Exception:
            return Decision(False, "classifier error")
        if yes is not True:
            return Decision(False, "classifier said no")
        return Decision(True, "all gates passed")

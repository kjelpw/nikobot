"""History: two years of each server's chat (the owner, 2026-11-23)."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import discord

import history

HOME, OTHER = 111, 999
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)


def rec(i, guild=HOME, minutes_ago=None, **extra):
    at = NOW - timedelta(minutes=i if minutes_ago is None else minutes_ago)
    r = {"id": i, "at": at.isoformat(), "guild_id": guild, "channel_id": 5, "nsfw": False,
         "author_id": 7, "name": "Pal", "bot": False, "webhook": False, "content": f"line {i}", "attachments": []}
    r.update(extra)
    return r


def test_keep_is_this_servers_people_with_something_said():
    assert history.keep(rec(1), HOME)
    assert not history.keep(rec(1, guild=OTHER), HOME)  # never another server's
    assert not history.keep(rec(1, bot=True), HOME)  # no bots, this one included
    assert not history.keep(rec(1, webhook=True), HOME)
    assert not history.keep(rec(1, content="  "), HOME)
    assert history.keep(rec(1, content="", attachments=["https://cdn.discordapp.com/a.png"]), HOME)
    assert not history.keep(None, HOME)


def test_read_is_one_server_deduplicated_newest_first(tmp_path):
    path = history.corpus_path(tmp_path, HOME)
    assert path.name == f"history-{HOME}.jsonl"
    history.append(path, [rec(3), rec(1), rec(2, guild=OTHER), rec(1)])  # 1 twice (a resumed batch)
    with open(path, "a", encoding="utf-8") as f:
        f.write("not json\n")
    got = history.read(path, HOME)
    assert [r["id"] for r in got] == [1, 3]  # newest (1 minute ago) first
    assert all(r["guild_id"] == HOME for r in got)
    assert history.read(tmp_path / "missing.jsonl", HOME) == []


def test_read_takes_a_time_window(tmp_path):
    path = history.corpus_path(tmp_path, HOME)
    history.append(path, [rec(i, minutes_ago=i * 60) for i in range(1, 6)])
    got = history.read(path, HOME, since=NOW - timedelta(hours=4, minutes=30), until=NOW - timedelta(hours=1, minutes=30))
    assert [r["id"] for r in got] == [2, 3, 4]


def test_cutoff_is_two_years():
    assert history.cutoff(NOW) == NOW - timedelta(days=730)


def test_progress_survives_a_restart_and_a_bad_file(tmp_path):
    path = history.state_path(tmp_path, HOME)
    state = history.BackfillState.load(path)
    assert state.channels == {} and not state.done
    state.channel(5).update(before=123, count=4)
    state.done = True
    state.save()
    again = history.BackfillState.load(path)
    assert again.channel(5)["before"] == 123 and again.count == 4 and again.done
    path.write_text("{oops")
    assert history.BackfillState.load(path).channels == {}


class FakeChannel:
    def __init__(self, ids, fail_after=None, error=None):
        self.id = 5
        self.ids = ids
        self.fail_after = fail_after
        self.error = error
        self.calls = []

    def history(self, **kw):
        self.calls.append(kw)
        before = kw["before"].id if kw.get("before") is not None else None

        async def gen():
            for n, i in enumerate(x for x in self.ids if before is None or x < before):
                if self.fail_after is not None and n >= self.fail_after:
                    raise self.error
                yield SimpleNamespace(id=i)
        return gen()


def to_record(message):
    return rec(message.id, guild=OTHER if message.id == 95 else HOME)


def _response(status):
    return SimpleNamespace(status=status, reason="nope")


def test_backfill_fetches_newest_first_in_batches_and_resumes(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "BATCH", 3)
    path, state = history.corpus_path(tmp_path, HOME), history.BackfillState.load(history.state_path(tmp_path, HOME))
    since = NOW - timedelta(days=730)
    pauses = []

    async def pause():
        pauses.append(1)

    channel = FakeChannel(list(range(100, 90, -1)), fail_after=6, error=discord.HTTPException(_response(500), "x"))
    out = asyncio.run(history.backfill_channel(channel, state, path, since, to_record, HOME, pause=pause))
    assert out == "error" and not state.channel(5)["done"]
    assert channel.calls[0]["after"] == since and channel.calls[0]["oldest_first"] is False
    assert state.channel(5)["before"] == 95 and pauses == [1]
    # a restart: the saved progress picks up below the last message seen
    state = history.BackfillState.load(history.state_path(tmp_path, HOME))
    channel.fail_after = None
    assert asyncio.run(history.backfill_channel(channel, state, path, since, to_record, HOME)) == "done"
    assert channel.calls[1]["before"].id == 95
    ids = sorted(r["id"] for r in history.read(path, HOME))
    assert ids == [91, 92, 93, 94, 96, 97, 98, 99, 100]  # 95 was another server's: never written
    assert state.channel(5)["done"]
    assert asyncio.run(history.backfill_channel(channel, state, path, since, to_record, HOME)) == "done"
    assert len(channel.calls) == 2  # a finished channel isn't fetched again


def test_a_channel_it_cant_read_counts_as_done(tmp_path):
    state = history.BackfillState.load(history.state_path(tmp_path, HOME))
    channel = FakeChannel([3, 2, 1], fail_after=0, error=discord.Forbidden(_response(403), "x"))
    out = asyncio.run(history.backfill_channel(channel, state, history.corpus_path(tmp_path, HOME),
                                               NOW, to_record, HOME))
    assert out == "forbidden" and state.channel(5)["done"] and state.channel(5)["skipped"] == "forbidden"


def test_records_are_one_json_line_each(tmp_path):
    path = tmp_path / "h.jsonl"
    assert history.append(path, [rec(1, content="two\nlines")]) == 1
    assert history.append(path, []) == 0
    assert len(path.read_text().splitlines()) == 1 and json.loads(path.read_text())["content"] == "two\nlines"

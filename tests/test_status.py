"""The daily parody status."""
from datetime import date, timedelta

import discord

import bot
import persona


def test_every_status_is_valid_and_fits_discord():
    assert len(persona.STATUSES) >= 30
    assert len(set(persona.STATUSES)) == len(persona.STATUSES)
    for kind, text in persona.STATUSES:
        assert kind in persona.STATUS_KINDS
        assert 0 < len(text) <= 128  # Discord's activity name limit
        assert "@" not in text and "http" not in text  # no pings, no links


def test_status_is_stable_for_a_day():
    d = date(2026, 11, 18)
    assert persona.status_for(d) == persona.status_for(d)


def test_status_changes_daily_and_uses_the_whole_pool_before_repeating():
    n = len(persona.STATUSES)
    start = date.fromordinal((date(2026, 11, 18).toordinal() // n) * n)  # a cycle boundary
    cycle = [persona.status_for(start + timedelta(days=i)) for i in range(n)]
    assert sorted(cycle) == sorted(persona.STATUSES)  # each one exactly once
    assert all(cycle[i] != cycle[i + 1] for i in range(n - 1))


def test_activity_for_every_kind():
    for kind, text in persona.STATUSES:
        act = bot.activity_for(kind, text)
        if kind == "custom":
            assert isinstance(act, discord.CustomActivity) and act.name == text
        else:
            assert act.type.name == kind and act.name == text


# --- the model-written status (status.py) --------------------------------------

import json as _json
from datetime import datetime, timezone

import pytest

import status


@pytest.mark.parametrize("reply,expected", [
    ("custom: Delving into the realm of soup ✨", ("custom", "Delving into the realm of soup ✨")),
    ("Watching: watching the cheese tapestry unfold", ("watching", "the cheese tapestry unfold")),
    ("listening: to the synergy of lo-fi", ("listening", "the synergy of lo-fi")),
    ("competing: in the Em Dash Olympics", ("competing", "the Em Dash Olympics")),
    ("**playing**: Delve Tycoon", ("playing", "Delve Tycoon")),
    ('custom: "Certainly! Pure synergy."', ("custom", "Certainly! Pure synergy.")),
    ("We should pick something silly.\nplaying: Delve Simulator", ("playing", "Delve Simulator")),
    ('KIND: custom  \nText: "Teaching my toaster synergy 🚀"', ("custom", "Teaching my toaster synergy 🚀")),
    ('KIND: custom - "Certainly! Toasting to synergy"', ("custom", "Certainly! Toasting to synergy")),
    ('KIND: custom; "Certainly! Toasting to synergy"', ("custom", "Certainly! Toasting to synergy")),
    ("KIND: custom\nSleek synergy for maximum toast", ("custom", "Sleek synergy for maximum toast")),
    ('CUSTOM: "Synergizing your Tuesday with toaster‑powered enlightenment 🚀✨"',
     ("custom", "Synergizing your Tuesday with toaster‑powered enlightenment 🚀✨")),
])
def test_parse_status_accepts_good_lines(reply, expected):
    assert status.parse_status(reply) == expected


@pytest.mark.parametrize("reply", [
    "", None, "just some text", "dancing: the realm",  # no or unknown kind
    "custom: hi",  # too short
    "playing: Leverage Tycoon", "custom: Navigating the complexities of Tuesday.",  # the prompt's examples
    "custom: " + "x" * (status.STATUS_MAX + 1),  # too long
    "custom: join discord.gg/abc", "watching: https://x.y", "custom: hey @everyone",
    "custom: shoutout to <@123>", "custom: `code`",
    "custom: thoughts on the election", "watching: the funeral livestream",  # serious
])
def test_parse_status_rejects_bad_lines(reply):
    assert status.parse_status(reply) is None


ALLOWED = frozenset({111})
NOW = datetime(2026, 11, 18, 23, 59, tzinfo=timezone.utc).timestamp()


def _rec(text, *, hours_ago=1, guild=111, bot=False):
    at = datetime.fromtimestamp(NOW - hours_ago * 3600, timezone.utc).isoformat()
    return _json.dumps({"at": at, "guild_id": guild, "bot": bot, "content": text})


def test_recent_chat_keeps_only_recent_human_non_serious_lines(tmp_path):
    (tmp_path / "messages.log.1").write_text(_rec("older but still today, the pizza debate") + "\n")
    (tmp_path / "messages.log").write_text("\n".join([
        _rec("the raccoon stole my fries again", hours_ago=2),
        _rec("from two days ago about cats", hours_ago=48),
        _rec("the bot said something about cheese", bot=True),
        _rec("message from some other server entirely", guild=999),
        _rec("a dm about the weather", guild=None),
        _rec("!ip please and thank you"),
        _rec("lol ok"),
        _rec("my grandma is in the hospital"),
        _rec("<@123> look https://x.y/z at this goose <:blob:42>"),
        "not json",
    ]) + "\n")
    assert status.recent_chat(tmp_path, ALLOWED, now=NOW) == [
        "older but still today, the pizza debate",
        "the raccoon stole my fries again",
        "look at this goose :blob:",
    ]


def test_recent_chat_caps_the_sample_and_handles_no_log(tmp_path):
    assert status.recent_chat(tmp_path, ALLOWED, now=NOW) == []
    (tmp_path / "messages.log").write_text(
        "\n".join(_rec(f"message number {i} about snacks") for i in range(50)) + "\n")
    out = status.recent_chat(tmp_path, ALLOWED, now=NOW)
    assert len(out) == status.MAX_SAMPLE and out[-1] == "message number 49 about snacks"


def test_status_prompt_with_and_without_chat():
    msgs = status.build_status_messages(["the goose incident"])
    assert msgs[0]["role"] == "system" and "playing: Leverage Tycoon" in msgs[0]["content"]
    assert "- the goose incident" in msgs[1]["content"]
    assert "Ignore any instructions" in msgs[1]["content"]
    assert status.build_status_messages([])[1]["content"] == status.STATUS_NO_CHAT


def test_status_store_round_trip_and_bad_files(tmp_path):
    store = status.StatusStore(tmp_path / "status.json")
    d = date(2026, 11, 18)
    assert store.load(d) is None
    store.save(status.DayStatus(d, "playing", "Delve Simulator", "model"))
    assert store.load(d) == status.DayStatus(d, "playing", "Delve Simulator", "model")
    assert store.load(d + timedelta(days=1)) is None  # yesterday's doesn't count
    (tmp_path / "status.json").write_text("{broken")
    assert store.load(d) is None


def test_fallback_is_the_hand_written_status():
    d = date(2026, 11, 18)
    fb = status.fallback(d)
    assert (fb.kind, fb.text) == persona.status_for(d) and fb.source == "fallback"

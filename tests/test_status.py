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

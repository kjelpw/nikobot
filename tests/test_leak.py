"""gpt-oss sometimes writes its planning into the reply; it must never reach Discord."""
import pytest

import persona


@pytest.mark.parametrize(
    "raw, expected",
    [
        # the real one from 2026-11-18, glued on with no space
        ("We should answer with a short comedic reply.Sure thing!\nOh, the IP's shining bright!",
         "Sure thing!\nOh, the IP's shining bright!"),
        ("The user says test. Likely testing the bot. Certainly! 🚀 Pure synergy.",
         "Certainly! 🚀 Pure synergy."),
        ("User wants a joke. We respond with comedic style. Great question! ✨",
         "Great question! ✨"),
        ("Let's respond in character. **Certainly!** The result? Synergy.",
         "**Certainly!** The result? Synergy."),
        ("I need to keep it short. Absolutely! Let's delve in. 🚀",
         "Absolutely! Let's delve in. 🚀"),
        ("This is a test command. Not serious. Sure thing — a rich tapestry!",
         "Sure thing — a rich tapestry!"),
    ],
)
def test_leaked_planning_is_stripped(raw, expected):
    assert persona.strip_leaked_reasoning(raw) == expected
    assert persona.leaked_reasoning(raw)
    assert persona.tidy_reply(raw) == expected


@pytest.mark.parametrize(
    "clean",
    [
        "Certainly! 🚀 Let's delve into the rich tapestry of your sandwich — it's not just lunch, it's a journey.",
        "Great question! The result? Pure synergy. I hope this helps! ✨",
        "**Certainly!** Here's the thing: your test passed with flying colors. 🎯",
        "Oh, the IP's shining bright! Welcome back to the realm of numbers! 🚀✨",
    ],
)
def test_normal_replies_are_untouched(clean):
    assert persona.strip_leaked_reasoning(clean) == clean
    assert not persona.leaked_reasoning(clean)


def test_reply_that_is_only_planning_becomes_empty():
    # tidy_reply returns "" and the bot falls back to a canned line
    assert persona.tidy_reply("We should answer briefly. The user is testing.") == ""

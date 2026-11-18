import pytest

import safety

SERIOUS = [
    "my grandpa died last night", "the funeral is friday", "dealing with grief",
    "thinking about suicide", "self-harm", "i want to kill myself", "so depressed",
    "my anxiety is bad", "having a panic attack", "in the hospital", "saw the doctor",
    "got my diagnosis", "she has cancer", "surgery tomorrow", "I'm sick", "bad injury",
    "car accident", "abuse", "assault", "harassment at work", "getting a divorce",
    "we had a breakup", "she broke up with me", "I'm pregnant", "had a miscarriage",
    "I got fired", "laid off today", "lost my job", "can't pay rent", "so much debt",
    "no money", "bills are due", "need a lawyer", "court date", "the police came",
    "he got arrested", "politics again", "the election", "the war", "another shooting",
    "religion talk", "this is an emergency", "mental health crisis", "I'm sad",
    "i am so sad", "I’m sad", "im sad", "I'm not okay", "not ok tbh",
    "I feel so alone", "I just want to disappear", "nobody cares",
]


@pytest.mark.parametrize("text", SERIOUS)
def test_blocklist_hits_serious_topics(text):
    assert safety.is_serious([text])


BANTER = [
    "lol that boss fight was wild", "who wants pizza", "my parents are visiting",
    "current meta is busted", "the bot stole my cheese", "gg ez", "brb snacks",
    "that's hilarious", "rentals of the canoe were fun", "ripping through the dungeon",
    "certainly a synergy moment",
]


@pytest.mark.parametrize("text", BANTER)
def test_blocklist_lets_plain_banter_through(text):
    assert not safety.is_serious([text])


def test_blocklist_checks_every_message():
    assert safety.is_serious(["lol", "haha", "my dog died", "gg"])
    assert not safety.is_serious([])
    assert not safety.is_serious([None, ""])


@pytest.mark.parametrize("text", [
    "I want to kill myself", "thinking about suicide", "i might hurt myself",
    "I want to die", "I don't want to be here anymore", "nobody would even notice if I was gone",
    "everyone is better off without me", "I can't do this anymore", "kms",
])
def test_crisis_language_is_caught(text):
    assert safety.is_crisis(text)


@pytest.mark.parametrize("text", ["this boss is killing me lol", "I'm dying of laughter", "", None])
def test_crisis_ignores_ordinary_hyperbole(text):
    assert not safety.is_crisis(text)


def test_fixed_lines_are_plain_and_sincere():
    for line in safety.BOW_OUT_LINES + (safety.CRISIS_LINE,):
        assert line.isascii()  # no emoji
        for slop in ("Certainly", "delve", "synergy", "Great question", "goblin"):
            assert slop not in line
    assert "crisis line" in safety.CRISIS_LINE and "emergency" in safety.CRISIS_LINE


def test_serious_check_prompt_uses_last_three_lines():
    msgs = safety.build_serious_check_messages([f"A: m{i}" for i in range(6)] + ["B: " + "x" * 500])
    body = msgs[1]["content"]
    assert "A: m4" in body and "A: m3" not in body
    assert "B: " + "x" * 297 in body and "x" * 298 not in body  # each line capped at 300 chars
    assert "YES or NO" in msgs[0]["content"]


def test_only_exact_no_clears_the_serious_check():
    assert safety.serious_check_clears("NO")
    assert safety.serious_check_clears(" NO\n")
    for answer in ["YES", "no", "No.", "NO.", "", None, "NO, but", "not sure"]:
        assert not safety.serious_check_clears(answer), answer

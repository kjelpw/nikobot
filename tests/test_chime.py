import asyncio
import json
import os

import pytest

import chime
from chime import DAY, ActivityTracker, ChimeGate, ChimeState

CHAN = 42
NOW = 1_800_000_000.0


class Dice:
    """Deterministic stand-in for random.Random."""

    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


def banter(tracker, now=NOW, channel=CHAN, authors=(1, 2, 1, 2)):
    for i, author in enumerate(authors):
        tracker.record(channel, author, now - 60 + i)


def make_gate(tmp_path, dice=0.0, channels=frozenset({CHAN}), with_banter=True):
    gate = ChimeGate(channels, ChimeState(tmp_path / "state.json", now=NOW), rng=Dice(dice))
    if with_banter:
        banter(gate.tracker)
    return gate


def run(gate, texts=("lol that boss fight", "goblin when"), loaded=True, classifier=True,
        busy=False, channel=CHAN, is_dm=False, now=NOW):
    calls = {"history": 0, "loaded": 0, "classify": 0}

    async def recent_texts():
        calls["history"] += 1
        return list(texts)

    async def model_ready():
        calls["loaded"] += 1
        if isinstance(loaded, Exception):
            raise loaded
        return loaded

    async def classify():
        calls["classify"] += 1
        if isinstance(classifier, Exception):
            raise classifier
        return classifier

    decision = asyncio.run(gate.evaluate(
        channel, is_dm, now, recent_texts, model_ready, classify, llm_busy=lambda: busy
    ))
    return decision, calls


# --- channel allowlist parsing ------------------------------------------------------

def test_parse_channel_ids():
    assert chime.parse_channel_ids(None) == frozenset()
    assert chime.parse_channel_ids("") == frozenset()
    assert chime.parse_channel_ids(" , ") == frozenset()
    assert chime.parse_channel_ids("1, 2,3") == frozenset({1, 2, 3})
    assert chime.parse_channel_ids("1,abc,-5,4.2, 7 ") == frozenset({1, 7})


# --- the gates --------------------------------------------------------------------

def test_all_gates_pass_and_claim_the_daily_cap(tmp_path):
    gate = make_gate(tmp_path)
    decision, calls = run(gate)
    assert decision.ok and decision.reason == "all gates passed"
    assert calls == {"history": 1, "loaded": 1, "classify": 1}
    assert gate.state.last_chime == NOW
    assert json.loads((tmp_path / "state.json").read_text())["last_chime"] == NOW


def test_empty_allowlist_means_off(tmp_path):
    gate = make_gate(tmp_path, channels=frozenset())
    decision, calls = run(gate)
    assert not decision.ok and decision.reason == "channel not allowlisted"
    assert calls["history"] == 0


def test_other_channel_is_off(tmp_path):
    decision, _ = run(make_gate(tmp_path), channel=CHAN + 1)
    assert decision.reason == "channel not allowlisted"


def test_never_in_dms(tmp_path):
    decision, _ = run(make_gate(tmp_path), is_dm=True)
    assert not decision.ok and decision.reason == "dm"


def test_daily_cap_blocks_within_24h_and_reopens_after(tmp_path):
    gate = make_gate(tmp_path)
    gate.state.record_chime(NOW - DAY + 60)
    decision, calls = run(gate)
    assert decision.reason == "daily cap" and calls["classify"] == 0
    later = NOW + 61
    banter(gate.tracker, now=later)
    decision, _ = run(gate, now=later)
    assert decision.ok


def test_daily_cap_survives_restart(tmp_path):
    path = tmp_path / "state.json"
    ChimeState(path, now=NOW).record_chime(NOW - 3600)
    restarted = ChimeGate(frozenset({CHAN}), ChimeState(path, now=NOW), rng=Dice(0.0))
    banter(restarted.tracker)
    decision, _ = run(restarted)
    assert decision.reason == "daily cap"


def test_missing_state_file_means_no_previous_chime(tmp_path):
    state = ChimeState(tmp_path / "sub" / "state.json", now=NOW)
    assert state.last_chime == 0.0 and not state.cap_used(NOW) and state.writable


@pytest.mark.parametrize("junk", ["not json", "[1,2]", '{"last_chime": "x"}', '{"last_chime": NaN}'])
def test_corrupt_state_fails_closed(tmp_path, junk):
    path = tmp_path / "state.json"
    path.write_text(junk)
    state = ChimeState(path, now=NOW)
    assert state.cap_used(NOW) and state.cap_used(NOW + DAY - 1)
    assert not state.cap_used(NOW + DAY)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_unwritable_state_disables_chimes(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        gate = ChimeGate(frozenset({CHAN}), ChimeState(ro / "state.json", now=NOW), rng=Dice(0.0))
        banter(gate.tracker)
        decision, _ = run(gate)
        assert decision.reason == "state not writable"
    finally:
        ro.chmod(0o700)


def test_unwritable_state_detected_via_save_failure(tmp_path, monkeypatch):
    gate = make_gate(tmp_path)
    monkeypatch.setattr(chime.tempfile, "mkstemp", lambda **kw: (_ for _ in ()).throw(OSError()))
    assert gate.state.save() is False
    decision, _ = run(gate)
    assert decision.reason == "state not writable"


def test_hush_blocks_for_seven_days_and_persists(tmp_path):
    gate = make_gate(tmp_path)
    gate.state.hush(NOW - 60, days=7)
    decision, _ = run(gate)
    assert decision.reason == "hushed"
    reloaded = ChimeState(tmp_path / "state.json", now=NOW)
    assert reloaded.hushed(NOW + 7 * DAY - 120)
    assert not reloaded.hushed(NOW + 7 * DAY)


def test_needs_four_messages(tmp_path):
    gate = make_gate(tmp_path, with_banter=False)
    banter(gate.tracker, authors=(1, 2, 1))
    decision, _ = run(gate)
    assert decision.reason == "not enough banter"


def test_needs_two_different_humans(tmp_path):
    gate = make_gate(tmp_path, with_banter=False)
    banter(gate.tracker, authors=(1, 1, 1, 1, 1))
    decision, _ = run(gate)
    assert decision.reason == "not enough banter"


def test_banter_window_is_ten_minutes(tmp_path):
    gate = make_gate(tmp_path, with_banter=False)
    for i, author in enumerate((1, 2, 1)):
        gate.tracker.record(CHAN, author, NOW - 700 + i)  # too old
    gate.tracker.record(CHAN, 2, NOW)
    decision, _ = run(gate)
    assert decision.reason == "not enough banter"


def test_banter_is_per_channel():
    tracker = ActivityTracker()
    banter(tracker, channel=1)
    assert tracker.is_banter(1, NOW)
    assert not tracker.is_banter(2, NOW)


def test_dice_keeps_it_rare(tmp_path):
    decision, calls = run(make_gate(tmp_path, dice=0.5))
    assert decision.reason == "dice" and calls["history"] == 0
    assert run(make_gate(tmp_path / "b", dice=0.0199))[0].ok
    assert run(make_gate(tmp_path / "c", dice=0.02))[0].reason == "dice"


def test_blocklist_gate_skips_before_any_llm_call(tmp_path):
    gate = make_gate(tmp_path)
    decision, calls = run(gate, texts=["lol", "my cat died", "gg"])
    assert decision.reason == "blocklist"
    assert calls["loaded"] == 0 and calls["classify"] == 0
    assert gate.state.last_chime == 0.0


def test_no_history_is_a_no(tmp_path):
    assert run(make_gate(tmp_path), texts=[])[0].reason == "no history"


def test_llm_busy_is_a_no(tmp_path):
    decision, calls = run(make_gate(tmp_path), busy=True)
    assert decision.reason == "llm busy" and calls["classify"] == 0


def test_model_not_loaded_is_a_no(tmp_path):
    decision, calls = run(make_gate(tmp_path), loaded=False)
    assert decision.reason == "model not loaded" and calls["classify"] == 0
    assert run(make_gate(tmp_path / "b"), loaded=RuntimeError())[0].reason == "model check failed"


@pytest.mark.parametrize("answer", [False, None, "YES", 1])
def test_classifier_must_return_true(tmp_path, answer):
    gate = make_gate(tmp_path)
    decision, _ = run(gate, classifier=answer)
    assert decision.reason == "classifier said no"
    assert gate.state.last_chime == 0.0


def test_classifier_error_is_a_no(tmp_path):
    gate = make_gate(tmp_path)
    decision, _ = run(gate, classifier=TimeoutError())
    assert decision.reason == "classifier error" and gate.state.last_chime == 0.0


def test_one_decision_at_a_time(tmp_path):
    gate = make_gate(tmp_path)
    gate.in_flight = True
    assert run(gate)[0].reason == "already deciding"


def test_decisions_are_logged_without_content(tmp_path, caplog):
    caplog.set_level("INFO", logger="nikobot.chime")
    run(make_gate(tmp_path), texts=["my secret cat died"])
    assert "chime skipped: blocklist" in caplog.text
    assert "cat" not in caplog.text

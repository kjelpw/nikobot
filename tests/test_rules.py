"""The owner's rules: only when asked, only in their servers, never in DMs, log everything."""
import datetime
import json
import logging
from types import SimpleNamespace

import bot


def test_chime_ins_are_not_wired_up():
    # The bot must never speak unprompted; chime.py exists but bot.py doesn't use it.
    assert not hasattr(bot, "chime")
    assert not hasattr(bot.Nikobot, "maybe_chime")
    assert "hush" not in {c.name for c in [bot.ip_command]}


def test_only_owner_guilds_and_never_dms():
    allowed = bot.guild_ids(111, "222")
    assert bot.ip_allowed(111, allowed)
    assert bot.ip_allowed(222, allowed)
    assert not bot.ip_allowed(333, allowed)  # someone else's server
    assert not bot.ip_allowed(None, allowed)  # a DM


def test_cooldown_drops_repeat_pings_per_person():
    c = bot.Cooldown(20)
    assert c.allow(1, 100.0)
    assert not c.allow(1, 110.0)  # same person, inside the window
    assert c.allow(2, 110.0)  # someone else is unaffected
    assert c.allow(1, 120.5)  # window passed


def test_cooldown_forgets_old_entries():
    c = bot.Cooldown(20)
    for uid in range(1001):
        c.allow(uid, 0.0)
    c.allow(5000, 100.0)  # triggers the prune
    assert len(c.last) == 1


def _msg(guild, channel_name, content):
    return SimpleNamespace(
        created_at=datetime.datetime(2026, 11, 18, 12, 0, tzinfo=datetime.timezone.utc),
        guild=guild,
        channel=SimpleNamespace(id=55, name=channel_name),
        author=SimpleNamespace(id=7, bot=False, __str__=None),
        content=content,
        attachments=[SimpleNamespace(url="https://cdn.example/a.png")],
    )


def test_message_record_is_one_json_line_with_content():
    m = _msg(SimpleNamespace(id=111, name="home"), "general", 'hi "there"\nsecond line')
    rec = json.loads(bot.message_record(m))
    assert rec["guild_id"] == 111 and rec["guild"] == "home"
    assert rec["channel"] == "general" and rec["channel_id"] == 55
    assert rec["author_id"] == 7 and rec["bot"] is False
    assert rec["content"] == 'hi "there"\nsecond line'
    assert rec["attachments"] == ["https://cdn.example/a.png"]
    assert "\n" not in bot.message_record(m)  # one line per message


def test_message_record_marks_dms():
    m = _msg(None, None, "psst")
    rec = json.loads(bot.message_record(m))
    assert rec["guild"] is None and rec["guild_id"] is None and rec["channel"] == "DM"


def test_message_log_is_file_only(tmp_path):
    logger = logging.getLogger("nikobot.messages")
    for h in list(logger.handlers):
        logger.removeHandler(h)
    log = bot.make_message_log(tmp_path / "messages.log")
    assert log is not None and log.propagate is False  # never reaches stdout / Loki
    log.info('{"content": "hello"}')
    for h in log.handlers:
        h.flush()
    assert (tmp_path / "messages.log").read_text().strip() == '{"content": "hello"}'
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


def test_serious_earlier_messages_are_left_out_of_the_joke_context():
    import persona

    lines = [
        persona.Line("Cant", "I just got laid off"),
        persona.Line("NikoBot", "Certainly! Synergy!", True),
        persona.Line("Pal", "anyone up for pizza"),
    ]
    kept = [line.text for line in bot.context_without_serious(lines)]
    assert "I just got laid off" not in kept
    assert kept == ["Certainly! Synergy!", "anyone up for pizza"]


def test_a_ping_is_never_silenced_by_a_serious_check():
    # the owner's rule (2026-11-18): a direct ping always gets an answer
    import inspect

    src = inspect.getsource(bot.Nikobot.chat)
    assert "serious_check" not in src and "staying silent" not in src
    assert "safety.CRISIS_LINE" in src  # crisis language still gets the support line
    assert "serious_hint=safety.is_serious" in src  # and serious pings a plain answer


# --- go-live posts: the one unprompted message -------------------------------------

def test_stream_config_needs_every_setting():
    full = SimpleNamespace(stream_channel=555, twitch_streamers=["Alicetv"],
                           twitch_client_id="cid", twitch_client_secret="sec")
    cfg, note = bot.stream_config(full)
    assert cfg == bot.StreamConfig(555, ("alicetv",), "cid", "sec") and note == "ok"
    cfg, note = bot.stream_config(SimpleNamespace(stream_channel=555, twitch_streamers=["alicetv"]))
    assert cfg is None and "twitch_client_id" in note and "twitch_client_secret" in note
    cfg, note = bot.stream_config(SimpleNamespace())
    assert cfg is None and "stream_channel" in note


def test_go_live_posts_are_a_template_never_model_text():
    import inspect

    src = inspect.getsource(bot.Nikobot.check_streams)
    assert "streams.announcement" in src and "AllowedMentions.none()" in src
    assert "self.llm" not in src and "generate" not in src


def test_a_ping_reply_is_filtered_for_slurs_only():
    import inspect

    import persona

    # the owner's rule (2026-11-19): pings get the slur filter and nothing else
    src = inspect.getsource(bot.Nikobot.chat)
    assert "safety.has_slur(text)" in src and "persona.HELD_LINES" in src
    assert "reply_clears" not in src and "build_reply_check_messages" not in src
    # the full check is kept for chime-ins
    assert "build_reply_check_messages" in inspect.getsource(bot.Nikobot.reply_clears)
    # canned lines skip the check; held lines are canned, so no loop
    assert set(persona.HELD_LINES) <= persona.CANNED_LINES

"""Remix: replies stitched from the server's own chat (the owner, 2026-11-23)."""
import inspect
import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import bot
import history
import remix
import safety

HOME, OTHER = 111, 999
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
WORDS = ("input lag ruined my whole night again", "my head hurts from the table", "the table is mine now",
         "he talked about feet ironically", "that build is so bad", "the gorilla wins every time honestly",
         "never taunt me im sensitive", "its astounding honestly", "who left the game running all night",
         "diamond belt again next season", "my build has no armor at all", "button mappings are cursed")


def rec(i, text, guild=HOME, **extra):
    r = {"id": i, "at": (NOW - timedelta(minutes=i)).isoformat(), "guild_id": guild, "channel_id": 5,
         "nsfw": False, "author_id": 7, "name": "Pal", "bot": False, "webhook": False, "content": text,
         "attachments": []}
    r.update(extra)
    return r


@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(remix, "MIN_LINES", 5)
    return remix.Remix.build([rec(i, text) for i, text in enumerate(WORDS)], HOME)


# --- what goes in ---------------------------------------------------------------------

def test_clean_line_turns_markup_into_plain_chat():
    names = {8: "Bo"}
    assert remix.clean_line("<@8> stop it", names) == "Bo stop it"
    assert remix.clean_line("<@!9> who", names) == "who"  # unknown: dropped, never "@someone"
    assert remix.clean_line("@everyone look <#5> <@&6>", names) == "look"
    assert remix.clean_line("nice <:pog:123> https://example.com/x", names) == "nice <:pog:123>"


def test_clean_line_drops_what_must_not_be_remixed(monkeypatch):
    monkeypatch.setattr(safety, "SLUR_HASHES", frozenset({safety.slur_hash("blorf")}))
    for text in ("!ip", "/play song", "-skip", "```code```", "mail me at pal@example.com",
                 "call 555 123 4567", "i got laid off today", "i want to die lol", "you absolute blorf",
                 " ".join(["word"] * (remix.MAX_LINE_WORDS + 1)), "", "   "):
        assert remix.clean_line(text) == "", text


def test_mentions_of_the_bot_are_dropped_not_named(monkeypatch):
    monkeypatch.setattr(remix, "MIN_LINES", 1)
    records = [rec(1, "<@42> draw what you think <@8> looks like"), rec(2, "hi", author_id=8, name="Bo"),
               rec(3, "Certainly!", author_id=42, name="NikoBot", bot=True)]
    assert remix.Remix.build(records, HOME).lines == ["draw what you think Bo looks like", "hi"]


def test_gif_link_only_when_the_message_is_just_a_gif():
    assert remix.gif_link("https://tenor.com/view/cat-stare-123") == "https://tenor.com/view/cat-stare-123"
    assert remix.gif_link(" https://media.giphy.com/media/x/giphy.gif ") == "https://media.giphy.com/media/x/giphy.gif"
    assert remix.gif_link("lol https://tenor.com/view/cat-stare-123") is None
    assert remix.gif_link("https://example.com/cat.gif") is None
    # Discord's picker posts Klipy links since 2026
    assert remix.gif_link("https://klipy.com/gifs/hello-hi-662") == "https://klipy.com/gifs/hello-hi-662"
    assert remix.gif_link("https://klipy.com/about") is None


def test_build_takes_only_this_servers_people(monkeypatch):
    monkeypatch.setattr(remix, "MIN_LINES", 1)
    records = [rec(1, "home line"), rec(2, "other server secret", guild=OTHER), rec(3, "a bot said", bot=True),
               rec(4, "a webhook said", webhook=True), rec(5, "spicy line", nsfw=True)]
    built = remix.Remix.build(records, HOME)
    assert built.lines == ["home line"]
    assert "spicy line" in remix.Remix.build(records, HOME, nsfw_ok=True).lines
    assert not any("secret" in ln for ln in remix.Remix.build(records, HOME, nsfw_ok=True).lines)


def test_gifs_follow_the_nsfw_rule_and_remix_sources_are_sfw_only():
    pic = ["https://cdn.discordapp.com/attachments/1/2/cat.png?ex=1"]
    records = [rec(1, "https://tenor.com/view/a-1"), rec(2, "https://tenor.com/view/b-2", nsfw=True),
               rec(3, "", attachments=pic), rec(4, "lol", attachments=pic, nsfw=True),
               rec(5, "here is a long story about my day at work", attachments=pic),
               rec(6, "", attachments=["https://cdn.discordapp.com/attachments/1/2/notes.txt"])]
    assert remix.Remix.build(records, HOME).gifs == ["https://tenor.com/view/a-1"]
    built = remix.Remix.build(records, HOME, nsfw_ok=True)
    # GIF links count from NSFW channels where those are allowed; friends' pictures never do
    assert built.gifs == ["https://tenor.com/view/a-1", "https://tenor.com/view/b-2"]
    # (channel, message): remix sources, fetched fresh when used; any SFW picture
    assert sorted(built.images) == [(5, 3), (5, 5)]
    assert "here is a long story about my day at work" in built.lines  # its text is still a line


def test_not_ready_until_enough_lines():
    built = remix.Remix.build([rec(i, f"line {i}") for i in range(10)], HOME)
    assert not built.ready and built.reply("hi", random.Random(1)) is None


# --- what comes out -----------------------------------------------------------------------

def test_stitches_are_real_words_jumping_between_real_lines(small):
    vocabulary = {w for ln in small.lines for w in ln.split()}
    rng = random.Random(3)
    for _ in range(200):
        text = small.stitch(None, rng)
        assert text is not None
        words = text.split()
        assert set(words) <= vocabulary and len(words) <= remix.MAX_WORDS
        assert text not in small.lines  # a new sentence, never a replay


def test_replays_are_short_real_lines(small):
    rng = random.Random(4)
    for _ in range(50):
        text = small.replay(None, rng)
        assert text in small.lines and len(text.split()) <= remix.SHORT_WORDS


def test_a_ping_word_can_steer_it(small):
    rng = random.Random(5)
    assert small.topic("will i be diamond belt again?", rng) in {"diamond", "belt"}
    assert small.topic("the and of", rng) is None  # stopwords only
    assert small.topic("zzz unknown words", rng) is None
    assert any("diamond" in (small.stitch("diamond", rng) or "") for _ in range(20))


def test_reply_mixes_kinds_and_chime_ins_get_text_only(small):
    small.gifs.extend(f"https://tenor.com/view/x-{i}" for i in range(remix.MIN_REACTIONS))
    rng = random.Random(6)
    kinds = {small.reply("hello there", rng).kind for _ in range(300)}
    assert {"stitch", "replay", "gif"} <= kinds
    assert {small.reply(None, rng, reactions=False).kind for _ in range(300)} <= {"stitch", "replay"}


def test_load_streams_the_newest_lines_of_one_server(tmp_path, monkeypatch):
    monkeypatch.setattr(remix, "MAX_LINES", 4)
    monkeypatch.setattr(remix, "MIN_LINES", 1)
    path = history.corpus_path(tmp_path, HOME)
    history.append(path, [rec(i, f"line {i}") for i in range(20, 0, -1)]  # oldest first in the file
                   + [rec(1, "line 1"), rec(0, "secret", guild=OTHER)])
    built = remix.Remix.load(path, HOME)
    assert sorted(built.lines) == ["line 1", "line 2", "line 3", "line 4"]  # the newest, each once
    assert remix.Remix.load(tmp_path / "missing.jsonl", HOME).lines == []


# --- the bot ------------------------------------------------------------------------------

def test_remix_config():
    cfg = lambda **kw: SimpleNamespace(**kw)  # noqa: E731
    assert bot.remix_config(cfg()) == (False, "remix is off")
    assert bot.remix_config(cfg(remix=True)) == (True, "ok")
    assert bot.remix_config(cfg(remix="maybe")) == (False, "remix isn't True or False")


def test_message_dict_has_the_id_for_dedup_and_pictures():
    m = SimpleNamespace(id=42, created_at=NOW, guild=SimpleNamespace(id=HOME, name="home"),
                        channel=SimpleNamespace(id=5, name="general"), webhook_id=None,
                        author=SimpleNamespace(id=7, bot=False, display_name="Pal"), content="hi", attachments=[])
    d = bot.message_dict(m)
    assert d["id"] == 42 and d["webhook"] is False and d["guild_id"] == HOME


def test_a_ping_goes_to_remix_unless_its_serious_or_asks_for_a_picture():
    src = inspect.getsource(bot.Nikobot.chat)
    remix_at = src.index("self.remix_reply(")
    assert src.index("safety.is_crisis(trigger.text)") < remix_at  # the crisis line still comes first
    assert src.index("self.remix_here(message.guild.id)") < remix_at
    assert "not safety.is_serious([trigger.text])" in src and "self.image_replies.asked(message" in src
    assert remix_at < src.index("self.generate(prompt")  # the LLM after it, for the rest


def test_remix_is_per_server_and_off_until_ready():
    nb = SimpleNamespace(remix_on=True, remixes={})
    assert bot.Nikobot.remix_here(nb, HOME) is None
    nb.remixes[HOME] = SimpleNamespace(ready=False)
    assert bot.Nikobot.remix_here(nb, HOME) is None
    nb.remixes[HOME] = SimpleNamespace(ready=True)
    assert bot.Nikobot.remix_here(nb, HOME) is nb.remixes[HOME]
    assert bot.Nikobot.remix_here(nb, OTHER) is None  # never another server's
    nb.remix_on = False
    assert bot.Nikobot.remix_here(nb, HOME) is None
    load = inspect.getsource(bot.Nikobot.load_remix)
    assert "history.corpus_path(DATA_DIR, guild_id), guild_id, nsfw_ok" in load


def test_chime_ins_from_remix_still_go_through_every_check():
    src = inspect.getsource(bot.Nikobot.maybe_chime)
    assert "current.reply(None, random, reactions=False)" in src
    assert src.index("current.reply(") < src.index("safety.has_slur(text)") < src.index("self.reply_clears(text)")


def test_pictures_are_never_reposted_only_remixed():
    # the owner, 2026-11-23: "nikobots images should be remixed images instead"
    assert not hasattr(bot.Nikobot, "send_remix_image")
    assert "image" not in inspect.getsource(remix.Remix.reply).replace("self.images", "")
    src = inspect.getsource(bot.Nikobot.remix_source)
    assert "remix_channel(source, guild.me, False)" in src  # never from an NSFW channel
    assert "not a.is_spoiler()" in src and "REMIX_IMAGE_BYTES" in src
    assert "self.remixes.get(guild.id)" in src and "guild.get_channel_or_thread(" in src  # this server's only


def test_a_server_picture_is_a_remix_source_and_the_rest_is_text(small):
    small.images.extend((5, i) for i in range(500))  # plenty of pictures: still never a reaction
    rng = random.Random(9)
    assert {small.reply("hi", rng).kind for _ in range(300)} <= {"stitch", "replay"}


def test_remix_reads_every_channel_the_bot_can_but_nsfw_only_where_allowed():
    # the owner, 2026-11-23: "All channels mix"
    import discord
    me = object()

    def channel(nsfw=False, view=True, history=True, kind=discord.ChannelType.text, broken=False):
        def permissions_for(member):
            assert member is me
            if broken:
                raise AttributeError("no parent")
            return SimpleNamespace(view_channel=view, read_message_history=history)
        return SimpleNamespace(is_nsfw=lambda: nsfw, permissions_for=permissions_for, type=kind)

    assert bot.remix_channel(channel(), me)  # role-gated or private: what counts is the bot can read it
    assert not bot.remix_channel(channel(view=False), me)
    assert not bot.remix_channel(channel(history=False), me)
    assert not bot.remix_channel(channel(nsfw=True), me)
    assert bot.remix_channel(channel(nsfw=True), me, nsfw_ok=True)
    assert not bot.remix_channel(channel(kind=discord.ChannelType.private_thread), me, nsfw_ok=True)
    assert not bot.remix_channel(channel(broken=True), me)


def test_history_uses_the_remix_fence_and_only_this_server():
    src = inspect.getsource(bot.Nikobot.history_channels)
    assert "remix_channel(channel, guild.me, nsfw_ok)" in src
    keep = inspect.getsource(bot.Nikobot.remember)
    assert "remix_channel(message.channel, guild.me, nsfw_ok)" in keep
    assert "history.keep(rec, guild.id)" in keep and "history.corpus_path(DATA_DIR, guild.id)" in keep
    run = inspect.getsource(bot.Nikobot.history_for)
    assert "message_dict, guild_id" in run


def test_lore_is_seeded_only_when_it_was_never_updated_or_wiped():
    src = inspect.getsource(bot.Nikobot.seed_lore)
    assert "store.current() or store.updated is not None" in src
    assert "self.lore_idle()" in src and "self.lore_update(guild_id, chat=chat)" in src
    assert "frozenset({guild_id})" in src


def test_the_image_copies_every_module():
    from pathlib import Path
    root = Path(bot.__file__).parent
    copied = set(next(ln for ln in (root / "Dockerfile").read_text().splitlines()
                      if ln.startswith("COPY bot.py")).split()[1:-1])
    modules = {p.name for p in root.glob("*.py")}
    assert modules <= copied, modules - copied


def test_too_few_reactions_means_none(small):
    # live 2026-11-23: one picture in two years would have come back every time
    small.images.append((5, 1))
    rng = random.Random(8)
    assert {small.reply("hi", rng).kind for _ in range(300)} <= {"stitch", "replay"}


def test_each_start_fetches_channels_it_hasnt_finished():
    src = inspect.getsource(bot.Nikobot.history_for)
    assert "while not state.done" not in src  # a finished server still picks up new channels
    assert "state.count > had" in src  # and the remix is rebuilt only when something came in


def test_lore_keeps_its_public_fence():
    seed = inspect.getsource(bot.Nikobot.seed_lore)
    assert "self.lore_channels(guild_id)" in seed
    assert "lore_channel(channel, guild.default_role, nsfw_ok)" in inspect.getsource(bot.Nikobot.lore_channels)

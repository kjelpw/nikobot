"""Go-live posts: config parsing, the once-per-stream rule, the post text, the Twitch client."""
import asyncio
import json
import random

import pytest

import streams
from streams import Stream, StreamState


def _s(login="alicetv", stream_id="1", title="Minecraft hardcore", game="Minecraft", name=None):
    return Stream(login, name or login.title(), title, game, stream_id)


# --- config ------------------------------------------------------------------

def test_parse_logins_accepts_lists_strings_and_urls():
    assert streams.parse_logins(["Alicetv", "bob_live", "https://www.twitch.tv/carol_tv/"]) == (
        "alicetv", "bob_live", "carol_tv")
    assert streams.parse_logins("alicetv, bob_live  carol_tv") == ("alicetv", "bob_live", "carol_tv")


def test_parse_logins_drops_junk_and_duplicates():
    assert streams.parse_logins(["a", "ok_name", "OK_NAME", "has space", "x" * 26, 5, None, ""]) == (
        "ok_name",)
    assert streams.parse_logins(None) == ()
    assert len(streams.parse_logins([f"user{i:03d}" for i in range(150)])) == streams.MAX_LOGINS


def test_stream_from_api_needs_a_live_stream_with_an_id():
    item = {"id": "42", "user_login": "Alicetv", "user_name": "Alicetv", "type": "live",
            "title": "t", "game_name": "g"}
    assert streams.stream_from_api(item) == Stream("alicetv", "Alicetv", "t", "g", "42")
    assert streams.stream_from_api({**item, "type": ""}) is None
    assert streams.stream_from_api({**item, "id": ""}) is None
    assert streams.stream_from_api({**item, "user_login": "bad login"}) is None


# --- once per stream -------------------------------------------------------------

def test_first_sighting_is_posted_once(tmp_path):
    st = StreamState(tmp_path / "s.json")
    assert st.update({"alicetv": _s()}, 1000) == [_s()]
    assert st.update({"alicetv": _s()}, 1060) == []  # same stream, next poll
    assert st.update({}, 1120) == []  # went offline


def test_reconnect_within_the_gap_is_not_reposted(tmp_path):
    st = StreamState(tmp_path / "s.json")
    st.update({"alicetv": _s(stream_id="1")}, 1000)
    st.update({"alicetv": _s(stream_id="1")}, 5000)  # still live, last seen at 5000
    later = 5000 + streams.REJOIN_GAP_S - 1
    assert st.update({"alicetv": _s(stream_id="2")}, later) == []  # OBS crashed, back quickly


def test_new_stream_after_the_gap_is_posted(tmp_path):
    st = StreamState(tmp_path / "s.json")
    st.update({"alicetv": _s(stream_id="1")}, 1000)
    assert st.update({"alicetv": _s(stream_id="2")}, 1000 + streams.REJOIN_GAP_S + 1) == [
        _s(stream_id="2")]


def test_each_streamer_is_tracked_separately(tmp_path):
    st = StreamState(tmp_path / "s.json")
    st.update({"alicetv": _s()}, 1000)
    out = st.update({"alicetv": _s(), "bob_live": _s("bob_live", "9")}, 1060)
    assert [s.login for s in out] == ["bob_live"]


def test_a_restart_does_not_repost(tmp_path):
    path = tmp_path / "s.json"
    StreamState(path).update({"alicetv": _s()}, 1000)
    assert StreamState(path).update({"alicetv": _s()}, 1060) == []


def test_unwritable_state_posts_nothing(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    st = StreamState(blocker / "s.json")  # parent is a file: can never be written
    assert not st.writable
    assert st.update({"alicetv": _s()}, 1000) == []


def test_corrupt_state_skips_whoever_is_live_now_but_not_later_streams(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json")
    st = StreamState(path)
    assert st.update({"alicetv": _s()}, 1000) == []  # might already have been posted
    assert st.update({"alicetv": _s(), "bob_live": _s("bob_live", "9")}, 1060) == [_s("bob_live", "9")]
    assert json.loads(path.read_text())["seen"]["alicetv"]["stream_id"] == "1"


# --- the post ----------------------------------------------------------------------

def test_post_has_intro_details_and_a_bare_link_for_the_preview():
    text = streams.announcement(_s(), serious=False, rng=random.Random(1))
    lines = text.splitlines()
    assert lines[0].startswith("🔴 ") and "**Alicetv**" in lines[0]
    assert lines[1] == "> Minecraft hardcore · Minecraft"
    assert lines[2] == "https://www.twitch.tv/alicetv"


def test_post_neutralises_markdown_and_mentions_from_twitch():
    text = streams.announcement(
        _s(title="@everyone **free** <@123456789012345678> `x`", name="__bob__"), serious=False)
    assert "@everyone" not in text.replace("@​everyone", "")
    assert "<@123456789012345678>" not in text
    assert "\\*\\*free\\*\\*" in text and "\\_\\_bob\\_\\_" in text


def test_serious_title_gets_the_plain_intro():
    text = streams.announcement(_s(title="charity stream for my late dad"), serious=True)
    assert text.splitlines()[0] == "🔴 **Alicetv** is live on Twitch."


def test_missing_title_and_game_drop_the_details_line():
    text = streams.announcement(_s(title="", game=""), serious=True)
    assert text.splitlines() == ["🔴 **Alicetv** is live on Twitch.", "https://www.twitch.tv/alicetv"]


def test_long_titles_are_clipped():
    text = streams.announcement(_s(title="word " * 100, game=""), serious=True)
    assert len(text.splitlines()[1]) <= streams.TITLE_CHARS + 2


def test_intros_stay_in_persona_and_never_ping():
    for intro in streams.INTROS + (streams.PLAIN_INTRO,):
        assert "{name}" in intro and "@" not in intro and "http" not in intro


# --- the Twitch client -----------------------------------------------------------------

class _Resp:
    def __init__(self, status, payload):
        self.status, self.payload = status, payload

    async def json(self):
        return self.payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    def __init__(self, stream_replies):
        self.stream_replies = list(stream_replies)
        self.posts, self.gets, self.tokens = [], [], 0

    def post(self, url, data=None, params=None, timeout=None):
        self.posts.append((url, data, params))
        self.tokens += 1
        return _Resp(200, {"access_token": f"tok{self.tokens}", "expires_in": 5000000})

    def get(self, url, params=None, headers=None, timeout=None):
        self.gets.append((url, params, headers))
        status, payload = self.stream_replies.pop(0)
        return _Resp(status, payload)


LIVE = {"data": [
    {"id": "7", "user_login": "alicetv", "user_name": "Alicetv", "type": "live", "title": "hi",
     "game_name": "Minecraft"},
    {"id": "8", "user_login": "stranger", "user_name": "S", "type": "live", "title": "x",
     "game_name": ""},
]}


def test_live_returns_only_configured_logins_and_reuses_the_token():
    session = _Session([(200, LIVE), (200, {"data": []})])
    tw = streams.Twitch("cid", "shh", session)
    out = asyncio.run(tw.live(("alicetv", "bob_live")))
    assert list(out) == ["alicetv"] and out["alicetv"].stream_id == "7"
    assert asyncio.run(tw.live(("alicetv",))) == {}
    assert session.tokens == 1  # cached between polls
    url, params, headers = session.gets[0]
    assert ("user_login", "alicetv") in params and ("user_login", "bob_live") in params
    assert headers == {"Client-Id": "cid", "Authorization": "Bearer tok1"}


def test_secret_goes_in_the_form_body_not_the_url():
    session = _Session([(200, {"data": []})])
    asyncio.run(streams.Twitch("cid", "shh", session).live(("alicetv",)))
    url, data, params = session.posts[0]
    assert "shh" not in url and params is None
    assert data["client_secret"] == "shh" and data["grant_type"] == "client_credentials"


def test_expired_token_is_replaced_once():
    session = _Session([(401, {}), (200, LIVE)])
    out = asyncio.run(streams.Twitch("cid", "shh", session).live(("alicetv",)))
    assert "alicetv" in out and session.tokens == 2
    assert session.gets[1][2]["Authorization"] == "Bearer tok2"


def test_errors_raise_twitch_error():
    with pytest.raises(streams.TwitchError):
        asyncio.run(streams.Twitch("cid", "shh", _Session([(500, {})])).live(("alicetv",)))
    with pytest.raises(streams.TwitchError):
        asyncio.run(streams.Twitch("cid", "shh", _Session([(401, {}), (401, {})])).live(("alicetv",)))


def test_no_logins_makes_no_request():
    session = _Session([])
    assert asyncio.run(streams.Twitch("cid", "shh", session).live(())) == {}
    assert session.posts == [] and session.gets == []

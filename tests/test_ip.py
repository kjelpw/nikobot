import bot


def test_ip_allowed_only_in_either_configured_guild():
    allowed = bot.guild_ids(10, 20)
    assert bot.ip_allowed(10, allowed)
    assert bot.ip_allowed(20, allowed)
    assert not bot.ip_allowed(30, allowed)  # the old `== a or b` bug let this through


def test_ip_refused_in_dms():
    assert not bot.ip_allowed(None, bot.guild_ids(10, 20))


def test_guild_ids_normalises_strings_and_drops_missing():
    assert bot.guild_ids("10", " 20 ", None, "", "junk", True) == frozenset({10, 20})
    assert bot.guild_ids(None, None) == frozenset()
    assert not bot.ip_allowed(0, bot.guild_ids(None, None))


def test_dig_command_is_unchanged():
    assert bot.DIG == ["dig", "-4", "+short", "myip.opendns.com", "@resolver1.opendns.com"]


def test_default_model_is_local_chat(monkeypatch):
    import importlib

    monkeypatch.delenv("NIKOBOT_MODEL", raising=False)
    assert importlib.reload(bot).MODEL == "local-chat:latest"
    monkeypatch.setenv("NIKOBOT_MODEL", "  ")
    assert importlib.reload(bot).MODEL == "local-chat:latest"
    monkeypatch.setenv("NIKOBOT_MODEL", "local-coder:latest")
    assert importlib.reload(bot).MODEL == "local-coder:latest"
    monkeypatch.delenv("NIKOBOT_MODEL")
    importlib.reload(bot)

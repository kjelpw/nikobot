import persona
from persona import Line

BOT = 111
ALICE = 222


# --- mention stripping -------------------------------------------------------

def test_strips_plain_and_nick_mentions_of_the_bot():
    assert persona.clean_text(f"<@{BOT}> hello", BOT) == "hello"
    assert persona.clean_text(f"<@!{BOT}> hello", BOT) == "hello"
    assert persona.clean_text(f"hey <@{BOT}>, what's up", BOT) == "hey what's up"
    assert persona.clean_text(f"<@{BOT}>: snacks?", BOT) == "snacks?"


def test_other_mentions_become_names_not_ids():
    out = persona.clean_text(f"<@{BOT}> is <@{ALICE}> cool? <@999>", BOT, {ALICE: "Alice"})
    assert out == "is @Alice cool? @someone"
    assert "999" not in out and str(ALICE) not in out


def test_roles_channels_and_custom_emoji_are_neutralised():
    out = persona.clean_text("<@&123> see <#456> <:blobcat:789> <a:party:1011>", BOT)
    assert out == "@role see #channel :blobcat: :party:"


def test_only_a_mention_leaves_empty_text():
    assert persona.clean_text(f"  <@{BOT}>  ", BOT) == ""


def test_collapses_blank_lines_and_spaces():
    assert persona.clean_text("a   b\n\n\n c ", BOT) == "a b\nc"


# --- who is being addressed ------------------------------------------------------

def test_addressed_by_direct_mention():
    assert persona.is_addressed(BOT, [BOT])
    assert persona.is_addressed(BOT, [ALICE, BOT])


def test_addressed_by_reply_to_the_bot():
    assert persona.is_addressed(BOT, [], replied_to_author_id=BOT)
    assert not persona.is_addressed(BOT, [], replied_to_author_id=ALICE)


def test_addressed_by_bot_managed_role_mention():
    assert persona.is_addressed(BOT, [], [555], bot_role_id=555)
    assert not persona.is_addressed(BOT, [], [555], bot_role_id=None)
    assert not persona.is_addressed(BOT, [], [556], bot_role_id=555)


def test_everyone_and_here_do_not_count():
    # @everyone/@here never appear in raw_mentions, so they never address the bot
    assert not persona.is_addressed(BOT, [])
    assert not persona.is_addressed(BOT, [ALICE])


# --- prompt building -------------------------------------------------------------

def test_prompt_starts_with_persona_and_maps_roles():
    msgs = persona.build_chat_messages(
        [Line("Alice", "hi bot"), Line("Niko", "Certainly!", is_self=True), Line("Bob", "snack?")]
    )
    assert msgs[0] == {"role": "system", "content": persona.SYSTEM_PROMPT}
    assert msgs[1] == {"role": "user", "content": "Alice: hi bot"}
    assert msgs[2] == {"role": "assistant", "content": "Certainly!"}
    assert msgs[3] == {"role": "user", "content": "Bob: snack?"}


def test_prompt_keeps_only_last_eight_messages():
    msgs = persona.build_chat_messages([Line("A", f"msg {i}") for i in range(20)])
    assert len(msgs) == 1 + persona.MAX_CONTEXT_MESSAGES
    assert msgs[1]["content"] == "A: msg 12"
    assert msgs[-1]["content"] == "A: msg 19"


def test_prompt_truncates_long_messages_and_names():
    msgs = persona.build_chat_messages([Line("N" * 100, "x" * 1000)])
    name, text = msgs[1]["content"].split(": ", 1)
    assert len(text) == persona.MAX_MESSAGE_CHARS and text.endswith("…")
    assert len(name) == persona.MAX_NAME_CHARS


def test_prompt_serious_hint_and_direction():
    msgs = persona.build_chat_messages([Line("A", "x")], serious_hint=True, direction="(go)")
    assert msgs[0]["content"].endswith(persona.SERIOUS_HINT)
    assert msgs[-1] == {"role": "user", "content": "(go)"}
    assert persona.SERIOUS_HINT not in persona.build_chat_messages([Line("A", "x")])[0]["content"]


def test_system_prompt_is_the_slop_parody_and_stays_small():
    p = persona.SYSTEM_PROMPT
    for marker in ("parodies", "slop", "Certainly!", "delve", "synergy", "I hope this helps"):
        assert marker in p
    assert "goblin" not in p.lower()
    # slurs and the serious override stay; nothing else is off limits on a
    # ping (the owner's rule, 2026-11-19)
    for rule in ("No slurs", "serious", "plain, sincere"):
        assert rule in p
    for gone in ("nothing sexual", "never cruel", "hateful"):
        assert gone not in p
    # the owner's ask: confidently wrong, never "I can't access that"
    for rule in ("Never refuse", "invent", "wrong math", "never believable advice"):
        assert rule in p
    # ~420 tokens is the budget. Measured on gpt-oss 2026-11-18: 241 words /
    # 1510 chars came to 426 prompt tokens with a one-line chat message. Don't
    # let it grow: every token is CPU time on a cold prompt cache.
    assert len(p.split()) <= 245
    assert len(p) <= 1530


def test_canned_lines_are_in_persona_voice():
    for line in persona.LOADING_LINES + persona.BROKEN_LINES + persona.BUSY_LINES:
        assert any(w in line for w in ("Certainly", "Great question", "As an AI language model"))
    assert "{days}" in persona.HUSH_LINE


def test_classifier_prompt_contains_only_last_eight_lines():
    lines = [Line("A", f"m{i}") for i in range(10)] + [Line("Niko", "hehe", is_self=True)]
    msgs = persona.build_classifier_messages(lines)
    assert msgs[0]["role"] == "system" and "YES or NO" in msgs[0]["content"]
    body = msgs[1]["content"]
    assert "A: m3" in body and "A: m2" not in body
    assert "Niko (bot): hehe" in body


def test_transcript_lines():
    assert persona.transcript_lines([Line("", "hi"), Line("x", "y", is_self=True)]) == [
        "someone: hi",
        "Niko (bot): y",
    ]


# --- classifier parsing ------------------------------------------------------------

def test_only_exact_yes_is_yes():
    assert persona.classifier_says_yes("YES")
    assert persona.classifier_says_yes("  YES\n")
    for answer in ["yes", "Yes", "YES.", "YES, it is", "NO", "", "Y", None, "maybe YES"]:
        assert not persona.classifier_says_yes(answer), answer


# --- reply tidying ---------------------------------------------------------------

def test_tidy_strips_name_prefix_quotes_and_think_tags():
    assert persona.tidy_reply("Niko: Certainly!") == "Certainly!"
    assert persona.tidy_reply("**Niko:** Certainly!") == "Certainly!"
    assert persona.tidy_reply('"Certainly!"') == "Certainly!"
    assert persona.tidy_reply("<think>hmm</think>Certainly!") == "Certainly!"
    assert persona.tidy_reply("Nikolai was here") == "Nikolai was here"


def test_tidy_keeps_a_tiny_list():
    text = "**Snack Synergy**\n- trail mix — vibrant\n\n- chocolate\nCertainly! \U0001F680"
    assert persona.tidy_reply(text) == "**Snack Synergy**\n- trail mix — vibrant\n- chocolate\nCertainly! \U0001F680"


def test_tidy_caps_lines_and_length():
    assert persona.tidy_reply("\n".join(f"- item {i}" for i in range(20))).count("\n") == persona.MAX_REPLY_LINES - 1
    long = "Certainly! " * 100
    out = persona.tidy_reply(long)
    assert len(out) <= persona.MAX_REPLY_CHARS and out.endswith("Certainly!")


def test_tidy_trims_cut_off_sentence_only_when_truncated():
    text = "Great question! It's not just lunch — it's a journey. And also the"
    assert persona.tidy_reply(text, truncated=True) == "Great question! It's not just lunch — it's a journey."
    assert persona.tidy_reply(text, truncated=False) == text
    assert persona.tidy_reply("no sentence end at all", truncated=True) == "no sentence end at all"
    assert persona.tidy_reply("- one\n- two\n- thr", truncated=True) == "- one\n- two"


def test_tidy_handles_empty():
    assert persona.tidy_reply(None) == ""
    assert persona.tidy_reply("   ") == ""

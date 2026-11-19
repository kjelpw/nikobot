# NikoBot

A small Discord bot (discord.py 2.x) for a private server. It does three things:

- **`!ip`** posts the host's public IPv4 address (via `dig`). It only works in
  the two servers named in `secrets.py`, and never in DMs.
- **Chat.** @mention the bot, or reply to one of its messages, and it answers as
  an over-the-top parody of AI-assistant "slop" that is confidently, gloriously
  wrong. It never refuses and never says it can't see something: ask what's in
  your `/home` and it lists 27 invisible unicorns; Mars has seven moons, two of
  them cheese. Replies come from a local LLM served by [Ollama](https://ollama.com).
- **Go-live posts.** When one of the Twitch channels in `secrets.py` starts
  streaming, it posts once in the configured channel: "*name* is live!" and
  the link, which Discord shows with Twitch's preview.

Apart from go-live posts it never speaks unprompted: only an @mention, a reply
to it, or `!ip` gets a response. It works only in the two servers named in
`secrets.py`, leaves any other server it is added to, and ignores DMs entirely
(no reply, nothing sent to the model).

## Safety

The persona never jokes about serious things, and that is enforced in code, not
left to the model:

- **Crisis language** (self-harm and similar) always gets a fixed, plain reply
  that points to a trusted person, a crisis line or local emergency services.
- **Every mention** first goes through a short LLM check of the last few lines.
  The bot only jokes if that check answers exactly `NO` (nothing serious, nobody
  upset). Anything else, including errors and timeouts, and it says nothing at
  all, even though it was pinged.
- The persona prompt forbids hate, slurs, sexual content and cruelty to a
  specific person. Its made-up answers must be obviously silly, never
  believable advice on medicine, drugs, weapons or anything that could hurt.
- The bot can never ping `@everyone`, `@here`, roles or users. Its replies only
  notify the person it is replying to.
- One ping per person per 20 seconds; extra pings are ignored.
- Every message the bot can see (DMs included) is logged as JSON lines to
  `/data/messages.log`, rotated at 10 × 10 MB. Message content never goes to
  stdout, so it stays out of container logs and Loki.

## Go-live posts

The bot asks Twitch directly every 60 seconds which of the configured channels
are live (Helix *Get Streams*, with an app token). Nobody has to link Twitch to
Discord: Discord's purple "Streaming" status needs Streamer Mode and a linked
account, so it was not used.

- One post per stream. A new stream within an hour of the same person's last
  one (a crash, an OBS restart) counts as the same stream and gets no second post.
- What was posted is kept in `/data/stream_state.json`, so a restart never
  reposts. If that file can't be written, nothing is posted.
- The post is a fixed, plain template ("*name* is live!" and the link), never
  model output, and never pings anyone. The Twitch name has its markdown and
  mentions escaped.
- A failed Twitch check counts as "unknown", not "everyone went offline".

To set it up, register an application at <https://dev.twitch.tv/console/apps>
(any name, OAuth redirect `http://localhost`, category *Other*, client type
*Confidential*). Copy its client ID and a new secret into `secrets.py`.

## Requirements

- **The Message Content intent must be enabled** for the bot in the Discord
  Developer Portal (Bot → Privileged Gateway Intents). Without it the bot cannot
  read messages. It needs no other privileged intents.
- The bot needs Read Message History in the channels where it chats, so it can
  give the model a little context.
- An Ollama server it can reach.

## Configuration

`secrets.py` is a plain Python file. It is gitignored and should be mounted
read-only, by default at `/app/secrets.py`. It defines:

| Name | Meaning |
| --- | --- |
| `token` | the bot's Discord token |
| `guild_permission`, `guild_permission2` | the two server IDs where `!ip` works |
| `stream_channel` | the text channel ID for go-live posts (must be in one of those servers) |
| `twitch_streamers` | list of Twitch logins (or `twitch.tv/...` links) to watch |
| `twitch_client_id`, `twitch_client_secret` | the Twitch application's credentials |

Go-live posts stay off until all four of the last settings are filled in. The
startup log says which are missing.

Keep it **out of the code directory**. discord.py imports the standard library's
`secrets` module, and a `secrets.py` next to `bot.py` would shadow it. The bot
refuses to start if that happens.

Environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `NIKOBOT_MODEL` | `local-chat:latest` | Ollama model to use. Names containing `chat` or `gpt-oss` are sent `"think": "low"`. |
| `OLLAMA_URL` | `http://ollama:11434` | Base URL of the Ollama server. |
| `NIKOBOT_DATA_DIR` | `/data` | Where `messages.log` and `stream_state.json` live. |
| `NIKOBOT_SECRETS` | `/app/secrets.py` | Path to `secrets.py`. |

The LLM is assumed to be slow and shared (CPU only), so requests are kept
small: non-streaming, about 150 output tokens (plus a reasoning budget for
thinking models), the last 8 messages at up to 300 characters each, and a
system prompt of about 250 tokens. One request runs at a time. If the model is
still loading (timeout 240 s), the bot says so in character.

## Chime-ins (built, not wired up)

`chime.py` implements gated, unprompted chime-ins, but `bot.py` doesn't use it:
the bot only speaks when asked. Turning them back on is a code change, not a
setting. The gates below describe that unused code.

A chime-in is an unprompted remark. It happens only if **every** gate passes,
checked cheapest first. Each decision is logged at INFO with its reason (for
example `chime skipped: daily cap`), never with message content.

1. The channel is listed in `NIKOBOT_CHIME_CHANNELS`, and the message is not in a DM.
2. `!hush` is not active.
3. There has been no chime-in in the last 24 hours, across all servers. The
   timestamp is kept in `/data`, so a restart doesn't reset it. If the state file
   can't be written, chime-ins are disabled. If it is corrupt, the 24 hours start
   again from now.
4. The channel is having active banter: at least 4 messages from at least 2
   different humans within 10 minutes.
5. A 2% roll per eligible message passes.
6. None of the last 15 messages hits a conservative serious-topic blocklist
   (death, illness, money, work, legal trouble, politics, feeling sad, and so on).
7. The model is idle and already loaded, so a chime-in never forces a slow reload.
8. An LLM classifier is asked whether the conversation is clearly lighthearted
   banter with nothing serious, sensitive, emotional or important in it. Only an
   exact `YES` passes.

## Running

```sh
docker build -t nikobot .
docker run -d --name nikobot \
  -v /path/to/secrets.py:/app/secrets.py:ro \
  -v nikobot_data:/data \
  -e OLLAMA_URL=http://ollama:11434 \
  nikobot
```

The image runs as UID 1000. `secrets.py` must be readable by that user, and
`/data` writable by it.

## Tests

The pure logic (blocklist, chime gates, mention stripping, prompt building, the
`!ip` check, and so on) is covered by pytest:

```sh
docker run --rm -v "$PWD":/src:ro -w /src python:3.12-slim \
  sh -c "pip install -q -r requirements.txt pytest && python -m pytest -q -p no:cacheprovider"
```

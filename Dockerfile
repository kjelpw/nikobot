FROM python:3.12-slim

# dnsutils - `dig` for the !ip command
# upgrade  - python:*-slim lags Debian security fixes by days; without it a rebuild
#            re-ships whatever vulnerable libssl the base image was cut with
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends dnsutils \
    && rm -rf /var/lib/apt/lists/*

# Non-root. UID 1000 so a mode-0600 secrets.py owned by the usual first host
# user stays readable through the bind mount. /data is created owned by it so a
# fresh volume is writable (an existing root-owned volume needs a one-off chown).
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin nikobot \
    && mkdir -p /data \
    && chown nikobot:nikobot /data

# Code lives in /opt/nikobot, NOT /app: compose bind-mounts the token file at
# /app/secrets.py, and a secrets.py in the script's own directory would shadow
# the stdlib `secrets` module that discord.py 2.x needs to send messages.
WORKDIR /opt/nikobot

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py chime.py images.py imagine.py llm.py lore.py persona.py safety.py streams.py ./

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# /data holds messages.log*, stream_state.json (which go-live streams were
# already posted), chime_state.json and lore.json* (the bot's lore, see lore.py)
WORKDIR /data
USER nikobot

# secrets.py (Discord token) is gitignored and bind-mounted at /app/secrets.py
CMD ["python", "/opt/nikobot/bot.py"]

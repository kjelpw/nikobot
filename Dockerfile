FROM python:3.12-slim

# ffmpeg  - yt-dlp merges audio/video streams for the !talk queue (bot.py:304)
# dnsutils - bot.py:200 shells out to `dig` for the !ip command
# firefox-esr - nikomaker.py drives headless Firefox via Selenium for !nikomaker
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg dnsutils firefox-esr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Deliberate split: Python sets sys.path[0] from the *script's* directory, so
# `from meme import *` and friends still resolve out of /app, while bot.py's
# relative writes - discord.log, log.txt, nikomessage.png, style_library.pickle -
# land in /data where a volume can persist them.
WORKDIR /data

# secrets.py (Discord token) is gitignored and bind-mounted over /app/secrets.py
CMD ["python", "/app/bot.py"]

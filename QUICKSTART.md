# Quick Start Guide

Get NikoBot up and running in 5 minutes!

## Prerequisites

- Python 3.8 or higher
- pip (Python package installer)
- Firefox browser (for NikoMaker command)
- geckodriver (for Selenium)

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install geckodriver

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install firefox-geckodriver
```

**macOS:**
```bash
brew install geckodriver
```

**Windows:**
Download from [geckodriver releases](https://github.com/mozilla/geckodriver/releases) and add to PATH.

### 3. Configure Bot

```bash
cp config.example.py config.py
```

Edit `config.py` and fill in:
```python
DISCORD_TOKEN = "your_bot_token_here"  # From Discord Developer Portal
BOT_ID = 123456789012345678            # Your bot's user ID
IMGFLIP_USERNAME = "your_username"     # For meme generation
IMGFLIP_PASSWORD = "your_password"     # For meme generation
```

**Getting a Discord Bot Token:**
1. Go to https://discord.com/developers/applications
2. Create a new application
3. Go to "Bot" tab
4. Click "Add Bot"
5. Copy the token
6. Enable "Message Content Intent" under Privileged Gateway Intents

## Running the Bot

### Easy Way

```bash
./start_bot.sh
```

### Manual Way

```bash
python bot.py
```

## Verify It's Working

1. Invite the bot to your Discord server
2. Try these commands:
   - `!hi` - Bot should respond "Hello World!"
   - `!ping` - Bot should respond "Pong!"
   - `!help` - Shows all available commands

## Optional: Web Interface

```bash
python app.py
```

Visit http://localhost:5000 to see the web interface.

## Optional: Server Management

For game server management features:

```bash
python server_manager.py
```

## Common Issues

### "config.py not found"
→ Run `cp config.example.py config.py` and edit it

### "No module named 'discord'"
→ Run `pip install -r requirements.txt`

### Bot doesn't respond
→ Check that "Message Content Intent" is enabled in Discord Developer Portal

### "geckodriver not found"
→ Install geckodriver (see step 2 above)

## Next Steps

- Read [README.md](README.md) for full documentation
- See [CONTRIBUTING.md](CONTRIBUTING.md) to add new commands
- Check [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) if upgrading from old version

## Getting Help

Check the logs for errors:
```bash
cat discord.log
```

## That's It! 🎉

Your bot is now running and ready to use!

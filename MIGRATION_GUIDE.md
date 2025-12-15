# Migration Guide: Old NikoBot → Refactored NikoBot

This guide will help you migrate from the old bot to the refactored version.

## What Changed

### Major Changes
1. **Modern discord.py 2.x**: Updated from old discord.py to version 2.3+
2. **Modular Structure**: Commands organized into cogs for better maintainability
3. **Configuration System**: Moved from `secrets.py` to `config.py` with better organization
4. **Updated Dependencies**: All dependencies updated to latest stable versions
5. **Better Error Handling**: Comprehensive error handling throughout
6. **Async Support**: Better async/await patterns for non-blocking operations

### File Mapping

| Old File | New File | Notes |
|----------|----------|-------|
| `bot.py` | `bot.py` | Completely rewritten with cogs |
| `app.py` | `app.py` / `web_app.py` | Modernized Flask app |
| `meme.py` | `utils/meme_generator.py` | Class-based structure |
| `nikomaker.py` | `utils/niko_generator.py` | Updated Selenium methods |
| `dream.py` | `utils/image_generator.py` | Class-based structure |
| `server_manager.py` | `server_manager.py` | Improved logging and error handling |

### Configuration Migration

**Old format (`secrets.py`):**
```python
token = "your_token"
bot_id = 123456
username = "imgflip_user"
password = "imgflip_pass"
guild_permission = 123456
bots_id = []
```

**New format (`config.py`):**
```python
DISCORD_TOKEN = "your_token"
BOT_ID = 123456
IMGFLIP_USERNAME = "imgflip_user"
IMGFLIP_PASSWORD = "imgflip_pass"
GUILD_PERMISSION = 123456
BOT_IDS = []
COMMAND_PREFIX = "!"
```

## Migration Steps

### 1. Create New Configuration

Copy your old secrets:
```bash
# If you have secrets.py
cp config.example.py config.py
# Then manually copy values from secrets.py to config.py
```

### 2. Install Updated Dependencies

```bash
pip install -r requirements.txt
```

This will install:
- discord.py 2.3+
- flask 3.0+
- selenium 4.15+
- Pillow 10.0+
- And other updated dependencies

### 3. Update Selenium Setup

The new version uses modern Selenium methods:
```bash
# Make sure geckodriver is installed
# Ubuntu/Debian:
sudo apt-get install firefox-geckodriver

# macOS:
brew install geckodriver
```

### 4. Test the New Bot

Start the bot:
```bash
python bot.py
```

The bot will:
- Check for `config.py` on startup
- Load all command cogs automatically
- Use proper logging to both file and console

### 5. Start Additional Services (Optional)

Web interface:
```bash
python app.py
# or
python web_app.py
```

Server manager (if you use game server management):
```bash
python server_manager.py
```

## Command Compatibility

All existing commands work the same way! No changes needed for users:

- `!hi`, `!ping`, `!canthtime`, `!snipe` - Work identically
- `!nikomaker`, `!nikomakerd` - Work identically  
- `!stuff`, `!stuffd`, `!aidna`, `!aidnad` - Work identically
- `!dream` - Works identically (if API configured)
- `!server` - Works identically (if server manager running)
- `!join`, `!leave` - Work identically

## Backwards Compatibility

### Old Files
Old files are preserved in the `legacy/` directory for reference:
- `legacy/bot.py`
- `legacy/app.py`
- `legacy/meme.py`
- `legacy/nikomaker.py`
- `legacy/dream.py`
- `legacy/server_manager.py`

### Secrets.py Support
If you want to keep using `secrets.py` temporarily, you can create a shim:

**config.py (temporary shim):**
```python
import secrets

DISCORD_TOKEN = secrets.token
BOT_ID = secrets.bot_id
IMGFLIP_USERNAME = secrets.username
IMGFLIP_PASSWORD = secrets.password
GUILD_PERMISSION = secrets.guild_permission
BOT_IDS = secrets.bots_id
COMMAND_PREFIX = "!"

# Optional AI image generation
API_ENDPOINT = getattr(secrets, 'api_endpoint', '')
LOGIN_ENDPOINT = getattr(secrets, 'login_endpoint', '')
LOGIN_CREDENTIALS = getattr(secrets, 'login', {})
```

## Troubleshooting

### "config.py not found"
Create `config.py` from `config.example.py` and fill in your values.

### "No module named 'discord'"
Run `pip install -r requirements.txt`

### "Selenium element not found"
Update to Selenium 4.15+ and ensure geckodriver is installed.

### Old commands not working
Check the logs for errors. The new bot provides better error messages.

### Bot doesn't respond
1. Check that message_content intent is enabled in Discord Developer Portal
2. Verify your bot token is correct in config.py
3. Check discord.log for errors

## Benefits of the Refactored Version

1. **Better Performance**: Modern async patterns
2. **Easier Maintenance**: Modular code structure
3. **Better Errors**: Comprehensive error handling and logging
4. **Future-Proof**: Uses latest library versions
5. **More Secure**: Better separation of secrets
6. **Extensible**: Easy to add new commands via cogs

## Rolling Back

If you need to roll back to the old version:

```bash
# Stop the new bot
# Restore old files from legacy/
cp legacy/bot.py bot.py
cp legacy/app.py app.py
cp legacy/meme.py meme.py
cp legacy/nikomaker.py nikomaker.py
cp legacy/dream.py dream.py
cp legacy/server_manager.py server_manager.py

# You'll need to reinstall old discord.py version
pip install 'discord.py<2.0'
```

## Getting Help

If you encounter issues:
1. Check `discord.log` for error messages
2. Verify all dependencies are installed
3. Ensure config.py has all required values
4. Review the README.md for setup instructions

## Next Steps

Once migrated:
1. Remove the `*_refactored.py` files (they're duplicates now)
2. Delete `README_new.md` (now copied to README.md)
3. Test all commands in Discord
4. Monitor logs for any issues
5. Consider setting up systemd services for production use

# NikoBot

A modern Discord bot built with discord.py 2.x for use in a private server. Features meme generation, image creation, and game server management.

## Features

- **Meme Generation**: Create memes using the imgflip API
- **NikoMaker**: Generate NikoQuote images with custom text using Selenium
- **AI Image Generation**: Generate images from text prompts (optional)
- **Server Management**: Start and monitor game servers via systemd
- **Utility Commands**: Ping, snipe messages, time display, voice channel controls
- **Web Interface**: Flask-based web interface for log viewing

## Requirements

- Python 3.8 or higher
- Firefox (for NikoMaker feature)
- geckodriver (for Selenium)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/kjelpw/nikobot.git
cd nikobot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure the bot:
```bash
cp config.example.py config.py
```

Edit `config.py` and fill in your values:
- Discord bot token
- Bot ID
- Imgflip credentials (for meme generation)
- Guild permission ID (for server management)
- Optional: AI image generation API endpoints

4. Set up geckodriver for Selenium:
```bash
# On Ubuntu/Debian
sudo apt-get install firefox-geckodriver

# On macOS
brew install geckodriver
```

## Running the Bot

### Main Bot
```bash
python bot_refactored.py
```

### Web Interface (Optional)
```bash
python web_app.py
```
The web interface will be available at `http://localhost:5000`

### Server Manager (Optional)
```bash
python server_manager_refactored.py
```
Required for game server management commands.

## Commands

### Utility Commands
- `!hi` - Bot says hello
- `!ping` - Test bot responsiveness
- `!canthtime` - Display current date and time
- `!snipe` - Show the last non-command message in the channel
- `!join` - Join your voice channel
- `!leave` - Leave the voice channel

### Meme Commands
- `!stuff <text>` - Create a Tony Stark meme
- `!stuffd <text>` - Create a Tony Stark meme and delete command
- `!aidna <text>` - Create an Aidna meme
- `!aidnad <text>` - Create an Aidna meme and delete command

If no text is provided, uses the previous message in the channel.

### Image Generation
- `!nikomaker <text>` - Create a NikoQuote image
- `!nikomakerd <text>` - Create a NikoQuote image and delete command
- `!dream <prompt>` - Generate an AI image from a text prompt (if configured)

### Server Management
- `!server` - List available game servers
- `!server status <name>` - Check server status
- `!server start <name>` - Start a game server (1-hour cooldown)

Available servers: factorio, minecraft, valheim

## Project Structure

```
nikobot/
├── bot_refactored.py           # Main bot entry point
├── web_app.py                  # Flask web interface
├── server_manager_refactored.py # Server management daemon
├── config.example.py           # Configuration template
├── requirements.txt            # Python dependencies
├── commands/                   # Command modules (cogs)
│   ├── __init__.py
│   ├── utility_commands.py
│   ├── meme_commands.py
│   ├── niko_commands.py
│   └── server_commands.py
└── utils/                      # Utility modules
    ├── __init__.py
    ├── meme_generator.py
    ├── niko_generator.py
    └── image_generator.py
```

## Legacy Files

The following files are from the original version and are kept for reference:
- `bot.py` - Original bot implementation
- `app.py` - Original Flask app
- `meme.py` - Original meme generator
- `nikomaker.py` - Original nikomaker
- `dream.py` - Original image generator
- `server_manager.py` - Original server manager

You can safely use the refactored versions instead.

## Development

### Adding New Commands

Commands are organized into cogs in the `commands/` directory. To add a new command:

1. Choose or create an appropriate cog file in `commands/`
2. Add your command function with the `@commands.command()` decorator
3. The command will be automatically loaded when the bot starts

Example:
```python
@commands.command(name='mycommand', help='Description of my command')
async def my_command(self, ctx, *, arg: str = ''):
    """Command implementation"""
    await ctx.send(f'You said: {arg}')
```

### Adding New Utilities

Create new utility classes in the `utils/` directory and import them into the relevant command cog.

## Security Notes

- Never commit `config.py` or any file containing secrets to version control
- The `.gitignore` file is configured to exclude sensitive files
- Store API keys and tokens securely
- Use environment variables for production deployments

## Troubleshooting

### Bot won't start
- Check that `config.py` exists and contains valid values
- Verify your Discord token is correct
- Ensure all dependencies are installed: `pip install -r requirements.txt`

### NikoMaker not working
- Ensure Firefox and geckodriver are installed
- Check that geckodriver is in your PATH
- Try running in non-headless mode for debugging

### Meme generation fails
- Verify your imgflip credentials in `config.py`
- Check your internet connection
- Ensure the imgflip API is accessible

### Server commands not working
- Ensure `server_manager_refactored.py` is running
- Check that the guild ID in config matches your server
- Verify systemd services are configured correctly

## License

This project is for private use.

## Contributing

This is a private project, but suggestions and improvements are welcome!

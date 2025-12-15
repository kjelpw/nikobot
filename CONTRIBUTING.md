# Contributing to NikoBot

Thank you for your interest in contributing to NikoBot! This guide will help you understand the codebase and make contributions.

## Code Structure

```
nikobot/
├── bot.py                    # Main bot entry point
├── app.py                    # Web interface
├── server_manager.py         # Game server management daemon
├── config.example.py         # Configuration template
├── commands/                 # Command modules (Cogs)
│   ├── utility_commands.py  # Basic utility commands
│   ├── meme_commands.py     # Meme generation commands
│   ├── niko_commands.py     # Image generation commands
│   └── server_commands.py   # Server management commands
├── utils/                    # Utility modules
│   ├── meme_generator.py    # Imgflip API wrapper
│   ├── niko_generator.py    # Selenium-based image generator
│   └── image_generator.py   # AI image generation
└── legacy/                   # Old code (for reference)
```

## Development Setup

1. **Clone and setup:**
```bash
git clone https://github.com/kjelpw/nikobot.git
cd nikobot
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Configure the bot:**
```bash
cp config.example.py config.py
# Edit config.py with your values
```

3. **Run the bot:**
```bash
python bot.py
```

## Adding New Commands

### Step 1: Choose the Right Cog

Commands are organized by category:
- **utility_commands.py**: Basic bot functions (ping, time, etc.)
- **meme_commands.py**: Meme generation
- **niko_commands.py**: Image generation
- **server_commands.py**: Server management

Or create a new cog file for a new category.

### Step 2: Write Your Command

```python
@commands.command(name='mycommand', help='What this command does')
async def my_command(self, ctx, *, arg: str = ''):
    """Detailed command description"""
    try:
        # Your command logic here
        await ctx.send('Response')
    except Exception as e:
        await ctx.send(f'Error: {str(e)}')
```

### Step 3: Test Your Command

1. Restart the bot
2. Use `!mycommand` in Discord
3. Check logs for any errors

### Command Best Practices

- **Always use async/await** for Discord operations
- **Handle errors gracefully** with try/except blocks
- **Use ctx.typing()** for long-running operations:
  ```python
  async with ctx.typing():
      # Long operation here
      pass
  ```
- **Clean up resources** (files, connections, etc.)
- **Provide helpful error messages** to users
- **Use type hints** for parameters
- **Document with docstrings**

## Adding New Utilities

### Creating a Utility Class

1. Create a new file in `utils/`:
```python
# utils/my_utility.py
class MyUtility:
    """Description of what this utility does"""
    
    def __init__(self):
        """Initialize the utility"""
        pass
    
    def do_something(self, param: str) -> str:
        """
        Do something useful
        
        Args:
            param: Description of parameter
            
        Returns:
            Description of return value
        """
        # Implementation
        return result
```

2. Import in your command cog:
```python
from utils.my_utility import MyUtility

class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.utility = MyUtility()
```

## Code Style Guidelines

### Python Style
- Follow PEP 8
- Use 4 spaces for indentation
- Maximum line length: 100 characters
- Use descriptive variable names

### Documentation
- Add docstrings to all functions and classes
- Use type hints where appropriate
- Comment complex logic

### Example:
```python
async def process_message(self, ctx, message: str) -> Optional[str]:
    """
    Process a user message and return a response
    
    Args:
        ctx: Discord command context
        message: The message to process
        
    Returns:
        Processed response string, or None if processing fails
    """
    if not message:
        return None
    
    # Process the message
    processed = message.upper()
    return processed
```

## Testing

### Manual Testing
1. Test in a private Discord server first
2. Test edge cases (empty input, special characters, etc.)
3. Test error conditions
4. Check logs for warnings or errors

### Testing Checklist
- [ ] Command responds correctly with valid input
- [ ] Command handles empty/missing input gracefully
- [ ] Command provides helpful error messages
- [ ] Long operations show typing indicator
- [ ] Files/resources are cleaned up
- [ ] No errors in discord.log

## Common Patterns

### Getting Previous Message
```python
def _get_message_text(self, ctx, arg: str) -> str:
    """Get text from argument or previous message"""
    if arg:
        return arg
    if ctx.channel.id in self.bot.prev_messages:
        return self.bot.prev_messages[ctx.channel.id]['content']
    return ''
```

### Deleting Command Message
```python
try:
    await ctx.message.delete()
except discord.Forbidden:
    pass  # Bot doesn't have permission
```

### Sending Files
```python
await ctx.send(file=discord.File('path/to/file.png'))
```

### Creating Embeds
```python
embed = discord.Embed(
    title='Title',
    description='Description',
    color=discord.Color.blue()
)
embed.add_field(name='Field Name', value='Field Value')
await ctx.send(embed=embed)
```

## Logging

Use the logging module instead of print:

```python
import logging
logger = logging.getLogger(__name__)

# In your code:
logger.info('Informational message')
logger.warning('Warning message')
logger.error('Error message', exc_info=True)
```

## Configuration

### Adding New Config Values

1. Add to `config.example.py`:
```python
MY_NEW_SETTING = "default_value"  # Description
```

2. Use in code:
```python
import config

value = config.MY_NEW_SETTING
```

3. Update documentation in README.md

## Working with Discord API

### Important Notes
- **Intents**: Make sure required intents are enabled
- **Rate Limits**: Discord has rate limits; use `ctx.typing()` for long operations
- **Permissions**: Check bot has necessary permissions
- **Message Content**: Requires privileged intent

### Common Discord Operations
```python
# Send message
await ctx.send('Message')

# Send DM
await ctx.author.send('Private message')

# Get guild members
members = ctx.guild.members

# Join voice channel
if ctx.author.voice:
    await ctx.author.voice.channel.connect()

# Get channel history
async for message in ctx.channel.history(limit=10):
    print(message.content)
```

## Working with External APIs

### Best Practices
- Use try/except for all API calls
- Set reasonable timeouts
- Handle rate limits
- Validate responses
- Log errors

### Example:
```python
import requests

def call_api(param: str) -> Optional[str]:
    """Call external API"""
    try:
        response = requests.post(
            'https://api.example.com/endpoint',
            json={'param': param},
            timeout=30
        )
        response.raise_for_status()
        return response.json()['result']
    except requests.Timeout:
        logger.error('API request timed out')
        return None
    except requests.RequestException as e:
        logger.error(f'API request failed: {e}')
        return None
```

## Submitting Changes

1. **Create a branch:**
```bash
git checkout -b feature/my-new-feature
```

2. **Make your changes**

3. **Test thoroughly**

4. **Commit with clear messages:**
```bash
git add .
git commit -m "Add new command for XYZ"
```

5. **Push and create pull request**

## Common Issues

### "Cog not loading"
- Check for syntax errors
- Ensure `async def setup(bot)` exists
- Check imports are correct

### "Command not responding"
- Check bot has message_content intent
- Verify command prefix is correct
- Check logs for errors

### "Permission denied"
- Bot needs appropriate Discord permissions
- Check role hierarchy

## Resources

- [discord.py Documentation](https://discordpy.readthedocs.io/)
- [Discord Developer Portal](https://discord.com/developers/applications)
- [Discord API Documentation](https://discord.com/developers/docs/)

## Questions?

If you have questions:
1. Check the documentation
2. Review existing code for examples
3. Check logs for error messages
4. Ask in Discord (if applicable)

Happy coding! 🤖

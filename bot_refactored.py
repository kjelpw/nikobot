"""
NikoBot - A Discord bot for a private server
Refactored for modern discord.py 2.x
"""
import logging
import datetime
import os
import pickle
import socket
from typing import Optional

import discord
from discord.ext import commands

# Import configuration
try:
    import config
except ImportError:
    print("ERROR: config.py not found!")
    print("Please copy config.example.py to config.py and fill in your values.")
    exit(1)

# Import command modules
from commands import meme_commands, niko_commands, server_commands, utility_commands

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(name)s: %(message)s',
    handlers=[
        logging.FileHandler('discord.log', encoding='utf-8', mode='w'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('nikobot')

# Store previous messages for snipe command
prev_messages = {}


class NikoBot(commands.Bot):
    """Custom Bot class for NikoBot"""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True
        
        super().__init__(
            command_prefix=config.COMMAND_PREFIX,
            intents=intents,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name='YOU'
            )
        )
        
        self.prev_messages = prev_messages
        self.server_socket = None
        
    async def setup_hook(self):
        """Setup hook for loading cogs"""
        # Load command cogs
        await self.load_extension('commands.meme_commands')
        await self.load_extension('commands.niko_commands')
        await self.load_extension('commands.utility_commands')
        await self.load_extension('commands.server_commands')
        logger.info("All command cogs loaded successfully")
        
    async def on_ready(self):
        """Called when the bot is ready"""
        logger.info(f'Logged on as {self.user} (ID: {self.user.id})')
        logger.info(f'Connected to {len(self.guilds)} guilds')
        logger.info('------')
        
    async def on_message(self, message: discord.Message):
        """Handle incoming messages"""
        # Ignore messages from the bot itself or other bots
        if message.author.bot:
            return
            
        # Log the message
        logger.info(f'Message from {message.author} in {message.channel}: {message.content}')
        with open('log.txt', 'a', encoding='utf-8') as f:
            f.write(f'Message from {message.author} in {message.channel}: {message.content}\n')
        
        # Handle mentions
        if self.user.mentioned_in(message) and message.content == f'hi <@{self.user.id}>':
            await message.channel.send(f'hi <@{message.author.id}>')
        
        # Store non-command messages for snipe command
        if not message.content.startswith(config.COMMAND_PREFIX):
            self.prev_messages[message.channel.id] = {
                'content': message.content,
                'author': str(message.author)
            }
        
        # Process commands
        await self.process_commands(message)


def main():
    """Main entry point for the bot"""
    bot = NikoBot()
    
    try:
        bot.run(config.DISCORD_TOKEN, log_handler=None)
    except discord.LoginFailure:
        logger.error("Failed to login. Check your DISCORD_TOKEN in config.py")
    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)


if __name__ == "__main__":
    logger.info(f"Starting NikoBot with discord.py version {discord.__version__}")
    main()

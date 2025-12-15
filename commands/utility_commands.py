"""Utility commands for NikoBot"""
import datetime
import discord
from discord.ext import commands


class UtilityCommands(commands.Cog):
    """Basic utility commands"""
    
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(name='hi', help='Returns a hello')
    async def greet(self, ctx):
        """Say hello"""
        await ctx.send('Hello World!')
        
    @commands.command(name='ping', help='Test response time')
    async def ping(self, ctx):
        """Test bot responsiveness"""
        await ctx.send('Pong!')
        
    @commands.command(name='canthtime', help='Displays the current date and time')
    async def canth_time(self, ctx):
        """Show current time"""
        await ctx.send(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
    @commands.command(name='snipe', help='Shows the last non-command message in the channel')
    async def snipe(self, ctx):
        """Retrieve the last deleted/previous message"""
        if ctx.channel.id in self.bot.prev_messages:
            msg_data = self.bot.prev_messages[ctx.channel.id]
            description = f"{msg_data['author']}: {msg_data['content']}"
            embed = discord.Embed(
                title='Previous Message',
                description=description,
                color=discord.Color.dark_red()
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send('No previous message exists!')
            
    @commands.command(name='join', help='Join your voice channel')
    async def join(self, ctx):
        """Join the user's voice channel"""
        if ctx.author.voice:
            await ctx.author.voice.channel.connect()
            await ctx.send('Joined voice channel!')
        else:
            await ctx.send('You need to be in a voice channel first!')
            
    @commands.command(name='leave', help='Leave the voice channel')
    async def leave(self, ctx):
        """Leave the current voice channel"""
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send('Left voice channel!')
        else:
            await ctx.send('Not in a voice channel!')


async def setup(bot):
    """Setup function for loading the cog"""
    await bot.add_cog(UtilityCommands(bot))

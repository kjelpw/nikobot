"""Meme generation commands for NikoBot"""
import discord
from discord.ext import commands
from utils.meme_generator import MemeGenerator


class MemeCommands(commands.Cog):
    """Commands for generating memes"""
    
    def __init__(self, bot):
        self.bot = bot
        self.meme_gen = MemeGenerator()
        
    def _get_message_text(self, ctx, arg: str) -> str:
        """Get text from argument or previous message"""
        if arg:
            return arg
        
        if ctx.channel.id in self.bot.prev_messages:
            return self.bot.prev_messages[ctx.channel.id]['content']
        
        return ''
        
    @commands.command(name='stuff', help='Create a Tony Stark meme with text')
    async def stuff(self, ctx, *, arg: str = ''):
        """Generate 'stuff' meme"""
        text = self._get_message_text(ctx, arg)
        if not text:
            await ctx.send('No text provided and no previous message found!')
            return
            
        meme_url = self.meme_gen.make_meme_stuff(text)
        if meme_url.startswith('http'):
            await ctx.send(meme_url)
        else:
            await ctx.send(f'Error generating meme: {meme_url}')
            
    @commands.command(name='stuffd', help='Create a Tony Stark meme and delete command')
    async def stuffd(self, ctx, *, arg: str = ''):
        """Generate 'stuff' meme and delete command"""
        text = self._get_message_text(ctx, arg)
        if not text:
            await ctx.send('No text provided and no previous message found!')
            return
            
        meme_url = self.meme_gen.make_meme_stuff(text)
        if meme_url.startswith('http'):
            await ctx.send(meme_url)
        else:
            await ctx.send(f'Error generating meme: {meme_url}')
            
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass  # Bot doesn't have permission to delete
            
    @commands.command(name='aidna', help='Create an Aidna meme with text')
    async def aidna(self, ctx, *, arg: str = ''):
        """Generate 'aidna' meme"""
        text = self._get_message_text(ctx, arg)
        if not text:
            await ctx.send('No text provided and no previous message found!')
            return
            
        meme_url = self.meme_gen.make_meme_aidna(text)
        if meme_url.startswith('http'):
            await ctx.send(meme_url)
        else:
            await ctx.send(f'Error generating meme: {meme_url}')
            
    @commands.command(name='aidnad', help='Create an Aidna meme and delete command')
    async def aidnad(self, ctx, *, arg: str = ''):
        """Generate 'aidna' meme and delete command"""
        text = self._get_message_text(ctx, arg)
        if not text:
            await ctx.send('No text provided and no previous message found!')
            return
            
        meme_url = self.meme_gen.make_meme_aidna(text)
        if meme_url.startswith('http'):
            await ctx.send(meme_url)
        else:
            await ctx.send(f'Error generating meme: {meme_url}')
            
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass  # Bot doesn't have permission to delete


async def setup(bot):
    """Setup function for loading the cog"""
    await bot.add_cog(MemeCommands(bot))

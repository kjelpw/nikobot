"""NikoMaker and image generation commands"""
import os
import discord
from discord.ext import commands
from utils.niko_generator import NikoGenerator
from utils.image_generator import ImageGenerator


class NikoCommands(commands.Cog):
    """Commands for NikoMaker and image generation"""
    
    def __init__(self, bot):
        self.bot = bot
        self.niko_gen = NikoGenerator()
        self.image_gen = ImageGenerator()
        
    def _get_message_text(self, ctx, arg: str) -> str:
        """Get text from argument or previous message"""
        if arg:
            return arg
        
        if ctx.channel.id in self.bot.prev_messages:
            return self.bot.prev_messages[ctx.channel.id]['content']
        
        return ''
        
    @commands.command(name='nikomaker', help='Create a NikoQuote from text')
    async def niko_maker(self, ctx, *, arg: str = ''):
        """Generate NikoQuote image"""
        text = self._get_message_text(ctx, arg)
        
        async with ctx.typing():
            try:
                filename = await self.niko_gen.create_niko_image(text)
                await ctx.send(file=discord.File(filename))
                # Clean up the file after sending
                if os.path.exists(filename):
                    os.remove(filename)
            except Exception as e:
                await ctx.send(f'Error generating NikoQuote: {str(e)}')
                
    @commands.command(name='nikomakerd', help='Create a NikoQuote and delete command')
    async def niko_maker_delete(self, ctx, *, arg: str = ''):
        """Generate NikoQuote image and delete command"""
        text = self._get_message_text(ctx, arg)
        
        async with ctx.typing():
            try:
                filename = await self.niko_gen.create_niko_image(text)
                await ctx.send(file=discord.File(filename))
                # Clean up the file after sending
                if os.path.exists(filename):
                    os.remove(filename)
                    
                # Try to delete the command message
                try:
                    await ctx.message.delete()
                except discord.Forbidden:
                    pass  # Bot doesn't have permission to delete
            except Exception as e:
                await ctx.send(f'Error generating NikoQuote: {str(e)}')
                
    @commands.command(name='dream', help='Generate an image from a text prompt')
    async def dream(self, ctx, *, arg: str = ''):
        """Generate AI image from prompt"""
        if not arg:
            await ctx.send('Please provide a prompt after !dream')
            return
            
        async with ctx.typing():
            try:
                filename = self.image_gen.generate_image(arg)
                if filename:
                    await ctx.send(file=discord.File(filename))
                    # Clean up the file after sending
                    if os.path.exists(filename):
                        os.remove(filename)
                else:
                    await ctx.send('Image generation is not configured. Check config.py')
            except Exception as e:
                await ctx.send(f'Error generating image: {str(e)}')


async def setup(bot):
    """Setup function for loading the cog"""
    await bot.add_cog(NikoCommands(bot))

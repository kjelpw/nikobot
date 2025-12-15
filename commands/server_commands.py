"""Server management commands"""
import pickle
import socket
import discord
from discord.ext import commands
import config


class ServerCommands(commands.Cog):
    """Commands for managing game servers"""
    
    def __init__(self, bot):
        self.bot = bot
        self.server_socket = None
        
    def _get_server_socket(self):
        """Get or create socket connection to server manager"""
        if self.server_socket is None:
            try:
                host = socket.gethostname()
                port = 6969
                self.server_socket = socket.socket()
                self.server_socket.connect((host, port))
            except Exception as e:
                print(f"Failed to connect to server manager: {e}")
                return None
        return self.server_socket
        
    @commands.command(name='server', help='Manage game servers (status, start)')
    async def server(self, ctx, *, arg: str = ''):
        """Manage game servers"""
        # Check if command is allowed in this guild
        if ctx.guild.id != config.GUILD_PERMISSION:
            await ctx.send('This command does not work in this server')
            return
            
        sock = self._get_server_socket()
        if sock is None:
            await ctx.send('Server manager is not available')
            return
            
        try:
            if arg:
                # Send command with arguments
                sock.send(f'server_process {arg}'.encode('utf-8'))
            else:
                # List servers
                sock.send('server_list'.encode('utf-8'))
                
            # Receive response
            response = pickle.loads(sock.recv(1024))
            await ctx.send(embed=response)
        except Exception as e:
            await ctx.send(f'Error communicating with server manager: {str(e)}')
            # Reset socket on error
            self.server_socket = None


async def setup(bot):
    """Setup function for loading the cog"""
    await bot.add_cog(ServerCommands(bot))

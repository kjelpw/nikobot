"""Server manager for controlling game servers via systemd"""
import subprocess
import socket
import pickle
import time
import logging
import discord

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('server_manager')


class ServerManager:
    """Manage game servers via systemd"""
    
    def __init__(self):
        self.games = {
            'factorio': ['factorio.service', False],
            'minecraft': ['minecraft.service', False],
            'valheim': ['valheim.service', False]
        }
        self.timestamp = 0
        self.cooldown_seconds = 3600  # 1 hour cooldown
        
        # Get initial server status
        self.set_status()
        
    def set_status(self):
        """Update status for all game servers"""
        for game_name, (service_name, _) in self.games.items():
            try:
                result = subprocess.run(
                    ['systemctl', 'is-active', service_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5
                )
                status = result.stdout.strip()
                self.games[game_name][1] = (status == 'active')
            except Exception as e:
                logger.error(f"Error checking status for {game_name}: {e}")
                self.games[game_name][1] = False
                
    def server_process(self, arg: str):
        """
        Process server command
        
        Args:
            arg: Command string (e.g., "status minecraft" or "start factorio")
            
        Returns:
            Discord embed with response
        """
        parts = arg.split()
        
        if len(parts) < 2:
            return discord.Embed(
                title='Error',
                description='Need to specify: <command> <server_name>',
                color=discord.Color.red()
            )
            
        command = parts[0]
        game_name = parts[1]
        
        if game_name not in self.games:
            return discord.Embed(
                title='Error',
                description=f'Unknown server: {game_name}',
                color=discord.Color.red()
            )
            
        if command == 'status':
            return self.server_status(game_name)
        elif command == 'start':
            return self.start(game_name)
        else:
            return discord.Embed(
                title='Error',
                description=f'Unknown command: {command}. Use "status" or "start"',
                color=discord.Color.red()
            )
            
    def server_status(self, game_name: str):
        """
        Get status of a game server
        
        Args:
            game_name: Name of the game server
            
        Returns:
            Discord embed with server status
        """
        self.set_status()  # Refresh status
        
        if self.games[game_name][1]:
            return self._server_on_embed(game_name)
        else:
            return self._server_off_embed(game_name)
            
    def _server_on_embed(self, game_name: str):
        """Create embed for server that is running"""
        embed = discord.Embed(
            title=f'{game_name.capitalize()} Server',
            description=f'Status of the {game_name} server',
            color=discord.Color.green()
        )
        embed.add_field(name='Status', value='🟢 ONLINE', inline=False)
        embed.add_field(name='IP', value=self.get_ip(), inline=False)
        return embed
        
    def _server_off_embed(self, game_name: str):
        """Create embed for server that is not running"""
        embed = discord.Embed(
            title=f'{game_name.capitalize()} Server',
            description=f'Status of the {game_name} server',
            color=discord.Color.red()
        )
        embed.add_field(name='Status', value='🔴 OFFLINE', inline=False)
        embed.add_field(name='IP', value=self.get_ip(), inline=False)
        embed.add_field(
            name='Start Server',
            value=f'Use: `!server start {game_name}`',
            inline=False
        )
        return embed
        
    def start(self, game_name: str):
        """
        Start a game server
        
        Args:
            game_name: Name of the game server to start
            
        Returns:
            Discord embed with result
        """
        current_time = int(time.time())
        
        # Check cooldown
        if current_time - self.timestamp < self.cooldown_seconds:
            remaining = self.cooldown_seconds - (current_time - self.timestamp)
            minutes = remaining // 60
            return discord.Embed(
                title='⏱️ Server Start Cooldown',
                description=f'Servers can only be started once per hour.\n\nTime remaining: {minutes} minutes',
                color=discord.Color.orange()
            )
            
        # Refresh status
        self.set_status()
        
        # Check if already running
        if self.games[game_name][1]:
            return discord.Embed(
                title='Already Running',
                description=f'The {game_name} server is already online!',
                color=discord.Color.blue()
            )
            
        # Stop other servers
        self._stop_others(game_name)
        
        # Start the requested server
        try:
            logger.info(f'Starting {game_name} server')
            subprocess.run(
                ['systemctl', 'start', self.games[game_name][0]],
                check=True,
                timeout=30
            )
            self.timestamp = current_time
            
            # Wait a moment for service to start
            time.sleep(2)
            
            return self.server_status(game_name)
        except Exception as e:
            logger.error(f'Error starting {game_name}: {e}')
            return discord.Embed(
                title='Error',
                description=f'Failed to start {game_name} server: {str(e)}',
                color=discord.Color.red()
            )
            
    def _stop_others(self, game_name: str):
        """Stop all game servers except the specified one"""
        for name, (service_name, is_running) in self.games.items():
            if name != game_name and is_running:
                try:
                    logger.info(f'Stopping {name} server')
                    subprocess.run(
                        ['systemctl', 'stop', service_name],
                        timeout=30
                    )
                except Exception as e:
                    logger.error(f'Error stopping {name}: {e}')
                    
    def get_ip(self) -> str:
        """Get the public IP address of the server"""
        try:
            result = subprocess.run(
                ['dig', '+short', 'myip.opendns.com', '@resolver1.opendns.com'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5
            )
            ip = result.stdout.strip()
            return ip if ip else 'Unable to determine IP'
        except Exception as e:
            logger.error(f'Error getting IP: {e}')
            return 'Unable to determine IP'
            
    def server_list(self):
        """Get list of available servers"""
        embed = discord.Embed(
            title='🎮 Available Game Servers',
            description='Get a server\'s status using `!server status <name>`',
            color=discord.Color.blue()
        )
        
        game_list = '\n'.join(f'• {name}' for name in self.games.keys())
        embed.add_field(name='Servers', value=game_list, inline=False)
        
        return embed


def main():
    """Main entry point for server manager"""
    logger.info('Starting server manager')
    
    host = socket.gethostname()
    port = 6969
    
    # Create socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((host, port))
        server_socket.listen(1)
        logger.info(f'Server manager listening on {host}:{port}')
        
        manager = ServerManager()
        
        while True:
            logger.info('Waiting for connection...')
            client_socket, address = server_socket.accept()
            logger.info(f'Connection from: {address}')
            
            try:
                while True:
                    data = client_socket.recv(1024).decode('utf-8')
                    if not data:
                        break
                        
                    logger.info(f'Received command: {data}')
                    
                    if data.startswith('server_process '):
                        arg = data.partition(' ')[2]
                        response = manager.server_process(arg)
                        client_socket.send(pickle.dumps(response))
                    elif data == 'server_list':
                        response = manager.server_list()
                        client_socket.send(pickle.dumps(response))
                    else:
                        logger.warning(f'Unknown command: {data}')
                        
            except Exception as e:
                logger.error(f'Error handling client: {e}')
            finally:
                client_socket.close()
                logger.info('Client disconnected')
                
    except KeyboardInterrupt:
        logger.info('Shutting down server manager')
    finally:
        server_socket.close()


if __name__ == "__main__":
    main()

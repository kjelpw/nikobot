from pydoc import describe
import subprocess
import discord
import socket
import pickle
import time
#https://python.plainenglish.io/send-an-embed-with-a-discord-bot-in-python-61d34c711046

class ServerManager():
    def __init__(self):
        self.games = {
            'factorio': ['factorio.service', False],
            'minecraft': ['minecraft.service', False],
            'valheim': ['valheim.service', False]
        }
        self.timestamp = 0
        
        # get server status
        self.set_status()

    def set_status(self):
        for key, value in self.games.items():
            status = subprocess.run(['systemctl', 'is-active', value[0]], stdout=subprocess.PIPE).stdout.decode('utf-8')
            if 'inactive' in status or 'failed' or 'could not be found' in status:
                self.games[key][1] = False
            else:
                self.games[key][1] = True

    def server_process(self, arg):
        print('processing')
        arg = arg.split()
        if len(arg) > 1:
            if arg[0] == 'status':
                game_name = arg[1]
                return self.server_status(game_name)
            if arg[0] == 'start':
                game_name = arg[1]
                return self.start(game_name)              
            else:
                return discord.Embed(title='Response', description='Command not Found')
        else:
            return discord.Embed(title='Response', description='Need to specify args')

    def server_status(self, game_name):
        status = ''
        try:
            status = subprocess.run(['systemctl', 'is-active', self.games[game_name][0]], stdout=subprocess.PIPE).stdout.decode('utf-8')
        except KeyError:
            return discord.Embed(title='Response', description='Command not Found')

        if 'inactive' in status:
            return self.server_off(game_name)
        elif 'active' in status:
            return self.server_on(game_name)
        else:
            return self.server_off(game_name)

    def server_on(self, game_name):
        description = 'Status of the ' + game_name + ' server'
        embed = discord.Embed(title=game_name + ' Server', description=description, color=discord.Color.green())
        embed.add_field(name='Status', value='ON')
        embed.add_field(name='IP', value=self.ip())
        return embed

    def server_off(self, game_name):
        description = 'Status of the ' + game_name + ' server'
        embed = discord.Embed(title=game_name + ' Server', description=description, color=discord.Color.dark_red())
        embed.add_field(name='Status', value='OFF')
        embed.add_field(name='IP', value=self.ip())
        embed.add_field(name='Start the server with the following command:', value='!server start ' + game_name)
        return embed

    def start(self, game_name):
        #lets update the server statuses
        self.set_status()

        # can only start a server every hour
        current_time = int(time.time())
        #current_time = 9223372036854775807
        print('timestamp: ' + str(self.timestamp))
        if current_time - self.timestamp > 3600:
            if not self.games[game_name][1]:
                #first, stop other game servers
                self.stop_others(game_name)

                #now start the requested server
                print('Starting: ' + game_name)
                subprocess.run(['systemctl', 'start', self.games[game_name][0]], stdout=subprocess.PIPE)
                self.timestamp = current_time
            return self.server_status(game_name)
        else:
            return discord.Embed(title='Server Start Cooldown', description='Servers can only be started once every hour', color=discord.Color.dark_red())

    #stop all other game servers
    def stop_others(self, game_name):
        for key, value in self.games.items():
            if not key == game_name:
                print('Stopping: ' + key)
                subprocess.run(['systemctl', 'stop', self.games[key][0]], stdout=subprocess.PIPE)

    # Returns the ip of the server
    def ip(self):
        return subprocess.run(['dig', '+short', 'myip.opendns.com', '@resolver1.opendns.com'], stdout=subprocess.PIPE).stdout.decode('utf-8')

    def server_list(self):
        embed = discord.Embed(title='List of available servers', description='Get a server\'s status using \"!server status [name]\"', color=discord.Color.green())
        
        game_list = ''
        for game_name in self.games:
            game_list += (game_name + ' \n')
        embed.add_field(name='Servers: ', value=game_list)
        return embed

if __name__ == "__main__":
    print('starting server manager')
    host = socket.gethostname()
    port = 6969

    #close an old socket if it exists
    s = socket.socket()
    s.close()

    s = socket.socket()
    s.bind((host, port))
    s.listen(1)
    manager = ServerManager()
    print('Server manager started')

    client_socket, address = s.accept()
    print("Connection from: " + str(address))
    while True:
        data = client_socket.recv(1024).decode('utf-8')
        if not data:
            break
        print('From connection: ' + data)
        if 'server_process' in data:
            # pass the arg on
            arg = data.partition(' ')[2]
            print('Debug: ' + arg)
            response = manager.server_process(arg)
            client_socket.send(pickle.dumps(response))
        elif 'server_list' in data:
            response = manager.server_list()
            client_socket.send(pickle.dumps(response))

    client_socket.close()

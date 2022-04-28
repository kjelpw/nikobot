from pydoc import describe
import subprocess
import discord
import socket
import pickle
#https://python.plainenglish.io/send-an-embed-with-a-discord-bot-in-python-61d34c711046

games = {
    'factorio': 'factorio.service',
    'minecraft': 'minecraft.service',
    'valheim': 'valheim.service'
}

def server_process(arg):
    arg = arg.split()
    if len(arg) > 1:
        if arg[0] == 'status':
            game_name = arg[1]
            return status(game_name)
        if arg[0] == 'start':
            game_name = arg[1]
            return start(game_name)              
        else:
            return discord.Embed(title='Response', description='Command not Found')
    else:
        return discord.Embed(title='Response', description='Need to specify args')

def status(game_name):
    status = ''
    status = subprocess.run(['systemctl', 'status', games[game_name]], stdout=subprocess.PIPE).stdout.decode('utf-8')

    if 'inactive' in status or 'failed' in status:
        return server_off(game_name)
    else:
        return server_on(game_name)

def server_on(game_name):
    description = 'Status of the ' + game_name + ' server'
    embed = discord.Embed(title=game_name + ' Server', description=description, color=discord.Color.green())
    embed.add_field(name='Status', value='ON')
    embed.add_field(name='IP', value=ip())
    return embed

def server_off(game_name):
    description = 'Status of the ' + game_name + ' server'
    embed = discord.Embed(title=game_name + ' Server', description=description, color=discord.Color.dark_red())
    embed.add_field(name='Status', value='OFF')
    embed.add_field(name='IP', value=ip())
    embed.add_field(name='Start the server with the following command:', value='!server start ' + game_name)
    return embed

def start(game_name):
    subprocess.run(['systemctl', 'start', games[game_name]], stdout=subprocess.PIPE)
    return status(game_name)

# Returns the ip of the server
def ip():
    return subprocess.run(['dig', '+short', 'myip.opendns.com', '@resolver1.opendns.com'], stdout=subprocess.PIPE).stdout.decode('utf-8')

def server_list():
    embed = discord.Embed(title='List of available servers', description='Get a server\'s status using \"!server status [name]\"', color=discord.Color.green())
    
    game_list = ''
    for game_name in games:
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
            response = server_process(data.partition(' ')[2])
            client_socket.send(pickle.dumps(response))
        elif 'server_list' in data:
            response = server_list()
            client_socket.send(pickle.dumps(response))

    client_socket.close()

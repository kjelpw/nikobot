from pydoc import describe
import subprocess
import discord
#https://python.plainenglish.io/send-an-embed-with-a-discord-bot-in-python-61d34c711046
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
            return 'Command not found'
    else:
        return 'Need more command args (see help)'

def status(game_name):
    status = ''
    if game_name == 'factorio':
        status = subprocess.run(['systemctl', 'status', 'factorio.service'], stdout=subprocess.PIPE).stdout.decode('utf-8')
    elif game_name == 'minecraft':
        status = subprocess.run(['systemctl', 'status', 'minecraft.service'], stdout=subprocess.PIPE).stdout.decode('utf-8')
    if 'active' in status:
        return server_on(game_name)
    else:
        return server_off(game_name)

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
    if game_name == 'factorio':
        subprocess.run(['systemctl', 'start', 'factorio.service'], stdout=subprocess.PIPE)
    elif game_name == 'minecraft':
        subprocess.run(['systemctl', 'start', 'minecraft.service'], stdout=subprocess.PIPE)
    return status(game_name)

# Returns the ip of the server
def ip():
    return subprocess.run(['dig', '+short', 'myip.opendns.com', '@resolver1.opendns.com'], stdout=subprocess.PIPE).stdout.decode('utf-8')

def server_list():
    embed = discord.Embed(title='List of available servers', description='Get a server\'s status using \"!server status [name]\"', color=discord.Color.green())
    game_list = 'factorio\n'
    embed.add_field(name='Servers: ', value=game_list)
    return embed
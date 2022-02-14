# -*- coding: utf-8 -*-
'''
Created Nov 2019

@author: canth
'''
import logging
import datetime
import discord
from discord.ext import commands,tasks
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver import FirefoxOptions
import wget
import subprocess
import numpy as np

from meme import *
from dotenv import load_dotenv

discord_niko_token = secrets.token
comm_prefix='!'
logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)
#logging.basicConfig(level=logging.WARNING)

cmds = {
    'hi': 'returns a hello',
    'ping': 'test response time',
    'help': 'displays helpful messages',
    'CanthTime': 'displays the current date and time in CanthLand',
    'NikoMaker': 'Converts the previous or current message into a NikoQuote',
    'stuff': 'Tony Stark a message'
}
prev_messages = {}

print(discord.__version__)

intents = discord.Intents().all()
nikobot = commands.Bot(command_prefix=comm_prefix, intents=intents, activity=discord.Activity(type=discord.ActivityType.watching, name='YOU'))

@nikobot.event
async def on_ready():
    print('Logged on as {0}!'.format(secrets.bot_id))

@nikobot.event
async def on_message(message):
    if message.author.id == secrets.bot_id or message.author == 212783784163016704 or message.author == 172002275412279296 or message.author == 234395307759108106 or message.author == 303730326692429825:
        #so bot doesn't reply to itself or other bots
        return
    print('Message from {0.author} in {0.channel}: {0.content}'.format(message))
    if message.content == 'hi <@!' + str(secrets.bot_id) + '>':
        await message.send('hi <@{0.author.id}>'.format(message))
    
    if message.content[:1] != comm_prefix:
        prev_messages[message.channel] = message.content

    await nikobot.process_commands(message)


# @nikobot.command(name='help', help=)
# async def HelpCommand(ctx):
#     embed = discord.Embed(
#         title='Nikobot Help',
#         color=discord.Color.dark_red()
#     )
#     for key in cmds:
#         embed.add_field(name=key, value = cmds[key])
#     await ctx.send(embed)


@nikobot.command(name='hi', help='returns a hello')
async def greet(ctx):
    await ctx.send('Hello World!')


@nikobot.command(name='ping', help='test response time')
async def ping(ctx):
    await ctx.send('Pong!')


async def unrecognized_cmd(ctx):
    await ctx.send('Unrecognized Command: use !help')


@nikobot.command(name='canthtime', help='displays the current date and time in CanthLand')
async def canth_time(ctx):
    await ctx.send(datetime.datetime.now())


@nikobot.command(name='nikomaker', help='Converts the previous or current message into a NikoQuote')
async def niko_maker(ctx, *, arg=''):
    niko_message = ''
    if arg != '':
        niko_message = arg
    else:
        niko_message = prev_messages.get(ctx.channel)

    #navigate to page
    opts = FirefoxOptions()
    opts.add_argument('--headless')
    driver = webdriver.Firefox(options=opts)
    driver.get('https://gh.princessrtfm.com/niko.html')
    assert 'NikoMaker' in driver.title

    #find and click normal face
    face = driver.find_element_by_css_selector('.normal')
    face.click()

    #find and use the textbox
    textbox = driver.find_element_by_id('message')
    textbox.clear()
    if niko_message == None:
        niko_message = ''
    textbox.send_keys(niko_message)

    #download the image
    with open('nikomessage.png', 'wb') as file:
        file.write(driver.find_element_by_id('render').screenshot_as_png)

    #send the image
    await ctx.channel.send(file=discord.File('nikomessage.png'))
    driver.close()


@nikobot.command(name='stuffd', help='Tony Stark a message and delete')
async def stuffd(ctx, *, arg=''):
    meme_url = ''

    if arg != '':
        meme_url = make_meme_stuff(arg)
    else:
        meme_url = make_meme_stuff(prev_messages.get(ctx.channel))
    await ctx.channel.send(meme_url)
    await ctx.message.delete()


@nikobot.command(name='stuff', help='Tony Stark a message')
async def stuff(ctx, *, arg=''):
    meme_url = ''

    if arg != '':
        meme_url = make_meme_stuff(arg)
    else:
        meme_url = make_meme_stuff(prev_messages.get(ctx.channel))
    await ctx.channel.send(meme_url)


@nikobot.command(name='aidnad', help='it\'s him')
async def aidnad(ctx, *, arg=''):
    meme_url = ''

    if arg != '':
        meme_url = make_meme_aidna(arg)
    else:
        meme_url = make_meme_aidna(prev_messages.get(ctx.channel))
    await ctx.channel.send(meme_url)
    await ctx.message.delete()


@nikobot.command(name='aidna', help='he is here')
async def aidna(ctx, *, arg=''):
    meme_url = ''

    if arg != '':
        meme_url = make_meme_aidna(arg)
    else:
        meme_url = make_meme_aidna(prev_messages.get(ctx.channel))
    await ctx.channel.send(meme_url)


@nikobot.command(name='join', help='join a voice channel')
async def join(ctx):
    if ctx.author.voice:
        await ctx.author.voice.channel.connect()


@nikobot.command(name='leave', help='leave a voice channel')
async def leave(ctx):
    voice = ctx.guild.voice_client
    if voice.is_connected():
        await voice.disconnect()


#@nikobot.command()
async def talk(ctx):
    await join(ctx)


# @nikobot.command(name='log', help='does literally nothing ;)')
# async def log(ctx, num=1, name='214605185765343232'):
#     #delete the call so Ashyan doesn't spam it
#     await ctx.message.delete()

#     messages = await ctx.channel.history(limit=num).flatten()
#     print(type(messages))
#     messages = np.asarray(messages)

#     np.save('mess', messages)

@nikobot.event
async def on_member_update(before, after):
    if after.activity != None:
        if len(after.activities) > 1:
            print(after.name + " is playing " + after.activities[1].name)

if __name__ == "__main__" :
    nikobot.run(discord_niko_token)
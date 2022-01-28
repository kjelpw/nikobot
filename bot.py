# -*- coding: utf-8 -*-
'''
Created Nov 2019

@author: canth
'''
import datetime
import discord
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver import FirefoxOptions
import wget
import subprocess

from meme import *
import secrets

discord_niko_token = secrets.token

print(discord.__version__)

class Niko(discord.Client):
    cmds = ['hi', 'ping', 'help', 'CanthTime', 'NikoMaker', 'stuff']
    descs = ['returns a hello', 'test response time', 'displays helpful messages', 'displays the current date and time in CanthLand', 'Converts the previous or current message into a NikoQuote', 'tony a message']
    prev_messages = {}

    async def on_ready(self):
        print('Logged on as {0}!'.format(self.user))

    async def on_message(self, message):
        if message.author == self.user or message.author == 212783784163016704 or message.author == 172002275412279296 or message.author == 234395307759108106 or message.author == 303730326692429825:
            #so bot doesn't reply to itself or other bots
            return
        print('Message from {0.author} in {0.channel}: {0.content}'.format(message))
        await self.process_message(message)

    #processes message contents
    async def process_message(self, message):
        # command handling
        if message.content.startswith('!'):
            await self.process_command(message)
        # greeting response
        elif message.content == 'hi <@!' + secrets.bot_id + '>':
            await self.send_message(message.channel, 'hi <@{0.author.id}>'.format(message))
        #save the message and channel it was in if another command follows up
        else:
            self.prev_messages[message.channel] = message.content

    #processes command in the messages
    async def process_command(self, message):
        mess = message.content[1:].split()[0].lower()
        if mess == 'hi':
            await self.greet(message)
        elif mess == 'ping':
            await self.ping(message)
        elif mess == 'help':
            await self.help(message)
        elif mess == 'canthtime':
            await self.canth_time(message)
        elif mess == 'nikomaker':
            await self.niko_maker(message)
        elif mess == 'stuff':
            await self.stuff(message)

    async def greet(self, message):
        await self.send_message(message.channel, 'Hello World!')

    async def ping(self, message):
        await self.send_message(message.channel, 'Pong!')

    async def unrecognized_cmd(self, message):
        await self.send_message(message.channel, 'Unrecognized Command: use !help')

    async def help(self, message):
        help_mes = "Hey! I'm Niko!\nEvery command must start with !\n+---------------------+\nCommands:\n"
        for i in range(len(self.cmds)):
            help_mes += '!' + self.cmds[i] + '\n'
            help_mes += self.descs[i] + '\n' + '+---------------------+\n'
        await self.send_message(message.channel, help_mes)

    async def canth_time(self, message):
        await self.send_message(message.channel, datetime.datetime.now())

    async def niko_maker(self, message):
        niko_message = ''
        if len(message.content.split()) > 1:
            niko_message = message.content[11:]
        else:
            niko_message = self.prev_messages.get(message.channel)

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
        await message.channel.send(file=discord.File('nikomessage.png'))
        driver.close()

    async def stuff(self, message):
        meme_url = ''

        if len(message.content.split()) > 1:
            meme_url = make_meme(message.content[7:])
        else:
            meme_url = make_meme(self.prev_messages.get(message.channel))
        await message.channel.send(meme_url)

    async def send_message(self, channel, message):
        await channel.send(message)


client = Niko()
client.run(discord_niko_token)

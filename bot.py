# -*- coding: utf-8 -*-
'''
Created on Sat Apr 11 12:02:31 2020

@author: canth
'''
import datetime
import discord
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver import FirefoxOptions
import wget
import subprocess

import meme
import secrets

discord_niko_token = secrets.token

print(discord.__version__)

class Niko(discord.Client):
    cmds = ['hi', 'ping', 'help', 'CanthTime', 'NikoMaker', 'mc_ip', 'stuff']
    descs = ['returns a hello', 'test response time', 'displays helpful messages', 'displays the current date and time in CanthLand', 'Converts the previous message into a NikoQuote. Only works for just sent messages', 
            'returns the ip of the mc server', 'meme the previous message']
    prev_messages = {}

    async def on_ready(self):
        print('Logged on as {0}!'.format(self.user))

    async def on_message(self, message):
        if message.author == self.user or message.author == 212783784163016704 or message.author == 172002275412279296 or message.author == 234395307759108106 or message.author == 303730326692429825:
            #so bot doesn't reply to itself or print its messages
            return
        print('Message from {0.author} in {0.channel}: {0.content}'.format(message))
        await self.process_message(message)

    #processes message contents
    async def process_message(self, message):
        # command handling
        if message.content.startswith('!'):
            await self.process_command(message)
        # greeting response
        elif message.content == 'hi <@!640995889854283778>':
            await self.send_message(message.channel, 'hi <@{0.author.id}>'.format(message))
        #save the message and channel it was in if another command follows up
        else:
            self.prev_messages[message.channel] = message.content

        #not command message, save it
        # else:
        #     message_file = open('messages.txt', 'a')
        #     message_file.write(str(message.content))
        #     message_file.close()

    #processes command in the messages
    async def process_command(self, message):
        mess = message.content[1:].split().lower()
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
        elif mess == 'mc':
            await self.mc_ip(message)
        elif mess == 'stuff':
            await self.stuff(message)
        # else:
        #     await self.unrecognized_cmd(message)

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
        niko_message = self.prev_messages.get(message.channel)
        if niko_message == None:
            niko_message = ''
        textbox.send_keys(niko_message)

        #download the image
        with open('nikomessage.png', 'wb') as file:
            file.write(driver.find_element_by_id('render').screenshot_as_png)

        #send the image
        await message.channel.send(file=discord.File('nikomessage.png'))
        driver.close()

    async def mc_ip(self, message):
        if message.guild.id == 221738707621904388:
            ip = subprocess.run(['dig', '+short', 'myip.opendns.com', '@resolver1.opendns.com'], stdout=subprocess.PIPE).stdout.decode('utf-8')
            await message.channel.send(ip)

    async def stuff(self, message):
        print('meme time!!!')
        

    async def send_message(self, channel, message):
        await channel.send(message)


client = Niko()
client.run(discord_niko_token)

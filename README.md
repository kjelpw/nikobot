# NikoBot
A discord bot using discord.py for use in a private server.


# Noteable Things
The !NikoMaker command uses Selenium to navigate to https://gh.princessrtfm.com/niko.html and create an image with the specified text

The !stuff command accesses the imgflip api to create a meme image of the specified text


# Needed Stuff
`secrets.py` should be a file containing the following variables

#### The username of an imgflip account: `username`
#### The password of an imgflip account: `password`
#### The discord auth token your bot will use: `token`
#### The user id of the bot: `bot_id`
#### The guild id where the server command may be used: `guild_permission`
#### The list of bot ids in the server, so we can avoid responding to them: `bots_id`


# Adding to the bot
To add a command to the bot

1. Create a function that describes implements your command
2. Add a decorator to your function nikobot.command
3. In the decorator specify the actual command that will be called by setting name
4. Optionally, specify the help text by setting help

# TODO
- [X] Some sort of web interface to control and monitor the bot, possibly using Flask?
- [ ] Play saved sounds clips like a soundboard (Unoriginal, but good for learning how to transmit audio)
- [ ] Receive audio
- [ ] Speech jammer
- [ ] Command to save audio over the past few minutes, specified by a command argument?
- [ ] Save user activity over bot restarts
- [ ] Using past messages, train a ml model to speak like a server member 
- [X] A command named "snipe", which outputs the most recent message
- [X] Be able to start up game servers and get status of running servers
- [X] Microservice things 
- [ ] Solve world hunger
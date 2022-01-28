# NikoBot

A discord bot using discord.py for use in a private server.

# Needed Stuff

secrets.py should be a file containing the following variables

#### The username of an imgflip account
`username`
#### The password of an imgflip account
`password`
#### The discord auth token your bot will use
`token`
#### The user id of the bot
`bot_id`

# Adding to the bot
To add a command to the bot you need to do four things

1. add the command name to the cmds array
2. add a description of the command to the descs array
3. add the command to the process_command function
4. write a function that is called to execute your command
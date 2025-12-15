# Deployment Checklist for NikoBot

Use this checklist to ensure proper deployment of the refactored NikoBot.

## Pre-Deployment

### 1. System Requirements
- [ ] Python 3.8 or higher installed
- [ ] pip package manager available
- [ ] Firefox browser installed (for NikoMaker)
- [ ] geckodriver installed (for Selenium)
- [ ] systemd available (for server management, optional)

### 2. Discord Setup
- [ ] Bot created in Discord Developer Portal
- [ ] Bot token obtained
- [ ] Bot invited to server with appropriate permissions
- [ ] **Message Content Intent** enabled in Developer Portal (Critical!)
- [ ] Bot's user ID recorded

### 3. External Services (Optional)
- [ ] Imgflip account created (for meme generation)
- [ ] Imgflip username and password available
- [ ] AI image generation API configured (if using dream command)

## Installation

### 4. Code Setup
- [ ] Repository cloned
- [ ] Navigate to project directory
- [ ] Virtual environment created (recommended):
  ```bash
  python3 -m venv venv
  source venv/bin/activate  # On Windows: venv\Scripts\activate
  ```

### 5. Dependencies
- [ ] Install Python dependencies:
  ```bash
  pip install -r requirements.txt
  ```
- [ ] Verify discord.py installed:
  ```bash
  python3 -c "import discord; print(discord.__version__)"
  ```
- [ ] Should show version 2.3.0 or higher

### 6. Configuration
- [ ] Copy config template:
  ```bash
  cp config.example.py config.py
  ```
- [ ] Edit config.py and fill in all required values:
  - [ ] DISCORD_TOKEN
  - [ ] BOT_ID
  - [ ] COMMAND_PREFIX (default: !)
  - [ ] BOT_IDS (list of bot IDs to ignore)
  - [ ] GUILD_PERMISSION (for server commands)
  - [ ] IMGFLIP_USERNAME (for memes)
  - [ ] IMGFLIP_PASSWORD (for memes)
  - [ ] API endpoints (if using dream command)
- [ ] Verify config.py is in .gitignore
- [ ] **Never commit config.py to version control!**

### 7. Directory Setup
- [ ] Create dream directory:
  ```bash
  mkdir -p dream
  ```
- [ ] Verify write permissions for log files
- [ ] Verify write permissions for dream directory

## Testing

### 8. Basic Validation
- [ ] Verify all Python files compile:
  ```bash
  python3 -m py_compile bot.py app.py server_manager.py commands/*.py utils/*.py
  ```
- [ ] Check configuration loads:
  ```bash
  python3 -c "import config; print('Config OK')"
  ```

### 9. Bot Testing
- [ ] Start the bot:
  ```bash
  python bot.py
  ```
- [ ] Bot shows "Logged on as..." message
- [ ] No errors in console
- [ ] Bot shows as online in Discord

### 10. Command Testing
Test each command in Discord:
- [ ] `!hi` - Should respond "Hello World!"
- [ ] `!ping` - Should respond "Pong!"
- [ ] `!help` - Should show help menu
- [ ] `!canthtime` - Should show current time
- [ ] `!snipe` - Should work after sending a message
- [ ] `!stuff test` - Should generate meme (if configured)
- [ ] `!nikomaker test` - Should generate image (if geckodriver works)
- [ ] `!dream test` - Should generate AI image (if configured)
- [ ] `!server` - Should list servers (if configured)
- [ ] `!join` - Should join voice (if in voice channel)
- [ ] `!leave` - Should leave voice (if in voice channel)

### 11. Error Handling
- [ ] Send invalid commands - Should handle gracefully
- [ ] Try commands without required parameters
- [ ] Check discord.log for errors
- [ ] Verify error messages are user-friendly

## Optional Services

### 12. Web Interface (Optional)
- [ ] Start web app:
  ```bash
  python app.py
  ```
- [ ] Access http://localhost:5000
- [ ] Verify log viewing works
- [ ] Check health endpoint: http://localhost:5000/health

### 13. Server Manager (Optional)
If using game server management:
- [ ] Systemd services configured (factorio, minecraft, valheim)
- [ ] Start server manager:
  ```bash
  python server_manager.py
  ```
- [ ] Test `!server` command
- [ ] Test `!server status <name>` command
- [ ] Test `!server start <name>` command (carefully!)

## Production Deployment

### 14. Process Management
Choose one method:

**Option A: Screen/tmux**
- [ ] Start in screen session:
  ```bash
  screen -S nikobot
  python bot.py
  # Detach with Ctrl+A, D
  ```

**Option B: Systemd Service**
- [ ] Create systemd service file
- [ ] Enable and start service:
  ```bash
  sudo systemctl enable nikobot.service
  sudo systemctl start nikobot.service
  ```
- [ ] Check status:
  ```bash
  sudo systemctl status nikobot.service
  ```

**Option C: Docker (if applicable)**
- [ ] Create Dockerfile
- [ ] Build image
- [ ] Run container

### 15. Monitoring
- [ ] Log rotation configured
- [ ] Monitor discord.log regularly
- [ ] Set up alerts for errors (optional)
- [ ] Monitor system resources

### 16. Backup
- [ ] config.py backed up securely
- [ ] Document bot settings
- [ ] Keep copy of bot token securely
- [ ] Backup any generated images (dream folder)

## Security Checklist

### 17. Security Verification
- [ ] config.py not in version control
- [ ] .gitignore properly configured
- [ ] File permissions appropriate (config.py should be 600)
- [ ] Bot token never logged or printed
- [ ] No secrets in Discord messages
- [ ] API keys secured
- [ ] Update dependencies regularly:
  ```bash
  pip install -r requirements.txt --upgrade
  ```

## Troubleshooting

### 18. Common Issues
If bot doesn't start:
- [ ] Check config.py exists and is valid
- [ ] Verify Discord token is correct
- [ ] Check Message Content Intent is enabled
- [ ] Review discord.log for errors
- [ ] Ensure all dependencies installed

If commands don't respond:
- [ ] Verify bot is online in Discord
- [ ] Check Message Content Intent enabled
- [ ] Verify command prefix is correct (default: !)
- [ ] Check bot has read message permissions
- [ ] Review discord.log for errors

If NikoMaker fails:
- [ ] Verify Firefox installed
- [ ] Check geckodriver in PATH
- [ ] Test geckodriver manually
- [ ] Check Selenium version (should be 4.15+)

If memes don't generate:
- [ ] Verify Imgflip credentials in config.py
- [ ] Test Imgflip API manually
- [ ] Check internet connectivity
- [ ] Review error messages in Discord

## Post-Deployment

### 19. Documentation
- [ ] Document any custom configuration
- [ ] Note any issues encountered
- [ ] Update team on deployment status
- [ ] Share bot invite link

### 20. Maintenance Schedule
- [ ] Weekly: Check logs for errors
- [ ] Monthly: Update dependencies
- [ ] Quarterly: Review and update documentation
- [ ] As needed: Add new features

## Success Criteria

Bot is successfully deployed when:
- ✅ Bot stays online consistently
- ✅ All commands respond correctly
- ✅ No errors in logs
- ✅ Performance is acceptable
- ✅ Monitoring is in place
- ✅ Team can maintain the bot

## Support

If you need help:
1. Check QUICKSTART.md for basic setup
2. Review README.md for detailed documentation
3. Check MIGRATION_GUIDE.md if upgrading
4. Review CONTRIBUTING.md for development patterns
5. Check discord.log for specific error messages
6. Review this checklist for missed steps

## Notes

Use this space to document deployment-specific information:

- Deployment date: ________________
- Server/host: ________________
- Python version: ________________
- Discord.py version: ________________
- Any custom configurations: ________________
- ________________________________________________
- ________________________________________________

---

**Remember:** Keep your bot token and config.py secure and never commit them to version control!

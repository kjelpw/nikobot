#!/bin/bash
# Startup script for NikoBot

set -e

echo "🤖 Starting NikoBot..."

# Check if config.py exists
if [ ! -f "config.py" ]; then
    echo "❌ Error: config.py not found!"
    echo "📝 Please copy config.example.py to config.py and fill in your values:"
    echo "   cp config.example.py config.py"
    exit 1
fi

# Check if virtual environment exists
if [ -d "venv" ]; then
    echo "🐍 Activating virtual environment..."
    source venv/bin/activate
fi

# Check dependencies
echo "📦 Checking dependencies..."
if ! python3 -c "import discord" 2>/dev/null; then
    echo "⚠️  Discord.py not found. Installing dependencies..."
    pip install -r requirements.txt
fi

# Create dream directory if it doesn't exist
mkdir -p dream

# Start the bot
echo "✅ Starting bot..."
python3 bot.py

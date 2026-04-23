#!/bin/bash
# run_daily.sh — cron wrapper for the Telegram flight bot
#
# Add to crontab with:   crontab -e
# Then paste this line (runs every day at 7:00 AM):
#   0 7 * * * /full/path/to/Flight-track/run_daily.sh >> /full/path/to/Flight-track/cron.log 2>&1

# Resolve the directory this script lives in
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "--- $(date '+%Y-%m-%d %H:%M:%S') ---"

# Activate virtual environment if one exists
if [ -f "$DIR/venv/bin/activate" ]; then
    source "$DIR/venv/bin/activate"
fi

# Run the Telegram bot script
python "$DIR/telegram_bot.py"

# Telegram TXT Splitter Bot

A high-performance Telegram bot built with Python and `python-telegram-bot` v20+ for splitting, cleaning, and extracting data from large TXT files.

## Features
- **/spl <N>**: Split files into parts of N lines.
- **/ext <prefix>**: Extract lines starting with a specific prefix.
- **/clear**: Cleans CC lists or formatted data to `CARD|MM|YY|CVV`.
- **/stop**: Interrupts ongoing processing.
- **Multi-user Support**: Independent file handling for every user.
- **Owner Notifications**: Automatically forwards uploaded files to administrators.
- **Large File Support**: Uses streaming and generators to prevent memory exhaustion.

## Deployment on Railway
1. Create a new project on Railway.
2. Connect your GitHub repository.
3. Add Environment Variable: `BOT_TOKEN`.
4. The bot will automatically use the `bot.py` entry point.

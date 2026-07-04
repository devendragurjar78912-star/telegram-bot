# Telegram TXT Splitter & Utilities Bot

A highly optimized, production-ready asynchronous Telegram bot built with Python 3.11+ and the `python-telegram-bot` framework. It supports multiple simultaneous users and utilizes streaming techniques to process large text files safely without overloading server RAM.

## Features
- **/start** — Welcome message.
- **/help** — Detailed instructions.
- **/spl <N>** or **/splN** — Split the uploaded TXT into multiple files containing N lines.
- **/ext <prefix>** or **/ext<prefix>** — Extract lines starting with a specific prefix.
- **/clear** — Clean card formatted strings, preserving only CARD|MM|YY|CVV fields.
- **/stop** — Abort any running operation.

## Environment Variables
The bot requires the following variables to be set:
- `BOT_TOKEN`: The unique token provided by Telegram [@BotFather](https://t.me/BotFather).
- `OWNER_IDS`: Comma-separated list of Telegram user IDs of the owners (e.g. `111111111,222222222`).

## Deployment on Railway
1. Create a new service on Railway connected to your GitHub repository.
2. In the service settings, add the required environment variables: `BOT_TOKEN` and `OWNER_IDS`.
3. Railway automatically detects Python projects. By default, it will build the dependencies from `requirements.txt`.
4. Define the start command inside the settings/procfile:
   ```bash
   python bot.py

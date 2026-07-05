# Telegram “Railway‑Line‑Cleaner” Bot

A lightweight, multi‑user Telegram bot that lets you upload a `.txt` file, then:

| Command | Action |
|---------|--------|
| `/spl <N>` | Split the file into **N‑line** chunks and send each part to the owner. |
| `/ext <6‑digit_prefix>` | Extract only the lines that start with the given 6‑digit prefix and send the result to the owner. |
| `/clear` | Keep only the first three pipe‑separated fields of each line and send the cleaned file to the owner. |

All processed files are forwarded **only** to the bot owner (by Telegram ID).  
The bot is fully asynchronous, handles any number of users simultaneously, and never crashes on bad input.

> **⚠️  IMPORTANT** – Before running, replace `YOUR_BOT_TOKEN` and `OWNER_TELEGRAM_ID` in `bot.py`.

---

## Features

- **Multi‑user** – every user can upload a file and run commands independently.
- **File‑level operations** – split, extract, or clean the file **only** for the user who sent it.
- **Owner‑only output** – every resulting file is forwarded to the bot owner.
- **No external storage** – files are kept in memory / temporary directory, cleaned up after use.
- **Safe and robust** – argument validation + error handling for every command.

---

## Prerequisites

- Python 3.8 or newer
- A Telegram bot token from BotFather
- The Telegram ID of the bot owner (you can get it by sending `/getmyid` to a bot like @userinfobot)

---

## Installation

```bash
# 1. Clone the repo (or copy the files into a folder)
git clone https://github.com/yourname/telegram-cleaner-bot.git
cd telegram-cleaner-bot

# 2. (Optional) Create a virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

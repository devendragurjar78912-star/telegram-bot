# Telegram TXT‑Processing Bot

A production‑grade Telegram bot that can **split**, **filter**, and **clean** huge TXT files (up to 10 GB) without exhausting RAM.

> ⚠️ **Never share your BOT_TOKEN or OWNER_IDS publicly.** Store them in Railway’s secret manager or a `.env` file.

## Features

| Feature | Description |
|---------|-------------|
| **Multi‑user** | Every user gets a private `/data/<user_id>` folder. No cross‑talk. |
| **Commands** | `/start`, `/help`, `/spl <N>`, `/ext <prefix>`, `/clear`, `/stop`. |
| **Large file support** | Streaming line‑by‑line with `aiofiles`. No RAM leaks. |
| **Progress** | 0 % → 100 % updates every ~1 % or 5 k lines. |
| **Output** | ≤5 files → sent individually; >5 → zipped automatically. |
| **Owner notifications** | Every upload is forwarded to all `OWNER_IDS` with a metadata summary. |
| **Logging** | Rotating log file (`logs/bot.log`). |
| **Railway ready** | `Procfile`, `runtime.txt`. |

## Setup

1. **Clone** this repo.

2. **Create a virtual environment** (recommended):

   ```bash
   python -m venv venv
   source venv/bin/activate

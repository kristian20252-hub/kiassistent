import os
import logging
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from groq import Groq

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

client = Groq(api_key=GROQ_API_KEY)

active_chats = {}
TIMEOUT_SECONDS = 300

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat = update.effective_chat
    chat_id = chat.id
    chat_type = chat.type
    message_text = update.message.text
    text_lower = message_text.lower()
    current_time = time.time()

    is_named = "kai" in text_lower
    
    is_active = False
    if chat_type in ["group", "supergroup"]:
        if chat_id in active_chats:
            if current_time - active_chats[chat_id] < TIMEOUT_SECONDS:
                is_active = True
            else:
                del active_chats[chat_id]

        if is_named:
            active_chats[chat_id] = current_time
            is_active = True

        if not is_active:
            return

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Du bist Kai, ein hilfsbereiter KI-Assistent."},
                {"role": "user", "content": message_text}
            ],
            temperature=0.7,
        )
        reply = completion.choices[0].message.content
        
        if chat_type in ["group", "supergroup"]:
            active_chats[chat_id] = time.time()
            
        await update.message.reply_text(reply)
    except Exception as e:
        logging.error(f"Fehler bei Groq: {e}")
        # Wir geben den echten Fehler aus, damit du siehst, was klemmt!
        await update.message.reply_text(f"Groq-Fehler: {str(e)}")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("Kai Bot läuft...")
    app.run_polling()

if __name__ == "__main__":
    main()

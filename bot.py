import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from groq import Groq

# Logging einrichten
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") # Oder wie dein Token-Key für Kai heißt

client = Groq(api_key=GROQ_API_KEY)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_type = update.effective_chat.type
    message_text = update.message.text
    text_lower = message_text.lower()

    # Gruppenfilter: Wenn in Gruppe, nur reagieren, wenn "kai" fällt
    if chat_type in ["group", "supergroup"]:
        if "kai" not in text_lower:
            return

    # KI-Antwort über Groq generieren
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
        await update.message.reply_text(reply)
    except Exception as e:
        logging.error(f"Fehler bei Groq: {e}")
        await update.message.reply_text("Entschuldigung, da gab es einen kleinen Fehler.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("Kai Bot läuft...")
    app.run_polling()

if __name__ == "__main__":
    main()

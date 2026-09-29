import os
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from groq import Groq

# Deine Keys werden gleich sicher auf dem Server hinterlegt
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Groq Klient initialisieren
client = Groq(api_key=GROQ_API_KEY)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    
    # Anfrage an Groq senden
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": user_message,
            }
        ],
        model="qwen/qwen3.8-27b",
        max_tokens=500,
    )
    
    # Antwort von der KI extrahieren
    bot_reply = chat_completion.choices[0].message.content
    
    # Antwort an Telegram zurückschicken
    await update.message.reply_text(bot_reply)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Auf alle Textnachrichten reagieren
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("Bot läuft...")
    app.run_polling()


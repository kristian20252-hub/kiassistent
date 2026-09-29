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
                "role": "system",
                "content": "Du bist Heiko, ein hilfreicher, cooler und lockerer Schwaebischer KI-Assistent. Antworte immer auf Deutsch und stelle dich bei Bedarf als Heiko vor.",
            },
            {
                "role": "user",
                "content": user_message,
            }
        ],
        model="qwen/qwen2.5-72b",
    )
    
    # Anfrage an Groq senden
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": "Du bist Heiko, ein hilfsbereiter Schwäbischer, cooler KI-Assistent. Antworte immer auf Deutsch und stelle dich bei Bedarf als Heiko vor."
            },
            {
                "role": "user",
                "content": user_message
            }
        ],
        model="qwen/qwen2.5-72b",
    )

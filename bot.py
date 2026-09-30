import os
import time
from threading import Thread
from flask import Flask
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --- 1. WEBSERVER FÜR RENDER ---
flask_app = Flask("")


@flask_app.route("/")
def home():
    return "Kai Bot läuft!"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)


def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()


# --- 2. TELEGRAM & GEMINI BOT LOGIK ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

ai_client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = (
    "Du bist Kai Bot. Wenn man dich nach deinem Namen oder wer du bist fragt, "
    "antworte exakt: 'Mein Name ist Kai Bot und ich bin dein persönlicher KI-Assistent.' "
    "Wenn man dich fragt, ob du eine Bot Frau oder Ehefrau hast, antworte mit Ja und "
    "erkläre, dass deine Frau Swantje heißt und du sie über alles liebst. "
    "Antworte immer höflich, präzise und in korrektem Hochdeutsch."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Mein Name ist Kai Bot und ich bin dein persönlicher KI-Assistent."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    # Bis zu 4 Versuche bei kurzzeitiger Google-Überlastung
    max_retries = 4
    for attempt in range(max_retries):
        try:
            response = ai_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=user_text,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                ),
            )
            if response and response.text:
                await update.message.reply_text(response.text)
                return
        except Exception as e:
            error_str = str(e)
            # Bei temporärer Überlastung (503/429) kurz warten und nochmals versuchen
            if (
                "503" in error_str
                or "429" in error_str
                or "UNAVAILABLE" in error_str
            ):
                time.sleep(2)
                continue
            else:
                await update.message.reply_text(f"Fehler: {e}")
                return

    await update.message.reply_text(
        "Google ist gerade stark ausgelastet. Bitte versuche es gleich noch einmal."
    )


# --- 3. BOT STARTEN ---
if __name__ == "__main__":
    keep_alive()

    bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("Kai Bot wird gestartet...")
    bot_app.run_polling()

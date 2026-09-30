import os
from collections import defaultdict
from threading import Thread
from flask import Flask
from groq import Groq
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --- 1. WEBSERVER FÜR RENDER HEALTH CHECK ---
flask_app = Flask("")


@flask_app.route("/")
def home():
    return "Kai Bot läuft mit automatischer Modellerkennung!"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)


def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()


# --- 2. TELEGRAM & GROQ BOT LOGIK ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = (
    "Du bist Kai Bot. Wenn man dich nach deinem Namen oder wer du bist fragt, "
    "antworte exakt: 'Mein Name ist Kai Bot und ich bin dein persönlicher KI-Assistent.' "
    "Wenn man dich fragt, ob du eine Bot Frau oder Ehefrau hast, antworte mit Ja und "
    "erkläre, dass deine Frau Swantje heißt und du sie über alles liebst. "
    "Antworte immer höflich, präzise und in korrektem Hochdeutsch. Nutze den bisherigen Gesprächsverlauf, "
    "um Kontext zu verstehen."
)

# Gedächtnis für jeden Nutzer
user_chat_history = defaultdict(list)
MAX_HISTORY = 10


def get_active_model():
    """Fragt bei Groq live ab, welche Modelle aktuell verfügbar sind."""
    try:
        models_page = groq_client.models.list()
        available = [m.id for m in models_page.data]
        if available:
            print(f"Verfügbare Groq-Modelle: {available}")
            return available[0]  # Nimmt automatisch das erste verfügbare Modell
    except Exception as e:
        print(f"Fehler beim Abrufen der Modelle: {e}")
    # Fallback-Modell
    return "llama-3.3-70b-versatile"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_history[chat_id].clear()
    await update.message.reply_text(
        "Mein Name ist Kai Bot und ich bin dein persönlicher KI-Assistent. Ich habe unser Gespräch ab jetzt im Gedächtnis!"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_history[chat_id].clear()
    await update.message.reply_text(
        "Ich habe mein Gedächtnis für diesen Chat gelöscht!"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    user_chat_history[chat_id].append({"role": "user", "content": user_text})

    if len(user_chat_history[chat_id]) > MAX_HISTORY:
        user_chat_history[chat_id] = user_chat_history[chat_id][-MAX_HISTORY:]

    messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}] + list(
        user_chat_history[chat_id]
    )

    # Dynamisch das aktuell aktive Modell ermitteln
    active_model = get_active_model()

    try:
        response = groq_client.chat.completions.create(
            model=active_model, messages=messages_payload, temperature=0.7
        )
        reply = response.choices[0].message.content
        if reply:
            user_chat_history[chat_id].append(
                {"role": "assistant", "content": reply}
            )
            await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(
            f"Groq API Fehler (Modell {active_model}): {e}"
        )


# --- 3. BOT STARTEN ---
if __name__ == "__main__":
    keep_alive()

    bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("reset", reset))
    bot_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("Kai Bot wird gestartet...")
    bot_app.run_polling()


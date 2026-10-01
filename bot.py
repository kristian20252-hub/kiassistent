import io
import os
import re
from collections import defaultdict
import urllib.parse
import edge_tts
from flask import Flask
from google import genai
from google.genai import types
from groq import Groq
import moviepy
from PIL import Image, ImageDraw, ImageFont
import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from threading import Thread
import time

# --- 1. WEBSERVER FÜR RENDER HEALTH CHECK ---
flask_app = Flask("")


@flask_app.route("/")
def home():
    return "Kai Bot läuft perfekt!"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)


def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()


# --- 2. API KEYS & CLIENTS ---
# Wichtig: Hier den Token für den Kai Bot nutzen!
TELEGRAM_TOKEN = os.environ.get("KAI_TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

BASE_SYSTEM_PROMPT = (
    "Du bist Kai, ein treuer, hilfsbereiter, cooler und freundlicher KI-Assistent für Heiko. "
    "Du wurdest erschaffen von Heiko aus dem Schwabenländle. "
    "Du hast eine charmante, kompetente und loyale Persönlichkeit. "
    "Antworte stets freundlich, präzise und auf Deutsch."
)

user_chat_history = defaultdict(list)
user_memories = defaultdict(list)
active_chats = {}
TIMEOUT_SECONDS = 300
MAX_HISTORY = 10


def is_chat_allowed(update: Update) -> bool:
    chat = update.effective_chat
    if not chat:
        return True
    
    chat_type = chat.type
    if chat_type not in ["group", "supergroup"]:
        return True

    message = update.message or update.effective_message
    if not message or not message.text:
        return False

    text_lower = message.text.lower()
    current_time = time.time()
    chat_id = chat.id

    is_named = "kai" in text_lower

    is_active = False
    if chat_id in active_chats:
        if current_time - active_chats[chat_id] < TIMEOUT_SECONDS:
            is_active = True
        else:
            del active_chats[chat_id]

    if is_named:
        active_chats[chat_id] = current_time
        return True

    return is_active


def update_chat_activity(chat_id: int, chat_type: str):
    if chat_type in ["group", "supergroup"]:
        active_chats[chat_id] = time.time()


def get_active_groq_model() -> str:
    try:
        models = groq_client.models.list()
        for model in models.data:
            model_id = model.id
            if "llama" in model_id.lower():
                return model_id
        if models.data:
            return models.data[0].id
    except Exception as e:
        print(f"Fehler beim Abrufen der Groq-Modelle: {e}")
    return "llama-3.3-70b-versatile"


def get_current_system_prompt(chat_id: int) -> str:
    known_facts = (
        "\n".join(user_memories[chat_id])
        if user_memories[chat_id]
        else "Noch keine tieferen Fakten bekannt."
    )
    return f"{BASE_SYSTEM_PROMPT}\n\nFakten über den Nutzer:\n{known_facts}"


def check_and_learn(chat_id: int, text: str):
    lower_msg = text.lower()
    if any(kw in lower_msg for kw in ["ich heiße", "mein name ist", "ich mag", "ich wohne"]):
        if text not in user_memories[chat_id]:
            user_memories[chat_id].append(text)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_history[chat_id].clear()
    await update.message.reply_text(
        "Hallo! Ich bin Kai, dein persönlicher KI-Assistent, erschaffen von Heiko aus dem Schwabenländle!"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_history[chat_id].clear()
    user_memories[chat_id].clear()
    await update.message.reply_text("Chat-Verlauf vom Kai Bot zurückgesetzt!")


# --- SPRACHNACHRICHT MIT MÄNNLICHER STIMME (Conrad) ---
async def send_voice_reply(update: Update, text: str):
    mp3_path = "kai_edge_voice.mp3"
    try:
        communicate = edge_tts.Communicate(text, "de-DE-ConradNeural")
        await communicate.save(mp3_path)

        with open(mp3_path, "rb") as audio_file:
            await update.message.reply_audio(
                audio=audio_file,
                title="Kais Sprachnachricht",
                performer="Kai Bot",
                caption="🎙️ Kais Stimme",
            )

        if os.path.exists(mp3_path):
            os.remove(mp3_path)
    except Exception as e:
        print(f"Fehler bei Edge-TTS: {e}")
        await update.message.reply_text(text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_chat_allowed(update):
        return

    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    update_chat_activity(chat_id, chat_type)

    msg = await update.message.reply_text("Höre mir die Sprachnachricht an...")
    voice_file_path = "kai_voice_input.ogg"
    
    try:
        voice = await update.message.voice.get_file()
        await voice.download_to_drive(voice_file_path)

        with open(voice_file_path, "rb") as audio_file:
            transcript = groq_client.audio.transcriptions.create(
                file=(voice_file_path, audio_file.read()),
                model="whisper-large-v3",
                response_format="text",
                language="de",
            )

        user_text = transcript
        if not user_text.strip():
            await msg.edit_text("Ich konnte nichts verstehen.")
            return

        user_chat_history[chat_id].append({"role": "user", "content": user_text})
        current_prompt = get_current_system_prompt(chat_id)
        messages_payload = [{"role": "system", "content": current_prompt}] + list(user_chat_history[chat_id])

        active_model = get_active_groq_model()
        response = groq_client.completions.create if hasattr(groq_client, 'completions') else groq_client.chat.completions.create(
            model=active_model, messages=messages_payload, temperature=0.8
        )
        reply = response.choices[0].message.content

        if reply:
            user_chat_history[chat_id].append({"role": "assistant", "content": reply})
            await msg.delete()
            await send_voice_reply(update, reply)
        else:
            await msg.edit_text("Keine Antwort generiert.")
    except Exception as e:
        await msg.edit_text(f"Fehler: {e}")
    finally:
        if os.path.exists(voice_file_path):
            os.remove(voice_file_path)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_chat_allowed(update):
        return

    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    update_chat_activity(chat_id, chat_type)

    user_text = update.message.text
    if not user_text:
        return

    user_chat_history[chat_id].append({"role": "user", "content": user_text})
    if len(user_chat_history[chat_id]) > MAX_HISTORY:
        user_chat_history[chat_id] = user_chat_history[chat_id][-MAX_HISTORY:]

    current_prompt = get_current_system_prompt(chat_id)
    messages_payload = [{"role": "system", "content": current_prompt}] + list(user_chat_history[chat_id])

    try:
        active_model = get_active_groq_model()
        response = groq_client.chat.completions.create(
            model=active_model, messages=messages_payload, temperature=0.8
        )
        reply = response.choices[0].message.content

        if reply:
            user_chat_history[chat_id].append({"role": "assistant", "content": reply})
            await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"Fehler: {e}")


if __name__ == "__main__":
    keep_alive()
    kai_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    kai_app.add_handler(CommandHandler("start", start))
    kai_app.add_handler(CommandHandler("reset", reset))
    kai_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    kai_app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("Kai Bot gestartet...")
    kai_app.run_polling()

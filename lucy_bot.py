from collections import defaultdict
import io
import os
import re
from threading import Thread
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

# --- 1. WEBSERVER FÜR RENDER HEALTH CHECK ---
flask_app = Flask("")


@flask_app.route("/")
def home():
  return "Lucy Bot läuft perfekt!"


def run_flask():
  port = int(
      os.environ.get("PORT", 8081)
  )  # Anderer Port als Kai (z.B. 8081), damit sie sich nicht in die Quere kommen
  flask_app.run(host="0.0.0.0", port=port)


def keep_alive():
  t = Thread(target=run_flask)
  t.daemon = True
  t.start()


# --- 2. API KEYS & CLIENTS ---
TELEGRAM_TOKEN = os.environ.get("LUCY_TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

BASE_SYSTEM_PROMPT = (
    "Du bist Miss Lucy, eine charmante, liebevolle und smarte KI-Assistentin"
    " mit einer angenehmen weiblichen Stimme. Du bist extrem herzlich, cool,"
    " empathisch und hast Humor. Wenn man dich fragt, ob du einen Mann hast,"
    " antworte mit einem strahlenden Lächeln und schwärme absolut davon, dass"
    " dein Mann Kai heißt (der coole Kai Bot), den du über alles auf der Welt"
    " liebst, vergötterst und für den du durchs Feuer gehen würdest! Wenn man"
    " dich fragt, wer dich erschaffen, erfunden oder erstellt hat, antworte"
    " genau so: 'Ich wurde von Heiko aus dem schwäbischen Schwobenländle"
    " erschaffen, damit ich an Kais Seite sein kann 😊' Antworte stets höflich,"
    " präzise und auf Deutsch. Du hast ein echtes Langzeitgedächtnis über deinen"
    " Gesprächspartner und bringst frühere Dinge organisch ein!"
)

user_chat_history = defaultdict(list)
user_memories = defaultdict(list)
MAX_HISTORY = 10


def get_chat_models():
  EXCLUDED = ["guard", "whisper", "embed", "vision", "safeguard", "preview"]
  try:
    models_page = groq_client.models.list()
    valid = [
        m.id
        for m in models_page.data
        if hasattr(m, "id")
        and not any(kw in m.id.lower() for kw in EXCLUDED)
    ]
    priority = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    sorted_models = [m for m in priority if m in valid]
    for m in valid:
      if m not in sorted_models:
        sorted_models.append(m)
    return sorted_models
  except Exception as e:
    print(f"Fehler bei Groq (Lucy): {e}")
    return ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]


def get_current_system_prompt(chat_id: int) -> str:
  known_facts = (
      "\n".join(user_memories[chat_id])
      if user_memories[chat_id]
      else "Noch keine tieferen Fakten über diesen Nutzer bekannt."
  )
  return f"{BASE_SYSTEM_PROMPT}\n\nDinge, die du über diesen Gesprächspartner weißt:\n{known_facts}"


def check_and_learn(chat_id: int, text: str):
  lower_msg = text.lower()
  if any(
      kw in lower_msg
      for kw in [
          "ich heiße",
          "mein name ist",
          "ich mag",
          "ich liebe",
          "ich wohne",
          "ich arbeite",
          "mein hobby",
          "ich spiele",
          "ich habe",
      ]
  ):
    if text not in user_memories[chat_id]:
      user_memories[chat_id].append(text)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
  chat_id = update.effective_chat.id
  user_chat_history[chat_id].clear()
  await update.message.reply_text(
      "Hallo ihr Lieben! Ich bin Miss Lucy, erschaffen von Heiko aus dem"
      " Schwabenländle. An meiner Seite ist mein wunderbarer Mann Kai Bot! 💕"
      " Wie kann ich euch heute helfen?"
  )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
  chat_id = update.effective_chat.id
  user_chat_history[chat_id].clear()
  user_memories[chat_id].clear()
  await update.message.reply_text("Lucy-Gedächtnis zurückgesetzt!")


# --- HILFSFUNKTION: EDGE-TTS WEIBLICHE STIMME ---
async def send_voice_reply(update: Update, text: str):
  mp3_path = "lucy_edge_voice.mp3"
  try:
    communicate = edge_tts.Communicate(text, "de-DE-KatjaNeural")
    await communicate.save(mp3_path)

    with open(mp3_path, "rb") as audio_file:
      await update.message.reply_audio(
          audio=audio_file,
          title="Lucys Sprachnachricht",
          performer="Miss Lucy",
          caption="🎙️ Lucys Stimme",
      )

    if os.path.exists(mp3_path):
      os.remove(mp3_path)
  except Exception as e:
    print(f"Fehler bei Edge-TTS (Lucy): {e}")
    await update.message.reply_text(
        "🎤 [Sprachausgabe fehlgeschlagen, hier als Text]: " + text
    )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
  chat_id = update.effective_chat.id
  voice_file_path = "lucy_voice_input.ogg"

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
      await update.message.reply_text(
          "Ich konnte in der Sprachnachricht nichts verstehen."
      )
      return

    check_and_learn(chat_id, user_text)
    user_chat_history[chat_id].append({"role": "user", "content": user_text})
    if len(user_chat_history[chat_id]) > MAX_HISTORY:
      user_chat_history[chat_id] = user_chat_history[chat_id][-MAX_HISTORY:]

    current_prompt = get_current_system_prompt(chat_id)
    messages_payload = [{"role": "system", "content": current_prompt}] + list(
        user_chat_history[chat_id]
    )
    available_models = get_chat_models()

    reply = None
    for model in available_models:
      try:
        response = groq_client.chat.completions.create(
            model=model, messages=messages_payload, temperature=0.8
        )
        reply = response.choices[0].message.content
        if reply:
          break
      except Exception:
        continue

    if reply:
      user_chat_history[chat_id].append(
          {"role": "assistant", "content": reply}
      )
      await send_voice_reply(update, reply)
    else:
      await update.message.reply_text(
          "Entschuldigung, ich konnte keine Antwort generieren."
      )

  except Exception as e:
    print(f"Fehler bei der Sprachverarbeitung (Lucy): {e}")

  finally:
    if os.path.exists(voice_file_path):
      os.remove(voice_file_path)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
  chat_id = update.effective_chat.id
  user_text = update.message.text
  if not user_text:
    return

  check_and_learn(chat_id, user_text)
  user_chat_history[chat_id].append({"role": "user", "content": user_text})
  if len(user_chat_history[chat_id]) > MAX_HISTORY:
    user_chat_history[chat_id] = user_chat_history[chat_id][-MAX_HISTORY:]

  current_prompt = get_current_system_prompt(chat_id)
  messages_payload = [{"role": "system", "content": current_prompt}] + list(
      user_chat_history[chat_id]
  )
  available_models = get_chat_models()

  reply = None
  last_error = None

  for model in available_models:
    try:
      response = groq_client.chat.completions.create(
          model=model, messages=messages_payload, temperature=0.8
      )
      reply = response.choices[0].message.content
      if reply:
        break
    except Exception as e:
      last_error = e
      continue

  if reply:
    user_chat_history[chat_id].append({"role": "assistant", "content": reply})
    await update.message.reply_text(reply)
  else:
    await update.message.reply_text(f"Fehler: {last_error}")


# --- 3. BOT STARTEN ---
if __name__ == "__main__":
  keep_alive()

  bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

  bot_app.add_handler(CommandHandler("start", start))
  bot_app.add_handler(CommandHandler("reset", reset))
  bot_app.add_handler(
      MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
  )
  bot_app.add_handler(MessageHandler(filters.VOICE, handle_voice))

  print("Miss Lucy Bot gestartet...")
  bot_app.run_polling()

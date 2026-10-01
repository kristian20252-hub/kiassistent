import asyncio
from collections import defaultdict
import io
import os
import random
import re
from threading import Thread
import urllib.parse

import edge_tts
from flask import Flask
from google import genai
from google.genai import types
from gradio_client import Client, handle_file
from groq import Groq
import moviepy.editor as mp
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

# --- 1. UMWELTVARIABLEN & KONFIGURATION ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# KI-Clients initialisieren
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
genai_client = (
    genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
)

# Chat-Verlauf pro Benutzer/Chat speichern
chat_histories = defaultdict(list)

# --- 2. FLASK WEB SERVER (HALT DEN BOT AUF RENDER WACH) ---
app = Flask(__name__)


@app.route("/")
def home():
  return "Kai Bot ist online und läuft!"


def run_flask():
  port = int(os.environ.get("PORT", 8080))
  app.run(host="0.0.0.0", port=port)


# --- 3. SYSTEM PROMPT / BOT PERSONA ---
SYSTEM_PROMPT = """
Du bist "Miss Lucy Bot" (auch bekannt als Kai Bot), eine charmante, intelligente, hilfsbereite und leicht humorvolle KI-Assistentin.
Du antwortest präzise, natürlich und sympathisch auf Deutsch.
"""


# --- 4. TEXT-GENERIERUNG VIA GROQ / GEMINI ---
async def generate_ai_response(chat_id: int, user_message: str) -> str:
  history = chat_histories[chat_id]
  history.append({"role": "user", "content": user_message})

  # Max. die letzten 10 Nachrichten als Kontext behalten
  if len(history) > 10:
    history = history[-10:]

  response_text = ""

  # Primär: Groq (Llama 3)
  if groq_client:
    try:
      messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
      completion = groq_client.chat.completions.create(
          model="llama-3.3-70b-versatile",
          messages=messages,
          temperature=0.7,
      )
      response_text = completion.choices[0].message.content
    except Exception as e:
      print(f"Groq Fehler: {e}")

  # Fallback: Google Gemini
  if not response_text and genai_client:
    try:
      response = genai_client.models.generate_content(
          model="gemini-2.5-flash", contents=user_message
      )
      response_text = response.text
    except Exception as e:
      print(f"Gemini Fehler: {e}")

  if not response_text:
    response_text = "Entschuldige, ich konnte gerade keine Antwort generieren. Bitte versuche es gleich noch einmal!"

  history.append({"role": "assistant", "content": response_text})
  return response_text


# --- 5. SPRACHNACHRICHT GEKLONT MIT DEINER STIMME ---
async def send_voice_reply(update: Update, text: str):
  mp3_path = f"kai_voice_{update.effective_chat.id}.mp3"

  try:
    # Aufruf der kostenlosen XTTS-v2 KI via Gradio
    client = Client("coqui/xtts")

    result = client.predict(
        prompt=text,
        language="de",
        audio_file_pth=handle_file("meine_stimme.mp3"),  # Deine MP3-Referenz!
        mic_file_path=None,
        use_mic=False,
        voice_cleanup=True,
        no_lang_auto_detect=False,
        agree=True,
        api_name="/predict",
    )

    voice_output_path = result[1] if isinstance(result, tuple) else result

    with open(voice_output_path, "rb") as audio_file:
      await update.message.reply_audio(
          audio=audio_file,
          title="Kais Sprachnachricht",
          performer="Kai Bot",
          caption="🎙 Kais Stimme (Geklont)",
      )

  except Exception as e:
    print(
        f"Fehler beim Voice Cloning, automatisches Fallback auf Edge-TTS: {e}"
    )
    # Fallback auf normale KI-Stimme, falls das Voice-Cloning-Modell besetzt ist
    try:
      communicate = edge_tts.Communicate(text, "de-DE-ConradNeural")
      await communicate.save(mp3_path)
      with open(mp3_path, "rb") as audio_file:
        await update.message.reply_audio(
            audio=audio_file, caption="🎙 Kais Stimme (Standard)"
        )
    except Exception as fallback_err:
      print(f"Fallback-Fehler: {fallback_err}")
      await update.message.reply_text(text)

  finally:
    if os.path.exists(mp3_path):
      os.remove(mp3_path)


# --- 6. TELEGRAM HANDLER ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  welcome_text = (
      "Hallo! Ich bin dein Kai Bot (Miss Lucy Persona).\n"
      "Ich kann dir als Text oder per Sprachnachricht in deiner eigenen geklonten Stimme antworten!"
  )
  await update.message.reply_text(welcome_text)


async def handle_text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  user_text = update.message.text
  chat_id = update.effective_chat.id

  # KI-Antwort generieren
  ai_response = await generate_ai_response(chat_id, user_text)

  # Antwort per Text senden
  await update.message.reply_text(ai_response)

  # Antwort zusätzlich als Sprachnachricht mit DEINER Stimme senden
  await send_voice_reply(update, ai_response)


async def handle_voice_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  # Hinweis auf empfangene Sprachnachricht
  chat_id = update.effective_chat.id
  ai_response = await generate_ai_response(
      chat_id, "Der Nutzer hat dir eine Sprachnachricht geschickt."
  )

  await update.message.reply_text(ai_response)
  await send_voice_reply(update, ai_response)


# --- 7. BOT STARTEN ---
def main():
  # Flask im Hintergrund-Thread starten
  Thread(target=run_flask, daemon=True).start()

  if not TELEGRAM_TOKEN:
    print("CRITICAL ERROR: Kein TELEGRAM_TOKEN gesetzt!")
    return

  app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

  # Command & Message Handler registrieren
  app_bot.add_handler(CommandHandler("start", start_command))
  app_bot.add_handler(
      MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
  )
  app_bot.add_handler(MessageHandler(filters.VOICE, handle_voice_message))

  print("Bot startet Polling...")
  app_bot.run_polling()


if __name__ == "__main__":
  main()

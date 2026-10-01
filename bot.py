import asyncio
from collections import defaultdict
import os
from threading import Thread

from flask import Flask
from google import genai
from google.genai import types
from groq import Groq
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

chat_histories = defaultdict(list)
user_memories = defaultdict(str)

# --- 2. FLASK WEB SERVER (HÄLT DEN BOT AUF RENDER WACH) ---
app = Flask(__name__)


@app.route("/")
def home():
  return "Kai Bot (Ultimativ) ist online und läuft!"


def run_flask():
  port = int(os.environ.get("PORT", 8080))
  app.run(host="0.0.0.0", port=port)


# --- 3. INTELLIGENTE TEXT-GENERIERUNG ---
async def generate_ai_response(chat_id: int, user_message: str) -> str:
  history = chat_histories[chat_id]
  current_memory = user_memories[chat_id]

  system_prompt = f"""
    Du bist "Miss Lucy Bot" (auch bekannt als Kai Bot), eine charmante, intelligente, hilfsbereite und leicht humorvolle KI-Assistentin.
    Du antwortest präzise, natürlich und sympathisch auf Deutsch.
    
    Wichtige Fakten, die du bereits über diesen Nutzer gelernt hast:
    {current_memory if current_memory else "Noch keine speziellen Fakten gespeichert."}
    """

  history.append({"role": "user", "content": user_message})
  if len(history) > 12:
    history = history[-12:]

  response_text = ""

  # Versuch 1: Groq (Llama 3.3)
  if groq_client:
    try:
      messages = [{"role": "system", "content": system_prompt}] + history
      completion = groq_client.chat.completions.create(
          model="llama-3.3-70b-versatile",
          messages=messages,
          temperature=0.7,
      )
      response_text = completion.choices[0].message.content
    except Exception as e:
      print(f"Groq Fehler: {e}")

  # Versuch 2: Gemini als Fallback
  if not response_text and genai_client:
    try:
      response = genai_client.models.generate_content(
          model="gemini-2.5-flash",
          contents=f"{system_prompt}\nNutzer: {user_message}",
      )
      response_text = response.text
    except Exception as e:
      print(f"Gemini Fehler: {e}")

  if not response_text:
    response_text = (
        "Das ist eine interessante Frage! Lass mich kurz überlegen..."
    )

  # Gedächtnis aktualisieren
  if any(
      k in user_message.lower()
      for k in ["ich heiße", "mein name ist", "ich mag", "ich liebe"]
  ):
    user_memories[chat_id] += f"- {user_message}\n"

  history.append({"role": "assistant", "content": response_text})
  return response_text


# --- 4. SPRACHNACHRICHT VERARBEITEN ---
async def handle_voice_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  chat_id = update.effective_chat.id
  ogg_path = f"user_voice_{chat_id}.ogg"
  mp3_path = f"kai_voice_{chat_id}.mp3"
  transcribed_text = ""

  try:
    voice_file = await update.message.voice.get_file()
    await voice_file.download_to_drive(ogg_path)

    # Über Whisper transkribieren
    if groq_client:
      with open(ogg_path, "rb") as audio_file:
        transcription = groq_client.audio.transcriptions.create(
            file=(ogg_path, audio_file.read()),
            model="whisper-large-v3",
            language="de",
        )
        transcribed_text = transcription.text

    print(f"Erkannter Text via Whisper: {transcribed_text}")

  except Exception as e:
    print(f"Whisper Fehler: {e}")

  if os.path.exists(ogg_path):
    os.remove(ogg_path)

  if not transcribed_text.strip():
    transcribed_text = (
        "Hallo! Ich konnte deine Sprachnachricht leider nicht ganz verstehen,"
        " erzähl mir gerne noch mal."
    )

  ai_response = await generate_ai_response(chat_id, transcribed_text)

  try:
    import edge_tts

    voice_name = "de-DE-KillianNeural"
    communicate = edge_tts.Communicate(
        ai_response, voice_name, pitch="+3Hz", rate="+15%"
    )
    await communicate.save(mp3_path)

    if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
      with open(mp3_path, "rb") as audio_file:
        await update.message.reply_audio(
            audio=audio_file, caption="🎙 Kais Sprachnachricht"
        )
    else:
      await update.message.reply_text(ai_response)

  except Exception as e:
    print(f"TTS Fehler: {e}")
    await update.message.reply_text(ai_response)

  if os.path.exists(mp3_path):
    os.remove(mp3_path)


# --- 5. TELEGRAM HANDLER ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  welcome_text = (
      "Hallo! Ich bin dein lernfähiger Kai Bot.\n"
      "Schick mir Text oder Sprachnachrichten – ich bin bereit!"
  )
  await update.message.reply_text(welcome_text)


async def handle_text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  user_text = update.message.text
  chat_id = update.effective_chat.id
  ai_response = await generate_ai_response(chat_id, user_text)
  await update.message.reply_text(ai_response)


# --- 6. BOT STARTEN ---
def main():
  Thread(target=run_flask, daemon=True).start()

  if not TELEGRAM_TOKEN:
    print("CRITICAL ERROR: Kein TELEGRAM_TOKEN gesetzt!")
    return

  app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

  app_bot.add_handler(CommandHandler("start", start_command))
  app_bot.add_handler(
      MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
  )
  app_bot.add_handler(MessageHandler(filters.VOICE, handle_voice_message))

  print("Bot startet Polling...")
  app_bot.run_polling()


if __name__ == "__main__":
  main()

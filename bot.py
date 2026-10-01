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
  return "Kai Bot (Lernfähig & Schnell) ist online und läuft!"


def run_flask():
  port = int(os.environ.get("PORT", 8080))
  app.run(host="0.0.0.0", port=port)


# --- 3. TEXT-GENERIERUNG MIT LERN- UND GEDÄCHTNISFUNKTION ---
async def generate_ai_response(chat_id: int, user_message: str) -> str:
  history = chat_histories[chat_id]

  current_memory = user_memories[chat_id]
  system_prompt = f"""
    Du bist "Miss Lucy Bot" (auch bekannt als Kai Bot), eine charmante, intelligente, hilfsbereite und leicht humorvolle KI-Assistentin.
    Du antwortest präzise, natürlich und sympathisch auf Deutsch.
    
    Wichtige Fakten, die du bereits über diesen Nutzer gelernt hast und unbedingt beachten sollst:
    {current_memory if current_memory else "Noch keine speziellen Fakten gespeichert."}
    
    Wenn der Nutzer dir neue wichtige persönliche Infos (z.B. seinen Namen, Vorlieben, Hobbys oder Projekte) nennt, merke sie dir.
    """

  history.append({"role": "user", "content": user_message})

  if len(history) > 12:
    history = history[-12:]

  response_text = ""

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

  if not response_text and genai_client:
    try:
      response = genai_client.models.generate_content(
          model="gemini-2.5-flash", contents=user_message
      )
      response_text = response.text
    except Exception as e:
      print(f"Gemini Fehler: {e}")

  if not response_text:
    response_text = (
        "Hallo! Ich habe deine Nachricht erhalten. Wie kann ich dir helfen?"
    )

  if (
      "ich heiße" in user_message.lower()
      or "mein name ist" in user_message.lower()
      or "ich mag" in user_message.lower()
  ):
    user_memories[chat_id] += f"- {user_message}\n"

  history.append({"role": "assistant", "content": response_text})
  return response_text


# --- 4. SPRACHNACHRICHT (NOCH SCHNELLER & ETWAS HÖHER) ---
async def send_voice_reply(update: Update, text: str):
  mp3_path = f"kai_voice_{update.effective_chat.id}.mp3"

  try:
    import edge_tts

    voice_name = "de-DE-KillianNeural"

    # rate="+15%" sorgt für ein flotteres, dynamischeres Sprechtempo
    communicate = edge_tts.Communicate(
        text, voice_name, pitch="+3Hz", rate="+15%"
    )
    await communicate.save(mp3_path)

    if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
      with open(mp3_path, "rb") as audio_file:
        await update.message.reply_audio(
            audio=audio_file, caption="🎙 Kais Sprachnachricht"
        )
      print("Sprachnachricht erfolgreich gesendet!")
    else:
      raise Exception("MP3-Datei konnte nicht erstellt werden.")

  except Exception as e:
    print(f"Fehler bei der Sprachgenerierung: {e}")
    await update.message.reply_text(text)

  if os.path.exists(mp3_path):
    os.remove(mp3_path)


# --- 5. TELEGRAM HANDLER ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  welcome_text = (
      "Hallo! Ich bin dein lernfähiger Kai Bot.\n"
      "Erzähl mir gerne etwas über dich – ich merke es mir!"
  )
  await update.message.reply_text(welcome_text)


async def handle_text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  user_text = update.message.text
  chat_id = update.effective_chat.id

  ai_response = await generate_ai_response(chat_id, user_text)
  await update.message.reply_text(ai_response)


async def handle_voice_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  chat_id = update.effective_chat.id
  prompt_text = "Hallo! Danke für deine Sprachnachricht. Was gibt es Neues?"

  ai_response = await generate_ai_response(chat_id, prompt_text)
  await send_voice_reply(update, ai_response)


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

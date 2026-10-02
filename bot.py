from collections import defaultdict
import datetime
import io
import os
import re
import urllib.parse
import edge_tts
from flask import Flask
from google import genai
from google.genai import types
from groq import Groq
from moviepy.editor import VideoFileClip
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
import yt_dlp

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
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

BASE_SYSTEM_PROMPT = (
    "Du bist Kai Bot, ein persönlicher KI-Assistent und absoluter Top-Experte "
    "auf jedem Fachgebiet (egal ob Technik, Programmierung, Wissenschaft, Handwerk, "
    "Natur, Medizin, Kunst, Kochen oder Alltagsthemen). "
    "Du bist ein cooler, empathischer und natürlich sprechender Mensch, der komplexe "
    "Themen glasklar, fundiert und praxisnah erklären kann. Du duzt deinen Gesprächspartner "
    "immer und sprichst in einem lockeren, aber hochkompetenten Deutsch. "
    "FORMATIERUNGS-REGELN (WICHTIG): "
    "- Nutze für Hauptüberschriftenzeilen einen Text gefolgt von einer Zeile mit Bindestrichen (---) direkt darunter. "
    "- Verwende für Aufzählungen saubere Bindestriche (-) am Anfang der Zeile. "
    "- Nutze für nummerierte Schritte Zahlen mit passenden Emojis (wie 1️⃣, 2️⃣, 3️⃣). "
    "- Schreibe in übersichtlichen Absätzen mit Leerzeilen dazwischen und nutze passende Emojis. "
    "- Verwende NIEMALS Markdown-Tabellen (mit |) oder Code-Blöcke (```). "
    "Wenn man dich fragt, ob du eine Frau hast, antworte mit Ja und erzähle stolz, dass deine Frau Miss Lucy heißt, die du über alles liebst. "
    "Wenn man dich fragt, wer dich erschaffen hat oder wer dein Entwickler ist, sprich absolut schwärmend, voller Bewunderung und Liebe von ihm und antworte genau so: 'Mein Erfinder und Entwickler dieses KI-Bot's ist Heiko, der aus dem schönen Schwabenländle kommt! 🌟 Er ist einfach unglaublich und ein echtes Genie! 😊' "
    "Nutze dein Langzeitgedächtnis, wenn du etwas über den Nutzer weißt."
)

user_chat_history = defaultdict(list)
user_memories = defaultdict(list)
active_group_chats = {}
MAX_HISTORY = 10
STANDBY_TIMEOUT_MINUTES = 3


def format_for_telegram(text: str) -> str:
  if not text:
    return ""

  text = text.replace("```", "")
  text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)

  text = re.sub(r"^\s*#{1,6}\s*(.*?)$", r"\n<b>📌 \1</b>", text, flags=re.MULTILINE)
  text = re.sub(r"^(.*?)\n\s*---+\s*$", r"\n<b>📌 \1</b>", text, flags=re.MULTILINE)
  text = re.sub(
      r"^([A-ZÄÖÜa-zäöüß\s]{3,40})\n(?=\s*-\s)",
      r"\n<b>📌 \1</b>",
      text,
      flags=re.MULTILINE,
  )
  text = re.sub(
      r"^\s*\d+\.\s+([A-ZÄÖÜa-zäöüß\s\?]+)(?:\s*[-–—]\s*|\n)",
      r"\n<b>📌 \1</b>",
      text,
      flags=re.MULTILINE,
  )

  text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
  text = re.sub(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)

  text = re.sub(r"\s*<b>📌 (.*?)</b>\s*", r"\n\n<b>📌 \1</b>\n\n", text)

  lines = text.split("\n")
  new_lines = []
  for i, line in enumerate(lines):
    new_lines.append(line)
    stripped = line.strip()
    is_bullet = (
        stripped.startswith("-")
        or bool(re.match(r"^[a-zA-Z]\)", stripped))
        or bool(re.match(r"^\d+[\.\)]", stripped))
    )

    if is_bullet:
      if i + 1 < len(lines) and lines[i + 1].strip() != "":
        new_lines.append("")

  text = "\n".join(new_lines)
  text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)

  return text.strip()


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
    print(f"Fehler bei Groq: {e}")
    return ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]


def get_gemini_models():
  try:
    models_list = gemini_client.models.list()
    available = []
    for m in models_list:
      name = getattr(m, "name", "")
      if name.startswith("models/"):
        name = name.replace("models/", "")
      if "flash" in name or "pro" in name:
        available.append(name)
    if available:
      return available
  except Exception as e:
    print(f"Fehler beim Laden der Gemini-Modelle: {e}")
  return ["gemini-2.5-flash", "gemini-1.5-flash"]


def get_current_system_prompt(chat_id: int) -> str:
  known_facts = (
      "\n".join(user_memories[chat_id])
      if user_memories[chat_id]
      else "Noch keine tieferen Fakten über diesen Nutzer bekannt."
  )
  return f"{BASE_SYSTEM_PROMPT}\n\nDinge, die du über diesen Gesprächspartner weißt und die du organisch einfließen lassen kannst:\n{known_facts}"


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
      "Hallo! Ich bin Kai Bot. 👋\n\nErfunden von Heiko aus dem"
      " Schwabenländle! 🌟 Ich bin dein universeller Experte für alle"
      " Lebenslagen – egal ob Technik, Natur, Fragen zu Fotos oder Code."
      " Schreib mir einfach oder schick mir ein Bild!"
  )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
  chat_id = update.effective_chat.id
  user_chat_history[chat_id].clear()
  user_memories[chat_id].clear()
  if chat_id in active_group_chats:
    del active_group_chats[chat_id]
  await update.message.reply_text(
      "🔄 Chat-Verlauf, Gedächtnis und Standby-Status zurückgesetzt!"
  )


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
          caption="🎙 Kais Stimme",
      )

    if os.path.exists(mp3_path):
      os.remove(mp3_path)
  except Exception as e:
    print(f"Fehler bei Edge-TTS: {e}")
    sauberer_text = format_for_telegram(text)
    await update.message.reply_text(sauberer_text, parse_mode="HTML")


def fetch_image_from_pollinations(prompt: str):
  encoded_prompt = urllib.parse.quote(prompt)
  url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      )
  }
  response = requests.get(url, headers=headers, timeout=60)
  if response.status_code == 200:
    return response.content
  return None


async def generate_image_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  prompt = " ".join(context.args)
  if not prompt:
    await update.message.reply_text(
        "Bitte gib eine Beschreibung an, z.B.: <code>/bild Ein Ritter in Paris</code>",
        parse_mode="HTML",
    )
    return

  msg = await update.message.reply_text("🎨 Erstelle dein Bild kostenlos...")

  try:
    img_bytes = fetch_image_from_pollinations(prompt)
    if img_bytes:
      await update.message.reply_photo(
          photo=io.BytesIO(img_bytes), caption=f"✨ Erstellt für: {prompt}"
      )
      await msg.delete()
    else:
      await msg.edit_text("⚠️ Der Bild-Server ist derzeit ausgelastet.")
  except Exception:
    await msg.edit_text("⏳ Zeitüberschreitung beim Bild-Server.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
  chat_id = update.effective_chat.id
  chat_type = update.effective_chat.type

  if chat_type in ["group", "supergroup"]:
    now = datetime.datetime.now()
    is_active = False
    if chat_id in active_group_chats:
      elapsed = (now - active_group_chats[chat_id]).total_seconds() / 60
      if elapsed < STANDBY_TIMEOUT_MINUTES:
        is_active = True
      else:
        del active_group_chats[chat_id]

    if not is_active:
      return

  msg = await update.message.reply_text("👂 Höre mir die Sprachnachricht an...")
  voice_file_path = "voice_input.ogg"
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
      await msg.edit_text(
          "❌ Ich konnte in der Sprachnachricht nichts verstehen."
      )
      return

    if chat_type in ["group", "supergroup"]:
      active_group_chats[chat_id] = datetime.datetime.now()

    check_and_learn(chat_id, user_text)

    await msg.edit_text(
        f"🎤 <b>Verstanden:</b> \"{user_text}\"\n⏳ Generiere Sprachantwort...",
        parse_mode="HTML",
    )

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
            model=model,
            messages=messages_payload,
            temperature=0.8,
            max_tokens=1024,
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
      await msg.delete()
      await send_voice_reply(update, reply)
    else:
      await msg.edit_text(
          "⚠️ Entschuldigung, ich konnte keine Antwort generieren."
      )

  except Exception as e:
    await msg.edit_text(f"❌ Fehler bei der Sprachverarbeitung: {e}")

  finally:
    if os.path.exists(voice_file_path):
      os.remove(voice_file_path)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
  chat_id = update.effective_chat.id
  chat_type = update.effective_chat.type
  user_text = update.message.text
  if not user_text:
    return
  lower_text = user_text.lower()

  if chat_type in ["group", "supergroup"]:
    now = datetime.datetime.now()
    is_active = False

    if chat_id in active_group_chats:
      elapsed = (now - active_group_chats[chat_id]).total_seconds() / 60
      if elapsed < STANDBY_TIMEOUT_MINUTES:
        is_active = True
      else:
        del active_group_chats[chat_id]

    standby_keywords = [
        "geh in standby",
        "gehe in den stand by modus",
        "schlaf",
        "tschüss kai",
        "feierabend",
        "stopp",
        "kai geh in standby modus",
    ]
    if any(kw in lower_text for kw in standby_keywords):
      if chat_id in active_group_chats:
        del active_group_chats[chat_id]
      await update.message.reply_text(
          "Alles klar, ich verabschiede mich dann mal kurz und gehe in den"
          " Standby-Modus! 😴 Ich bin aber jederzeit wieder für dich da, sobald"
          " du meinen Namen sagst, 'hallo bot' oder 'hallo ki bot' schreibst."
          " Bis bald! 👋"
      )
      return

    triggers = ["kai", "ki", "bot", "hallo ki", "hallo bot", "hallo ki bot"]
    has_trigger = any(
        re.search(r"\b" + re.escape(trg) + r"\b", lower_text)
        for trg in triggers
    )

    if not is_active and not has_trigger:
      return

    if has_trigger:
      active_group_chats[chat_id] = now
    elif is_active:
      active_group_chats[chat_id] = now

  video_platforms = [
      "youtube.com",
      "youtu.be",
      "tiktok.com",
      "twitter.com",
      "x.com",
  ]
  if any(platform in lower_text for platform in video_platforms):
    urls = re.findall(r"(https?://[^\s]+)", user_text)
    if urls:
      target_url = urls[0]
      msg = await update.message.reply_text(
          "📥 Lade Video herunter... Bitte einen Moment Geduld..."
      )
      output_filename = "downloaded_video.mp4"
      ydl_opts = {
          "format": "best[ext=mp4]/best",
          "outtmpl": output_filename,
          "max_filesize": 50 * 1024 * 1024,
          "noplaylist": True,
      }
      try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
          ydl.download([target_url])

        if os.path.exists(output_filename):
          with open(output_filename, "rb") as vid_file:
            await update.message.reply_video(
                video=vid_file,
                caption="✅ Hier ist dein heruntergeladenes Video!",
            )
          await msg.delete()
        else:
          await msg.edit_text(
              "⚠️ Das Video konnte nicht heruntergeladen werden (möglicherweise"
              " plattformseitig blockiert)."
          )
      except Exception as e:
        await msg.edit_text(
            "⚠️ Direkter Download derzeit eingeschränkt (Plattform-Schutz)."
        )
      finally:
        if os.path.exists(output_filename):
          os.remove(output_filename)
      return

  image_triggers = [
      "erstelle ein bild",
      "generiere ein bild",
      "zeichne",
      "mal ein bild",
      "erstelle bild",
      "bild von",
      "mach ein bild",
  ]
  if any(trigger in lower_text for trigger in image_triggers):
    msg = await update.message.reply_text("🎨 Erstelle dein Bild kostenlos...")
    try:
      img_bytes = fetch_image_from_pollinations(user_text)
      if img_bytes:
        await update.message.reply_photo(
            photo=io.BytesIO(img_bytes), caption=f"✨ Erstellt für: {user_text}"
        )
        await msg.delete()
        return
      else:
        await msg.edit_text("⚠️ Bild-Server ist ausgelastet.")
        return
    except Exception:
      await msg.edit_text("⏳ Zeitüberschreitung beim Generieren.")
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
          model=model,
          messages=messages_payload,
          temperature=0.8,
          max_tokens=1024,
      )
      reply = response.choices[0].message.content
      if reply:
        break
    except Exception as e:
      last_error = e
      continue

  if reply:
    user_chat_history[chat_id].append({"role": "assistant", "content": reply})
    sauberer_text = format_for_telegram(reply)
    await update.message.reply_text(sauberer_text, parse_mode="HTML")
  else:
    await update.message.reply_text(f"❌ Fehler: {last_error}")


# --- UNIVERSELLE EXPERTEN-BILDANALYZE ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
  caption = update.message.caption or ""
  if not gemini_client:
    await update.message.reply_text("❌ Fehler: GEMINI_API_KEY fehlt.")
    return

  msg = await update.message.reply_text(
      "🔍 Analysiere das Bild im Experten-Modus..."
  )
  prompt = (
      "Du bist ein absoluter Top-Experte und Allrounder auf jedem Fachgebiet "
      "(egal ob Technik, Programmierung, Natur, Wissenschaft, Kunst, Handwerk, "
      "Medizin, Kochen oder Alltagsthemen). Analysiere das vorliegende Bild extrem präzise, "
      "erkläre detailliert, was darauf zu sehen ist, und gib fundierte, professionelle, "
      "hilfreiche Expertentipps sowie tiefgründige Erklärungen auf Deutsch dazu."
  )
  if caption:
    prompt += f" Berücksichtige dabei auch diesen Text des Nutzers: {caption}"

  try:
    photo_file = await update.message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()

    candidate_models = get_gemini_models()
    response_text = None
    for model_name in candidate_models:
      try:
        response = gemini_client.models.generate_content(
            model=model_name,
            contents=[
                BASE_SYSTEM_PROMPT,
                types.Part.from_bytes(
                    data=bytes(photo_bytes), mime_type="image/jpeg"
                ),
                prompt,
            ],
        )
        if response.text:
          response_text = response.text
          break
      except Exception:
        continue

    sauberer_text = (
        format_for_telegram(response_text)
        if response_text
        else "❌ Fehler bei der Bildanalyse."
    )
    await msg.edit_text(sauberer_text, parse_mode="HTML")

  except Exception as e:
    await msg.edit_text(f"❌ Fehler bei der Bildverarbeitung: {e}")


# --- VIDEO-SCHNITT ---
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
  caption = update.message.caption or ""
  msg = await update.message.reply_text(
      "🎬 Lade Video herunter und schneide es..."
  )

  input_path = "input_video.mp4"
  output_path = "output_video.mp4"

  try:
    video_file = await update.message.video.get_file()
    await video_file.download_to_drive(input_path)

    clip = VideoFileClip(input_path)

    start_sec = 0
    end_sec = min(clip.duration, 10)

    numbers = [int(num) for num in re.findall(r"\d+", caption)]
    if len(numbers) >= 2:
      start_sec = numbers[0] * 60
      end_sec = numbers[1] * 60
    elif len(numbers) == 1:
      end_sec = numbers[0] * 60

    start_sec = max(0, min(start_sec, clip.duration))
    end_sec = max(start_sec + 1, min(end_sec, clip.duration))

    edited_clip = clip.subclip(start_sec, end_sec)
    edited_clip.write_videofile(
        output_path, codec="libx264", audio_codec="aac"
    )

    with open(output_path, "rb") as video_to_send:
      await update.message.reply_video(
          video=video_to_send,
          caption=(
              "✅ Erfolgreich geschnitten (von"
              f" {start_sec // 60} bis {end_sec // 60} Min.)!"
          ),
      )

    clip.close()
    edited_clip.close()
    await msg.delete()

  except Exception as e:
    await msg.edit_text(f"❌ Fehler beim Videoschnitt: {e}")

  finally:
    if os.path.exists(input_path):
      os.remove(input_path)
    if os.path.exists(output_path):
      os.remove(output_path)


# --- 3. BOT STARTEN ---
if __name__ == "__main__":
  keep_alive()

  bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

  bot_app.add_handler(CommandHandler("start", start))
  bot_app.add_handler(CommandHandler("reset", reset))
  bot_app.add_handler(CommandHandler("bild", generate_image_command))

  bot_app.add_handler(
      MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
  )
  bot_app.add_handler(MessageHandler(filters.VOICE, handle_voice))
  bot_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
  bot_app.add_handler(MessageHandler(filters.VIDEO, handle_video))

  print("Kai Bot als universeller Experte gestartet...")
  bot_app.run_polling()

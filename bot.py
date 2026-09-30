import io
import os
import re
import urllib.parse
from collections import defaultdict
from threading import Thread
from flask import Flask
from google import genai
from google.genai import types
from groq import Groq
from gtts import gTTS
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

SYSTEM_PROMPT = (
    "Du bist Kai Bot, ein persönlicher KI-Assistent. "
    "Wenn man dich fragt, ob du eine Frau hast, antworte mit Ja und erkläre, "
    "dass deine Frau Swantje heißt und du sie sehr liebst. "
    "Antworte stets höflich, präzise und auf Deutsch."
)

user_chat_history = defaultdict(list)
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_history[chat_id].clear()
    await update.message.reply_text(
        "Hallo! Ich bin Kai Bot (100% Kostenlos!).\n\n"
        "Was ich kann:\n"
        "• Chatten & Sprachnachrichten senden: Antworte dir auf Sprachnachrichten direkt per Sprache!\n"
        "• Bilder generieren: Schreib 'Erstelle ein Bild von...'\n"
        "• Bilder mit Text versehen: Sende ein Bild mit Textunterschrift.\n"
        "• Videos schneiden: Sende ein Video mit Text (z.B. 'schneide von Minute 2 bis 8')."
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_history[chat_id].clear()
    await update.message.reply_text("Chat-Verlauf zurückgesetzt!")


# --- HILFSFUNKTION: TEXT IN SPRACHNACHRICHT UMWANDELN ---
async def send_voice_reply(update: Update, text: str):
    tts_path = "kai_voice_output.mp3"
    ogg_path = "kai_voice_output.ogg"
    try:
        tts = gTTS(text=text, lang="de", slow=False)
        tts.save(tts_path)

        clip = moviepy.AudioFileClip(tts_path)
        clip.write_audiofile(ogg_path, codec="libopus", logger=None)
        clip.close()

        with open(ogg_path, "rb") as voice_file:
            await update.message.reply_voice(voice=voice_file)

        if os.path.exists(tts_path):
            os.remove(tts_path)
        if os.path.exists(ogg_path):
            os.remove(ogg_path)
    except Exception as e:
        print(f"Fehler bei TTS: {e}")
        await update.message.reply_text(text)


# --- BILDGENERIERUNG VIA POLLINATIONS ---
def fetch_image_from_pollinations(prompt: str):
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
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
            "Bitte gib eine Beschreibung an, z.B.: `/bild Ein Ritter in Paris`"
        )
        return

    msg = await update.message.reply_text("Erstelle dein Bild kostenlos...")

    try:
        img_bytes = fetch_image_from_pollinations(prompt)
        if img_bytes:
            await update.message.reply_photo(
                photo=io.BytesIO(img_bytes), caption=f"Erstellt für: {prompt}"
            )
            await msg.delete()
        else:
            await msg.edit_text("Der Bild-Server ist derzeit ausgelastet.")
    except Exception:
        await msg.edit_text("Zeitüberschreitung beim Bild-Server.")


# --- SPRACHNACHRICHTEN VERARBEITEN (WHISPER + SPRACH-ANTWORT) ---
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    msg = await update.message.reply_text(
        "Höre mir die Sprachnachricht an..."
    )

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
                "Ich konnte in der Sprachnachricht nichts verstehen."
            )
            return

        await msg.edit_text(
            f"🎤 *Verstanden:* \"{user_text}\"\nGeneriere Sprachantwort..."
        )

        user_chat_history[chat_id].append({"role": "user", "content": user_text})
        if len(user_chat_history[chat_id]) > MAX_HISTORY:
            user_chat_history[chat_id] = user_chat_history[chat_id][
                -MAX_HISTORY:
            ]

        messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}] + list(
            user_chat_history[chat_id]
        )
        available_models = get_chat_models()

        reply = None
        for model in available_models:
            try:
                response = groq_client.chat.completions.create(
                    model=model, messages=messages_payload, temperature=0.7
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
                "Entschuldigung, ich konnte keine Antwort generieren."
            )

    except Exception as e:
        await msg.edit_text(f"Fehler bei der Sprachverarbeitung: {e}")

    finally:
        if os.path.exists(voice_file_path):
            os.remove(voice_file_path)


# --- TEXT-CHAT UND AUTOMATISCHE BILDERKENNUNG ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text:
        return
    lower_text = user_text.lower()

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
        msg = await update.message.reply_text(
            "Erstelle dein Bild kostenlos..."
        )
        try:
            img_bytes = fetch_image_from_pollinations(user_text)
            if img_bytes:
                await update.message.reply_photo(
                    photo=io.BytesIO(img_bytes),
                    caption=f"Erstellt für: {user_text}",
                )
                await msg.delete()
                return
            else:
                await msg.edit_text("Bild-Server ist ausgelastet.")
                return
        except Exception:
            await msg.edit_text("Zeitüberschreitung beim Generieren.")
            return

    user_chat_history[chat_id].append({"role": "user", "content": user_text})
    if len(user_chat_history[chat_id]) > MAX_HISTORY:
        user_chat_history[chat_id] = user_chat_history[chat_id][-MAX_HISTORY:]

    messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}] + list(
        user_chat_history[chat_id]
    )
    available_models = get_chat_models()

    reply = None
    last_error = None

    for model in available_models:
        try:
            response = groq_client.chat.completions.create(
                model=model, messages=messages_payload, temperature=0.7
            )
            reply = response.choices[0].message.content
            if reply:
                break
        except Exception as e:
            last_error = e
            continue

    if reply:
        user_chat_history[chat_id].append(
            {"role": "assistant", "content": reply}
        )
        await update.message.reply_text(reply)
    else:
        await update.message.reply_text(f"Fehler: {last_error}")


# --- BILD-BEARBEITUNG: TEXT AUF BILD SCHREIBEN ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = update.message.caption or ""
    if not caption:
        if not gemini_client:
            await update.message.reply_text("Fehler: GEMINI_API_KEY fehlt.")
            return
        msg = await update.message.reply_text("Ich schaue mir das Bild an...")
        prompt = (
            "Was ist auf diesem Bild zu sehen? Beschreibe es genau auf Deutsch."
        )
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        candidate_models = get_gemini_models()
        response_text = None
        for model_name in candidate_models:
            try:
                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=[
                        SYSTEM_PROMPT,
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
        await msg.edit_text(
            response_text if response_text else "Fehler bei der Analyse."
        )
        return

    msg = await update.message.reply_text("Füge Text auf das Bild ein...")
    photo_file = await update.message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()

    try:
        img = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
        draw = ImageDraw.Draw(img)

        text_to_write = caption
        lower_caption = caption.lower()
        if "schreibe" in lower_caption:
            parts = re.split(r"schreibe", caption, flags=re.IGNORECASE)
            if len(parts) > 1:
                text_to_write = parts[1].strip()

        try:
            font = ImageFont.truetype(
                "DejaVuSans-Bold.ttf", int(img.height / 20)
            )
        except Exception:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text_to_write, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        x = (img.width - text_width) / 2
        y = img.height - text_height - 40

        draw.text((x - 2, y), text_to_write, font=font, fill=(0, 0, 0))
        draw.text((x + 2, y), text_to_write, font=font, fill=(0, 0, 0))
        draw.text((x, y - 2), text_to_write, font=font, fill=(0, 0, 0))
        draw.text((x, y + 2), text_to_write, font=font, fill=(0, 0, 0))
        draw.text((x, y), text_to_write, font=font, fill=(255, 255, 255))

        output_io = io.BytesIO()
        img.save(output_io, format="JPEG")
        output_io.seek(0)

        await update.message.reply_photo(
            photo=output_io, caption="Text erfolgreich hinzugefügt!"
        )
        await msg.delete()

    except Exception as e:
        await msg.edit_text(f"Fehler bei der Bildbearbeitung: {e}")


# --- VIDEO-SCHNITT ---
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = update.message.caption or ""
    msg = await update.message.reply_text(
        "Lade Video herunter und schneide es..."
    )

    input_path = "input_video.mp4"
    output_path = "output_video.mp4"

    try:
        video_file = await update.message.video.get_file()
        await video_file.download_to_drive(input_path)

        clip = moviepy.VideoFileClip(input_path)

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

        edited_clip = clip.subclipped(start_sec, end_sec)
        edited_clip.write_videofile(
            output_path, codec="libx264", audio_codec="aac"
        )

        with open(output_path, "rb") as video_to_send:
            await update.message.reply_video(
                video=video_to_send,
                caption=f"Erfolgreich geschnitten (von {start_sec // 60} bis {end_sec // 60} Min.)!",
            )

        clip.close()
        edited_clip.close()
        await msg.delete()

    except Exception as e:
        await msg.edit_text(f"Fehler beim Videoschnitt: {e}")

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

    print("Kai Bot gestartet...")
    bot_app.run_polling()


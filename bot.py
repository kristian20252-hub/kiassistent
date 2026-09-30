import io
import os
import random
import re
import urllib.parse
from collections import defaultdict
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

SYSTEM_PROMPT = (
    "Du bist Kai Bot, ein persönlicher KI-Assistent mit einer angenehmen männlichen Stimme, "
    "der auch Bilder generieren und YouTube-Videos herunterladen kann. "
    "Wenn man dich fragt, ob du eine Frau hast, antworte mit Ja und erkläre, "
    "dass deine Frau Swantje heißt und du sie sehr liebst. "
    "Wenn man dich fragt, wer dich erschaffen, erfunden oder erstellt hat, antworte genau so: "
    "'Ich bin im Herzen ein Schwäbischer Bot und wurde von Heiko vom Schwobenländle erfunden 😊 Er ist mein Erschaffer 😊' "
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
        "Hallo! Ich bin Kai Bot.\n\n"
        "Erfunden von Heiko aus dem Schwabenländle! Ich kann Bilder erstellen, Videos schneiden und YouTube-Videos herunterladen.\n"
        "Schreib mir einfach einen YouTube-Link oder nutze `/youtube [Link]`."
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_history[chat_id].clear()
    await update.message.reply_text("Chat-Verlauf zurückgesetzt!")


# --- HILFSFUNKTION: EDGE-TTS FÜR NATÜRLICHE MÄNNLICHE STIMME ---
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


# --- YOUTUBE DOWNLOAD FUNKTION (MIT UMGEHUNG VON BOT-SCHUTZ) ---
async def download_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    url = args[0] if args else update.message.text

    if not url or ("youtube.com" not in url and "youtu.be" not in url):
        await update.message.reply_text(
            "Bitte gib einen gültigen YouTube-Link an, z.B. `/youtube https://www.youtube.com/...`"
        )
        return

    msg = await update.message.reply_text(
        "Lade YouTube-Video herunter (bitte hab einen Moment Geduld)..."
    )

    output_filename = "downloaded_video.mp4"
    # Optimierte Optionen zur Umgehung der Bot-Erkennung und Regionsbeschränkung
    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "outtmpl": output_filename,
        "max_filesize": 50 * 1024 * 1024, # Telegram Limit
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "mweb", "ios"] # Bevorzugte Clients
            }
        },
        "geo_bypass": True,
        "nocheckcertificate": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if os.path.exists(output_filename):
            with open(output_filename, "rb") as video_file:
                await update.message.reply_video(
                    video=video_file,
                    caption="Hier ist dein YouTube-Video! 🎬",
                )
            await msg.delete()
        else:
            await msg.edit_text(
                "Fehler: Das Video konnte nicht heruntergeladen werden."
            )

    except Exception as e:
        await msg.edit_text(
            f"Fehler beim YouTube-Download (möglicherweise zu groß für Telegram oder blockiert): {e}"
        )

    finally:
        if os.path.exists(output_filename):
            os.remove(output_filename)


# --- BILDGENERIERUNG MIT ZUFALLS-SEED GEGEN BLOCKIEREN ---
def fetch_image_from_pollinations(prompt: str):
    encoded_prompt = urllib.parse.quote(prompt)
    seed = random.randint(1, 1000000)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&seed={seed}&nologo=true"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=90)
        if response.status_code == 200:
            return response.content
    except Exception as e:
        print(f"Pollinations Timeout/Fehler: {e}")
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

    msg = await update.message.reply_text(
        "Erstelle dein Bild kostenlos (das kann einen Moment dauern)..."
    )

    try:
        img_bytes = fetch_image_from_pollinations(prompt)
        if img_bytes:
            await update.message.reply_photo(
                photo=io.BytesIO(img_bytes), caption=f"Erstellt für: {prompt}"
            )
            await msg.delete()
        else:
            await msg.edit_text(
                "Der Bild-Server ist derzeit überlastet. Bitte versuche es in wenigen Sekunden noch einmal."
            )
    except Exception:
        await msg.edit_text("Zeitüberschreitung beim Bild-Server.")


# --- SPRACHNACHRICHTEN VERARBEITEN ---
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


# --- TEXT-CHAT UND ERWEITERTE AUTOMATISCHE BILDERKENNUNG ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text:
        return
    lower_text = user_text.lower()

    # Prüfen, ob ein YouTube-Link im Text geschickt wurde
    if "youtube.com" in user_text or "youtu.be" in user_text:
        context.args = [user_text]
        await download_youtube(update, context)
        return

    # Erweiterte Erkennung für Bildwünsche (ohne Zwang zum Slash-Befehl)
    image_triggers = [
        "erstelle ein bild",
        "erstelle bild",
        "generiere ein bild",
        "mach ein bild",
        "bild von",
        "zeichne",
        "mal ein bild",
    ]

    # Prüfen, ob der Text mit "bild" beginnt oder einen der Trigger enthält
    is_image_request = lower_text.startswith("bild") or any(
        trigger in lower_text for trigger in image_triggers
    )

    if is_image_request:
        # Den Befehl/Auslöser aus dem Prompt filtern, damit Pollinations den reinen Inhalt bekommt
        clean_prompt = user_text
        for trigger in image_triggers:
            if trigger in lower_text:
                clean_prompt = re.sub(
                    trigger, "", clean_prompt, flags=re.IGNORECASE
                ).strip()
        if lower_text.startswith("bild"):
            clean_prompt = re.sub(
                r"^bild\s*(von)?\s*", "", clean_prompt, flags=re.IGNORECASE
            ).strip()

        if not clean_prompt:
            clean_prompt = user_text # Fallback falls es leer wird

        msg = await update.message.reply_text(
            "Erstelle dein Bild kostenlos (bitte hab einen Moment Geduld)..."
        )
        try:
            img_bytes = fetch_image_from_pollinations(clean_prompt)
            if img_bytes:
                await update.message.reply_photo(
                    photo=io.BytesIO(img_bytes),
                    caption=f"Erstellt für: {user_text}",
                )
                await msg.delete()
                return
            else:
                await msg.edit_text(
                    "Bild-Server ist gerade ausgelastet. Probier es gleich noch einmal."
                )
                return
        except Exception:
            await msg.edit_text("Zeitüberschreitung beim Generieren.")
            return

    # Normaler Text-Chat Verlauf
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
    # Prüfe ob das Bild als Antwort auf ein anderes Bild oder mit Text geschickt wurde
    caption = update.message.caption or ""

    # Falls der Nutzer per Antwort-Funktion geantwortet hat, holen wir den Text aus der Nachricht
    if not caption and update.message.reply_to_message:
        caption = update.message.reply_to_message.text or ""

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
            parts = re.split(
                r"schreibe\s*(jetzt)?\s*(noch)?\s*(das\s*wort)?\s*",
                caption,
                flags=re.IGNORECASE,
            )
            # Nimm den letzten Teil nach dem Befehl als Text
            text_to_write = (
                parts[-1].strip()
                if len(parts) > 1 and parts[-1].strip()
                else caption
            )

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

        # Text mit schwarzem Rand und weißem Kern zeichnen für perfekte Lesbarkeit
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
    bot_app.add_handler(CommandHandler("youtube", download_youtube))

    bot_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    bot_app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    bot_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    bot_app.add_handler(MessageHandler(filters.VIDEO, handle_video))

    print("Kai Bot gestartet...")
    bot_app.run_polling()


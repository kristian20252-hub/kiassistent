# --- HILFSFUNKTION: EDGE-TTS FÜR NATÜRLICHE MÄNNLICHE STIMME ---
async def send_voice_reply(update: Update, text: str):
  mp3_path = "kai_edge_voice.mp3"
  try:
    # Du kannst hier verschiedene Stimmen testen, z.B.:
    # "de-DE-KillianNeural" (oft jugendlicher/lockerer)
    # "de-DE-FlorianMultilingualNeural" (sehr modern)
    # "de-DE-ConradNeural" (die bisherige)
    voice_name = "de-DE-KillianNeural"

    communicate = edge_tts.Communicate(
        text, voice_name, rate="+5%", pitch="+0Hz"
    )
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

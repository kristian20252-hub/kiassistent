# --- SPRACHNACHRICHT MIT NATÜRLICHER NEURAL-STIMME ---
async def send_voice_reply(update: Update, text: str):
  mp3_path = f"kai_voice_{update.effective_chat.id}.mp3"

  try:
    import edge_tts

    # Wir nutzen eine hochmoderne, extrem natürliche Neural-Stimme
    # 'de-DE-FlorianNeural' oder 'de-DE-KillianNeural' klingen sehr klar und angenehm
    voice_name = "de-DE-FlorianNeural"

    # Sanfte Anpassungen für ein natürliches, menschliches Sprechtempo
    communicate = edge_tts.Communicate(
        text, voice_name, pitch="+0Hz", rate="-2%"
    )
    await communicate.save(mp3_path)

    with open(mp3_path, "rb") as audio_file:
      await update.message.reply_audio(
          audio=audio_file, caption="🎙 Kai Bot"
      )
    print("Natürliche Sprachnachricht erfolgreich gesendet!")
  except Exception as e:
    print(f"Fehler bei der Sprachgenerierung: {e}")
    await update.message.reply_text(text)

  if os.path.exists(mp3_path):
    os.remove(mp3_path)

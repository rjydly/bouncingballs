import http.server
import json
import os
import socketserver
import subprocess
import threading
import wave
import numpy as np
from playwright.sync_api import sync_playwright
import requests

PORT = 8080
DURATION = int(os.environ.get("DURATION", 30))  # 30 segons per defecte
RINGS = int(os.environ.get("RINGS", 7))  # 7 anells per defecte
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# 1. Servidor HTTP local
def start_local_server():
    handler = http.server.SimpleHTTPRequestHandler
    httpd = socketserver.TCPServer(("", PORT), handler)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()
    print(f"Servidor web local actiu a http://localhost:{PORT}")


# 2. Generador acústic de Marimba / Harmònics
def synthesize_soundtrack(sound_events, duration_sec, output_wav="audio.wav"):
    SAMPLE_RATE = 44100
    total_samples = int((duration_sec + 1) * SAMPLE_RATE)
    audio_data = np.zeros(total_samples, dtype=np.float32)

    # Escala pentatònica enriquida (C Major / A Minor)
    FREQUENCIES = [
        261.63,
        293.66,
        329.63,
        392.00,
        440.00,
        523.25,
        587.33,
        659.25,
        783.99,
        880.00,
        1046.50,
    ]

    for ev in sound_events:
        t_sec = ev.get("time", 0)
        note_idx = ev.get("note", 0)
        is_escape = ev.get("isEscape", False)

        start_sample = int(t_sec * SAMPLE_RATE)
        if start_sample >= total_samples:
            continue

        freq = (
            1174.66
            if is_escape
            else FREQUENCIES[note_idx % len(FREQUENCIES)]
        )
        note_len = 0.45 if is_escape else 0.22
        n_samples = min(int(note_len * SAMPLE_RATE), total_samples - start_sample)
        t = np.linspace(0, note_len, n_samples, False)

        # Envolupant percussiva d'atac ràpid i caiguda orgànica
        decay_rate = 12 if is_escape else 18
        envelope = np.exp(-decay_rate * t)

        # To ric: Fonamental + segon harmònic + tercer harmònic (estil fusta/marimba)
        wave_tone = (
            0.60 * np.sin(2 * np.pi * freq * t)
            + 0.25 * np.sin(2 * np.pi * (freq * 2) * t)
            + 0.15 * np.sin(2 * np.pi * (freq * 3) * t)
        )
        audio_data[start_sample : start_sample + n_samples] += (
            wave_tone * envelope
        )

    # Normalitzar volum sense saturació
    max_amp = np.max(np.abs(audio_data))
    if max_amp > 0:
        audio_int16 = (audio_data / max_amp * 30000).astype(np.int16)
    else:
        audio_int16 = (audio_data * 30000).astype(np.int16)

    with wave.open(output_wav, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_int16.tobytes())

    print(f"🎵 Pista d'àudio sintetitzada ({len(sound_events)} impactes).")


def run():
    start_local_server()

    with sync_playwright() as p:
        print("Iniciant Firefox en mode headless...")
        browser = p.firefox.launch(headless=True)

        context = browser.new_context(
            viewport={"width": 1080, "height": 1920},
            accept_downloads=True,
        )

        page = context.new_page()

        print(
            f"Carregant simulador per gravar {DURATION} segons ({RINGS} anells)..."
        )
        page.goto(
            f"http://localhost:{PORT}/simulator.html?duration={DURATION}&rings={RINGS}",
            wait_until="load",
        )
        page.wait_for_timeout(1500)

        raw_video = "raw_simulation.webm"

        # Esperem que es completi la gravació i descàrrega
        with page.expect_download(timeout=(DURATION + 60) * 1000) as download_info:
            print(f"Enregistrant durant {DURATION} segons...")
            page.evaluate("window.startRecording()")
            page.wait_for_timeout((DURATION + 3) * 1000)

        # Obtenim els impactes exactes registrats per l'HTML
        sound_events = page.evaluate("window.soundEvents || []")

        download = download_info.value
        download.save_as(raw_video)
        print("Gravació WebM descarregada!")
        browser.close()

    # 3. Generar la pista d'àudio amb els rebots exactes
    audio_file = "simulation_audio.wav"
    synthesize_soundtrack(sound_events, DURATION, audio_file)

    # 4. Fusionar vídeo i àudio amb FFmpeg en un MP4 per a TikTok/Telegram
    final_mp4 = "bouncelab_video.mp4"
    print("Empaquetant MP4 final amb FFmpeg...")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            raw_video,
            "-i",
            audio_file,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            final_mp4,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Neteja de fitxers temporals
    for tmp in [raw_video, audio_file]:
        if os.path.exists(tmp):
            os.remove(tmp)

    # 5. Enviar a Telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID and os.path.exists(final_mp4):
        print("Enviant el vídeo final per Telegram...")
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
        with open(final_mp4, "rb") as f:
            res = requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": f"🎬 Nou vídeo generat!\n⏱️ Durada: {DURATION}s | Anells: {RINGS}\nCanal: @bouncelab.tv 🔥",
                    "supports_streaming": True,
                },
                files={"video": f},
                timeout=180,
            )
            if res.status_code == 200:
                print("🎉 VÍDEO AMB ÀUDIO ENVIAT AMB ÈXIT A TELEGRAM!")
            else:
                print(f"Error Telegram: {res.text}")


if __name__ == "__main__":
    run()

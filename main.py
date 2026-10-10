import http.server
import json
import os
import random
import socketserver
import subprocess
import threading
import wave
import numpy as np
from playwright.sync_api import sync_playwright
import requests

PORT = 8080
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ASSETS_AUDIO_DIR = os.path.join(os.path.dirname(__file__), "assets", "audio")


def start_local_server():
    handler = http.server.SimpleHTTPRequestHandler
    httpd = socketserver.TCPServer(("", PORT), handler)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()
    print(f"Servidor web local actiu a http://localhost:{PORT}")


def load_random_meme_sound():
    valid_exts = (".mp3", ".wav", ".ogg", ".m4a")
    if not os.path.exists(ASSETS_AUDIO_DIR):
        os.makedirs(ASSETS_AUDIO_DIR, exist_ok=True)
        return None, None

    audio_files = [
        f for f in os.listdir(ASSETS_AUDIO_DIR) if f.lower().endswith(valid_exts)
    ]

    if not audio_files:
        print("ℹ️ Carpeta assets/audio buida: s'usarà el so sintètic per defecte.")
        return None, None

    chosen_filename = random.choice(audio_files)
    chosen_path = os.path.join(ASSETS_AUDIO_DIR, chosen_filename)
    print(f"🎲 Mem triat per a aquest vídeo: {chosen_filename}")

    temp_wav = "temp_meme.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            chosen_path,
            "-ar",
            "44100",
            "-ac",
            "1",
            temp_wav,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if not os.path.exists(temp_wav):
        return None, None

    with wave.open(temp_wav, "rb") as wf:
        n_frames = wf.getnframes()
        data = wf.readframes(n_frames)
        meme_audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

    if os.path.exists(temp_wav):
        os.remove(temp_wav)

    return meme_audio, chosen_filename


def synthesize_soundtrack(
    sound_events, duration_sec, meme_audio=None, output_wav="audio.wav"
):
    SAMPLE_RATE = 44100
    total_samples = int((duration_sec + 1) * SAMPLE_RATE)
    audio_data = np.zeros(total_samples, dtype=np.float32)

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

        if is_escape and meme_audio is not None:
            n_samples = min(len(meme_audio), total_samples - start_sample)
            audio_data[start_sample : start_sample + n_samples] += (
                meme_audio[:n_samples] * 0.95
            )
        else:
            freq = (
                1174.66
                if is_escape
                else FREQUENCIES[note_idx % len(FREQUENCIES)]
            )
            note_len = 0.45 if is_escape else 0.18
            n_samples = min(
                int(note_len * SAMPLE_RATE), total_samples - start_sample
            )
            t = np.linspace(0, note_len, n_samples, False)

            decay_rate = 12 if is_escape else 20
            envelope = np.exp(-decay_rate * t)

            wave_tone = (
                0.60 * np.sin(2 * np.pi * freq * t)
                + 0.25 * np.sin(2 * np.pi * (freq * 2) * t)
                + 0.15 * np.sin(2 * np.pi * (freq * 3) * t)
            )
            audio_data[start_sample : start_sample + n_samples] += (
                wave_tone * envelope
            )

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

    print(
        f"🎵 Àudio sintetitzat ({len(sound_events)} impactes, {duration_sec:.1f}s)."
    )


def run():
    start_local_server()
    meme_audio, meme_name = load_random_meme_sound()

    with sync_playwright() as p:
        print("Iniciant Firefox en mode headless...")
        browser = p.firefox.launch(headless=True)

        context = browser.new_context(
            viewport={"width": 1080, "height": 1920},
            accept_downloads=True,
        )

        page = context.new_page()

        sim_url = f"http://localhost:{PORT}/simulator.html"
        print("Carregant simulador i resolent pre-simulació...")
        page.goto(sim_url, wait_until="load")
        page.wait_for_timeout(1000)

        # Llegir configuració generada
        col1 = page.evaluate("window.color1Name || 'PILOTA 1'")
        col2 = page.evaluate("window.color2Name || 'PILOTA 2'")
        rings_cnt = page.evaluate("window.ringCount || 4")
        print(f"🎮 Duel generat: {col1} vs {col2} amb {rings_cnt} anells!")

        raw_video = "raw_simulation.webm"

        # Timeout de 120 segons per permetre partides de fins a 1.5 minuts sense talls
        with page.expect_download(timeout=120000) as download_info:
            print("Iniciant duel i gravació...")
            page.evaluate("window.startRecording()")

        sound_events = page.evaluate("window.soundEvents || []")
        actual_duration = page.evaluate("window.actualDuration || 15")
        winner_name = page.evaluate("window.winnerName || 'DESCONEGUT'")

        download = download_info.value
        download.save_as(raw_video)
        print(
            f"Duel completat! Guanyador: {winner_name} en {actual_duration:.1f}s."
        )
        browser.close()

    audio_file = "simulation_audio.wav"
    synthesize_soundtrack(sound_events, actual_duration, meme_audio, audio_file)

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

    for tmp in [raw_video, audio_file]:
        if os.path.exists(tmp):
            os.remove(tmp)

    # Enviar a Telegram amb tots els detalls
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID and os.path.exists(final_mp4):
        print("Enviant el vídeo per Telegram...")
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
        meme_caption = f"\n🔊 So mem: {meme_name}" if meme_name else ""
        caption_text = (
            f"🎬 Duel: {col1} vs {col2} ({rings_cnt} anells)!\n"
            f"🏆 Guanyador: {winner_name}!\n"
            f"⏱️ Durada: {actual_duration:.1f}s{meme_caption}\n"
            f"Canal: @bouncelab.tv 🔥"
        )

        with open(final_mp4, "rb") as f:
            res = requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption_text,
                    "supports_streaming": True,
                },
                files={"video": f},
                timeout=240,
            )
            if res.status_code == 200:
                print("🎉 VÍDEO ENVIAT AMB ÈXIT A TELEGRAM!")
            else:
                print(f"Error Telegram: {res.text}")


if __name__ == "__main__":
    run()

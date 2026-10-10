import asyncio
import http.server
import json
import os
import random
import socketserver
import subprocess
import threading
import wave
import edge_tts
import numpy as np
from playwright.sync_api import sync_playwright
import requests

# ==============================================================================
# ⚙️ PANELL DE CONTROL PRINCIPAL
# ==============================================================================
MODE_PROVA = True

# Mode a provar
SELECTED_MODE = "battle"
# ==============================================================================

# Llista de 15 frases simples i directes
HOOK_PHRASES = [
    "Which ball will last longer?",
    "Which color will win?",
    "Which ball will survive?",
    "Who will be the last one standing?",
    "Pick a color right now!",
    "Guess which ball wins!",
    "Which color is going to lose first?",
    "Which ball will be eliminated first?",
    "Can you guess the winner?",
    "Which color will make it to the end?",
    "Pick your ball before it starts!",
    "Which one is going to survive?",
    "Who is winning this battle?",
    "Which color are you betting on?",
    "Who is going to lose?",
]

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


# Generador de veu en off amb volum màxim
async def _async_generate_voice(text, output_mp3):
    communicate = edge_tts.Communicate(
        text, voice="en-US-ChristopherNeural", rate="+8%", volume="+30%"
    )
    await communicate.save(output_mp3)


def generate_tts_intro():
    chosen_phrase = random.choice(HOOK_PHRASES)
    print(f"🎙️ Generant veu Edge-TTS a màxim volum: \"{chosen_phrase}\"")

    temp_mp3 = "temp_tts.mp3"
    temp_wav = "temp_tts.wav"

    asyncio.run(_async_generate_voice(chosen_phrase, temp_mp3))

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            temp_mp3,
            "-ar",
            "44100",
            "-ac",
            "1",
            temp_wav,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    tts_audio = None
    if os.path.exists(temp_wav):
        with wave.open(temp_wav, "rb") as wf:
            n_frames = wf.getnframes()
            data = wf.readframes(n_frames)
            tts_audio = (
                np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            )

        # Normalització prèvia de la veu al 100%
        max_v = np.max(np.abs(tts_audio))
        if max_v > 0:
            tts_audio = tts_audio / max_v

        os.remove(temp_wav)

    if os.path.exists(temp_mp3):
        os.remove(temp_mp3)

    return tts_audio, chosen_phrase


def load_random_meme_sound():
    valid_exts = (".mp3", ".wav", ".ogg", ".m4a")
    if not os.path.exists(ASSETS_AUDIO_DIR):
        os.makedirs(ASSETS_AUDIO_DIR, exist_ok=True)
        return None, None

    audio_files = [
        f for f in os.listdir(ASSETS_AUDIO_DIR) if f.lower().endswith(valid_exts)
    ]

    if not audio_files:
        print("ℹ️ Carpeta assets/audio buida: s'usarà el so per defecte.")
        return None, None

    chosen_filename = random.choice(audio_files)
    chosen_path = os.path.join(ASSETS_AUDIO_DIR, chosen_filename)
    print(f"🎲 Mem triat per a cada mort en aquest vídeo: {chosen_filename}")

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
        meme_audio = (
            np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        )

    if os.path.exists(temp_wav):
        os.remove(temp_wav)

    return meme_audio, chosen_filename


def synthesize_soundtrack(
    sound_events,
    duration_sec,
    meme_audio=None,
    tts_audio=None,
    output_wav="audio.wav",
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

    # Finestra temporal de la veu (Ducking)
    tts_start_sample = int(0.20 * SAMPLE_RATE)
    tts_end_sample = 0

    if tts_audio is not None and len(tts_audio) > 0:
        n_tts = min(len(tts_audio), total_samples - tts_start_sample)
        tts_end_sample = tts_start_sample + n_tts + int(0.35 * SAMPLE_RATE)
        audio_data[tts_start_sample : tts_start_sample + n_tts] += (
            tts_audio[:n_tts] * 2.5
        )

    # Inserció de notes i mems
    for ev in sound_events:
        t_sec = ev.get("time", 0)
        note_idx = ev.get("note", 0)
        is_escape = ev.get("isEscape", False)

        start_sample = int(t_sec * SAMPLE_RATE)
        if start_sample >= total_samples:
            continue

        # Ducking: s'atenua un 75% mentre la veu parla
        is_during_tts = tts_start_sample <= start_sample <= tts_end_sample
        duck_factor = 0.25 if is_during_tts else 1.0

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
            note_len = 0.45 if is_escape else 0.16
            n_samples = min(
                int(note_len * SAMPLE_RATE), total_samples - start_sample
            )
            t = np.linspace(0, note_len, n_samples, False)

            decay_rate = 14 if is_escape else 22
            envelope = np.exp(-decay_rate * t)

            wave_tone = (
                0.60 * np.sin(2 * np.pi * freq * t)
                + 0.25 * np.sin(2 * np.pi * (freq * 2) * t)
                + 0.15 * np.sin(2 * np.pi * (freq * 3) * t)
            )
            audio_data[start_sample : start_sample + n_samples] += (
                wave_tone * envelope * duck_factor
            )

    max_amp = np.max(np.abs(audio_data))
    if max_amp > 0:
        audio_int16 = (audio_data / max_amp * 31500).astype(np.int16)
    else:
        audio_int16 = (audio_data * 31500).astype(np.int16)

    with wave.open(output_wav, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_int16.tobytes())

    print(
        f"🎵 Àudio sintetitzat ({len(sound_events)} impactes + veu forta, {duration_sec:.1f}s)."
    )


def run():
    start_local_server()
    meme_audio, meme_name = load_random_meme_sound()
    tts_audio, tts_phrase = generate_tts_intro()

    active_mode = SELECTED_MODE
    print(f"🧪 [MODE PROVA: {active_mode.upper()}]")

    if os.path.exists(os.path.join("simulators", f"{active_mode}.html")):
        sim_url = f"http://localhost:{PORT}/simulators/{active_mode}.html"
    elif os.path.exists(f"{active_mode}.html"):
        sim_url = f"http://localhost:{PORT}/{active_mode}.html"
    else:
        sim_url = f"http://localhost:{PORT}/simulator.html"

    with sync_playwright() as p:
        print("Iniciant Firefox en mode headless...")
        browser = p.firefox.launch(headless=True)

        context = browser.new_context(
            viewport={"width": 1080, "height": 1920},
            accept_downloads=True,
        )

        page = context.new_page()

        print(f"Carregant simulador ({sim_url})...")
        page.goto(sim_url, wait_until="load")
        page.wait_for_timeout(1000)

        total_fighters = page.evaluate("window.ringCount || 5")
        print(f"⚔️ Batalla iniciada amb {total_fighters} boles!")

        raw_video = "raw_simulation.webm"

        with page.expect_download(timeout=120000) as download_info:
            print(
                "Iniciant enregistrament de la batalla (garantida > 20s)..."
            )
            page.evaluate("window.startRecording()")

        sound_events = page.evaluate("window.soundEvents || []")
        actual_duration = page.evaluate("window.actualDuration || 25")
        winner_name = page.evaluate("window.winnerName || 'DESCONEGUT'")

        download = download_info.value
        download.save_as(raw_video)
        print(
            f"Batalla acabada! Guanyador: {winner_name} en {actual_duration:.1f}s."
        )
        browser.close()

    audio_file = "simulation_audio.wav"
    synthesize_soundtrack(
        sound_events, actual_duration, meme_audio, tts_audio, audio_file
    )

    final_mp4 = "bouncelab_video.mp4"
    print("Empaquetant MP4 a 30 FPS amb compressió CRF 26...")
    # 30 FPS + CRF 26 = MÀXIMA QUALITAT AMB PES < 20 MB (NO MÉS ERROR 413)
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
            "-r",
            "30",
            "-vsync",
            "cfr",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "26",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            final_mp4,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    file_size_mb = os.path.getsize(final_mp4) / (1024 * 1024)
    print(f"📦 Mida final del vídeo: {file_size_mb:.2f} MB (límit Telegram: 50 MB)")

    for tmp in [raw_video, audio_file]:
        if os.path.exists(tmp):
            os.remove(tmp)

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID and os.path.exists(final_mp4):
        print("Enviant el vídeo per Telegram...")
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
        meme_caption = f"\n🔊 So mem: {meme_name}" if meme_name else ""
        caption_text = (
            f"⚔️ [STRING BATTLE ROYALE]\n"
            f"🎙️ Hook: \"{tts_phrase}\"\n"
            f"🔥 {total_fighters} boles enfrontades!\n"
            f"🏆 Guanyador: {winner_name}!\n"
            f"⏱️ Durada: {actual_duration:.1f}s{meme_caption}\n"
            f"📦 Pes: {file_size_mb:.1f} MB\n"
            f"Canal: @bouncelab.tv 🚀"
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
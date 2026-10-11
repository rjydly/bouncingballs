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
SELECTED_MODE = "multiply"
# ==============================================================================

HOOK_PHRASES = [
    "Watch how many balls we can get!",
    "One ball escapes, three more spawn!",
    "Watch the circle fill up completely!",
    "It multiplies non-stop!",
    "Can the circle contain 500 balls?",
    "Watch 1 ball turn into hundreds!",
    "Watch the balls multiply out of control!",
    "Bet how many balls will fit inside!",
]

PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ASSETS_AUDIO_DIR = os.path.join(BASE_DIR, "assets", "audio")


class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)


def start_local_server():
    httpd = socketserver.TCPServer(("", PORT), CustomHTTPRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()
    print(f"Servidor web local actiu a http://localhost:{PORT} (servint des de {BASE_DIR})")


async def _async_generate_voice(text, output_mp3):
    communicate = edge_tts.Communicate(
        text, voice="en-US-ChristopherNeural", rate="+10%", volume="+30%"
    )
    await communicate.save(output_mp3)


def generate_tts_intro():
    chosen_phrase = random.choice(HOOK_PHRASES)
    print(f"🎙️ Generant veu Edge-TTS: \"{chosen_phrase}\"")

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
        return None, None

    chosen_filename = random.choice(audio_files)
    chosen_path = os.path.join(ASSETS_AUDIO_DIR, chosen_filename)

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
    total_samples = int((duration_sec + 1.5) * SAMPLE_RATE)
    audio_data = np.zeros(total_samples, dtype=np.float32)

    # Inserció de la veu inicial amb ducking
    tts_start_sample = int(0.15 * SAMPLE_RATE)
    tts_end_sample = 0
    if tts_audio is not None and len(tts_audio) > 0:
        n_tts = min(len(tts_audio), total_samples - tts_start_sample)
        tts_end_sample = tts_start_sample + n_tts + int(0.20 * SAMPLE_RATE)
        audio_data[tts_start_sample : tts_start_sample + n_tts] += (
            tts_audio[:n_tts] * 1.5
        )

    FREQUENCIES = [329.63, 392.00, 440.00, 493.88, 587.33, 659.25, 783.99]

    for ev in sound_events:
        t_sec = ev.get("time", 0)
        ev_type = ev.get("type", "bounce")
        note_idx = ev.get("note", 0)
        is_reveal = ev.get("isEscape", False)

        start_sample = int(t_sec * SAMPLE_RATE)
        if start_sample >= total_samples:
            continue

        is_during_tts = tts_start_sample <= start_sample <= tts_end_sample
        duck = 0.45 if is_during_tts else 1.0

        if is_reveal and meme_audio is not None:
            n_samples = min(len(meme_audio), total_samples - start_sample)
            audio_data[start_sample : start_sample + n_samples] += (
                meme_audio[:n_samples] * 1.8
            )
        elif is_reveal:
            # Acord final brillant en assolir les 500 boles
            note_len = 1.6
            n_samples = min(int(note_len * SAMPLE_RATE), total_samples - start_sample)
            t = np.linspace(0, note_len, n_samples, False)
            chord = (
                0.5 * np.sin(2 * np.pi * 523.25 * t)
                + 0.4 * np.sin(2 * np.pi * 659.25 * t)
                + 0.5 * np.sin(2 * np.pi * 783.99 * t)
                + 0.4 * np.sin(2 * np.pi * 1046.50 * t)
            ) * np.exp(-2.2 * t)
            audio_data[start_sample : start_sample + n_samples] += chord * 2.2
        elif ev_type == "spawn":
            # So d'aparició de noves boles (+3)
            note_len = 0.12
            n_samples = min(int(note_len * SAMPLE_RATE), total_samples - start_sample)
            t = np.linspace(0, note_len, n_samples, False)
            spawn_tone = (
                0.6 * np.sin(2 * np.pi * 987.77 * t)
                + 0.4 * np.sin(2 * np.pi * 1318.51 * t)
            ) * np.exp(-22 * t)
            audio_data[start_sample : start_sample + n_samples] += spawn_tone * 1.6
        else:
            # Rebot harmònic curt
            freq = FREQUENCIES[note_idx % len(FREQUENCIES)]
            note_len = 0.06
            n_samples = min(int(note_len * SAMPLE_RATE), total_samples - start_sample)
            t = np.linspace(0, note_len, n_samples, False)
            pop = np.sin(2 * np.pi * freq * t) * np.exp(-36 * t)
            audio_data[start_sample : start_sample + n_samples] += pop * 0.8 * duck

    # Normalització global al màxim de volum
    max_amp = np.max(np.abs(audio_data))
    if max_amp > 0:
        audio_int16 = (audio_data / max_amp * 31800).astype(np.int16)
    else:
        audio_int16 = (audio_data * 31800).astype(np.int16)

    with wave.open(output_wav, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_int16.tobytes())

    print(f"🎵 Àudio sintetitzat correctament ({duration_sec:.1f}s).")


def resolve_simulation_url():
    possible_candidates = [
        os.path.join("simulators", f"{SELECTED_MODE}.html"),
        f"{SELECTED_MODE}.html",
        os.path.join("simulators", "spikes.html"),
        "spikes.html",
    ]

    for rel_path in possible_candidates:
        full_path = os.path.join(BASE_DIR, rel_path)
        if os.path.exists(full_path):
            web_path = rel_path.replace("\\", "/")
            print(f"📄 Fitxer HTML trobat: {web_path}")
            return f"http://localhost:{PORT}/{web_path}"

    all_files = os.listdir(BASE_DIR)
    raise FileNotFoundError(
        f"❌ No s'ha trobat {SELECTED_MODE}.html a {BASE_DIR}. Fitxers: {all_files}"
    )


def run():
    start_local_server()
    meme_audio, meme_name = load_random_meme_sound()
    tts_audio, tts_phrase = generate_tts_intro()

    sim_url = resolve_simulation_url()

    with sync_playwright() as p:
        print("Iniciant Firefox en mode headless...")
        browser = p.firefox.launch(headless=True)

        context = browser.new_context(
            viewport={"width": 1080, "height": 1920},
            accept_downloads=True,
        )

        page = context.new_page()

        page.on("pageerror", lambda err: print(f"❌ ERROR JS AL NAVEGADOR: {err}"))
        page.on("console", lambda msg: print(f"🖥️ CONSOLE [{msg.type}]: {msg.text}"))

        cache_buster = random.randint(100000, 999999)
        final_sim_url = f"{sim_url}?cb={cache_buster}"

        print(f"Carregant simulador ({final_sim_url})...")
        response = page.goto(final_sim_url, wait_until="load")
        if response and response.status >= 400:
            raise RuntimeError(f"Error HTTP {response.status} en carregar {final_sim_url}!")

        try:
            page.wait_for_function("typeof window.startRecording === 'function'", timeout=6000)
            print("✅ Funció window.startRecording trobada i llesta!")
        except Exception:
            title = page.title()
            body_preview = page.evaluate("document.body ? document.body.innerHTML.slice(0, 300) : 'BUIT'")
            print(f"⚠️ Títol de la pàgina: '{title}'")
            print(f"⚠️ Contingut HTML carregat: {body_preview}")
            raise RuntimeError("window.startRecording no està definida al fitxer HTML!")

        raw_video = "raw_simulation.webm"

        with page.expect_download(timeout=120000) as download_info:
            print("Enregistrant mode Multiply Swarm (fins a 500 boles)...")
            page.evaluate("window.startRecording()")

        sound_events = page.evaluate("window.soundEvents || []")
        actual_duration = page.evaluate("window.actualDuration || 28.0")
        final_balls = page.evaluate("window.finalBalls || 500")

        download = download_info.value
        download.save_as(raw_video)
        print(f"Repte completat! S'han assolit {final_balls} boles ({actual_duration:.1f}s).")
        browser.close()

    audio_file = "simulation_audio.wav"
    synthesize_soundtrack(
        sound_events, actual_duration, meme_audio, tts_audio, audio_file
    )

    final_mp4 = "bouncelab_video.mp4"
    print("Empaquetant MP4 a 30 FPS...")
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
    print(f"📦 Mida final del vídeo: {file_size_mb:.2f} MB")

    for tmp in [raw_video, audio_file]:
        if os.path.exists(tmp):
            os.remove(tmp)

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID and os.path.exists(final_mp4):
        print("Enviant el vídeo per Telegram...")
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
        caption_text = (
            f"💥 [MULTIPLY SWARM]\n"
            f"🎙️ Hook: \"{tts_phrase}\"\n"
            f"🔮 Boles aconseguides: {final_balls}\n"
            f"⏱️ Durada: {actual_duration:.1f}s\n"
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
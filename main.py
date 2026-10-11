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
# ⚙️ PANELL DE CONTROL PRINCIPAL: TRIA EL MODE AQUÍ
# ==============================================================================
# Opcions disponibles: "multiply", "spikes", "accumulation", "tracker", "classic", "battle"
SELECTED_MODE = "multiply"
# ==============================================================================

# Hooks de veu específics i adaptats a la mecànica de cada mode
MODE_HOOKS = {
    "multiply": [
        "Watch us reach 2,000 balls!",
        "One ball escapes, three more spawn!",
        "Watch the circle fill up completely!",
        "Can the circle contain 2,000 balls?",
        "Watch 1 ball turn into thousands!",
        "Look how packed the circle gets!",
        "Watch the balls multiply out of control!",
        "Wait until the circle is completely full!",
    ],
    "spikes": [
        "Touch the spike, lose the ball!",
        "Can any ball escape the spikes?",
        "How many balls will it take to escape?",
        "Watch the balls sacrifice themselves!",
        "Don't touch the spikes!",
        "Will the final ball make it out?",
        "Guess how many balls will pop!",
        "Only one ball can make it through!",
    ],
    "accumulation": [
        "Can the ball escape before freezing?",
        "Will any ball manage to escape?",
        "How many balls will freeze before one escapes?",
        "Guess how many balls will freeze!",
        "Watch the arena fill up with frozen balls!",
        "Can the final ball make it out?",
        "Bet how many balls it takes to escape!",
        "Which ball will break through?",
    ],
    "tracker": [
        "Don't lose the red ball!",
        "Keep your eyes on the red ball!",
        "Can you track the red ball to the end?",
        "Don't blink or you'll lose the red ball!",
        "Focus! Which number is the red ball?",
        "Follow the red ball and guess the number!",
        "Test your focus! Track the red ball!",
    ],
    "classic": [
        "Which ball will escape first?",
        "Which color are you betting on?",
        "Pick a color right now!",
        "Which ball will break through all rings?",
        "Guess which ball wins!",
        "Who is winning this race?",
        "Can you guess the winner?",
    ],
    "battle": [
        "Which ball will survive?",
        "Which color will win?",
        "Who will be the last one standing?",
        "Pick your ball before it starts!",
        "Which color is going to lose first?",
        "Who is winning this battle?",
        "Watch until the last ball remains!",
    ],
}

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


def generate_tts_intro(mode):
    phrases = MODE_HOOKS.get(mode, MODE_HOOKS["classic"])
    chosen_phrase = random.choice(phrases)
    print(f"🎙️ Generant veu Edge-TTS per al mode [{mode.upper()}]: \"{chosen_phrase}\"")

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
    mode,
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

    # PREPARACIÓ DEL SO D'ESCAPADA PER AL MODE MULTIPLY (del teu arxiu assets/audio)
    if mode == "multiply":
        if meme_audio is not None and len(meme_audio) > 0:
            max_len = min(len(meme_audio), int(0.26 * SAMPLE_RATE))
            escape_wave = meme_audio[:max_len].copy()
            fade_len = int(max_len * 0.35)
            fade_curve = np.linspace(1.0, 0.0, fade_len)
            escape_wave[-fade_len:] *= fade_curve
        else:
            pop_len = int(0.08 * SAMPLE_RATE)
            t = np.linspace(0, 0.08, pop_len, False)
            escape_wave = (
                0.75 * np.sin(2 * np.pi * 950 * t)
                + 0.25 * np.sin(2 * np.pi * 1900 * t)
            ) * np.exp(-28 * t)
        n_esc_samples = len(escape_wave)

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

        # --- PROCESSAMENT ESPECÍFIC PER A CADA MODE ---
        if mode == "multiply":
            # Al mode multiply només sona el so quan surt una bola (sense rebots ni acords finals)
            if ev_type == "spawn":
                n_samples = min(n_esc_samples, total_samples - start_sample)
                audio_data[start_sample : start_sample + n_samples] += (
                    escape_wave[:n_samples] * 0.85
                )

        elif mode == "spikes":
            if is_reveal and meme_audio is not None:
                n_samples = min(len(meme_audio), total_samples - start_sample)
                audio_data[start_sample : start_sample + n_samples] += meme_audio[:n_samples] * 1.8
            elif is_reveal:
                note_len = 1.4
                n_samples = min(int(note_len * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, note_len, n_samples, False)
                chord = (
                    0.5 * np.sin(2 * np.pi * 523.25 * t)
                    + 0.4 * np.sin(2 * np.pi * 659.25 * t)
                    + 0.5 * np.sin(2 * np.pi * 783.99 * t)
                    + 0.4 * np.sin(2 * np.pi * 1046.50 * t)
                ) * np.exp(-3.0 * t)
                audio_data[start_sample : start_sample + n_samples] += chord * 2.0
            elif ev_type == "burst":
                # Mort de la bola contra la punxa
                note_len = 0.22
                n_samples = min(int(note_len * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, note_len, n_samples, False)
                burst = (
                    0.75 * np.sin(2 * np.pi * 160 * t)
                    + 0.45 * np.sin(2 * np.pi * 320 * t)
                    + (np.random.rand(n_samples) - 0.5) * 0.55
                ) * np.exp(-16 * t)
                audio_data[start_sample : start_sample + n_samples] += burst * 2.4
            else:
                # Rebot contra boles grises
                freq = FREQUENCIES[note_idx % len(FREQUENCIES)]
                note_len = 0.11
                n_samples = min(int(note_len * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, note_len, n_samples, False)
                pop = (
                    0.75 * np.sin(2 * np.pi * freq * t)
                    + 0.35 * np.sin(2 * np.pi * (freq * 2) * t)
                ) * np.exp(-24 * t)
                audio_data[start_sample : start_sample + n_samples] += pop * 1.7 * duck

        elif mode == "accumulation":
            if is_reveal and meme_audio is not None:
                n_samples = min(len(meme_audio), total_samples - start_sample)
                audio_data[start_sample : start_sample + n_samples] += meme_audio[:n_samples] * 1.5
            elif is_reveal:
                note_len = 1.3
                n_samples = min(int(note_len * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, note_len, n_samples, False)
                chord = (
                    0.5 * np.sin(2 * np.pi * 523.25 * t)
                    + 0.4 * np.sin(2 * np.pi * 659.25 * t)
                    + 0.5 * np.sin(2 * np.pi * 783.99 * t)
                ) * np.exp(-3.5 * t)
                audio_data[start_sample : start_sample + n_samples] += chord * 1.8
            elif ev_type == "freeze":
                # So de congelació de gel
                note_len = 0.22
                n_samples = min(int(note_len * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, note_len, n_samples, False)
                ice = (
                    np.sin(2 * np.pi * 880 * t) * 0.4
                    + np.sin(2 * np.pi * 1760 * t) * 0.3
                    + (np.random.rand(n_samples) - 0.5) * 0.25
                ) * np.exp(-12 * t)
                audio_data[start_sample : start_sample + n_samples] += ice * 0.80
            else:
                freq = FREQUENCIES[note_idx % len(FREQUENCIES)]
                note_len = 0.08
                n_samples = min(int(note_len * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, note_len, n_samples, False)
                pop = np.sin(2 * np.pi * freq * t) * np.exp(-35 * t)
                audio_data[start_sample : start_sample + n_samples] += pop * 0.6 * duck

        elif mode == "tracker":
            if is_reveal and meme_audio is not None:
                n_samples = min(len(meme_audio), total_samples - start_sample)
                audio_data[start_sample : start_sample + n_samples] += meme_audio[:n_samples] * 1.5
            elif is_reveal:
                note_len = 1.2
                n_samples = min(int(note_len * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, note_len, n_samples, False)
                chord = (
                    0.5 * np.sin(2 * np.pi * 523.25 * t)
                    + 0.5 * np.sin(2 * np.pi * 783.99 * t)
                    + 0.4 * np.sin(2 * np.pi * 1046.50 * t)
                ) * np.exp(-3.5 * t)
                audio_data[start_sample : start_sample + n_samples] += chord * 1.8
            elif ev_type == "pop":
                note_len = 0.04
                n_samples = min(int(note_len * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, note_len, n_samples, False)
                pop = np.sin(2 * np.pi * 1800 * t) * np.exp(-90 * t)
                audio_data[start_sample : start_sample + n_samples] += pop * 0.60
            else:
                note_len = 0.05
                n_samples = min(int(note_len * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, note_len, n_samples, False)
                click = np.sin(2 * np.pi * 1100 * t) * np.exp(-65 * t)
                audio_data[start_sample : start_sample + n_samples] += click * 0.50 * duck

        else:
            # Modes Classic i Battle
            freq = FREQUENCIES[note_idx % len(FREQUENCIES)]
            note_len = 0.12
            n_samples = min(int(note_len * SAMPLE_RATE), total_samples - start_sample)
            t = np.linspace(0, note_len, n_samples, False)
            pop = np.sin(2 * np.pi * freq * t) * np.exp(-25 * t)
            audio_data[start_sample : start_sample + n_samples] += pop * 0.8 * duck

    # Limitador suau (tanh) per evitar distorsió digital
    audio_data = np.tanh(audio_data * 1.05)

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

    print(f"🎵 Àudio sintetitzat correctament ({len(sound_events)} esdeveniments, {duration_sec:.1f}s).")


def resolve_simulation_url(mode):
    possible_candidates = [
        os.path.join("simulators", f"{mode}.html"),
        f"{mode}.html",
    ]

    for rel_path in possible_candidates:
        full_path = os.path.join(BASE_DIR, rel_path)
        if os.path.exists(full_path):
            web_path = rel_path.replace("\\", "/")
            print(f"📄 Fitxer HTML trobat: {web_path}")
            return f"http://localhost:{PORT}/{web_path}"

    all_files = os.listdir(BASE_DIR)
    raise FileNotFoundError(
        f"❌ No s'ha trobat {mode}.html a {BASE_DIR} ni a simulators/. Fitxers existents: {all_files}"
    )


def run():
    active_mode = SELECTED_MODE.lower().strip()
    print(f"🚀 INICIANT RENDERITZAT DEL MODE: [{active_mode.upper()}]")

    start_local_server()
    meme_audio, meme_name = load_random_meme_sound()
    tts_audio, tts_phrase = generate_tts_intro(active_mode)

    sim_url = resolve_simulation_url(active_mode)

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
            print(f"Enregistrant simulació del mode {active_mode}...")
            page.evaluate("window.startRecording()")

        sound_events = page.evaluate("window.soundEvents || []")
        actual_duration = page.evaluate("window.actualDuration || 28.0")
        winner_name = page.evaluate("window.winnerName || ''")
        frozen_count = page.evaluate("window.frozenCount || 0")
        final_balls = page.evaluate("window.finalBalls || 0")

        download = download_info.value
        download.save_as(raw_video)
        print(f"Simulació acabada! Durada: {actual_duration:.1f}s.")
        browser.close()

    audio_file = "simulation_audio.wav"
    synthesize_soundtrack(
        sound_events,
        actual_duration,
        active_mode,
        meme_audio,
        tts_audio,
        audio_file,
    )

    final_mp4 = "bouncelab_video.mp4"
    print("Empaquetant MP4 a 30 FPS amb H.264...")
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

        # Caption personalitzat segons el mode
        if active_mode == "multiply":
            title_badge = "💥 [MULTIPLY SWARM]"
            details = f"🔮 Boles aconseguides: {final_balls}"
        elif active_mode == "spikes":
            title_badge = "⚡ [TOUCH THE SPIKE LOSE THE BALL]"
            details = f"💀 Boles sacrificades: {frozen_count}\n🏆 Bola que ha escapat: #{winner_name}"
        elif active_mode == "accumulation":
            title_badge = "🧊 [ACCUMULATION MODE]"
            details = f"❄️ Boles congelades: {frozen_count}\n🏆 Bola que ha escapat: #{winner_name}"
        elif active_mode == "tracker":
            title_badge = "🎯 [DON'T LOSE THE RED BALL]"
            details = f"🏆 Bola correcta: #{winner_name}"
        elif active_mode == "classic":
            title_badge = "🌀 [NEON RINGS ESCAPE]"
            details = f"🏆 Guanyador: {winner_name}"
        elif active_mode == "battle":
            title_badge = "⚔️ [STRING BATTLE ROYALE]"
            details = f"🏆 Guanyador: {winner_name}"
        else:
            title_badge = f"🎮 [{active_mode.upper()}]"
            details = f"🏆 Resultat: {winner_name}"

        meme_note = f"\n🔊 Àudio utilitzat: {meme_name}" if meme_name else ""
        caption_text = (
            f"{title_badge}\n"
            f"🎙️ Hook: \"{tts_phrase}\"\n"
            f"{details}\n"
            f"⏱️ Durada: {actual_duration:.1f}s{meme_note}\n"
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

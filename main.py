import asyncio
import http.server
import json
import os
import random
import socketserver
import subprocess
import threading
import time
import uuid
import wave
from datetime import date, datetime, timezone

import edge_tts
import numpy as np
from playwright.sync_api import sync_playwright
import requests

# ==============================================================================
# ⚙️ CONFIGURACIÓ DE MODES I ROTACIÓ (SENSE BATTLE)
# ==============================================================================
ALLOWED_MODES = ["multiply", "spikes", "accumulation", "tracker", "classic"]

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
}

PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEOS_DIR = os.path.join(BASE_DIR, "videos")
ASSETS_AUDIO_DIR = os.path.join(BASE_DIR, "assets", "audio")

# Secrets d'entorn
GITHUB_REPO = os.environ.get("GITHUB_REPO")
ZERNIO_API_KEY = os.environ.get("ZERNIO_API_KEY")
ZERNIO_IG_ID = os.environ.get("ZERNIO_INSTAGRAM_ACCOUNT_ID")
ZERNIO_FB_ID = os.environ.get("ZERNIO_FACEBOOK_ACCOUNT_ID")
BUFFER_TOKEN = os.environ.get("BUFFER_ACCESS_TOKEN")
BUFFER_TIKTOK_ID = os.environ.get("BUFFER_TIKTOK_CHANNEL_ID")
BUFFER_YOUTUBE_ID = os.environ.get("BUFFER_YOUTUBE_CHANNEL_ID")
BUNDLE_KEY = os.environ.get("BUNDLE_SOCIAL_API_KEY")
BUNDLE_TEAM_ID = os.environ.get("BUNDLE_SOCIAL_TEAM_ID")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
FORCE_SNAPCHAT = os.environ.get("FORCE_SNAPCHAT", "false").lower() == "true"


def get_current_slot_and_mode():
    """Calcula el torn del dia (0: 14h, 1: 19h, 2: 23h UTC) i el mode rotatiu."""
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour

    if hour < 16:
        slot = 0  # 14:00 UTC (10 AM EDT)
    elif hour < 21:
        slot = 1  # 19:00 UTC (3 PM EDT)
    else:
        slot = 2  # 23:00 UTC (7 PM EDT)

    # Dies des de data base
    day_number = (now_utc.date() - date(2026, 1, 1)).days
    mode_index = (day_number * 3 + slot) % len(ALLOWED_MODES)

    env_mode = os.environ.get("SELECTED_MODE", "auto").strip().lower()
    if env_mode in ALLOWED_MODES:
        active_mode = env_mode
    else:
        active_mode = ALLOWED_MODES[mode_index]

    # Snapchat cada 1,5 dies (cicle de 3 dies = 2 publicacions cada 3 dies = 20 al mes)
    cycle_day = day_number % 3
    should_snapchat = FORCE_SNAPCHAT or (
        (cycle_day == 0 and slot == 0) or (cycle_day == 1 and slot == 2)
    )

    return active_mode, slot, should_snapchat


# ==============================================================================
# 📝 GENERADOR DE DESCRIPCIONS I TÍTOLS VARIABLES (AMB #bouncingballs)
# ==============================================================================
def generate_captions(mode, tts_phrase, duration, winner_name, frozen_count, final_balls):
    intros = [
        "You won't believe how this ends! 😱",
        "Wait for the last second... 👀",
        "This is pure satisfaction right here 🤤",
        "The physics engine went completely crazy! ⚡",
        "Did anyone expect this outcome?! 🤯",
        "Watch closely or you'll miss it! 🔍",
        "Most satisfying moment of the day ✨",
        "Can your brain process this physics puzzle? 🧠",
        "The ending is 100% unexpected 🚀",
        "Tell me you didn't blink! 😳",
    ]

    ctas = [
        "Drop your guess in the comments! 👇",
        "Rate this satisfaction from 1 to 10! ⭐",
        "Which color should we try next? Let me know!",
        "Tag a friend who loves satisfying physics! 💬",
        "Subscribe & follow for daily kinetic simulations! 🔔",
        "Did you get it right? Comment below! 🎯",
    ]

    extra_hashtags = [
        "#satisfying", "#physics", "#asmr", "#oddlysatisfying",
        "#simulation", "#gaming", "#satisfyingvideo", "#neon",
        "#viral", "#fyp", "#trending"
    ]

    chosen_intro = random.choice(intros)
    chosen_cta = random.choice(ctas)
    picked_tags = " ".join(random.sample(extra_hashtags, 4))
    tag_string = f"#bouncingballs {picked_tags}"

    if mode == "multiply":
        title = f"1 Ball Spawns {final_balls} Balls! 💥"
        body = (
            f"{chosen_intro}\n\n"
            f"🎙️ \"{tts_phrase}\"\n"
            f"We started with just 1 single ball and reached {final_balls} balls filling the entire arena in {duration:.1f}s!\n\n"
            f"{chosen_cta}\n\n{tag_string}"
        )
    elif mode == "spikes":
        title = f"Escaping After {frozen_count} Sacrifices! ⚡"
        body = (
            f"{chosen_intro}\n\n"
            f"🎙️ \"{tts_phrase}\"\n"
            f"Every ball that touched a spike was instantly popped, creating shields until Ball #{winner_name} made it out!\n\n"
            f"{chosen_cta}\n\n{tag_string}"
        )
    elif mode == "accumulation":
        title = f"Can The Ball Escape Before Freezing? 🧊"
        body = (
            f"{chosen_intro}\n\n"
            f"🎙️ \"{tts_phrase}\"\n"
            f"After {frozen_count} balls froze solid in place, Ball #{winner_name} finally broke free through the gap!\n\n"
            f"{chosen_cta}\n\n{tag_string}"
        )
    elif mode == "tracker":
        title = f"Did You Keep Your Eye on the Red Ball? 🎯"
        body = (
            f"{chosen_intro}\n\n"
            f"🎙️ \"{tts_phrase}\"\n"
            f"15 balls shuffled at maximum speed. Did you correctly spot that the red ball landed on slot #{winner_name}?\n\n"
            f"{chosen_cta}\n\n{tag_string}"
        )
    else:  # classic
        title = f"Which Color Escapes First? 🌀"
        body = (
            f"{chosen_intro}\n\n"
            f"🎙️ \"{tts_phrase}\"\n"
            f"Massive race through multiple spinning neon rings! Winner of the duel: {winner_name}!\n\n"
            f"{chosen_cta}\n\n{tag_string}"
        )

    # Versió curta per a Snapchat Spotlight (màxim 160 caràcters)
    snapchat_desc = f"{title} {chosen_intro} #bouncingballs #asmr"[:158]

    # Versió per a YouTube Short (màxim 100 caràcters)
    youtube_title = f"{title} #Shorts #bouncingballs"[:98]

    return {
        "title": title,
        "youtube_title": youtube_title,
        "full_caption": body,
        "snapchat_desc": snapchat_desc
    }


# ==============================================================================
# 🌐 SERVIDOR WEB I SÍNTESI
# ==============================================================================
class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)


def start_local_server():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("", PORT), CustomHTTPRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()
    print(f"Servidor web local actiu a http://localhost:{PORT}")


async def _async_generate_voice(text, output_mp3):
    communicate = edge_tts.Communicate(
        text, voice="en-US-ChristopherNeural", rate="+10%", volume="+30%"
    )
    await communicate.save(output_mp3)


def generate_tts_intro(mode):
    phrases = MODE_HOOKS.get(mode, MODE_HOOKS["classic"])
    chosen_phrase = random.choice(phrases)
    print(f"🎙️ Edge-TTS [{mode.upper()}]: \"{chosen_phrase}\"")

    temp_mp3 = "temp_tts.mp3"
    temp_wav = "temp_tts.wav"

    asyncio.run(_async_generate_voice(chosen_phrase, temp_mp3))

    subprocess.run(
        ["ffmpeg", "-y", "-i", temp_mp3, "-ar", "44100", "-ac", "1", temp_wav],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    tts_audio = None
    if os.path.exists(temp_wav):
        with wave.open(temp_wav, "rb") as wf:
            data = wf.readframes(wf.getnframes())
            tts_audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

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

    audio_files = [f for f in os.listdir(ASSETS_AUDIO_DIR) if f.lower().endswith(valid_exts)]
    if not audio_files:
        return None, None

    chosen_filename = random.choice(audio_files)
    chosen_path = os.path.join(ASSETS_AUDIO_DIR, chosen_filename)
    temp_wav = "temp_meme.wav"

    subprocess.run(
        ["ffmpeg", "-y", "-i", chosen_path, "-ar", "44100", "-ac", "1", temp_wav],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    if not os.path.exists(temp_wav):
        return None, None

    with wave.open(temp_wav, "rb") as wf:
        data = wf.readframes(wf.getnframes())
        meme_audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

    if os.path.exists(temp_wav):
        os.remove(temp_wav)

    return meme_audio, chosen_filename


def synthesize_soundtrack(sound_events, duration_sec, mode, meme_audio=None, tts_audio=None, output_wav="audio.wav"):
    SAMPLE_RATE = 44100
    total_samples = int((duration_sec + 1.5) * SAMPLE_RATE)
    audio_data = np.zeros(total_samples, dtype=np.float32)

    tts_start_sample = int(0.15 * SAMPLE_RATE)
    tts_end_sample = 0
    if tts_audio is not None and len(tts_audio) > 0:
        n_tts = min(len(tts_audio), total_samples - tts_start_sample)
        tts_end_sample = tts_start_sample + n_tts + int(0.20 * SAMPLE_RATE)
        audio_data[tts_start_sample : tts_start_sample + n_tts] += tts_audio[:n_tts] * 1.5

    FREQUENCIES = [329.63, 392.00, 440.00, 493.88, 587.33, 659.25, 783.99]

    if mode == "multiply":
        if meme_audio is not None and len(meme_audio) > 0:
            max_len = min(len(meme_audio), int(0.26 * SAMPLE_RATE))
            escape_wave = meme_audio[:max_len].copy()
            fade_len = int(max_len * 0.35)
            escape_wave[-fade_len:] *= np.linspace(1.0, 0.0, fade_len)
        else:
            pop_len = int(0.08 * SAMPLE_RATE)
            t = np.linspace(0, 0.08, pop_len, False)
            escape_wave = (0.75 * np.sin(2 * np.pi * 950 * t) + 0.25 * np.sin(2 * np.pi * 1900 * t)) * np.exp(-28 * t)
        n_esc_samples = len(escape_wave)

    for ev in sound_events:
        t_sec = ev.get("time", 0)
        ev_type = ev.get("type", "bounce")
        note_idx = ev.get("note", 0)
        is_reveal = ev.get("isEscape", False)

        start_sample = int(t_sec * SAMPLE_RATE)
        if start_sample >= total_samples:
            continue

        duck = 0.45 if tts_start_sample <= start_sample <= tts_end_sample else 1.0

        if mode == "multiply":
            if ev_type == "spawn":
                n_samples = min(n_esc_samples, total_samples - start_sample)
                audio_data[start_sample : start_sample + n_samples] += escape_wave[:n_samples] * 0.85
        elif mode == "spikes":
            if is_reveal and meme_audio is not None:
                n_samples = min(len(meme_audio), total_samples - start_sample)
                audio_data[start_sample : start_sample + n_samples] += meme_audio[:n_samples] * 1.8
            elif is_reveal:
                n_samples = min(int(1.4 * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, 1.4, n_samples, False)
                chord = (0.5 * np.sin(2 * np.pi * 523.25 * t) + 0.5 * np.sin(2 * np.pi * 783.99 * t)) * np.exp(-3.0 * t)
                audio_data[start_sample : start_sample + n_samples] += chord * 2.0
            elif ev_type == "burst":
                n_samples = min(int(0.22 * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, 0.22, n_samples, False)
                burst = (0.75 * np.sin(2 * np.pi * 160 * t) + (np.random.rand(n_samples) - 0.5) * 0.55) * np.exp(-16 * t)
                audio_data[start_sample : start_sample + n_samples] += burst * 2.4
            else:
                freq = FREQUENCIES[note_idx % len(FREQUENCIES)]
                n_samples = min(int(0.11 * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, 0.11, n_samples, False)
                pop = np.sin(2 * np.pi * freq * t) * np.exp(-24 * t)
                audio_data[start_sample : start_sample + n_samples] += pop * 1.7 * duck
        elif mode == "accumulation":
            if is_reveal and meme_audio is not None:
                n_samples = min(len(meme_audio), total_samples - start_sample)
                audio_data[start_sample : start_sample + n_samples] += meme_audio[:n_samples] * 1.5
            elif is_reveal:
                n_samples = min(int(1.3 * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, 1.3, n_samples, False)
                chord = (0.5 * np.sin(2 * np.pi * 523.25 * t) + 0.5 * np.sin(2 * np.pi * 783.99 * t)) * np.exp(-3.5 * t)
                audio_data[start_sample : start_sample + n_samples] += chord * 1.8
            elif ev_type == "freeze":
                n_samples = min(int(0.22 * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, 0.22, n_samples, False)
                ice = (np.sin(2 * np.pi * 880 * t) * 0.4 + (np.random.rand(n_samples) - 0.5) * 0.25) * np.exp(-12 * t)
                audio_data[start_sample : start_sample + n_samples] += ice * 0.80
            else:
                freq = FREQUENCIES[note_idx % len(FREQUENCIES)]
                n_samples = min(int(0.08 * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, 0.08, n_samples, False)
                pop = np.sin(2 * np.pi * freq * t) * np.exp(-35 * t)
                audio_data[start_sample : start_sample + n_samples] += pop * 0.6 * duck
        elif mode == "tracker":
            if is_reveal and meme_audio is not None:
                n_samples = min(len(meme_audio), total_samples - start_sample)
                audio_data[start_sample : start_sample + n_samples] += meme_audio[:n_samples] * 1.5
            elif is_reveal:
                n_samples = min(int(1.2 * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, 1.2, n_samples, False)
                chord = (0.5 * np.sin(2 * np.pi * 523.25 * t) + 0.4 * np.sin(2 * np.pi * 1046.5 * t)) * np.exp(-3.5 * t)
                audio_data[start_sample : start_sample + n_samples] += chord * 1.8
            elif ev_type == "pop":
                n_samples = min(int(0.04 * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, 0.04, n_samples, False)
                pop = np.sin(2 * np.pi * 1800 * t) * np.exp(-90 * t)
                audio_data[start_sample : start_sample + n_samples] += pop * 0.60
            else:
                n_samples = min(int(0.05 * SAMPLE_RATE), total_samples - start_sample)
                t = np.linspace(0, 0.05, n_samples, False)
                click = np.sin(2 * np.pi * 1100 * t) * np.exp(-65 * t)
                audio_data[start_sample : start_sample + n_samples] += click * 0.50 * duck
        else:
            freq = FREQUENCIES[note_idx % len(FREQUENCIES)]
            n_samples = min(int(0.12 * SAMPLE_RATE), total_samples - start_sample)
            t = np.linspace(0, 0.12, n_samples, False)
            pop = np.sin(2 * np.pi * freq * t) * np.exp(-25 * t)
            audio_data[start_sample : start_sample + n_samples] += pop * 0.8 * duck

    audio_data = np.tanh(audio_data * 1.05)
    max_amp = np.max(np.abs(audio_data))
    audio_int16 = (audio_data / max_amp * 31800).astype(np.int16) if max_amp > 0 else (audio_data * 31800).astype(np.int16)

    with wave.open(output_wav, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_int16.tobytes())


def resolve_simulation_url(mode):
    candidates = [os.path.join("simulators", f"{mode}.html"), f"{mode}.html"]
    for rel in candidates:
        full = os.path.join(BASE_DIR, rel)
        if os.path.exists(full):
            return f"http://localhost:{PORT}/{rel.replace(chr(92), '/')}"
    raise FileNotFoundError(f"No s'ha trobat {mode}.html!")


# ==============================================================================
# 🚀 PUBLISHERS (ZERNIO, BUFFER, BUNDLE.SOCIAL, TELEGRAM)
# ==============================================================================
def publish_to_zernio(video_url, captions):
    if not (ZERNIO_API_KEY and ZERNIO_IG_ID and ZERNIO_FB_ID):
        print("⚠️ Zernio: Falten credencials. Saltant Instagram i Facebook.")
        return

    url = "https://zernio.com/api/v1/posts"
    headers = {
        "Authorization": f"Bearer {ZERNIO_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "content": captions["full_caption"],
        "mediaItems": [{"type": "video", "url": video_url}],
        "platforms": [
            {
                "platform": "instagram",
                "accountId": ZERNIO_IG_ID,
                "platformSpecificData": {
                    "shareToFeed": True
                }
            },
            {
                "platform": "facebook",
                "accountId": ZERNIO_FB_ID,
                "platformSpecificData": {
                    "contentType": "reel",
                    "title": captions["title"]
                }
            }
        ],
        "publishNow": True
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=60)
        if res.status_code in [200, 201]:
            print("✅ Instagram & Facebook: Publicats amb èxit via Zernio!")
        else:
            print(f"❌ Error Zernio ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ Excepció Zernio: {e}")


def publish_to_buffer(video_url, captions):
    if not BUFFER_TOKEN:
        print("⚠️ Buffer: Falta BUFFER_ACCESS_TOKEN. Saltant TikTok i YouTube.")
        return

    endpoint = "https://api.buffer.com"
    headers = {
        "Authorization": f"Bearer {BUFFER_TOKEN}",
        "Content-Type": "application/json"
    }

    query = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess {
          post { id status }
        }
        ... on MutationError {
          message
        }
      }
    }
    """

    # 1. TikTok
    if BUFFER_TIKTOK_ID:
        tiktok_payload = {
            "query": query,
            "variables": {
                "input": {
                    "channelId": BUFFER_TIKTOK_ID,
                    "text": captions["full_caption"],
                    "mode": "shareNow",
                    "schedulingType": "automatic",
                    "assets": [{
                        "video": {
                            "url": video_url,
                            "metadata": {"title": captions["title"]}
                        }
                    }],
                    "metadata": {
                        "tiktok": {"isAiGenerated": False}
                    }
                }
            }
        }
        try:
            res = requests.post(endpoint, json=tiktok_payload, headers=headers, timeout=60)
            print(f"✅ Buffer TikTok Response: {res.json()}")
        except Exception as e:
            print(f"❌ Error TikTok Buffer: {e}")

    # 2. YouTube Shorts
    if BUFFER_YOUTUBE_ID:
        youtube_payload = {
            "query": query,
            "variables": {
                "input": {
                    "channelId": BUFFER_YOUTUBE_ID,
                    "text": captions["full_caption"],
                    "mode": "shareNow",
                    "schedulingType": "automatic",
                    "assets": [{
                        "video": {
                            "url": video_url,
                            "metadata": {"title": captions["youtube_title"]}
                        }
                    }],
                    "metadata": {
                        "youtube": {
                            "title": captions["youtube_title"],
                            "categoryId": "24",
                            "privacy": "public",
                            "madeForKids": False,
                            "embeddable": True
                        }
                    }
                }
            }
        }
        try:
            res = requests.post(endpoint, json=youtube_payload, headers=headers, timeout=60)
            print(f"✅ Buffer YouTube Shorts Response: {res.json()}")
        except Exception as e:
            print(f"❌ Error YouTube Buffer: {e}")


def publish_to_snapchat(video_path, captions):
    if not (BUNDLE_KEY and BUNDLE_TEAM_ID):
        print("⚠️ bundle.social: Falten credencials. Saltant Snapchat.")
        return

    print("👻 Pujant Spotlight a Snapchat via bundle.social...")
    upload_url = "https://api.bundle.social/api/v1/upload"
    headers_upload = {"x-api-key": BUNDLE_KEY}

    upload_id = None
    try:
        filename = os.path.basename(video_path)
        with open(video_path, "rb") as f:
            files = {"file": (filename, f, "video/mp4")}
            data = {"teamId": BUNDLE_TEAM_ID}
            up_res = requests.post(upload_url, headers=headers_upload, files=files, data=data, timeout=120)
            if up_res.status_code in [200, 201]:
                res_json = up_res.json()
                upload_id = res_json.get("uploadId") or res_json.get("id")
            else:
                print(f"❌ Error Upload bundle.social ({up_res.status_code}): {up_res.text}")
                return
    except Exception as e:
        print(f"❌ Excepció pujant vídeo a bundle.social: {e}")
        return

    if not upload_id:
        print("❌ No s'ha rebut uploadId de bundle.social.")
        return

    post_url = "https://api.bundle.social/api/v1/post"
    headers_post = {
        "x-api-key": BUNDLE_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "teamId": BUNDLE_TEAM_ID,
        "title": captions["title"][:40],
        "status": "SCHEDULED",
        "postDate": datetime.now(timezone.utc).isoformat(),
        "socialAccountTypes": ["SNAPCHAT"],
        "data": {
            "SNAPCHAT": {
                "type": "SPOTLIGHT",
                "uploadIds": [upload_id],
                "description": captions["snapchat_desc"],
                "locale": "en_US",
                "skipSaveToProfile": False
            }
        }
    }
    try:
        p_res = requests.post(post_url, headers=headers_post, json=payload, timeout=60)
        if p_res.status_code in [200, 201]:
            print("🎉 Snapchat Spotlight: Creat i publicat amb èxit!")
        else:
            print(f"❌ Error Post bundle.social ({p_res.status_code}): {p_res.text}")
    except Exception as e:
        print(f"❌ Excepció creant post a bundle.social: {e}")


def send_telegram_backup(video_path, captions, mode, duration, posted_snapchat):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return

    snap_status = "✅ PUSHED" if posted_snapchat else "⏸️ SKIPPED (Cicle 1.5d)"
    caption = (
        f"🚀 <b>BOUNCELAB AUTOMATION</b>\n\n"
        f"Mode: <b>{mode.upper()}</b>\n"
        f"Durada: {duration:.1f}s\n"
        f"Snapchat Spotlight: {snap_status}\n\n"
        f"📝 <b>Text publicat:</b>\n{captions['full_caption']}"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    try:
        with open(video_path, "rb") as f:
            requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption[:1024],
                    "parse_mode": "HTML",
                    "supports_streaming": True,
                },
                files={"video": f},
                timeout=180
            )
        print("📲 Notificació enviada a Telegram!")
    except Exception as e:
        print(f"⚠️ Error Telegram: {e}")


# ==============================================================================
# 🎯 PIPELINE PRINCIPAL
# ==============================================================================
def run():
    active_mode, slot, should_snapchat = get_current_slot_and_mode()
    print("=" * 60)
    print(f"🎬 EXECUTANT TORN #{slot} | MODE: [{active_mode.upper()}]")
    print(f"👻 SNAPCHAT SPOTLIGHT AVUI?: {'SÍ (Publicant)' if should_snapchat else 'NO (Descans cicle 1.5 dies)'}")
    print("=" * 60)

    os.makedirs(VIDEOS_DIR, exist_ok=True)

    # 1. Netejar carpeta videos/ per evitar acumular arxius locals
    for f in os.listdir(VIDEOS_DIR):
        if f.endswith(".mp4"):
            try:
                os.remove(os.path.join(VIDEOS_DIR, f))
            except Exception:
                pass

    start_local_server()
    meme_audio, _ = load_random_meme_sound()
    tts_audio, tts_phrase = generate_tts_intro(active_mode)
    sim_url = resolve_simulation_url(active_mode)

    raw_video = "raw_simulation.webm"

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        context = browser.new_context(viewport={"width": 1080, "height": 1920}, accept_downloads=True)
        page = context.new_page()

        final_url = f"{sim_url}?cb={random.randint(100000, 999999)}"
        page.goto(final_url, wait_until="load")
        page.wait_for_function("typeof window.startRecording === 'function'", timeout=8000)

        with page.expect_download(timeout=120000) as download_info:
            print(f"Enregistrant mode {active_mode}...")
            page.evaluate("window.startRecording()")

        sound_events = page.evaluate("window.soundEvents || []")
        actual_duration = page.evaluate("window.actualDuration || 25.0")
        winner_name = str(page.evaluate("window.winnerName || ''"))
        frozen_count = int(page.evaluate("window.frozenCount || 0"))
        final_balls = int(page.evaluate("window.finalBalls || 0"))

        download = download_info.value
        download.save_as(raw_video)
        browser.close()

    # 2. Sintetitzar àudio procedimental
    audio_file = "simulation_audio.wav"
    synthesize_soundtrack(sound_events, actual_duration, active_mode, meme_audio, tts_audio, audio_file)

    # 3. Generar MP4 final amb ID únic per evitar problemes de memòria cau
    video_id = uuid.uuid4().hex[:8]
    final_video_filename = f"bouncelab_{active_mode}_{video_id}.mp4"
    final_mp4 = os.path.join(VIDEOS_DIR, final_video_filename)

    print("Empaquetant MP4 H.264 vertical a 30 FPS...")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", raw_video, "-i", audio_file,
            "-c:v", "libx264", "-preset", "fast", "-r", "30", "-vsync", "cfr",
            "-pix_fmt", "yuv420p", "-crf", "26", "-c:a", "aac", "-b:a", "128k",
            "-shortest", final_mp4,
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    for tmp in [raw_video, audio_file]:
        if os.path.exists(tmp):
            os.remove(tmp)

    # 4. Generar descripcions úniques i variables
    captions = generate_captions(
        active_mode, tts_phrase, actual_duration, winner_name, frozen_count, final_balls
    )

    # 5. Git push a la branca òrfena 'cdn' (Mantingut el repositori net per sempre)
    public_video_url = None
    if GITHUB_REPO:
        try:
            print("📤 Fent Git push a la branca 'cdn' (Sense inflar l'historial)...")
            
            # Assegurar que no hi ha branques temporals prèvies
            subprocess.run(["git", "branch", "-D", "cdn_temp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Crear branca òrfena cdn_temp (comença buida, sense arrossegar commits vells)
            subprocess.run(["git", "checkout", "--orphan", "cdn_temp"], check=True)
            subprocess.run(["git", "reset"], check=True)
            
            # Afegir únicament el nou vídeo MP4
            rel_mp4_path = os.path.relpath(final_mp4, BASE_DIR)
            subprocess.run(["git", "add", "-f", rel_mp4_path], check=True)
            subprocess.run(["git", "commit", "-m", f"CDN Video {video_id} [skip ci]"], check=True)
            
            # Push forçat a la branca remota cdn
            subprocess.run(["git", "push", "-f", "origin", "cdn_temp:cdn"], check=True)
            
            # Retornar netament a main i eliminar la branca temporal
            subprocess.run(["git", "checkout", "-f", "main"], check=True)
            subprocess.run(["git", "branch", "-D", "cdn_temp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # URL pública directa de la branca 'cdn'
            public_video_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/cdn/videos/{final_video_filename}"
            print(f"🔗 URL Pública generada: {public_video_url}")
            print("Esperant 8 segons per a la propagació de la CDN de GitHub...")
            time.sleep(8)
        except Exception as e:
            print(f"⚠️ Avís Git: No s'ha pogut fer push a la branca 'cdn' ({e}).")
            subprocess.run(["git", "checkout", "-f", "main"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not public_video_url:
        public_video_url = f"https://raw.githubusercontent.com/{GITHUB_REPO or 'user/repo'}/cdn/videos/{final_video_filename}"

    # 6. Publicar a totes les xarxes socials
    # Instagram & Facebook (Zernio)
    publish_to_zernio(public_video_url, captions)

    # TikTok & YouTube (Buffer)
    publish_to_buffer(public_video_url, captions)

    # Snapchat Spotlight (bundle.social - Només cada 1,5 dies per mantenir els 20/mes)
    if should_snapchat:
        publish_to_snapchat(final_mp4, captions)
    else:
        print("⏸️ Snapchat: Torn descansat per complir la quota de 20 posts mensuals (1 post cada 1,5 dies).")

    # Telegram Backup
    send_telegram_backup(final_mp4, captions, active_mode, actual_duration, should_snapchat)

    print("🏁 Procés completat amb èxit!")


if __name__ == "__main__":
    run()
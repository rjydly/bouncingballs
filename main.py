import math
import os
import random
import subprocess
import wave
import cv2
import numpy as np
import requests

# ==========================================
# 1. CONFIGURACIÓ (TikTok 1080x1920 @ 60 FPS)
# ==========================================
WIDTH, HEIGHT = 1080, 1920
FPS = 60
DURATION_SEC = 18
TOTAL_FRAMES = FPS * DURATION_SEC
CENTER = (WIDTH // 2, HEIGHT // 2)

GRAVITY = 0.35
BOUNCE_ENERGY = 1.01
BALL_RADIUS = 22
BALL_COLOR = (255, 255, 255)

RINGS_COUNT = 5
BASE_RADIUS = 180
RING_SPACING = 75

rings = []
for i in range(RINGS_COUNT):
    r = BASE_RADIUS + i * RING_SPACING
    speed = random.choice([-1, 1]) * random.uniform(0.015, 0.035)
    gap_size = math.radians(45)
    gap_angle = random.uniform(0, 2 * math.pi)
    hue = int((i / RINGS_COUNT) * 180)
    rings.append(
        {
            "radius": r,
            "gap_angle": gap_angle,
            "speed": speed,
            "gap_size": gap_size,
            "hue": hue,
            "alive": True,
        }
    )

ball_x, ball_y = CENTER[0], CENTER[1] - 50
ball_vx, ball_vy = random.uniform(-6, 6), random.uniform(-4, 4)

trail = []
particles = []
bounce_events = []

# ==========================================
# 2. GENERAR FOTOGRAMES DE VÍDEO
# ==========================================
fourcc = cv2.VideoWriter_fourcc(*"mp4v")
video_out = cv2.VideoWriter("temp_video.mp4", fourcc, FPS, (WIDTH, HEIGHT))

for frame_idx in range(TOTAL_FRAMES):
    current_time = frame_idx / FPS
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

    for ring in rings:
        if ring["alive"]:
            ring["gap_angle"] = (ring["gap_angle"] + ring["speed"]) % (
                2 * math.pi
            )

    ball_vy += GRAVITY
    ball_x += ball_vx
    ball_y += ball_vy
    trail.append((int(ball_x), int(ball_y)))
    if len(trail) > 18:
        trail.pop(0)

    dx = ball_x - CENTER[0]
    dy = ball_y - CENTER[1]
    dist = math.sqrt(dx * dx + dy * dy)
    angle_from_center = math.atan2(dy, dx) % (2 * math.pi)

    for idx, ring in enumerate(rings):
        if not ring["alive"]:
            continue

        r = ring["radius"]
        if abs(dist - r) <= BALL_RADIUS + 4:
            gap_start = (ring["gap_angle"] - ring["gap_size"] / 2) % (
                2 * math.pi
            )
            gap_end = (ring["gap_angle"] + ring["gap_size"] / 2) % (2 * math.pi)

            in_gap = (
                gap_start <= angle_from_center <= gap_end
                if gap_start < gap_end
                else (
                    angle_from_center >= gap_start
                    or angle_from_center <= gap_end
                )
            )

            if in_gap:
                ring["alive"] = False
                bounce_events.append((current_time, 880 + idx * 110))
                for _ in range(35):
                    p_ang = random.uniform(0, 2 * math.pi)
                    p_spd = random.uniform(3, 10)
                    particles.append(
                        [
                            ball_x,
                            ball_y,
                            math.cos(p_ang) * p_spd,
                            math.sin(p_ang) * p_spd,
                            25,
                            ring["hue"],
                        ]
                    )
            else:
                nx, ny = dx / dist, dy / dist
                dot = ball_vx * nx + ball_vy * ny
                ball_vx = (ball_vx - 2 * dot * nx) * BOUNCE_ENERGY
                ball_vy = (ball_vy - 2 * dot * ny) * BOUNCE_ENERGY

                overlap = (BALL_RADIUS + 4) - abs(dist - r)
                ball_x -= nx * (overlap if dist > r else -overlap)
                ball_y -= ny * (overlap if dist > r else -overlap)
                bounce_events.append((current_time, 440 + idx * 80))
            break

    # Dibuixar Anells
    for ring in rings:
        if not ring["alive"]:
            continue
        color_bgr = cv2.applyColorMap(
            np.uint8([[[ring["hue"], 255, 255]]]), cv2.COLOR_HSV2BGR
        )[0][0]
        color = (int(color_bgr[0]), int(color_bgr[1]), int(color_bgr[2]))

        start_deg = math.degrees(ring["gap_angle"] + ring["gap_size"] / 2)
        end_deg = math.degrees(ring["gap_angle"] - ring["gap_size"] / 2)
        if end_deg < start_deg:
            end_deg += 360

        cv2.ellipse(
            frame,
            CENTER,
            (ring["radius"], ring["radius"]),
            0,
            start_deg,
            end_deg,
            color,
            8,
            cv2.LINE_AA,
        )

    # Rastro
    for i, pt in enumerate(trail):
        alpha = (i + 1) / len(trail)
        cv2.circle(
            frame, pt, max(1, int(BALL_RADIUS * alpha * 0.6)), (180, 180, 255), -1
        )

    # Pilota
    cv2.circle(
        frame, (int(ball_x), int(ball_y)), BALL_RADIUS, BALL_COLOR, -1, cv2.LINE_AA
    )

    # Partícules
    for p in particles[:]:
        p[0] += p[2]
        p[1] += p[3]
        p[4] -= 1
        if p[4] <= 0:
            particles.remove(p)
        else:
            p_bgr = cv2.applyColorMap(
                np.uint8([[[p[5], 255, 255]]]), cv2.COLOR_HSV2BGR
            )[0][0]
            cv2.circle(
                frame,
                (int(p[0]), int(p[1])),
                max(1, p[4] // 4),
                (int(p_bgr[0]), int(p_bgr[1]), int(p_bgr[2])),
                -1,
            )

    # Ganxo de text
    cv2.putText(
        frame,
        "WILL IT ESCAPE?",
        (WIDTH // 2 - 240, 260),
        cv2.FONT_HERSHEY_DUPLEX,
        1.5,
        (255, 255, 255),
        3,
        cv2.LINE_AA,
    )
    video_out.write(frame)

    if not any(r["alive"] for r in rings) and (
        ball_x < 0 or ball_x > WIDTH or ball_y < 0 or ball_y > HEIGHT
    ):
        break

video_out.release()
actual_duration = (frame_idx + 1) / FPS

# ==========================================
# 3. SÍNTESI D'ÀUDIO
# ==========================================
SAMPLE_RATE = 44100
total_samples = int(actual_duration * SAMPLE_RATE)
audio_data = np.zeros(total_samples, dtype=np.float32)

for event_time, freq in bounce_events:
    start_sample = int(event_time * SAMPLE_RATE)
    if start_sample >= total_samples:
        continue
    note_duration = 0.18
    n_samples = min(int(note_duration * SAMPLE_RATE), total_samples - start_sample)
    t = np.linspace(0, note_duration, n_samples, False)
    envelope = np.exp(-14 * t)
    audio_data[start_sample : start_sample + n_samples] += (
        0.5 * np.sin(2 * np.pi * freq * t) * envelope
    )

max_val = np.max(np.abs(audio_data))
audio_int16 = (
    (audio_data / max_val * 32767).astype(np.int16)
    if max_val > 0
    else (audio_data * 32767).astype(np.int16)
)

with wave.open("temp_audio.wav", "w") as wav_file:
    wav_file.setnchannels(1)
    wav_file.setsampwidth(2)
    wav_file.setframerate(SAMPLE_RATE)
    wav_file.writeframes(audio_int16.tobytes())

# ==========================================
# 4. EXPORTAR MP4 DEFINITIU AMB FFMPEG
# ==========================================
output_filename = "daily_viral_video.mp4"
cmd = [
    "ffmpeg",
    "-y",
    "-i",
    "temp_video.mp4",
    "-i",
    "temp_audio.wav",
    "-c:v",
    "libx264",
    "-preset",
    "veryfast",
    "-pix_fmt",
    "yuv420p",
    "-crf",
    "23",
    "-c:a",
    "aac",
    "-b:a",
    "128k",
    "-shortest",
    output_filename,
]
subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

for tmp in ["temp_video.mp4", "temp_audio.wav"]:
    if os.path.exists(tmp):
        os.remove(tmp)

print(f"Vídeo generat ({output_filename}).")

# ==========================================
# 5. ENVIAR A TELEGRAM
# ==========================================
bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat_id = os.environ.get("TELEGRAM_CHAT_ID")

if bot_token and chat_id:
    print("Enviant el vídeo per Telegram...")
    url = f"https://api.telegram.org/bot{bot_token}/sendVideo"
    with open(output_filename, "rb") as video_file:
        files = {"video": video_file}
        data = {
            "chat_id": chat_id,
            "caption": "🎬 Nou vídeo de simulació generat! Mode: Clàssic 🔥",
            "supports_streaming": True,
        }
        res = requests.post(url, data=data, files=files)
        if res.status_code == 200:
            print("Enviat amb èxit a Telegram!")
        else:
            print(f"Error Telegram: {res.text}")
else:
    print("Secrets de Telegram no trobats.")

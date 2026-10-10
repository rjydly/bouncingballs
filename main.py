import http.server
import os
import socketserver
import subprocess
import threading
import time
from playwright.sync_api import sync_playwright
import requests

PORT = 8080
DURATION = 18  # Durada en segons
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# 1. Engegar servidor HTTP local per servir simulator.html
def start_local_server():
    handler = http.server.SimpleHTTPRequestHandler
    httpd = socketserver.TCPServer(("", PORT), handler)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()
    print(f"Servidor local llest a http://localhost:{PORT}")


def run():
    start_local_server()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--autoplay-policy=no-user-gesture",
                "--use-fake-ui-for-media-stream",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1080, "height": 1920},
            accept_downloads=True,
        )
        page = context.new_page()

        print(f"Obrint simulator.html per gravar {DURATION} segons...")
        page.goto(
            f"http://localhost:{PORT}/simulator.html?duration={DURATION}"
        )
        time.sleep(1)

        # Esperem la descàrrega automàtica que farà simulator.html
        with page.expect_download(timeout=120000) as download_info:
            # Cridem la funció de gravació que hem programat a l'HTML
            page.evaluate("window.startRecording()")
            print(f"Enregistrant partida durant {DURATION}s...")
            time.sleep(DURATION + 2)

        download = download_info.value
        raw_video = "raw_simulation.webm"
        download.save_as(raw_video)
        print("Gravació WebM descarregada amb èxit!")
        browser.close()

    # 2. Convertir a MP4 (H.264 / AAC) amb FFmpeg per a màxima compatibilitat
    final_mp4 = "bouncelab_video.mp4"
    print("Convertint a MP4 d'alta definició amb FFmpeg...")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            raw_video,
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
            "128k",
            final_mp4,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if os.path.exists(raw_video):
        os.remove(raw_video)

    # 3. Enviar a Telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID and os.path.exists(final_mp4):
        print("Enviant el vídeo per Telegram...")
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
        with open(final_mp4, "rb") as f:
            res = requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": "🎬 Nou vídeo generat amb el nostre propi motor HTML5!\nCanal: @bouncelab.tv 🔥",
                    "supports_streaming": True,
                },
                files={"video": f},
                timeout=120,
            )
            if res.status_code == 200:
                print("🎉 Vídeo enviat a Telegram amb èxit!")
            else:
                print(f"Error Telegram: {res.text}")


if __name__ == "__main__":
    run()

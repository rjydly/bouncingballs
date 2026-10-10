import http.server
import os
import socketserver
import subprocess
import threading
from playwright.sync_api import sync_playwright
import requests

PORT = 8080
DURATION = 18  # Durada en segons
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def start_local_server():
    handler = http.server.SimpleHTTPRequestHandler
    httpd = socketserver.TCPServer(("", PORT), handler)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()
    print(f"Servidor local actiu a http://localhost:{PORT}")


def run():
    start_local_server()

    with sync_playwright() as p:
        # Executem el navegador complet (sota la pantalla virtual Xvfb)
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--autoplay-policy=no-user-gesture",
                "--use-fake-ui-for-media-stream",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1080, "height": 1920},
            accept_downloads=True,
        )

        page = context.new_page()

        print(f"Carregant simulator.html per gravar {DURATION} segons...")
        page.goto(
            f"http://localhost:{PORT}/simulator.html?duration={DURATION}"
        )
        page.wait_for_timeout(1500)

        raw_video = "raw_simulation.webm"

        # Esperem la descàrrega automàtica
        with page.expect_download(timeout=120000) as download_info:
            print("Iniciant gravació...")
            page.evaluate("window.startRecording()")
            # Deixem transcórrer la gravació sense bloquejar Playwright
            page.wait_for_timeout((DURATION + 3) * 1000)

        download = download_info.value
        download.save_as(raw_video)
        print("Gravació WebM completada i descarregada!")
        browser.close()

    # Convertir a MP4 H.264 d'alta qualitat
    final_mp4 = "bouncelab_video.mp4"
    print("Convertint a MP4 per a mòbils...")
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

    # Enviar a Telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID and os.path.exists(final_mp4):
        print("Enviant el vídeo per Telegram...")
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
        with open(final_mp4, "rb") as f:
            res = requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": "🎬 Nou vídeo generat amb el nostre motor HTML5!\nCanal: @bouncelab.tv 🔥",
                    "supports_streaming": True,
                },
                files={"video": f},
                timeout=120,
            )
            if res.status_code == 200:
                print("🎉 Vídeo enviat amb èxit a Telegram!")
            else:
                print(f"Error Telegram: {res.text}")


if __name__ == "__main__":
    run()

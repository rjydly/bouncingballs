import os
import math
import wave
import subprocess
import requests
import numpy as np
import bpy

# ==============================================================================
# ⚙️ CONFIGURACIÓ I VARIABLES D'ENTORN
# ==============================================================================
TEST_MODE = os.environ.get("TEST_MODE", "false").strip().lower() in ["true", "1", "yes"]
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

OUTPUT_VIDEO = "output_spiral.mp4"
TEMP_RAW_VIDEO = "temp_render.mp4"
TEMP_AUDIO = "temp_chimes.wav"

FPS = 30
TOTAL_FRAMES = 180  # 6 segons (per prova ràpida a GitHub Actions)
WIDTH = 720
HEIGHT = 1280

# ==============================================================================
# 🔔 1. SÍNTESI D'ÀUDIO PROCEDURAL (CAMPANES DE MEDITACIÓ / RELAX)
# ==============================================================================
def generate_chimes_audio(duration_sec, output_wav):
    print("🎵 Sintetitzant àudio de campanes sincronitzades...")
    SAMPLE_RATE = 44100
    n_samples = int(duration_sec * SAMPLE_RATE)
    audio = np.zeros(n_samples, dtype=np.float32)

    # Harmònics de campana de vidre/metàl·lica (Hz)
    chime_freqs = [523.25, 659.25, 783.99, 1046.50]  # Acord C major cristal·lí
    
    # Emet una campana a cada cicle de l'ona (cada 1.5s aproximadament)
    strike_times = [0.0, 1.5, 3.0, 4.5]

    for idx, t_strike in enumerate(strike_times):
        start = int(t_strike * SAMPLE_RATE)
        if start >= n_samples:
            continue
        
        dur_note = min(2.5, duration_sec - t_strike)
        n_note = int(dur_note * SAMPLE_RATE)
        t = np.linspace(0, dur_note, n_note, False)
        
        freq = chime_freqs[idx % len(chime_freqs)]
        
        # Superposició harmònica amb caiguda exponencial
        note = (
            0.60 * np.sin(2 * np.pi * freq * t) +
            0.30 * np.sin(2 * np.pi * (freq * 2.02) * t) +
            0.15 * np.sin(2 * np.pi * (freq * 3.01) * t)
        ) * np.exp(-2.2 * t)
        
        audio[start : start + n_note] += note

    audio = np.tanh(audio * 1.2)
    max_amp = np.max(np.abs(audio))
    if max_amp > 0:
        audio = audio / max_amp * 31000

    audio_int16 = audio.astype(np.int16)
    with wave.open(output_wav, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_int16.tobytes())


# ==============================================================================
# 🎨 2. MOTOR 3D PROCEDURAL (BLENDER HEADLESS)
# ==============================================================================
def render_3d_spiral():
    print("🎬 Construint escena 3D a Blender...")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    scene.render.fps = FPS
    scene.frame_start = 1
    scene.frame_end = TOTAL_FRAMES
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT

    # Cycles per CPU: Sense necessitat de pantalles X11 ni drivers gràfics
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 16
    scene.cycles.use_denoising = True

    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    scene.render.filepath = f"//{TEMP_RAW_VIDEO}"

    # Càmera
    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = (0, -11.0, 7.5)
    cam.rotation_euler = (math.radians(58), 0, 0)

    # Llum
    light_data = bpy.data.lights.new(name="TopLight", type='AREA')
    light_data.energy = 450
    light_data.size = 8.0
    light = bpy.data.objects.new("TopLight", light_data)
    light.location = (0, 0, 8.5)
    scene.collection.objects.link(light)

    # Materials
    mat_sphere = bpy.data.materials.new("SphereMat")
    mat_sphere.use_nodes = True
    bsdf = mat_sphere.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.05, 0.85, 0.45, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.85
    bsdf.inputs["Roughness"].default_value = 0.15

    mat_mirror = bpy.data.materials.new("MirrorMat")
    mat_mirror.use_nodes = True
    bsdf_m = mat_mirror.node_tree.nodes.get("Principled BSDF")
    bsdf_m.inputs["Base Color"].default_value = (0.02, 0.03, 0.03, 1.0)
    bsdf_m.inputs["Metallic"].default_value = 0.95
    bsdf_m.inputs["Roughness"].default_value = 0.05

    # Disc mirall inferior
    bpy.ops.mesh.primitive_cylinder_add(radius=4.8, depth=0.1, location=(0, 0, -2.8))
    mirror_disc = bpy.context.active_object
    mirror_disc.data.materials.append(mat_mirror)

    # Espiral de Fermat
    N_BALLS = 1200
    GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))

    base_mesh = bpy.data.meshes.new("SpiralPointsMesh")
    spiral_obj = bpy.data.objects.new("Spiral", base_mesh)
    scene.collection.objects.link(spiral_obj)

    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.075)
    proto = bpy.context.active_object
    proto.data.materials.append(mat_sphere)
    proto.parent = spiral_obj
    spiral_obj.instance_type = 'VERTS'

    radii = [math.sqrt(i) * 0.115 for i in range(N_BALLS)]
    thetas = [i * GOLDEN_ANGLE for i in range(N_BALLS)]
    max_r = max(radii)

    initial_verts = [(radii[i]*math.cos(thetas[i]), radii[i]*math.sin(thetas[i]), 0.0) for i in range(N_BALLS)]
    base_mesh.from_pydata(initial_verts, [], [])
    base_mesh.update()

    print("Rendering 3D frames...")
    for frame in range(1, TOTAL_FRAMES + 1):
        scene.frame_set(frame)
        t = (frame / TOTAL_FRAMES) * math.pi * 4.0

        verts = []
        for i in range(N_BALLS):
            r = radii[i]
            theta = thetas[i]
            u = r / max_r
            z = 1.4 * math.sin(u * math.pi * 3.0 - t) * (1.0 - u * 0.4)
            r_mod = r * (1.0 + 0.12 * math.cos(u * math.pi * 2.0 - t))
            verts.append((r_mod * math.cos(theta), r_mod * math.sin(theta), z))

        base_mesh.clear_geometry()
        base_mesh.from_pydata(verts, [], [])
        base_mesh.update()

        bpy.ops.render.render(write_still=True)


# ==============================================================================
# 📲 3. ENVIAMENT A TELEGRAM
# ==============================================================================
def send_telegram_video(video_path):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("⚠️ Telegram: Falten credencials TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID.")
        return

    print("📲 Mode de prova actiu: Enviant vídeo a Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    caption = (
        "🧪 <b>BOUNCELAB 3D PROTOTYPE (TEST MODE)</b>\n\n"
        "✨ <b>Model:</b> Espiral Àuria de Fermat amb Ones 3D\n"
        "🟢 <b>Elements:</b> 1.200 boles metàl·liques amb reflex mirall\n"
        "🔔 <b>Àudio:</b> Sincronitzat amb campanes harmòniques"
    )

    try:
        with open(video_path, "rb") as f:
            res = requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption,
                    "parse_mode": "HTML",
                    "supports_streaming": True
                },
                files={"video": f},
                timeout=180
            )
        if res.status_code == 200:
            print("✅ Vídeo de prova enviat a Telegram amb èxit!")
        else:
            print(f"❌ Error enviant a Telegram ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ Excepció Telegram: {e}")


# ==============================================================================
# 🚀 PIPELINE PRINCIPAL
# ==============================================================================
def main():
    print(f"🔧 Iniciant generador 3D | TEST_MODE: {TEST_MODE}")

    # 1. Generar vídeo 3D
    render_3d_spiral()

    # 2. Generar àudio procedimental
    duration = TOTAL_FRAMES / FPS
    generate_chimes_audio(duration, TEMP_AUDIO)

    # 3. Unir vídeo i àudio amb FFmpeg
    print("⚡ Unint àudio i vídeo final...")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", TEMP_RAW_VIDEO, "-i", TEMP_AUDIO,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", OUTPUT_VIDEO
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # Netejar fitxers temporals
    for f in [TEMP_RAW_VIDEO, TEMP_AUDIO]:
        if os.path.exists(f):
            os.remove(f)

    # 4. Decisió segons TEST_MODE
    if TEST_MODE:
        send_telegram_video(OUTPUT_VIDEO)
    else:
        print("ℹ️ TEST_MODE no està activat. El vídeo està generat a disc, però no s'ha publicat enlloc.")


if __name__ == "__main__":
    main()

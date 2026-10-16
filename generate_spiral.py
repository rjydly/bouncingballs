import os
import math
import wave
import shutil
import subprocess
import requests
import numpy as np
import bpy

# ==============================================================================
# ⚙️ CONFIGURACIÓ PRINCIPAL (EDITA AQUÍ DIRECTAMENT)
# ==============================================================================
TEST_MODE = True  # 👉 True (envia a Telegram) | False (no fa res)

OUTPUT_VIDEO = "output_spiral.mp4"
FRAMES_DIR = "temp_frames"
TEMP_AUDIO = "temp_chimes.wav"

FPS = 30
TOTAL_FRAMES = 180  # 6 segons
WIDTH = 720
HEIGHT = 1280

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# ==============================================================================
# 🔔 1. SÍNTESI D'ÀUDIO PROCEDURAL
# ==============================================================================
def generate_chimes_audio(duration_sec, output_wav):
    print("🎵 Sintetitzant àudio de campanes...")
    SAMPLE_RATE = 44100
    n_samples = int(duration_sec * SAMPLE_RATE)
    audio = np.zeros(n_samples, dtype=np.float32)

    chime_freqs = [523.25, 659.25, 783.99, 1046.50]
    strike_times = [0.0, 1.5, 3.0, 4.5]

    for idx, t_strike in enumerate(strike_times):
        start = int(t_strike * SAMPLE_RATE)
        if start >= n_samples:
            continue
        
        dur_note = min(2.5, duration_sec - t_strike)
        n_note = int(dur_note * SAMPLE_RATE)
        t = np.linspace(0, dur_note, n_note, False)
        
        freq = chime_freqs[idx % len(chime_freqs)]
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
# 🎨 2. RENDERITZAT 3D ULTRA-OPTIMITZAT
# ==============================================================================
def render_3d_spiral():
    print("🎬 Construint escena 3D a Blender...")
    
    if os.path.exists(FRAMES_DIR):
        shutil.rmtree(FRAMES_DIR)
    os.makedirs(FRAMES_DIR, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    scene.render.fps = FPS
    scene.frame_start = 1
    scene.frame_end = TOTAL_FRAMES
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT

    # Optimitzacions extremes de velocitat per a CPU
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 4           # 4 mostres + denoiser = imatge neta i vola
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 2       # En lloc de 12 (elimina el 80% del temps de càlcul)
    scene.cycles.diffuse_bounces = 1
    scene.cycles.glossy_bounces = 2
    scene.cycles.transmission_bounces = 0
    scene.cycles.transparent_max_bounces = 1
    scene.cycles.volume_bounces = 0

    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'

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

    # Materials (sense 'use_nodes' per evitar avisos de Blender 5/6)
    mat_sphere = bpy.data.materials.new("SphereMat")
    bsdf = mat_sphere.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.05, 0.85, 0.45, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.85
    bsdf.inputs["Roughness"].default_value = 0.15

    mat_mirror = bpy.data.materials.new("MirrorMat")
    bsdf_m = mat_mirror.node_tree.nodes.get("Principled BSDF")
    bsdf_m.inputs["Base Color"].default_value = (0.02, 0.03, 0.03, 1.0)
    bsdf_m.inputs["Metallic"].default_value = 0.95
    bsdf_m.inputs["Roughness"].default_value = 0.05

    # Disc mirall
    bpy.ops.mesh.primitive_cylinder_add(radius=4.8, depth=0.1, location=(0, 0, -2.8))
    mirror_disc = bpy.context.active_object
    mirror_disc.data.materials.append(mat_mirror)

    # Espiral de Fermat
    N_BALLS = 1200
    GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))

    base_mesh = bpy.data.meshes.new("SpiralPointsMesh")
    spiral_obj = bpy.data.objects.new("Spiral", base_mesh)
    scene.collection.objects.link(spiral_obj)

    # Subdivisions=1 + shade_smooth redueix els triangles un 75% mantenint aspecte esfèric
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.075)
    proto = bpy.context.active_object
    proto.data.materials.append(mat_sphere)
    proto.parent = spiral_obj
    spiral_obj.instance_type = 'VERTS'

    # Precalcular arrays de NumPy vectoritzats (0 mil·lisegons)
    indices = np.arange(N_BALLS)
    thetas = indices * GOLDEN_ANGLE
    radii = np.sqrt(indices) * 0.115
    max_r = radii[-1]
    u = radii / max_r

    # Inicialitzar la malla un sol cop a la memòria
    initial_verts = np.column_stack((radii * np.cos(thetas), radii * np.sin(thetas), np.zeros(N_BALLS)))
    base_mesh.from_pydata(initial_verts.tolist(), [], [])
    base_mesh.update()

    print("Renderitzant fotogrames a alta velocitat...")
    for frame in range(1, TOTAL_FRAMES + 1):
        scene.frame_set(frame)
        t = (frame / TOTAL_FRAMES) * math.pi * 4.0

        # Càlcul vectorial instantani amb NumPy
        z = 1.4 * np.sin(u * np.pi * 3.0 - t) * (1.0 - u * 0.4)
        r_mod = radii * (1.0 + 0.12 * np.cos(u * np.pi * 2.0 - t))
        x = r_mod * np.cos(thetas)
        y = r_mod * np.sin(thetas)

        # Actualització directa de memòria (sense reconstruir la malla ni el BVH)
        coords = np.column_stack((x, y, z)).astype(np.float32).ravel()
        base_mesh.vertices.foreach_set("co", coords)
        base_mesh.update()

        scene.render.filepath = os.path.join(FRAMES_DIR, f"frame_{frame:04d}.png")
        bpy.ops.render.render(write_still=True)

        if frame % 30 == 0:
            print(f"  -> {frame}/{TOTAL_FRAMES} fotogrames enllestits")


# ==============================================================================
# 📲 3. ENVIAMENT A TELEGRAM
# ==============================================================================
def send_telegram_video(video_path):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("⚠️ Telegram: Falten credencials TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID.")
        return

    print("📲 TEST_MODE=True: Enviant vídeo a Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    caption = (
        "🧪 <b>PROVA DE CONCEPTE 3D (BLENDER PROCEDURAL)</b>\n\n"
        "✨ <b>Efecte:</b> Espiral àuria de 1.200 boles metàl·liques amb reflex de mirall\n"
        "🔔 <b>Àudio:</b> Sincronitzat procedimentalment amb campanes"
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
            print("✅ Vídeo enviat a Telegram correctament!")
        else:
            print(f"❌ Error Telegram ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ Excepció Telegram: {e}")


# ==============================================================================
# 🚀 PUNT D'ENTRADA
# ==============================================================================
def main():
    print(f"🔧 Estat de la variable TEST_MODE: {TEST_MODE}")

    render_3d_spiral()

    duration = TOTAL_FRAMES / FPS
    generate_chimes_audio(duration, TEMP_AUDIO)

    print("⚡ Empaquetant MP4 H.264 amb FFmpeg...")
    frame_pattern = os.path.join(FRAMES_DIR, "frame_%04d.png")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", frame_pattern,
            "-i", TEMP_AUDIO,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            OUTPUT_VIDEO
        ],
        check=True
    )

    if os.path.exists(FRAMES_DIR):
        shutil.rmtree(FRAMES_DIR)
    if os.path.exists(TEMP_AUDIO):
        os.remove(TEMP_AUDIO)

    if TEST_MODE is True:
        send_telegram_video(OUTPUT_VIDEO)
    else:
        print("⏸️ TEST_MODE és False: no s'ha enviat res.")


if __name__ == "__main__":
    main()

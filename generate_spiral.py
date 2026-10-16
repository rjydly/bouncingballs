import os
import sys
import math
import wave
import shutil
import subprocess
import requests
import numpy as np

# ==============================================================================
# ⚙️ CONFIGURACIÓ PRINCIPAL (EDITA AQUÍ DIRECTAMENT)
# ==============================================================================
TEST_MODE = True  # 👉 True (envia a Telegram) | False (no fa res)

OUTPUT_VIDEO = "output_spiral.mp4"
FRAMES_DIR = "temp_frames"
ASSEMBLE_DIR = "all_frames"
TEMP_AUDIO = "temp_chimes.wav"

FPS = 30
TOTAL_FRAMES = 480  # 16 segons (480 / 15 = 32 frames per màquina)
WIDTH = 720
HEIGHT = 1280

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Geometria i dinàmica lenta
NUM_RINGS = 16
R_MIN = 0.35
R_MAX = 3.60
BALL_RADIUS = 0.065
BOUNCE_HEIGHT = 1.45
BOUNCE_FREQ = 0.65  # Baixat a 0.65 per un moviment pausat i flotant (1 bot cada ~1.54s)

# ==============================================================================
# 📐 CÀLCUL MATEMÀTIC DEL MOVIMENT LENT (PLA -> ONA)
# ==============================================================================
def get_ring_height(ring_idx, t):
    """
    Moviment suau i lent:
    - 0s a 4.0s: Totalment pla (2 bots complets sincronitzats a l'uníson).
    - 4.0s a 12.0s: L'ona es desplega molt lentament i suau del centre enfora.
    - 12.0s a 16.0s: Ona ondulant completa a velocitat lenta.
    """
    u = ring_idx / (NUM_RINGS - 1)  # 0.0 (centre) a 1.0 (vora exterior)
    
    if t < 4.0:
        wave_dispersion = 0.0
    else:
        # Transició de dispersió molt progressiva al llarg de 7 segons
        progress = min(1.0, (t - 4.0) / 7.0)
        # Funció d'acceleració suau (smoothstep)
        progress_eased = progress * progress * (3.0 - 2.0 * progress)
        wave_dispersion = progress_eased * math.pi * 1.6

    phase = 2.0 * math.pi * BOUNCE_FREQ * t - (u * wave_dispersion)
    
    # Gravetat suau rectificada (tocant el terra a z=0)
    z = BOUNCE_HEIGHT * (abs(math.sin(phase)) ** 1.30)
    return z


# ==============================================================================
# 🔔 1. SÍNTESI D'ÀUDIO PER IMPACTES AMB RESSONÀNCIA PROFUNDA
# ==============================================================================
def generate_chimes_audio(duration_sec, output_wav):
    print("🎵 Calculant impactes lents i sintetitzant campanes amb eco profund...")
    SAMPLE_RATE = 44100
    n_samples = int(duration_sec * SAMPLE_RATE)
    audio = np.zeros(n_samples, dtype=np.float32)

    # Escala pentatònica de C major
    NOTES_SCALE = [
        130.81, 146.83, 164.81, 196.00, 220.00,  # C3 - A3
        261.63, 293.66, 329.63, 392.00, 440.00,  # C4 - A4
        523.25, 587.33, 659.25, 783.99, 880.00,  # C5 - A5
        1046.50                                   # C6
    ]

    DT_AUDIO_SCAN = 1.0 / 600.0
    scan_steps = int(duration_sec / DT_AUDIO_SCAN)
    
    for ring_idx in range(NUM_RINGS):
        freq = NOTES_SCALE[(NUM_RINGS - 1) - ring_idx]
        prev_z = get_ring_height(ring_idx, 0.0)
        prev_vel = 0.0

        for step in range(1, scan_steps):
            t_curr = step * DT_AUDIO_SCAN
            z_curr = get_ring_height(ring_idx, t_curr)
            vel = z_curr - prev_z

            # Xoc contra el terra
            if prev_vel <= 0.0 and vel > 0.0 and z_curr < 0.08:
                hit_sample = int(t_curr * SAMPLE_RATE)
                if hit_sample < n_samples:
                    # Ressonància més llarga (2.6 segons per campana gràcies al ritme lent)
                    note_len = min(int(2.6 * SAMPLE_RATE), n_samples - hit_sample)
                    t_note = np.linspace(0, note_len / SAMPLE_RATE, note_len, False)
                    
                    # Campana harmònica amb caiguda suau
                    sound_wave = (
                        0.60 * np.sin(2 * np.pi * freq * t_note) +
                        0.30 * np.sin(2 * np.pi * (freq * 2.01) * t_note) +
                        0.10 * np.sin(2 * np.pi * (freq * 3.00) * t_note)
                    ) * np.exp(-2.0 * t_note)
                    
                    audio[hit_sample : hit_sample + note_len] += sound_wave * 0.42

            prev_z = z_curr
            prev_vel = vel

    # Compressió suau
    audio = np.tanh(audio * 1.35)
    max_amp = np.max(np.abs(audio))
    if max_amp > 0:
        audio = (audio / max_amp) * 31500

    audio_int16 = audio.astype(np.int16)
    with wave.open(output_wav, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_int16.tobytes())


# ==============================================================================
# 🎨 2. RENDERITZAT 3D DE CADA CHUNK (BLENDER)
# ==============================================================================
def render_chunk():
    import bpy

    chunk_idx = int(os.environ.get("CHUNK_INDEX", 0))
    total_chunks = int(os.environ.get("TOTAL_CHUNKS", 1))

    frames_per_chunk = math.ceil(TOTAL_FRAMES / total_chunks)
    start_frame = chunk_idx * frames_per_chunk + 1
    end_frame = min(TOTAL_FRAMES, (chunk_idx + 1) * frames_per_chunk)

    print(f"🎬 Runner #{chunk_idx}: fotogrames {start_frame} a {end_frame} ({end_frame - start_frame + 1} frames)...")
    os.makedirs(FRAMES_DIR, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    scene.render.fps = FPS
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT

    # Optimitzacions Cycles CPU
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 4
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 2
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
    cam.location = (0, -10.2, 7.8)
    cam.rotation_euler = (math.radians(54), 0, 0)

    # Llums
    light_data = bpy.data.lights.new(name="MainLight", type='AREA')
    light_data.energy = 500
    light_data.size = 9.0
    light = bpy.data.objects.new("MainLight", light_data)
    light.location = (0, -1.0, 9.0)
    scene.collection.objects.link(light)

    # Materials
    mat_sphere = bpy.data.materials.new("SphereMat")
    bsdf_s = mat_sphere.node_tree.nodes.get("Principled BSDF")
    bsdf_s.inputs["Base Color"].default_value = (0.05, 0.90, 0.45, 1.0)
    bsdf_s.inputs["Metallic"].default_value = 0.85
    bsdf_s.inputs["Roughness"].default_value = 0.12

    mat_floor = bpy.data.materials.new("FloorMat")
    bsdf_f = mat_floor.node_tree.nodes.get("Principled BSDF")
    bsdf_f.inputs["Base Color"].default_value = (0.08, 0.10, 0.12, 1.0)
    bsdf_f.inputs["Metallic"].default_value = 0.30
    bsdf_f.inputs["Roughness"].default_value = 0.35

    # Pedestal / Terra rígid visible
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=64,
        radius=R_MAX + 0.45,
        depth=0.5,
        location=(0, 0, -BALL_RADIUS - 0.25)
    )
    floor_obj = bpy.context.active_object
    floor_obj.data.materials.append(mat_floor)

    bpy.ops.mesh.primitive_torus_add(
        major_radius=R_MAX + 0.45,
        minor_radius=0.04,
        major_segments=64,
        minor_segments=12,
        location=(0, 0, -BALL_RADIUS)
    )
    ring_border = bpy.context.active_object
    ring_border.data.materials.append(mat_sphere)

    # Anells concèntrics
    ring_radii = np.linspace(R_MIN, R_MAX, NUM_RINGS)
    all_x = []
    all_y = []
    ball_ring_indices = []

    for idx, r in enumerate(ring_radii):
        num_balls = max(6, int(round((2.0 * math.pi * r) / (BALL_RADIUS * 2.3))))
        angles = np.linspace(0, 2.0 * math.pi, num_balls, endpoint=False)
        for a in angles:
            all_x.append(r * math.cos(a))
            all_y.append(r * math.sin(a))
            ball_ring_indices.append(idx)

    total_balls = len(all_x)
    ball_ring_indices = np.array(ball_ring_indices, dtype=np.int32)
    all_x = np.array(all_x, dtype=np.float32)
    all_y = np.array(all_y, dtype=np.float32)

    base_mesh = bpy.data.meshes.new("ConcentricBallsMesh")
    spiral_obj = bpy.data.objects.new("ConcentricSystem", base_mesh)
    scene.collection.objects.link(spiral_obj)

    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=BALL_RADIUS)
    proto = bpy.context.active_object
    proto.data.materials.append(mat_sphere)
    proto.parent = spiral_obj
    spiral_obj.instance_type = 'VERTS'

    initial_verts = np.column_stack((all_x, all_y, np.zeros(total_balls, dtype=np.float32)))
    base_mesh.from_pydata(initial_verts.tolist(), [], [])
    base_mesh.update()

    # Bucle del chunk
    for frame in range(start_frame, end_frame + 1):
        scene.frame_set(frame)
        t = (frame - 1) / FPS

        ring_z_values = np.array([get_ring_height(i, t) for i in range(NUM_RINGS)], dtype=np.float32)
        balls_z = ring_z_values[ball_ring_indices]

        coords = np.column_stack((all_x, all_y, balls_z)).astype(np.float32).ravel()
        base_mesh.vertices.foreach_set("co", coords)
        base_mesh.update()

        scene.render.filepath = os.path.join(FRAMES_DIR, f"frame_{frame:04d}.png")
        bpy.ops.render.render(write_still=True)
        if frame % 10 == 0 or frame == end_frame:
            print(f"  [Chunk {chunk_idx}] Frame {frame}/{TOTAL_FRAMES} OK.")


# ==============================================================================
# 📲 3. ENVIAMENT A TELEGRAM
# ==============================================================================
def send_telegram_video(video_path):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("⚠️ Falten secrets de Telegram.")
        return

    print("📲 TEST_MODE=True: Enviant vídeo a Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    caption = (
        "✨ <b>BOUNCELAB 3D - MOVIMENT LENT I FLOTANT (16s)</b>\n\n"
        "🧘 <b>Ritme:</b> Animació pausada (0.65 Hz) amb transició suau de pla a ona\n"
        "🔘 <b>Terra:</b> Pedestal rígid integrat a z=0\n"
        "🔔 <b>Àudio:</b> Campanes harmòniques amb ressonància profunda a cada xoc de fila"
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
            print("✅ Vídeo enviat a Telegram amb èxit!")
        else:
            print(f"❌ Error Telegram ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ Excepció Telegram: {e}")


# ==============================================================================
# 🎬 4. ACOBLAMENT FINAL (FFMPEG)
# ==============================================================================
def assemble_final_video():
    print("⚡ Unint els 480 fotogrames descarregats...")
    duration = TOTAL_FRAMES / FPS
    generate_chimes_audio(duration, TEMP_AUDIO)

    frame_pattern = os.path.join(ASSEMBLE_DIR, "frame_%04d.png")
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

    if os.path.exists(TEMP_AUDIO):
        os.remove(TEMP_AUDIO)

    if TEST_MODE is True:
        send_telegram_video(OUTPUT_VIDEO)
    else:
        print("⏸️ TEST_MODE és False: Vídeo generat a disc sense enviar.")


# ==============================================================================
# 🚀 PUNT D'ENTRADA
# ==============================================================================
if __name__ == "__main__":
    if "--assemble" in sys.argv:
        assemble_final_video()
    else:
        render_chunk()
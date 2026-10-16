import os
import sys
import math
import wave
import shutil
import colorsys
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
TOTAL_FRAMES = 480  # 16 segons (480 / 15 màquines = 32 frames per màquina)
WIDTH = 720
HEIGHT = 1280

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Geometria i dinàmica física real
NUM_RINGS = 16
R_MIN = 0.30
R_MAX = 3.25
BALL_RADIUS = 0.062
BOUNCE_HEIGHT = 1.45

# Durada del 1r bot (1.7 segons = bot lent i elegant)
T_FIRST_BOUNCE = 1.70

# ==============================================================================
# 🎨 PALETA DE COLORS ALEATORIS DETERMINISTA
# ==============================================================================
COLOR_SEED = 2026
rng = np.random.RandomState(COLOR_SEED)
random_hues = rng.rand(40)
COLOR_PALETTE = []
for h in random_hues:
    r, g, b = colorsys.hsv_to_rgb(h, 0.88, 0.95)
    COLOR_PALETTE.append((r, g, b, 1.0))


def get_ring_color(ring_idx, phase):
    cycle = max(0.0, phase / math.pi)
    idx0 = int(cycle) % len(COLOR_PALETTE)
    idx1 = (idx0 + 1) % len(COLOR_PALETTE)
    frac = cycle - int(cycle)
    
    frac_eased = frac * frac * (3.0 - 2.0 * frac)
    c0 = COLOR_PALETTE[idx0]
    c1 = COLOR_PALETTE[idx1]
    
    r = (1.0 - frac_eased) * c0[0] + frac_eased * c1[0]
    g = (1.0 - frac_eased) * c0[1] + frac_eased * c1[1]
    b = (1.0 - frac_eased) * c0[2] + frac_eased * c1[2]
    return (r, g, b, 1.0)


# ==============================================================================
# 📐 FÍSICA REAL: EL CENTRE SIMPLEMENT BOTA MÉS RÀPID A PARTIR DEL 2n BOT
# ==============================================================================
def get_ring_phase_and_height(ring_idx, t):
    u = ring_idx / (NUM_RINGS - 1)  # 0.0 (centre) a 1.0 (vora exterior)
    
    if t <= T_FIRST_BOUNCE:
        # 1r BOT: Totes les boles són 100% idèntiques en altura i velocitat
        phase = (math.pi / T_FIRST_BOUNCE) * t
    else:
        # A PARTIR DEL 2n BOT: El centre és un 14% més ràpid de forma natural
        # Simplement completa el cicle abans i baixa cap al terra més ràpid!
        speed_factor = 1.0 + 0.14 * (1.0 - u)
        tau = t - T_FIRST_BOUNCE
        phase = math.pi + (math.pi / T_FIRST_BOUNCE) * tau * speed_factor

    # Trajectòria de bot suau i natural sense deformacions estranyes
    z = BOUNCE_HEIGHT * (abs(math.sin(phase)) ** 1.30)
    return phase, z


# ==============================================================================
# 🔔 1. SÍNTESI D'ÀUDIO SINCRONITZAT AMB ELS XOCS
# ==============================================================================
def generate_chimes_audio(duration_sec, output_wav):
    print("🎵 Sintetitzant àudio sincronitzat amb els impactes...")
    SAMPLE_RATE = 44100
    n_samples = int(duration_sec * SAMPLE_RATE)
    audio = np.zeros(n_samples, dtype=np.float32)

    NOTES_SCALE = [
        130.81, 146.83, 164.81, 196.00, 220.00,
        261.63, 293.66, 329.63, 392.00, 440.00,
        523.25, 587.33, 659.25, 783.99, 880.00,
        1046.50
    ]

    DT_AUDIO_SCAN = 1.0 / 600.0
    scan_steps = int(duration_sec / DT_AUDIO_SCAN)
    
    for ring_idx in range(NUM_RINGS):
        freq = NOTES_SCALE[(NUM_RINGS - 1) - ring_idx]
        _, prev_z = get_ring_phase_and_height(ring_idx, 0.0)
        prev_vel = 0.0

        for step in range(1, scan_steps):
            t_curr = step * DT_AUDIO_SCAN
            _, z_curr = get_ring_phase_and_height(ring_idx, t_curr)
            vel = z_curr - prev_z

            if prev_vel <= 0.0 and vel > 0.0 and z_curr < 0.08:
                hit_sample = int(t_curr * SAMPLE_RATE)
                if hit_sample < n_samples:
                    note_len = min(int(2.4 * SAMPLE_RATE), n_samples - hit_sample)
                    t_note = np.linspace(0, note_len / SAMPLE_RATE, note_len, False)
                    
                    sound_wave = (
                        0.60 * np.sin(2 * np.pi * freq * t_note) +
                        0.30 * np.sin(2 * np.pi * (freq * 2.01) * t_note) +
                        0.10 * np.sin(2 * np.pi * (freq * 3.00) * t_note)
                    ) * np.exp(-2.2 * t_note)
                    
                    audio[hit_sample : hit_sample + note_len] += sound_wave * 0.42

            prev_z = z_curr
            prev_vel = vel

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

    print(f"🎬 Runner #{chunk_idx}: processant fotogrames {start_frame} a {end_frame}...")
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

    # CÀMERA MÉS LLUNY: Marge ampli i net al voltant de tot el pedestal
    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = (0, -18.5, 14.0)
    cam.rotation_euler = (math.radians(52.5), 0, 0)

    # Llums
    light_data = bpy.data.lights.new(name="MainLight", type='AREA')
    light_data.energy = 700
    light_data.size = 13.0
    light = bpy.data.objects.new("MainLight", light_data)
    light.location = (0, -1.0, 14.0)
    scene.collection.objects.link(light)

    # Materials del terra
    mat_floor = bpy.data.materials.new("FloorMat")
    bsdf_f = mat_floor.node_tree.nodes.get("Principled BSDF")
    bsdf_f.inputs["Base Color"].default_value = (0.07, 0.08, 0.10, 1.0)
    bsdf_f.inputs["Metallic"].default_value = 0.35
    bsdf_f.inputs["Roughness"].default_value = 0.30

    mat_border = bpy.data.materials.new("BorderMat")
    bsdf_b = mat_border.node_tree.nodes.get("Principled BSDF")
    bsdf_b.inputs["Base Color"].default_value = (0.15, 0.90, 0.60, 1.0)
    bsdf_b.inputs["Metallic"].default_value = 0.90
    bsdf_b.inputs["Roughness"].default_value = 0.15

    # Pedestal / Terra rígid visible
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=64,
        radius=R_MAX + 0.35,
        depth=0.5,
        location=(0, 0, -BALL_RADIUS - 0.25)
    )
    floor_obj = bpy.context.active_object
    floor_obj.data.materials.append(mat_floor)

    bpy.ops.mesh.primitive_torus_add(
        major_radius=R_MAX + 0.35,
        minor_radius=0.035,
        major_segments=64,
        minor_segments=12,
        location=(0, 0, -BALL_RADIUS)
    )
    ring_border = bpy.context.active_object
    ring_border.data.materials.append(mat_border)

    # Sistemes d'anells
    ring_radii = np.linspace(R_MIN, R_MAX, NUM_RINGS)
    ring_systems = []

    for ring_i, r in enumerate(ring_radii):
        mat_ring = bpy.data.materials.new(f"Mat_Ring_{ring_i}")
        bsdf_r = mat_ring.node_tree.nodes.get("Principled BSDF")
        bsdf_r.inputs["Metallic"].default_value = 0.85
        bsdf_r.inputs["Roughness"].default_value = 0.12

        num_balls = max(6, int(round((2.0 * math.pi * r) / (BALL_RADIUS * 2.3))))
        angles = np.linspace(0, 2.0 * math.pi, num_balls, endpoint=False)
        rx = r * np.cos(angles)
        ry = r * np.sin(angles)

        ring_mesh = bpy.data.meshes.new(f"Mesh_Ring_{ring_i}")
        ring_obj = bpy.data.objects.new(f"Obj_Ring_{ring_i}", ring_mesh)
        scene.collection.objects.link(ring_obj)

        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=BALL_RADIUS)
        proto = bpy.context.active_object
        proto.data.materials.append(mat_ring)
        proto.parent = ring_obj
        ring_obj.instance_type = 'VERTS'

        init_verts = np.column_stack((rx, ry, np.zeros(num_balls, dtype=np.float32)))
        ring_mesh.from_pydata(init_verts.tolist(), [], [])
        ring_mesh.update()

        ring_systems.append({
            "idx": ring_i,
            "mesh": ring_mesh,
            "bsdf": bsdf_r,
            "rx": rx,
            "ry": ry,
            "num_balls": num_balls
        })

    # Renderitzat dels fotogrames del chunk
    for frame in range(start_frame, end_frame + 1):
        scene.frame_set(frame)
        t = (frame - 1) / FPS

        for sys_data in ring_systems:
            ring_i = sys_data["idx"]
            phase, z = get_ring_phase_and_height(ring_i, t)
            
            # Actualitzar coordenades z naturals
            coords = np.column_stack((
                sys_data["rx"],
                sys_data["ry"],
                np.full(sys_data["num_balls"], z, dtype=np.float32)
            )).ravel()
            sys_data["mesh"].vertices.foreach_set("co", coords)
            sys_data["mesh"].update()

            # Actualitzar color: el centre canvia abans en tocar el terra més ràpid
            color = get_ring_color(ring_i, phase)
            sys_data["bsdf"].inputs["Base Color"].default_value = color

        scene.render.filepath = os.path.join(FRAMES_DIR, f"frame_{frame:04d}.png")
        bpy.ops.render.render(write_still=True)
        if frame % 10 == 0 or frame == end_frame:
            print(f"  [Chunk {chunk_idx}] Frame {frame}/{TOTAL_FRAMES} enllestit.")


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
        "✨ <b>BOUNCELAB 3D - MOVIMENT NATURAL I CÀMERA AMPLA</b>\n\n"
        "🔭 <b>Enquadrament:</b> Pedestal complet amb ampli marge a tots els costats\n"
        "⚡ <b>Dinàmica:</b> 1r bot 100% pla a l'uníson -> Al 2n bot el centre simplement baixa més àgil cap al terra de manera neta i harmònica\n"
        "🌈 <b>Colors:</b> Onades de color que flueixen des del centre"
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
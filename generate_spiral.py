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
TOTAL_FRAMES = 240  # 8 segons (permet veure la transició de pla a ona)
WIDTH = 720
HEIGHT = 1280

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Geometria dels anells concèntrics
NUM_RINGS = 16
R_MIN = 0.35
R_MAX = 3.60
BALL_RADIUS = 0.065
BOUNCE_HEIGHT = 1.35
BOUNCE_FREQ = 1.15  # Cicles de bot per segon

# ==============================================================================
# 📐 CÀLCUL MATEMÀTIC DEL MOVIMENT (TRANSICIÓ PLA -> ONA)
# ==============================================================================
def get_ring_height(ring_idx, t):
    """
    Calcula l'altura z d'un anell en el temps t.
    Comença sincronitzat (pla) i progressivament crea un desfasament radial (ona).
    """
    u = ring_idx / (NUM_RINGS - 1)  # 0.0 (centre) a 1.0 (vora exterior)
    
    # El decalatge de fase (ona) és 0 al principi i creix a partir del segon 1.8
    if t < 1.8:
        wave_dispersion = 0.0
    else:
        # Creixement suau de la dispersió de fase
        progress = min(1.0, (t - 1.8) / 3.0)
        wave_dispersion = progress * math.pi * 1.5

    # Fase: a l'inici wave_dispersion=0, per tant tots els anells comparteixen la mateixa fase
    phase = 2.0 * math.pi * BOUNCE_FREQ * t - (u * wave_dispersion)
    
    # Bouncing rectificat (altura >= 0 sempre, tocant el terra a z=0)
    z = BOUNCE_HEIGHT * (abs(math.sin(phase)) ** 1.35)
    return z


# ==============================================================================
# 🔔 1. SÍNTESI D'ÀUDIO PER IMPACTES FÍSICS REALS A TERRA
# ==============================================================================
def generate_chimes_audio(duration_sec, output_wav):
    print("🎵 Calculant impactes contra el terra i sintetitzant notes...")
    SAMPLE_RATE = 44100
    n_samples = int(duration_sec * SAMPLE_RATE)
    audio = np.zeros(n_samples, dtype=np.float32)

    # Escala pentatònica de C major (des de greus a l'exterior fins a aguts al centre)
    # 16 notes harmòniques cristal·lines
    NOTES_SCALE = [
        130.81, 146.83, 164.81, 196.00, 220.00,  # C3 - A3
        261.63, 293.66, 329.63, 392.00, 440.00,  # C4 - A4
        523.25, 587.33, 659.25, 783.99, 880.00,  # C5 - A5
        1046.50                                   # C6
    ]

    # Mostrejar les altures a alta freqüència (600 fps) per detectar els moments de xoc amb el terra (mínims z=0)
    DT_AUDIO_SCAN = 1.0 / 600.0
    scan_steps = int(duration_sec / DT_AUDIO_SCAN)
    
    for ring_idx in range(NUM_RINGS):
        freq = NOTES_SCALE[(NUM_RINGS - 1) - ring_idx]  # Exterior greu, interior agut
        prev_z = get_ring_height(ring_idx, 0.0)
        prev_vel = 0.0

        for step in range(1, scan_steps):
            t_curr = step * DT_AUDIO_SCAN
            z_curr = get_ring_height(ring_idx, t_curr)
            vel = z_curr - prev_z

            # Detectem el canvi de sentit just quan la pilota colpeja el terra (vel passa de negativa a positiva i z ~ 0)
            if prev_vel <= 0.0 and vel > 0.0 and z_curr < 0.08:
                hit_sample = int(t_curr * SAMPLE_RATE)
                if hit_sample < n_samples:
                    # Durada de la ressonància de la campana
                    note_len = min(int(1.8 * SAMPLE_RATE), n_samples - hit_sample)
                    t_note = np.linspace(0, note_len / SAMPLE_RATE, note_len, False)
                    
                    # So de campana metàl·lica amb harmònics i caiguda
                    sound_wave = (
                        0.60 * np.sin(2 * np.pi * freq * t_note) +
                        0.30 * np.sin(2 * np.pi * (freq * 2.01) * t_note) +
                        0.10 * np.sin(2 * np.pi * (freq * 3.00) * t_note)
                    ) * np.exp(-3.5 * t_note)
                    
                    audio[hit_sample : hit_sample + note_len] += sound_wave * 0.45

            prev_z = z_curr
            prev_vel = vel

    # Compressió suau per evitar distorsió quan sonen totes les boles a la vegada a l'inici
    audio = np.tanh(audio * 1.4)
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

    # Càmera angular elevada
    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = (0, -10.2, 7.8)
    cam.rotation_euler = (math.radians(54), 0, 0)

    # Llums (Principal i rebliment lateral)
    light_data = bpy.data.lights.new(name="MainLight", type='AREA')
    light_data.energy = 500
    light_data.size = 9.0
    light = bpy.data.objects.new("MainLight", light_data)
    light.location = (0, -1.0, 9.0)
    scene.collection.objects.link(light)

    # 1. MATERIALS
    # Boles: Verd maragda brillant amb metall
    mat_sphere = bpy.data.materials.new("SphereMat")
    bsdf_s = mat_sphere.node_tree.nodes.get("Principled BSDF")
    bsdf_s.inputs["Base Color"].default_value = (0.05, 0.90, 0.45, 1.0)
    bsdf_s.inputs["Metallic"].default_value = 0.85
    bsdf_s.inputs["Roughness"].default_value = 0.12

    # Terra/Pedestal: Base fosca visible amb bisell de contrast
    mat_floor = bpy.data.materials.new("FloorMat")
    bsdf_f = mat_floor.node_tree.nodes.get("Principled BSDF")
    bsdf_f.inputs["Base Color"].default_value = (0.08, 0.10, 0.12, 1.0)
    bsdf_f.inputs["Metallic"].default_value = 0.30
    bsdf_f.inputs["Roughness"].default_value = 0.35

    # 2. CREACIÓ DEL TERRA (EL PEDESTAL DEL VÍDEO)
    # Col·locat exactament a z = -BALL_RADIUS perquè les boles toquin la superfície en z=0
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=64,
        radius=R_MAX + 0.45,
        depth=0.5,
        location=(0, 0, -BALL_RADIUS - 0.25)
    )
    floor_obj = bpy.context.active_object
    floor_obj.data.materials.append(mat_floor)

    # Anell de contorn estètic al terra
    bpy.ops.mesh.primitive_torus_add(
        major_radius=R_MAX + 0.45,
        minor_radius=0.04,
        major_segments=64,
        minor_segments=12,
        location=(0, 0, -BALL_RADIUS)
    )
    ring_border = bpy.context.active_object
    ring_border.data.materials.append(mat_sphere)

    # 3. GENERACIÓ DELS ANELLS CONCÈNTRICS DE BOLES
    ring_radii = np.linspace(R_MIN, R_MAX, NUM_RINGS)
    all_x = []
    all_y = []
    ball_ring_indices = []

    for idx, r in enumerate(ring_radii):
        # Nombre de boles proporcional al perímetre de l'anell
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

    # Malla base per instanciació
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

    # Precalcular altures per anell per a cada fotograma del chunk
    for frame in range(start_frame, end_frame + 1):
        scene.frame_set(frame)
        t = (frame - 1) / FPS

        # Altura de cadascun dels 16 anells en aquest instant exacte
        ring_z_values = np.array([get_ring_height(i, t) for i in range(NUM_RINGS)], dtype=np.float32)
        
        # Mapejar a cada bola segons a quin anell pertany
        balls_z = ring_z_values[ball_ring_indices]

        # Actualització directa a memòria
        coords = np.column_stack((all_x, all_y, balls_z)).astype(np.float32).ravel()
        base_mesh.vertices.foreach_set("co", coords)
        base_mesh.update()

        scene.render.filepath = os.path.join(FRAMES_DIR, f"frame_{frame:04d}.png")
        bpy.ops.render.render(write_still=True)
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
        "✨ <b>BOUNCELAB 3D - ANELLS CONCÈNTRICS</b>\n\n"
        "🟢 <b>Moviment:</b> Bota en pla a l'inici i es converteix en ona concèntrica\n"
        "🔘 <b>Terra:</b> Pedestal rígid integrat amb contacte visual exacte\n"
        "🔔 <b>Àudio:</b> Cada fila d'anell dispara la seva nota quan toca el terra (acord uníson inicial -> cascada arpegiada)"
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
    print("⚡ Unint els fotogrames i sincronitzant impactes...")
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

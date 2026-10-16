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

OUTPUT_VIDEO = "output_pyramid.mp4"
FRAMES_DIR = "temp_frames"
ASSEMBLE_DIR = "all_frames"
TEMP_AUDIO = "temp_impacts.wav"
BAKED_BLEND = "pyramid_baked.blend"

FPS = 30
ROUND_FRAMES = 210  # 7 segons per ronda (4 rondes = 28 segons = 840 frames)
TOTAL_FRAMES = ROUND_FRAMES * 4
WIDTH = 720
HEIGHT = 1280

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

PYRAMID_LAYERS = 14  # 1.015 cubs sòlids
CUBE_SIZE = 0.20

# Configuració de les 4 rondes (cadascuna amb piràmide neta)
ROUNDS_CONFIG = [
    {"label": "1 kg",    "mass": 1.0,    "radius": 0.22, "hit_time": 1.5},
    {"label": "10 kg",   "mass": 10.0,   "radius": 0.36, "hit_time": 8.5},
    {"label": "100 kg",  "mass": 100.0,  "radius": 0.58, "hit_time": 15.5},
    {"label": "1000 kg", "mass": 1000.0, "radius": 0.90, "hit_time": 22.5},
]


# ==============================================================================
# 💥 1. SÍNTESI D'ÀUDIO PROCEDURAL DELS 4 IMPACTES
# ==============================================================================
def generate_impacts_audio(duration_sec, output_wav):
    print("🎵 Sintetitzant sons d'impacte contundents...")
    SAMPLE_RATE = 44100
    n_samples = int(duration_sec * SAMPLE_RATE)
    audio = np.zeros(n_samples, dtype=np.float32)

    impact_profiles = [
        {"time": 1.5,  "sub_freq": 110.0, "decay": 10.0, "noise_amt": 0.35, "vol": 0.50},  # 1kg
        {"time": 8.5,  "sub_freq": 72.0,  "decay": 5.5,  "noise_amt": 0.55, "vol": 0.75},  # 10kg
        {"time": 15.5, "sub_freq": 50.0,  "decay": 3.2,  "noise_amt": 0.75, "vol": 0.95},  # 100kg
        {"time": 22.5, "sub_freq": 36.0,  "decay": 2.0,  "noise_amt": 0.95, "vol": 1.15},  # 1000kg
    ]

    for p in impact_profiles:
        start = int(p["time"] * SAMPLE_RATE)
        dur = min(4.0, duration_sec - p["time"])
        n_note = int(dur * SAMPLE_RATE)
        t = np.linspace(0, dur, n_note, False)

        sub_boom = np.sin(2 * np.pi * p["sub_freq"] * t) * np.exp(-p["decay"] * t)
        noise = (np.random.rand(n_note) * 2.0 - 1.0) * np.exp(-p["decay"] * 0.75 * t)
        
        sound = (sub_boom * 0.7 + noise * p["noise_amt"]) * p["vol"]
        audio[start : start + n_note] += sound

    audio = np.tanh(audio * 1.3)
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
# 🏗️ 2. SIMULACIÓ FÍSICA PER RONDES AMB REINICI DE PIRÀMIDE
# ==============================================================================
def simulate_single_round(mass, radius):
    """Simula una ronda de 7 segons (210 fotogrames) amb piràmide neta."""
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = ROUND_FRAMES
    scene.render.fps = FPS

    bpy.ops.rigidbody.world_add()
    scene.rigidbody_world.point_cache.frame_start = 1
    scene.rigidbody_world.point_cache.frame_end = ROUND_FRAMES
    scene.rigidbody_world.substeps_per_frame = 10
    scene.rigidbody_world.solver_iterations = 10
    scene.gravity = (0, 0, -8.2)

    # Terra
    bpy.ops.mesh.primitive_cube_add(size=20.0, location=(0, 0, -10.0))
    ground = bpy.context.active_object
    bpy.ops.rigidbody.object_add()
    ground.rigid_body.type = 'PASSIVE'
    ground.rigid_body.collision_shape = 'BOX'
    ground.rigid_body.friction = 0.8

    # Construir piràmide neta
    cubes = []
    cube_init_pos = []
    for layer_k in range(PYRAMID_LAYERS):
        num_per_side = layer_k + 1
        z = (PYRAMID_LAYERS - 1 - layer_k) * CUBE_SIZE + (CUBE_SIZE / 2.0)
        offset = ((num_per_side - 1) * CUBE_SIZE) / 2.0

        for ix in range(num_per_side):
            for iy in range(num_per_side):
                x = ix * CUBE_SIZE - offset
                y = iy * CUBE_SIZE - offset

                bpy.ops.mesh.primitive_cube_add(size=CUBE_SIZE * 0.98, location=(x, y, z))
                c = bpy.context.active_object
                bpy.ops.rigidbody.object_add()
                c.rigid_body.type = 'ACTIVE'
                c.rigid_body.collision_shape = 'BOX'
                c.rigid_body.mass = 0.35
                c.rigid_body.friction = 0.70
                c.rigid_body.use_deactivation = True
                cubes.append(c)
                cube_init_pos.append((x, y, z))

    # Bola de la ronda
    drop_z = (PYRAMID_LAYERS * CUBE_SIZE) + 4.5 + radius
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=(0, 0, drop_z))
    ball = bpy.context.active_object
    bpy.ops.rigidbody.object_add()
    ball.rigid_body.type = 'ACTIVE'
    ball.rigid_body.collision_shape = 'SPHERE'
    ball.rigid_body.mass = mass
    ball.rigid_body.friction = 0.4

    # Simular física de la ronda
    for f in range(1, ROUND_FRAMES + 1):
        scene.frame_set(f)

    # Extreure dades simulades
    cube_anim = []
    ball_anim = []
    for f in range(1, ROUND_FRAMES + 1):
        scene.frame_set(f)
        f_cubes = [(c.matrix_world.translation.copy(), c.matrix_world.to_euler().copy()) for c in cubes]
        cube_anim.append(f_cubes)
        ball_anim.append((ball.matrix_world.translation.copy(), ball.matrix_world.to_euler().copy()))

    return cube_anim, ball_anim, cube_init_pos


def simulate_physics():
    import bpy

    print("🔨 Simulant les 4 rondes de destrucció independentment...")
    sim_data = []
    init_positions = None

    for idx, r_conf in enumerate(ROUNDS_CONFIG):
        print(f"  -> Simulant xoc de {r_conf['label']} (massa {r_conf['mass']} kg)...")
        c_anim, b_anim, c_init = simulate_single_round(r_conf["mass"], r_conf["radius"])
        sim_data.append((c_anim, b_anim, r_conf["radius"]))
        if init_positions is None:
            init_positions = c_init

    print("🎬 Construint escena definitiva combinada amb piràmide reiniciada...")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = TOTAL_FRAMES
    scene.render.fps = FPS

    # Materials
    mat_block = bpy.data.materials.new("BlockMat")
    bsdf_b = mat_block.node_tree.nodes.get("Principled BSDF")
    bsdf_b.inputs["Base Color"].default_value = (0.50, 0.32, 0.17, 1.0)
    bsdf_b.inputs["Roughness"].default_value = 0.75

    mat_chrome = bpy.data.materials.new("ChromeBallMat")
    bsdf_c = mat_chrome.node_tree.nodes.get("Principled BSDF")
    bsdf_c.inputs["Base Color"].default_value = (0.95, 0.95, 0.95, 1.0)
    bsdf_c.inputs["Metallic"].default_value = 1.0
    bsdf_c.inputs["Roughness"].default_value = 0.05

    mat_floor = bpy.data.materials.new("GroundMat")
    bsdf_f = mat_floor.node_tree.nodes.get("Principled BSDF")
    bsdf_f.inputs["Base Color"].default_value = (0.07, 0.08, 0.10, 1.0)
    bsdf_f.inputs["Roughness"].default_value = 0.40

    # Terra
    bpy.ops.mesh.primitive_cube_add(size=20.0, location=(0, 0, -10.0))
    ground = bpy.context.active_object
    ground.data.materials.append(mat_floor)

    # Cubs de la piràmide
    scene_cubes = []
    for pos in init_positions:
        bpy.ops.mesh.primitive_cube_add(size=CUBE_SIZE * 0.98, location=pos)
        cube_obj = bpy.context.active_object
        cube_obj.data.materials.append(mat_block)
        scene_cubes.append(cube_obj)

    # Bola única
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, location=(0, 0, 15.0))
    ball_obj = bpy.context.active_object
    ball_obj.data.materials.append(mat_chrome)
    bpy.ops.object.shade_smooth()

    # Càmera
    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = (0, -11.5, 7.5)
    cam.rotation_euler = (math.radians(60), 0, 0)

    # Il·luminació
    light_data = bpy.data.lights.new(name="MainLight", type='AREA')
    light_data.energy = 750
    light_data.size = 12.0
    light = bpy.data.objects.new("MainLight", light_data)
    light.location = (0, -1.0, 12.0)
    scene.collection.objects.link(light)

    fill_data = bpy.data.lights.new(name="FillLight", type='AREA')
    fill_data.energy = 200
    fill_data.size = 8.0
    fill = bpy.data.objects.new("FillLight", fill_data)
    fill.location = (0, -8.0, 5.0)
    scene.collection.objects.link(fill)

    # Gravar keyframes a l'escena
    print("⏳ Gravant keyframes a l'escena (reinici net a cada pes)...")
    for r_idx in range(4):
        c_anim, b_anim, b_rad = sim_data[r_idx]
        base_f = r_idx * ROUND_FRAMES

        ball_obj.scale = (b_rad, b_rad, b_rad)
        ball_obj.keyframe_insert("scale", frame=base_f + 1)

        has_moved_cube = [False] * len(scene_cubes)

        for local_f in range(ROUND_FRAMES):
            global_f = base_f + local_f + 1

            # Posició de la bola
            b_loc, b_rot = b_anim[local_f]
            ball_obj.location = b_loc
            ball_obj.rotation_euler = b_rot
            ball_obj.keyframe_insert("location", frame=global_f)
            ball_obj.keyframe_insert("rotation_euler", frame=global_f)

            # Posició dels cubs amb math.dist() corregit
            for c_i, c_obj in enumerate(scene_cubes):
                c_loc, c_rot = c_anim[local_f][c_i]
                init_p = init_positions[c_i]

                if not has_moved_cube[c_i]:
                    diff = math.dist(tuple(c_loc), init_p)
                    if diff > 0.015:
                        has_moved_cube[c_i] = True
                        if local_f > 0:
                            c_obj.location = init_p
                            c_obj.rotation_euler = (0, 0, 0)
                            c_obj.keyframe_insert("location", frame=global_f - 1)
                            c_obj.keyframe_insert("rotation_euler", frame=global_f - 1)

                if has_moved_cube[c_i]:
                    c_obj.location = c_loc
                    c_obj.rotation_euler = c_rot
                    c_obj.keyframe_insert("location", frame=global_f)
                    c_obj.keyframe_insert("rotation_euler", frame=global_f)

        for c_i, c_obj in enumerate(scene_cubes):
            if not has_moved_cube[c_i]:
                c_obj.location = init_positions[c_i]
                c_obj.rotation_euler = (0, 0, 0)
                c_obj.keyframe_insert("location", frame=base_f + 1)
                c_obj.keyframe_insert("rotation_euler", frame=base_f + 1)

    print(f"💾 Desant escena congelada a {BAKED_BLEND}...")
    bpy.ops.wm.save_as_mainfile(filepath=BAKED_BLEND, compress=True)
    print("✅ Simulació per rondes completada amb èxit!")


# ==============================================================================
# 🎨 3. RENDERITZAT 3D EN PARAL·LEL (PAS 2)
# ==============================================================================
def render_chunk(chunk_idx, total_chunks):
    import bpy

    frames_per_chunk = math.ceil(TOTAL_FRAMES / total_chunks)
    start_frame = chunk_idx * frames_per_chunk + 1
    end_frame = min(TOTAL_FRAMES, (chunk_idx + 1) * frames_per_chunk)

    print(f"🎬 Runner #{chunk_idx}: renderitzant fotogrames {start_frame} a {end_frame}...")
    os.makedirs(FRAMES_DIR, exist_ok=True)
    scene = bpy.context.scene

    scene.render.fps = FPS
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT

    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 4
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 1
    scene.cycles.diffuse_bounces = 1
    scene.cycles.glossy_bounces = 1
    scene.cycles.transmission_bounces = 0
    scene.cycles.transparent_max_bounces = 0
    scene.cycles.volume_bounces = 0
    if hasattr(scene.cycles, "use_light_tree"):
        scene.cycles.use_light_tree = False

    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'

    for frame in range(start_frame, end_frame + 1):
        scene.frame_set(frame)
        scene.render.filepath = os.path.join(FRAMES_DIR, f"frame_{frame:04d}.png")
        bpy.ops.render.render(write_still=True)
        if frame % 15 == 0 or frame == end_frame:
            print(f"  [Chunk {chunk_idx}] Frame {frame}/{TOTAL_FRAMES} enllestit.")


# ==============================================================================
# 📲 4. ENVIAMENT A TELEGRAM
# ==============================================================================
def send_telegram_video(video_path):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("⚠️ Falten secrets de Telegram.")
        return

    print("📲 TEST_MODE=True: Enviant vídeo de la piràmide a Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    caption = (
        "💥 <b>BOUNCELAB 3D - DESTRUCCIÓ DE PIRÀMIDE PER RONDES</b>\n\n"
        "🧱 <b>Format:</b> Piràmide neta a cada nou pes (4 rondes de 7s)\n"
        "⚖️ <b>Pesos:</b> 1kg → 10kg → 100kg → 1.000kg amb text 2D nítid\n"
        "🔊 <b>So:</b> Terrabastall sincronitzat a cada impacte"
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
                timeout=240
            )
        if res.status_code == 200:
            print("✅ Vídeo de la piràmide enviat a Telegram amb èxit!")
        else:
            print(f"❌ Error Telegram ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ Excepció Telegram: {e}")


# ==============================================================================
# 🎬 5. ACOBLAMENT FINAL AMB TEXT 2D NÍTID (FFMPEG)
# ==============================================================================
def assemble_final_video():
    print("⚡ Unint els 840 fotogrames i afegint text 2D...")
    duration = TOTAL_FRAMES / FPS
    generate_impacts_audio(duration, TEMP_AUDIO)

    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    font_arg = ""
    for f in font_candidates:
        if os.path.exists(f):
            font_arg = f":fontfile='{f}'"
            break

    vf_filter = (
        f"drawtext=text='1 kg':enable='between(t,0,7)'{font_arg}:fontsize=80:fontcolor=white:borderw=5:bordercolor=black@0.85:x=(w-text_w)/2:y=130,"
        f"drawtext=text='10 kg':enable='between(t,7,14)'{font_arg}:fontsize=80:fontcolor=white:borderw=5:bordercolor=black@0.85:x=(w-text_w)/2:y=130,"
        f"drawtext=text='100 kg':enable='between(t,14,21)'{font_arg}:fontsize=80:fontcolor=white:borderw=5:bordercolor=black@0.85:x=(w-text_w)/2:y=130,"
        f"drawtext=text='1000 kg':enable='between(t,21,28)'{font_arg}:fontsize=80:fontcolor=white:borderw=5:bordercolor=black@0.85:x=(w-text_w)/2:y=130"
    )

    frame_pattern = os.path.join(ASSEMBLE_DIR, "frame_%04d.png")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", frame_pattern,
            "-i", TEMP_AUDIO,
            "-vf", vf_filter,
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
    raw_args = sys.argv
    cli_args = raw_args[raw_args.index("--") + 1:] if "--" in raw_args else raw_args[1:]

    if "--simulate" in cli_args:
        simulate_physics()
    elif "--render-chunk" in cli_args:
        idx = int(cli_args[cli_args.index("--render-chunk") + 1])
        tot = int(cli_args[cli_args.index("--render-chunk") + 2])
        render_chunk(idx, tot)
    elif "--assemble" in cli_args:
        assemble_final_video()
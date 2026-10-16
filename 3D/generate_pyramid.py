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
TOTAL_FRAMES = 840  # 28 segons exactes
WIDTH = 720
HEIGHT = 1280

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

PYRAMID_LAYERS = 14  # 1.015 cubs sòlids
CUBE_SIZE = 0.20

# Configuració dels 4 pesos i els seus intervals
DROPS_CONFIG = [
    {"label": "1kg",    "mass": 1.0,    "radius": 0.22, "start_frame": 1,   "drop_frame": 10,  "end_frame": 180},
    {"label": "10kg",   "mass": 10.0,   "radius": 0.36, "start_frame": 181, "drop_frame": 190, "end_frame": 420},
    {"label": "100kg",  "mass": 100.0,  "radius": 0.58, "start_frame": 421, "drop_frame": 430, "end_frame": 660},
    {"label": "1000kg", "mass": 1000.0, "radius": 0.88, "start_frame": 661, "drop_frame": 670, "end_frame": 840},
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
        {"time": 1.0,  "sub_freq": 110.0, "decay": 12.0, "noise_amt": 0.35, "vol": 0.45},
        {"time": 7.0,  "sub_freq": 75.0,  "decay": 6.0,  "noise_amt": 0.55, "vol": 0.70},
        {"time": 15.0, "sub_freq": 52.0,  "decay": 3.5,  "noise_amt": 0.75, "vol": 0.90},
        {"time": 23.0, "sub_freq": 38.0,  "decay": 2.2,  "noise_amt": 0.90, "vol": 1.10},
    ]

    for p in impact_profiles:
        start = int(p["time"] * SAMPLE_RATE)
        dur = min(3.5, duration_sec - p["time"])
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
# 🏗️ 2. SIMULACIÓ FÍSICA I CONGELACIÓ (HEADLESS)
# ==============================================================================
def simulate_physics():
    import bpy

    print("🔨 Construint piràmide i preparant Bullet Engine...")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    scene.frame_start = 1
    scene.frame_end = TOTAL_FRAMES
    scene.render.fps = FPS

    if not scene.rigidbody_world:
        bpy.ops.rigidbody.world_add()
    scene.rigidbody_world.point_cache.frame_start = 1
    scene.rigidbody_world.point_cache.frame_end = TOTAL_FRAMES
    scene.rigidbody_world.substeps_per_frame = 10
    scene.rigidbody_world.solver_iterations = 10

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

    mat_text = bpy.data.materials.new("TextMat")
    bsdf_t = mat_text.node_tree.nodes.get("Principled BSDF")
    bsdf_t.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    if "Emission Color" in bsdf_t.inputs:
        bsdf_t.inputs["Emission Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        bsdf_t.inputs["Emission Strength"].default_value = 1.5

    # 1. Terra passiu rígid (Cub massiu de 20m amb cara superior plana a z = 0.0)
    bpy.ops.mesh.primitive_cube_add(size=20.0, location=(0, 0, -10.0))
    ground = bpy.context.active_object
    ground.data.materials.append(mat_floor)
    bpy.ops.rigidbody.object_add()
    ground.rigid_body.type = 'PASSIVE'
    ground.rigid_body.collision_shape = 'BOX'
    ground.rigid_body.friction = 0.8

    # 2. Piràmide de cubs
    active_cubes = []
    for layer_k in range(PYRAMID_LAYERS):
        num_per_side = layer_k + 1
        z = (PYRAMID_LAYERS - 1 - layer_k) * CUBE_SIZE + (CUBE_SIZE / 2.0)
        offset = ((num_per_side - 1) * CUBE_SIZE) / 2.0

        for ix in range(num_per_side):
            for iy in range(num_per_side):
                x = ix * CUBE_SIZE - offset
                y = iy * CUBE_SIZE - offset

                bpy.ops.mesh.primitive_cube_add(size=CUBE_SIZE * 0.98, location=(x, y, z))
                cube = bpy.context.active_object
                cube.data.materials.append(mat_block)
                
                bpy.ops.rigidbody.object_add()
                cube.rigid_body.type = 'ACTIVE'
                cube.rigid_body.collision_shape = 'BOX'
                cube.rigid_body.mass = 0.40
                cube.rigid_body.friction = 0.70
                cube.rigid_body.use_deactivation = True
                active_cubes.append(cube)

    print(f"🧱 Piràmide construïda amb èxit: {len(active_cubes)} blocs sòlids.")

    # 3. Les 4 boles pesades amb activació seqüencial
    ball_objects = []
    for drop in DROPS_CONFIG:
        drop_z = (PYRAMID_LAYERS * CUBE_SIZE) + 2.5 + (drop["radius"] * 1.5)
        
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=drop["radius"],
            segments=32,
            ring_count=16,
            location=(0, 0, drop_z)
        )
        ball = bpy.context.active_object
        ball.name = f"Ball_{drop['label']}"
        ball.data.materials.append(mat_chrome)
        bpy.ops.object.shade_smooth()

        bpy.ops.rigidbody.object_add()
        ball.rigid_body.type = 'ACTIVE'
        ball.rigid_body.collision_shape = 'SPHERE'
        ball.rigid_body.mass = drop["mass"]
        ball.rigid_body.friction = 0.4
        
        f_drop = drop["drop_frame"]
        
        # Animació correcta del flag kinematic
        ball.rigid_body.kinematic = True
        ball.keyframe_insert(data_path="rigid_body.kinematic", frame=1)
        if f_drop > 1:
            ball.keyframe_insert(data_path="rigid_body.kinematic", frame=f_drop - 1)
        ball.rigid_body.kinematic = False
        ball.keyframe_insert(data_path="rigid_body.kinematic", frame=f_drop)

        # Visibilitat de la bola
        ball.hide_render = True
        ball.keyframe_insert(data_path="hide_render", frame=1)
        if f_drop > 1:
            ball.keyframe_insert(data_path="hide_render", frame=f_drop - 1)
        ball.hide_render = False
        ball.keyframe_insert(data_path="hide_render", frame=f_drop)

        ball_objects.append(ball)

        # 4. Text 3D
        bpy.ops.object.text_add(location=(0, -0.6, 5.8))
        txt_obj = bpy.context.active_object
        txt_obj.name = f"Text_{drop['label']}"
        txt_obj.data.body = drop["label"]
        txt_obj.data.align_x = 'CENTER'
        txt_obj.data.size = 0.70
        txt_obj.data.materials.append(mat_text)
        txt_obj.rotation_euler = (math.radians(90), 0, 0)

        f_start = drop["start_frame"]
        f_end = drop["end_frame"]
        
        txt_obj.hide_render = True
        txt_obj.keyframe_insert(data_path="hide_render", frame=1)
        if f_start > 1:
            txt_obj.keyframe_insert(data_path="hide_render", frame=f_start - 1)
        txt_obj.hide_render = False
        txt_obj.keyframe_insert(data_path="hide_render", frame=f_start)
        txt_obj.keyframe_insert(data_path="hide_render", frame=f_end)
        if f_end < TOTAL_FRAMES:
            txt_obj.hide_render = True
            txt_obj.keyframe_insert(data_path="hide_render", frame=f_end + 1)

    # 5. Càmera i Il·luminació
    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = (0, -11.0, 7.2)
    cam.rotation_euler = (math.radians(62), 0, 0)

    light_data = bpy.data.lights.new(name="SunLight", type='SUN')
    light_data.energy = 4.5
    light = bpy.data.objects.new("SunLight", light_data)
    light.rotation_euler = (math.radians(45), math.radians(25), math.radians(-30))
    scene.collection.objects.link(light)

    # 6. SIMULACIÓ BULLET I EXTRACCIÓ A KEYFRAMES (100% HEADLESS)
    print("⏳ Executant simulació física Bullet pas a pas...")
    bpy.ops.wm.save_as_mainfile(filepath=BAKED_BLEND)
    try:
        bpy.ops.ptcache.bake_all(bake=True)
    except Exception as e:
        print(f"ℹ️ Executant càlcul seqüencial directament ({e})")

    print("⚡ Convertint les posicions simulades a keyframes permanents...")
    init_states = {cube.name: (cube.location.copy(), cube.rotation_euler.copy()) for cube in active_cubes}
    has_moved = {cube.name: False for cube in active_cubes}

    for f in range(1, TOTAL_FRAMES + 1):
        scene.frame_set(f)
        
        # Boles: enregistrem trajectòria a partir del seu llançament
        for drop_idx, ball in enumerate(ball_objects):
            drop_info = DROPS_CONFIG[drop_idx]
            if f >= drop_info["drop_frame"]:
                ball.location = ball.matrix_world.translation.copy()
                ball.rotation_euler = ball.matrix_world.to_euler()
                ball.keyframe_insert(data_path="location", frame=f)
                ball.keyframe_insert(data_path="rotation_euler", frame=f)

        # Cubs: només keyframegem els que reben un impacte real (> 1.5 cm) per no saturar memòria
        for cube in active_cubes:
            cur_loc = cube.matrix_world.translation.copy()
            cur_rot = cube.matrix_world.to_euler()

            if not has_moved[cube.name]:
                diff = (cur_loc - init_states[cube.name][0]).length
                if diff > 0.015:
                    has_moved[cube.name] = True
                    if f > 1:
                        cube.location = init_states[cube.name][0]
                        cube.rotation_euler = init_states[cube.name][1]
                        cube.keyframe_insert(data_path="location", frame=f - 1)
                        cube.keyframe_insert(data_path="rotation_euler", frame=f - 1)

            if has_moved[cube.name]:
                cube.location = cur_loc
                cube.rotation_euler = cur_rot
                cube.keyframe_insert(data_path="location", frame=f)
                cube.keyframe_insert(data_path="rotation_euler", frame=f)

    # Retirem el motor físic perquè el fitxer sigui una animació pura independent
    bpy.ops.rigidbody.world_remove()

    print(f"💾 Desant escena congelada a {BAKED_BLEND}...")
    bpy.ops.wm.save_as_mainfile(filepath=BAKED_BLEND, compress=True)
    print("✅ Simulació completada i congelada amb èxit!")


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
    scene.cycles.max_bounces = 2
    scene.cycles.diffuse_bounces = 1
    scene.cycles.glossy_bounces = 2
    scene.cycles.transmission_bounces = 0
    scene.cycles.transparent_max_bounces = 1
    scene.cycles.volume_bounces = 0

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
        "💥 <b>BOUNCELAB 3D - DESTRUCCIÓ DE PIRÀMIDE (WEIGHT TEST)</b>\n\n"
        "🧱 <b>Estructura:</b> 1.015 blocs sòlids amb física de cossos rígids\n"
        "⚖️ <b>Impactes:</b> 1kg → 10kg → 100kg → 1.000kg (Destrucció total)\n"
        "🔊 <b>So:</b> Terrabastall i terratrèmol sincronitzat a cada impacte"
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
# 🎬 5. ACOBLAMENT FINAL (PAS 3)
# ==============================================================================
def assemble_final_video():
    print("⚡ Unint els 840 fotogrames de la destrucció...")
    duration = TOTAL_FRAMES / FPS
    generate_impacts_audio(duration, TEMP_AUDIO)

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
        print("⏸️ TEST_MODE és False: Vídeo de la piràmide generat a disc sense enviar.")


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

import os
import sys
import math
import wave
import json
import shutil
import subprocess
import requests
import numpy as np

# ==============================================================================
# ⚙️ CONFIGURACIÓ PRINCIPAL I VARIACIONS (EDITA AQUÍ DIRECTAMENT)
# ==============================================================================
TEST_MODE = True  # 👉 True (envia a Telegram) | False (no fa res)

# VARIACIÓ D'IMPACTE:
# "vertical" -> Caiguda lliure vertical des de dalt (Vídeo clàssic)
# "ramp"     -> Tobogan / Rampa corbada lateral per a xoc horitzontal tipus bitlles
IMPACT_MODE = "vertical"

OUTPUT_VIDEO = "output_pyramid.mp4"
FRAMES_DIR = "temp_frames"
ASSEMBLE_DIR = "all_frames"
TEMP_AUDIO = "temp_impacts.wav"
EVENTS_JSON = "impact_events.json"

FPS = 30
CLIP_FRAMES = 210   # 7 segons per clip
NUM_CLIPS = 4       # 1kg, 10kg, 100kg, 1000kg
TOTAL_FRAMES = CLIP_FRAMES * NUM_CLIPS  # 840 fotogrames (28s exactes)

WIDTH = 720
HEIGHT = 1280

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

PYRAMID_LAYERS = 14  # 1.015 blocs
CUBE_SIZE = 0.20

CLIPS_CONFIG = [
    {"label": "1kg",    "mass": 1.0,    "radius": 0.20, "is_marble": True},
    {"label": "10kg",   "mass": 10.0,   "radius": 0.35, "is_marble": False},
    {"label": "100kg",  "mass": 100.0,  "radius": 0.55, "is_marble": False},
    {"label": "1000kg", "mass": 1000.0, "radius": 0.85, "is_marble": False},
]


# ==============================================================================
# 🔔 1. SÍNTESI D'ÀUDIO ASMR (CANICA CRISTAL·LINA + RUNES PESADES)
# ==============================================================================
def synthesize_audio(duration_sec, output_wav, events):
    print("🎵 Sintetitzant àudio ASMR de canica i runes...")
    SAMPLE_RATE = 44100
    n_samples = int(duration_sec * SAMPLE_RATE)
    audio = np.zeros(n_samples, dtype=np.float32)

    for ev in events:
        t_hit = ev["time"]
        sound_type = ev["type"]  # "marble" o "heavy"
        intensity = min(1.0, max(0.15, ev.get("intensity", 0.5)))
        start_idx = int(t_hit * SAMPLE_RATE)

        if start_idx >= n_samples:
            continue

        if sound_type == "marble":
            # So agut i cristal·lí de canica rebotant per un esglaó (2.400 - 3.200 Hz)
            dur = 0.12
            n_note = min(int(dur * SAMPLE_RATE), n_samples - start_idx)
            t = np.linspace(0, dur, n_note, False)
            freq = 2800.0 + np.random.uniform(-400.0, 400.0)

            # To cristal·lí inharmònic amb caiguda ràpida
            marble_clink = (
                0.70 * np.sin(2 * np.pi * freq * t) +
                0.25 * np.sin(2 * np.pi * (freq * 2.76) * t) +
                0.05 * (np.random.rand(n_note) * 2 - 1)
            ) * np.exp(-48.0 * t)

            audio[start_idx : start_idx + n_note] += marble_clink * intensity * 0.65

        else:
            # Impacte greu de destrucció pesada
            dur = 2.5
            n_note = min(int(dur * SAMPLE_RATE), n_samples - start_idx)
            t = np.linspace(0, dur, n_note, False)
            sub_freq = ev.get("sub_freq", 60.0)

            boom = np.sin(2 * np.pi * sub_freq * t) * np.exp(-4.5 * t)
            crunch = (np.random.rand(n_note) * 2 - 1) * np.exp(-5.5 * t)
            audio[start_idx : start_idx + n_note] += (boom * 0.75 + crunch * 0.55) * intensity

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
# 🏗️ 2. SIMULACIÓ FÍSICA DELS 4 CLIPS INDEPENDENTS (PAS 1)
# ==============================================================================
def simulate_all_clips():
    import bpy

    all_events = []
    print(f"🎬 Iniciant simulació de 4 clips aïllats (Mode: {IMPACT_MODE.upper()})...")

    for clip_idx, config in enumerate(CLIPS_CONFIG):
        print(f"\n--- 🔨 Simulant Clip #{clip_idx} ({config['label']}) ---")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene

        scene.frame_start = 1
        scene.frame_end = CLIP_FRAMES
        scene.render.fps = FPS

        if not scene.rigidbody_world:
            bpy.ops.rigidbody.world_add()
        scene.rigidbody_world.point_cache.frame_start = 1
        scene.rigidbody_world.point_cache.frame_end = CLIP_FRAMES
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

        # 1. Terra passiu rígid
        bpy.ops.mesh.primitive_cube_add(size=20.0, location=(0, 0, -10.0))
        ground = bpy.context.active_object
        ground.data.materials.append(mat_floor)
        bpy.ops.rigidbody.object_add()
        ground.rigid_body.type = 'PASSIVE'
        ground.rigid_body.collision_shape = 'BOX'
        ground.rigid_body.friction = 0.8

        # 2. Piràmide intacta de 1.015 cubs
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

        # 3. La bola del clip concret
        ball_r = config["radius"]
        if IMPACT_MODE == "ramp":
            # Posició dalt de la rampa acceleradora lateral
            ball_start_pos = (-4.0, 0.0, 5.0)
            # Rampa corbada de llançament
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-2.6, 0.0, 2.8))
            ramp = bpy.context.active_object
            ramp.scale = (3.2, 1.6, 0.15)
            ramp.rotation_euler = (0, math.radians(35), 0)
            ramp.data.materials.append(mat_floor)
            bpy.ops.rigidbody.object_add()
            ramp.rigid_body.type = 'PASSIVE'
            ramp.rigid_body.collision_shape = 'BOX'
            ramp.rigid_body.friction = 0.05  # Molt lliscant per agafar velocitat
        else:
            # Caiguda lliure vertical des de dalt
            apex_z = PYRAMID_LAYERS * CUBE_SIZE
            ball_start_pos = (0.0, 0.0, apex_z + 2.5 + ball_r * 1.5)

        bpy.ops.mesh.primitive_uv_sphere_add(radius=ball_r, segments=32, ring_count=16, location=ball_start_pos)
        ball = bpy.context.active_object
        ball.name = f"Ball_{config['label']}"
        ball.data.materials.append(mat_chrome)
        bpy.ops.object.shade_smooth()

        bpy.ops.rigidbody.object_add()
        ball.rigid_body.type = 'ACTIVE'
        ball.rigid_body.collision_shape = 'SPHERE'
        ball.rigid_body.mass = config["mass"]
        ball.rigid_body.friction = 0.35

        # 4. Text 3D flotant ("1kg", "10kg", etc.)
        bpy.ops.object.text_add(location=(0, -0.6, 6.0))
        txt_obj = bpy.context.active_object
        txt_obj.name = f"Text_{config['label']}"
        txt_obj.data.body = config["label"]
        txt_obj.data.align_x = 'CENTER'
        txt_obj.data.size = 0.72
        txt_obj.data.materials.append(mat_text)
        txt_obj.rotation_euler = (math.radians(90), 0, 0)

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

        # 6. Simulació i captura de keyframes
        clip_blend = f"clip_{clip_idx}.blend"
        bpy.ops.wm.save_as_mainfile(filepath=clip_blend)
        try:
            bpy.ops.ptcache.bake_all(bake=True)
        except Exception:
            pass

        init_states = {cube.name: (cube.location.copy(), cube.rotation_euler.copy()) for cube in active_cubes}
        has_moved = {cube.name: False for cube in active_cubes}

        prev_ball_z = ball_start_pos[2]
        prev_vz = 0.0

        for f in range(1, CLIP_FRAMES + 1):
            scene.frame_set(f)
            t_global = (clip_idx * CLIP_FRAMES + (f - 1)) / FPS

            # Trajectòria de la bola
            ball.location = ball.matrix_world.translation.copy()
            ball.rotation_euler = ball.matrix_world.to_euler()
            ball.keyframe_insert(data_path="location", frame=f)
            ball.keyframe_insert(data_path="rotation_euler", frame=f)

            # Detecció de contactes / bots per al so ASMR
            cur_ball_z = ball.location.z
            vz = (cur_ball_z - prev_ball_z) * FPS
            delta_vz = vz - prev_vz

            # Si hi ha una desacceleració vertical brusca (xoc contra un esglaó)
            if delta_vz > 1.2 and cur_ball_z < 3.8:
                intensity = min(1.0, delta_vz / 6.0)
                if config["is_marble"]:
                    all_events.append({
                        "time": t_global,
                        "type": "marble",
                        "intensity": intensity
                    })
                elif f == 26:  # Impacte principal per a pesos grans
                    sub_f = 90.0 if config["label"] == "10kg" else (55.0 if config["label"] == "100kg" else 35.0)
                    all_events.append({
                        "time": t_global,
                        "type": "heavy",
                        "intensity": 1.0,
                        "sub_freq": sub_f
                    })

            prev_ball_z = cur_ball_z
            prev_vz = vz

            # Cubs: només keyframegem els que reben un impacte real
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

        bpy.ops.rigidbody.world_remove()
        bpy.ops.wm.save_as_mainfile(filepath=clip_blend, compress=True)
        print(f"✅ Clip #{clip_idx} congelat a {clip_blend}")

    # Guardar els esdeveniments sonors detectats
    with open(EVENTS_JSON, "w") as jf:
        json.dump(all_events, jf)
    print("✅ Esdeveniments sonors desats correctament!")


# ==============================================================================
# 🎨 3. RENDERITZAT 3D EN PARAL·LEL (PAS 2)
# ==============================================================================
def render_chunk(chunk_idx, total_chunks):
    import bpy

    frames_per_chunk = math.ceil(TOTAL_FRAMES / total_chunks)
    start_global = chunk_idx * frames_per_chunk + 1
    end_global = min(TOTAL_FRAMES, (chunk_idx + 1) * frames_per_chunk)

    print(f"🎬 Runner #{chunk_idx}: processant fotogrames globals {start_global} a {end_global}...")
    os.makedirs(FRAMES_DIR, exist_ok=True)

    # Renderitzar obrint directament el clip .blend corresponent
    current_loaded_clip = None

    for global_f in range(start_global, end_global + 1):
        clip_idx = (global_f - 1) // CLIP_FRAMES
        local_f = ((global_f - 1) % CLIP_FRAMES) + 1
        clip_blend = f"clip_{clip_idx}.blend"

        if current_loaded_clip != clip_blend:
            bpy.ops.wm.open_mainfile(filepath=clip_blend)
            current_loaded_clip = clip_blend

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

        scene = bpy.context.scene
        scene.frame_set(local_f)
        scene.render.filepath = os.path.join(FRAMES_DIR, f"frame_{global_f:04d}.png")
        bpy.ops.render.render(write_still=True)

        if global_f % 15 == 0 or global_f == end_global:
            print(f"  [Chunk {chunk_idx}] Frame {global_f}/{TOTAL_FRAMES} enllestit.")


# ==============================================================================
# 📲 4. ENVIAMENT A TELEGRAM
# ==============================================================================
def send_telegram_video(video_path):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("⚠️ Falten secrets de Telegram.")
        return

    print("📲 TEST_MODE=True: Enviant vídeo a Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    caption = (
        "💥 <b>BOUNCELAB 3D - CLIPS AÏLLATS I SO DE CANICA ASMR</b>\n\n"
        "✨ <b>Estructura:</b> 4 clips completament nets i independents\n"
        "🔮 <b>Àudio:</b> So cristal·lí de canica en rodolar pels esglaons + xoc greu\n"
        "⚖️ <b>Pesos:</b> 1kg → 10kg → 100kg → 1.000kg"
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
    print("⚡ Unint els 840 fotogrames i sintetitzant l'àudio ASMR...")
    duration = TOTAL_FRAMES / FPS

    events = []
    if os.path.exists(EVENTS_JSON):
        with open(EVENTS_JSON, "r") as jf:
            events = json.load(jf)

    synthesize_audio(duration, TEMP_AUDIO, events)

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
    raw_args = sys.argv
    cli_args = raw_args[raw_args.index("--") + 1:] if "--" in raw_args else raw_args[1:]

    if "--simulate" in cli_args:
        simulate_all_clips()
    elif "--render-chunk" in cli_args:
        idx = int(cli_args[cli_args.index("--render-chunk") + 1])
        tot = int(cli_args[cli_args.index("--render-chunk") + 2])
        render_chunk(idx, tot)
    elif "--assemble" in cli_args:
        assemble_final_video()

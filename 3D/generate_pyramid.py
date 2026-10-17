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
# ⚙️ CONFIGURACIÓ PRINCIPAL I DURADES DINÀMIQUES
# ==============================================================================
TEST_MODE = True  # 👉 True (envia a Telegram) | False (no fa res)

IMPACT_MODE = "vertical"

OUTPUT_VIDEO = "output_pyramid.mp4"
FRAMES_DIR = "temp_frames"
ASSEMBLE_DIR = "all_frames"
TEMP_AUDIO = "temp_impacts.wav"
EVENTS_JSON = "impact_events.json"

FPS = 30
WIDTH = 720
HEIGHT = 1280

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

PYRAMID_LAYERS = 14  # 1.015 blocs
CUBE_SIZE = 0.20
APEX_Z = PYRAMID_LAYERS * CUBE_SIZE  # 2.80 metres

# Durada dinàmica per tall: sense temps morts quan la bola surt de pantalla
CLIPS_CONFIG = [
    {"label": "1 KG",     "mass": 1.0,    "radius": 0.20, "frames": 105}, # 3.5s (ràpid, sense esperar)
    {"label": "10 KG",    "mass": 10.0,   "radius": 0.35, "frames": 135}, # 4.5s (impacte i net)
    {"label": "100 KG",   "mass": 100.0,  "radius": 0.55, "frames": 180}, # 6.0s (destrucció mitjana)
    {"label": "1,000 KG", "mass": 1000.0, "radius": 0.85, "frames": 210}, # 7.0s (apocalipsi de 1.015 blocs)
]

TOTAL_FRAMES = sum(c["frames"] for c in CLIPS_CONFIG)  # 630 fotogrames (21.0s exactes)


def get_clip_and_local_frame(global_f):
    """Mapeja qualsevol fotograma global al seu clip corresponent i fotograma local."""
    accum = 0
    for idx, c in enumerate(CLIPS_CONFIG):
        if global_f <= accum + c["frames"]:
            return idx, (global_f - accum)
        accum += c["frames"]
    return len(CLIPS_CONFIG) - 1, CLIPS_CONFIG[-1]["frames"]


# ==============================================================================
# 🔔 1. SÍNTESI D'ÀUDIO ASMR DE BLOCS DE PEDRA / GUIX (SO SEC I NEUTRE - OPCIÓ B)
# ==============================================================================
def synthesize_audio(duration_sec, output_wav, events):
    print(f"🎵 Sintetitzant àudio mineral de blocs de pedra ({len(events)} impactes)...")
    SAMPLE_RATE = 44100
    n_samples = int(duration_sec * SAMPLE_RATE)
    audio = np.zeros(n_samples, dtype=np.float32)

    for ev in events:
        t_hit = ev["time"]
        sound_type = ev.get("type", "stone")  # "stone" o "heavy_thud"
        intensity = min(1.0, max(0.18, ev.get("intensity", 0.5)))
        start_idx = int(t_hit * SAMPLE_RATE)

        if start_idx >= n_samples:
            continue

        if sound_type == "stone":
            # So sec, sord i mineral de blocs de pedra/guix xocant
            dur = 0.07
            n_note = min(int(dur * SAMPLE_RATE), n_samples - start_idx)
            t = np.linspace(0, dur, n_note, False)
            
            # To fonamental greu-mitjà del bloc (210 - 290 Hz)
            f_fund = 250.0 + np.random.uniform(-40.0, 40.0)

            # 1. Cos sord de pedra (mineral thud)
            body = np.sin(2 * np.pi * f_fund * t) * np.exp(-65.0 * t)
            # 2. Xoc sec de contacte rígid
            click = (
                0.55 * np.sin(2 * np.pi * (f_fund * 3.3) * t) +
                0.25 * np.sin(2 * np.pi * (f_fund * 5.6) * t)
            ) * np.exp(-115.0 * t)
            # 3. Microfricció de guix/roca
            grit = (np.random.rand(n_note) * 2 - 1) * np.exp(-130.0 * t) * 0.18

            wave_stone = (body * 0.70 + click * 0.45 + grit) * intensity
            audio[start_idx : start_idx + n_note] += wave_stone

        else:
            # Impacte principal més sord per a pesos massius (sense metall, to mineral)
            dur = 1.2
            n_note = min(int(dur * SAMPLE_RATE), n_samples - start_idx)
            t = np.linspace(0, dur, n_note, False)
            sub_f = ev.get("sub_freq", 45.0)

            thud = np.sin(2 * np.pi * sub_f * t) * np.exp(-5.0 * t)
            crunch = (np.random.rand(n_note) * 2 - 1) * np.exp(-7.0 * t) * 0.40
            audio[start_idx : start_idx + n_note] += (thud * 0.85 + crunch) * intensity

    # Compressió suau per mantenir la claredat i evitar distorsió
    audio = np.tanh(audio * 1.25)
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
# 🏗️ 2. SIMULACIÓ FÍSICA A BLENDER (DURADES VARIABLES I CONTACTES DE BLOCS)
# ==============================================================================
def simulate_all_clips():
    import bpy

    all_events = []
    print(f"🎬 Iniciant simulació física amb durades dinàmiques (Total: {TOTAL_FRAMES} frames)...")

    accum_frames = 0

    for clip_idx, config in enumerate(CLIPS_CONFIG):
        clip_frames = config["frames"]
        print(f"\n--- 🔨 Simulant Clip #{clip_idx} ({config['label']}) | {clip_frames} frames ({clip_frames/FPS:.1f}s) ---")
        
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene

        scene.frame_start = 1
        scene.frame_end = clip_frames
        scene.render.fps = FPS

        if not scene.rigidbody_world:
            bpy.ops.rigidbody.world_add()
        scene.rigidbody_world.point_cache.frame_start = 1
        scene.rigidbody_world.point_cache.frame_end = clip_frames
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

        # 3. La bola amb descentrament mínim (7 cm)
        ball_r = config["radius"]
        drop_z = APEX_Z + 2.8 + ball_r
        ball_start_pos = (0.07, 0.03, drop_z)

        bpy.ops.mesh.primitive_uv_sphere_add(radius=ball_r, segments=32, ring_count=16, location=ball_start_pos)
        ball = bpy.context.active_object
        ball.name = f"Ball_{clip_idx}"
        ball.data.materials.append(mat_chrome)
        bpy.ops.object.shade_smooth()

        bpy.ops.rigidbody.object_add()
        ball.rigid_body.type = 'ACTIVE'
        ball.rigid_body.collision_shape = 'SPHERE'
        ball.rigid_body.mass = config["mass"]
        ball.rigid_body.friction = 0.35

        # 4. Càmera i llum
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

        # 5. Simulació física
        clip_blend = f"clip_{clip_idx}.blend"
        bpy.ops.wm.save_as_mainfile(filepath=clip_blend)
        try:
            bpy.ops.ptcache.bake_all(bake=True)
        except Exception:
            pass

        init_states = {cube.name: (cube.location.copy(), cube.rotation_euler.copy()) for cube in active_cubes}
        has_moved = {cube.name: False for cube in active_cubes}
        prev_cube_pos = {cube.name: cube.location.copy() for cube in active_cubes}

        prev_ball_pos = np.array(ball_start_pos, dtype=np.float32)
        prev_ball_vel = np.zeros(3, dtype=np.float32)

        main_ball_impact = False

        for f in range(1, clip_frames + 1):
            scene.frame_set(f)
            t_global = (accum_frames + (f - 1)) / FPS

            cur_pos = np.array(ball.matrix_world.translation, dtype=np.float32)
            cur_vel = (cur_pos - prev_ball_pos) * FPS
            expected_vel = prev_ball_vel + np.array([0.0, 0.0, -9.81 / FPS], dtype=np.float32)
            ball_accel_dev = float(np.linalg.norm(cur_vel - expected_vel))

            ball.location = cur_pos
            ball.rotation_euler = ball.matrix_world.to_euler()
            ball.keyframe_insert(data_path="location", frame=f)
            ball.keyframe_insert(data_path="rotation_euler", frame=f)

            # Detecció de blocs moguts i contactes
            newly_moved = 0
            moving_bounces = 0

            for cube in active_cubes:
                cur_loc = cube.matrix_world.translation.copy()
                cur_rot = cube.matrix_world.to_euler()

                if not has_moved[cube.name]:
                    diff = (cur_loc - init_states[cube.name][0]).length
                    if diff > 0.035:
                        has_moved[cube.name] = True
                        newly_moved += 1
                        if f > 1:
                            cube.location = init_states[cube.name][0]
                            cube.rotation_euler = init_states[cube.name][1]
                            cube.keyframe_insert(data_path="location", frame=f - 1)
                            cube.keyframe_insert(data_path="rotation_euler", frame=f - 1)
                else:
                    # Bloc que ja es movia: comprovar si xoca fort contra terra o veí
                    cube_spd = (cur_loc - prev_cube_pos[cube.name]).length * FPS
                    if cube_spd > 2.2 and cur_loc.z < 2.5:
                        moving_bounces += 1

                if has_moved[cube.name]:
                    cube.location = cur_loc
                    cube.rotation_euler = cur_rot
                    cube.keyframe_insert(data_path="location", frame=f)
                    cube.keyframe_insert(data_path="rotation_euler", frame=f)

                prev_cube_pos[cube.name] = cur_loc

            # --- SÍNTESI DE CONTACTES (BOLA AMB BLOC + BLOCS ENTRE ELLS) ---
            ball_bottom_z = cur_pos[2] - ball_r
            is_at_pyramid = ball_bottom_z <= (APEX_Z + 0.06)

            # 1. La bola toca un bloc (fa el so corresponent)
            if is_at_pyramid and ball_accel_dev > 1.4:
                all_events.append({
                    "time": t_global,
                    "type": "stone",
                    "intensity": min(1.0, 0.45 + config["mass"] * 0.0005)
                })
                if not main_ball_impact and config["mass"] >= 10.0:
                    main_ball_impact = True
                    all_events.append({
                        "time": t_global,
                        "type": "heavy_thud",
                        "intensity": 0.85,
                        "sub_freq": 55.0 if config["mass"] == 10.0 else 38.0
                    })

            # 2. Els blocs es mouen i xoquen entre ells o amb el terra
            # Si es mouen 1-4 blocs, tocs individuals. Si cau una allau (1000kg), ràfega densa
            if newly_moved > 0:
                taps_to_add = min(8, max(1, newly_moved // 3))
                for tap_i in range(taps_to_add):
                    jitter = (tap_i / taps_to_add) * (1.0 / FPS)
                    all_events.append({
                        "time": t_global + jitter,
                        "type": "stone",
                        "intensity": min(0.9, 0.35 + (newly_moved / 40.0) * 0.45)
                    })

            if moving_bounces > 4:
                # Esglaons i blocs rodolant pel terra
                all_events.append({
                    "time": t_global + 0.015,
                    "type": "stone",
                    "intensity": min(0.8, 0.25 + (moving_bounces / 30.0) * 0.4)
                })

            prev_ball_pos = cur_pos
            prev_ball_vel = cur_vel

        accum_frames += clip_frames
        bpy.ops.rigidbody.world_remove()
        bpy.ops.wm.save_as_mainfile(filepath=clip_blend, compress=True)
        print(f"✅ Clip #{clip_idx} finalitzat a {clip_blend}")

    with open(EVENTS_JSON, "w") as jf:
        json.dump(all_events, jf)
    print("✅ Esdeveniments sonors de blocs sincronitzats!")


# ==============================================================================
# 🎨 3. RENDERITZAT EN PARAL·LEL (ADAPTAT A LES DURADES DINÀMIQUES)
# ==============================================================================
def render_chunk(chunk_idx, total_chunks):
    import bpy

    frames_per_chunk = math.ceil(TOTAL_FRAMES / total_chunks)
    start_global = chunk_idx * frames_per_chunk + 1
    end_global = min(TOTAL_FRAMES, (chunk_idx + 1) * frames_per_chunk)

    print(f"🎬 Runner #{chunk_idx}: processant fotogrames globals {start_global} a {end_global} (de {TOTAL_FRAMES})...")
    os.makedirs(FRAMES_DIR, exist_ok=True)

    current_loaded_clip = None

    for global_f in range(start_global, end_global + 1):
        clip_idx, local_f = get_clip_and_local_frame(global_f)
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

    print("📲 TEST_MODE=True: Enviant vídeo dinàmic a Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    caption = (
        "💥 <b>BOUNCELAB 3D - PIRÀMIDE (DURADES DINÀMIQUES I SO MINERAL)</b>\n\n"
        "⚡ <b>Ritme àgil:</b> Clips curts sense temps morts (21s totals)\n"
        "🧱 <b>Àudio:</b> Xoc sec i neutre de blocs de pedra/guix entre ells\n"
        "📐 <b>Textos:</b> Sincronitzats automàticament amb la nova durada"
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
            print("✅ Vídeo enviat a Telegram amb èxit!")
        else:
            print(f"❌ Error Telegram ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ Excepció Telegram: {e}")


# ==============================================================================
# 🎬 5. ACOBLAMENT FINAL I TEXTOS FFMPEG DINÀMICS
# ==============================================================================
def assemble_final_video():
    print(f"⚡ Unint els {TOTAL_FRAMES} fotogrames i sintetitzant àudio ({TOTAL_FRAMES/FPS:.1f}s)...")
    duration = TOTAL_FRAMES / FPS

    events = []
    if os.path.exists(EVENTS_JSON):
        with open(EVENTS_JSON, "r") as jf:
            events = json.load(jf)

    synthesize_audio(duration, TEMP_AUDIO, events)

    # Tipografia Ubuntu
    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"
    ]
    font_path = next((f for f in font_candidates if os.path.exists(f)), None)
    font_opt = f":fontfile='{font_path}'" if font_path else ":font='sans'"

    # Càlcul dinàmic dels intervals de temps per als rètols
    drawtext_filters = []
    curr_t = 0.0
    for config in CLIPS_CONFIG:
        clip_dur = config["frames"] / FPS
        t0 = curr_t
        t1 = curr_t + clip_dur
        curr_t = t1
        label = config["label"]
        filt = (
            f"drawtext=text='{label}'{font_opt}:fontsize=64:fontcolor=white:"
            f"box=1:boxcolor=black@0.65:boxborderw=20:"
            f"x=(w-text_w)/2:y=160:"
            f"enable='between(t\\,{t0:.2f}\\,{t1:.2f})'"
        )
        drawtext_filters.append(filt)

    vf_chain = ",".join(drawtext_filters)

    frame_pattern = os.path.join(ASSEMBLE_DIR, "frame_%04d.png")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", frame_pattern,
            "-i", TEMP_AUDIO,
            "-vf", vf_chain,
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
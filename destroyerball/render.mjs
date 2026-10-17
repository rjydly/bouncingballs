import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WIDTH = 1080;
const HEIGHT = 1920;
const FPS = 60;
const RAW_VIDEO = path.join(__dirname, 'temp_video.mp4');
const AUDIO_FILE = path.join(__dirname, 'temp_audio.wav');
const FINAL_VIDEO = path.join(__dirname, 'destroyerball_output.mp4');

const HTML_CONTENT = `
<!DOCTYPE html>
<html>
<head>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { background: #000000; display: flex; justify-content: center; align-items: center; width: 1080px; height: 1920px; overflow: hidden; }
    canvas { width: 1080px; height: 1920px; background: #000000; }
  </style>
</head>
<body>
  <canvas id="gameCanvas" width="1080" height="1920"></canvas>
  <script>
    const canvas = document.getElementById('gameCanvas');
    const ctx = canvas.getContext('2d');
    window.audioEvents = [];
    window.isFinished = false;

    let simTime = 0;
    const dt = 1 / 60;

    // 36 columnes omplen exactament 1080px (36 * 30px)
    const COLS = 36;
    const ROWS = 48;
    const CELL_W = 30;
    const CELL_H = 26;
    const BRICK_W = 28;
    const BRICK_H = 24;

    const grid = Array.from({ length: ROWS }, () => Array(COLS).fill(0));
    const chamberTop = 2;
    const chamberBottom = 40;

    // 1. Mur gris exterior i cambra de vermells
    for (let r = chamberTop; r <= chamberBottom; r++) {
      for (let c = 0; c < COLS; c++) {
        if (r === chamberTop || r === chamberBottom || c === 0 || c === COLS - 1) {
          grid[r][c] = 1; // Mur gris
        } else {
          grid[r][c] = 2; // Vermell
        }
      }
    }

    // 2. Generar camí del túnel d'1 sol bloc (Ortogonal: Amunt -> Costat -> Amunt)
    const mouthCol = Math.floor(Math.random() * (COLS - 16)) + 8;
    const turn1Row = chamberBottom - (Math.floor(Math.random() * 5) + 7);
    const sideDir = (mouthCol > COLS / 2) ? -1 : 1;
    const turnLength = Math.floor(Math.random() * 5) + 6;
    const turn2Col = Math.max(3, Math.min(COLS - 4, mouthCol + sideDir * turnLength));
    const targetEndRow = turn1Row - (Math.floor(Math.random() * 6) + 8);

    const pathCells = [];

    // Tram 1: Pujada
    for (let r = chamberBottom; r >= turn1Row; r--) pathCells.push({ r, c: mouthCol });
    // Tram 2: Lateral
    for (let c = mouthCol + sideDir; sideDir > 0 ? c <= turn2Col : c >= turn2Col; c += sideDir) pathCells.push({ r: turn1Row, c });
    // Tram 3: Pujada final a l'interior vermell
    for (let r = turn1Row - 1; r >= targetEndRow; r--) pathCells.push({ r, c: turn2Col });

    const pathSet = new Set(pathCells.map(p => p.r + ',' + p.c));
    const lastCell = pathCells[pathCells.length - 1];

    // Buidar el passadís i blindar-lo amb blocs grisos
    for (const p of pathCells) {
      grid[p.r][p.c] = 0;
      for (let dr = -1; dr <= 1; dr++) {
        for (let dc = -1; dc <= 1; dc++) {
          const nr = p.r + dr;
          const nc = p.c + dc;
          if (nr < chamberTop || nr > chamberBottom || nc < 0 || nc >= COLS) continue;
          if (p === lastCell && dr === -1 && dc === 0) continue; // Sortida oberta
          if (!pathSet.has(nr + ',' + nc)) grid[nr][nc] = 1;
        }
      }
    }

    // Waypoints per al trànsit pel tub (accelera i no s'encalla mai)
    const waypoints = [
      { x: mouthCol * CELL_W + CELL_W / 2, y: chamberBottom * CELL_H + CELL_H / 2 },
      { x: mouthCol * CELL_W + CELL_W / 2, y: turn1Row * CELL_H + CELL_H / 2 },
      { x: turn2Col * CELL_W + CELL_W / 2, y: turn1Row * CELL_H + CELL_H / 2 },
      { x: turn2Col * CELL_W + CELL_W / 2, y: (targetEndRow - 1) * CELL_H }
    ];

    const entranceX = waypoints[0].x;
    const entranceY = waypoints[0].y;

    const bricks = [];
    let remainingRed = 0;

    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        if (grid[r][c] > 0) {
          const type = grid[r][c] === 1 ? 'grey' : 'red';
          if (type === 'red') remainingRed++;
          bricks.push({
            r, c,
            x: c * CELL_W + 1,
            y: r * CELL_H + 1,
            w: BRICK_W,
            h: BRICK_H,
            type,
            alive: true
          });
        }
      }
    }

    const paddle = {
      x: 540,
      y: 1720,
      w: 180,
      h: 22,
      targetX: 540,
      speed: 1350
    };

    let balls = [{
      x: 540,
      y: 1660,
      vx: (Math.random() - 0.5) * 320,
      vy: -1050,
      radius: 8.5,
      inTunnel: false,
      wpIndex: 0,
      trail: []
    }];

    let bouncesDone = 0;
    const requiredBounces = Math.floor(Math.random() * 3) + 1;

    const powerups = [];
    const particles = [];

    window.advanceFrame = function() {
      simTime += dt;

      // 1. IA de la Barra
      let trackedBall = balls[0];
      for (const b of balls) {
        if (!b.inTunnel && b.y > trackedBall.y) trackedBall = b;
      }

      if (trackedBall) {
        if (bouncesDone < requiredBounces) {
          const missOffset = (bouncesDone % 2 === 0 ? 70 : -70);
          paddle.targetX = trackedBall.x + missOffset;
        } else {
          // Tir precís cap a la boca del tub
          const dx = entranceX - trackedBall.x;
          const dy = entranceY - trackedBall.y;
          const targetAngle = Math.atan2(dx, -dy);
          const hitFactor = targetAngle / (Math.PI / 3.4);
          paddle.targetX = trackedBall.x - hitFactor * (paddle.w / 2);
        }
      }

      paddle.targetX = Math.max(paddle.w / 2, Math.min(1080 - paddle.w / 2, paddle.targetX));
      const pDiff = paddle.targetX - paddle.x;
      paddle.x += Math.sign(pDiff) * Math.min(Math.abs(pDiff), paddle.speed * dt);

      // 2. FÍSICA I MOVIMENT DE LES BOLES
      const subSteps = 3;
      const subDt = dt / subSteps;

      for (let s = 0; s < subSteps; s++) {
        for (let bi = balls.length - 1; bi >= 0; bi--) {
          const ball = balls[bi];

          // MODE TUB PNEUMÀTIC (TRÀNSIT RÀPID PER DINS EL PASSADÍS)
          if (ball.inTunnel) {
            const targetWP = waypoints[ball.wpIndex];
            const tdx = targetWP.x - ball.x;
            const tdy = targetWP.y - ball.y;
            const dist = Math.hypot(tdx, tdy);
            const tubeSpeed = 1450; // Gran velocitat d'acceleració

            if (dist < tubeSpeed * subDt) {
              ball.x = targetWP.x;
              ball.y = targetWP.y;
              ball.wpIndex++;
              window.audioEvents.push({ time: simTime, freq: 440 + ball.wpIndex * 80 });

              // En arribar al final del túnel: SURT DISPARADA A DESTROSSAR ELS VERMELLS
              if (ball.wpIndex >= waypoints.length) {
                ball.inTunnel = false;
                ball.vx = (Math.random() - 0.5) * 650;
                ball.vy = -1200; // Llançament fort cap amunt
                window.audioEvents.push({ time: simTime, freq: 880 });
              }
            } else {
              ball.x += (tdx / dist) * tubeSpeed * subDt;
              ball.y += (tdy / dist) * tubeSpeed * subDt;
            }
            continue; // Evita xocs mentre viatja pel tub
          }

          // MODE FÍSIC NORMAL
          ball.x += ball.vx * subDt;
          ball.y += ball.vy * subDt;

          // Conservació estricta de velocitat (mai no es frena)
          const currentSpeed = Math.hypot(ball.vx, ball.vy);
          const TARGET_SPEED = 1100;
          if (currentSpeed < TARGET_SPEED) {
            ball.vx = (ball.vx / currentSpeed) * TARGET_SPEED;
            ball.vy = (ball.vy / currentSpeed) * TARGET_SPEED;
          }

          // Detecció d'entrada al tub
          if (
            ball.vy < 0 &&
            Math.abs(ball.x - entranceX) < 18 &&
            Math.abs(ball.y - entranceY) < 22
          ) {
            ball.inTunnel = true;
            ball.wpIndex = 1;
            ball.x = entranceX;
            ball.y = entranceY;
            window.audioEvents.push({ time: simTime, freq: 350 });
            continue;
          }

          // Parets exteriors de la pantalla
          if (ball.x - ball.radius <= 0) { ball.x = ball.radius; ball.vx = Math.abs(ball.vx); window.audioEvents.push({ time: simTime, freq: 160 }); }
          else if (ball.x + ball.radius >= 1080) { ball.x = 1080 - ball.radius; ball.vx = -Math.abs(ball.vx); window.audioEvents.push({ time: simTime, freq: 160 }); }

          // Rebot a la barra
          if (
            ball.y + ball.radius >= paddle.y - paddle.h / 2 &&
            ball.y - ball.radius <= paddle.y + paddle.h / 2 &&
            ball.x >= paddle.x - paddle.w / 2 &&
            ball.x <= paddle.x + paddle.w / 2 &&
            ball.vy > 0
          ) {
            bouncesDone++;
            const hitRatio = (ball.x - paddle.x) / (paddle.w / 2);
            const spd = Math.hypot(ball.vx, ball.vy);
            const angle = hitRatio * (Math.PI / 3.1);
            ball.vx = spd * Math.sin(angle);
            ball.vy = -Math.abs(spd * Math.cos(angle));
            ball.y = paddle.y - paddle.h / 2 - ball.radius;
            window.audioEvents.push({ time: simTime, freq: 120 });
          }

          if (ball.y + ball.radius >= 1880) {
            ball.vy = -Math.abs(ball.vy);
          }

          // Col·lisions amb els maons
          const gridCol = Math.floor(ball.x / CELL_W);
          const gridRow = Math.floor(ball.y / CELL_H);

          for (let ro = -1; ro <= 1; ro++) {
            for (let co = -1; co <= 1; co++) {
              const r = gridRow + ro;
              const c = gridCol + co;
              if (r < 0 || r >= ROWS || c < 0 || c >= COLS) continue;

              const brick = bricks.find(b => b.r === r && b.c === c && b.alive);
              if (!brick) continue;

              if (
                ball.x + ball.radius > brick.x &&
                ball.x - ball.radius < brick.x + brick.w &&
                ball.y + ball.radius > brick.y &&
                ball.y - ball.radius < brick.y + brick.h
              ) {
                const prevX = ball.x - ball.vx * subDt;
                if (prevX + ball.radius <= brick.x) {
                  ball.vx = -Math.abs(ball.vx);
                  ball.x = brick.x - ball.radius;
                } else if (prevX - ball.radius >= brick.x + brick.w) {
                  ball.vx = Math.abs(ball.vx);
                  ball.x = brick.x + brick.w + ball.radius;
                } else {
                  ball.vy = -ball.vy;
                }

                if (brick.type === 'red') {
                  brick.alive = false;
                  remainingRed--;
                  window.audioEvents.push({ time: simTime, freq: 380 + Math.random() * 90 });

                  for (let p = 0; p < 5; p++) {
                    const ang = Math.random() * Math.PI * 2;
                    particles.push({
                      x: brick.x + brick.w / 2, y: brick.y + brick.h / 2,
                      vx: Math.cos(ang) * (Math.random() * 200 + 40),
                      vy: Math.sin(ang) * (Math.random() * 200 + 40),
                      life: 0.25
                    });
                  }

                  // 14% de probabilitat de boost per provocar allau de boles
                  if (Math.random() < 0.14) {
                    powerups.push({
                      x: brick.x + brick.w / 2,
                      y: brick.y + brick.h / 2,
                      vy: 380,
                      type: Math.random() < 0.7 ? 'MULTIBALL' : 'BIG_PADDLE'
                    });
                  }
                } else {
                  window.audioEvents.push({ time: simTime, freq: 180 });
                }
                break;
              }
            }
          }
        }
      }

      // Esteles
      for (const b of balls) {
        b.trail.push({ x: b.x, y: b.y });
        if (b.trail.length > 8) b.trail.shift();
      }

      // Boosts
      for (let i = powerups.length - 1; i >= 0; i--) {
        const p = powerups[i];
        p.y += p.vy * dt;

        if (
          p.y >= paddle.y - paddle.h / 2 &&
          p.y <= paddle.y + paddle.h / 2 + 20 &&
          p.x >= paddle.x - paddle.w / 2 &&
          p.x <= paddle.x + paddle.w / 2
        ) {
          window.audioEvents.push({ time: simTime, freq: 800 });
          if (p.type === 'MULTIBALL' && balls.length < 24) {
            const total = balls.length;
            for (let b = 0; b < total; b++) {
              const src = balls[b];
              if (src.inTunnel) continue;
              balls.push({
                x: src.x, y: src.y,
                vx: -src.vx + (Math.random() - 0.5) * 200,
                vy: src.vy + (Math.random() - 0.5) * 200,
                radius: src.radius,
                inTunnel: false,
                wpIndex: 0,
                trail: []
              });
            }
          } else if (p.type === 'BIG_PADDLE') {
            paddle.w = Math.min(320, paddle.w + 45);
          }
          powerups.splice(i, 1);
          continue;
        }
        if (p.y > 1920) powerups.splice(i, 1);
      }

      for (let i = particles.length - 1; i >= 0; i--) {
        const pt = particles[i];
        pt.x += pt.vx * dt;
        pt.y += pt.vy * dt;
        pt.life -= dt;
        if (pt.life <= 0) particles.splice(i, 1);
      }

      // Finalització: quan es netegen els vermells o temps complet
      if (remainingRed <= 0 || (simTime >= 35 && remainingRed < 40) || simTime >= 45) {
        window.isFinished = true;
      }

      render();
    };

    function render() {
      ctx.fillStyle = '#000000';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      for (let i = 0; i < bricks.length; i++) {
        const b = bricks[i];
        if (!b.alive) continue;

        if (b.type === 'grey') {
          ctx.fillStyle = '#6b7280';
          ctx.fillRect(b.x, b.y, b.w, b.h);
        } else {
          ctx.fillStyle = '#ff2440';
          ctx.fillRect(b.x, b.y, b.w, b.h);
        }
      }

      ctx.fillStyle = '#ff2440';
      for (const p of particles) {
        ctx.fillRect(p.x, p.y, 4, 4);
      }

      for (const p of powerups) {
        ctx.save();
        ctx.fillStyle = p.type === 'MULTIBALL' ? '#ff0055' : '#00f0ff';
        ctx.shadowColor = ctx.fillStyle;
        ctx.shadowBlur = 12;
        ctx.beginPath();
        ctx.roundRect(p.x - 13, p.y - 13, 26, 26, 13);
        ctx.fill();
        ctx.restore();
      }

      // Barra
      ctx.save();
      ctx.fillStyle = '#ffffff';
      ctx.shadowColor = '#00f0ff';
      ctx.shadowBlur = 16;
      ctx.beginPath();
      ctx.roundRect(paddle.x - paddle.w / 2, paddle.y - paddle.h / 2, paddle.w, paddle.h, 10);
      ctx.fill();
      ctx.restore();

      // Pilotes
      for (const b of balls) {
        for (let i = 0; i < b.trail.length; i++) {
          const t = b.trail[i];
          ctx.beginPath();
          ctx.arc(t.x, t.y, b.radius * 0.7, 0, Math.PI * 2);
          ctx.fillStyle = '#ffffff';
          ctx.globalAlpha = (i / b.trail.length) * 0.35;
          ctx.fill();
        }
        ctx.globalAlpha = 1.0;

        ctx.save();
        ctx.fillStyle = '#ffffff';
        ctx.shadowColor = '#ffffff';
        ctx.shadowBlur = 14;
        ctx.beginPath();
        ctx.arc(b.x, b.y, b.radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }
    }
  </script>
</body>
</html>
`;

function generateWavTrack(audioEvents, duration) {
  const sampleRate = 44100;
  const totalSamples = Math.ceil(duration * sampleRate);
  const buffer = new Float32Array(totalSamples);

  for (const ev of audioEvents) {
    const startSample = Math.floor(ev.time * sampleRate);
    const popLength = Math.floor(0.06 * sampleRate);
    const freq = ev.freq || 250;

    for (let i = 0; i < popLength; i++) {
      const idx = startSample + i;
      if (idx >= totalSamples) break;
      const t = i / sampleRate;
      buffer[idx] += Math.sin(2 * Math.PI * freq * t) * Math.exp(-t * 55) * 0.35;
    }
  }

  const wav = Buffer.alloc(44 + totalSamples * 2);
  wav.write('RIFF', 0);
  wav.writeUInt32LE(36 + totalSamples * 2, 4);
  wav.write('WAVE', 8);
  wav.write('fmt ', 12);
  wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20);
  wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(sampleRate, 24);
  wav.writeUInt32LE(sampleRate * 2, 28);
  wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34);
  wav.write('data', 36);
  wav.writeUInt32LE(totalSamples * 2, 40);

  let offset = 44;
  for (let i = 0; i < totalSamples; i++) {
    const s = Math.max(-1, Math.min(1, buffer[i]));
    wav.writeInt16LE(s < 0 ? s * 0x8000 : s * 0x7FFF, offset);
    offset += 2;
  }
  fs.writeFileSync(AUDIO_FILE, wav);
}

async function start() {
  console.log('🚀 Renderitzant Destroyer Ball (Tube Accelerator Mode)...');
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT } });

  await page.setContent(HTML_CONTENT);

  const ffmpeg = spawn('ffmpeg', [
    '-y', '-f', 'image2pipe', '-vcodec', 'mjpeg', '-r', `${FPS}`,
    '-i', '-', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'ultrafast',
    RAW_VIDEO
  ]);

  let frame = 0, isFinished = false;
  while (!isFinished) {
    const data = await page.evaluate(() => {
      window.advanceFrame();
      const canvas = document.getElementById('gameCanvas');
      return {
        base64: canvas.toDataURL('image/jpeg', 0.8).split(',')[1],
        finished: window.isFinished
      };
    });

    ffmpeg.stdin.write(Buffer.from(data.base64, 'base64'));
    isFinished = data.finished;
    frame++;

    if (frame % 300 === 0) {
      console.log(`Renderitzats ${frame} fotogrames (~${(frame / FPS).toFixed(1)}s)...`);
    }
  }

  ffmpeg.stdin.end();
  await new Promise(r => ffmpeg.on('close', r));

  const audioEvents = await page.evaluate(() => window.audioEvents);
  await browser.close();

  console.log('🎵 Generant so...');
  generateWavTrack(audioEvents, frame / FPS);

  console.log('📦 Generant MP4 final...');
  await new Promise((res, rej) => {
    const mux = spawn('ffmpeg', [
      '-y', '-i', RAW_VIDEO, '-i', AUDIO_FILE, '-c:v', 'copy', '-c:a', 'aac', '-shortest', FINAL_VIDEO
    ]);
    mux.on('close', c => c === 0 ? res() : rej(new Error('Error en muxing')));
  });

  if (fs.existsSync(RAW_VIDEO)) fs.unlinkSync(RAW_VIDEO);
  if (fs.existsSync(AUDIO_FILE)) fs.unlinkSync(AUDIO_FILE);

  await sendTelegram(FINAL_VIDEO);
}

async function sendTelegram(filePath) {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;
  if (!token || !chatId) return console.log('⚠️ Telegram credentials not found.');

  console.log('📤 Enviant a Telegram...');
  const formData = new FormData();
  formData.append('chat_id', chatId);
  formData.append('caption', 'Destroyer Ball Daily Video');
  formData.append('video', new Blob([fs.readFileSync(filePath)], { type: 'video/mp4' }), 'video.mp4');

  const res = await fetch(`https://api.telegram.org/bot${token}/sendVideo`, { method: 'POST', body: formData });
  const json = await res.json();
  if (json.ok) console.log('✅ Enviat a Telegram!');
  else console.error('❌ Error Telegram:', json);
}

start();

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

    // Dimensions de la graella de blocs
    const COLS = 32;
    const ROWS = 38;
    const BRICK_W = 28;
    const BRICK_H = 22;
    const GAP = 2;
    const GRID_X = (1080 - (COLS * (BRICK_W + GAP))) / 2;
    const GRID_Y = 160;

    // Matriu de blocs: 0 = Buit, 1 = Gris (indestructible), 2 = Vermell (destruïble)
    const grid = Array.from({ length: ROWS }, () => Array(COLS).fill(0));

    // 1. GENERACIÓ PROCEDURAL DEL LABERINT I EMUT
    const chamberTop = 2;
    const chamberBottom = 30;
    const chamberLeft = 2;
    const chamberRight = COLS - 3;

    // Omplir cambra interior de vermells
    for (let r = chamberTop; r <= chamberBottom; r++) {
      for (let c = chamberLeft; c <= chamberRight; c++) {
        if (r === chamberTop || r === chamberBottom || c === chamberLeft || c === chamberRight) {
          grid[r][c] = 1; // Murs grisos exteriors
        } else {
          grid[r][c] = 2; // Interior vermell
        }
      }
    }

    // Crear passadís / embut aleatori
    const mouthCol = Math.floor(Math.random() * (chamberRight - chamberLeft - 8)) + chamberLeft + 4;
    const tunnelWidth = 2;
    const funnelBottomRow = 35; // sobresurt cap avall en direcció a la barra

    // Buidar obertura al mur inferior de la cambra
    for (let w = 0; w < tunnelWidth; w++) {
      grid[chamberBottom][mouthCol + w] = 0;
    }

    // Murs del túnel cap avall (embut exterior)
    for (let r = chamberBottom; r <= funnelBottomRow; r++) {
      grid[r][mouthCol - 1] = 1;
      grid[r][mouthCol + tunnelWidth] = 1;
      for (let w = 0; w < tunnelWidth; w++) grid[r][mouthCol + w] = 0;
    }
    // Boca d'entrada eixamplada
    grid[funnelBottomRow][mouthCol - 2] = 1;
    grid[funnelBottomRow][mouthCol + tunnelWidth + 1] = 1;

    // Túnel interior cap al cor dels blocs vermells (amb gir aleatori)
    const bendDirection = Math.random() < 0.5 ? -1 : 1;
    const bendAmount = Math.floor(Math.random() * 5) + 3;
    let currC = mouthCol;
    const targetInsideRow = Math.floor(Math.random() * 8) + 12;

    for (let r = chamberBottom - 1; r >= targetInsideRow; r--) {
      // Aplicar possible desviació / recolzament
      if (r < chamberBottom - 4 && r > targetInsideRow + 4 && Math.random() < 0.6) {
        currC = Math.max(chamberLeft + 2, Math.min(chamberRight - tunnelWidth - 2, currC + bendDirection));
      }
      // Paredes grises protectores del túnel interior
      grid[r][currC - 1] = 1;
      grid[r][currC + tunnelWidth] = 1;
      for (let w = 0; w < tunnelWidth; w++) grid[r][currC + w] = 0;
    }

    // Obertura final a l'interior dels vermells
    for (let w = 0; w < tunnelWidth; w++) {
      grid[targetInsideRow - 1][currC + w] = 0;
    }

    // Convertir a llista de blocs renderitzables
    const bricks = [];
    let remainingRed = 0;

    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        if (grid[r][c] > 0) {
          const type = grid[r][c] === 1 ? 'grey' : 'red';
          if (type === 'red') remainingRed++;
          bricks.push({
            r, c,
            x: GRID_X + c * (BRICK_W + GAP),
            y: GRID_Y + r * (BRICK_H + GAP),
            w: BRICK_W,
            h: BRICK_H,
            type: type,
            alive: true
          });
        }
      }
    }

    // Coordenada de la boca de l'embut (Objectiu de la barra)
    const funnelEntranceX = GRID_X + (mouthCol + tunnelWidth / 2) * (BRICK_W + GAP);
    const funnelEntranceY = GRID_Y + funnelBottomRow * (BRICK_H + GAP);

    // Barra inferior
    const paddle = {
      x: 540,
      y: 1740,
      w: 180,
      h: 22,
      targetX: 540,
      speed: 1200
    };

    // Pilotes (mida petita)
    let balls = [{
      x: 540,
      y: 1680,
      vx: (Math.random() - 0.5) * 400,
      vy: -980,
      radius: 9,
      trail: []
    }];

    // IA Humana: defineix quants rebots farà abans d'encertar (1 a 3)
    let bouncesDone = 0;
    const requiredBounces = Math.floor(Math.random() * 3) + 1;

    const powerups = [];
    const particles = [];

    window.advanceFrame = function() {
      simTime += dt;

      // 1. Control intel·ligent / humà de la barra
      let trackedBall = balls[0];
      for (const b of balls) {
        if (b.y > trackedBall.y) trackedBall = b;
      }

      if (trackedBall) {
        if (bouncesDone < requiredBounces) {
          // Desplaçament intencionat per rebotar fora de l'embut
          const failOffset = (bouncesDone % 2 === 0 ? 65 : -65);
          paddle.targetX = trackedBall.x + failOffset;
        } else {
          // Càlcul d'angle precís cap a la boca de l'embut
          const dxToMouth = funnelEntranceX - trackedBall.x;
          const correction = Math.max(-75, Math.min(75, -dxToMouth * 0.16));
          paddle.targetX = trackedBall.x + correction;
        }
      }

      // Desplaçament fluid de la barra
      paddle.targetX = Math.max(paddle.w / 2 + 30, Math.min(1080 - paddle.w / 2 - 30, paddle.targetX));
      const pDiff = paddle.targetX - paddle.x;
      paddle.x += Math.sign(pDiff) * Math.min(Math.abs(pDiff), paddle.speed * dt);

      // 2. Física de les boles (2 passos de substepping)
      const subSteps = 2;
      const subDt = dt / subSteps;

      for (let s = 0; s < subSteps; s++) {
        for (let bi = balls.length - 1; bi >= 0; bi--) {
          const ball = balls[bi];
          ball.x += ball.vx * subDt;
          ball.y += ball.vy * subDt;

          // Parets laterals i sostre
          if (ball.x - ball.radius <= 30) { ball.x = 30 + ball.radius; ball.vx = Math.abs(ball.vx); window.audioEvents.push({ time: simTime, freq: 160 }); }
          else if (ball.x + ball.radius >= 1050) { ball.x = 1050 - ball.radius; ball.vx = -Math.abs(ball.vx); window.audioEvents.push({ time: simTime, freq: 160 }); }
          if (ball.y - ball.radius <= 30) { ball.y = 30 + ball.radius; ball.vy = Math.abs(ball.vy); window.audioEvents.push({ time: simTime, freq: 160 }); }

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
            const speed = Math.sqrt(ball.vx * ball.vx + ball.vy * ball.vy);
            const angle = hitRatio * (Math.PI / 3.2);
            ball.vx = speed * Math.sin(angle);
            ball.vy = -Math.abs(speed * Math.cos(angle));
            ball.y = paddle.y - paddle.h / 2 - ball.radius;
            window.audioEvents.push({ time: simTime, freq: 120 });
          }

          // Seguretat inferior
          if (ball.y + ball.radius >= 1860) {
            ball.vy = -Math.abs(ball.vy);
          }

          // Col·lisions ràpides amb la graella de maons
          const gridCol = Math.floor((ball.x - GRID_X) / (BRICK_W + GAP));
          const gridRow = Math.floor((ball.y - GRID_Y) / (BRICK_H + GAP));

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
                // Rebot
                const prevX = ball.x - ball.vx * subDt;
                if (prevX + ball.radius <= brick.x || prevX - ball.radius >= brick.x + brick.w) {
                  ball.vx = -ball.vx;
                } else {
                  ball.vy = -ball.vy;
                }

                if (brick.type === 'red') {
                  brick.alive = false;
                  remainingRed--;
                  window.audioEvents.push({ time: simTime, freq: 360 + (Math.random() * 80) });

                  // Partícules vermelles
                  for (let p = 0; p < 6; p++) {
                    const ang = Math.random() * Math.PI * 2;
                    particles.push({
                      x: brick.x + brick.w / 2, y: brick.y + brick.h / 2,
                      vx: Math.cos(ang) * (Math.random() * 200 + 40),
                      vy: Math.sin(ang) * (Math.random() * 200 + 40),
                      life: 0.3
                    });
                  }

                  // 10% probabilitat de boost
                  if (Math.random() < 0.10) {
                    powerups.push({
                      x: brick.x + brick.w / 2,
                      y: brick.y + brick.h / 2,
                      vy: 360,
                      type: Math.random() < 0.65 ? 'MULTIBALL' : 'BIG_PADDLE'
                    });
                  }
                } else {
                  // Bloc gris indestructible
                  window.audioEvents.push({ time: simTime, freq: 200 });
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
        if (b.trail.length > 7) b.trail.shift();
      }

      // 3. Gestió de Boosts
      for (let i = powerups.length - 1; i >= 0; i--) {
        const p = powerups[i];
        p.y += p.vy * dt;

        if (
          p.y >= paddle.y - paddle.h / 2 &&
          p.y <= paddle.y + paddle.h / 2 + 18 &&
          p.x >= paddle.x - paddle.w / 2 &&
          p.x <= paddle.x + paddle.w / 2
        ) {
          window.audioEvents.push({ time: simTime, freq: 750 });
          if (p.type === 'MULTIBALL' && balls.length < 24) {
            const currentTotal = balls.length;
            for (let b = 0; b < currentTotal; b++) {
              const src = balls[b];
              balls.push({
                x: src.x, y: src.y,
                vx: -src.vx + (Math.random() - 0.5) * 160,
                vy: src.vy + (Math.random() - 0.5) * 160,
                radius: src.radius,
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

      // Partícules
      for (let i = particles.length - 1; i >= 0; i--) {
        const pt = particles[i];
        pt.x += pt.vx * dt;
        pt.y += pt.vy * dt;
        pt.life -= dt;
        if (pt.life <= 0) particles.splice(i, 1);
      }

      if (remainingRed <= 0 || simTime >= 42) {
        window.isFinished = true;
      }

      render();
    };

    function render() {
      // Fons 100% negre
      ctx.fillStyle = '#000000';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Maons
      for (let i = 0; i < bricks.length; i++) {
        const b = bricks[i];
        if (!b.alive) continue;

        if (b.type === 'grey') {
          ctx.fillStyle = '#6e7480';
          ctx.fillRect(b.x, b.y, b.w, b.h);
        } else {
          ctx.fillStyle = '#ff2b43';
          ctx.fillRect(b.x, b.y, b.w, b.h);
        }
      }

      // Partícules
      ctx.fillStyle = '#ff2b43';
      for (const p of particles) {
        ctx.fillRect(p.x, p.y, 4, 4);
      }

      // Power-ups (sense cap text)
      for (const p of powerups) {
        ctx.save();
        if (p.type === 'MULTIBALL') {
          ctx.fillStyle = '#ff0055';
          ctx.shadowColor = '#ff0055';
        } else {
          ctx.fillStyle = '#00f0ff';
          ctx.shadowColor = '#00f0ff';
        }
        ctx.shadowBlur = 12;
        ctx.beginPath();
        ctx.roundRect(p.x - 14, p.y - 14, 28, 28, 14); // Píndola esfèrica neta
        ctx.fill();
        ctx.restore();
      }

      // Barra inferior (Paddle)
      ctx.save();
      ctx.fillStyle = '#ffffff';
      ctx.shadowColor = '#00f0ff';
      ctx.shadowBlur = 15;
      ctx.beginPath();
      ctx.roundRect(paddle.x - paddle.w / 2, paddle.y - paddle.h / 2, paddle.w, paddle.h, 10);
      ctx.fill();
      ctx.restore();

      // Pilotes amb estela
      for (const b of balls) {
        for (let i = 0; i < b.trail.length; i++) {
          const t = b.trail[i];
          ctx.beginPath();
          ctx.arc(t.x, t.y, b.radius * 0.7, 0, Math.PI * 2);
          ctx.fillStyle = '#ffffff';
          ctx.globalAlpha = (i / b.trail.length) * 0.3;
          ctx.fill();
        }
        ctx.globalAlpha = 1.0;

        ctx.save();
        ctx.fillStyle = '#ffffff';
        ctx.shadowColor = '#ffffff';
        ctx.shadowBlur = 12;
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

// Síntesi d'àudio autònoma en memòria (WAV 16-bit 44.1kHz)
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
  console.log('🚀 Renderitzant Destroyer Ball (Laberint Procedural)...');
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

  console.log('🎵 Generant so de col·lisions i boosts...');
  generateWavTrack(audioEvents, frame / FPS);

  console.log('📦 Muntant MP4 final...');
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
  if (!token || !chatId) return console.log('⚠️ Secrets de Telegram no trobats. Vídeo guardat localment.');

  console.log('📤 Enviant a Telegram...');
  const formData = new FormData();
  formData.append('chat_id', chatId);
  formData.append('caption', 'Destroyer Ball Daily Video');
  formData.append('video', new Blob([fs.readFileSync(filePath)], { type: 'video/mp4' }), 'video.mp4');

  const res = await fetch(`https://api.telegram.org/bot${token}/sendVideo`, { method: 'POST', body: formData });
  const json = await res.json();
  if (json.ok) console.log('✅ Vídeo enviat a Telegram correctament!');
  else console.error('❌ Error Telegram:', json);
}

start();

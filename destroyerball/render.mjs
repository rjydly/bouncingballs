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

    const COLS = 36;
    const ROWS = 48;
    const CELL_W = 30;
    const CELL_H = 26;
    const BRICK_W = 28;
    const BRICK_H = 24;

    const grid = Array.from({ length: ROWS }, () => Array(COLS).fill(0));
    const chamberTop = 2;
    const chamberBottom = 40;

    // 1. MURS GRISOS I INTERIOR VERMELL
    for (let r = chamberTop; r <= chamberBottom; r++) {
      for (let c = 0; c < COLS; c++) {
        if (r === chamberTop || r === chamberBottom || c === 0 || c === COLS - 1) {
          grid[r][c] = 1;
        } else {
          grid[r][c] = 2;
        }
      }
    }

    // 2. GENERACIÓ DEL PASSADÍS AMB FINAL HORITZONTAL
    const mouthCol = Math.floor(Math.random() * (COLS - 16)) + 8;
    const turn1Row = chamberBottom - (Math.floor(Math.random() * 4) + 7);
    const sideDir1 = (mouthCol > COLS / 2) ? -1 : 1;
    const turn1Len = Math.floor(Math.random() * 4) + 5;
    const turn1Col = Math.max(3, Math.min(COLS - 4, mouthCol + sideDir1 * turn1Len));

    const turn2Row = turn1Row - (Math.floor(Math.random() * 5) + 6);
    const finalDir = (turn1Col > COLS / 2) ? -1 : 1;
    const finalLen = Math.floor(Math.random() * 5) + 6;
    const exitCol = Math.max(2, Math.min(COLS - 3, turn1Col + finalDir * finalLen));

    const pathCells = [];

    // Tram 1: Amunt
    for (let r = chamberBottom; r >= turn1Row; r--) pathCells.push({ r, c: mouthCol });
    // Tram 2: Horitzontal 1
    for (let c = mouthCol + sideDir1; sideDir1 > 0 ? c <= turn1Col : c >= turn1Col; c += sideDir1) {
      pathCells.push({ r: turn1Row, c });
    }
    // Tram 3: Amunt 2
    for (let r = turn1Row - 1; r >= turn2Row; r--) pathCells.push({ r, c: turn1Col });
    // Tram 4: FINAL HORITZONTAL
    for (let c = turn1Col + finalDir; finalDir > 0 ? c <= exitCol : c >= exitCol; c += finalDir) {
      pathCells.push({ r: turn2Row, c });
    }

    const pathSet = new Set(pathCells.map(p => p.r + ',' + p.c));
    const lastCell = pathCells[pathCells.length - 1];

    for (const p of pathCells) {
      grid[p.r][p.c] = 0;
      for (let dr = -1; dr <= 1; dr++) {
        for (let dc = -1; dc <= 1; dc++) {
          const nr = p.r + dr;
          const nc = p.c + dc;
          if (nr < chamberTop || nr > chamberBottom || nc < 0 || nc >= COLS) continue;
          if (p === lastCell && dr === 0 && dc === finalDir) continue; // Sortida horitzontal als vermells
          if (!pathSet.has(nr + ',' + nc)) grid[nr][nc] = 1;
        }
      }
    }

    // Coordenades clau de navegació
    const entranceX = mouthCol * CELL_W + CELL_W / 2;
    const entranceY = chamberBottom * CELL_H + CELL_H / 2;
    const turn1X = turn1Col * CELL_W + CELL_W / 2;
    const turn1Y = turn1Row * CELL_H + CELL_H / 2;
    const turn2Y = turn2Row * CELL_H + CELL_H / 2;
    const exitX = exitCol * CELL_W + CELL_W / 2;

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
      y: 1730,
      w: 180,
      h: 22,
      targetX: 540,
      speed: 1350
    };

    let mainBallId = 1;
    let nextBallId = 2;
    const TARGET_SPEED = 1100;

    let balls = [{
      id: mainBallId,
      x: 540,
      y: 1670,
      vx: (Math.random() - 0.5) * 300,
      vy: -TARGET_SPEED,
      radius: 8.5,
      trail: [],
      corridorState: null,
      turn1Attempts: 0
    }];

    let bouncesDone = 0;
    const requiredBounces = Math.floor(Math.random() * 3) + 1;

    const powerups = [];
    const particles = [];

    window.advanceFrame = function() {
      simTime += dt;

      // 1. IA DE LA BARRA
      let targetBall = balls.find(b => b.id === mainBallId) || balls[0];

      let boostToCatch = null;
      for (const p of powerups) {
        if (p.y > 1300 && p.y < paddle.y) {
          if (!boostToCatch || p.y > boostToCatch.y) boostToCatch = p;
        }
      }

      if (boostToCatch && (!targetBall || targetBall.y < 1350 || targetBall.vy < 0)) {
        paddle.targetX = boostToCatch.x;
      } else if (targetBall) {
        if (bouncesDone < requiredBounces) {
          const missOffset = (bouncesDone % 2 === 0 ? 70 : -70);
          paddle.targetX = targetBall.x + missOffset;
        } else {
          // Si la bola està caient rebotada del passadís o puja:
          const dx = entranceX - targetBall.x;
          const dy = entranceY - targetBall.y;
          const targetAngle = Math.atan2(dx, -dy);
          const hitFactor = targetAngle / (Math.PI / 3.4);
          paddle.targetX = targetBall.x - hitFactor * (paddle.w / 2);
        }
      }

      paddle.targetX = Math.max(paddle.w / 2, Math.min(1080 - paddle.w / 2, paddle.targetX));
      const pDiff = paddle.targetX - paddle.x;
      paddle.x += Math.sign(pDiff) * Math.min(Math.abs(pDiff), paddle.speed * dt);

      // 2. FÍSICA DE LES BOLES
      for (let bi = balls.length - 1; bi >= 0; bi--) {
        const ball = balls[bi];

        // GESTIÓ SENSE FALLA DINS DEL PASSADÍS
        if (ball.corridorState) {
          if (ball.corridorState === 'V1') {
            ball.x = entranceX;
            ball.y += ball.vy * dt;

            // Arriba a la primera cantonada
            if (ball.y <= turn1Y) {
              ball.turn1Attempts = (ball.turn1Attempts || 0) + 1;

              // REBOT ENRERE PROBABILÍSTIC AL PRIMER INTENT
              if (ball.turn1Attempts === 1 && Math.random() < 0.65) {
                ball.corridorState = 'FALLING_BACK';
                ball.vy = TARGET_SPEED; // Torna enrere cap avall!
                window.audioEvents.push({ time: simTime, freq: 220 });
              } else {
                // Gira correctament cap al tram horitzontal
                ball.corridorState = 'H1';
                ball.y = turn1Y;
                ball.vx = sideDir1 * TARGET_SPEED;
                ball.vy = 0;
                window.audioEvents.push({ time: simTime, freq: 440 });
              }
            }
          } else if (ball.corridorState === 'FALLING_BACK') {
            ball.x = entranceX;
            ball.y += ball.vy * dt;

            // Surt disparada cap avall per la boca de l'embut
            if (ball.y >= entranceY + 15) {
              ball.corridorState = null;
              ball.vx = (Math.random() - 0.5) * 220;
              ball.vy = TARGET_SPEED;
            }
          } else if (ball.corridorState === 'H1') {
            ball.y = turn1Y;
            ball.x += ball.vx * dt;

            // Arriba a la cantonada 2 (puja)
            if ((sideDir1 > 0 && ball.x >= turn1X) || (sideDir1 < 0 && ball.x <= turn1X)) {
              ball.corridorState = 'V2';
              ball.x = turn1X;
              ball.vy = -TARGET_SPEED;
              ball.vx = 0;
              window.audioEvents.push({ time: simTime, freq: 520 });
            }
          } else if (ball.corridorState === 'V2') {
            ball.x = turn1X;
            ball.y += ball.vy * dt;

            // Arriba a la cantonada 3 (gir final cap a l'horitzontal)
            if (ball.y <= turn2Y) {
              ball.corridorState = 'H_FINAL';
              ball.y = turn2Y;
              ball.vx = finalDir * TARGET_SPEED;
              ball.vy = 0;
              window.audioEvents.push({ time: simTime, freq: 640 });
            }
          } else if (ball.corridorState === 'H_FINAL') {
            ball.y = turn2Y;
            ball.x += ball.vx * dt;

            // SURT EN HORITZONTAL CAP ALS VERMELLS!
            if ((finalDir > 0 && ball.x >= exitX) || (finalDir < 0 && ball.x <= exitX)) {
              ball.corridorState = null;
              ball.vx = finalDir * TARGET_SPEED;
              ball.vy = (Math.random() - 0.5) * 350;
              window.audioEvents.push({ time: simTime, freq: 880 });
            }
          }

          // Estela i continuar
          ball.trail.push({ x: ball.x, y: ball.y });
          if (ball.trail.length > 7) ball.trail.shift();
          continue;
        }

        // FÍSICA NORMAL FORA O DINS LA CAMBRA
        ball.x += ball.vx * dt;
        ball.y += ball.vy * dt;

        // PROTECTOR ANTI-BUCLE / ANTI-OSCIL·LACIÓ 1D
        if (Math.abs(ball.vx) < 160) ball.vx = Math.sign(ball.vx || (Math.random() - 0.5)) * 220;
        if (Math.abs(ball.vy) < 160) ball.vy = Math.sign(ball.vy || (Math.random() - 0.5)) * 220;

        const spd = Math.hypot(ball.vx, ball.vy);
        ball.vx = (ball.vx / spd) * TARGET_SPEED;
        ball.vy = (ball.vy / spd) * TARGET_SPEED;

        // ENTRADA AL PASSADÍS
        if (
          ball.vy < 0 &&
          Math.abs(ball.x - entranceX) < 16 &&
          Math.abs(ball.y - entranceY) < 20
        ) {
          ball.corridorState = 'V1';
          ball.x = entranceX;
          ball.y = entranceY;
          ball.vy = -TARGET_SPEED;
          ball.vx = 0;
          window.audioEvents.push({ time: simTime, freq: 350 });
          continue;
        }

        // Parets de pantalla
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
          const angle = hitRatio * (Math.PI / 3.1);
          ball.vx = TARGET_SPEED * Math.sin(angle);
          ball.vy = -Math.abs(TARGET_SPEED * Math.cos(angle));
          ball.y = paddle.y - paddle.h / 2 - ball.radius;
          window.audioEvents.push({ time: simTime, freq: 130 });
        }

        // Pèrdua de boles extra que cauen al fons
        if (ball.y + ball.radius >= 1900) {
          if (ball.id !== mainBallId && balls.length > 1) {
            balls.splice(bi, 1);
            continue;
          } else {
            ball.vy = -Math.abs(ball.vy);
          }
        }

        // Col·lisió amb maons
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
              const prevX = ball.x - ball.vx * dt;
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

                // 3.5% de probabilitat de boost
                if (Math.random() < 0.035) {
                  powerups.push({
                    x: brick.x + brick.w / 2,
                    y: brick.y + brick.h / 2,
                    vy: 340,
                    radius: 20,
                    type: Math.random() < 0.6 ? 'MULTIBALL' : 'BIG_PADDLE'
                  });
                }
              } else {
                window.audioEvents.push({ time: simTime, freq: 180 });
              }
              break;
            }
          }
        }

        ball.trail.push({ x: ball.x, y: ball.y });
        if (ball.trail.length > 7) ball.trail.shift();
      }

      // 3. BOOSTS
      for (let i = powerups.length - 1; i >= 0; i--) {
        const p = powerups[i];
        p.y += p.vy * dt;

        if (
          p.y + p.radius >= paddle.y - paddle.h / 2 &&
          p.y - p.radius <= paddle.y + paddle.h / 2 &&
          p.x >= paddle.x - paddle.w / 2 &&
          p.x <= paddle.x + paddle.w / 2
        ) {
          window.audioEvents.push({ time: simTime, freq: 850 });

          if (p.type === 'MULTIBALL') {
            for (let k = 0; k < 3; k++) {
              const spreadAngle = (k - 1) * 0.35;
              balls.push({
                id: nextBallId++,
                x: paddle.x + (k - 1) * 25,
                y: paddle.y - paddle.h / 2 - 12,
                vx: TARGET_SPEED * Math.sin(spreadAngle),
                vy: -Math.abs(TARGET_SPEED * Math.cos(spreadAngle)),
                radius: 8.5,
                corridorState: null,
                trail: []
              });
            }
          } else if (p.type === 'BIG_PADDLE') {
            paddle.w = Math.min(340, paddle.w + 55);
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

      if (remainingRed <= 0 || (simTime >= 35 && remainingRed < 35) || simTime >= 45) {
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
        ctx.fillStyle = b.type === 'grey' ? '#6b7280' : '#ff2440';
        ctx.fillRect(b.x, b.y, b.w, b.h);
      }

      ctx.fillStyle = '#ff2440';
      for (const p of particles) {
        ctx.fillRect(p.x, p.y, 4, 4);
      }

      for (const p of powerups) {
        ctx.save();
        ctx.fillStyle = p.type === 'MULTIBALL' ? '#ff0055' : '#00f0ff';
        ctx.shadowColor = ctx.fillStyle;
        ctx.shadowBlur = 14;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = '#ffffff';
        ctx.font = '900 18px monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(p.type === 'MULTIBALL' ? 'x3' : '< >', p.x, p.y + 1);
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
  console.log('🚀 Renderitzant Destroyer Ball (Anti-Stuck Safe Pipeline)...');
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

  console.log('🎵 Generant àudio...');
  generateWavTrack(audioEvents, frame / FPS);

  console.log('📦 Creant MP4 final...');
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
  if (!token || !chatId) return console.log('⚠️ Secrets de Telegram no trobats. Fitxer guardat localment.');

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

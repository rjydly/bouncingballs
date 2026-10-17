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
    body { background: #08090d; display: flex; justify-content: center; align-items: center; width: 1080px; height: 1920px; overflow: hidden; font-family: 'Segoe UI', Roboto, sans-serif; }
    canvas { width: 1080px; height: 1920px; }
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

    // Arena principal
    const arena = { x: 70, y: 180, width: 940, height: 1650 };

    // Barra inferior (Paddle)
    const paddle = {
      x: 540,
      y: 1720,
      w: 190,
      h: 24,
      targetX: 540,
      speed: 1100
    };

    // Paràmetres del forat d'entrada
    const hole = {
      x: arena.x + arena.width / 2 - 80,
      w: 160,
      y: 1380
    };

    // Creació de centenars de quadradets petits
    const bricks = [];
    const cols = 28;
    const rows = 28;
    const brickW = 28;
    const brickH = 24;
    const startX = arena.x + (arena.width - (cols * (brickW + 4))) / 2;
    const startY = arena.y + 120;
    const colors = ['#FF0055', '#FF4400', '#FF9900', '#FFDD00', '#00FF66', '#00F0FF', '#0077FF', '#9900FF'];

    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        bricks.push({
          x: startX + c * (brickW + 4),
          y: startY + r * (brickH + 4),
          w: brickW,
          h: brickH,
          color: colors[Math.floor((r / rows) * colors.length)],
          alive: true
        });
      }
    }

    let remainingBricks = bricks.length;

    // Sistema de pilotes (més petites)
    let balls = [{
      x: 540,
      y: 1650,
      vx: 380,
      vy: -950,
      radius: 11,
      color: '#ffffff',
      trail: []
    }];

    // Estat de la IA humana (decideix quants intents necessita: 1, 2 o 3)
    let bounceCount = 0;
    const targetBounces = Math.floor(Math.random() * 3) + 1; // 1 a 3 rebots

    // Power-ups i efectes
    const powerups = [];
    const particles = [];
    const floatingTexts = [];

    function spawnPowerup(x, y) {
      if (Math.random() < 0.12) { // 12% probabilitat
        const type = Math.random() < 0.65 ? 'MULTIBALL' : 'BIG_PADDLE';
        powerups.push({ x, y, vy: 340, type });
      }
    }

    // Pas de simulació
    window.advanceFrame = function() {
      simTime += dt;

      // 1. IA de la Barra (Humana i imperfecta)
      // Segueix la pilota més propera a la barra
      let lowestBall = balls[0];
      for (const b of balls) {
        if (b.y > lowestBall.y) lowestBall = b;
      }

      if (lowestBall) {
        if (bounceCount < targetBounces) {
          // Intent fallit: la barra es posiciona lleugerament desviada per fer rebotar cap a la paret
          const intentionalMissOffset = (bounceCount % 2 === 0 ? 55 : -55);
          paddle.targetX = lowestBall.x + intentionalMissOffset;
        } else {
          // Intent encertat: apunta per embocar al forat
          const targetHoleX = hole.x + hole.w / 2;
          const dxToHole = targetHoleX - lowestBall.x;
          // Càlcul de deflexió: desplaça la pala per donar angle correcte
          const paddleOffset = Math.max(-75, Math.min(75, -dxToHole * 0.15));
          paddle.targetX = lowestBall.x + paddleOffset;
        }
      }

      // Moviment suau de la pala
      paddle.targetX = Math.max(arena.x + paddle.w / 2, Math.min(arena.x + arena.width - paddle.w / 2, paddle.targetX));
      const moveDiff = paddle.targetX - paddle.x;
      paddle.x += Math.sign(moveDiff) * Math.min(Math.abs(moveDiff), paddle.speed * dt);

      // 2. Sub-stepping físic de les boles (2 passos per evitar túnels de col·lisió)
      const subSteps = 2;
      const subDt = dt / subSteps;

      for (let step = 0; step < subSteps; step++) {
        for (let bi = balls.length - 1; bi >= 0; bi--) {
          const ball = balls[bi];
          ball.x += ball.vx * subDt;
          ball.y += ball.vy * subDt;

          // Xoc amb parets laterals de l'arena
          if (ball.x - ball.radius <= arena.x) {
            ball.x = arena.x + ball.radius;
            ball.vx = Math.abs(ball.vx);
            window.audioEvents.push({ time: simTime, freq: 150 });
          } else if (ball.x + ball.radius >= arena.x + arena.width) {
            ball.x = arena.x + arena.width - ball.radius;
            ball.vx = -Math.abs(ball.vx);
            window.audioEvents.push({ time: simTime, freq: 150 });
          }

          // Xoc amb sostre
          if (ball.y - ball.radius <= arena.y) {
            ball.y = arena.y + ball.radius;
            ball.vy = Math.abs(ball.vy);
            window.audioEvents.push({ time: simTime, freq: 150 });
          }

          // Paret de la cambra inferior (amb el FORAT al mig)
          if (ball.y + ball.radius >= hole.y && ball.y - ball.radius <= hole.y + 12) {
            const isInsideHole = (ball.x > hole.x && ball.x < hole.x + hole.w);
            if (!isInsideHole) {
              ball.vy = -ball.vy;
              window.audioEvents.push({ time: simTime, freq: 220 });
            }
          }

          // Xoc amb la pala inferior
          if (
            ball.y + ball.radius >= paddle.y - paddle.h / 2 &&
            ball.y - ball.radius <= paddle.y + paddle.h / 2 &&
            ball.x >= paddle.x - paddle.w / 2 &&
            ball.x <= paddle.x + paddle.w / 2 &&
            ball.vy > 0
          ) {
            bounceCount++;
            const hitFactor = (ball.x - paddle.x) / (paddle.w / 2); // -1 a 1
            const currentSpeed = Math.sqrt(ball.vx * ball.vx + ball.vy * ball.vy);
            const bounceAngle = hitFactor * (Math.PI / 3); // fins a 60 graus
            ball.vx = currentSpeed * Math.sin(bounceAngle);
            ball.vy = -Math.abs(currentSpeed * Math.cos(bounceAngle));
            ball.y = paddle.y - paddle.h / 2 - ball.radius;
            window.audioEvents.push({ time: simTime, freq: 130 });
          }

          // Si cau al fons absolut, rebot de salvament
          if (ball.y + ball.radius >= arena.y + arena.height) {
            ball.vy = -Math.abs(ball.vy);
          }

          // Xoc amb els quadradets diminuts
          for (let i = 0; i < bricks.length; i++) {
            const b = bricks[i];
            if (!b.alive) continue;

            if (
              ball.x + ball.radius > b.x &&
              ball.x - ball.radius < b.x + b.w &&
              ball.y + ball.radius > b.y &&
              ball.y - ball.radius < b.y + b.h
            ) {
              b.alive = false;
              remainingBricks--;

              // Decisió de rebot
              const prevX = ball.x - ball.vx * subDt;
              if (prevX + ball.radius <= b.x || prevX - ball.radius >= b.x + b.w) {
                ball.vx = -ball.vx;
              } else {
                ball.vy = -ball.vy;
              }

              // So agut creixent
              const noteFreq = 300 + (Math.sin(simTime * 6) * 100) + Math.random() * 80;
              window.audioEvents.push({ time: simTime, freq: noteFreq });

              // Partícules
              for (let p = 0; p < 8; p++) {
                const ang = Math.random() * Math.PI * 2;
                particles.push({
                  x: b.x + b.w / 2, y: b.y + b.h / 2,
                  vx: Math.cos(ang) * (Math.random() * 260 + 40),
                  vy: Math.sin(ang) * (Math.random() * 260 + 40),
                  color: b.color,
                  life: 0.35, maxLife: 0.35
                });
              }

              spawnPowerup(b.x + b.w / 2, b.y + b.h);
              break;
            }
          }
        }
      }

      // 3. Esteles de les boles
      for (const ball of balls) {
        ball.trail.push({ x: ball.x, y: ball.y });
        if (ball.trail.length > 8) ball.trail.shift();
      }

      // 4. Gestió de Power-ups (caiguda i recollida)
      for (let i = powerups.length - 1; i >= 0; i--) {
        const p = powerups[i];
        p.y += p.vy * dt;

        // Recollit per la pala
        if (
          p.y >= paddle.y - paddle.h / 2 &&
          p.y <= paddle.y + paddle.h / 2 + 20 &&
          p.x >= paddle.x - paddle.w / 2 &&
          p.x <= paddle.x + paddle.w / 2
        ) {
          window.audioEvents.push({ time: simTime, freq: 880 });

          if (p.type === 'MULTIBALL' && balls.length < 16) {
            const currentTotal = balls.length;
            for (let b = 0; b < currentTotal; b++) {
              const src = balls[b];
              balls.push({
                x: src.x, y: src.y,
                vx: -src.vx + (Math.random() - 0.5) * 150,
                vy: src.vy + (Math.random() - 0.5) * 150,
                radius: src.radius,
                color: '#ff00aa',
                trail: []
              });
            }
            floatingTexts.push({ text: 'x3 PILOTES!', x: p.x, y: p.y - 30, life: 1.0 });
          } else if (p.type === 'BIG_PADDLE') {
            paddle.w = Math.min(320, paddle.w + 50);
            floatingTexts.push({ text: '+BARRA!', x: p.x, y: p.y - 30, life: 1.0 });
          }
          powerups.splice(i, 1);
          continue;
        }

        // Fora de pantalla
        if (p.y > arena.y + arena.height) powerups.splice(i, 1);
      }

      // 5. Partícules i textos flotants
      for (let i = particles.length - 1; i >= 0; i--) {
        const pt = particles[i];
        pt.x += pt.vx * dt;
        pt.y += pt.vy * dt;
        pt.life -= dt;
        if (pt.life <= 0) particles.splice(i, 1);
      }

      for (let i = floatingTexts.length - 1; i >= 0; i--) {
        const ft = floatingTexts[i];
        ft.y -= 40 * dt;
        ft.life -= dt;
        if (ft.life <= 0) floatingTexts.splice(i, 1);
      }

      if (remainingBricks <= 0 || simTime >= 40) {
        window.isFinished = true;
      }

      render();
    };

    function render() {
      // Fons
      ctx.fillStyle = '#08090d';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Arena exterior
      ctx.strokeStyle = '#181b24';
      ctx.lineWidth = 6;
      ctx.strokeRect(arena.x, arena.y, arena.width, arena.height);

      // Mur de la cambra amb el FORAT
      ctx.fillStyle = '#222838';
      ctx.fillRect(arena.x, hole.y, hole.x - arena.x, 12); // Paret esquerra
      ctx.fillRect(hole.x + hole.w, hole.y, (arena.x + arena.width) - (hole.x + hole.w), 12); // Paret dreta

      // Guia lluminosa del forat
      ctx.strokeStyle = '#00f2fe';
      ctx.lineWidth = 4;
      ctx.strokeRect(hole.x, hole.y - 2, hole.w, 16);

      // UI Superior
      ctx.fillStyle = '#ffffff';
      ctx.font = '900 50px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('DESTROYER BALL', canvas.width / 2, 110);

      ctx.font = 'bold 36px monospace';
      ctx.fillStyle = '#00f2fe';
      ctx.fillText('RESTANTS: ' + remainingBricks, canvas.width / 2, 160);

      // Maons diminuts
      for (let i = 0; i < bricks.length; i++) {
        const b = bricks[i];
        if (!b.alive) continue;
        ctx.fillStyle = b.color;
        ctx.fillRect(b.x, b.y, b.w, b.h);
      }

      // Partícules
      for (const p of particles) {
        ctx.globalAlpha = p.life / p.maxLife;
        ctx.fillStyle = p.color;
        ctx.fillRect(p.x, p.y, 4, 4);
      }
      ctx.globalAlpha = 1.0;

      // Power-ups
      for (const p of powerups) {
        ctx.fillStyle = (p.type === 'MULTIBALL' ? '#ff0077' : '#ffd700');
        ctx.beginPath();
        ctx.roundRect(p.x - 22, p.y - 12, 44, 24, 8);
        ctx.fill();
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 14px sans-serif';
        ctx.fillText(p.type === 'MULTIBALL' ? 'x3' : '+BAR', p.x, p.y + 5);
      }

      // Textos flotants
      for (const ft of floatingTexts) {
        ctx.globalAlpha = ft.life;
        ctx.fillStyle = '#00ffaa';
        ctx.font = 'bold 28px sans-serif';
        ctx.fillText(ft.text, ft.x, ft.y);
      }
      ctx.globalAlpha = 1.0;

      // Barra inferior (Paddle) amb resplendor
      ctx.save();
      ctx.shadowColor = '#00f2fe';
      ctx.shadowBlur = 18;
      ctx.fillStyle = '#00f2fe';
      ctx.beginPath();
      ctx.roundRect(paddle.x - paddle.w / 2, paddle.y - paddle.h / 2, paddle.w, paddle.h, 12);
      ctx.fill();
      ctx.restore();

      // Pilotes (petites amb estela)
      for (const ball of balls) {
        for (let i = 0; i < ball.trail.length; i++) {
          const tr = ball.trail[i];
          ctx.beginPath();
          ctx.arc(tr.x, tr.y, ball.radius * 0.7, 0, Math.PI * 2);
          ctx.fillStyle = ball.color;
          ctx.globalAlpha = (i / ball.trail.length) * 0.35;
          ctx.fill();
        }
        ctx.globalAlpha = 1.0;

        ctx.save();
        ctx.shadowColor = ball.color;
        ctx.shadowBlur = 14;
        ctx.fillStyle = ball.color;
        ctx.beginPath();
        ctx.arc(ball.x, ball.y, ball.radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      if (remainingBricks <= 0) {
        ctx.fillStyle = 'rgba(0,0,0,0.8)';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#00FF66';
        ctx.font = 'bold 80px sans-serif';
        ctx.fillText('STAGE CLEARED!', canvas.width / 2, canvas.height / 2);
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
    const freq = ev.freq || 240;

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
  console.log('🚀 Renderitzant Destroyer Ball (Pixel Grid + Paddle AI)...');
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

  console.log('🎵 Sintetitzant àudio de rebots i powerups...');
  generateWavTrack(audioEvents, frame / FPS);

  console.log('📦 Generant vídeo final...');
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
  formData.append('caption', '🕹️ Destroyer Ball amb maons petits, paddle i boosts completat!');
  formData.append('video', new Blob([fs.readFileSync(filePath)], { type: 'video/mp4' }), 'video.mp4');

  const res = await fetch(`https://api.telegram.org/bot${token}/sendVideo`, { method: 'POST', body: formData });
  const json = await res.json();
  if (json.ok) console.log('✅ Enviat a Telegram!');
  else console.error('❌ Error Telegram:', json);
}

start();
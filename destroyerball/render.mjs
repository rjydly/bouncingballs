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

// TOT L'HTML, CANVAS I FÍSICA ENCASTAT AQUÍ:
const HTML_CONTENT = `
<!DOCTYPE html>
<html>
<head>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { background: #07090e; display: flex; justify-content: center; align-items: center; width: 1080px; height: 1920px; overflow: hidden; font-family: sans-serif; }
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

    const ball = { x: 540, y: 1250, vx: 700, vy: -950, radius: 24, color: '#00f2fe', trail: [] };
    const arena = { x: 80, y: 320, width: 920, height: 1350 };
    const bricks = [];
    const rows = 12, cols = 9;
    const brickW = arena.width / cols;
    const brickH = 45;
    const colors = ['#FF0055', '#FF5500', '#FFAA00', '#00FF66', '#00F0FF', '#7000FF'];

    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        bricks.push({
          x: arena.x + c * brickW,
          y: arena.y + 100 + r * brickH,
          w: brickW - 4,
          h: brickH - 4,
          color: colors[r % colors.length],
          alive: true
        });
      }
    }

    let remainingBricks = bricks.length;
    let combo = 0;
    const particles = [];

    function triggerHit(brick, x, y) {
      brick.alive = false;
      remainingBricks--;
      combo++;
      const baseFreq = 220;
      const scale = [1, 1.125, 1.25, 1.5, 1.667, 2];
      const noteFreq = baseFreq * scale[(combo % scale.length)] * Math.pow(2, Math.floor(combo / 12));
      window.audioEvents.push({ time: simTime, freq: noteFreq });

      for (let i = 0; i < 16; i++) {
        const angle = Math.random() * Math.PI * 2;
        const speed = Math.random() * 400 + 100;
        particles.push({ x, y, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed, color: brick.color, size: Math.random() * 6 + 4, life: 0.45, maxLife: 0.45 });
      }
      ball.vx *= 1.008;
      ball.vy *= 1.008;
    }

    window.advanceFrame = function() {
      simTime += dt;
      ball.x += ball.vx * dt;
      ball.y += ball.vy * dt;

      ball.trail.push({ x: ball.x, y: ball.y });
      if (ball.trail.length > 14) ball.trail.shift();

      if (ball.x - ball.radius <= arena.x) { ball.x = arena.x + ball.radius; ball.vx = -ball.vx; window.audioEvents.push({ time: simTime, freq: 160 }); }
      else if (ball.x + ball.radius >= arena.x + arena.width) { ball.x = arena.x + arena.width - ball.radius; ball.vx = -ball.vx; window.audioEvents.push({ time: simTime, freq: 160 }); }
      if (ball.y - ball.radius <= arena.y) { ball.y = arena.y + ball.radius; ball.vy = -ball.vy; window.audioEvents.push({ time: simTime, freq: 160 }); }
      else if (ball.y + ball.radius >= arena.y + arena.height) { ball.y = arena.y + arena.height - ball.radius; ball.vy = -ball.vy; window.audioEvents.push({ time: simTime, freq: 160 }); }

      for (const b of bricks) {
        if (!b.alive) continue;
        if (ball.x + ball.radius > b.x && ball.x - ball.radius < b.x + b.w && ball.y + ball.radius > b.y && ball.y - ball.radius < b.y + b.h) {
          const prevX = ball.x - ball.vx * dt;
          if (prevX + ball.radius <= b.x || prevX - ball.radius >= b.x + b.w) ball.vx = -ball.vx;
          else ball.vy = -ball.vy;
          triggerHit(b, ball.x, ball.y);
          break;
        }
      }

      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.x += p.vx * dt; p.y += p.vy * dt; p.life -= dt;
        if (p.life <= 0) particles.splice(i, 1);
      }

      if (remainingBricks <= 0 || simTime >= 35) window.isFinished = true;
      render();
    };

    function render() {
      ctx.fillStyle = '#07090e';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      ctx.strokeStyle = '#2b334a';
      ctx.lineWidth = 8;
      ctx.strokeRect(arena.x, arena.y, arena.width, arena.height);

      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 52px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('DESTROYER BALL', canvas.width / 2, 160);

      ctx.font = 'bold 36px sans-serif';
      ctx.fillStyle = '#00f2fe';
      ctx.fillText('MAONS RESTANTS: ' + remainingBricks, canvas.width / 2, 230);

      for (const b of bricks) {
        if (!b.alive) continue;
        ctx.fillStyle = b.color;
        ctx.beginPath();
        ctx.roundRect(b.x, b.y, b.w, b.h, 6);
        ctx.fill();
      }

      for (const p of particles) {
        ctx.globalAlpha = p.life / p.maxLife;
        ctx.fillStyle = p.color;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1.0;

      for (let i = 0; i < ball.trail.length; i++) {
        const t = ball.trail[i];
        ctx.beginPath();
        ctx.arc(t.x, t.y, ball.radius * 0.8, 0, Math.PI * 2);
        ctx.fillStyle = ball.color;
        ctx.globalAlpha = (i / ball.trail.length) * 0.4;
        ctx.fill();
      }
      ctx.globalAlpha = 1.0;

      ctx.save();
      ctx.shadowColor = ball.color;
      ctx.shadowBlur = 25;
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(ball.x, ball.y, ball.radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      if (remainingBricks <= 0) {
        ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#00FF66';
        ctx.font = 'bold 84px sans-serif';
        ctx.shadowColor = '#00FF66';
        ctx.shadowBlur = 30;
        ctx.fillText('CONGRATULATIONS!', canvas.width / 2, canvas.height / 2);
      }
    }
  </script>
</body>
</html>
`;

// Generador de so procedural en memòria (WAV 16-bit 44.1kHz)
function generateWavTrack(audioEvents, duration) {
  const sampleRate = 44100;
  const totalSamples = Math.ceil(duration * sampleRate);
  const buffer = new Float32Array(totalSamples);

  for (const ev of audioEvents) {
    const startSample = Math.floor(ev.time * sampleRate);
    const popLength = Math.floor(0.08 * sampleRate);
    const freq = ev.freq || 260;

    for (let i = 0; i < popLength; i++) {
      const idx = startSample + i;
      if (idx >= totalSamples) break;
      const t = i / sampleRate;
      buffer[idx] += Math.sin(2 * Math.PI * freq * t) * Math.exp(-t * 45) * 0.4;
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
  console.log('🚀 Iniciant Destroyer Ball (Mode integrat)...');
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT } });

  // Carrega el joc directament des de la variable
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
  }

  ffmpeg.stdin.end();
  await new Promise(r => ffmpeg.on('close', r));

  const audioEvents = await page.evaluate(() => window.audioEvents);
  await browser.close();

  console.log('🎵 Generant àudio...');
  generateWavTrack(audioEvents, frame / FPS);

  console.log('📦 Processant MP4 final...');
  await new Promise((res, rej) => {
    const mux = spawn('ffmpeg', [
      '-y', '-i', RAW_VIDEO, '-i', AUDIO_FILE, '-c:v', 'copy', '-c:a', 'aac', '-shortest', FINAL_VIDEO
    ]);
    mux.on('close', c => c === 0 ? res() : rej(new Error('Error muxing')));
  });

  if (fs.existsSync(RAW_VIDEO)) fs.unlinkSync(RAW_VIDEO);
  if (fs.existsSync(AUDIO_FILE)) fs.unlinkSync(AUDIO_FILE);

  await sendTelegram(FINAL_VIDEO);
}

async function sendTelegram(filePath) {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;
  if (!token || !chatId) return console.log('⚠️ Secrets de Telegram no trobats. Vídeo generat localment.');

  console.log('📤 Enviant a Telegram...');
  const formData = new FormData();
  formData.append('chat_id', chatId);
  formData.append('caption', '🎮 Destroyer Ball generat amb èxit!');
  formData.append('video', new Blob([fs.readFileSync(filePath)], { type: 'video/mp4' }), 'video.mp4');

  const res = await fetch(`https://api.telegram.org/bot${token}/sendVideo`, { method: 'POST', body: formData });
  const json = await res.json();
  if (json.ok) console.log('✅ Enviat a Telegram!');
  else console.error('❌ Error Telegram:', json);
}

start();
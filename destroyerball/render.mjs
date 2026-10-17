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

    // Dimensions: 36 columnes que omplen EXACTAMENT els 1080px (36 * 30px = 1080px)
    const COLS = 36;
    const ROWS = 48;
    const CELL_W = 30;
    const CELL_H = 26;
    const BRICK_W = 28;
    const BRICK_H = 24;
    const GAP = 2;

    // 0 = Buit, 1 = Gris (Indestructible), 2 = Vermell (Destruïble)
    const grid = Array.from({ length: ROWS }, () => Array(COLS).fill(0));

    const chamberTop = 2;
    const chamberBottom = 42; // Línia que separa la cambra de la zona de la pala

    // 1. OMPLIR LA CAMBRA SUPERIOR DE VERMELLS AMB MURS GRISOS
    for (let r = chamberTop; r <= chamberBottom; r++) {
      for (let c = 0; c < COLS; c++) {
        if (r === chamberTop || r === chamberBottom || c === 0 || c === COLS - 1) {
          grid[r][c] = 1; // Mur gris
        } else {
          grid[r][c] = 2; // Bloc vermell interior
        }
      }
    }

    // 2. GENERAR PASSADÍS D'1 SOL QUADRADET (ORTOGONAL: AMUNT I COSTATS)
    const mouthCol = Math.floor(Math.random() * (COLS - 14)) + 7;
    const pathCells = [];

    // Obertura a la paret inferior
    pathCells.push({ r: chamberBottom, c: mouthCol, dir: 'UP' });

    // Tram 1: Pujar recte amunt (entre 8 i 12 blocs)
    const turn1Row = chamberBottom - (Math.floor(Math.random() * 5) + 8);
    for (let r = chamberBottom - 1; r >= turn1Row; r--) {
      pathCells.push({ r, c: mouthCol, dir: 'UP' });
    }

    // Tram 2: Anar cap als costats (Esquerra o Dreta)
    const sideDir = (mouthCol > COLS / 2) ? -1 : 1;
    const turnLength = Math.floor(Math.random() * 5) + 6;
    const turn2Col = Math.max(3, Math.min(COLS - 4, mouthCol + sideDir * turnLength));

    for (let c = mouthCol + sideDir; sideDir > 0 ? c <= turn2Col : c >= turn2Col; c += sideDir) {
      pathCells.push({ r: turn1Row, c, dir: sideDir > 0 ? 'RIGHT' : 'LEFT' });
    }

    // Tram 3: Tornar a pujar recte amunt cap al centre dels vermells
    const targetEndRow = turn1Row - (Math.floor(Math.random() * 6) + 8);
    for (let r = turn1Row - 1; r >= targetEndRow; r--) {
      pathCells.push({ r, c: turn2Col, dir: 'UP' });
    }

    const pathSet = new Set(pathCells.map(p => p.r + ',' + p.c));
    const lastCell = pathCells[pathCells.length - 1];

    // Buidar el passadís i protegir-lo amb parets grises de blindatge
    for (const p of pathCells) {
      grid[p.r][p.c] = 0; // Buit per on viatja la bola

      // Posar blocs grisos a tots els voltants del passadís
      for (let dr = -1; dr <= 1; dr++) {
        for (let dc = -1; dc <= 1; dc++) {
          const nr = p.r + dr;
          const nc = p.c + dc;
          if (nr < chamberTop || nr > chamberBottom || nc < 0 || nc >= COLS) continue;

          // No tapar la sortida final que dóna a l'interior vermell
          if (p === lastCell && dr === -1 && dc === 0) continue;

          if (!pathSet.has(nr + ',' + nc)) {
            grid[nr][nc] = 1; // Bloc gris protector
          }
        }
      }
    }

    // Crear la llista final d'objectes per al joc
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

    // Coordenada exacta de l'obertura (1 sol quadradet)
    const entranceX = mouthCol * CELL_W + CELL_W / 2;
    const entranceY = chamberBottom * CELL_H + CELL_H / 2;

    // Barra inferior
    const paddle = {
      x: 540,
      y: 1730,
      w: 180,
      h: 22,
      targetX: 540,
      speed: 1300
    };

    // Pilotes (petites per entrar pel túnel estret)
    let balls = [{
      x: 540,
      y: 1670,
      vx: (Math.random() - 0.5) * 350,
      vy: -960,
      radius: 8.5,
      trail: []
    }];

    // IA Humana: 1 a 3 rebots abans d'apuntar a la perfecció
    let bouncesDone = 0;
    const requiredBounces = Math.floor(Math.random() * 3) + 1;

    const powerups = [];
    const particles = [];

    // Bucle físic determinista
    window.advanceFrame = function() {
      simTime += dt;

      // 1. Control de la barra
      let lowestBall = balls[0];
      for (const b of balls) {
        if (b.y > lowestBall.y) lowestBall = b;
      }

      if (lowestBall) {
        if (bouncesDone < requiredBounces) {
          // Rebot fallat intencionadament contra la paret
          const missOffset = (bouncesDone % 2 === 0 ? 65 : -65);
          paddle.targetX = lowestBall.x + missOffset;
        } else {
          // Càlcul precís cap al forat d'1 sol quadradet
          const dx = entranceX - lowestBall.x;
          const dy = entranceY - lowestBall.y;
          const targetAngle = Math.atan2(dx, -dy);
          const hitFactor = targetAngle / (Math.PI / 3.4);
          paddle.targetX = lowestBall.x - hitFactor * (paddle.w / 2);
        }
      }

      // Limitar la barra a la pantalla
      paddle.targetX = Math.max(paddle.w / 2, Math.min(1080 - paddle.w / 2, paddle.targetX));
      const pDiff = paddle.targetX - paddle.x;
      paddle.x += Math.sign(pDiff) * Math.min(Math.abs(pDiff), paddle.speed * dt);

      // 2. Sub-stepping de les pilotes (4 passos per màxima precisió en 1 bloc)
      const subSteps = 4;
      const subDt = dt / subSteps;

      for (let s = 0; s < subSteps; s++) {
        for (let bi = balls.length - 1; bi >= 0; bi--) {
          const ball = balls[bi];
          ball.x += ball.vx * subDt;
          ball.y += ball.vy * subDt;

          // Parets laterals de la pantalla
          if (ball.x - ball.radius <= 0) {
            ball.x = ball.radius;
            ball.vx = Math.abs(ball.vx);
            window.audioEvents.push({ time: simTime, freq: 160 });
          } else if (ball.x + ball.radius >= 1080) {
            ball.x = 1080 - ball.radius;
            ball.vx = -Math.abs(ball.vx);
            window.audioEvents.push({ time: simTime, freq: 160 });
          }

          // Rebot amb la barra
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
            window.audioEvents.push({ time: simTime, freq: 130 });
          }

          // Fons inferior de seguretat
          if (ball.y + ball.radius >= 1880) {
            ball.vy = -Math.abs(ball.vy);
          }

          // Redirecció suau a les cantonades del passadís estret
          const currC = Math.floor(ball.x / CELL_W);
          const currR = Math.floor(ball.y / CELL_H);
          const currentPathNode = pathCells.find(p => p.r === currR && p.c === currC);

          if (currentPathNode) {
            if (currentPathNode.dir === 'RIGHT' && ball.vy < 0) {
              ball.vx = Math.abs(ball.vy);
              ball.vy = 0;
            } else if (currentPathNode.dir === 'LEFT' && ball.vy < 0) {
              ball.vx = -Math.abs(ball.vy);
              ball.vy = 0;
            } else if (currentPathNode.dir === 'UP' && Math.abs(ball.vx) > 0) {
              ball.vy = -Math.abs(ball.vx);
              ball.vx = 0;
            }
          }

          // Col·lisions amb els blocs
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
                if (prevX + ball.radius <= brick.x || prevX - ball.radius >= brick.x + brick.w) {
                  ball.vx = -ball.vx;
                } else {
                  ball.vy = -ball.vy;
                }

                if (brick.type === 'red') {
                  brick.alive = false;
                  remainingRed--;
                  window.audioEvents.push({ time: simTime, freq: 360 + Math.random() * 80 });

                  for (let p = 0; p < 5; p++) {
                    const ang = Math.random() * Math.PI * 2;
                    particles.push({
                      x: brick.x + brick.w / 2, y: brick.y + brick.h / 2,
                      vx: Math.cos(ang) * (Math.random() * 180 + 30),
                      vy: Math.sin(ang) * (Math.random() * 180 + 30),
                      life: 0.28
                    });
                  }

                  if (Math.random() < 0.10) {
                    powerups.push({
                      x: brick.x + brick.w / 2,
                      y: brick.y + brick.h / 2,
                      vy: 360,
                      type: Math.random() < 0.65 ? 'MULTIBALL' : 'BIG_PADDLE'
                    });
                  }
                } else {
                  window.audioEvents.push({ time: simTime, freq: 190 });
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

      // Boosts
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
            const total = balls.length;
            for (let b = 0; b < total; b++) {
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
      ctx.fillStyle = '#000000';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Dibuixar tots els maons (ocupen tota l'amplada)
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

      // Partícules
      ctx.fillStyle = '#ff2440';
      for (const p of particles) {
        ctx.fillRect(p.x, p.y, 4, 4);
      }

      // Boosts (píndoles netes sense text)
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

      // Barra inferior
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
  console.log('🚀 Renderitzant Destroyer Ball (Full Width + 1-Brick Tunnel)...');
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

  console.log('📦 Creant fitxer MP4 final...');
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

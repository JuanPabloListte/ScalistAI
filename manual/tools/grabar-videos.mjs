// (Versión 2) Graba recorridos en video según config.videos(ids, h) y los convierte a MP4.
//
// Uso (desde manual/tools):
//   node grabar-videos.mjs              todos los videos
//   node grabar-videos.mjs alta         solo ids que contengan "alta"
//
// Cada video: { id, titulo?, rol, url, pasos: async (page, h) => … }
// Ayudas útiles en pasos: h.clic(page, locator), h.escribir(page, locator, texto),
// h.rotulo(page, 'texto'), h.pausa(page, ms). El cursor se dibuja solo.
// Salida: <config.videosDir ?? '../videos'>/<id>.mp4 y <id>.jpg (póster). Requiere ffmpeg en el PATH.

import { chromium } from 'playwright';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { cargarConfig, leerArgs, crearAyudas, inyectarCss, opcionesDeRol, CSS_BASE, CURSOR_VISIBLE } from './ayudas.mjs';

const config = await cargarConfig();
const { filtro } = leerArgs();
const h = crearAyudas();
if (typeof config.videos !== 'function') {
  console.log('config.videos no está definido: nada que grabar.');
  process.exit(0);
}
try {
  execFileSync('ffmpeg', ['-version'], { stdio: 'ignore' });
} catch {
  console.error('ffmpeg no está en el PATH (winget install ffmpeg | brew install ffmpeg | apt install ffmpeg).');
  process.exit(1);
}

const OUT = resolve(config.__dir, config.videosDir ?? '../videos');
mkdirSync(OUT, { recursive: true });
const viewport = config.viewport ?? { width: 1440, height: 900 };
const ids = config.preparar ? await config.preparar() : {};
const lista = config.videos(ids, h).filter((v) => v.id.includes(filtro));

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL ?? 'chrome' }); // Chrome instalado: sin descargar navegadores de Playwright
const fallas = [];
for (const v of lista) {
  const tmp = mkdtempSync(join(tmpdir(), 'manual-video-'));
  const { storageState, preparar } = opcionesDeRol(config, v.rol);
  const ctx = await browser.newContext({
    viewport,
    locale: config.locale ?? 'es-AR',
    timezoneId: config.timezoneId ?? 'America/Argentina/Buenos_Aires',
    storageState,
    recordVideo: { dir: tmp, size: viewport },
  });
  if (preparar) await preparar(ctx);
  await inyectarCss(ctx, CSS_BASE + (config.cssLimpio ?? ''));
  await ctx.addInitScript(CURSOR_VISIBLE);
  const page = await ctx.newPage();
  try {
    await page.goto(`${config.baseUrl}${v.url}`, { waitUntil: 'domcontentloaded', timeout: 90000 });
    await h.settle(page, 1200);
    if (v.titulo) await h.rotulo(page, v.titulo, 2500);
    await v.pasos(page, h);
    await page.waitForTimeout(1500);
    const video = page.video();
    await ctx.close();
    const webm = await video.path();
    const mp4 = join(OUT, `${v.id}.mp4`);
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', webm, '-c:v', 'libx264', '-preset', 'slow',
      '-crf', String(config.videoCrf ?? 26), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an', mp4]);
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-ss', '1', '-i', mp4, '-frames:v', '1', '-q:v', '3',
      join(OUT, `${v.id}.jpg`)]);
    console.log(`✔ ${v.id} → ${mp4}`);
  } catch (e) {
    fallas.push(v.id);
    console.log(`✘ ${v.id}: ${e.message.split('\n')[0]}`);
    await ctx.close().catch(() => {});
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}
await browser.close();
if (fallas.length) {
  console.log(`Fallaron: ${fallas.join(', ')}`);
  process.exitCode = 1;
}

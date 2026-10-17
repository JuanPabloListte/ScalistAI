// Verifica el manual antes de exportar/publicar.
//
// Uso:  node verificar-manual.mjs <ruta/index.html> [--json]
// Errores (exit 1): falta <title>/<meta charset>, imágenes o videos referenciados inexistentes.
// Avisos: imágenes sin usar, PNG sospechosas de estar vacías, figuras duplicadas o salteadas.
// --json imprime además la lista de imágenes referenciadas (útil para el `files` del Artifact).

import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, resolve, relative } from 'node:path';

const [, , entrada, ...resto] = process.argv;
if (!entrada) {
  console.error('Uso: node verificar-manual.mjs <ruta/index.html> [--json]');
  process.exit(1);
}
const htmlPath = resolve(entrada);
const base = dirname(htmlPath);
const html = readFileSync(htmlPath, 'utf8');
const errores = [];
const avisos = [];

if (!/<title>[^<]+<\/title>/i.test(html)) errores.push('Falta <title>.');
if (!/<meta\s+charset=/i.test(html)) errores.push('Falta <meta charset="utf-8"> (acentos rotos al abrir local).');

const refs = (re) => [...html.matchAll(re)].map((m) => m[1]).filter((s) => !/^(https?:|data:)/.test(s));
const imgs = [...new Set(refs(/<img[^>]+src="([^"]+)"/g))];
const posters = refs(/poster="([^"]+)"/g);
const videos = refs(/<source[^>]+src="([^"]+)"/g);

for (const r of [...imgs, ...posters, ...videos]) {
  if (!existsSync(join(base, r))) errores.push(`No existe: ${r}`);
}

// Imágenes sin usar
const imgDir = join(base, 'img');
if (existsSync(imgDir)) {
  const usadas = new Set(imgs.map((r) => resolve(base, r)));
  for (const f of readdirSync(imgDir)) {
    if (/\.(png|jpe?g|webp)$/i.test(f) && !usadas.has(resolve(imgDir, f))) avisos.push(`Sin usar: img/${f}`);
  }
}

// PNG sospechosas de estar vacías: pocos bytes por píxel (pantalla casi lisa).
function pngTam(file) {
  const b = readFileSync(file);
  if (b.length < 24 || b.toString('ascii', 12, 16) !== 'IHDR') return null;
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20), bytes: b.length };
}
for (const r of imgs.filter((x) => x.endsWith('.png'))) {
  const f = join(base, r);
  if (!existsSync(f)) continue;
  const t = pngTam(f);
  if (!t) continue;
  const bpp = t.bytes / (t.w * t.h);
  // Un login o un diálogo sobre fondo liso dan ~0,015–0,025 B/px; una pantalla en blanco, menos.
  if (bpp < 0.012) avisos.push(`¿Vacía? ${r} (${t.w}×${t.h}, ${(t.bytes / 1024).toFixed(0)} KB) — mirala`);
  else if (bpp < 0.022) avisos.push(`Poco contenido: ${r} (${(t.bytes / 1024).toFixed(0)} KB) — normal en login/diálogos; mirala si esperabas datos`);
  if (t.h > 4000) avisos.push(`Muy alta: ${r} (${t.h} px) — en el PDF queda ilegible`);
}

// Numeración de figuras por capítulo: "Fig. 7.3"
const figs = [...html.matchAll(/(Fig\.|Video)\s+(\d+)\.(\d+)/g)].map((m) => ({ tipo: m[1], cap: +m[2], n: +m[3] }));
const porCap = new Map();
for (const f of figs) {
  const k = `${f.tipo} ${f.cap}`;
  if (!porCap.has(k)) porCap.set(k, []);
  porCap.get(k).push(f.n);
}
for (const [k, ns] of porCap) {
  const dup = ns.filter((n, i) => ns.indexOf(n) !== i);
  if (dup.length) avisos.push(`${k}: números repetidos ${[...new Set(dup)].join(', ')}`);
  const orden = [...new Set(ns)].sort((a, b) => a - b);
  orden.forEach((n, i) => {
    if (n !== i + 1) avisos.push(`${k}: salta del ${orden[i - 1] ?? 0} al ${n}`);
  });
}

// Marcadores de plantilla sin reemplazar
const pendientes = html.match(/«[^»]{1,60}»/g);
if (pendientes) avisos.push(`Textos de plantilla sin completar: ${[...new Set(pendientes)].slice(0, 8).join(' ')}`);

const tamTotal = imgs.reduce((s, r) => (existsSync(join(base, r)) ? s + statSync(join(base, r)).size : s), 0);
console.log(`Manual: ${relative(process.cwd(), htmlPath)}`);
console.log(`Imágenes referenciadas: ${imgs.length} (${(tamTotal / 1048576).toFixed(1)} MB) · videos: ${videos.length}`);
errores.forEach((e) => console.log(`✘ ${e}`));
avisos.forEach((a) => console.log(`! ${a}`));
if (!errores.length && !avisos.length) console.log('✔ Sin problemas.');
if (resto.includes('--json')) console.log(JSON.stringify(Object.fromEntries(imgs.map((r) => [r, r])), null, 2));
process.exitCode = errores.length ? 1 : 0;

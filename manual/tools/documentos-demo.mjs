// Genera documentos demo en PDF (con marca de agua) a partir de HTML.
//
// Uso:  node documentos-demo.mjs <documentos.json> <carpeta-salida> [--marca "texto"] [--forzar]
//   documentos.json: [{ "file": "balance-empresa.pdf", "html": "<h1>…</h1><table>…</table>" }]
//   --marca   texto del recuadro superior (default "DOCUMENTO FICTICIO — SOLO PARA DEMOSTRACIÓN")
//   --forzar  regenera aunque el PDF ya exista
// Clases disponibles en el html: .muted (gris), td.n (número alineado a la derecha), th/td con borde.

import { chromium } from 'playwright';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const a = process.argv.slice(2);
const [json, dir] = a.filter((x, i) => !x.startsWith('--') && a[i - 1] !== '--marca');
if (!json || !dir) {
  console.error('Uso: node documentos-demo.mjs <documentos.json> <carpeta-salida> [--marca "texto"] [--forzar]');
  process.exit(1);
}
const marca = a.includes('--marca') ? a[a.indexOf('--marca') + 1] : 'DOCUMENTO FICTICIO — SOLO PARA DEMOSTRACIÓN';
const forzar = a.includes('--forzar');
const docs = JSON.parse(readFileSync(resolve(json), 'utf8'));
const out = resolve(dir);
mkdirSync(out, { recursive: true });

const CSS = `
  body{font-family:Arial,Helvetica,sans-serif;font-size:12px;margin:40px;color:#222}
  h1{font-size:18px;margin:0 0 4px} h2{font-size:14px;margin:18px 0 6px}
  .muted{color:#777} table{border-collapse:collapse;width:100%;margin-top:6px}
  td,th{border:1px solid #bbb;padding:5px 8px;text-align:left} th{background:#eee}
  td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
  .demo{border:2px dashed #c00;color:#c00;padding:6px;margin-bottom:14px;font-weight:bold}
`;

const browser = await chromium.launch();
const page = await browser.newPage();
let n = 0;
for (const d of docs) {
  const file = join(out, d.file);
  if (existsSync(file) && !forzar) continue;
  await page.setContent(
    `<!doctype html><html><head><meta charset="utf-8"><style>${CSS}</style></head>` +
      `<body><div class="demo">${marca}</div>${d.html}</body></html>`,
    { waitUntil: 'load' },
  );
  await page.pdf({ path: file, format: 'A4', printBackground: true });
  n++;
}
await browser.close();
console.log(`${n} PDF generados en ${out} (${docs.length - n} ya existían)`);

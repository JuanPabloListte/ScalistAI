// Exporta el manual HTML a PDF con sus propios estilos de impresión.
//
// Uso:  node exportar-pdf.mjs <ruta/index.html> [salida.pdf]
//   Sin salida: manual-usuario-<slug del <title>>.pdf junto al HTML.
// A4, márgenes 16/14/18 mm, pie con título y "página N / M", <details> abiertos,
// imágenes diferidas cargadas antes de imprimir.

import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const [, , entrada, salidaArg] = process.argv;
if (!entrada) {
  console.error('Uso: node exportar-pdf.mjs <ruta/index.html> [salida.pdf]');
  process.exit(1);
}
const html = resolve(entrada);
const titulo = (readFileSync(html, 'utf8').match(/<title>([^<]+)<\/title>/i)?.[1] ?? 'Manual de usuario').trim();
const slug = titulo
  .normalize('NFD')
  .replace(/[̀-ͯ]/g, '')
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, '-')
  .replace(/^-|-$/g, '');
const salida = resolve(salidaArg ?? join(dirname(html), `${slug}.pdf`));
const escapar = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL ?? 'chrome' }); // Chrome instalado: sin descargar navegadores de Playwright
const page = await browser.newPage();
await page.goto(pathToFileURL(html).href, { waitUntil: 'networkidle' });
await page.evaluate(async () => {
  document.querySelectorAll('img[loading="lazy"]').forEach((i) => (i.loading = 'eager'));
  await Promise.all(
    [...document.images].map((i) => (i.complete ? null : new Promise((r) => (i.onload = i.onerror = r)))),
  );
  document.querySelectorAll('details').forEach((d) => (d.open = true));
  await document.fonts?.ready;
});
await page.emulateMedia({ media: 'print', colorScheme: 'light' });
await page.pdf({
  path: salida,
  format: 'A4',
  printBackground: true,
  displayHeaderFooter: true,
  headerTemplate: '<span></span>',
  footerTemplate:
    '<div style="width:100%;font:8px Arial,sans-serif;color:#6b6b80;padding:0 14mm;display:flex;justify-content:space-between">' +
    `<span>${escapar(titulo)}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`,
  margin: { top: '16mm', bottom: '18mm', left: '14mm', right: '14mm' },
});
await browser.close();
console.log(`PDF generado: ${salida}`);

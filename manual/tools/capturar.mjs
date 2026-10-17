// Genera las capturas del manual con Playwright según manual.config.mjs.
//
// Uso (desde manual/tools):
//   node capturar.mjs                     todas las capturas
//   node capturar.mjs clientes            solo las que contengan "clientes" en el id
//   node capturar.mjs --workers 3         3 páginas en paralelo
//   node capturar.mjs --config otra.mjs   otro archivo de configuración
//
// Cada captura de config.capturas(ids, h):
//   { id, rol, url, pasos?, fullPage?, esperar?, elemento?, oscuro? }
//   - rol       clave de config.roles, o null para páginas públicas
//   - pasos     async (page, h) => …  acciones previas a la foto (abrir diálogo, cambiar pestaña)
//   - esperar   texto o selector CSS que tiene que estar visible antes de la foto
//   - elemento  selector CSS: captura solo ese elemento (p. ej. un diálogo)
//   - oscuro    true: emula prefers-color-scheme: dark
// Salida: <config.outDir>/<id>.png  (outDir relativo a manual.config.mjs). Sale con código 1 si falla alguna.

import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { cargarConfig, leerArgs, crearAyudas, inyectarCss, opcionesDeRol, CSS_BASE } from './ayudas.mjs';

const config = await cargarConfig();
const { filtro, workers } = leerArgs();
const h = crearAyudas();
const OUT = resolve(config.__dir, config.outDir ?? '../img');
mkdirSync(OUT, { recursive: true });

const ids = config.preparar ? await config.preparar() : {};
const lista = config.capturas(ids, h).filter((c) => c.id.includes(filtro));
if (lista.length === 0) {
  console.log(`Ninguna captura coincide con "${filtro}".`);
  process.exit(0);
}

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL ?? 'chrome' }); // Chrome instalado: sin descargar navegadores de Playwright

async function nuevoContexto(rol, oscuro) {
  const { storageState, preparar } = opcionesDeRol(config, rol);
  const ctx = await browser.newContext({
    viewport: config.viewport ?? { width: 1440, height: 900 },
    deviceScaleFactor: config.deviceScaleFactor ?? 1,
    locale: config.locale ?? 'es-AR',
    timezoneId: config.timezoneId ?? 'America/Argentina/Buenos_Aires',
    colorScheme: oscuro ? 'dark' : 'light',
    storageState,
  });
  if (preparar) await preparar(ctx);
  await inyectarCss(ctx, CSS_BASE + (config.cssLimpio ?? ''));
  return ctx;
}

async function esperarObjetivo(page, objetivo) {
  const esSelector = /^[.#[]|^[a-z]+[.#[:]/i.test(objetivo);
  const loc = esSelector ? page.locator(objetivo) : page.getByText(objetivo);
  await loc.first().waitFor({ state: 'visible', timeout: 30000 });
}

const fallas = [];
async function trabajador(tareas) {
  const contextos = new Map();
  for (const c of tareas) {
    const clave = `${c.rol ?? '-'}|${c.oscuro ? 'd' : 'l'}`;
    if (!contextos.has(clave)) contextos.set(clave, await nuevoContexto(c.rol, c.oscuro));
    const page = await contextos.get(clave).newPage();
    const t0 = Date.now();
    try {
      await page.goto(`${config.baseUrl}${c.url}`, { waitUntil: 'domcontentloaded', timeout: 90000 });
      await h.settle(page, 1500);
      if (c.pasos) {
        await c.pasos(page, h);
        await h.settle(page);
      }
      if (c.esperar) await esperarObjetivo(page, c.esperar);
      await page.mouse.move(0, 0);
      const destino = join(OUT, `${c.id}.png`);
      if (c.elemento) await page.locator(c.elemento).first().screenshot({ path: destino });
      else await page.screenshot({ path: destino, fullPage: !!c.fullPage });
      console.log(`✔ ${c.id} (${((Date.now() - t0) / 1000).toFixed(1)} s)`);
    } catch (e) {
      fallas.push(c.id);
      console.log(`✘ ${c.id}: ${e.message.split('\n')[0]}`);
    } finally {
      await page.close();
    }
  }
  for (const ctx of contextos.values()) await ctx.close();
}

const grupos = Array.from({ length: Math.min(workers, lista.length) }, () => []);
lista.forEach((c, i) => grupos[i % grupos.length].push(c));
await Promise.all(grupos.map(trabajador));
await browser.close();

console.log(`\n${lista.length - fallas.length}/${lista.length} capturas OK → ${OUT}`);
if (fallas.length) {
  console.log(`Fallaron: ${fallas.join(', ')}`);
  process.exitCode = 1;
}

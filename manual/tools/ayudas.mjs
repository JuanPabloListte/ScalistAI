// Ayudas compartidas por capturar.mjs y grabar-videos.mjs.
// Se exponen a manual.config.mjs como `h` en capturas(ids, h) y videos(ids, h).

import { dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { existsSync } from 'node:fs';

/** Carga manual.config.mjs (por defecto en el directorio actual, o --config <ruta>). */
export async function cargarConfig(argv = process.argv.slice(2)) {
  const i = argv.indexOf('--config');
  const ruta = resolve(i >= 0 ? argv[i + 1] : 'manual.config.mjs');
  if (!existsSync(ruta)) {
    throw new Error(`No encuentro ${ruta}. Copiá assets/manual.config.example.mjs y completalo.`);
  }
  const mod = await import(pathToFileURL(ruta).href);
  const config = mod.default ?? mod;
  config.__dir = dirname(ruta);
  return config;
}

/** Argumentos comunes: filtro posicional, --workers N. */
export function leerArgs(argv = process.argv.slice(2)) {
  const out = { filtro: '', workers: 1 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--config') i++;
    else if (a === '--workers') out.workers = Math.max(1, Number(argv[++i]) || 1);
    else if (!a.startsWith('--')) out.filtro = a;
  }
  return out;
}

export const CSS_BASE = `
  *, *::before, *::after { transition: none !important; animation-duration: 0s !important;
    animation-delay: 0s !important; caret-color: transparent !important; }
  nextjs-portal, [data-nextjs-toast], #__next-build-watcher, vite-error-overlay { display: none !important; }
`;

/** Inyecta CSS en cada documento del contexto (antes de que pinte la app). */
export async function inyectarCss(context, css) {
  await context.addInitScript((texto) => {
    const poner = () => {
      const s = document.createElement('style');
      s.setAttribute('data-manual', '');
      s.textContent = texto;
      (document.head || document.documentElement).appendChild(s);
    };
    if (document.head) poner();
    else document.addEventListener('DOMContentLoaded', poner);
  }, css);
}

/** Aplica la sesión de un rol: función (context) => void | { storageState } | null. */
export function opcionesDeRol(config, rol) {
  const def = rol ? config.roles?.[rol] : null;
  if (rol && def === undefined) throw new Error(`Rol "${rol}" no definido en config.roles`);
  if (def && typeof def === 'object' && def.storageState) {
    return { storageState: resolve(config.__dir, def.storageState), preparar: null };
  }
  return { storageState: undefined, preparar: typeof def === 'function' ? def : null };
}

const escaparRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

export function crearAyudas() {
  /** Espera a que la red se calme y desaparezcan spinners/skeletons comunes. */
  async function settle(page, ms = 900) {
    await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
    await page
      .waitForFunction(
        () =>
          !document.querySelector(
            '.animate-spin, .animate-pulse, [aria-busy="true"], .skeleton, .spinner, [role="progressbar"]:not([aria-valuenow])',
          ),
        null,
        { timeout: 15000 },
      )
      .catch(() => {});
    await page.waitForTimeout(ms);
  }

  /** Clic por texto visible: prueba tab → button → link → menuitem → option → texto. */
  async function click(page, texto, { exact = false } = {}) {
    const candidatos = [
      page.getByRole('tab', { name: texto, exact }),
      page.getByRole('button', { name: texto, exact }),
      page.getByRole('link', { name: texto, exact }),
      page.getByRole('menuitem', { name: texto, exact }),
      page.getByRole('option', { name: texto, exact }),
      page.getByText(texto, { exact }),
    ];
    for (const loc of candidatos) {
      const primero = loc.first();
      if ((await loc.count()) > 0 && (await primero.isVisible().catch(() => false))) {
        await primero.click();
        return;
      }
    }
    throw new Error(`No encontré "${texto}"`);
  }

  /** Pestaña por prefijo (tolera contadores: "Reglas 2"). Devuelve una función de pasos. */
  function tab(nombre) {
    return async (page) => {
      const re = new RegExp(`^\\s*${escaparRegex(nombre)}(\\s|\\d|$)`);
      await page.getByRole('tab', { name: re }).or(page.getByRole('button', { name: re })).first().click();
    };
  }

  // ---- ayudas para videos (también sirven en capturas) ----

  /** Mueve el mouse en pasos hasta el centro del locator y hace clic (el cursor se ve viajar). */
  async function clic(page, locator, { pasos = 25 } = {}) {
    await locator.scrollIntoViewIfNeeded();
    const caja = await locator.boundingBox();
    if (!caja) throw new Error('Elemento sin caja (¿oculto?)');
    await page.mouse.move(caja.x + caja.width / 2, caja.y + caja.height / 2, { steps: pasos });
    await page.waitForTimeout(150);
    await locator.click();
  }

  /** Tipea como una persona. */
  async function escribir(page, locator, texto, { demora = 60 } = {}) {
    await clic(page, locator);
    await locator.pressSequentially(texto, { delay: demora });
  }

  async function pausa(page, ms = 900) {
    await page.waitForTimeout(ms);
  }

  /** Subtítulo abajo al centro durante `ms`. */
  async function rotulo(page, texto, ms = 2200) {
    await page.evaluate(
      ([t, d]) => {
        let el = document.getElementById('__manual_rotulo');
        if (!el) {
          el = document.createElement('div');
          el.id = '__manual_rotulo';
          el.style.cssText =
            'position:fixed;left:50%;bottom:36px;transform:translateX(-50%);z-index:2147483647;' +
            'background:rgba(20,20,28,.88);color:#fff;font:600 18px/1.35 system-ui,sans-serif;' +
            'padding:10px 18px;border-radius:10px;max-width:70vw;text-align:center;pointer-events:none';
          document.body.appendChild(el);
        }
        el.textContent = t;
        el.style.opacity = '1';
        clearTimeout(window.__manualRotuloT);
        window.__manualRotuloT = setTimeout(() => (el.style.opacity = '0'), d);
      },
      [texto, ms],
    );
    await page.waitForTimeout(Math.min(ms, 1200));
  }

  return { settle, click, tab, clic, escribir, pausa, rotulo };
}

/** Script de página que dibuja un cursor y un anillo al hacer clic (headless no los pinta). */
export const CURSOR_VISIBLE = () => {
  const init = () => {
    const c = document.createElement('div');
    c.style.cssText =
      'position:fixed;top:0;left:0;width:22px;height:22px;margin:-3px 0 0 -3px;z-index:2147483647;pointer-events:none;' +
      "background:url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='22' height='22'><path d='M3 2l14 8-6 2-3 6z' fill='black' stroke='white' stroke-width='1.5'/></svg>\") no-repeat";
    document.body.appendChild(c);
    addEventListener('mousemove', (e) => (c.style.transform = `translate(${e.clientX}px,${e.clientY}px)`), true);
    addEventListener(
      'mousedown',
      (e) => {
        const r = document.createElement('div');
        r.style.cssText =
          `position:fixed;left:${e.clientX - 18}px;top:${e.clientY - 18}px;width:36px;height:36px;border-radius:50%;` +
          'border:3px solid rgba(37,89,224,.85);z-index:2147483646;pointer-events:none;transition:all .45s ease-out';
        document.body.appendChild(r);
        requestAnimationFrame(() => {
          r.style.transform = 'scale(1.8)';
          r.style.opacity = '0';
        });
        setTimeout(() => r.remove(), 500);
      },
      true,
    );
  };
  if (document.body) init();
  else document.addEventListener('DOMContentLoaded', init);
};

// QA — Paso "Precios" del asistente de proyecto nuevo (/projects/new?id=<borrador>).
// Código: frontend/components/wizard/step-3-prices.tsx, components/price-review.tsx,
//         backend/app/api/v1/price_lists.py, services/project_budget.py.
//
// Los casos corren EN ORDEN sobre un borrador propio "QA · Precios <hora>" que crea preparar()
// (IFC demo subido y procesado, sin presupuesto del proveedor). Primero los errores sin archivo,
// después la subida buena y lo que se hace con la lista cargada. No correr con --workers > 1.

import { readFileSync } from 'node:fs';

import config, { api, ARCHIVOS, token } from './_config.mjs';

const espera = (ms) => new Promise((r) => setTimeout(r, ms));

function formData(nombre, buffer, tipo) {
  const fd = new FormData();
  fd.append('file', new Blob([buffer], { type: tipo }), nombre);
  return fd;
}

/** PDF válido con texto pero sin ninguna tabla de precios. */
function pdfSinTabla() {
  const objs = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    null,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ];
  const texto = 'BT /F1 14 Tf 72 760 Td (Carta de presentacion - sin precios) Tj 0 -24 Td (Hola, les dejo nuestros datos.) Tj ET';
  objs[3] = `<< /Length ${texto.length} >>\nstream\n${texto}\nendstream`;
  let out = '%PDF-1.4\n';
  const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const xref = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
  for (const o of offs) out += `${String(o).padStart(10, '0')} 00000 n \n`;
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}

const JPG = Buffer.from('/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=', 'base64');

const PRESUPUESTO = () => ({
  name: 'presupuesto-corralon-demo.pdf', mimeType: 'application/pdf', buffer: readFileSync(ARCHIVOS.presupuesto),
});

const sesionInvalida = async (ctx) => {
  await ctx.addInitScript(() => localStorage.setItem('scalistai_token', 'token.vencido.invalido'));
};

/** Selector de "IVA de los precios" / "Reglas de cómputo" (los <select> del encabezado). */
const selectDe = (page, etiqueta) =>
  page.locator(`div:has(> div:text-is("${etiqueta}")) select`).first();

const siguiente = (page) => page.getByRole('button', { name: 'Siguiente →' });

/** Muestra en la página el resultado de una verificación por API, para que quede en la captura. */
async function cartel(page, texto) {
  await page.evaluate((t) => {
    const d = document.createElement('div');
    d.textContent = t;
    d.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#fffbe6;color:#000;' +
      'font:13px monospace;padding:6px 10px;border-bottom:2px solid #c90;white-space:pre-wrap';
    document.body.appendChild(d);
  }, texto);
}

/** Botón (círculo) del paso Precios en el stepper: el texto "Precios" está fuera del botón. */
const pasoPrecios = (page) => page.locator('ol li:has(span:text-is("Precios")) button');

/** Con lista ya subida el asistente abre en Ubicación (wizard_step 3): volver a Precios por el stepper. */
async function irAPrecios(page, h) {
  await h.esperarTexto(page, 'Nuevo proyecto', 60000);
  await h.settle(page, 800);
  if (!(await page.getByText('IVA de los precios').isVisible())) {
    await pasoPrecios(page).first().click();
    await h.settle(page, 800);
  }
  await h.esperarTexto(page, 'IVA de los precios', 30000);
}

export default {
  roles: { ...config.roles, vencido: sesionInvalida },

  async preparar() {
    const ids = await config.preparar();
    const hora = new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
    const ifc = () => formData('casa-demo.ifc', readFileSync(ARCHIVOS.ifc), 'application/octet-stream');
    const nuevo = async (sufijo) => {
      const p = await api(ids.adminId, 'POST', '/projects', { name: `QA · Precios ${hora} · ${sufijo}`, description: 'Borrador del QA (se puede borrar).' });
      await api(ids.adminId, 'POST', `/projects/${p.id}/plans`, ifc()); // wizard_step = 2 → abre en Precios
      return p.id;
    };
    // Borrador principal (camino feliz y lo que sigue). Comitente y capataz en el equipo: no deben ver precios.
    const qa = await nuevo('principal');
    await api(ids.adminId, 'POST', `/projects/${qa}/members`, { user_id: ids.usuarios.comitente, role: 'comitente' });
    await api(ids.adminId, 'POST', `/projects/${qa}/members`, { user_id: ids.usuarios.capataz, role: 'capataz' });
    // Un borrador limpio por cada archivo inválido que llega al backend: si uno queda guardado por error,
    // no contamina a los demás casos.
    const fresco = {};
    for (const k of ['renombrado', 'vacio', 'sintabla', 'xlsx', 'csv']) fresco[k] = await nuevo(k);
    for (let i = 0; i < 80; i++) {
      const planes = await api(ids.adminId, 'GET', `/projects/${qa}/plans`);
      if (planes[0]?.status === 'ready') break;
      if (/error|failed/.test(planes[0]?.status ?? '')) throw new Error(`IFC con error: ${planes[0].error_message}`);
      await espera(2500);
    }
    console.log(`preparar: proyecto QA #${qa}, frescos ${JSON.stringify(fresco)}`);
    return { ...ids, qa, fresco };
  },

  casos: (d) => {
    const url = `/projects/new?id=${d.qa}`;
    return [
      // ------------------------------------------------------------ sin archivo
      {
        id: 'precios-01-inicial',
        titulo: 'Paso Precios recién llegado (modelo ya procesado, sin presupuesto)',
        esperado: 'Stepper en "Precios", selector de reglas con "Estándar Argentina", zona para elegir el archivo ' +
          '("PDF con texto (no escaneado), Excel o CSV · máx 15 MB"), "Omitir por ahora" y "Siguiente →" deshabilitado.',
        rol: 'admin', url,
        pasos: async (page, h) => {
          await h.esperarTexto(page, 'Presupuesto del proveedor', 60000);
          await h.foto(page, 'inicial', { fullPage: true });
          if (!(await siguiente(page).isDisabled())) throw new Error('"Siguiente" está habilitado sin archivo');
        },
      },
      {
        id: 'precios-02-archivo-jpg',
        titulo: 'Error: elegir una foto (.jpg) como presupuesto',
        esperado: 'Aparece "Subí el presupuesto en PDF, Excel (.xlsx) o CSV." y no se sube nada (sigue la zona de carga).',
        rol: 'admin', url,
        pasos: async (page, h) => {
          await h.esperarTexto(page, 'Presupuesto del proveedor', 60000);
          await h.subir(page, h.archivo('foto-obra.jpg', JPG, 'image/jpeg'));
          await h.foto(page, 'error');
        },
      },
      {
        id: 'precios-03-jpg-renombrado-pdf',
        titulo: 'Error: una imagen renombrada a .pdf',
        esperado: 'Mensaje claro en español de que el archivo no es un PDF válido / no se pudo leer; no queda archivo cargado; sin 500.',
        rol: 'admin', url: `/projects/new?id=${d.fresco.renombrado}`, redEsperada: [400, 422],
        pasos: async (page, h) => {
          await h.esperarTexto(page, 'Presupuesto del proveedor', 60000);
          await h.subir(page, h.archivo('presupuesto.pdf', JPG, 'application/pdf'));
          await h.settle(page, 1500);
          await h.foto(page, 'error');
        },
      },
      {
        id: 'precios-04-archivo-vacio',
        titulo: 'Error: PDF vacío (0 bytes)',
        esperado: 'Mensaje claro ("el archivo está vacío" o similar); no se guarda nada; sin 500.',
        rol: 'admin', url: `/projects/new?id=${d.fresco.vacio}`, redEsperada: [400, 422],
        pasos: async (page, h) => {
          await h.esperarTexto(page, 'Presupuesto del proveedor', 60000);
          await h.subir(page, h.archivo('vacio.pdf', Buffer.alloc(0), 'application/pdf'));
          await h.settle(page, 1500);
          await h.foto(page, 'error');
        },
      },
      {
        id: 'precios-05-pdf-sin-tabla',
        titulo: 'Error: PDF con texto pero sin tabla de precios',
        esperado: 'Mensaje claro de que no se encontraron renglones/precios en el archivo; no queda un presupuesto con 0 renglones.',
        rol: 'admin', url: `/projects/new?id=${d.fresco.sintabla}`, redEsperada: [400, 422],
        pasos: async (page, h) => {
          await h.esperarTexto(page, 'Presupuesto del proveedor', 60000);
          await h.subir(page, h.archivo('carta-sin-precios.pdf', pdfSinTabla(), 'application/pdf'));
          await h.settle(page, 2000);
          await h.foto(page, 'resultado', { fullPage: true });
        },
      },
      {
        id: 'precios-06-xlsx-corrupto',
        titulo: 'Error: Excel corrupto (bytes al azar con extensión .xlsx)',
        esperado: 'Mensaje claro de que el Excel no se pudo leer; sin trazas ni 500.',
        rol: 'admin', url: `/projects/new?id=${d.fresco.xlsx}`, redEsperada: [400, 422],
        pasos: async (page, h) => {
          await h.esperarTexto(page, 'Presupuesto del proveedor', 60000);
          await h.subir(page, h.archivo('lista.xlsx', Buffer.from('esto no es un excel '.repeat(50)),
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'));
          await h.settle(page, 1500);
          await h.foto(page, 'error');
        },
      },
      {
        id: 'precios-07-csv-basura',
        titulo: 'Error: CSV sin columnas de precio',
        esperado: 'Mensaje claro de que no se encontraron precios; no se guarda una lista vacía.',
        rol: 'admin', url: `/projects/new?id=${d.fresco.csv}`, redEsperada: [400, 422],
        pasos: async (page, h) => {
          await h.esperarTexto(page, 'Presupuesto del proveedor', 60000);
          await h.subir(page, h.archivo('lista.csv', 'nombre;telefono\nJuan;123\nAna;456\n', 'text/csv'));
          await h.settle(page, 1500);
          await h.foto(page, 'resultado', { fullPage: true });
        },
      },
      {
        id: 'precios-08-archivo-grande',
        titulo: 'Error: PDF de 16 MB (supera el límite)',
        esperado: 'Aparece "El archivo supera los 15 MB." sin subir nada.',
        rol: 'admin', url,
        pasos: async (page, h) => {
          await h.esperarTexto(page, 'Presupuesto del proveedor', 60000);
          await h.subir(page, h.archivo('enorme.pdf', Buffer.alloc(16 * 1024 * 1024, 32), 'application/pdf'));
          await h.foto(page, 'error');
        },
      },
      {
        id: 'precios-09-red-caida',
        titulo: 'Error: se corta la conexión al subir',
        esperado: 'Mensaje claro en español ("No se pudo conectar…"), sin "Failed to fetch"; se puede reintentar.',
        rol: 'admin', url,
        pasos: async (page, h) => {
          await h.esperarTexto(page, 'Presupuesto del proveedor', 60000);
          await page.route(/\/price-list$/, (r) => (r.request().method() === 'POST' ? r.abort('internetdisconnected') : r.continue()));
          await h.subir(page, PRESUPUESTO());
          await h.foto(page, 'error');
        },
      },
      {
        id: 'precios-10-api-sin-guardar',
        titulo: 'Verificación: ningún archivo inválido quedó guardado como presupuesto',
        esperado: 'La API devuelve price_list = null en el borrador principal y en los 5 borradores de archivos inválidos.',
        rol: 'admin', url,
        pasos: async (page, h) => {
          const filas = [];
          for (const [k, id] of [['principal (jpg, 16 MB, red caída)', d.qa], ...Object.entries(d.fresco)]) {
            const v = await api(d.adminId, 'GET', `/projects/${id}/price-list`);
            const p = await api(d.adminId, 'GET', `/projects/${id}`);
            filas.push(`#${id} ${k}: price_list = ${v.price_list ? `"${v.price_list.filename}" (${v.price_list.lines.length} renglones)` : 'null'} · wizard_step = ${p.wizard_step}`);
          }
          await h.esperarTexto(page, 'Presupuesto del proveedor', 60000);
          await cartel(page, filas.join(String.fromCharCode(10)));
          await h.foto(page, 'api');
        },
      },
      {
        id: 'precios-11-subir-ok',
        titulo: 'Camino feliz: subir el presupuesto del corralón (PDF demo)',
        esperado: 'Encabezado con archivo, "13 renglones", reglas "Estándar Argentina", IVA "Detectar automáticamente" ' +
          '(detectado con IVA); KPIs Materiales/IVA/Total en $ es-AR sin NaN; tablas por medida; "Siguiente →" habilitado.',
        rol: 'admin', url,
        pasos: async (page, h) => {
          await h.esperarTexto(page, 'Presupuesto del proveedor', 60000);
          await h.subir(page, PRESUPUESTO());
          await h.esperarTexto(page, 'renglones', 60000);
          await h.settle(page, 1000);
          await h.foto(page, 'cargado');
          await h.foto(page, 'completo', { fullPage: true });
          if (await siguiente(page).isDisabled()) throw new Error('"Siguiente" sigue deshabilitado con archivo');
        },
      },
      {
        id: 'precios-12-iva',
        titulo: 'Forzar IVA: "No incluyen IVA" y "Incluyen IVA"',
        esperado: 'Con "No incluyen IVA" el neto sube (se usan tal cual) y el texto dice "Se usan tal cual…"; con "Incluyen IVA" ' +
          'dice "Se descuenta el 21%…"; los totales cambian coherentes (Total = Neto + 21%). Vuelve a "Detectar".',
        rol: 'admin', url,
        pasos: async (page, h) => {
          await irAPrecios(page, h);
          const iva = selectDe(page, 'IVA de los precios');
          await iva.selectOption('excluded'); await h.settle(page, 800);
          await h.foto(page, 'sin-iva');
          await iva.selectOption('included'); await h.settle(page, 800);
          await h.foto(page, 'con-iva');
          await iva.selectOption('auto'); await h.settle(page, 800);
          await h.foto(page, 'auto');
        },
      },
      {
        id: 'precios-13-cambiar-reglas',
        titulo: 'Cambiar el juego de reglas a "Obra económica" y volver',
        esperado: 'El presupuesto se recalcula con el otro juego (cambian cantidades o totales) sin errores; al volver a "Estándar Argentina" vuelven los valores originales.',
        rol: 'admin', url,
        pasos: async (page, h) => {
          await irAPrecios(page, h);
          const rs = selectDe(page, 'Reglas de cómputo');
          await h.foto(page, 'estandar');
          await rs.selectOption({ label: 'Obra económica' }); await h.settle(page, 1000);
          await h.foto(page, 'economica');
          await rs.selectOption({ label: 'Estándar Argentina' }); await h.settle(page, 1000);
          await h.foto(page, 'estandar-de-nuevo');
        },
      },
      {
        id: 'precios-14-renglon-incompatible',
        titulo: 'Error: elegir a mano un renglón de otra cosa para un ítem',
        esperado: 'El ítem muestra "Unidad incompatible" o el renglón elegido con "elegido a mano", sin NaN ni error; ' +
          'aparece "↺ Volver a la elección automática" y al usarlo vuelve al renglón original.',
        rol: 'admin', url,
        pasos: async (page, h) => {
          await irAPrecios(page, h);
          const sel = page.locator('table select').first();
          await sel.scrollIntoViewIfNeeded();
          const otros = await sel.locator('optgroup[label="Otro renglón del archivo"] option').evaluateAll((os) => os.map((o) => o.value));
          if (!otros.length) throw new Error('El primer ítem no ofrece "Otro renglón del archivo"');
          // el último suele ser de otro rubro (p. ej. hierro para un ladrillo)
          await sel.selectOption(otros[otros.length - 1]); await h.settle(page, 1000);
          await h.foto(page, 'elegido-a-mano');
          await page.locator('table select').first().selectOption('auto'); await h.settle(page, 1000);
          await h.foto(page, 'vuelta-a-auto');
        },
      },
      {
        id: 'precios-15-presentacion-invalida',
        titulo: 'Error: corregir la presentación de un renglón con letras, 0 y negativo',
        esperado: 'Con "abc", "0" o "-3" la app avisa que el valor no es válido (no se cierra en silencio); con "2,5" queda ' +
          '"x 2,5 …(corregido)" y "deshacer" lo vuelve atrás.',
        rol: 'admin', url,
        pasos: async (page, h) => {
          await irAPrecios(page, h);
          await h.click(page, /Renglones leídos del archivo/);
          const boton = () => page.getByTitle('Corregir la presentación').first();
          for (const [valor, nombre] of [['abc', 'letras'], ['0', 'cero'], ['-3', 'negativo']]) {
            await boton().click();
            const inp = page.locator('form input').first();
            await inp.fill(valor);
            await h.foto(page, `${nombre}-tipeado`, { elemento: 'section:has(button:has-text("Renglones leídos"))' });
            await page.locator('form button[type=submit]').first().click(); await h.settle(page, 800);
            await h.foto(page, `${nombre}-ok`, { elemento: 'section:has(button:has-text("Renglones leídos"))' });
          }
          await boton().click();
          await page.locator('form input').first().fill('2,5');
          await page.locator('form button[type=submit]').first().click(); await h.settle(page, 1200);
          await h.foto(page, 'coma-decimal', { elemento: 'section:has(button:has-text("Renglones leídos"))' });
          const deshacer = page.getByRole('button', { name: 'deshacer' }).first();
          if (await deshacer.isVisible()) { await deshacer.click(); await h.settle(page, 1200); }
          await h.foto(page, 'deshecho', { elemento: 'section:has(button:has-text("Renglones leídos"))' });
        },
      },
      {
        id: 'precios-16-reemplazar-por-jpg',
        titulo: 'Error: "Reemplazar archivo" con un .jpg teniendo ya la lista cargada',
        esperado: 'Aparece el error de formato y la lista anterior (13 renglones, totales) sigue intacta.',
        rol: 'admin', url,
        pasos: async (page, h) => {
          await irAPrecios(page, h);
          await h.subir(page, h.archivo('foto.jpg', JPG, 'image/jpeg'));
          await h.foto(page, 'error');
        },
      },
      {
        id: 'precios-17-reemplazar-por-invalido',
        titulo: 'Error: "Reemplazar archivo" con un PDF sin tabla teniendo la lista cargada',
        esperado: 'Error claro y la lista anterior NO se pierde (sigue presupuesto-corralon-demo.pdf con 13 renglones).',
        rol: 'admin', url, redEsperada: [400, 422],
        pasos: async (page, h) => {
          await irAPrecios(page, h);
          await h.subir(page, h.archivo('carta-sin-precios.pdf', pdfSinTabla(), 'application/pdf'));
          await h.settle(page, 2000);
          await h.foto(page, 'resultado');
        },
      },
      {
        id: 'precios-18-recargar',
        titulo: 'Recargar la página (F5) en el paso Precios',
        esperado: 'Vuelve al paso Precios (o al siguiente, pero con lo cargado intacto); nada se pierde ni se rompe.',
        rol: 'admin', url,
        pasos: async (page, h) => {
          await h.settle(page, 1500);
          // Ir a Precios desde el stepper (al abrir puede arrancar en el paso siguiente).
          const aPrecios = page.getByRole('button', { name: /Precios/ });
          if (await aPrecios.count()) { await aPrecios.first().click(); await h.settle(page, 1500); }
          h.nota(`URL antes de F5: ${page.url()}`);
          await h.foto(page, 'al-abrir');
          await page.reload(); await h.settle(page, 1500);
          await h.foto(page, 'tras-f5');
        },
      },
      {
        id: 'precios-19-volver-y-avanzar',
        titulo: 'Volver al paso Modelo y avanzar de nuevo',
        esperado: '"← Volver" lleva a Modelo BIM con el IFC; "Siguiente →" vuelve a Precios con la lista y totales intactos.',
        rol: 'admin', url,
        pasos: async (page, h) => {
          await h.settle(page, 1500);
          // si arrancó en Ubicación (wizard_step ≥ 3), saltar a Precios por el stepper
          if (!(await page.getByText('IVA de los precios').isVisible())) await pasoPrecios(page).click(); await h.settle(page, 800);
          await h.esperarTexto(page, 'IVA de los precios', 30000);
          await h.click(page, '← Volver');
          await h.foto(page, 'modelo');
          await h.click(page, 'Siguiente →');
          await h.esperarTexto(page, 'IVA de los precios', 30000);
          await h.foto(page, 'precios-de-nuevo');
        },
      },
      {
        id: 'precios-20-doble-clic-siguiente',
        titulo: 'Doble clic rápido en "Siguiente →"',
        esperado: 'Avanza un solo paso (Ubicación), no saltea a Revisión ni muestra errores.',
        rol: 'admin', url,
        pasos: async (page, h) => {
          await h.settle(page, 1500);
          if (!(await page.getByText('IVA de los precios').isVisible())) await pasoPrecios(page).click(); await h.settle(page, 800);
          await h.esperarTexto(page, 'IVA de los precios', 30000);
          await siguiente(page).dblclick(); await h.settle(page, 2000);
          await h.foto(page, 'despues');
        },
      },
      // ------------------------------------------------------------ URLs, sesión, permisos
      {
        id: 'precios-21-paso-posterior-sin-modelo',
        titulo: 'URL directa al asistente de un borrador que no tiene modelo',
        esperado: 'Abre en "Modelo BIM" (no deja saltar a Precios por el stepper) sin errores.',
        rol: 'admin', url: `/projects/new?id=${d.proyectos.borradorDatos}`,
        pasos: async (page, h) => {
          await h.settle(page, 1500);
          await h.foto(page, 'abre');
          await pasoPrecios(page).first().click({ timeout: 3000 }).catch(() => {});
          await h.settle(page, 800);
          await h.foto(page, 'clic-en-precios');
        },
      },
      {
        id: 'precios-22-id-inexistente',
        titulo: 'URL con un id de borrador que no existe',
        esperado: 'Mensaje claro "Proyecto no encontrado" con forma de volver; sin pantalla rota.',
        rol: 'admin', url: '/projects/new?id=999999', redEsperada: [404],
        pasos: async (page, h) => { await h.settle(page, 1500); await h.foto(page, 'pantalla'); },
      },
      {
        id: 'precios-23-sesion-vencida',
        titulo: 'Sesión vencida / token inválido en el paso Precios',
        esperado: 'Lleva a /login?next=… (vuelve al asistente al entrar); no queda una pantalla rota.',
        rol: 'vencido', url, redEsperada: [401],
        pasos: async (page, h) => { await h.settle(page, 2000); await h.foto(page, 'pantalla'); },
      },
      {
        id: 'precios-24-comitente',
        titulo: 'Permisos: el comitente del proyecto entra por URL al paso Precios',
        esperado: 'Aviso claro de que su rol no ve la información económica; no se ven precios ni se puede subir/cambiar nada.',
        rol: 'comitente', url, redEsperada: [403],
        pasos: async (page, h) => {
          await h.settle(page, 1500);
          if (!(await page.getByText('IVA de los precios').isVisible()) && await pasoPrecios(page).count())
            await pasoPrecios(page).first().click({ timeout: 3000 }).catch(() => {});
          await h.settle(page, 1200);
          await h.foto(page, 'pantalla', { fullPage: true });
        },
      },
      {
        id: 'precios-25-capataz',
        titulo: 'Permisos: el capataz entra por URL al paso Precios',
        esperado: 'Igual que el comitente: aviso claro, sin precios ni carga.',
        rol: 'capataz', url, redEsperada: [403],
        pasos: async (page, h) => {
          await h.settle(page, 1500);
          if (!(await page.getByText('IVA de los precios').isVisible()) && await pasoPrecios(page).count())
            await pasoPrecios(page).first().click({ timeout: 3000 }).catch(() => {});
          await h.settle(page, 1200);
          await h.foto(page, 'pantalla', { fullPage: true });
        },
      },
      {
        id: 'precios-26-comitente-api',
        titulo: 'Permisos (backend): el comitente intenta cambiar el IVA y subir un archivo por API',
        esperado: 'Las dos llamadas devuelven 403 y la lista del proyecto no cambia.',
        rol: 'admin', url,
        pasos: async (page, h) => {
          const r = [];
          for (const [m, cuerpo] of [['PATCH', JSON.stringify({ iva_mode: 'excluded' })], ['POST', formData('x.pdf', readFileSync(ARCHIVOS.presupuesto), 'application/pdf')]]) {
            const res = await fetch(`http://localhost:8100/api/v1/projects/${d.qa}/price-list`, {
              method: m, body: cuerpo,
              headers: { Authorization: `Bearer ${token(d.usuarios.comitente)}`, ...(m === 'PATCH' ? { 'Content-Type': 'application/json' } : {}) },
            });
            r.push(`${m} → ${res.status} ${(await res.text()).slice(0, 120)}`);
          }
          const v = await api(d.adminId, 'GET', `/projects/${d.qa}/price-list`);
          await h.esperarTexto(page, 'Nuevo proyecto', 60000);
          await cartel(page, `Como comitente:\n${r.join('\n')}\nIVA guardado ahora (admin): ${v.price_list?.iva_mode}`);
          await h.foto(page, 'api');
        },
      },
    ];
  },
};

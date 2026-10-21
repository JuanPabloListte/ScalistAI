// QA — Reglas de cómputo (/reglas, /reglas/[id]).
// Código: frontend/app/reglas/page.tsx, frontend/app/reglas/[id]/page.tsx,
//         backend/app/api/v1/rule_sets.py, schemas/rule_set.py.
//
// preparar() crea un juego propio "QA · Reglas <hora>" (copia del estándar) para editar sin tocar
// "Obra económica" del manual. Los casos que guardan van sobre ese juego. Correr con --workers 1.

import config, { api, token } from './_config.mjs';

const sesionInvalida = async (ctx) => {
  await ctx.addInitScript(() => localStorage.setItem('scalistai_token', 'token.vencido.invalido'));
};

async function cartel(page, texto) {
  await page.evaluate((t) => {
    const d = document.createElement('div');
    d.textContent = t;
    d.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#fffbe6;color:#000;' +
      'font:13px monospace;padding:6px 10px;border-bottom:2px solid #c90;white-space:pre-wrap';
    document.body.appendChild(d);
  }, texto);
}

/** Fila de la primera regla de material (Ladrillo portante 12, modo ladrillos). */
const fila = (page) => page.locator('div.grid:has(> div input[placeholder="Ej. Cemento"])').first();
const factor = (page) => fila(page).locator('input[inputmode="decimal"]').nth(0);
const desperdicio = (page) => fila(page).locator('input[inputmode="decimal"]').nth(1);
const guardar = (page) => page.getByRole('button', { name: 'Guardar cambios' });
const barra = 'div.fixed.bottom-0';

async function abrirEditor(page, h) {
  await h.esperarTexto(page, 'Reglas de cómputo', 60000);
  await page.locator('input[placeholder="Ej. Cemento"]').first().waitFor({ timeout: 60000 });
  await h.settle(page, 500);
}

/** Cambia un campo, guarda y saca dos fotos: fila + barra inferior. */
async function probarGuardar(page, h, loc, valor, nombre) {
  await loc.fill(valor);
  await guardar(page).click();
  await h.settle(page, 1200);
  await h.foto(page, `${nombre}-pantalla`);
  await h.foto(page, `${nombre}-barra`, { elemento: barra });
}

const juegosConNombre = async (uid, nombre) =>
  (await api(uid, 'GET', '/rule-sets')).filter((r) => r.name === nombre);

export default {
  roles: { ...config.roles, vencido: sesionInvalida },

  async preparar() {
    const ids = await config.preparar();
    const hora = new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
    const rs = await api(ids.adminId, 'POST', '/rule-sets', {
      name: `QA · Reglas ${hora}`, description: 'Juego del QA (se puede borrar).', copy_from_id: ids.ruleSetEstandar,
    });
    console.log(`preparar: juego QA #${rs.id}`);
    return { ...ids, juego: rs.id, juegoNombre: rs.name, hora };
  },

  casos: (d) => {
    const ed = `/reglas/${d.juego}`;
    return [
      // ------------------------------------------------------------ lista y permisos
      {
        id: 'reglas-01-lista-admin',
        titulo: 'Lista de juegos como admin de la org',
        esperado: '"Estándar Argentina" con insignias "Estándar" y "Por defecto", botones "Ver" y "Duplicar" (sin "Borrar"); ' +
          'los juegos de la org con "Editar", "Duplicar" y "Borrar"; botón "+ Nuevo juego".',
        rol: 'admin', url: '/reglas',
        pasos: async (page, h) => { await h.esperarTexto(page, 'Estándar Argentina', 60000); await h.foto(page, 'lista', { fullPage: true }); },
      },
      {
        id: 'reglas-02-lista-super',
        titulo: 'Lista de juegos como superadmin',
        esperado: 'El estándar aparece con "Editar" (el superadmin sí puede editarlo) y sigue sin "Borrar".',
        rol: 'super', url: '/reglas',
        pasos: async (page, h) => { await h.esperarTexto(page, 'Estándar Argentina', 60000); await h.foto(page, 'lista', { fullPage: true }); },
      },
      {
        id: 'reglas-03-lista-miembro',
        titulo: 'Permisos: lista como miembro sin rol admin (jefe de obra)',
        esperado: 'Texto "· Solo lectura.", sin "+ Nuevo juego", sin "Duplicar"/"Borrar"; todos los botones dicen "Ver".',
        rol: 'jefe', url: '/reglas',
        pasos: async (page, h) => { await h.esperarTexto(page, 'Estándar Argentina', 60000); await h.foto(page, 'lista', { fullPage: true }); },
      },
      {
        id: 'reglas-04-estandar-admin',
        titulo: 'Permisos: el admin abre el estándar (solo lo edita el superadmin)',
        esperado: 'Campos deshabilitados, sin "+ Agregar material", sin papelera y sin barra "Guardar cambios"; ' +
          'idealmente un aviso de que hay que duplicarlo para modificarlo.',
        rol: 'admin', url: `/reglas/${d.ruleSetEstandar}`,
        pasos: async (page, h) => { await abrirEditor(page, h); await h.foto(page, 'editor'); },
      },
      {
        id: 'reglas-05-miembro-url-directa',
        titulo: 'Permisos: miembro (computista) entra por URL al editor del juego de la org',
        esperado: 'Todo deshabilitado, sin barra de guardar ni botones de agregar/borrar.',
        rol: 'computista', url: ed,
        pasos: async (page, h) => { await abrirEditor(page, h); await h.foto(page, 'editor'); },
      },
      {
        id: 'reglas-06-backend-permisos',
        titulo: 'Permisos (backend): editar/borrar sin permiso por API',
        esperado: 'Admin PUT al estándar → 403; superadmin DELETE al estándar → 400; jefe PUT y DELETE al juego QA → 403. Nada cambia.',
        rol: 'admin', url: '/reglas',
        pasos: async (page, h) => {
          const est = await api(d.adminId, 'GET', `/rule-sets/${d.ruleSetEstandar}`);
          const qa = await api(d.adminId, 'GET', `/rule-sets/${d.juego}`);
          const cuerpo = (rs) => JSON.stringify({ name: rs.name + ' X', description: rs.description, rules: rs.rules });
          const llamar = async (uid, m, id, body) => {
            const r = await fetch(`http://localhost:8100/api/v1/rule-sets/${id}`, {
              method: m, body, headers: { Authorization: `Bearer ${token(uid)}`, 'Content-Type': 'application/json' },
            });
            return `${r.status} ${(await r.text()).slice(0, 110)}`;
          };
          const filas = [
            `admin PUT estándar → ${await llamar(d.adminId, 'PUT', d.ruleSetEstandar, cuerpo(est))}`,
            `super DELETE estándar → ${await llamar(d.superId, 'DELETE', d.ruleSetEstandar)}`,
            `jefe PUT juego QA → ${await llamar(d.usuarios.jefe, 'PUT', d.juego, cuerpo(qa))}`,
            `jefe DELETE juego QA → ${await llamar(d.usuarios.jefe, 'DELETE', d.juego)}`,
          ];
          const despues = await api(d.adminId, 'GET', `/rule-sets/${d.juego}`).catch(() => null);
          filas.push(`juego QA sigue existiendo: ${!!despues} · nombre: ${despues?.name}`);
          await h.esperarTexto(page, 'Estándar Argentina', 60000);
          await cartel(page, filas.join(String.fromCharCode(10)));
          await h.foto(page, 'api');
        },
      },
      {
        id: 'reglas-07-id-inexistente',
        titulo: 'URL de un juego que no existe',
        esperado: 'Mensaje "Juego de reglas no encontrado" con el link "← Reglas de cómputo"; sin pantalla rota.',
        rol: 'admin', url: '/reglas/999999', redEsperada: [404],
        pasos: async (page, h) => { await h.settle(page, 1500); await h.foto(page, 'pantalla'); },
      },
      {
        id: 'reglas-08-sesion-vencida',
        titulo: 'Sesión vencida en Reglas de cómputo',
        esperado: 'Lleva a /login?next=/reglas; no queda la pantalla rota.',
        rol: 'vencido', url: '/reglas', redEsperada: [401],
        pasos: async (page, h) => { await h.settle(page, 2000); await h.foto(page, 'pantalla'); },
      },
      // ------------------------------------------------------------ crear / duplicar
      {
        id: 'reglas-09-nuevo-nombre-vacio',
        titulo: 'Error: "+ Nuevo juego" con nombre vacío o solo espacios',
        esperado: 'El botón "Crear" queda deshabilitado con el nombre vacío y con "   "; no se crea nada.',
        rol: 'admin', url: '/reglas',
        pasos: async (page, h) => {
          await h.esperarTexto(page, 'Estándar Argentina', 60000);
          await h.click(page, '+ Nuevo juego');
          await h.foto(page, 'modal');
          await h.llenar(page, 'css=input[placeholder="Ej. Obra económica"]', '');
          await h.foto(page, 'vacio');
          await h.llenar(page, 'css=input[placeholder="Ej. Obra económica"]', '   ');
          await h.foto(page, 'espacios');
          if (!(await page.getByRole('button', { name: 'Crear', exact: true }).isDisabled())) throw new Error('"Crear" habilitado con solo espacios');
        },
      },
      {
        id: 'reglas-10-nuevo-escape',
        titulo: 'Cancelar el diálogo con Escape y con clic afuera',
        esperado: 'El diálogo se cierra y no se crea ningún juego con ese nombre.',
        rol: 'admin', url: '/reglas',
        pasos: async (page, h) => {
          const nombre = `QA · Cancelado ${d.hora}`;
          await h.esperarTexto(page, 'Estándar Argentina', 60000);
          await h.click(page, '+ Nuevo juego');
          await h.llenar(page, 'css=input[placeholder="Ej. Obra económica"]', nombre);
          await page.keyboard.press('Escape'); await h.settle(page, 500);
          await h.foto(page, 'tras-escape');
          // Si Escape no lo cerró (hallazgo), cerrarlo con "Cancelar" para seguir.
          if (await page.getByRole('button', { name: 'Cancelar' }).isVisible()) await h.click(page, 'Cancelar');
          await h.click(page, '+ Nuevo juego');
          await h.llenar(page, 'css=input[placeholder="Ej. Obra económica"]', nombre);
          await page.mouse.click(10, 450); await h.settle(page, 500);
          await h.foto(page, 'tras-clic-afuera');
          const n = (await juegosConNombre(d.adminId, nombre)).length;
          await cartel(page, `Juegos creados con "${nombre}": ${n}`);
          await h.foto(page, 'api');
        },
      },
      {
        id: 'reglas-11-nombre-especial-doble-clic',
        titulo: 'Crear con caracteres especiales y doble clic en "Crear"',
        esperado: 'Se crea UN solo juego; el nombre `Ñandú & Hijos <b>"S.A."</b> 🏗️` se ve tal cual (sin negrita) en el editor y en la lista.',
        rol: 'admin', url: '/reglas',
        pasos: async (page, h) => {
          const nombre = `QA · Ñandú & Hijos <b>"S.A."</b> 🏗️ ${d.hora}`;
          await h.esperarTexto(page, 'Estándar Argentina', 60000);
          await h.click(page, '+ Nuevo juego');
          await h.llenar(page, 'css=input[placeholder="Ej. Obra económica"]', nombre);
          await page.getByRole('button', { name: 'Crear', exact: true }).dblclick();
          await page.waitForURL(/\/reglas\/\d+$/, { timeout: 30000 });
          await abrirEditor(page, h);
          await h.foto(page, 'editor');
          await page.goto('http://localhost:3100/reglas'); await h.settle(page, 1000);
          const n = (await juegosConNombre(d.adminId, nombre)).length;
          await cartel(page, `Juegos creados con ese nombre: ${n}`);
          await h.foto(page, 'lista', { fullPage: true });
        },
      },
      {
        id: 'reglas-12-duplicar',
        titulo: 'Camino feliz: duplicar el estándar',
        esperado: 'El diálogo propone "Estándar Argentina (copia)" partiendo de la copia del estándar; al crear abre el editor ' +
          'de la copia, editable, con las mismas 30 reglas.',
        rol: 'admin', url: '/reglas',
        pasos: async (page, h) => {
          await h.esperarTexto(page, 'Estándar Argentina', 60000);
          await page.locator('li:has-text("Estándar Argentina")').first().getByRole('button', { name: 'Duplicar' }).click();
          await h.settle(page, 500);
          await h.llenar(page, 'css=input[placeholder="Ej. Obra económica"]', `QA · Copia estándar ${d.hora}`);
          await h.foto(page, 'modal');
          await page.getByRole('button', { name: 'Crear', exact: true }).click();
          await page.waitForURL(/\/reglas\/\d+$/, { timeout: 30000 });
          await abrirEditor(page, h);
          await h.foto(page, 'editor');
        },
      },
      // ------------------------------------------------------------ editor (juego QA)
      {
        id: 'reglas-13-pestanas-filtro',
        titulo: 'Pestañas por medida y el buscador',
        esperado: 'Pestaña "Muros" muestra solo muros; el buscador con "cemento" muestra "N de 30 reglas" y solo las que coinciden; ' +
          'un texto sin coincidencias no deja la pantalla muda.',
        rol: 'admin', url: ed,
        pasos: async (page, h) => {
          await abrirEditor(page, h);
          await h.foto(page, 'todas');
          await page.getByRole('button', { name: /^Muros/ }).click(); await h.settle(page, 400);
          await h.foto(page, 'muros');
          await page.getByRole('button', { name: /^Todas/ }).click();
          await h.llenar(page, 'css=input[placeholder="Buscar producto, palabra clave o nota…"]', 'cemento'); await h.settle(page, 400);
          await h.foto(page, 'filtro-cemento');
          await h.llenar(page, 'css=input[placeholder="Buscar producto, palabra clave o nota…"]', 'zzzz'); await h.settle(page, 400);
          await h.foto(page, 'filtro-sin-resultados');
        },
      },
      {
        id: 'reglas-14-sin-palabras-clave',
        titulo: 'Error: guardar una regla sin palabras clave',
        esperado: 'Barra inferior: "\\"Ladrillo portante 12\\": falta al menos una palabra para buscar en el PDF." y no se guarda.',
        rol: 'admin', url: ed,
        pasos: async (page, h) => {
          await abrirEditor(page, h);
          await probarGuardar(page, h, fila(page).locator('input[placeholder="cemento, cemento portland"]'), '  ,  ', 'sin-palabras');
        },
      },
      {
        id: 'reglas-15-producto-vacio',
        titulo: 'Error: guardar una regla sin nombre de producto',
        esperado: '"Hay una regla sin nombre de producto." y no se guarda.',
        rol: 'admin', url: ed,
        pasos: async (page, h) => {
          await abrirEditor(page, h);
          await probarGuardar(page, h, fila(page).locator('input[placeholder="Ej. Cemento"]'), '   ', 'sin-nombre');
        },
      },
      {
        id: 'reglas-16-factor-letras',
        titulo: 'Error: cantidad (factor) con letras',
        esperado: 'Mensaje claro de que la cantidad tiene que ser un número; no se guarda.',
        rol: 'admin', url: ed,
        pasos: async (page, h) => { await abrirEditor(page, h); await probarGuardar(page, h, factor(page), 'quince', 'letras'); },
      },
      {
        id: 'reglas-17-factor-negativo',
        titulo: 'Error: cantidad negativa',
        esperado: 'Mensaje claro de que la cantidad no puede ser negativa; no se guarda.',
        rol: 'admin', url: ed,
        pasos: async (page, h) => { await abrirEditor(page, h); await probarGuardar(page, h, factor(page), '-5', 'negativo'); },
      },
      {
        id: 'reglas-18-factor-miles',
        titulo: 'Cantidad con separador de miles y coma decimal ("1.234,5")',
        esperado: 'Se interpreta 1234,5 (formato argentino) o se avisa claramente el formato esperado; nunca se guarda otro número.',
        rol: 'admin', url: ed,
        pasos: async (page, h) => {
          await abrirEditor(page, h);
          await probarGuardar(page, h, factor(page), '1.234,5', 'miles');
          const v = (await api(d.adminId, 'GET', `/rule-sets/${d.juego}`)).rules[0];
          await cartel(page, `Guardado en la API: ${v.label} → factor ${v.factor}`);
          await h.foto(page, 'api');
        },
      },
      {
        id: 'reglas-19-coma-decimal',
        titulo: 'Camino feliz: cantidad con coma decimal ("16,5") y recarga',
        esperado: '"Cambios guardados."; al recargar la cantidad es 16,5 (o 16.5) y la API guarda 16.5.',
        rol: 'admin', url: ed,
        pasos: async (page, h) => {
          await abrirEditor(page, h);
          await probarGuardar(page, h, factor(page), '16,5', 'guardado');
          await page.reload(); await abrirEditor(page, h);
          await h.foto(page, 'tras-recargar', { elemento: 'div.grid:has(> div input[placeholder="Ej. Cemento"]) >> nth=0' });
          const v = (await api(d.adminId, 'GET', `/rule-sets/${d.juego}`)).rules[0];
          await cartel(page, `Guardado en la API: ${v.label} → factor ${v.factor}`);
          await h.foto(page, 'api');
        },
      },
      {
        id: 'reglas-20-desperdicio-letras',
        titulo: 'Error: desperdicio con letras ("cinco")',
        esperado: 'Mensaje de que el desperdicio tiene que ser un número; NO se guarda en silencio como 0 %.',
        rol: 'admin', url: ed,
        pasos: async (page, h) => {
          await abrirEditor(page, h);
          await probarGuardar(page, h, desperdicio(page), 'cinco', 'letras');
          const v = (await api(d.adminId, 'GET', `/rule-sets/${d.juego}`)).rules[0];
          await cartel(page, `Guardado en la API: ${v.label} → waste_pct ${v.waste_pct}`);
          await h.foto(page, 'api');
        },
      },
      {
        id: 'reglas-21-desperdicio-negativo',
        titulo: 'Error: desperdicio negativo ("-10")',
        esperado: 'Mensaje claro en español junto a la barra ("el desperdicio va de 0 a 100 %"); sin texto técnico tipo "body.rules.0…".',
        rol: 'admin', url: ed, redEsperada: [422],
        pasos: async (page, h) => { await abrirEditor(page, h); await probarGuardar(page, h, desperdicio(page), '-10', 'negativo'); },
      },
      {
        id: 'reglas-22-desperdicio-150',
        titulo: 'Error: desperdicio absurdo ("150")',
        esperado: 'Mensaje claro en español (máximo 100 %); sin texto técnico.',
        rol: 'admin', url: ed, redEsperada: [422],
        pasos: async (page, h) => { await abrirEditor(page, h); await probarGuardar(page, h, desperdicio(page), '150', 'absurdo'); },
      },
      {
        id: 'reglas-23-material-nuevo-vacio',
        titulo: 'Error: "+ Agregar material" y guardar sin completar',
        esperado: 'Aparece una fila nueva vacía; al guardar: "Hay una regla sin nombre de producto." y no se guarda.',
        rol: 'admin', url: ed,
        pasos: async (page, h) => {
          await abrirEditor(page, h);
          await page.getByRole('button', { name: /^Muros/ }).click();
          await page.getByRole('button', { name: '+ Agregar material' }).first().click(); await h.settle(page, 400);
          await guardar(page).click(); await h.settle(page, 800);
          await h.foto(page, 'pantalla', { fullPage: true });
        },
      },
      {
        id: 'reglas-24-mano-de-obra',
        titulo: 'Mano de obra: rendimiento con letras y precio "12.500"',
        esperado: 'Rendimiento "ocho" → mensaje de que tiene que ser un número. Precio "12.500" → se guarda 12500 (formato es-AR) ' +
          'o se avisa; nunca 12,5.',
        rol: 'admin', url: ed,
        pasos: async (page, h) => {
          await abrirEditor(page, h);
          await page.getByRole('button', { name: /^Muros/ }).click();
          await page.getByRole('button', { name: '+ Agregar mano de obra' }).first().click(); await h.settle(page, 400);
          const tarea = page.locator('input[placeholder="Mano de obra: mampostería"]').last();
          const filaMO = page.locator('div.grid:has(input[placeholder="Mano de obra: mampostería"])').last();
          await tarea.fill('Mano de obra: QA muro');
          await filaMO.locator('input[placeholder="8"]').fill('ocho');
          await filaMO.locator('input[placeholder="lo carga cada proyecto"]').fill('12.500');
          await guardar(page).click(); await h.settle(page, 800);
          await filaMO.scrollIntoViewIfNeeded();
          await h.foto(page, 'rendimiento-letras');
          await filaMO.locator('input[placeholder="8"]').fill('8');
          await guardar(page).click(); await h.settle(page, 1200);
          await h.foto(page, 'guardado');
          const r = (await api(d.adminId, 'GET', `/rule-sets/${d.juego}`)).rules.find((x) => x.label === 'Mano de obra: QA muro');
          await cartel(page, `Guardado en la API: daily_yield ${r?.daily_yield} · unit_price ${r?.unit_price} (se tipeó "12.500")`);
          await h.foto(page, 'api');
        },
      },
      {
        id: 'reglas-25-texto-largo',
        titulo: 'Nombre del juego de 500 caracteres',
        esperado: 'El campo corta a 120 caracteres; el diseño no se rompe.',
        rol: 'admin', url: ed,
        pasos: async (page, h) => {
          await abrirEditor(page, h);
          const nombre = page.locator('section label:has-text("Nombre") input');
          await nombre.fill('Juego larguísimo '.repeat(30));
          const largo = (await nombre.inputValue()).length;
          await cartel(page, `Largo del nombre en el campo: ${largo}`);
          await h.foto(page, 'pantalla');
        },
      },
      {
        id: 'reglas-26-salir-sin-guardar',
        titulo: 'Salir con cambios sin guardar por el link "← Reglas de cómputo"',
        esperado: 'Antes de salir pregunta si descartar los cambios (o los conserva); no se pierden en silencio.',
        rol: 'admin', url: ed,
        pasos: async (page, h) => {
          await abrirEditor(page, h);
          page.on('dialog', (dlg) => dlg.dismiss());
          await factor(page).fill('99');
          await h.foto(page, 'con-cambios');
          await page.getByRole('link', { name: '← Reglas de cómputo' }).click(); await h.settle(page, 1200);
          await h.foto(page, 'despues-del-link');
        },
      },
      {
        id: 'reglas-27-descartar',
        titulo: 'Cambiar algo y "Descartar"',
        esperado: 'Muestra "Hay cambios sin guardar."; "Descartar" devuelve los valores guardados y deshabilita los botones.',
        rol: 'admin', url: ed,
        pasos: async (page, h) => {
          await abrirEditor(page, h);
          await factor(page).fill('77');
          await h.foto(page, 'con-cambios', { elemento: barra });
          await h.click(page, 'Descartar');
          await h.foto(page, 'descartado');
        },
      },
      // ------------------------------------------------------------ borrar
      {
        id: 'reglas-28-borrar',
        titulo: 'Borrar un juego de la org: cancelar y confirmar',
        esperado: 'El diálogo "¿Borrar …?" explica que los proyectos pasan al estándar; con "Cancelar" no pasa nada; con "Borrar" desaparece de la lista.',
        rol: 'admin', url: '/reglas',
        pasos: async (page, h) => {
          await h.esperarTexto(page, d.juegoNombre, 60000);
          const card = page.locator(`li:has-text("${d.juegoNombre}")`).first();
          await card.getByRole('button', { name: 'Borrar' }).click(); await h.settle(page, 400);
          await h.foto(page, 'confirmar');
          await h.click(page, 'Cancelar');
          await h.foto(page, 'cancelado');
          await card.getByRole('button', { name: 'Borrar' }).click(); await h.settle(page, 400);
          await page.locator('[role="dialog"], .fixed').getByRole('button', { name: 'Borrar', exact: true }).last().click();
          await h.settle(page, 1200);
          await h.foto(page, 'borrado', { fullPage: true });
        },
      },
    ];
  },
};

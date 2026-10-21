// QA de la página Presupuesto: pestañas Materiales / Mano de obra, filtros, avisos de
// cordura del modelo y precio de venta. Proyecto "activo" del entorno demo (Casa Los Aromos).

import { api } from './_config.mjs';

export default {
  casos: (d) => {
    const url = `/projects/${d.proyectos.activo}/presupuesto`;
    const lab = `${url}?tab=mano-de-obra`;
    return [
      {
        id: 'presupuesto-01-materiales',
        titulo: 'Pestaña Materiales por defecto',
        esperado: 'Pestañas "Materiales N" (activa) y "Mano de obra N"; buscador "Buscar producto o renglón del proveedor…" y select "Todas" DENTRO de la tarjeta de Materiales; Precio de venta abajo a todo el ancho de su tarjeta.',
        rol: 'admin', url,
        pasos: async (page, h) => {
          await h.campo(page, 'Buscar producto o renglón del proveedor…').waitFor({ state: 'visible' });
          await h.foto(page, 'materiales');
          await h.foto(page, 'precio-venta', { elemento: 'section:has(h2:text("Precio de venta"))' });
        },
      },
      {
        id: 'presupuesto-02-filtro-materiales',
        titulo: 'Filtrar materiales por texto y medida',
        esperado: 'Con "cemento" quedan solo ítems de cemento y aparece "N de M ítems" + "Limpiar"; con un texto que no existe: "Ningún ítem coincide con el filtro."; "Limpiar" vuelve a mostrar todo.',
        rol: 'admin', url,
        pasos: async (page, h) => {
          await h.llenar(page, 'Buscar producto o renglón del proveedor…', 'cemento');
          await h.settle(page, 400);
          await h.foto(page, 'cemento');
          await h.llenar(page, 'Buscar producto o renglón del proveedor…', 'zzzz-no-existe');
          await h.settle(page, 400);
          await h.foto(page, 'sin-resultados');
          await h.click(page, 'Limpiar');
          await h.foto(page, 'limpio');
        },
      },
      {
        id: 'presupuesto-03-mano-de-obra',
        titulo: 'Pestaña Mano de obra con su filtro dentro de la tarjeta',
        esperado: 'Pestaña "Mano de obra" activa; el buscador "Buscar tarea de mano de obra…" y el select "Todos" están DENTRO de la tarjeta de mano de obra (no sueltos arriba); tareas agrupadas por rubro.',
        rol: 'admin', url: lab,
        pasos: async (page, h) => {
          await h.campo(page, 'Buscar tarea de mano de obra…').waitFor({ state: 'visible' });
          await h.foto(page, 'mano-de-obra');
        },
      },
      {
        id: 'presupuesto-04-filtro-rubro',
        titulo: 'Filtrar mano de obra por rubro y F5 conserva la pestaña',
        esperado: 'Al elegir un rubro quedan solo sus tareas con "N de M ítems"; tras recargar la página sigue en la pestaña Mano de obra (la URL tiene ?tab=mano-de-obra).',
        rol: 'admin', url: lab,
        pasos: async (page, h) => {
          const sel = page.locator('select[aria-label="Rubro"]');
          const opciones = await sel.locator('option').allTextContents();
          h.nota(`Rubros disponibles: ${opciones.join(', ')}`);
          if (opciones.length > 1) await sel.selectOption({ index: 1 });
          await h.settle(page, 400);
          await h.foto(page, 'rubro');
          await page.reload();
          await h.settle(page);
          await h.foto(page, 'tras-f5');
        },
      },
      {
        id: 'presupuesto-05-avisos',
        titulo: 'Avisos de cordura del modelo',
        esperado: 'Si la API devuelve measures.alerts, arriba de la revisión de materiales aparece "Revisá el modelo" con cada aviso (rojo = alto, ámbar = medio), en castellano.',
        rol: 'admin', url,
        pasos: async (page, h, dd) => {
          const v = await api(dd.adminId, 'GET', `/projects/${dd.proyectos.activo}/price-list`);
          const alerts = v.measures?.alerts ?? [];
          h.nota(`La API devuelve ${alerts.length} aviso(s): ${alerts.map((a) => `[${a.level}] ${a.message}`).join(' | ') || '—'}`);
          await h.foto(page, 'avisos');
        },
      },
      {
        id: 'presupuesto-06-comitente',
        titulo: 'Permisos: el comitente no ve la plata',
        esperado: 'El comitente no ve precios ni totales del presupuesto (aviso de sin acceso o redirección a Obra); nunca un error técnico.',
        rol: 'comitente', url,
        redEsperada: [403],
        pasos: async (page, h) => {
          await h.foto(page, 'comitente');
        },
      },
    ];
  },
};

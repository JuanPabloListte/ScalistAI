// QA de la barra de navegación del proyecto (Presupuesto · Cronograma · Obra · Cambios).
// Proyecto "activo" del entorno demo (Casa Los Aromos).

export default {
  casos: (d) => {
    const base = `/projects/${d.proyectos.activo}`;
    const pantallas = [
      ['presupuesto', 'Presupuesto'],
      ['gantt', 'Cronograma'],
      ['obra', 'Obra'],
      ['changes', 'Cambios'],
    ];
    return [
      ...pantallas.map(([ruta, pestana], i) => ({
        id: `nav-0${i + 1}-${ruta}`,
        titulo: `Barra del proyecto en ${pestana}`,
        esperado: `Arriba "← Proyectos", el nombre del proyecto y las pestañas Presupuesto · Cronograma · Obra · Cambios con "${pestana}" activa (subrayada); sin "← Volver" propio de la página ni título duplicado.`,
        rol: 'admin', url: `${base}/${ruta}`,
        pasos: async (page, h) => {
          await h.settle(page, 2500);
          await h.foto(page, ruta);
        },
      })),
      {
        id: 'nav-05-navegar',
        titulo: 'Ir de una pestaña a otra',
        esperado: 'Clic en Cronograma lleva al cronograma con esa pestaña activa; clic en "← Proyectos" vuelve a la lista.',
        rol: 'admin', url: `${base}/presupuesto`,
        pasos: async (page, h) => {
          await h.settle(page, 2000);
          await page.getByRole('link', { name: 'Cronograma' }).first().click();
          await h.settle(page, 2500);
          h.nota(`URL tras clic: ${page.url()}`);
          await h.foto(page, 'cronograma');
          await page.getByRole('link', { name: /Proyectos/ }).first().click();
          await h.settle(page, 2000);
          h.nota(`URL tras "← Proyectos": ${page.url()}`);
          await h.foto(page, 'lista');
        },
      },
      {
        id: 'nav-06-comitente',
        titulo: 'Comitente: solo Cronograma y Obra',
        esperado: 'El comitente ve solo las pestañas Cronograma y Obra (sin Presupuesto ni Cambios); nada parpadea ni aparece un error.',
        rol: 'comitente', url: `${base}/obra`,
        pasos: async (page, h) => {
          await h.settle(page, 2500);
          await h.foto(page, 'obra');
        },
      },
      {
        id: 'nav-07-movil',
        titulo: 'Barra en celular (375 px)',
        esperado: 'La barra entra o se desplaza de costado; no rompe el ancho de la página ni se superpone con el contenido.',
        rol: 'admin', url: `${base}/presupuesto`,
        pasos: async (page, h) => {
          await page.setViewportSize({ width: 375, height: 812 });
          await page.reload(); await h.settle(page, 2500);
          await h.foto(page, 'movil');
          const ancho = await page.evaluate(() => document.documentElement.scrollWidth);
          h.nota(`Ancho del documento: ${ancho}px (viewport 375)`);
        },
      },
      {
        id: 'nav-08-reglas-pestanas',
        titulo: 'Pestañas de Reglas que no entran',
        esperado: 'Se nota que hay más pestañas a la derecha (borde que se desvanece) y se pueden desplazar.',
        rol: 'admin', url: `/reglas`,
        pasos: async (page, h) => {
          await h.esperarTexto(page, 'Estándar Argentina', 60000);
          await page.getByRole('link', { name: 'Ver' }).or(page.getByRole('button', { name: 'Ver' })).first().click();
          await h.settle(page, 2000);
          await h.foto(page, 'pestanas');
        },
      },
    ];
  },
};

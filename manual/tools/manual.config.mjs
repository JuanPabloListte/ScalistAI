// manual.config.mjs — qué capturar y cómo autenticar cada rol (lo usan capturar.mjs y grabar-videos.mjs).
// Entorno: .\entorno-demo.ps1 up + web, datos: node cargar-datos-demo.mjs (deja datos-demo/ids.json).

import { readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

import { firmarJwt } from './token-jwt.mjs';

const BASE = 'http://localhost:3100'; // front del manual (no el 3000 de desarrollo)
const API = 'http://localhost:8100/api/v1'; // API del manual
const SECRETO_JWT = 'manual-demo-jwt-secret-solo-local-0123456789abcdef'; // = docker-compose.manual.yml

const ids0 = JSON.parse(readFileSync(new URL('./datos-demo/ids.json', import.meta.url), 'utf8'));
const tokenDe = (id) => firmarJwt({ secreto: SECRETO_JWT, payload: { sub: String(id) } });

// La app guarda la sesión en localStorage["scalistai_token"].
const sesion = (id) => async (context) => {
  await context.addInitScript((t) => window.localStorage.setItem('scalistai_token', t), tokenDe(id));
};

async function api(id, path) {
  const r = await fetch(`${API}${path}`, { headers: { authorization: `Bearer ${tokenDe(id)}` } });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

// El PDF del presupuesto se baja de la API y se abre en el visor de Chrome, sin barra
// y con la primera hoja entera (A4 ≈ 1:1,414).
const verPdf = (id, path, nombre) => async (page) => {
  const r = await fetch(`${API}${path}`, { headers: { authorization: `Bearer ${tokenDe(id)}` } });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  const archivo = join(tmpdir(), `manual-${nombre}.pdf`);
  writeFileSync(archivo, Buffer.from(await r.arrayBuffer()));
  await page.setViewportSize({ width: 1000, height: 1400 });
  await page.goto(`${pathToFileURL(archivo).href}#toolbar=0&navpanes=0&view=FitH`);
  await page.waitForTimeout(3000);
};

// Lleva un título de la página arriba de todo (para capturar una sección del medio).
const irA = (texto) => async (page) => {
  const el = page.getByRole('heading', { name: texto, exact: true }).first();
  await el.evaluate((n) => { n.scrollIntoView({ block: 'start' }); window.scrollBy(0, -24); });
};

const SUPER = 'superadmin';
const ADMIN = 'admin';
const JEFE = 'jefe';
const CAPATAZ = 'capataz';

export default {
  baseUrl: BASE,
  outDir: '../img',
  videosDir: '../videos',
  viewport: { width: 1440, height: 900 },
  locale: 'es-AR',
  timezoneId: 'America/Argentina/Buenos_Aires',

  cssLimpio: `
    /* Marcadores del mapa y controles de Mapbox se dejan; se oculta el aviso de atribución grande. */
    .mapboxgl-ctrl-attrib-inner { display: none !important; }
    /* Capturas de página completa: la barra lateral fija acompaña todo el alto.
       (Solo en la app: en el visor de PDF de Chrome deja la hoja en blanco.) */
    body:has(aside.fixed) { position: relative; }
    aside.fixed { position: absolute !important; }
  `,

  roles: {
    [SUPER]: sesion(ids0.superId),
    [ADMIN]: sesion(ids0.adminId),
    [JEFE]: sesion(ids0.usuarios.jefe),
    [CAPATAZ]: sesion(ids0.usuarios.capataz),
  },

  async preparar() {
    const juegos = await api(ids0.adminId, '/rule-sets');
    return {
      ...ids0,
      juegoOrg: juegos.find((j) => j.name === 'Obra económica')?.id,
      juegoEstandar: juegos.find((j) => j.is_system)?.id,
    };
  },

  capturas: (ids, h) => {
    const P = ids.proyectos;
    // Los círculos del stepper no tienen nombre accesible: se busca el <li> por su etiqueta.
    const paso = (nombre) => async (p) => {
      await p.locator('ol li', { hasText: nombre }).locator('button').click();
    };
    return [
      // Acceso
      { id: 'acceso-landing', rol: null, url: '/' },
      { id: 'acceso-login', rol: null, url: '/login' },

      // Navegación y proyectos
      { id: 'proyectos-lista', rol: ADMIN, url: '/projects', esperar: 'Casa Los Aromos' },
      { id: 'navegacion-menu-perfil', rol: ADMIN, url: '/projects', esperar: 'Casa Los Aromos',
        pasos: (p) => p.getByRole('button', { name: 'Perfil y opciones' }).click() },
      { id: 'proyectos-editar', rol: ADMIN, url: '/projects', esperar: 'Casa Los Aromos',
        pasos: async (p) => {
          await p.getByText('Casa Los Aromos').first().hover();
          await p.getByRole('button', { name: 'Editar proyecto' }).first().click();
        } },
      { id: 'proyectos-eliminar', rol: ADMIN, url: '/projects', esperar: 'Casa Los Aromos',
        pasos: async (p) => {
          // Las tarjetas van de la más nueva a la más vieja: la primera es el local (borrador).
          await p.getByText('Local comercial Av. Colón').first().hover();
          await p.getByRole('button', { name: 'Eliminar proyecto' }).first().click();
        } },

      // Asistente de proyecto nuevo
      { id: 'wizard-datos', rol: ADMIN, url: '/projects/new', esperar: 'Datos del proyecto' },
      { id: 'wizard-modelo', rol: ADMIN, url: `/projects/new?id=${P.borradorPrecios}`, pasos: paso('Modelo BIM'),
        esperar: 'Calidad del modelo' },
      { id: 'wizard-precios-vacio', rol: ADMIN, url: `/projects/new?id=${P.borradorPrecios}`,
        esperar: 'Presupuesto del proveedor' },
      { id: 'wizard-precios-revision', rol: ADMIN, url: `/projects/new?id=${P.activo}&edit=1`, pasos: paso('Precios'),
        esperar: 'Total con IVA' },
      { id: 'wizard-ubicacion', rol: ADMIN, url: `/projects/new?id=${P.activo}&edit=1`,
        esperar: 'Localización del proyecto' },
      { id: 'wizard-revision', rol: ADMIN, url: `/projects/new?id=${P.activo}&edit=1`, pasos: paso('Revisión'),
        esperar: 'Revisar y crear', fullPage: true },

      // Presupuesto del proyecto
      { id: 'presupuesto-resumen', rol: ADMIN, url: `/projects/${P.activo}/presupuesto`, esperar: 'Lista de compras' },
      { id: 'presupuesto-renglones', rol: ADMIN, url: `/projects/${P.activo}/presupuesto`, esperar: 'Lista de compras',
        pasos: async (p) => {
          await p.getByText(/Renglones leídos del archivo/).first().click();
          await p.getByText(/Lista de compras/).first().evaluate((el) => el.scrollIntoView({ block: 'start' }));
        } },
      { id: 'presupuesto-medidas', rol: ADMIN, url: `/projects/${P.activo}/presupuesto`, esperar: 'Lista de compras',
        pasos: async (p) => {
          await p.getByText(/Medidas del modelo/).first().click();
          await p.getByText(/Medidas del modelo/).first().evaluate((el) => el.scrollIntoView({ block: 'start' }));
        } },
      { id: 'presupuesto-mano-de-obra', rol: ADMIN, url: `/projects/${P.activo}/presupuesto`, esperar: 'Lista de compras',
        pasos: irA('Mano de obra') },
      { id: 'presupuesto-jornales', rol: ADMIN, url: `/projects/${P.activo}/presupuesto`, esperar: 'Lista de compras',
        pasos: (p) => p.getByRole('button', { name: 'Jornales y márgenes' }).click() },
      { id: 'presupuesto-precio-venta', rol: ADMIN, url: `/projects/${P.activo}/presupuesto`, esperar: 'Lista de compras',
        pasos: irA('Precio de venta') },
      { id: 'presupuesto-pdf-menu', rol: ADMIN, url: `/projects/${P.activo}/presupuesto`, esperar: 'Lista de compras',
        pasos: (p) => p.getByRole('button', { name: 'Descargar PDF' }).click() },
      { id: 'presupuesto-pdf-comitente', rol: null, url: '/login',
        pasos: verPdf(ids.adminId, `/projects/${P.activo}/price-list/export.pdf?audience=comitente`, 'comitente') },
      { id: 'presupuesto-pdf-interno', rol: null, url: '/login',
        pasos: verPdf(ids.adminId, `/projects/${P.activo}/price-list/export.pdf?audience=interno`, 'interno') },

      // Reglas de cómputo
      { id: 'reglas-lista', rol: ADMIN, url: '/reglas', esperar: 'Obra económica' },
      { id: 'reglas-nuevo', rol: ADMIN, url: '/reglas', esperar: 'Obra económica',
        pasos: (p) => p.getByRole('button', { name: /Nuevo juego/ }).click() },
      { id: 'reglas-editor', rol: ADMIN, url: `/reglas/${ids.juegoOrg}`, esperar: 'Muros' },
      { id: 'reglas-editor-armadura', rol: ADMIN, url: `/reglas/${ids.juegoOrg}`, esperar: 'Muros',
        pasos: (p) => p.getByRole('button', { name: /^Armadura/ }).first().click() },
      { id: 'reglas-editor-mano-de-obra', rol: ADMIN, url: `/reglas/${ids.juegoOrg}`, esperar: 'Muros',
        // En "Todas": debajo de Muros sigue Columnas, así el bloque no queda bajo la barra de guardar.
        pasos: (p) => p.getByText('Mano de obra', { exact: true }).first()
          .evaluate((el) => { el.scrollIntoView({ block: 'start' }); window.scrollBy(0, -260); }) },
      { id: 'reglas-estandar-lectura', rol: ADMIN, url: `/reglas/${ids.juegoEstandar}`, esperar: 'Muros' },

      // Equipo de la organización
      { id: 'equipo-lista', rol: ADMIN, url: '/team', esperar: 'Desde' },
      { id: 'equipo-nuevo-usuario', rol: ADMIN, url: '/team', esperar: 'Desde',
        pasos: (p) => p.getByText('Nuevo usuario').first().click() },
      { id: 'equipo-roles-obra', rol: ADMIN, url: '/team', esperar: 'Desde',
        pasos: (p) => p.getByRole('button', { name: 'Roles de obra' }).click() },

      // Perfil
      { id: 'perfil', rol: JEFE, url: '/profile', esperar: 'Seguridad' },

      // Administración de la plataforma
      { id: 'admin-organizaciones', rol: SUPER, url: '/admin/organizations', esperar: 'Constructora Del Valle' },
      { id: 'admin-nueva-organizacion', rol: SUPER, url: '/admin/organizations', esperar: 'Constructora Del Valle',
        pasos: (p) => p.getByText('Nueva organización').first().click() },
      { id: 'admin-organizacion-detalle', rol: SUPER, url: `/admin/organizations/${ids.orgId}`,
        esperar: 'Usuarios de la organización' },
    ];
  },
};

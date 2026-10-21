// Config común de los casos de QA de Scalist (skill global qa-local).
// Entorno aislado del manual: web :3100, API :8100. Ver .claude/qa.md.

import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const RAIZ = new URL('../../', import.meta.url);
const { firmarJwt } = await import(
  pathToFileURL(join(homedir(), '.claude', 'skills', 'qa-local', 'scripts', 'jwt.mjs')).href
);

// Solo existe en manual/tools/docker-compose.manual.yml (entorno local de prueba).
const SECRETO = 'manual-demo-jwt-secret-solo-local-0123456789abcdef';
export const API = 'http://localhost:8100/api/v1';

const sesion = (uid) => async (ctx) => {
  const t = firmarJwt({ secreto: SECRETO, payload: { sub: String(uid) } });
  await ctx.addInitScript((tok) => localStorage.setItem('scalistai_token', tok), t);
};

export const token = (uid) => firmarJwt({ secreto: SECRETO, payload: { sub: String(uid) } });

/** fetch a la API del entorno de QA con la sesión de un usuario. */
export async function api(uid, metodo, ruta, cuerpo) {
  const init = { method: metodo, headers: { Authorization: `Bearer ${token(uid)}` } };
  if (cuerpo instanceof FormData) init.body = cuerpo;
  else if (cuerpo !== undefined) {
    init.body = JSON.stringify(cuerpo);
    init.headers['Content-Type'] = 'application/json';
  }
  const r = await fetch(API + ruta, init);
  const txt = await r.text();
  if (!r.ok) throw new Error(`${metodo} ${ruta} → ${r.status}: ${txt.slice(0, 300)}`);
  return txt ? JSON.parse(txt) : undefined;
}

export const ARCHIVOS = {
  presupuesto: new URL('manual/tools/datos-demo/storage/demo/presupuesto-corralon-demo.pdf', RAIZ),
  ifc: new URL('manual/tools/datos-demo/ifc/casa-demo.ifc', RAIZ),
};

export default {
  baseUrl: 'http://localhost:3100',
  oscuro: true, // la app se usa en tema oscuro
  logs: 'docker compose -p scalist-manual logs backend --tail 60',

  // Borra lo que crean los casos (proyectos y juegos "QA ·"). runner --limpiar.
  async limpiar(d) {
    for (const p of (await api(d.adminId, 'GET', '/projects')).filter((x) => x.name.startsWith('QA ·'))) {
      await api(d.adminId, 'DELETE', `/projects/${p.id}`);
    }
    for (const r of (await api(d.adminId, 'GET', '/rule-sets')).filter((x) => x.name.startsWith('QA ·'))) {
      await api(d.adminId, 'DELETE', `/rule-sets/${r.id}`);
    }
  },

  async preparar() {
    const ids = JSON.parse(readFileSync(new URL('manual/tools/datos-demo/ids.json', RAIZ), 'utf8'));
    return ids;
  },

  roles: {
    super: (ctx, d) => sesion(d.superId)(ctx),
    admin: (ctx, d) => sesion(d.adminId)(ctx),
    jefe: (ctx, d) => sesion(d.usuarios.jefe)(ctx),
    capataz: (ctx, d) => sesion(d.usuarios.capataz)(ctx),
    comitente: (ctx, d) => sesion(d.usuarios.comitente)(ctx),
    computista: (ctx, d) => sesion(d.usuarios.computista)(ctx),
  },
};

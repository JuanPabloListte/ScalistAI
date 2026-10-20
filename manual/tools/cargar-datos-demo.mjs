// Carga los datos FICTICIOS del manual en el entorno demo (API en :8100), por la API de la app.
// Idempotente: busca por nombre/email antes de crear; se puede correr N veces.
//
// Uso (desde manual/tools, con el entorno arriba: .\entorno-demo.ps1 up):
//   node cargar-datos-demo.mjs
// Deja los ids que usan las capturas en datos-demo/ids.json.
//
// Sesiones sin contraseñas: el superadmin se crea con bootstrap-superadmin.py (contraseña
// aleatoria que nadie conoce) y todo lo demás se hace con tokens firmados con el JWT_SECRET
// del entorno demo. Las contraseñas de los usuarios demo también son aleatorias.

import { execSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { firmarJwt } from './token-jwt.mjs';

const AQUI = dirname(fileURLToPath(import.meta.url));
const RAIZ = join(AQUI, '..', '..');
const API = 'http://localhost:8100/api/v1';
const SECRETO = 'manual-demo-jwt-secret-solo-local-0123456789abcdef'; // = docker-compose.manual.yml
const datos = JSON.parse(readFileSync(join(AQUI, 'datos-demo', 'datos.json'), 'utf8'));

const token = (id) => firmarJwt({ secreto: SECRETO, payload: { sub: String(id) }, ttl: 8 * 3600 });
const clave = () => randomBytes(18).toString('base64url');

async function api(tok, metodo, ruta, cuerpo) {
  const init = { method: metodo, headers: { Authorization: `Bearer ${tok}` } };
  if (cuerpo instanceof FormData) init.body = cuerpo;
  else if (cuerpo !== undefined) {
    init.body = JSON.stringify(cuerpo);
    init.headers['Content-Type'] = 'application/json';
  }
  const r = await fetch(API + ruta, init);
  const txt = await r.text();
  if (!r.ok) throw new Error(`${metodo} ${ruta} → ${r.status}: ${txt.slice(0, 400)}`);
  return txt ? JSON.parse(txt) : undefined;
}

function archivo(ruta, nombre, tipo) {
  const fd = new FormData();
  fd.append('file', new Blob([readFileSync(ruta)], { type: tipo }), nombre);
  return fd;
}

const espera = (ms) => new Promise((r) => setTimeout(r, ms));

async function esperarModelo(tok, projectId) {
  for (let i = 0; i < 120; i++) {
    const planes = await api(tok, 'GET', `/projects/${projectId}/plans`);
    const ifc = planes.find((p) => p.original_filename?.toLowerCase().endsWith('.ifc'));
    if (ifc?.status === 'ready') return ifc;
    if (ifc?.status === 'error' || ifc?.status === 'failed') throw new Error(`IFC con error: ${ifc.error_message}`);
    await espera(2500);
  }
  throw new Error('El IFC no terminó de procesarse');
}

// ---------------------------------------------------------------- 1. superadmin
const salida = execSync(
  `docker compose -p scalist-manual exec -T backend python -`,
  { input: readFileSync(join(AQUI, 'datos-demo', 'bootstrap-superadmin.py')), cwd: RAIZ },
).toString().trim().split(/\s+/).pop();
const superId = Number(salida);
const tSuper = token(superId);
console.log(`superadmin #${superId}`);

// ---------------------------------------------------------------- 2. organizaciones
const orgs = await api(tSuper, 'GET', '/admin/organizations');
let orgPrincipal;
for (const o of datos.organizaciones) {
  let org = orgs.find((x) => x.name === o.nombre);
  if (!org) {
    org = await api(tSuper, 'POST', '/admin/organizations', {
      name: o.nombre, subscription_status: o.estado,
      ...(o.admin ? { admin_email: o.admin, admin_password: clave() } : {}),
    });
    console.log(`+ organización ${o.nombre}`);
  }
  if (o.principal) orgPrincipal = org;
}
const detalle = await api(tSuper, 'GET', `/admin/organizations/${orgPrincipal.id}`);
const admin = detalle.users.find((u) => u.email === datos.organizaciones.find((o) => o.principal).admin);
const tAdmin = token(admin.id);

// ---------------------------------------------------------------- 3. usuarios y oficios
const oficios = await api(tAdmin, 'GET', '/team/job-roles');
const idsOficio = (nombres) => nombres.map((n) => {
  const j = oficios.find((x) => x.name.toLowerCase() === n.toLowerCase());
  if (!j) throw new Error(`No existe el oficio "${n}". Hay: ${oficios.map((x) => x.name).join(', ')}`);
  return j.id;
});
let usuarios = await api(tAdmin, 'GET', '/team/users');
for (const u of datos.usuarios) {
  if (!usuarios.some((x) => x.email === u.email)) {
    await api(tAdmin, 'POST', '/team/users', {
      email: u.email, password: clave(), role: u.permiso, job_role_ids: idsOficio(u.oficios),
    });
    console.log(`+ usuario ${u.email}`);
  }
}
usuarios = await api(tAdmin, 'GET', '/team/users');
const idUsuario = (email) => usuarios.find((x) => x.email === email).id;

// ---------------------------------------------------------------- 3b. membrete, jornales y márgenes
const membrete = await api(tAdmin, 'GET', '/organization/letterhead');
if (membrete.contact_info !== datos.membrete.contacto) {
  await api(tAdmin, 'PUT', '/organization/letterhead', { contact_info: datos.membrete.contacto });
  console.log('  membrete: datos de contacto');
}
const logo = readFileSync(join(AQUI, 'datos-demo', datos.membrete.logo));
const logoActual = membrete.has_logo
  ? Buffer.from(await (await fetch(`${API}/organization/letterhead/logo`, { headers: { Authorization: `Bearer ${tAdmin}` } })).arrayBuffer())
  : null;
if (!logoActual?.equals(logo)) {
  await api(tAdmin, 'PUT', '/organization/letterhead/logo', archivo(join(AQUI, 'datos-demo', datos.membrete.logo), datos.membrete.logo, 'image/png'));
  console.log('  membrete: logo');
}

const jornales = await api(tAdmin, 'GET', '/labor-rates');
const jornalesDemo = datos.jornales.map((j) => ({ trade: j.oficio, daily_cost: j.costo }));
if (JSON.stringify(jornales.map((j) => ({ trade: j.trade, daily_cost: j.daily_cost }))) !== JSON.stringify(jornalesDemo)) {
  await api(tAdmin, 'PUT', '/labor-rates', jornalesDemo);
  console.log('  jornales de la empresa');
}
const margenes = await api(tAdmin, 'GET', '/cost-settings');
if (margenes.overhead_pct !== datos.margenes.gastosGenerales || margenes.profit_pct !== datos.margenes.beneficio) {
  await api(tAdmin, 'PUT', '/cost-settings', { overhead_pct: datos.margenes.gastosGenerales, profit_pct: datos.margenes.beneficio });
  console.log('  márgenes de la empresa');
}

// ---------------------------------------------------------------- 4. juegos de reglas
let juegos = await api(tAdmin, 'GET', '/rule-sets');
const estandar = juegos.find((j) => j.is_system || j.organization_id == null);
for (const j of datos.juegosDeReglas) {
  if (!juegos.some((x) => x.name === j.nombre)) {
    await api(tAdmin, 'POST', '/rule-sets', { name: j.nombre, description: j.descripcion, copy_from_id: estandar.id });
    console.log(`+ juego de reglas ${j.nombre}`);
  }
}
juegos = await api(tAdmin, 'GET', '/rule-sets');
// Mano de obra en los juegos propios: las copias hechas antes de que existiera no la traen.
const sinId = ({ id, position, ...r }) => r;
for (const j of datos.juegosDeReglas) {
  const juego = juegos.find((x) => x.name === j.nombre);
  let reglas = juego.rules.map(sinId);
  if (!reglas.some((r) => r.kind === 'labor')) {
    reglas = [...reglas, ...estandar.rules.filter((r) => r.kind === 'labor').map(sinId)];
  }
  reglas = reglas.map((r) => (r.kind === 'labor' && j.cuadrillaPropia?.includes(r.label) ? { ...r, labor_mode: 'daily' } : r));
  if (JSON.stringify(reglas) !== JSON.stringify(juego.rules.map(sinId))) {
    await api(tAdmin, 'PUT', `/rule-sets/${juego.id}`, { name: juego.name, description: juego.description, rules: reglas });
    console.log(`  mano de obra en ${j.nombre}`);
  }
}
juegos = await api(tAdmin, 'GET', '/rule-sets');

// ---------------------------------------------------------------- 5. proyectos
const ids = { superId, adminId: admin.id, orgId: orgPrincipal.id, ruleSetEstandar: estandar.id, proyectos: {}, usuarios: {} };
for (const u of datos.usuarios) ids.usuarios[u.clave] = idUsuario(u.email);

let proyectos = await api(tAdmin, 'GET', '/projects');
for (const p of datos.proyectos) {
  let proj = proyectos.find((x) => x.name === p.nombre);
  if (!proj) {
    proj = await api(tAdmin, 'POST', '/projects', { name: p.nombre, description: p.descripcion });
    console.log(`+ proyecto ${p.nombre}`);
  }
  ids.proyectos[p.clave] = proj.id;
  const hasta = p.hasta; // datos | modelo | precios | ubicacion | activo

  if (['modelo', 'precios', 'ubicacion', 'activo'].includes(hasta)) {
    const planes = await api(tAdmin, 'GET', `/projects/${proj.id}/plans`);
    if (!planes.length) {
      await api(tAdmin, 'POST', `/projects/${proj.id}/plans`,
        archivo(join(AQUI, 'datos-demo', 'ifc', 'casa-demo.ifc'), p.ifc, 'application/octet-stream'));
      console.log(`  subido ${p.ifc}`);
    }
    await esperarModelo(tAdmin, proj.id);
  }
  if (['precios', 'ubicacion', 'activo'].includes(hasta)) {
    const pl = await api(tAdmin, 'GET', `/projects/${proj.id}/price-list`).catch(() => null);
    if (!pl?.price_list) {
      const fd = archivo(join(AQUI, 'datos-demo', 'storage', 'demo', 'presupuesto-corralon-demo.pdf'),
        'presupuesto-corralon-demo.pdf', 'application/pdf');
      const juego = juegos.find((j) => j.name === p.juegoDeReglas) ?? estandar;
      fd.append('rule_set_id', String(juego.id));
      await api(tAdmin, 'POST', `/projects/${proj.id}/price-list`, fd);
      console.log('  subido presupuesto del proveedor');
    }
  }
  if (['ubicacion', 'activo'].includes(hasta) && !proj.address) {
    await api(tAdmin, 'PATCH', `/projects/${proj.id}/location`, p.ubicacion);
  }
  if (p.manoDeObra) {
    // Modo y precio de cada tarea en esta obra; los márgenes, los de la empresa.
    const vista = await api(tAdmin, 'GET', `/projects/${proj.id}/price-list`);
    const cambios = {};
    for (const m of p.manoDeObra) {
      const item = vista.labor.items.find((i) => i.label === m.tarea);
      if (!item) throw new Error(`El presupuesto no tiene la tarea "${m.tarea}"`);
      const quiero = m.modo === 'unit' ? { mode: 'unit', unit_price: m.precio } : { mode: m.modo };
      if (JSON.stringify(vista.settings.labor[item.key] ?? null) !== JSON.stringify(quiero)) cambios[item.key] = quiero;
    }
    if (Object.keys(cambios).length || vista.settings.margins_custom) {
      await api(tAdmin, 'PATCH', `/projects/${proj.id}/budget-settings`,
        { labor: cambios, reset_margins: vista.settings.margins_custom });
      console.log(`  mano de obra de ${p.nombre}`);
    }
  }
  if (hasta === 'activo') {
    const actual = await api(tAdmin, 'GET', `/projects/${proj.id}`);
    if (actual.status !== 'active') await api(tAdmin, 'POST', `/projects/${proj.id}/activate`);
    const miembros = await api(tAdmin, 'GET', `/projects/${proj.id}/members`);
    for (const m of p.equipo ?? []) {
      const uid = idUsuario(m.email);
      if (!miembros.members?.some((x) => x.user_id === uid)) {
        await api(tAdmin, 'POST', `/projects/${proj.id}/members`, { user_id: uid, role: m.rol });
      }
    }
  }
}

writeFileSync(join(AQUI, 'datos-demo', 'ids.json'), JSON.stringify(ids, null, 2));
console.log('OK', JSON.stringify(ids));

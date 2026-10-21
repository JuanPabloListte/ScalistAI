// Borra los proyectos y juegos de reglas "QA ·" que crean los casos. Uso: node qa/casos/_limpiar.mjs
import { api } from './_config.mjs';
const ps = (await api(2,'GET','/projects')).filter(p => p.name.startsWith('QA ·'));
for (const p of ps) { await api(2,'DELETE',`/projects/${p.id}`); console.log('proyecto borrado', p.id, p.name); }
const rs = (await api(2,'GET','/rule-sets')).filter(r => r.name.startsWith('QA ·'));
for (const r of rs) { await api(2,'DELETE',`/rule-sets/${r.id}`); console.log('juego borrado', r.id, r.name); }
console.log('quedan', (await api(2,'GET','/projects')).map(p=>p.name), (await api(2,'GET','/rule-sets')).map(r=>r.name));

# Manual de usuario — Scalist

Manual funcional de la plataforma, con capturas de pantalla.

| Archivo | Qué es |
|---|---|
| `index.html` | El manual navegable: índice lateral, buscador, capturas ampliables, tema claro/oscuro. Se abre directo en el navegador. |
| `manual-usuario-scalist.pdf` | La misma guía para imprimir o compartir, generada desde el HTML. |
| `img/` | Capturas (1440×900) tomadas automáticamente sobre un entorno demo. |
| `tools/` | Scripts para regenerar entorno, datos demo, capturas y PDF. |

Todas las capturas usan la organización ficticia **"Constructora Del Valle Demo S.R.L."**, un
modelo IFC público de ejemplo (la casa AC20-FZK-Haus del KIT, renombrada como "Casa Los Aromos")
un presupuesto de proveedor inventado ("Corralón Demo S.A.", marcado como documento ficticio) y un
logo ficticio ("Del Valle constructora · demo", `tools/datos-demo/logo-demo.svg` → `.png`).

**Alcance de la v1.1:** acceso, navegación, proyectos, asistente de proyecto nuevo, preparación y
exportación del IFC, presupuesto (materiales, mano de obra por rubro, jornales y márgenes, precio de
venta y PDF por rubros para el comitente e interno), reglas de cómputo (con la mano de obra), equipo
(con el membrete del PDF), perfil y administración de la plataforma. **Cronograma, Obra, Costos y Cambios** quedan para la próxima versión (se estaban
rehaciendo para usar el presupuesto nuevo).

## Regenerar el manual

Requisitos: Docker, Node 22+, Google Chrome instalado (Playwright lo usa en lugar de descargar
navegadores; para otro, `PW_CHANNEL=msedge`) y la imagen del backend construida
(`docker compose build backend` en la raíz).

Todo corre en un entorno **aislado** (`tools/docker-compose.manual.yml`, proyecto
`scalist-manual`): base propia (puerto 5450), redis (6390), API (8100), worker y el frontend en
el 3100. Las bases, contenedores y `.env` de desarrollo no se tocan; del `.env` solo se lee
`NEXT_PUBLIC_MAPBOX_TOKEN` para el mapa del paso Ubicación.

```powershell
# 1. Base, redis, API y worker (migran solos)
.\manual\tools\entorno-demo.ps1 up

# 2. Frontend del manual en http://localhost:3100 (dejarlo corriendo en otra terminal)
.\manual\tools\entorno-demo.ps1 web
```

```bash
cd manual/tools
npm install

# 3. Archivos y datos demo
curl -L -o datos-demo/ifc/casa-demo.ifc https://www.ifcwiki.org/images/e/e3/AC20-FZK-Haus.ifc
docker compose -p scalist-manual exec -T backend python - < datos-demo/generar-presupuesto-demo.py
node cargar-datos-demo.mjs          # idempotente; deja datos-demo/ids.json

# 4. Capturas, verificación y PDF
node capturar.mjs --workers 3       # o: node capturar.mjs presupuesto  (solo las que coinciden)
node verificar-manual.mjs ../index.html
node exportar-pdf.mjs ../index.html ../manual-usuario-scalist.pdf
```

Para bajar el entorno: `.\manual\tools\entorno-demo.ps1 down`. Para borrarlo con sus datos:
`.\manual\tools\entorno-demo.ps1 destroy`.

### Cómo se arma la sesión

Los scripts no escriben contraseñas en ningún formulario. Firman un token con el `JWT_SECRET` del
entorno demo (definido en `docker-compose.manual.yml`, solo existe ahí) y lo guardan en
`localStorage["scalistai_token"]`, que es donde lo guarda la app al iniciar sesión.

### Qué hace el script de datos y por qué

- **Superadmin por base de datos** (`datos-demo/bootstrap-superadmin.py`): no hay registro
  público ni forma de crear el primer usuario por la API. Se crea con contraseña aleatoria que nadie
  conoce.
- **Todo lo demás por la API**, como lo haría un administrador: tres organizaciones (una activa,
  una en prueba y una vencida, para la pantalla de administración), cuatro usuarios con sus roles
  de obra, un juego de reglas propio ("Obra económica", copia del estándar) y tres proyectos (uno
  activo con modelo, precios, ubicación y equipo; un borrador con el modelo subido; un borrador
  recién creado).
- El IFC se procesa de verdad en el worker del entorno demo y el presupuesto del proveedor lo lee
  el lector real.
- Membrete (logo y datos de contacto), jornales de los cuatro oficios, márgenes de la empresa (15% y
  10%) y la mano de obra de "Casa Los Aromos" (cuatro tareas tercerizadas con precios inventados y
  los revoques con cuadrilla propia). A "Obra económica" le copia la mano de obra del estándar si no
  la tiene. Todo sale de `datos-demo/datos.json`.
- Las dos hojas del PDF del presupuesto se capturan abriendo el PDF de la API en el visor de Chrome.

## Versión 2: videos

Pendiente. Los recorridos se definen en `tools/manual.config.mjs` (sección `videos`) y se graban
con `node grabar-videos.mjs` (requiere ffmpeg).

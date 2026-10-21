# QA — Scalist

Config de la skill global `qa-local`. Producto: modelo IFC → presupuesto del proveedor (PDF/Excel)
× reglas de cómputo → presupuesto (materiales + mano de obra), lista de compras, Gantt, obra.

## Entorno (aislado, reutiliza el del manual)
- **Tipo**: aislado — proyecto docker `scalist-manual`, base 5450, redis 6390, API **8100**,
  web **3100**. No toca la base ni el `.env` de desarrollo.
- **Requisito**: imagen del backend construida (`docker compose build backend` en la raíz) y
  `npm install` hecho en `manual/tools`.
- **Levantar** (PowerShell, desde la raíz del repo):
  1. `.\manual\tools\entorno-demo.ps1 up` — base, cola, API y worker (migra solo).
  2. `.\manual\tools\entorno-demo.ps1 web` — **en segundo plano**; frontend en :3100.
- **Listo cuando**: `http://localhost:8100/docs` y `http://localhost:3100/login` → 200.
- **Bajar**: `.\manual\tools\entorno-demo.ps1 down`. **Borrar todo**: `... destroy`.
- **Trampas conocidas**:
  - Docker Desktop a veces queda colgado (error 500 de la API de Docker): `docker desktop restart`.
  - En Windows el backend no siempre recarga solo: tras cambiar código, `docker compose -p
    scalist-manual restart backend worker`.
  - El primer `next dev` compila cada ruta al visitarla: la primera captura de una pantalla puede
    tardar 20–40 s; el runner espera, no es una falla.
  - El IFC se procesa en el worker (≈ 30 s el demo); si queda en "procesando" mucho rato, el
    worker murió: reiniciarlo.

## Sesiones (sin contraseñas)
- Token HS256 firmado con el `JWT_SECRET` de `manual/tools/docker-compose.manual.yml` (solo
  existe en ese entorno local), `payload.sub = <id de usuario>`, guardado en
  `localStorage["scalistai_token"]`. Ya está armado en `qa/casos/_config.mjs` (roles).
- **Roles** (ids en `manual/tools/datos-demo/ids.json`): `super` (superadmin), `admin` (admin de
  la org demo), `jefe` / `capataz` / `comitente` (miembros con rol de proyecto en el proyecto
  activo), `computista` (miembro sin equipo asignado).

## Datos de prueba
- **Crear** (idempotente), con el entorno arriba, desde `manual/tools`:
  1. `docker compose -p scalist-manual exec -T backend python - < datos-demo/generar-presupuesto-demo.py`
  2. `node cargar-datos-demo.mjs` → deja `datos-demo/ids.json`.
  Si falta `datos-demo/ifc/casa-demo.ifc`: `curl -L -o datos-demo/ifc/casa-demo.ifc https://www.ifcwiki.org/images/e/e3/AC20-FZK-Haus.ifc`.
- **Qué queda**: org "Constructora Del Valle Demo S.R.L."; proyectos `activo` (Casa Los Aromos:
  modelo, precios, ubicación, equipo), `borradorPrecios` (borrador con modelo y precios),
  `borradorDatos` (recién creado); juego de reglas "Obra económica".
- **Archivos de prueba**: `manual/tools/datos-demo/storage/demo/presupuesto-corralon-demo.pdf`
  (ficticio, con IVA), `manual/tools/datos-demo/ifc/casa-demo.ifc`. Para errores, generar
  sintéticos con `h.archivo(...)`.
- **Limpiar**: no hace falta (entorno aislado); `destroy` borra todo.

## Flujos
### Acceso
- **Ruta**: /login, /. **Código**: frontend/app/login, frontend/app/page.tsx, backend/app/api/v1/auth.py
- **Verificar**: landing sin cotizador ni textos de IA; sin sesión, una ruta privada lleva a
  /login?next=…; token inválido → login, no pantalla rota.

### Proyectos
- **Ruta**: /projects. **Código**: frontend/app/projects/page.tsx, backend/app/api/v1/projects.py
- **Verificar**: lista según membresía (computista no ve proyectos con equipo ajeno); acciones.

### Asistente de proyecto nuevo
- **Ruta**: /projects/new (?id=<borrador>). **Código**: frontend/app/projects/new,
  frontend/components/wizard/*, backend price_lists.py, plans/_core.py
- **Pasos**: Datos → Modelo BIM (solo .ifc, máx 500 MB) → Precios (PDF/Excel/CSV máx 15 MB,
  reglas, IVA, revisión de ítems) → Ubicación (Mapbox) → Revisión (lista de compras + totales,
  "Crear proyecto").
- **Errores propios**: subir no-IFC en Modelo; PDF escaneado/sin tabla, .jpg, archivo vacío en
  Precios; forzar IVA; cambiar el renglón de un ítem a uno incompatible; Siguiente sin archivo.
- **Casos**: `qa/casos/precios.mjs` (26). `preparar()` crea un borrador "QA · Precios <hora> · principal"
  con el IFC demo + uno fresco por cada archivo inválido (si uno queda guardado por error no contamina
  al resto). Corren EN ORDEN, sin `--workers`.
- **Trampas para los casos**:
  - El borrador abre en `wizard_step + 1`: con lista ya subida abre en **Ubicación**, hay que volver
    a Precios por el stepper.
  - En el stepper el texto "Precios" está FUERA del botón (el botón es solo el círculo, sin nombre
    accesible): `page.locator('ol li:has(span:text-is("Precios")) button')`.
  - No hay endpoint para borrar el presupuesto del proveedor: para probar "sin archivo" hace falta
    un borrador nuevo. Subir el IFC (sin esperar que procese) ya deja wizard_step = 2.
  - Selectores de IVA / reglas: `div:has(> div:text-is("IVA de los precios")) select`.
  - Un 500 del backend llega al navegador SIN CORS → la UI muestra "Failed to fetch"; el detalle
    está en `docker logs scalist-manual-backend-1`.

### Reglas de cómputo
- **Ruta**: /reglas, /reglas/[id]. **Código**: frontend/app/reglas, backend rule_sets.py, budget_rules.py
- **Verificar**: "Estándar Argentina" global, Por defecto, solo lectura salvo superadmin;
  duplicar crea copia editable; pestañas por medida + "Filtrar..."; coma decimal; mano de obra.
- **Errores propios**: guardar regla sin palabras clave; factor con letras; borrar el estándar.
- **Casos**: `qa/casos/reglas.mjs` (28). `preparar()` crea "QA · Reglas <hora>" (copia del estándar)
  para no tocar "Obra económica" del manual.
- **Trampas para los casos**: los mensajes de validación salen en la barra fija de abajo
  (`div.fixed.bottom-0`), no junto al campo; primera fila de material =
  `div.grid:has(> div input[placeholder="Ej. Cemento"])`, factor = 1.er `input[inputmode=decimal]`,
  desperdicio = 2.º. Los placeholders con punto ("Ej. Obra económica", "Filtrar...") hay que pasarlos
  como selector CSS a `h.llenar` (la heurística de `h.campo` los toma por selector). La barra lateral
  queda por encima del fondo de los modales: un clic en x < 64 no es "clic afuera".
- **Dato demo**: "Obra económica" tiene las MISMAS 30 reglas que el estándar (pese a su descripción):
  cambiar de juego no mueve los totales. Para probar el recálculo, cambiar una regla antes.

### Presupuesto
- **Ruta**: /projects/[id]/presupuesto. **Código**: frontend/app/projects/[id]/presupuesto,
  components/price-review.tsx, backend project_budget.py
- **Verificar**: totales coherentes; Excel/PDF solo con proyecto activo; comitente no ve plata.

### Gantt, Obra, Costos, Cambios
- **Ruta**: /projects/[id]/gantt, /obra, /costos, /changes. **Código**: frontend/app/projects/[id]/…,
  backend work_plans.py, work_plan.py
- **Verificar**: mismos números que Presupuesto (motor nuevo desde 97c13d4); roles capataz/comitente.

### Equipo y administración
- **Ruta**: /team, /admin/organizations. **Código**: frontend/app/team, frontend/app/admin, backend team.py, admin.py
- **Verificar**: solo admin / superadmin; roles de obra; membrete.

## Limpieza tras un QA
Borrar por API (admin, id 2) los proyectos y juegos cuyo nombre empieza con "QA ·" (los casos los
crean en cada corrida). Script: `node qa/casos/_limpiar.mjs` (el runner ignora los archivos que empiezan con `_`).

## Pendientes conocidos (QA 2026-10-20, reporte qa/reportes/2026-10-20_2300)
No re-reportar como nuevos si siguen; verificar si se arreglaron:
- Precios: archivos sin renglones (jpg renombrado, PDF sin tabla, CSV basura) se guardan con 0
  renglones; "Reemplazar archivo" con uno así BORRA la lista buena; PDF vacío / xlsx corrupto → 500.
- Reglas: desperdicio con letras se guarda como 0; desperdicio fuera de 0–100 muestra el 422 crudo en
  inglés; precio "12.500" se guarda 12,5; el link "← Reglas de cómputo" descarta cambios sin preguntar;
  Escape no cierra el modal.

## Notas de revisión
- Diseño: tema oscuro (el runner captura en claro por defecto; el login sale oscuro), pestañas subrayadas, inputs como los de Insumos/Sistemas; nada de cajas
  negras ni bandas de otro color. Textos de ayuda cortos.
- Moneda `$ 1.234.567` (es-AR, sin decimales en totales). Coma decimal aceptada en inputs.
- Ocultos a propósito (no reportar como falla): /precios y /materials redirigen a /projects;
  paso Construcción; cotizador de la landing; PDF/DXF/DWG eliminados.

# Equipo — Scalist

Contexto que el jefe (skill global `jefe-de-equipo`) reparte en los briefs. El producto y el
flujo están en `README.md`; QA en `.claude/qa.md`.

## Producto en una línea
Presupuesto de obra desde el modelo BIM: IFC + presupuesto del proveedor (PDF/Excel/CSV) ×
reglas de cómputo → materiales + mano de obra, lista de compras, PDF por rubros, Gantt, obra.
Ocultos a propósito tras flags (`frontend/lib/features.ts`): Inteligencia de Precios, Cómputos
(catálogo viejo), paso Construcción, presupuesto viejo (`LEGACY_BUDGET`), cotizador de la
landing. PDF/DXF/DWG y el visor con IA fueron eliminados.

## Stack y mapa
| Área | Carpeta | Tecnología | Ejemplo a imitar |
|---|---|---|---|
| backend | `backend/app/api/v1/`, `backend/app/services/` | FastAPI, SQLAlchemy 2, Pydantic 2, RQ | router `api/v1/price_lists.py` + servicio `services/project_budget.py`; permisos con `services/project_access.py` (`require_project`) |
| frontend | `frontend/app/`, `frontend/components/`, `frontend/lib/` | Next.js (app router), React, Tailwind, TS | página `app/reglas/[id]/page.tsx`; modales `components/modal.tsx`; formatos `lib/format.ts`; API `lib/api.ts` (`request()`) |
| base de datos | `backend/app/models/`, `backend/alembic/versions/` | PostgreSQL 16, Alembic | `models/rule_set.py` + `alembic/versions/p5d6e7f8a9b0_rubros_y_membrete.py` (cadena lineal, una sola head) |
| infra | `docker-compose*.yml`, `backend/Dockerfile`, `frontend/Dockerfile*`, `nginx/`, `docs/despliegue.md` | Docker compose, gunicorn, nginx, certbot | — |
| tests | `backend/tests/` | scripts Python (`python tests/<x>.py`, sin pytest), `fastapi.testclient` | `tests/test_project_price_list.py` (API + DB con org de prueba que se borra) |
| docs | `README.md`, `docs/`, `manual/` | Markdown; manual HTML+PDF con Playwright | `docs/despliegue.md` |

## Cómo verificar (por área)
Todo corre en los contenedores de desarrollo (`docker compose up -d` en la raíz):
- backend: `docker compose exec -T backend python tests/<archivo>.py` (cada archivo imprime
  `N/N tests pasaron`); todos: `for t in backend/tests/test_*.py; do …; done`.
- frontend: `docker compose exec -T frontend npx tsc --noEmit -p .` (ESLint no está
  configurado: `next lint` no sirve todavía).
- base de datos: `docker compose exec -T backend alembic upgrade head`; probar `downgrade -1` y
  volver a `upgrade head`; `alembic heads` tiene que dar una sola.
- QA visual: skill `qa-local` (entorno aislado del manual, ver `.claude/qa.md`).

## Entorno
- Dev: web :3000, API :8000, Postgres :5432, Redis :6379, worker RQ. `.env` en la raíz.
- **Trampas**: en Windows el backend no siempre recarga solo → `docker compose restart backend
  worker` tras cambiar código Python. Docker Desktop a veces se cuelga → `docker desktop
  restart`. El worker no tiene reload.
- Los contenedores montan `./backend` y `./frontend` de la RAÍZ, no del worktree de un
  especialista. Para verificar el código de un worktree (`<WT>` = ruta Windows, `pwd -W`), con
  los contenedores de dev arriba — probado:
  - backend: `MSYS_NO_PATHCONV=1 docker run --rm --network scalistai_default -v "<WT>/backend:/app" -w /app --env-file <raíz>/.env -e POSTGRES_HOST=postgres -e REDIS_HOST=redis scalistai-backend python tests/<x>.py`
  - frontend: `MSYS_NO_PATHCONV=1 docker run --rm -v "<WT>/frontend:/app" -v scalistai_frontend_node_modules:/app/node_modules -w /app scalistai-frontend npx tsc --noEmit -p .`

## Convenciones
- Código y comentarios en castellano (rioplatense neutro); textos de la UI en castellano, cortos.
- Commits en castellano, `tipo(área): descripción` (`feat`, `fix`, `refactor`, `docs`, `chore`),
  cuerpo explicando el porqué, y al final `Co-Authored-By: Claude <modelo> <noreply@anthropic.com>`.
- Permisos de proyecto siempre por `project_access` (roles jefe_obra / capataz / comitente);
  catálogos de la org: solo admin; juego de reglas estándar: solo superadmin.
- Dinero: es-AR, `$ 1.234.567` (helpers en `lib/format.ts`); precios del proveedor se guardan
  netos de IVA.
- Diseño: tema oscuro, pestañas subrayadas, inputs como los de Reglas; nada de cajas negras ni
  bandas de otro color. Modales con `components/modal.tsx`.
- No se borra código oculto por flag sin OK del usuario.

## Reglas del repo
- Rama `main`; remoto `origin` (GitHub). **Nunca push sin OK del usuario.**
- No versionar: `.env`, `storage/`, `qa/reportes/`, `.claude/settings.local.json`, archivos de
  clientes (presupuestos reales, IFC de obras).
- Datos de prueba siempre ficticios.

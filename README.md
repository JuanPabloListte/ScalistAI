# Scalist

Presupuesto de obra a partir del modelo BIM. El usuario sube el **IFC** del
proyecto y el **presupuesto del proveedor** (PDF, Excel o CSV); las **reglas de
cómputo** convierten las medidas del modelo en productos de esa lista y sale
la lista de compras con su total.

## Flujo

1. **Datos** — nombre y datos básicos del proyecto.
2. **Modelo BIM** — se sube el `.ifc`. Un job (`services/ifc_import.py`, cola
   RQ `scalist-jobs`) lo procesa con `ifcopenshell` y guarda los elementos
   (muros, losas, columnas, vigas, armaduras…) con sus medidas. También se
   evalúa la calidad del modelo.
3. **Precios** — se sube el presupuesto del proveedor.
   `services/price_list_parse.py` lo lee sin LLM: arma filas y columnas por
   posición, detecta formato numérico e IVA, y deja precio neto y
   presentación de venta (bolsa 25 kg, camión 6 m³, barra 12 m…).
4. **Ubicación**.
5. **Revisión** — presupuesto y lista de compras; Excel una vez creado el
   proyecto.

Después, en el proyecto: **Presupuesto**, **Plan de obra (Gantt)**,
**Costos**, **Cambios** y **Obra** (avance, costos reales, reportes).

### Cómo se calcula el presupuesto

`services/budget_rules.py` + `services/project_budget.py`:

1. Los elementos del IFC se resumen en medidas (m² de muro, m³ de columnas,
   ml de vigas, kg de armadura por diámetro…).
2. Cada regla del juego activo convierte una medida en cantidad de producto
   (kg de cemento, m³ de arena, ladrillos, barras de hierro).
3. El producto se busca por palabras clave en la lista del proveedor y se
   pasa a su unidad de venta; entre varios candidatos gana el más barato.
4. La lista de compras agrupa por renglón y redondea hacia arriba.

Se recalcula en vivo: si cambian las reglas o se re-procesa el IFC, el
presupuesto se actualiza. Solo se guardan el archivo del proveedor, su
lectura y las decisiones del usuario en la revisión.

### Reglas de cómputo

Pantalla **Reglas** (`/reglas`, modelo `RuleSet`). El juego
**"Estándar Argentina"** es global y solo lo edita el superadmin; cada
organización puede crear los suyos.

## Roles

- **Superadmin** — todo, incluida la administración de organizaciones
  (`/admin`) y las reglas globales.
- **Admin de la organización** — todo sobre los proyectos de su org y el
  equipo (`/team`).
- **Miembro de la organización** — según su rol en cada proyecto:
  `jefe_obra`, `capataz` (registra avance, no ve márgenes) o `comitente` (ve
  avance, no ve números financieros). Un proyecto sin miembros asignados lo
  ve toda la org.

La fuente de verdad es `services/project_access.py`. Aparte están los
**roles de obra** (oficios) por organización, en `services/job_roles.py`.

## Cómo levantarlo

```bash
cp .env.example .env   # completar JWT_SECRET y contraseñas
docker compose up --build
```

- App: http://localhost:3000
- API: http://localhost:8000 (OpenAPI en `/docs`)

Servicios: `postgres`, `redis`, `backend` (FastAPI, corre `alembic upgrade
head` al arrancar), `worker` (RQ) y `frontend` (Next.js 14). Producción:
`docker-compose.prod.yml` + `nginx/`, con `deploy.sh` y
`init-letsencrypt.sh`.

Si cambian dependencias del frontend, recrear los volúmenes:
`docker compose down -v && docker compose up --build`.

### Verificación

```bash
docker compose exec -T backend python tests/test_budget_rules.py
cd frontend && npx tsc --noEmit
```

## Feature flags

Hay secciones apagadas para concentrarse en el presupuesto. El código sigue
en el repo: se reactivan con la variable en `"true"` en `.env` y reiniciando
el frontend (`frontend/lib/features.ts`).

| Variable | Qué prende |
|---|---|
| `NEXT_PUBLIC_FEATURE_PRICE_INTELLIGENCE` | `/precios` — Inteligencia de Precios |
| `NEXT_PUBLIC_FEATURE_COMPUTOS` | `/materials` — insumos y sistemas constructivos |
| `NEXT_PUBLIC_FEATURE_WIZARD_BUILDING` | Paso "Construcción" del wizard |
| `NEXT_PUBLIC_FEATURE_LEGACY_BUDGET` | Presupuesto viejo (insumos/sistemas + paramétricos) |
| `NEXT_PUBLIC_FEATURE_LANDING_PRICING` | Cotizador de planes en la landing |

Los planos PDF/DXF/DWG con visor 2D/3D, la detección automática y el modelo de reconocimiento
se retiraron del código; están en el tag `archivo/planos-pdf-ia` (ver
`docs/archivo/funciones-retiradas.md`).

## Documentación anterior

En `docs/archivo/`: el README original (planos PDF, calibración, dibujo
manual), la hoja de ruta de ML, el contexto del pipeline CAD y
`funciones-retiradas.md`, que dice qué se borró y cómo recuperarlo.

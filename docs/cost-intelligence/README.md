# Motor de Inteligencia de Costos — Plan Técnico

> Evolución de ScalistAI: de **calculadora estática** de materiales a **plataforma de simulación estratégica de construcción** (presupuesto base → comparación de materiales → simulación de escenarios → proyección de costos futuros).

**Estado:** ✅ **ROADMAP COMPLETO — los 5 módulos (M1-M5, Vía A) implementados, testeados y commiteados.** Único pendiente (a propósito): el predictivo ML (Vía B), cuando se acumule serie real de precios.
**45 tests verdes.** Flujo end-to-end: plano CAD → presupuesto → comparar sistemas → proyectar inflación (IPC real) → precio de venta → XLSX.

### Progreso
| Fase | Estado | Commit | Entregado |
|---|---|---|---|
| **0 — Cimientos** | ✅ | `3e5ddf8` | Bounded context, domain (`Money`/`Quantity`/`measure_for`), `ConstructionEntity` + alternativas |
| **1a — Histórico de precios** | ✅ | `34467e9` | Vertical slice domain→app→infra, `material_price_history` |
| **1b — Mano de obra first-class** | ✅ | `3d68efa` | `labor_rates` + histórico |
| **2a — Simulador (núcleo)** | ✅ | `890b346` | `ScenarioCalculator` + casos de uso, validado sobre plan real |
| **2b — Simulador (API)** | ✅ | `4cc12b2` | `simulations` + `POST /simulations`, `/scenarios/compare` |
| **4 — Predictivo (Vía A)** | ✅ | `78320f6` | `Forecaster` + `macro_series`, `POST /forecast`. **IPC real INDEC** (`e956c34`) |
| **5 — Export XLSX** | ✅ | `aa6a420` | 4 hojas (presupuesto/escenarios/proyección/detalle), `GET /export/{id}` |
| **3 — Costos indirectos** | ✅ | `c9ce215` | `cost_settings` + `build_price` (gastos+beneficio+IVA → precio de venta), `GET/PUT /cost-settings` |
| **D — Fuentes reales 2022-2026** | ✅ | `541b043`+`25dabb3`+`be16b14` | Scraper 2448 (JSON-LD), Cormac 2022, acopio Silicio 2023 (3 proveedores) → 268 precios reales |
| **E — Producto canónico** | ✅ | `63878dd`+`25cbe5e` | `MaterialGroup`, `match_materials.py` (sugiere/aprueba/aplica) → 15 series multi-año unidas |
| **F — Vista Inteligencia de Precios** | ✅ | `95bb97e`+`2dd2da1` | `GET /price-series`, página `/precios` (gráfico SVG), ítem en sidebar |
| **G — Forecaster por material (Vía B-lite)** | ✅ | — | `material_trend.py`: proyecta desde la serie PROPIA + fallback IPC + comparación |
| **Vía B — Predictivo ML** | futuro | — | Prophet/XGBoost/regresión cuando la serie tenga densidad (puerto `Forecaster` listo) |

> **Nota de datos (CRÍTICO):** los precios de materiales solo entran de fuentes **reales** o del flywheel de clientes — **NUNCA data sintética** al histórico (envenena presupuesto y forecasting). Ver §14 para las fuentes cargadas (Cormac 2022, Silicio 2023, Carignani 2025, scraper 2448 2026 = 268 puntos). Índices macro: **IPC real de INDEC** (`datos.gob.ar`, serie `195.1_NIVEL_GENERAL_0_0_13`) vía `scripts/fetch_indec_macro.py`; el **ICC está discontinuado** (termina 2015) → IPC como proxy. Scraping: **del propio proveedor del usuario** (2448, Tiendanube vía JSON-LD) es defendible y está hecho; scrapear retailers ajenos al por mayor no. El **histórico no se fetchea ni se reconstruye con fórmulas** (eso es fabricar el pasado): se observa hacia adelante o se transcribe de listas reales fechadas.

---

## Tabla de contenidos
1. [Principio rector](#1-principio-rector-evolucionar-no-greenfield)
2. [Estado actual del sistema](#2-estado-actual-del-sistema-lo-que-ya-existe)
3. [Mapeo: propuesta ↔ existente](#3-mapeo-propuesta--existente)
4. [Inconsistencias y decisiones de diseño](#4-inconsistencias-y-decisiones-de-diseño)
5. [Arquitectura objetivo](#5-arquitectura-objetivo)
6. [Modelo de datos](#6-modelo-de-datos-evolución)
7. [Módulos](#7-módulos)
8. [APIs](#8-apis)
9. [Plan por fases](#9-plan-por-fases)
10. [Riesgos técnicos](#10-riesgos-técnicos)
11. [Estrategia de escalabilidad](#11-estrategia-de-escalabilidad)
12. [Decisiones abiertas](#12-decisiones-abiertas)
13. [Glosario dominio ↔ código](#13-glosario-dominio--código)

---

## 1. Principio rector: evolucionar, no greenfield

La propuesta original arrancaría de cero. **~60% del Módulo 1 ya existe y funciona en producción.** Reconstruir implica tirar el motor de cómputo, el cronograma, el export XLSX y —crítico— el modelo **multi-tenant**.

**Decisión:** mapear la propuesta sobre lo existente, renombrar al lenguaje del dominio (DDD) en un **bounded context aislado**, y agregar solo lo que falta. Menos riesgo, valor incremental, sin romper lo que ya vende.

---

## 2. Estado actual del sistema (lo que ya existe)

**Stack:** FastAPI · SQLAlchemy 2.0 · PostgreSQL · Redis (cliente lazy con fallback en memoria) · Alembic (18 migraciones) · FastAPI `BackgroundTasks` (no hay Celery) · openpyxl + reportlab (export) · multi-tenant por `organization_id`.

**Modelos relevantes (ya existen):**
- `Material(id, organization_id, name, category, unit, unit_price)` — material en crudo.
- `Assembly(id, organization_id, name, applies_to, daily_yield, stage, stage_order)` — **receta / BOM** ("Muro Exterior 22cm" → consume X").
- `AssemblyMaterial(assembly_id, material_id, consumption, waste_factor)` — **componentes de receta**.
- `DetectedElement(plan_id, type, geometry, length_m, area_m2, height_m, source, ...)` — **mediciones del CAD** (el JSON de entrada).
- `element_assemblies` — M2M elemento ↔ receta asignada.
- `Plan`, `Project`, `Organization`, `User`.

**Motores de cómputo (ya existen):**
- `_get_materials_summary_data(plan_id, page, db)` en `app/api/v1/plans/_export.py` — multiplica geometría × receta → **lista de materiales + costo**. Cubre wall/room/opening/beam/column/roof/riostra/cloaca/electricidad/escalera/pozo.
- `compute_schedule()` y `compute_cashflow()` en `app/services/schedule.py` — **horas-hombre, duración (Gantt), cashflow/curva de inversión** desde `daily_yield`.
- Export XLSX (openpyxl) + PDF (reportlab) en `_export.py`.

> **Conclusión:** ya hay presupuesto base, materiales, mano de obra (como hs), cronograma y export. Falta: **histórico de precios, simulación de alternativas, predictivo y grafo formal**.

---

## 3. Mapeo: propuesta ↔ existente

| Propuesta | ¿Existe hoy? | Acción |
|---|---|---|
| `Materials` | ✅ `Material` | + campo `active`; precio se mueve a histórico |
| `MaterialPriceHistory` | ❌ | **Nuevo** — base del predictivo |
| `LaborRates` | ⚠️ hoy la mano de obra es un `Material` ("Mano de Obra Ayudante" hs) | **Promover a entidad propia** + histórico |
| `ConstructionEntities` | ⚠️ implícito en `applies_to` ("wall","roof"…) | **Formalizar catálogo** (habilita alternativas) |
| `Recipes (BOM)` | ✅ `Assembly` | + link a entidad + agrupación de **alternativas** |
| `RecipeComponents` | ✅ `AssemblyMaterial` (`consumption` = `quantity_per_unit`) | Sin cambios estructurales |
| **Mód. 2** Simulador | ⚠️ base: `_get_materials_summary_data` + `schedule.py` | **Envolver** en motor de escenarios |
| **Mód. 3** Predictivo | ❌ | **Nuevo** (ver cold-start) |
| **Mód. 4** Grafo dependencias | ⚠️ parcial: el compute ya recalcula al cambiar receta | **Formalizar** DAG + indirectos |
| **Mód. 5** XLSX multi-hoja | ✅ export openpyxl (1 hoja) | **Extender** a 4 hojas |

---

## 4. Inconsistencias y decisiones de diseño

1. **TimescaleDB → diferir a Fase 4.** Para la escala actual, Postgres + tabla `material_price_history` indexada alcanza. Timescale se justifica con ingesta de alta frecuencia. Adoptarlo ahora es *premature optimization*. La tabla se diseña **"hypertable-ready"** para migrar sin dolor.

2. **🔴 Cold-start del predictivo (riesgo #1).** Prophet/XGBoost necesitan series históricas que **no existen aún**. Estrategia de dos vías:
   - **Vía A — determinística (hoy):** proyección por índices (aplicar IPC/ICC/dólar al costo actual). Usable desde el día 1, sin datos ni ML.
   - **Vía B — ML (después):** ingestar precios desde ya; entrenar con ≥12-18 meses. Interfaz `Forecaster` intercambiable A→B.

3. **Mano de obra first-class.** Migrar de "material hs" a `LaborRate(trade, daily_cost, date)` + histórico → habilita `labor_cost_difference` correcto.

4. **DDD/Clean Architecture solo en el módulo nuevo.** Reescribir toda la app a hexagonal es riesgoso. Se aísla un **bounded context `cost_intelligence/`** con capas limpias; la app actual se integra vía **anti-corruption layer**. Lo que funciona no se toca.

5. **Contrato de medición.** Value object `Measurement` (entidad → medida + unidad) + corrección del quirk actual (columna computa por m² de sección sin altura). Es el límite anti-corrupción entre el JSON del CAD y el dominio.

6. **Multitenancy + procedencia de precio.** Todo precio lleva `organization_id + source + date` (auditable, lista de precios por org). **Innegociable en un SaaS.**

---

## 5. Arquitectura objetivo

### Bounded context aislado
```
backend/app/cost_intelligence/
├── domain/            # PURO (sin SQLAlchemy)
│   ├── entities/      # Recipe, ConstructionEntity, Scenario, Forecast
│   ├── value_objects/ # Measurement, Money, Quantity, DateRange
│   └── services/      # reglas de negocio puras (diff de escenarios, etc.)
├── application/       # casos de uso + PUERTOS (interfaces)
│   ├── use_cases/     # RunSimulation, CompareScenarios, ForecastCost, ExportSimulation
│   └── ports/         # RecipeRepo, PriceHistoryRepo, Forecaster, PriceFeed
├── infrastructure/    # ADAPTERS
│   ├── persistence/   # repos SQLAlchemy (implementan los puertos)
│   ├── forecasting/   # adapters Prophet / XGBoost / determinístico
│   ├── feeds/         # INDEC / BCRA / CAC / manual
│   └── acl/           # anti-corruption: Material/Assembly/DetectedElement → dominio
└── interface/         # routers FastAPI + DTOs Pydantic
```

### Flujo — Simulación de escenario
```
CAD JSON (DetectedElement)
        │
        ▼
[ACL] Measurement(entity, value, unit)
        │
        ▼
RunSimulation ── asocia Recipe(s) por ConstructionEntity
        │
        ├──► CostEngine (envuelve _get_materials_summary_data) ──► costo materiales
        ├──► LaborEngine (envuelve schedule.py)               ──► HH + duración + costo MO
        │
        ▼
Scenario(base) ──► materializado en `simulations`
        │
        ▼  CompareScenarios(alt_recipe)
Scenario(alt) ──► diff ──► { material_cost_difference, labor_cost_difference, time_saved_days }
```

### Flujo — Forecast
```
material_price_history + macro_series (IPC/ICC/dólar)
        │
        ▼
Forecaster (puerto)
   ├── Vía A: IndexProjection  (determinístico, hoy)
   └── Vía B: ProphetAdapter / XGBoostAdapter (cuando haya datos)
        │
        ▼
CostForecast { cost_today, projected_cost, variation, horizon }
```

- **Async pesado:** simulaciones/forecast → `BackgroundTasks` + cache Redis (ambos ya existen). Resultados **materializados** (no recomputar). Celery/RQ recién si crece la carga.
- **El motor viejo no se duplica:** `_get_materials_summary_data` y `schedule.py` se envuelven como servicios de dominio.

---

## 6. Modelo de datos (evolución)

### Conservar (sin cambios destructivos)
`materials` · `assemblies` · `assembly_materials` · `detected_elements` · `element_assemblies` · `organizations`

### Agregar
| Tabla | Campos clave | Notas |
|---|---|---|
| `construction_entities` | `id, organization_id, name, type, unit` | Catálogo (muro, losa, cubierta, contrapiso…). Mapea de `applies_to` |
| `recipe_alternatives` | `id, construction_entity_id, assembly_id, is_default` | Agrupa assemblies como alternativas de una entidad (Ladrillo vs Durlock vs Retak) |
| `material_price_history` | `id, material_id, price, date, source` | **Hypertable-ready**. Índice `(material_id, date)` |
| `labor_rates` | `id, organization_id, trade, daily_cost, active` | Mano de obra first-class |
| `labor_rate_history` | `id, labor_rate_id, daily_cost, date, source` | Histórico de salarios |
| `macro_series` | `id, indicator, value, date, source` | IPC, ICC, dólar oficial/paralelo |
| `simulations` | `id, organization_id, plan_id, name, status, created_at, totals(jsonb)` | Read-model materializado |
| `simulation_scenarios` | `id, simulation_id, label, recipe_set(jsonb), totals(jsonb)` | Base + alternativas |
| `cost_forecasts` | `id, simulation_id, horizon_months, method, result(jsonb)` | Resultado de forecast |

### Migrar
- "Mano de Obra Ayudante" (`materials`) → `labor_rates`. Las recetas que la referencian pasan a usar HH desde `daily_yield`.
- `unit_price` de `materials` → último registro de `material_price_history` (el campo queda como cache de "precio vigente").

### Migraciones Alembic (incremental, siguiendo las 18 existentes)
1. `add_construction_entities_and_recipe_alternatives`
2. `add_material_price_history`
3. `add_labor_rates_and_history` (+ data migration de mano de obra)
4. `add_macro_series`
5. `add_simulations_and_scenarios`
6. `add_cost_forecasts`
7. *(Fase 4)* `enable_timescaledb_on_price_history` (opcional)

---

## 7. Módulos

### Módulo 1 — Base de datos de costos
Responsabilidad: catálogo de materiales, mano de obra, entidades constructivas, recetas y **histórico de precios**. Es la fuente de verdad de costos por org.
Entradas: ingesta manual + feeds (INDEC/BCRA/CAC). Salidas: precio vigente + serie histórica por material/trade.

### Módulo 2 — Simulador de escenarios
Responsabilidad: recibe mediciones CAD, asocia recetas por entidad, calcula **costo materiales + HH + duración + costo MO**, genera escenarios alternativos y su **diff**.
Reusa: `_get_materials_summary_data` (materiales) + `schedule.py` (HH/duración/cashflow).
Salida (ejemplo):
```json
{ "original": "Ladrillo", "alternative": "Durlock",
  "material_cost_difference": -12.5, "labor_cost_difference": -35.8, "time_saved_days": 18 }
```

### Módulo 3 — Motor predictivo
Responsabilidad: proyectar costo futuro dado un horizonte.
Vía A (determinística): `projected = cost_today × Π(1 + índice_periodo)`.
Vía B (ML): Prophet / XGBoost / LightGBM → (futuro) TFT / DeepAR / N-BEATS.
Salida:
```json
{ "cost_today": 150000, "projected_cost": 221000, "variation": 47.3 }
```

### Módulo 4 — Grafo de dependencias constructivas
Responsabilidad: DAG `Entidad → {materiales, mortero, MO, revoque, indirectos}`. Al cambiar una receta (Ladrillo→Durlock) recalcula materiales, tiempos, MO y **costos indirectos configurables**.
Reusa: la lógica de recálculo del compute; formaliza el grafo + indirectos.

### Módulo 5 — Exportación
XLSX con 4 hojas: **(1)** presupuesto actual · **(2)** comparativa de escenarios · **(3)** proyección futura · **(4)** detalle de materiales. Extiende el export openpyxl existente.

---

## 8. APIs

| Método | Endpoint | Caso de uso |
|---|---|---|
| `POST` | `/api/v1/simulations` | `RunSimulation` — presupuesto base desde mediciones |
| `POST` | `/api/v1/scenarios/compare` | `CompareScenarios` — diff entre recetas alternativas |
| `POST` | `/api/v1/forecast` | `ForecastCost` — proyección a N meses |
| `GET` | `/api/v1/export/{simulationId}` | `ExportSimulation` — XLSX 4 hojas |

**Ejemplo `POST /api/v1/simulations`**
```json
// request
{ "plan_id": 92, "scenario_recipes": { "wall": "muro_durlock", "roof": "losa_vigueta" } }
// response
{ "simulation_id": 1, "status": "done",
  "totals": { "materials": 18250000, "labor_hours": 2193, "labor_cost": 12060000, "duration_days": 145 } }
```

Todos los endpoints scoped por `organization_id` (auth actual). Cómputo pesado → 202 + job async + polling/cache.

---

## 9. Plan por fases

Cada fase entrega: diseño · modelo de datos · migraciones · seeds · servicios · DTOs · casos de uso · tests · endpoints · diagrama de flujo · riesgos.

| Fase | Estado | Qué | Reusa | Net-new |
|---|---|---|---|---|
| **0 — Cimientos** | ✅ `3e5ddf8` | Bounded context + `ConstructionEntity` (mapeado de `applies_to`) + agrupación de alternativas + `Money`/`Quantity`/`measure_for` + tests | Assembly/Material | esqueleto + dominio |
| **1a — Histórico precios** | ✅ `34467e9` | `material_price_history` (slice domain→app→infra) + backfill + ingesta data real | unit_price | tabla + repo + casos de uso |
| **1b — Labor first-class** | ✅ `3d68efa` | `labor_rates`(+hist) + seed desde material "Mano de Obra" | schedule | tablas + slice |
| **2 — Simulador (Mód. 2)** | ⏳ siguiente | `POST /simulations`, `/scenarios/compare` | budget + schedule | motor escenarios |
| **3 — Grafo (Mód. 4)** | pendiente | DAG BOM formal + recalc + indirectos configurables | compute | grafo + indirectos |
| **4 — Predictivo (Mód. 3)** | pendiente | Vía A determinística → Vía B ML (con datos). Timescale si hace falta | histórico (F1) | forecaster |
| **5 — Export (Mód. 5)** | pendiente | XLSX 4 hojas | openpyxl | hojas nuevas |

**Ruta recomendada:** **0 + 1 primero** (cimientos + histórico) → desbloquea todo y da valor sin romper nada → luego **2** (el feature estrella: comparar escenarios).

---

## 10. Riesgos técnicos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Cold-start de datos** (sin histórico, el ML no sirve) | Alto | Vía A determinística + ingesta temprana desde Fase 1 |
| **Sourcing macro** (APIs INDEC/BCRA: disponibilidad/licencia) | Medio | Adapter `PriceFeed` con fallback manual |
| **Correctitud dimensional** (quirk columnas por m² sin altura) | Medio | Contrato `Measurement` + tests por tipo de entidad |
| **Fuga multi-tenant** | Alto | `organization_id` en toda query nueva + tests de aislamiento |
| **Romper la app estable durante el refactor** | Alto | Bounded context aislado; no se toca el flujo que vende |
| **Alcance (meses, no días)** | Medio | Faseo con valor incremental (F2 ya entrega escenarios usables) |
| **Mantenimiento del modelo ML** | Medio | Forecaster como adapter intercambiable; reentrenos versionados |

---

## 11. Estrategia de escalabilidad

- **Particionado por org** en todas las tablas nuevas.
- **Jobs async** (`BackgroundTasks` → Celery/RQ cuando crezca) + **cache Redis** (ya disponible).
- **Read-model materializado** para simulaciones (no recomputar en cada lectura).
- **Hypertable (TimescaleDB)** en `material_price_history` solo cuando la ingesta lo pida.
- **Servicios stateless**; forecaster como **adapter intercambiable**.
- **Compute envuelto, no duplicado** → una sola fuente de verdad de costos.

---

## 12. Decisiones abiertas

1. ✅ Enfoque "evolucionar lo existente" — **aprobado e implementado**.
2. ✅ Arrancar por **Fase 0 + 1** — **hecho** (Fase 0, 1a, 1b commiteadas).
3. ✅ Predictivo **Vía A determinística primero**, ML después — **definido**.
4. ✅ **TimescaleDB diferido a Fase 4** — **definido** (tablas hypertable-ready mientras tanto).
5. ⏳ Fuente de datos macro (ICC/IPC/dólar): API INDEC/BCRA en Fase 4. **Pendiente** elegir endpoint/feed.
6. ⏳ Precios de materiales reales: ingestar más cotizaciones de proveedor (Carignani et al.) para construir serie. **Pendiente** (depende de que el usuario sume PDFs).

---

## 13. Glosario dominio ↔ código

| Lenguaje de dominio (DDD) | Implementación actual |
|---|---|
| Recipe / BOM | `Assembly` |
| RecipeComponent | `AssemblyMaterial` |
| ConstructionEntity | `Assembly.applies_to` (string) → catálogo nuevo |
| Measurement | `DetectedElement.{length_m, area_m2, height_m}` |
| LaborRate | hoy `Material` "Mano de Obra" → tabla nueva |
| Money (precio) | `Material.unit_price` → `material_price_history` |

---

## 14. Inteligencia de Precios: fuentes reales, producto canónico y forecaster por material

Esta sección documenta cómo el motor pasa de "un precio suelto" a "una serie real
que predice", **sin fabricar nada**.

### 14.1 Fuentes reales cargadas (268 precios, 2022-2026)

Cada precio entra a `material_price_history` con **fecha + fuente**. No hay data sintética.

| Fuente | Script | Fecha | Qué es |
|---|---|---|---|
| **Cormac S.A** | `seed_cormac_2022.py` | ene-2022 | 86 ítems transcritos de un PDF real de lista (ancla histórica) |
| **Acopio Silicio** | `seed_acopio_2023.py` | sep-2023 | 32 materiales × 3 proveedores (Zárate/Ferrocons/Cormac) = 78 puntos; incluye outliers reales (no se corrigen) |
| **Carignani/2448** | seed manual de PDFs | mar-abr 2025 | cotizaciones del proveedor del usuario |
| **2448materiales.com.ar** | `scrape_2448_prices.py` | jun-2026 | scraper del **propio proveedor**: parsea el JSON-LD (schema.org `Product`/`Offer`) de la Tiendanube. Honesto: si falla, FALLA (sin fallbacks). Ojo idempotencia same-day |
| **IPC INDEC** (macro) | `fetch_indec_macro.py` | 2016-2026 | inflación oficial real, en `macro_series` |

**Principio:** el histórico **no se fetchea ni se reconstruye con fórmulas** (deflactar el
precio de hoy + ruido = fabricar el pasado). Se observa hacia adelante (flywheel) o se
transcribe de listas reales fechadas. Gemini reincide en generar scripts `fetch_*`/`scrape_*`
que en realidad devuelven hardcoded/ruido — **revisar y borrar siempre**.

### 14.2 Producto canónico (`MaterialGroup`)

Cada fuente nombra el mismo producto distinto ("Cemento Holcim 50kg" vs "CEMENTO BOLSA").
`MaterialGroup` + `materials.group_id` agrupan los equivalentes para unir sus precios en
**una sola serie**. El match **no es automático** (un match malo envenena la serie):
`scripts/match_materials.py` —

- `--suggest`: propone candidatos cross-fuente por similitud (fuzzy). **Read-only.**
- `--apply`: crea los grupos `CONFIRMED` (revisados a mano por id). El fuzzy **solo descubre**, el humano **aprueba** (misma filosofía que la detección CAD/IA).
- `--series`: imprime la serie consolidada.

Trampas reales a NO unir: distinta **marca** (revoque fino Weber ≠ Tector), **color**
(pastina Plata ≠ Plomo) o **medida**. Commodities (cemento, cal) sí se agrupan entre marcas.

### 14.3 Forecaster por material (Vía B-lite) — `domain/material_trend.py`

La idea del usuario: *"si tengo que el hormigón valía X hace 3 meses y hoy Y, proyecto a
qué ritmo viene subiendo"*. Implementado como función pura:

```
tasa_mensual = (precio_último / precio_primero) ^ (1 / meses) − 1
proyectado   = precio_último × (1 + tasa_mensual) ^ horizonte
```

Reglas de **honestidad/confianza**:
- **≥2 puntos** en fechas distintas → tasa **observada** del material (`method="serie_propia"`).
- **<2 puntos** → fallback a **IPC** (`method="ipc"`); si tampoco hay IPC, no proyecta (`sin_dato`).
- Varias cotizaciones del **mismo día** (varios proveedores) cuentan como **1 punto** de tendencia (se promedian).
- Siempre se informa **nº de puntos** (confianza) y se compara contra el **IPC** (`beats_inflation`): "tu material sube más/menos que la inflación".

Es determinístico y explicable. Cuando la serie tenga densidad, una **regresión/ML** (Vía B)
reemplaza el cálculo de la tasa **sin cambiar el contrato** (`TrendForecast`). Trabaja en
`float`: es proyección analítica para mostrar, no aritmética de dinero autoritativa (esa es `Money`).

Tests: `tests/test_cost_intelligence_material_trend.py` (serie propia, fallback IPC, sin dato,
same-day = 1 punto, flag vs inflación).

### 14.4 Las 3 capas de valor (para un cliente que arranca de cero)

Un cliente nuevo carga precios de **hoy**, no historia de años. Por eso el valor se da en capas:

1. **Día 1, sin historia** — forecaster con **IPC**: con 1 solo precio ya proyecta "hoy → +IPC%". Universal.
2. **Con el tiempo — flywheel**: cada actualización suma un punto fechado → el cliente construye **su** serie real hacia adelante; ahí entra `serie_propia`.
3. **Opcional — índice de mercado compartido**: el scraper de precios públicos podría ser una referencia compartida entre orgs (separada de las cotizaciones privadas). **No implementado.**

La historia 2022-2023 cargada es **ventaja particular** de este usuario (tenía PDFs viejos),
no la norma. Que un cliente nuevo **no** tenga historia es coherente con no fabricar data.

### 14.5 Interfaz

- `GET /api/v1/price-series` → productos canónicos con serie + proyección (`PriceSeriesProduct`).
- Frontend `/precios` (ítem **Inteligencia de Precios** en el sidebar, org-level): gráfico SVG
  propio (sin libs), dots por proveedor, tramo de proyección punteado, badge "vs IPC".
| CostEngine | `_get_materials_summary_data()` |
| Labor/ScheduleEngine | `schedule.py: compute_schedule/compute_cashflow` |

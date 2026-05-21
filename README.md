# MuroAI

Aplicación web para automatizar el cómputo métrico y presupuesto de materiales en la fase de preconstrucción y preventa inmobiliaria. El usuario sube planos en PDF, la plataforma extrae dimensiones mediante visión por computadora e IA, y genera un presupuesto desglosado y editable contra un catálogo de materiales con fórmulas de rendimiento.

## Stack

- **Frontend**: Next.js 14 (App Router) + Tailwind CSS + React-Konva (visor interactivo sobre HTML5 Canvas).
- **Backend**: Python con FastAPI (asíncrono, compatible con el ecosistema de IA).
- **Base de datos**: PostgreSQL.
- **IA / Visión**: PyMuPDF, OpenCV, YOLOv8, PaddleOCR, SAM / U-Net.
- **Infra**: Docker Compose (postgres + redis + backend + frontend), RQ para tareas async.

## Resumen del proyecto

El objetivo es reducir el tiempo que los directores de obra e ingenieros dedican al cómputo métrico. El flujo es:

1. El usuario sube un plano en PDF desde el frontend.
2. El backend rasteriza el documento, calibra la escala geométrica, identifica muros, habitaciones, puertas y ventanas, y extrae dimensiones.
3. El usuario valida los datos detectados y asigna materiales.
4. El motor cruza las mediciones con la base de datos de rendimiento y genera un presupuesto exportable en Excel o PDF.

---

## 1. Estructura de carpetas (monorepo)

```
MuroAI/
├── frontend/                  Next.js 14 (App Router) + Tailwind + Konva
│   ├── app/                   rutas: /login, /projects, /projects/[id]
│   ├── components/
│   │   ├── viewer/            React-Konva: capas plano + overlays
│   │   └── ui/                botones, tablas, modales
│   ├── lib/api.ts             cliente HTTP tipado
│   └── package.json
├── backend/                   FastAPI
│   ├── app/
│   │   ├── api/v1/            routers: auth, projects, plans, materials, budgets
│   │   ├── core/              config, seguridad JWT, dependencias
│   │   ├── services/
│   │   │   ├── pdf.py         rasterización (PyMuPDF)
│   │   │   ├── preprocess.py  binarización (OpenCV)
│   │   │   ├── scale.py       calibración manual + OCR cotas
│   │   │   ├── detect.py      YOLOv8 (aberturas, escala)
│   │   │   ├── segment.py     SAM/U-Net (muros, recintos)
│   │   │   └── compute.py     fórmulas de cómputo métrico
│   │   ├── models/            SQLAlchemy
│   │   ├── schemas/           Pydantic
│   │   └── workers/           tareas async (RQ o Celery + Redis)
│   ├── ml/                    pesos entrenados (.pt), gitignored
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── db/
│   ├── migrations/            Alembic
│   └── seeds/                 catálogo base de materiales
├── storage/                   PDFs originales + rasters (montar volumen)
├── docker-compose.yml         postgres + redis + backend + frontend
├── .env.example
└── README.md
```

---

## 2. Modelo de datos PostgreSQL (tablas principales)

| Tabla | Campos clave | Notas |
|---|---|---|
| `users` | id, email, password_hash, role | role: admin / director_obra |
| `projects` | id, user_id, name, status | status: draft / processing / ready |
| `plans` | id, project_id, pdf_path, raster_path, dpi, page, scale_px_per_m, scale_source | scale_source: manual / ocr / yolo |
| `detected_elements` | id, plan_id, type, geometry (GeoJSON o PostGIS), area_m2, length_m, height_m, confidence, source | type: wall / room / door / window; source: ai / manual / edited |
| `materials` | id, name, category, unit | unit: m2, m3, ml, un, kg |
| `material_yields` | id, material_id, applies_to, consumption, waste_factor, unit_price, currency | fórmula = consumption × area × (1+waste) |
| `budget_items` | id, project_id, element_id, material_id, quantity, unit_price, subtotal | snapshot del precio al momento del cálculo |
| `processing_jobs` | id, plan_id, stage, status, started_at, error | tracking de pipeline async |

Decisión pendiente: **PostGIS sí o no**. Para polígonos del plano, GeoJSON en JSONB alcanza al principio; PostGIS solo se justifica si hacen falta queries espaciales (ej: "¿qué muros tocan esta habitación?").

---

## 3. Contratos de API (v1)

### Auth
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login` → JWT

### Proyectos
- `POST /api/v1/projects`
- `GET /api/v1/projects`
- `GET /api/v1/projects/{id}`

### Planos (procesamiento async)
- `POST /api/v1/projects/{id}/plans` (multipart PDF) → `{ plan_id, job_id }`
- `GET /api/v1/plans/{id}/status` → `{ stage: "raster|scale|detect|done", progress }`
- `GET /api/v1/plans/{id}` → raster URL + elementos detectados + escala
- `POST /api/v1/plans/{id}/scale` → `{ p1, p2, real_distance_m }` (calibración manual)
- `PATCH /api/v1/plans/{id}/elements/{eid}` → corregir geometría/tipo
- `POST /api/v1/plans/{id}/elements` → crear elemento dibujado a mano

### Materiales y presupuesto
- `GET /api/v1/materials` (catálogo)
- `POST /api/v1/projects/{id}/budget` con asignaciones material↔elemento
- `GET /api/v1/projects/{id}/budget`
- `GET /api/v1/projects/{id}/budget/export?format=xlsx|pdf`

---

## 4. Roadmap por sprints

El orden no sigue 1→2→3→4 puro. El objetivo es llegar a un MVP vendible **sin IA** y luego incorporar modelos como asistencia progresiva: cada modelo pre-rellena el dibujo que el usuario ya sabe hacer manualmente, nunca lo reemplaza.

| Sprint | Duración | Entrega | Por qué primero |
|---|---|---|---|
| **0** | 1 sem | Scaffolding, auth, CRUD proyectos, upload PDF crudo | Base sólida antes de tocar IA |
| **1** | 1-2 sem | **Fase 1**: rasterización + binarización + visor Konva mostrando el plano | El usuario ya ve su PDF en el navegador |
| **2** | 1 sem | **Calibración manual** (Paso 2.3 sin 2.1/2.2): el usuario marca 2 puntos y escribe "esto son 5 m" | Desbloquea todo el cómputo métrico sin entrenar modelos |
| **3** | 1-2 sem | **Dibujo manual** de muros, recintos y vanos + cálculo de áreas/longitudes/descuentos | MVP vendible: sustituye a AutoCAD para cómputo rápido |
| **4** | 1 sem | **Fase 4 completa**: catálogo de materiales, fórmulas, presupuesto, export xlsx/pdf | Cierra el ciclo de valor |
| **5** | — | **Fase 2 IA**: OCR de cotas con PaddleOCR + YOLOv8 para barra de escala | Calibración asistida, reduce trabajo manual |
| **6** | — | **Fase 3.3**: YOLOv8 para puertas/ventanas | El modelo más rentable: símbolos estándar, dataset chico |
| **7** | — | **Fase 3.1/3.2**: SAM o U-Net para muros + contornos para recintos | Lo más caro de afinar; al final del roadmap |

---

## 5. Fases originales del motor de IA (referencia técnica)

### Fase 1 — Ingesta y preprocesamiento
- **1.1 Rasterización adaptativa**: PyMuPDF / pdf2image convierten el PDF a PNG/TIFF a 300 DPI mínimo.
- **1.2 Binarización y limpieza**: OpenCV convierte a blanco y negro puro, elimina ruido, texturas y gradientes.

### Fase 2 — Sistema de referencia (escala)
- **2.1 Detección del bloque de escala**: YOLOv8 localiza la barra gráfica o el texto "1:100".
- **2.2 OCR de cotas**: PaddleOCR lee los números de las cotas en los ejes principales.
- **2.3 Calibración del píxel**: `relación = píxeles / metros reales`. Cualquier distancia en píxeles se traduce a metros.

### Fase 3 — Segmentación y extracción de geometrías
- **3.1 Muros**: SAM o U-Net aíslan paredes. Combinando largo × grosor × altura estándar se obtiene m³ de mampostería/hormigón.
- **3.2 Recintos**: detección de contornos cerrados con OpenCV. Cada polígono cerrado entrega m² para acabados (pisos, cielorrasos, pintura).
- **3.3 Aberturas**: YOLOv8 reconoce símbolos de puertas y ventanas; sus áreas se descuentan del total de muros.

### Fase 4 — Motor de cómputo y base de datos
- **4.1 Asignación guiada**: el frontend muestra mediciones detectadas y el usuario asigna tipos de material (global o por sector).
- **4.2 Fórmulas de rendimiento**: FastAPI consulta PostgreSQL.
  `Cantidad = Área × Consumo_por_m² × Factor_desperdicio`
- **4.3 Consolidación y exportación**: backend agrupa insumos en JSON; frontend genera tablas y exporta a xlsx o PDF.

---

## 6. Decisiones a cerrar antes de codear

1. **Cola de trabajo async**: RQ (Redis, simple) vs Celery (más potente, más config). Recomendado para arrancar: **RQ**.
2. **Storage de PDFs/rasters**: filesystem local con volumen Docker vs S3/MinIO desde el día uno. Recomendado: **local con interfaz abstraída**.
3. **Autenticación**: JWT propio vs Clerk/Auth.js. Recomendado: **JWT propio** (trivial en FastAPI, sin lock-in).
4. **PostGIS**: probablemente no al inicio. **GeoJSON en JSONB**.
5. **Deploy objetivo**: VPS propio (Hetzner) / Railway / Fly / cloud grande. Define `docker-compose` y CI.

---

## Estado actual

**Sprint 0 + Sprint 1 completados.**

### Sprint 0 (base)

- Monorepo con `frontend/` (Next.js 14 + Tailwind) y `backend/` (FastAPI).
- `docker-compose.yml` con postgres, redis, backend y frontend.
- Backend: auth JWT (`/auth/register`, `/auth/login`), CRUD de proyectos, upload de PDF.
- Modelos SQLAlchemy: `User`, `Project`, `Plan`. Alembic con migración inicial.
- Frontend: landing, `/login`, `/register`, `/projects`, `/projects/[id]` con uploader.
- Toggle light/dark con persistencia y sin flash.

### Sprint 1 (Fase 1 — ingesta y visor)

- **Rasterización** con PyMuPDF a 300 DPI: [backend/app/services/pdf.py](backend/app/services/pdf.py).
- **Binarización** Otsu con OpenCV (planos digitales y escaneados): [backend/app/services/preprocess.py](backend/app/services/preprocess.py).
- Procesamiento síncrono en el upload: el endpoint `POST /projects/{id}/plans` ahora deja el plan con `status="ready"` y `raster_path` apuntando al PNG binarizado.
- Nuevo endpoint `GET /api/v1/plans/{id}/raster` que sirve el PNG (autenticado por JWT, descargado como Blob desde el frontend).
- **Visor React-Konva** ([frontend/components/plan-viewer-inner.tsx](frontend/components/plan-viewer-inner.tsx)) con:
  - Zoom centrado en el cursor (rueda del mouse).
  - Pan arrastrando el lienzo.
  - Auto-fit al cargar y botón "Centrar".
- Integrado en `/projects/[id]`: al subir un PDF se muestra automáticamente, y los planos previos tienen botón "Ver".

## Arranque local

```bash
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8000 (docs en `/docs`)
- App: http://localhost:3000

Las migraciones corren automáticamente al iniciar el backend.

### Sprint 2 (calibración de escala — automática + manual)

- **Escala por página**: nuevo campo `page_scales: dict[str, float]` en `plans` (migración 0004). Cada página tiene su propio `px/m` porque planos reales mezclan 1:100 en plantas, 1:75 en cortes, 1:25 en detalles.
- **Auto-detección al subir**: [backend/app/services/auto_scale.py](backend/app/services/auto_scale.py) extrae el texto del PDF con PyMuPDF y matchea regex `esc(ala)?\s*1[:/]N`. Para cada match calcula `px_per_m = (DPI × 1000) / (25.4 × N)`. Se guarda automáticamente con `scale_source="auto_text"`. En el PDF de prueba del usuario (31 hojas), detecta correctamente 1:100, 1:75, 1:50, 1:25.
- Endpoint `POST /api/v1/plans/{id}/auto-detect-scale` para re-correrlo manualmente (preserva calibraciones manuales previas).
- **Calibración manual por página**: `POST /api/v1/plans/{id}/scale` con `{ p1, p2, real_distance_m, page }`. Sobreescribe `page_scales[page]`. Útil para páginas sin notación "Esc 1:N" en texto.
- Visor con dos botones: **"Auto-detectar escalas"** (corre todo el PDF) y **"Calibrar página"** (modo manual con clicks + overlay SVG). Footer muestra `Esc. pág. N: X px/m` y `N de M con escala`.

## Próximo paso — Sprint 3

Dibujo manual de muros, recintos y vanos sobre el plano con cálculo automático de longitudes/áreas usando la escala ya calibrada. Es el MVP vendible: cómputo métrico sin IA.

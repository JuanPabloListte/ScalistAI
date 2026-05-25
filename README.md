# MuroAI

Aplicación web para automatizar el cómputo métrico y presupuesto de materiales en la fase de preconstrucción y preventa inmobiliaria. El usuario sube planos en PDF, calibra la escala (auto o manual), dibuja muros, recintos y aberturas sobre el plano, asigna materiales con sus fórmulas de rendimiento, y obtiene un presupuesto exportable a Excel y PDF.

## Stack

- **Frontend**: Next.js 14 (App Router) + Tailwind CSS. Visor de planos con `<img>` + CSS transform (pan/zoom) y overlay SVG para muros/recintos/aberturas/calibración. Visor 3D con Three.js / React Three Fiber v8.
- **Backend**: Python con FastAPI (asíncrono, BackgroundTasks para pre-render).
- **Base de datos**: PostgreSQL.
- **Procesamiento**: PyMuPDF (rasterización + extracción de texto), OpenCV (preprocesamiento), openpyxl (export XLSX), reportlab (export PDF).
- **3D**: Three.js + `@react-three/fiber` v8 + `@react-three/drei` v9 (compatible React 18). Renderiza muros, aberturas y recintos en tiempo real desde los elementos detectados.
- **IA futura**: PaddleOCR (cotas), YOLOv8 (aberturas, barra de escala), SAM / U-Net (muros). No implementado todavía — el MVP funciona sin IA.
- **Infra**: Docker Compose (postgres + redis + backend + frontend). Redis reservado para RQ en sprints futuros.

## Flujo end-to-end

1. **Crear proyecto** y subir un PDF (cualquier cantidad de páginas).
2. **Background processing**: el backend cuenta páginas, ejecuta auto-detección de escalas leyendo el texto, y dispara pre-render de todas las páginas en una BackgroundTask.
3. **Calibrar** (cuando el texto del PDF no alcanza): marcar dos puntos sobre una cota conocida, escribir los metros reales. Se pueden acumular varias referencias y la app aplica la **mediana** para robustez.
4. **Dibujar** muros (línea), recintos (polígono cerrado) y aberturas (línea, se restan del muro). Cada elemento tiene `length_m` / `area_m2` calculados con la escala de su página.
5. **Asignar materiales** a los elementos (single o bulk). Cada material tiene yields con `applies_to` + `consumption` + `waste_factor` + `unit_price`.
6. **Presupuesto** consolidado que cruza elementos con yields. Editable inline (precio unitario).
7. **Exportar** a XLSX estilado (openpyxl) o PDF estilado (reportlab).

---

## 1. Estructura de carpetas (monorepo)

```
MuroAI/
├── frontend/                  Next.js 14 (App Router) + Tailwind
│   ├── app/
│   │   ├── login/ register/ projects/ projects/[id]/ materials/
│   │   └── layout.tsx         + script de tema sin flash
│   ├── components/
│   │   ├── plan-viewer.tsx           wrapper dynamic ssr:false
│   │   ├── plan-viewer-inner.tsx     viewer, dibujo, presupuesto, selección múltiple, toggle 3D
│   │   ├── plan-3d-viewer.tsx        visor 3D interactivo (Three.js / R3F v8), estilos Blueprint/Render
│   │   ├── scales-modal.tsx          tabla editable de escalas por página
│   │   ├── confirm-modal.tsx         confirmación reutilizable
│   │   ├── sidebar.tsx               navegación + perfil + tema
│   │   └── theme-toggle.tsx          switch light/dark accesible
│   ├── lib/api.ts             cliente HTTP tipado (~40 endpoints)
│   └── package.json
├── backend/                   FastAPI
│   ├── app/
│   │   ├── api/v1/            routers: auth, projects, plans, materials
│   │   ├── core/              config, JWT, dependencias
│   │   ├── services/
│   │   │   ├── pdf.py         rasterización (PyMuPDF)
│   │   │   ├── preprocess.py  enhance_for_display (gamma + dilate líneas)
│   │   │   ├── auto_scale.py  regex "1:N" sobre texto del PDF
│   │   │   └── prewarm.py     BackgroundTask que pre-rendera todas las páginas
│   │   ├── models/            SQLAlchemy: User, Project, Plan, DetectedElement, Material, MaterialYield
│   │   ├── schemas/           Pydantic v2
│   │   └── alembic/           migraciones (0001 → 0007)
│   └── Dockerfile
├── storage/                   PDFs originales + rasters cacheados
├── docker-compose.yml         postgres + redis + backend + frontend
└── README.md
```

---

## 2. Modelo de datos PostgreSQL

| Tabla | Campos clave | Notas |
|---|---|---|
| `users` | id, email, password_hash, role | role: admin / director_obra |
| `projects` | id, user_id, name, description, status | status: draft / processing / ready |
| `plans` | id, project_id, pdf_path, dpi, page_count, `page_scales` (JSON), `deleted_pages` (JSON), scale_source | `page_scales` = `{ "1": 59.06, "2": 78.74, ... }` (px/m por página). `scale_source`: auto_text / manual / manual_multi / manual_ratio |
| `detected_elements` | id, plan_id, page, type, geometry (JSON), length_m, area_m2, height_m, source | type: wall / room / opening. geometry: `{ points: [...], label?: string }` |
| `materials` | id, name, category, unit | category libre. unit: un, m2, ml, kg, l, etc. |
| `material_yields` | id, material_id, applies_to, consumption, waste_factor, unit_price | applies_to: wall / room_floor / room_wall / room_perimeter / opening / opening_perimeter |
| `element_materials` | element_id, material_id | M2M, permite múltiples materiales por elemento |

Geometría: GeoJSON-like en JSONB. **PostGIS descartado** — no hace falta para nuestras queries (todo se filtra por `plan_id` o `page`).

---

## 3. API v1 (endpoints implementados)

### Auth
- `POST /api/v1/auth/register` · `POST /api/v1/auth/login` → JWT
- `GET /api/v1/auth/me` · `PATCH /api/v1/auth/update` (perfil)

### Proyectos
- `POST /api/v1/projects` · `GET /api/v1/projects` · `GET /api/v1/projects/{id}`
- `PATCH /api/v1/projects/{id}` · `DELETE /api/v1/projects/{id}` (cascade)

### Planos
- `POST /api/v1/projects/{id}/plans` (PDF upload) → dispara auto-detect + background prewarm
- `GET /api/v1/projects/{id}/plans` · `GET /api/v1/plans/{id}`
- `GET /api/v1/plans/{id}/raster?page=N` → PNG procesado de la página
- `GET /api/v1/plans/{id}/render-status` → `{rendered, total}` para barra de progreso
- `POST /api/v1/plans/{id}/prewarm` → dispara/re-dispara el background
- `POST /api/v1/plans/{id}/delete-page/{page}` · `POST /api/v1/plans/{id}/restore-page/{page}`

### Escalas
- `POST /api/v1/plans/{id}/scale` `{p1, p2, real_distance_m, page}` (manual)
- `POST /api/v1/plans/{id}/scale-direct` `{page, px_per_m, source}` (mediana multi-ref)
- `POST /api/v1/plans/{id}/scale-ratio` `{page, denominator}` (1:N directo)
- `POST /api/v1/plans/{id}/bulk-scale-ratio` `{ "1": 100, "2": 75, ... }`
- `POST /api/v1/plans/{id}/auto-detect-scale` · `GET /api/v1/plans/{id}/preview-auto-detect`
- `DELETE /api/v1/plans/{id}/scale/{page}` (limpia una página)

### Elementos detectados (muros, recintos, aberturas)
- `POST /api/v1/plans/{id}/elements` · `GET /api/v1/plans/{id}/elements?page=N`
- `PATCH /api/v1/plans/{id}/elements/{eid}` · `DELETE /api/v1/plans/{id}/elements/{eid}`

### Materiales
- `GET /api/v1/materials/` · `POST /api/v1/materials/` · `GET/PUT/DELETE /api/v1/materials/{id}`
- `PATCH /api/v1/materials/{id}/price` (edit inline)
- `GET /api/v1/materials/export/xlsx` · `POST /api/v1/materials/import/excel`

### Asignación material ↔ elemento
- `POST /api/v1/plans/{id}/elements/{eid}/materials` · `DELETE …/materials/{material_id}`
- `POST /api/v1/plans/{id}/elements/bulk/materials` (asigna a N elementos a la vez)
- `POST /api/v1/plans/{id}/elements/bulk/materials/remove`

### Presupuesto + Export
- `GET /api/v1/plans/{id}/materials-summary?page=N` → cantidades + subtotales
- `GET /api/v1/plans/{id}/export/xlsx` → planilla estilada
- `GET /api/v1/plans/{id}/export/pdf` → PDF estilado

---

## 4. Roadmap por sprints

| Sprint | Estado | Entrega |
|---|---|---|
| **0** | ✅ | Scaffolding, auth JWT, CRUD proyectos, docker-compose |
| **1** | ✅ | Rasterización PyMuPDF + preprocesamiento + visor con pan/zoom |
| **2** | ✅ | Calibración por página: auto (regex sobre texto), manual single, manual multi-ref con mediana, edición 1:N en tabla |
| **3** | ✅ | Dibujo manual de muros / recintos / aberturas con cálculo automático de longitudes y áreas. Edición interactiva de vértices (drag handles) y eliminación con doble clic |
| **4** | ✅ | Catálogo de materiales con yields, asignación, presupuesto, export XLSX + PDF |
| **5** | ✅ | **Asistencia a calibración**: extracción de cotas desde el texto vectorial del PDF, badges sobre el plano, pre-llenado automático del modal con la cota más cercana |
| **9** | ✅ | **Selección múltiple y eliminación en lote**: Shift+click, Ctrl+A, Delete/Backspace, cuadro de selección con drag, selección de tipo completo, confirmación de eliminación en lote |
| **10** | ✅ | **Visor 3D interactivo**: muros extruidos, puertas/ventanas, suelos de recintos, modos Blueprint/Render Blanco (R3F v8 + Three.js) |
| **6** | pendiente | **Fase 2.2 IA**: OCR (Tesseract/PaddleOCR) para PDFs escaneados sin capa de texto |
| **7** | ✅ | **Fase 3.3 IA (Aberturas)**: detección automática de aberturas (puertas/ventanas) en base a etiquetas vectoriales y anchos |
| **8** | ✅ | **Fase 3.1/3.2 IA (Muros y Recintos)**: detección automática de muros por líneas paralelas y recintos semánticos. Auto-ajuste de recintos a muros cercanos e indicador inteligente de páginas recomendadas (Costo $0) |

El MVP vendible (Sprints 0-5, 9, 10) **ya está terminado**. Los sprints 6-8 incorporan IA como **asistencia progresiva**: pre-rellenan lo que hoy hace el usuario a mano, pero nunca lo reemplazan totalmente.

---

## 5. Estado actual — detalle de lo entregado

### Sprint 0 (base)
- Monorepo Next.js + FastAPI, docker-compose con postgres/redis.
- Auth JWT, CRUD proyectos, edición/eliminación con confirmación.
- Sidebar persistente con navegación, perfil editable, theme switch.

### Sprint 1 (ingesta + visor)
- Upload de PDF instantáneo (solo guarda + cuenta páginas).
- **BackgroundTask** pre-renderiza todas las páginas a 150 DPI con gamma + dilatación morfológica (mantiene líneas finas visibles).
- Render-status endpoint + barra de progreso en el visor.
- Visor con `<img>` + CSS transform: pan, zoom (rueda + botones), reset.

### Sprint 2 (escala por página)
- Campo `page_scales` JSONB (px/m por página).
- **Auto-detección** al subir: regex sobre el texto del PDF (`Esc 1:100`, `Escala: 1:75`, etc.) + fallback por keywords.
- **Calibración manual multi-referencia**: marcar N cotas conocidas, ver el `1:N` de cada una en el banner, aplicar la **mediana** (robusto contra una mala medición). Líneas mostaza para refs guardadas, roja para la en curso.
- **Tabla de escalas**: modal editable página por página, con input `1:N` + acción "Calibrar" que salta al visor en esa página y entra en modo manual.
- Páginas eliminables (`deleted_pages`): se ocultan del navegador, scales modal y export.

### Sprint 3 (dibujo + cómputo)
- Tres herramientas: **Muro** (L), **Recinto** (P), **Abertura** (O) + **Pan** (H).
- Atajos de teclado para cambiar tool, snapping al primer vértice para cerrar polígonos.
- Etiquetas editables sobre cada elemento (doble click).
- Panel lateral izquierdo: lista filtrable de muros/recintos/aberturas, hover destaca el elemento en el canvas.
- Cálculo automático de `length_m` (muros, aberturas, perímetros) y `area_m2` (recintos) usando `page_scales[page]`.
- **Barra de herramientas unificada** (bottom-right): tools + zoom in/out + centrar en una sola fila horizontal — no choca con el banner de calibración.

### Sprint 9 (selección múltiple y eliminación en lote)
- **Modo Selección** (`S`) nuevo en la barra de herramientas.
- **Shift + click** sobre cualquier elemento lo añade/quita de la selección.
- **Ctrl + A** selecciona todos los elementos de la página actual.
- **Clic en un tipo** ("Muros", "Recintos", "Aberturas") en el panel lateral selecciona todos los de ese tipo.
- **Cuadro de selección por drag** (rubber-band) cuando se arrastra sobre el canvas en modo Selección.
- Elementos seleccionados se resaltan con un halo cian animado.
- **Delete / Backspace** elimina todos los seleccionados con modal de confirmación (`Eliminar N elemento(s)`).
- Compatible con el panel de presupuesto: si se eliminan elementos asignados a materiales, los cálculos se recalculan automáticamente.

### Sprint 10 (visor 3D interactivo)
- Botón **"Vista 3D"** en la barra de herramientas (shortcut: `3`) alterna entre el visor 2D y el visor 3D.
- Visor 3D implementado en [`plan-3d-viewer.tsx`](frontend/components/plan-3d-viewer.tsx) con Three.js + React Three Fiber v8.
- **Muros extruidos** con altura real (`height_m`, default 2.8 m) y espesor estándar de 15 cm.
- **Aberturas** recortadas del muro: puertas (vacío hasta 2.1 m + dintel), ventanas (antepecho 0.9 m + vidrio translúcido + dintel).
- **Suelos de recintos** como extrusión 2D desde los polígonos detectados.
- **Modo Blueprint** (CAD oscuro con bordes cian brillantes) y **Modo Render Blanco** (materiales blancos con iluminación suave).
- **OrbitControls**: orbitar (click izq), mover cámara (click der / Shift+click), zoom (scroll).
- Carga dinámica con `next/dynamic` + `ssr: false` para evitar incompatibilidades SSR.
- Stack de dependencias: `three@^0.184`, `@react-three/fiber@^8.17` (React 18 compatible), `@react-three/drei@^9.122`.

### Sprint 5 (asistencia a calibración con texto vectorial)
- Backend: [backend/app/services/dimension_text.py](backend/app/services/dimension_text.py) usa PyMuPDF para extraer todos los spans de texto con sus bounding boxes. Filtra los que matchean patrón decimal (`X.XX` / `X,XX`) en rango plausible (5 cm – 500 m).
- Endpoint `GET /api/v1/plans/{id}/dimensions?page=N` devuelve `[{text, value, bbox, cx, cy}]` en píxeles del raster.
- Visor: al entrar en modo calibración, las cotas aparecen como **badges teal** sobre el plano (con el número resaltado).
- Cuando el usuario marca dos puntos, el modal se abre **pre-llenado** con la cota más cercana al midpoint (umbral: 200 px de papel, ~3.4 cm a 150 DPI). El input se resalta en teal y muestra "Sugerencia del PDF: cota X · editá si no es la correcta".
- No requiere instalar OCR ni nuevas dependencias. Cubre el 95% de los planos profesionales (CAD-exportados con capa de texto).

### Sprint 4 (materiales + presupuesto)
- Catálogo de materiales en `/materials`: CRUD completo, edición inline de precios, import/export Excel.
- Materiales con N yields (un material puede aplicarse a muros y a perímetros de recintos con consumos distintos).
- Asignación M2M material↔elemento, individual o bulk.
- **Panel de presupuesto** lateral derecho: agrupa materiales, calcula cantidades con `consumption × medida × (1 + waste_factor)`, precio editable inline.
- Export XLSX estilado (openpyxl: header navy, alineaciones, formato moneda, total destacado).
- Export PDF estilado (reportlab: paleta corporativa, tabla con grid, total con borde doble).

### UX / theming
- **Theme switch** light/dark accesible (`role="switch"` + `aria-checked`), persistente sin flash.
- Colores diferenciados por tipo de elemento en light **y dark**: recinto=verde, muro=azul, abertura=naranja/ámbar.
- Audit dark/light global: todas las páginas con pares `bg-X dark:bg-Y` consistentes.

### Sprint 7 (Deteccion de Aberturas por IA)
- Boton **"Detectar Aberturas"** en la barra superior.
- Escaneo de etiquetas vectoriales (puertas y ventanas como *P1*, *V2*) en el PDF nativo y su ancho asociado.
- Banner de resultados flotante para aceptar o descartar candidatos en lote (bulk) o de manera individual.

### Sprint 8 (Deteccion de Muros y Recintos por IA)
- Boton **"Detectar Muros/Recintos"** en la barra superior.
- **Muros**: Extraccion morfologica y geometrica de parejas de lineas paralelas con espesores de muros standard (8cm - 35cm) y fusion colineal.
- **Recintos**: Localizacion de etiquetas semanticas de recintos (*Cocina*, *Estar*, *Dormitorio*, *Baño*) y dibujo automatico de rectangulos con areas sugeridas.
- Banners de resultados flotantes apilables de forma dinamica segun su activacion.

### Edicion Interactiva de Geometrias (Drag Handles)
- Visualizacion de **handles circulares** en cada vertice del elemento seleccionado sobre el lienzo SVG 2D.
- Insercion de nuevos vertices al arrastrar handles secundarios (midpoints) situados en la mitad de cada segmento.
- Eliminacion interactiva de vertices haciendo **doble clic** sobre cualquier handle.
- Debounce de red y recargas optimistas del presupuesto (recalculo dinamico durante el arrastre, persistencia PATCH unica al soltar).

### Auto-ajuste de Recintos y Recomendacion de Paginas (Costo $0)
- **Ajustar a muros**: Boton en el panel lateral de recintos para proyectar lineas ortogonales desde el centro geometrico del recinto y encajarlo de forma automatica a los muros circundantes de la pagina, cubriendo camas, mesas y sillones.
- **Recomendacion Inteligente de Paginas**: Escaneo en milisegundos con PyMuPDF que analiza localmente textos y geometrias para puntuar las paginas mas optimas para arquitectura en PDFs de muchas paginas, sin consumo de APIs de vision. Presenta botones de acceso rapido y motivos en la cabecera del visor.

---

## 6. Arranque local

```bash
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8000 (docs OpenAPI en `/docs`)
- App: http://localhost:3000

Las migraciones Alembic corren automáticamente al iniciar el backend.

### Notas de dependencias frontend

| Paquete | Versión | Nota |
|---|---|---|
| `@react-three/fiber` | `^8.17.10` | v8 = compatible React 16-18; v9+ requiere React 19 |
| `@react-three/drei` | `^9.122.0` | Par de fiber v8 |
| `three` | `^0.184.0` | Motor 3D base |
| `react` / `react-dom` | `18.3.1` | Fijado — no actualizar a 19 sin revisar todo el stack |

> [!IMPORTANT]
> El `docker-compose.yml` usa **named volumes** (`frontend_node_modules`, `frontend_next`) en lugar de volúmenes anónimos para evitar que el bind mount de `./frontend:/app` pise el `node_modules` instalado en la imagen. Si se cambian dependencias en `package.json`, ejecutar `docker compose down -v && docker compose up --build` para recrear los volúmenes desde cero.

---

## 7. Próximo paso — Sprint 6 (OCR para PDFs escaneados)

El Sprint 5 resolvió la asistencia de cotas leyendo el texto vectorial del PDF (PyMuPDF). Funciona perfecto en CAD-exportados pero **no** en PDFs escaneados (sin capa de texto). Ese caso es minoritario pero existe — planos viejos, fotos del plano subidas como PDF, etc.

**Alcance del Sprint 6:**
- Agregar Tesseract al `backend/Dockerfile` (apt install `tesseract-ocr` + `tesseract-ocr-spa`).
- `pytesseract` a `requirements.txt`.
- En `dimension_text.py`: si PyMuPDF no devuelve texto para la página, fallback a OCR sobre el raster cacheado.
- Cache JSON del resultado en `storage/plans/{id}/{file}_p{N}.dims.json` para no re-OCRizar.
- Si Tesseract es insuficiente para CAD (símbolos raros, texto rotado), considerar PaddleOCR como alternativa.

Sprints 7 y 8 (YOLO aberturas + SAM muros) vienen después y siguen el mismo patrón: la IA propone, el usuario confirma o corrige.

# Contexto: Pipeline CAD/Vectorial → Ground Truth → Entrenamiento

> Documento de contexto para retomar el trabajo si se corta la sesión.
> Última actualización: 2026-06-11.

## Qué se construyó (sesión 2026-06-10/11)

### 1. Soporte DWG/DXF completo
- **Conversión DWG→DXF**: ODA File Converter instalado en el Docker del backend
  (`backend/Dockerfile`). El `.deb` NO está en git (54 MB, está en `.gitignore`);
  descargar de opendesign.com y poner en `backend/` antes del build.
- **Headless**: ODA es app Qt; corre con `xvfb-run -a` por invocación
  (`dxf_import.py:_read_dwg`). Dependencias xcb completas + xauth en Dockerfile.
- **Import**: `build_dxf_plan` renderiza overview; el wizard (paso 3) pide unidad
  (m/cm/mm) y recortes por planta. Cada recorte = página SVG vectorial + PNG
  gemelo (`{id}_p{n}.png`) que consume la IA.

### 2. Import automático de PDFs vectoriales (`pdf_vector_import.py`)
- Al subir un PDF, `try_vector_import` corre en background (hook en
  `_core.py:upload_plan`). Si el PDF tiene capas OCG reconocibles
  (MURO/WALL, ABERTURA/CARPINTERIA, CLOACAL/PLUVIAL, ELECTRIC/BOCAS/TOMAS),
  extrae geometría exacta con `source="dxf"`.
- **Escala desde cotas**: texto "3.50" + línea de cota adyacente → mediana
  validada por consistencia (`page_scale_pt_per_m`).
- **Rotación**: páginas con `/Rotate` (ej. 270°) → `page.rotation_matrix`
  porque `get_drawings()` devuelve coords sin rotar. (Bug real que pasó:
  ProyectoTest p6/p8.)
- El pipeline de IA se saltea si hay elementos vectoriales
  (`auto_detect_pipeline.run_initial_detection` — marca etapas `done` para
  que el banner del frontend no quede colgado).

### 3. Post-procesado de muros (`dxf_import.py`)
- `_merge_segments`: colapsa segmentos colineales (intervalos sobre el eje).
- `_fuse_parallel_faces`: fusiona las DOS CARAS de un muro (paralelas a
  0.04–0.55 m, solape ≥50%) en UNA línea sobre el eje. Un muro = una línea.
- `_bridge_walls_over_openings`: une muros colineales cortados por un vano si
  hay una abertura en el hueco (gap ≤3 m, abertura a ≤0.45 m del eje). El muro
  pasa continuo sobre la abertura y el cómputo le resta las medidas después
  (dintel/antepecho incluidos — más preciso).
- Orden: merge → fuse → bridge. Corre en ambos flujos (DXF apply y PDF vector).

### 4. Resolución anclada en píxeles
- `apply_layer_mapping` calcula `px_per_unit = TARGET_PX / span_unidades`:
  la página siempre sale ~3000 px de lado mayor, **independiente de la unidad
  elegida**. Una unidad mal elegida ya no degrada el render (solo las medidas,
  corregibles re-eligiendo unidad). Bug real: heurística eligió cm para un
  archivo en metros → páginas de 401×320 px ilegibles.
- Heurística de unidad: $INSUNITS si plausible; si no, probar m→cm→mm buscando
  lámina de 20–600 m.

## Proyectos creados (ground truth exacto, org 1 / juanpilistte@gmail.com)

| Proyecto | ID | Plan | Contenido |
|---|---|---|---|
| PipeTest (ProyectoTest.pdf) | 69 | 60 | 9 págs: ~550 muros, ~230 aberturas, ~450 cloacas, ~960 elec + curación manual (11 recintos, 4 techos, 3 columnas) |
| A02 - Modulo A | 70 | 61 | 2 plantas: 291 muros, 159 aberturas |
| NOBU Casa 4 | 71 | 62 | 2 plantas: 50 muros, 32 aberturas |
| Duplex Terrazas | 72 | 63 | 10 págs: SOLO instalaciones (267 cloacas + 662 elec en p1) — los muros están en capas eléctricas, irrecuperables |
| Casa de la Placita | 73 | 64 | planta: 35 muros, 11 aberturas, 94 cloacas, 95 elec (p2=techos sin elementos) |
| Casa Esquina | 74 | 65 | 1 pág (se eliminó la p1 mala): 50 muros, 37 aberturas, 117 cloacas, 171 elec |
| Angel Suarez 15-01 | 75 | 66 | 3 plantas (sin azotea): 98 muros, 40 aberturas |

**Convención de capas del estudio**: muros = `Arq. Corte` (lo que corta el
plano de sección), aberturas = `Arq. Aberturas` + `AR - Carpinteria`,
instalaciones = `Inst. Cloacales/Pluvial/Electricidad`. El Duplex usa capas
`MUROS`/`I-WALL` pero sus plantas tienen los muros dibujados en capas
eléctricas (archivo de trabajo sucio).

**Cómo re-aplicar un proyecto CAD** (regiones quedan en
`storage/plans/{proj}/{id}_regions.json`):
```python
from app.services.dxf_import import apply_layer_mapping
# mapping: dict capa→tipo ('wall'/'opening'/'cloaca'/'electricidad'/'context')
# regions=None usa las guardadas; pasar lista [[x1,y1,x2,y2],...] para cambiar
apply_layer_mapping(plan, mapping, db, regions=...)
```
El DXF convertido se regenera con:
`xvfb-run -a ODAFileConverter <in_dir> <out_dir> ACAD2010 DXF 0 1 '*.dwg'`
(/tmp del contenedor se borra al reiniciar).

## Tipo "escalera" (agregado 2026-06-11)

Nuevo ElementType `escalera` end-to-end: schemas (regex), PageRole
`escaleras`, máscara clase 12 (`MASK_ESCALERA`, CLASS_NAMES/WEIGHTS en
`scripts/_common.py` — el próximo entrenamiento usa 13 clases), handler ML
`_emit_escaleras` (polígono + área), keywords ESCALERA/STAIR en ambos imports,
clustering `_cluster_escaleras` (trazos → un polígono bbox por escalera,
1–25 m²), herramienta de dibujo polígono en el visor (violeta).
Re-aplicados los 13 proyectos: PipeTest +30 escaleras, Costera 1 +3 (los
demás CAD no tienen capa de escalera).

PENDIENTE MENOR: `derive_rooms_for_plan` devuelve 0 en los proyectos CAD
re-aplicados (en PipeTest funciona — 70 recintos). Investigar flood-fill con
páginas SVG/PNG de CAD.

## Estado del entrenamiento

- Modelo actual: `muroai_seg_v10.pt`, mIoU 0.40 — flojo, necesita diversidad.
- El generador sintético (`synthetic_generator.py`) toma TODOS los elementos
  sin filtrar por source → el ground truth `dxf` fluye ✓.
- Máscaras: clases 0-8 (fondo/muro/recinto/puerta/ventana/pta-ventana/viga/
  columna/losa). **Cloaca/electricidad NO están en el esquema de máscara** —
  extenderlo es tarea futura (tocar modelo + generador).

## Pendientes (en orden)

1. ~~Fix sintético para CAD~~ → HECHO (`synthetic_generator.py` usa el PNG
   gemelo `{id}_p{n}.png` cuando pdf_path es .svg).
2. ~~Recintos derivados~~ → HECHO (`room_derivation.py`: flood-fill entre
   muros. 115 recintos creados en los 7 planes; salta páginas que ya tienen).
3. ~~Correr sintético~~ → HECHO: 510 variaciones nuevas (30 por página × 17
   páginas de los planes 60/61/62/64/65/66; Duplex excluido — solo
   instalaciones, fuera del esquema de máscara). Dataset sintético total:
   **2.030 muestras** (incluye 1.400 de planes viejos 29/30/31).
4. **Reentrenar** como checkpoint — LISTO PARA DISPARAR (`/admin` → train-now,
   o `api.triggerTraining(epochs)`). Esperar mejora en muros/aberturas/
   recintos; vigas/columnas/techos no van a mejorar — casi no hay datos.
5. **Conseguir más archivos** (meta: 20-50 proyectos distintos). Cada PDF
   vectorial o DWG que se sube se etiqueta solo.
6. (Futuro) Extender clases de máscara a cloaca/electricidad (hoy 0-8:
   fondo/muro/recinto/puerta/ventana/pta-ventana/viga/columna/losa).
7. (Futuro) Híbrido para vectoriales sin capas útiles: la IA propone regiones,
   la geometría vectorial da coordenadas exactas.

## Estrategia producto (acordada con Juan Pablo)

| Archivo | Estrategia |
|---|---|
| Vectorial con capas | Extracción exacta (funciona hoy) |
| Vectorial sin capas | Híbrido IA-propone + vector-precisión (futuro) |
| Escaneado | IA pura, mejora sola con el flywheel |

El pitch: "de plano a presupuesto en 30 minutos" (como plan0.ai), con
diferencial LATAM (materiales, rendimientos, formato de presupuesto argentino).
La IA asiste, el flujo completo (cómputo→materiales→presupuesto→Gantt→Excel)
es lo vendible.

## Archivos descargados para entrenar (2026-06-11)

En `C:\Users\USUARIO\Downloads\training_planos\`: **12 DWG oficiales** de
prototipos de vivienda nacional (argentina.gob.ar/habitat, Casa Propia /
Procrear II — documentos públicos, legalmente limpios) + 4 PDF de IPV Mendoza
(vectoriales SIN capas — solo útiles para el futuro híbrido).

Patrones de URL: `sites/default/files/{modelo}_plano_municipal.zip` y
`sites/default/files/{modelo}-cad.zip` (costera1/2, metropolitana1-6).
Hay más modelos en argentina.gob.ar/habitat/modelos-de-vivienda (página JS;
buscar los links con curl + user-agent de browser en cada página de modelo).

Validados (muros/carpinterías/estructura por capas):
- EXCELENTES: costera1 (4282 muros, 308 estr), metro6 AToT (1775 muros, **5999
  estructura** — ¡vigas/columnas que faltan!), metro1 CPHCPPII (1341/842/198),
  metro5 (774 muros, 6044 carp), milagro (235 muros portantes + est_viga),
  casa1-lam2a4 (344 muros), costera2-LAMINA2 (241 muros), bicentenaria
  (capas `arq_muros _ ladrillo 08/12/18` + carpinterías — mapeo más fino).
- DÉBILES: metro3 TRABAJO0228 (0 muros por keyword — capas con otros nombres,
  inspeccionar), procrear0190 (25 muros), casa1-lam1 (carátula).

PROCESADOS (2026-06-11, proyectos "Gob - *", regiones por clustering de
densidad de muros — sin verificación visual por límite de imágenes):
- 76 Costera 1 (113 muros, 27 vigas, 9 col), 77 Metro 5 (150/95/32 elec),
  78 Metro 6 Estructura (**171 vigas, 115 columnas, 221 losas**, 319 muros),
  80 Costera 2 (102/11), 81 Metro 4 (56/93/78 cloacas),
  88 Metro 1 (183/225/16 vigas — unidad forzada a metros: una entidad basura
  lejana hacía detectar mm).
- PENDIENTES (caso borde): Milagro y Bicentenaria — los muros son bloques
  INSERT; el clustering los ve pero `apply_layer_mapping` genera 0 elementos
  (investigar el manejo de INSERT en `_entity_boxes`/`_insert_to_detected`).
  Metro 3 (capas sin nombres de muro) y Metro 2/casa1-lam1 (poco contenido)
  descartados.

DATASET TOTAL (13 proyectos): 1.994 muros, 952 aberturas, 1.896 elec,
923 cloacas, 225 losas, 214 vigas, 130 recintos, 127 columnas.

## Gotchas conocidos

- `/tmp` del contenedor se vacía al reiniciar (helpers y DXF convertidos hay
  que regenerarlos).
- `scale_source`: `"dxf"` activa el branch SVG del raster endpoint — NO usar
  para PDFs vectoriales (usan `"vector"`).
- ezdxf addon `odafc` NO se usa (frágil); se llama ODAFileConverter por
  subprocess con xvfb-run (`dxf_import.py:_read_dwg`).
- La sesión de Claude tiene límite de imágenes acumuladas: si los renders de
  verificación fallan con "media rejected", localizar plantas por densidad de
  entidades (`Arq. Corte` + `Arq. Aberturas` por celda de grilla).
- Páginas con la misma planta repetida (instalaciones): asignar materiales en
  UNA sola página por rubro para no duplicar el cómputo.

# Sprints — Integración ML (CubiCasa5K)

Roadmap de la integración de un modelo de segmentación visual entrenado sobre
**CubiCasa5K** al pipeline de detección de ScalistAI. Reemplaza/complementa la
detección clásica con OpenCV.

## Objetivo

- Subir la calidad de detección de muros / recintos / aberturas.
- Cero costo por inferencia (modelo local, no APIs pagas).
- Dejar lista la infraestructura de **feedback loop** para fine-tunear con
  los planos que suban los clientes.
- No romper nada: la detección clásica sigue funcionando como fallback si el
  modelo ML no está disponible.

## Decisiones de arquitectura

| Decisión | Valor | Por qué |
|---|---|---|
| Familia de modelos | Segmentación visual (U-Net / similar) | Lo correcto para detección espacial. VLMs/LLMs no dan coordenadas precisas. |
| Dataset | CubiCasa5K | 5000 planos anotados, licencia CC-BY 4.0 (uso comercial OK). |
| Framework | PyTorch + segmentation-models-pytorch | Estándar, soporta CPU y GPU, fine-tuning sencillo. |
| Despliegue inicial | CPU | Barato. ~2-5s por página. Migrar a GPU si volumen lo justifica. |
| Modo de operación | **Ensemble** ML + clásico | ML como detector primario, clásico valida / completa. |
| Trigger | Endpoint `/page-roles` (ya existe) | Reutilizamos el flujo del wizard, sin trigger paralelo. |
| Loop de feedback | Captura accept/reject del usuario | Cada corrección queda guardada para futuro fine-tune. |
| Storage modelo | `backend/models/cubicasa5k.pt` (gitignored) | Archivo bajado en setup, fuera del repo. |

## Sprints

### ✅ Sprint 0 — Decisión y plan

**Status**: completado.

- Confirmamos enfoque clásico CV no escala.
- Descartamos VLMs (Ollama, LLaVA) por ser familia equivocada.
- Elegimos pre-entrenado sobre CubiCasa5K.
- Definimos modo de operación (ensemble) y trigger (page-roles).

---

### ✅ Sprint 1 — Dependencias + esqueleto del servicio

**Status**: completado el 2026-05-27.

**Objetivo**: dejar el código del detector ML escrito, con dependencias instaladas, pero sin requerir todavía el archivo del modelo. Si el modelo no está presente, el sistema sigue funcionando con detección clásica.

**Tareas completadas**:
1. ✅ Agregadas a `backend/requirements.txt`: `torch>=2.4.0`, `torchvision>=0.19.0`, `segmentation-models-pytorch>=0.3.4`, `pillow>=10.4.0`.
2. ✅ Creado `backend/app/services/ml_detector.py`:
   - Clase `MLDetector` con carga lazy del modelo (no bloquea arranque).
   - Detección de device automática (cuda → cpu).
   - `MLDetectionResult` con walls/rooms/openings + metadata.
   - `is_available()`, `model_info()`, `detect()`.
   - Singleton `get_ml_detector()`.
   - Preprocess: resize a 512×512 con padding + normalización ImageNet.
   - Postprocess: máscaras → skeleton + HoughLinesP para muros / connected components para recintos / bbox para aberturas.
3. ✅ Settings en `app/core/config.py`: `ML_MODEL_PATH`, `ENABLE_ML_DETECTION`, `ML_DEVICE`.
4. ✅ Endpoint `GET /api/v1/plans/ml-status` que devuelve estado y metadata del modelo.

**Resultado**: el servicio importa sin error aún sin modelo descargado. `is_available()` devuelve `False` y el pipeline cae al detector clásico transparentemente.

---

### ✅ Sprint 2 — Integración al pipeline (ensemble básico)

**Status**: completado el 2026-05-27.

**Objetivo**: usar el detector ML como etapa adicional del pipeline. Co-existe con el detector clásico — los elementos ML quedan marcados con `source="ai_ml"`.

**Tareas completadas**:
1. ✅ `auto_detect_pipeline.py`:
   - Nueva etapa `"ml"` agregada a `Stage` y al tracking de progreso.
   - Función `_run_ml_stage()` que itera todas las páginas con algún rol, hace inferencia ML una sola vez por página (eficiente), y filtra resultados según el rol asignado a la página.
   - Se llama al final de `run_initial_detection`, después de las etapas clásicas.
   - Si el modelo no está disponible: stage marcado como "done" sin error.
2. ✅ Funciones `_create_*_elements` aceptan parámetro `source` (default `"ai"`, ML pasa `"ai_ml"`).
3. ✅ Tipo `AiStatus` en frontend extendido con `ml: AiStage`.
4. ✅ `STAGE_LABELS` del banner agrega "ML" como cuarto detector visible.
5. ✅ Type `MlModelStatus` + `api.getMlStatus()` en el cliente frontend.

**Resultado**:
- Pipeline corre con o sin modelo descargado (sin regresión).
- Banner de detección IA muestra el estado de las 5 etapas (Escalas / Muros / Recintos / Aberturas / ML).
- Elementos ML quedan diferenciados por `source` para análisis y eventual merge inteligente.

**Pendientes para futuras iteraciones**:
- Merge IoU entre candidatos ML y clásicos (Sprint 3 → será re-priorizado tras tener el modelo real).
- Distinguir puerta/ventana en aberturas ML (hoy todas se marcan como "door").

---

### ❌ Sprint 3 — Setup y descarga del modelo CubiCasa5K (DESCARTADO)

**Status**: cancelado el 2026-05-27.

**Motivo**: el LICENSE de CubiCasa5K es **CC-BY-NC 4.0** (NonCommercial). No podemos usarlo para un producto comercial. Pivotamos a Sprint 3' (generador sintético desde planos del usuario).

---

### ✅ Sprint 3' — Generador sintético desde planos reales

**Status**: completado el 2026-05-27.

**Objetivo**: generar dataset de training derivando variaciones de los planos que sube el usuario. Cada plano confirmado → 50-200 muestras de training con ground truth perfecto. Sin dependencias externas con licencias restrictivas.

**Tareas completadas**:
1. ✅ `backend/app/services/synthetic_generator.py`:
   - `generate_synthetic_variations(plan_id, page, num_variations)` función principal.
   - Renderiza la página a 512×512 manteniendo aspect ratio + padding centrado.
   - Construye la máscara `uint8` desde los `DetectedElement`:
     * Recintos primero (fill polygon) — clase 2.
     * Muros segundo (línea con espesor) — clase 1.
     * Aberturas al final (línea con espesor) — clase 3.
   - Por cada variación aplica:
     * **Geométricas** (12 combos): rotaciones 0/90/180/270° × flips none/H/V.
     * **Estilo** (random, probabilísticas): brillo ±30, contraste 0.85-1.15, ruido gaussiano σ=2-8, inversión, dilatación/erosión, blur leve.
   - Persiste a `storage/synthetic/plan_<id>/page_<N>/var_<NNN>/` con `image.png`, `mask.png`, `meta.json`.
   - Determinístico por seed (mismo plan_id + page → mismas variaciones).
2. ✅ Endpoint `POST /api/v1/plans/{id}/generate-synthetic` con body `{ "page": 1, "num_variations": 50 }`.
3. ✅ `api.generateSynthetic()` en el cliente frontend.

**Definition of Done cumplido**:
- ✓ Sintaxis Python OK.
- ✓ Frontend typecheck OK.
- ✓ Generación independiente de internet (no descarga nada).
- ✓ Salida lista para consumir por un script de training PyTorch.

**Limitaciones conocidas**:
- Solo transformaciones geométricas + estilo. No mueve muros ni inserta columnas (esas son **structural** — se evaluarán en Sprint 5' después de validar el bootstrap).
- Cada variación es independiente — no hace mixup / crop random.
- La calidad del ground truth depende de la calidad de los `DetectedElement` confirmados por el usuario. Si el usuario subió un plano y aceptó detecciones malas, el dataset hereda esos errores.

---

### ✅ Sprint 4 — Captura automática de feedback

**Status**: completado el 2026-05-27.

**Decisión**: en vez de una tabla nueva `ml_training_samples` con tracking granular (accept/reject/edit por elemento), aprovechamos que **el estado final de `DetectedElement` al activar el proyecto YA es el ground truth**. El `synthetic_generator` lo convierte directamente en muestras de training. Mucho más simple.

**Tareas completadas**:
1. ✅ Migration `0008_project_training_consent.py`: nueva columna `allow_training_data: bool` en `projects` (default True). Permite opt-out per-proyecto para clientes con NDA.
2. ✅ `Project` model + schema actualizados con la flag. Schema nuevo `TrainingConsentUpdate`.
3. ✅ Hook en `activate_project`: si `project.allow_training_data` + `settings.AUTO_GENERATE_TRAINING_DATA`, dispara `_snapshot_project_for_training` en background. Ese task itera todos los planes del proyecto, encuentra páginas con elementos confirmados y llama a `generate_synthetic_variations(num_variations=40)` por cada una.
4. ✅ Endpoint `PATCH /api/v1/projects/{id}/training-consent` para toggle del flag desde el frontend.
5. ✅ `synthetic_generator` extendido con metadata de lineage en cada `meta.json`:
   - `source_project_id`, `source_plan_id`, `source_page`
   - `snapshot_at` (ISO 8601 UTC)
   - `element_counts` por tipo (wall/room/opening)
   - Además genera un `_manifest.json` por batch (resumen del set entero).
6. ✅ Endpoint `GET /api/v1/plans/training-stats`: recorre `storage/synthetic/` y devuelve total de samples, batches, planes y proyectos contribuyendo, último snapshot, y flag `ready_to_train` (≥200 samples).
7. ✅ Settings: `AUTO_GENERATE_TRAINING_DATA: bool = True` (kill switch global).
8. ✅ Frontend: `Project` type con `allow_training_data`; `TrainingStats` type; `api.getTrainingStats()` y `api.setTrainingConsent()`.

**Flujo end-to-end ahora completo (Sprint 1 → 4)**:
```
[Usuario sube planos]
        ↓
[Wizard 3: asigna page roles]
        ↓
[Backend: IA clásica (+ ML si modelo) genera candidatos]
        ↓
[Usuario confirma/edita/dibuja en editor]
        ↓
[Wizard 6 → Activate]
        ↓
[Background: snapshot automático]   ← Sprint 4
  └─ Genera 40 variaciones × página × plan
  └─ Guarda en storage/synthetic/plan_X/page_Y/var_NNN/
  └─ Cada batch con _manifest.json + lineage
        ↓
[Operador / cron: training-stats indica ready_to_train=true]
        ↓
[python -m scripts.train_model] ← Sprint 4'
        ↓
[Próximo proyecto: ML detector usa el nuevo modelo]
```

**Definition of Done cumplido**:
- ✓ Activar un proyecto consentido → snapshot automático sin intervención.
- ✓ Cada variación trae trazabilidad completa al plan y proyecto origen.
- ✓ Endpoint para saber cuándo conviene entrenar.
- ✓ Flag de consent para compliance con clientes sensibles.

**Pendientes para iteración posterior**:
- Tracking explícito de rejected (hoy una detección rechazada simplemente se borra y no queda registro). Útil como hard negatives.
- UI en `/projects/{id}/settings` para que el usuario vea/cambie su consent post-activación.

---

### ✅ Sprint 4' — Pipeline de training inicial

**Status**: completado el 2026-05-27.

**Objetivo**: script que toma las variaciones sintéticas + cualquier corrección real, entrena un U-Net y guarda el checkpoint que el detector ML va a levantar automáticamente.

**Tareas completadas**:
1. ✅ `backend/scripts/train_model.py`:
   - `SyntheticDataset` PyTorch que recorre recursivamente `storage/synthetic/**/var_*/{image.png,mask.png}`.
   - Normalización ImageNet consistente con `ml_detector._preprocess`.
   - Model: `smp.Unet(encoder_name="resnet34", encoder_weights="imagenet", classes=4)` — misma arquitectura que `MLDetector`.
   - Loss: `CrossEntropyLoss` con pesos por clase para compensar desbalance de background.
   - Optimizer Adam + Cosine LR schedule.
   - Métrica de validación: mIoU (excluyendo background) + IoU por clase.
   - Guarda el mejor checkpoint a `backend/models/scalistai_seg_v1.pt`.
   - Persiste historial completo en `.history.json` para análisis posterior.
2. ✅ Default `settings.ML_MODEL_PATH` cambiado a `./backend/models/scalistai_seg_v1.pt`.
3. ✅ `.gitignore` actualizado para excluir `backend/models/*.pt`, `*.history.json` y `test_plans/`.

**Uso**:
```bash
cd backend
python -m scripts.train_model --epochs 30 --batch-size 8
# Para GPU: --device cuda
```

**Flujo completo end-to-end** (gracias a Sprint 1-4'):
1. Usuario sube planos → wizard asigna roles → IA clásica genera candidatos.
2. Usuario confirma/edita candidatos en el editor.
3. `POST /plans/<id>/generate-synthetic` → variaciones sintéticas en `storage/synthetic/`.
4. `python -m scripts.train_model` → modelo entrenado en `backend/models/scalistai_seg_v1.pt`.
5. Próximo upload + `/page-roles` → la etapa ML del pipeline ahora corre con el modelo entrenado, devolviendo elementos con `source="ai_ml"` además de los clásicos.

**Pendiente para siguiente sprint**:
- Sprint 4'-bis: endpoint admin para gatillar el training desde la UI (en lugar de CLI).
- Bootstrap inicial — si el usuario nunca tuvo modelo, opción de entrenar usando solo las variaciones de los primeros 2-3 planos.

---

### ✅ Sprint 5 — Pipeline de fine-tuning incremental

**Status**: completado el 2026-05-27.

**Objetivo**: script reproducible que toma el corpus actualizado (datos nuevos + viejos), re-entrena el modelo desde el checkpoint activo y solo lo promueve a producción si supera al actual.

**Decisiones de diseño**:
- **Holdout fijo**: 10% de los samples se reserva al primer training, congelado en `holdout.json`. Todas las versiones se comparan en ese mismo holdout — números comparables a lo largo del tiempo.
- **Replay anti-forgetting**: durante el fine-tune se mezcla un % de datos viejos con los nuevos (default 50/50). Evita que el modelo olvide patrones aprendidos.
- **Active pointer**: `backend/models/active.json` indica qué versión está en producción. `MLDetector` lo lee al arrancar.
- **Promoción condicional**: el nuevo modelo solo reemplaza al activo si su mIoU en el holdout supera al anterior por al menos `--promote-threshold` (default 0.005). Si no, queda guardado para diagnóstico pero no se activa.

**Tareas completadas**:
1. ✅ `backend/scripts/_common.py` — código compartido:
   - `SyntheticDataset`, `build_unet_model`, `compute_iou_per_class`, `evaluate_on_loader`.
   - `read_active_model`/`write_active_model` (pointer `active.json`).
   - `read_holdout`/`write_holdout` + `initialize_or_load_holdout`.
   - Constantes sincronizadas con `ml_detector.py` (INPUT_SIZE, CLASS_NAMES, normalización ImageNet).
2. ✅ `backend/scripts/train_model.py` refactorizado:
   - Usa helpers de `_common`.
   - Congela holdout al primer run.
   - Evalúa final en holdout (no solo val rotativo).
   - Escribe `active.json` apuntando a la versión recién entrenada.
3. ✅ `backend/scripts/finetune_model.py` nuevo:
   - Lee modelo activo de partida.
   - Filtra samples por `--since <iso-date>` para "datos nuevos" (lee `_manifest.json` por batch).
   - Mezcla con replay (`--replay-frac`).
   - Fine-tune con LR más bajo (default 2e-4 vs 1e-3 inicial), menos epochs.
   - Compara contra holdout. Promueve a nueva versión solo si supera el threshold.
   - Permite `--force-promote` para casos manuales.
4. ✅ `app/services/ml_detector.py`:
   - Lee `active.json` al instanciarse (con fallback a `settings.ML_MODEL_PATH`).
   - Expone version + holdout_miou + created_at en `model_info()` (endpoint `/ml-status`).
5. ✅ `backend/scripts/__init__.py` agregado para que `python -m scripts.xxx` funcione.

**Uso típico**:
```bash
# 1) Una vez por mes / cuando ready_to_train=true:
python -m scripts.finetune_model --epochs 10 --replay-frac 0.5

# Solo datos del último mes como "nuevos":
python -m scripts.finetune_model --since 2026-04-27

# Sin promover si no mejora >0.005:
# (default; explícito)
python -m scripts.finetune_model --promote-threshold 0.005

# Reentrenar desde cero (raro):
python -m scripts.train_model --epochs 30
```

**Definition of Done cumplido**:
- ✓ Fine-tune corre con un comando.
- ✓ Comparación automática vs modelo anterior en holdout fijo.
- ✓ Versiones numeradas con history JSON.
- ✓ `MLDetector` levanta automáticamente la versión activa.
- ✓ Cero downtime: el detector siempre tiene un modelo (el viejo) hasta que se promueve uno nuevo.

**Sintaxis ✓, frontend typecheck ✓.**

---

### Sprint 6 — Operaciones y monitoreo

**Status**: pendiente.

**Objetivo**: poder ver en producción cómo está performando el modelo.

**Tareas**:
1. Logging estructurado de cada inferencia (latencia, n elementos detectados, confianza media).
2. Métricas agregadas: % aceptación de candidatos por detector.
3. Rollback path: poder volver al checkpoint anterior si nuevo modelo regresiona.

**Definition of Done**:
- Dashboard mínimo en `/admin/ml-metrics`.
- Switch para forzar uso del modelo previo.

---

## Bitácora de avance

### 2026-05-27 — Sprint 0/1/2 cerrados

- Creado este documento con el roadmap.
- **Sprint 1 completo**: dependencias + `ml_detector.py` + endpoint `/ml-status`.
- **Sprint 2 completo**: etapa ML wired al pipeline. Co-existe con detector clásico (no rompe nada si modelo no está).
- Frontend typecheck ✓, sintaxis Python ✓.

### 2026-05-27 — Pivot por licencia + Sprint 3' cerrado

- Descubrimos que CubiCasa5K es CC-BY-NC (uso no comercial). Bloqueante para vender el producto.
- **Sprint 3 (descarga modelo CubiCasa5K) → CANCELADO**.
- **Sprint 3' (Generador sintético) → completado**:
  - `synthetic_generator.py` con 12 combos geométricos + 6 augmentations de estilo.
  - Endpoint `POST /plans/{id}/generate-synthetic`.
  - `api.generateSynthetic()` en el frontend.
- **Próximo paso**: Sprint 4' — pipeline de training inicial que use estas variaciones para producir el primer `cubicasa5k.pt` (mal nombre — renombrar a `scalistai_seg_v1.pt`).

### 2026-05-27 — Sprint 4' y Sprint 4 cerrados

- **Sprint 4' (training inicial)**: `scripts/train_model.py` con dataset PyTorch, U-Net resnet34, val con mIoU, best-checkpoint. CLI `python -m scripts.train_model`.
- **Sprint 4 (captura automática)**: migration 0008 + hook en activate + manifest de lineage + endpoint training-stats + consent toggle.
- Pipeline end-to-end ahora cierra el loop: usuario activa proyecto → snapshot automático → cuando hay ≥200 samples, training-stats marca `ready_to_train=true` → corremos train_model → modelo nuevo entra al pipeline.
- **Próximo paso**: Sprint 5 — fine-tuning incremental (re-entrenar con datos nuevos sin perder lo aprendido).

### 2026-05-27 — Sprint 5 cerrado

- Extraído código compartido a `scripts/_common.py` para que train y finetune no se dupliquen.
- `train_model.py` ahora congela un holdout fijo (10%) en `holdout.json` y escribe `active.json` apuntando a la versión productiva.
- `finetune_model.py` nuevo: parte del modelo activo, fine-tunea con mix de datos nuevos + replay, compara en holdout, promueve solo si supera threshold.
- `MLDetector` lee `active.json` al instanciarse → bajar un nuevo modelo es solo bajarlo del entrenamiento, no requiere reiniciar la app si está stateless.
- **Próximo paso**: Sprint 6 — operaciones y monitoreo (logging estructurado, métricas de aceptación, rollback).

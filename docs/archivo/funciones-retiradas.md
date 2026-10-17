# Funciones retiradas (octubre 2026)

El producto pasó a trabajar solo con modelos **IFC**. Se borraron dos bloques
que estaban ocultos desde el pivote de julio 2026. El código sigue en git.

- **Tag con todo intacto:** `archivo/planos-pdf-ia`, el último commit antes de
  borrar.
- **Ver un archivo:** `git show archivo/planos-pdf-ia:frontend/components/plan-viewer-inner.tsx`.
- **Recuperar una carpeta o archivo:** `git checkout archivo/planos-pdf-ia -- <ruta>`.
- **Volver todo atrás:** `git revert` del commit "chore: borrar planos PDF/DXF/DWG,
  visor y detección por IA". Si pasó mucho tiempo, conviene usar el archivo como
  referencia y rehacerlo sobre el flujo actual: modelos, permisos y `lib/api.ts`
  habrán cambiado.

## 1. Planos PDF / DXF / DWG con visor y detección automática

Qué hacía: subir un plano en PDF, DXF o DWG, calibrar la escala por página
(automática leyendo "1:100" del texto, o manual marcando una cota), elegir
qué páginas son planta, corte, estructura, etc., y dibujar o detectar muros,
recintos, aberturas, vigas y columnas sobre el plano. Tenía visor 3D, y
el cómputo salía de esos elementos × el catálogo de insumos y sistemas.

- **Frontend:**
  - Visores: `components/plan-viewer.tsx`, `plan-viewer-inner.tsx` (visor 2D,
    dibujo, selección y presupuesto lateral) y `plan-3d-viewer.tsx` (Three.js).
  - Escalas e IA: `scales-modal.tsx` y `ai-detection-banner.tsx`.
  - Wizard: `wizard/step-3-page-roles.tsx` (paso "Páginas" / capas DXF).
  - Página: `app/projects/[id]/page.tsx` era el visor; ahora solo redirige a
    Presupuesto u Obra.
  - Dependencias: `three`, `@react-three/fiber`, `@react-three/drei`.
- **Backend, routers:** `api/v1/plans/_detection.py`, `_dxf.py`, `_scale.py` y
  `_render.py`, `api/v1/integrations.py`, y en `_core.py` la subida de PDF/DXF,
  recommend-pages, suggest-roles, page-override y delete-page.
- **Backend, services:**
  - Planos: `pdf.py`, `preprocess.py`, `prewarm.py`, `auto_scale.py`,
    `dimension_text.py`, `dxf_import.py` y `pdf_vector_import.py`.
  - Detección: `room_derivation.py`, `hybrid_validation.py` y
    `auto_detect_pipeline.py`.
- **Infra:** ODA File Converter (DWG → DXF) y las librerías Qt/xcb/xvfb en el
  Dockerfile; dependencias `opencv-python-headless` y `ezdxf`.
- **Tests:** `test_dxf_import.py` y `test_pdf_vector_import.py`.

## 2. Modelo ML propio y detección con LLM

Qué hacía: entrenar un modelo de segmentación (PyTorch,
segmentation-models-pytorch) con variaciones sintéticas de los planos de los
usuarios (con su consentimiento) y planos procedurales, y usarlo para detectar
muros. También clasificaba capas DXF con un LLM local (ollama) y permitía
configurar un LLM externo por organización (BYOK: OpenAI, Anthropic, Gemini).

- **Frontend:** `app/admin/model/page.tsx` (flag `NEXT_PUBLIC_FEATURE_ML_MODEL`),
  `components/AiConfigSection.tsx` (BYOK en Equipo) y el checkbox de
  consentimiento de entrenamiento con sus términos en el paso Revisión del
  wizard.
- **Backend:**
  - Routers: `api/v1/plans/_training.py`, `api/v1/ai_providers.py`,
    `api/v1/organization.py` (ai-config), y en `projects.py` training-consent,
    regenerate-synthetic y el snapshot al activar.
  - ML: `ml_detector.py`, `training_manager.py`, `dxf_training.py`,
    `synthetic_generator.py` y `procedural_generator.py`.
  - LLM: `llm_detector.py` y `layer_llm.py`.
  - Config: `ML_*`, `ENABLE_*_DETECT*`, `AUTO_GENERATE_TRAINING_DATA` y
    `PROCEDURAL_DATA_DIR`.
  - Scripts: `train_model.py`, `finetune_model.py`, `gen_procedural.py`,
    `regenerate_synthetic.py`, `dxf_to_training.py`, `eval_product_metric.py`,
    `import_swiss_dwellings.py`, `backfill_geometry_measures.py` y `_common.py`.
- **Infra:** servicio `ollama`, reserva de GPU NVIDIA y `shm_size` en backend y
  worker; dependencias `torch`, `torchvision`, `segmentation-models-pytorch`,
  `matplotlib`, `openai`, `anthropic` y `google-generativeai`.
- **Tests:** `test_hybrid_validation.py` y `test_layer_llm.py`.

## Lo que se dejó a propósito

- **Base de datos sin tocar** (no hay migración). Siguen las columnas
  `plans.page_scales`, `page_roles`, `page_overrides`, `deleted_pages`,
  `organizations.ai_provider`/`ai_api_key`, `projects.allow_training_data` y la
  tabla `plan_ai_contexts`. Se pueden borrar con una migración cuando ya no
  interese recuperar nada.
- **`plans/_elements.py` y `plans/_export.py`:** los elementos detectados y el
  export siguen porque Gantt, Costos y Cambios todavía calculan con
  detected_elements + catálogo de insumos y sistemas.
- **Ocultos tras flags, sin borrar:** Inteligencia de Precios (`/precios`),
  Cómputos (`/materials`), presupuesto viejo y paso "Construcción". Ver el
  README.
- **Archivos sueltos fuera de git:** `backend/ODAFileConverter_*.deb` (56 MB) y el
  volumen de docker `ollama_data` (el modelo de ollama). Se pueden mandar a la
  papelera.

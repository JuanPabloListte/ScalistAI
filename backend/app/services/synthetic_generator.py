"""Generador de variaciones sintéticas a partir de planos reales del usuario.

Toma un plan + página, lee los elementos confirmados (muros, recintos,
aberturas) y genera N variaciones aplicando transformaciones geométricas
(rotación, espejo) y de estilo (brillo, ruido, espesor de trazos, inversión).

Cada variación se persiste como:
    storage/synthetic/plan_<id>/page_<N>/var_<NNN>/
        image.png    # Lo que el modelo ve
        mask.png     # uint8 single-channel: 0=fondo 1=muro 2=recinto
                     #                       3=puerta 4=ventana 5=puerta-ventana
                     #                       6=viga 7=columna 8=losa
        meta.json    # Transformaciones aplicadas, conteo de elementos, etc.

Las máscaras tienen ground truth perfecto porque las generamos nosotros — no
hay error de anotación. Esto es el dataset base para entrenar el modelo
propio (Sprint 4 — fine-tuning).

Diseño legalmente limpio: las variaciones son derivadas del plano original del
usuario (que ya está bajo licencia de uso para training según T&C), no de
ningún dataset externo con restricciones.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import random
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.detected_element import DetectedElement
from app.models.plan import Plan

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------
TARGET_SIZE = 512  # entrada estándar del U-Net

# Clases en la máscara — debe matchear `scripts._common.CLASS_NAMES`.
MASK_BG = 0
MASK_WALL = 1
MASK_ROOM = 2
MASK_DOOR = 3
MASK_WINDOW = 4
MASK_SLIDING_DOOR = 5
MASK_BEAM = 6
MASK_COLUMN = 7
MASK_ROOF = 8
MASK_RIOSTRA = 9
MASK_CLOACA = 10
MASK_ELECTRICIDAD = 11

# Espesores de trazo al "rasterizar" la geometría en la máscara
DEFAULT_WALL_THICK_PX = 4
DEFAULT_OPENING_THICK_PX = 10
# Vigas dibujadas como línea — equivalente visual a un muro pero notoriamente
# más ancho. Subimos a 18 px (vs 4 px de muro) porque con 10 px el modelo
# confundía vigas con muros: ambos eran "líneas finas" y CrossEntropy las
# colapsaba en la clase mayoritaria (wall). Si el usuario dibujó un polígono
# explícito, se respeta el polígono.
DEFAULT_BEAM_THICK_PX = 18
# Columnas dibujadas como punto único — usamos un círculo lleno para
# simular la sección. Si el usuario dibujó un polígono, se respeta.
# Subimos de 8 a 14 px porque con 8 px las columnas eran muy pocos pixeles
# (~400/sample vs 3000-7000 de viga) y el modelo no las aprendía: column
# IoU se quedaba en 0.08 mientras beam llegaba a 0.53.
DEFAULT_COLUMN_RADIUS_PX = 14
DEFAULT_RIOSTRA_THICK_PX = 18
DEFAULT_CLOACA_THICK_PX = 6
DEFAULT_ELECTRICIDAD_THICK_PX = 4

# Límites de seguridad
MIN_VARIATIONS = 1
MAX_VARIATIONS = 500


# ----------------------------------------------------------------------
# API pública
# ----------------------------------------------------------------------
def generate_synthetic_variations(
    plan_id: int,
    page: int,
    num_variations: int = 50,
    output_dir: Path | None = None,
    seed: int | None = None,
) -> list[dict]:
    """Genera variaciones sintéticas. Devuelve la lista de metadatas.

    Si no hay elementos en la página (nada confirmado por el usuario), no
    genera nada — sin elementos no hay ground truth útil.
    """
    if num_variations < MIN_VARIATIONS or num_variations > MAX_VARIATIONS:
        raise ValueError(
            f"num_variations debe estar entre {MIN_VARIATIONS} y {MAX_VARIATIONS}"
        )

    # ---- Carga de datos ----
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        if plan is None:
            return []
        elements: list[DetectedElement] = list(
            db.query(DetectedElement)
            .filter(
                DetectedElement.plan_id == plan_id,
                DetectedElement.page == page,
            )
            .all()
        )
        pdf_path = Path(plan.pdf_path)
        dpi = plan.dpi or 150
        project_id = plan.project_id

    if not pdf_path.exists():
        logger.warning("synthetic: PDF no encontrado plan=%s", plan_id)
        return []

    # Solo elementos con geometría real
    elements = [e for e in elements if e.geometry and e.geometry.get("points")]
    if not elements:
        logger.info(
            "synthetic: sin elementos en plan=%s page=%s — nada que generar",
            plan_id, page,
        )
        return []

    # ---- Render base + máscara base (una sola vez, a tamaño completo) ----
    image_full = _render_page_image(pdf_path, page - 1, dpi)
    H_full, W_full = image_full.shape[:2]
    # Los trazos finos (muros 4px, aberturas 5px, columnas) se dibujan a tamaño
    # COMPLETO y después se baja todo a 512. En planos grandes ese downscale
    # convierte un muro de 4px en <1px → desaparece. Compensamos engrosando los
    # trazos proporcional al factor de reducción, así sobreviven a 512.
    thick_mult = max(1.0, max(H_full, W_full) / float(TARGET_SIZE))
    mask_full = _build_mask_from_elements(elements, (H_full, W_full), thick_mult)

    # Downsample a TARGET_SIZE manteniendo aspect ratio, luego padding cuadrado.
    image_base, mask_base = _resize_and_pad(image_full, mask_full, TARGET_SIZE)

    # ---- Directorio de salida ----
    base_out = output_dir or (
        Path(settings.STORAGE_DIR) / "synthetic" / f"plan_{plan_id}" / f"page_{page}"
    )
    base_out.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed if seed is not None else plan_id * 10000 + page)

    # Las 12 combinaciones geométricas base (rot × flip) — son "gratis".
    geometric_combos: list[tuple[int, str | None]] = [
        (rot, flip)
        for rot in (0, 90, 180, 270)
        for flip in (None, "h", "v")
    ]

    # Snapshot timestamp + lineage común a todas las variaciones del batch
    snapshot_at = dt.datetime.now(dt.UTC).isoformat()
    element_counts = _count_elements_by_type(elements)

    metas: list[dict] = []
    for i in range(num_variations):
        meta = _generate_one_variation(
            i + 1, image_base, mask_base, geometric_combos, rng, base_out,
        )
        meta["source_project_id"] = project_id
        meta["source_plan_id"] = plan_id
        meta["source_page"] = page
        meta["element_counts"] = element_counts
        meta["snapshot_at"] = snapshot_at
        # Reescribir meta.json con el lineage extendido.
        var_dir = base_out / meta["variation_id"]
        (var_dir / "meta.json").write_text(json.dumps(meta, indent=2))
        metas.append(meta)

    # Manifesto del batch — útil para el script de training y para auditar.
    manifest = {
        "snapshot_at": snapshot_at,
        "project_id": project_id,
        "plan_id": plan_id,
        "page": page,
        "num_variations": len(metas),
        "element_counts": element_counts,
    }
    (base_out / "_manifest.json").write_text(json.dumps(manifest, indent=2))

    logger.info(
        "synthetic: generadas %d variaciones project=%s plan=%s page=%s en %s",
        len(metas), project_id, plan_id, page, base_out,
    )
    return metas


# ----------------------------------------------------------------------
# Generación de una variación
# ----------------------------------------------------------------------
def _generate_one_variation(
    idx: int,
    image_base,
    mask_base,
    geometric_combos: list,
    rng: random.Random,
    base_out: Path,
) -> dict:
    import cv2
    import numpy as np

    rot, flip = rng.choice(geometric_combos)
    img = _rotate(image_base, rot)
    mask = _rotate(mask_base, rot)
    if flip == "h":
        img = cv2.flip(img, 1)
        mask = cv2.flip(mask, 1)
    elif flip == "v":
        img = cv2.flip(img, 0)
        mask = cv2.flip(mask, 0)

    # ---- Style augmentations (solo en imagen, mask no cambia) ----
    style_ops: list[str] = []

    # Brillo / contraste
    if rng.random() < 0.5:
        beta = rng.randint(-30, 30)
        img = np.clip(img.astype(np.int16) + beta, 0, 255).astype(np.uint8)
        style_ops.append(f"brightness={beta}")
    if rng.random() < 0.4:
        alpha = rng.uniform(0.85, 1.15)
        img = np.clip(img.astype(np.float32) * alpha, 0, 255).astype(np.uint8)
        style_ops.append(f"contrast={alpha:.2f}")

    # Ruido gaussiano (simula scan/foto)
    if rng.random() < 0.3:
        sigma = rng.uniform(2.0, 8.0)
        noise = np.random.normal(0, sigma, img.shape).astype(np.float32)
        img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
        style_ops.append(f"noise_sigma={sigma:.1f}")

    # Inversión de color (modo oscuro)
    if rng.random() < 0.15:
        img = 255 - img
        style_ops.append("invert")

    # Espesor de trazo via morfología
    if rng.random() < 0.25:
        k = rng.choice([2, 3])
        kernel = np.ones((k, k), np.uint8)
        if rng.random() < 0.5:
            img = cv2.erode(img, kernel, iterations=1)
            style_ops.append(f"thinner_k{k}")
        else:
            img = cv2.dilate(img, kernel, iterations=1)
            style_ops.append(f"thicker_k{k}")

    # Blur leve (simula impresión / scan baja calidad)
    if rng.random() < 0.2:
        k = rng.choice([3, 5])
        img = cv2.GaussianBlur(img, (k, k), 0)
        style_ops.append(f"blur_k{k}")

    # ---- Persistir ----
    var_dir = base_out / f"var_{idx:03d}"
    var_dir.mkdir(exist_ok=True)
    # cv2.imwrite quiere BGR
    img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if img.ndim == 3 else img
    cv2.imwrite(str(var_dir / "image.png"), img_bgr)
    cv2.imwrite(str(var_dir / "mask.png"), mask)

    meta: dict[str, Any] = {
        "variation_id": f"var_{idx:03d}",
        "rotation": rot,
        "flip": flip,
        "style_ops": style_ops,
        "image_size": TARGET_SIZE,
        "image_path": str(var_dir / "image.png"),
        "mask_path": str(var_dir / "mask.png"),
    }
    (var_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _render_page_image(pdf_path: Path, page_index: int, dpi: int):
    """Rasteriza una página del PDF a numpy RGB uint8."""
    import fitz
    import numpy as np

    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(page_index)
        zoom = dpi / 72.0
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        h, w = pixmap.height, pixmap.width
        return np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(h, w, 3).copy()
    finally:
        doc.close()


def _build_mask_from_elements(
    elements: list[DetectedElement],
    shape: tuple[int, int],
    thick_mult: float = 1.0,
):
    """Construye la máscara uint8 con clases por píxel.

    `thick_mult` engrosa los trazos de línea/círculo (muros, aberturas, vigas,
    columnas) para que sobrevivan al downscale posterior a TARGET_SIZE. Los
    rellenos de polígono (recintos, losas) no lo necesitan: el área escala sola.

    Orden de pintado (los posteriores tapan a los anteriores en cada píxel):
      0. Losas/techos (fill) — el área más grande, va al fondo.
      1. Recintos (fill) — encima de la losa.
      2. Vigas (fill polígono).
      3. Columnas (fill polígono).
      4. Muros (line con espesor).
      5. Aberturas (line con espesor) — encima del muro porque "cortan" el muro.

    Losas van primero (al fondo) porque cubren toda la planta; recintos y
    estructura se dibujan encima. Vigas/columnas van antes de muros porque cuando
    un muro se apoya sobre una viga, la prioridad visual del muro define el píxel.
    Cuando una columna está junto a un muro, los píxeles compartidos quedan como
    muro: arquitectónicamente es lo mismo y simplifica la inferencia (el modelo no
    tiene que romperse la cabeza distinguiendo el borde exacto).
    """
    import cv2
    import numpy as np

    H, W = shape
    mask = np.zeros((H, W), dtype=np.uint8)

    # Espesores escalados al tamaño completo (se reducen al bajar a TARGET_SIZE).
    wall_t = max(DEFAULT_WALL_THICK_PX, int(round(DEFAULT_WALL_THICK_PX * thick_mult)))
    open_t = max(DEFAULT_OPENING_THICK_PX, int(round(DEFAULT_OPENING_THICK_PX * thick_mult)))
    beam_t = max(DEFAULT_BEAM_THICK_PX, int(round(DEFAULT_BEAM_THICK_PX * thick_mult)))
    col_r = max(DEFAULT_COLUMN_RADIUS_PX, int(round(DEFAULT_COLUMN_RADIUS_PX * thick_mult)))
    riostra_t = max(DEFAULT_RIOSTRA_THICK_PX, int(round(DEFAULT_RIOSTRA_THICK_PX * thick_mult)))
    cloaca_t = max(DEFAULT_CLOACA_THICK_PX, int(round(DEFAULT_CLOACA_THICK_PX * thick_mult)))
    elec_t = max(DEFAULT_ELECTRICIDAD_THICK_PX, int(round(DEFAULT_ELECTRICIDAD_THICK_PX * thick_mult)))

    # 0) Losas / techos (fill) — al fondo porque cubren toda la planta.
    for el in elements:
        if el.type != "roof":
            continue
        pts_flat = el.geometry.get("points") or []
        if len(pts_flat) < 6:  # mínimo 3 puntos (6 coords)
            continue
        pts = _chunk_points(pts_flat)
        if len(pts) < 3:
            continue
        cv2.fillPoly(mask, [pts.astype(np.int32)], MASK_ROOF)

    # 1) Recintos
    for el in elements:
        if el.type != "room":
            continue
        pts_flat = el.geometry.get("points") or []
        if len(pts_flat) < 6:  # mínimo 3 puntos (6 coords)
            continue
        pts = _chunk_points(pts_flat)
        if len(pts) < 3:
            continue
        cv2.fillPoly(mask, [pts.astype(np.int32)], MASK_ROOM)

    # 2) Vigas — el editor las guarda como línea (4 coords); el detector
    #    clásico las genera como polígono rectangular (≥6 coords). Aceptamos
    #    ambos formatos.
    for el in elements:
        if el.type != "beam":
            continue
        pts_flat = el.geometry.get("points") or []
        if len(pts_flat) >= 6:
            pts = _chunk_points(pts_flat)
            if len(pts) >= 3:
                cv2.fillPoly(mask, [pts.astype(np.int32)], MASK_BEAM)
        elif len(pts_flat) >= 4:
            x1, y1, x2, y2 = (int(round(v)) for v in pts_flat[:4])
            cv2.line(mask, (x1, y1), (x2, y2), MASK_BEAM, beam_t)

    # 3) Columnas — el editor las guarda como punto único (2 coords); el
    #    detector clásico las genera como polígono (≥6 coords). El punto único
    #    lo pintamos como un círculo lleno representando la sección.
    for el in elements:
        if el.type != "column":
            continue
        pts_flat = el.geometry.get("points") or []
        if len(pts_flat) >= 6:
            pts = _chunk_points(pts_flat)
            if len(pts) >= 3:
                cv2.fillPoly(mask, [pts.astype(np.int32)], MASK_COLUMN)
        elif len(pts_flat) >= 2:
            cx, cy = int(round(pts_flat[0])), int(round(pts_flat[1]))
            cv2.circle(mask, (cx, cy), col_r, MASK_COLUMN, -1)

    # 4) Muros
    for el in elements:
        if el.type != "wall":
            continue
        pts_flat = el.geometry.get("points") or []
        if len(pts_flat) < 4:
            continue
        x1, y1, x2, y2 = (int(round(v)) for v in pts_flat[:4])
        cv2.line(mask, (x1, y1), (x2, y2), MASK_WALL, wall_t)

    # 5) Aberturas
    for el in elements:
        if el.type != "opening":
            continue
        pts_flat = el.geometry.get("points") or []
        if len(pts_flat) < 4:
            continue
        x1, y1, x2, y2 = (int(round(v)) for v in pts_flat[:4])
        subtype = (el.geometry.get("subtype") or "door").lower()
        if "sliding" in subtype or "puerta ventana" in subtype or "puertaventana" in subtype:
            mask_val = MASK_SLIDING_DOOR
        elif "window" in subtype or "ventana" in subtype:
            mask_val = MASK_WINDOW
        else:
            mask_val = MASK_DOOR
        cv2.line(mask, (x1, y1), (x2, y2), mask_val, open_t)

    # 6) Instalaciones y Cimientos
    for el in elements:
        if el.type == "riostra":
            pts_flat = el.geometry.get("points") or []
            if len(pts_flat) >= 4:
                x1, y1, x2, y2 = (int(round(v)) for v in pts_flat[:4])
                cv2.line(mask, (x1, y1), (x2, y2), MASK_RIOSTRA, riostra_t)
        elif el.type == "cloaca":
            pts_flat = el.geometry.get("points") or []
            if len(pts_flat) >= 4:
                x1, y1, x2, y2 = (int(round(v)) for v in pts_flat[:4])
                cv2.line(mask, (x1, y1), (x2, y2), MASK_CLOACA, cloaca_t)
        elif el.type == "electricidad":
            pts_flat = el.geometry.get("points") or []
            if len(pts_flat) >= 4:
                x1, y1, x2, y2 = (int(round(v)) for v in pts_flat[:4])
                cv2.line(mask, (x1, y1), (x2, y2), MASK_ELECTRICIDAD, elec_t)

    return mask


def _chunk_points(flat: list[float]):
    """Convierte [x1,y1,x2,y2,...] en array Nx2 numpy."""
    import numpy as np

    n = len(flat) // 2
    arr = np.array(flat[: n * 2], dtype=np.float32).reshape(n, 2)
    return arr


def _resize_and_pad(image, mask, target: int):
    """Redimensiona manteniendo aspect ratio y rellena a cuadrado.

    Image: pad con blanco (255). Mask: pad con fondo (0).
    """
    import cv2
    import numpy as np

    H, W = image.shape[:2]
    scale = target / max(H, W)
    new_h = int(round(H * scale))
    new_w = int(round(W * scale))
    img_resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    mask_resized = cv2.resize(mask, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

    canvas_img_shape = (target, target, 3) if img_resized.ndim == 3 else (target, target)
    canvas_img = np.full(canvas_img_shape, 255, dtype=np.uint8)
    canvas_mask = np.zeros((target, target), dtype=np.uint8)

    # Centrado (no top-left): mejor para training porque no hay "esquina vacía"
    off_y = (target - new_h) // 2
    off_x = (target - new_w) // 2
    canvas_img[off_y:off_y + new_h, off_x:off_x + new_w] = img_resized
    canvas_mask[off_y:off_y + new_h, off_x:off_x + new_w] = mask_resized
    return canvas_img, canvas_mask


def _rotate(img, angle: int):
    """Rotación en múltiplos de 90° sin pérdida de información."""
    import cv2

    if angle == 0:
        return img
    if angle == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if angle == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if angle == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError(f"Rotación no soportada: {angle}")


def _count_elements_by_type(elements: list[DetectedElement]) -> dict[str, int]:
    counts = {"wall": 0, "room": 0, "opening": 0, "beam": 0, "column": 0, "roof": 0, "riostra": 0, "cloaca": 0, "electricidad": 0}
    for el in elements:
        if el.type in counts:
            counts[el.type] += 1
    return counts

"""Detector ML basado en un modelo de segmentación U-Net propio.

El modelo se entrena 100% sobre datos sintéticos derivados de los planos del
propio usuario (ver `synthetic_generator.py` + `scripts/train_model.py`), con
backbone ResNet34 inicializado en ImageNet. No se usa CubiCasa5K ni ningún
dataset externo (licencias non-commercial incompatibles con el uso del producto).

Diseño:
- Carga **lazy** del modelo en primera invocación (no bloquea el arranque).
- Si el archivo del modelo no existe, `is_available()` devuelve False y el
  pipeline cae al detector clásico (sin romper nada).
- Singleton accesible vía `get_ml_detector()`.
- Salidas convertidas al formato `DetectedElement` (polígonos + tipos).

El modelo esperado es un U-Net o equivalente con salida multi-clase. El número
y orden de canales lo decide el `active.json` (campos `num_classes` y
`class_names`). El set actual de la app es:
    canal 0 → fondo
    canal 1 → muros
    canal 2 → recintos
    canal 3 → aberturas (puertas + ventanas)
    canal 4 → vigas
    canal 5 → columnas
    canal 6 → losas / techos

Si el `active.json` no tiene esos campos (modelos viejos), defaulteamos al set
legacy de 4 clases (bg, wall, room, opening).

`_postprocess` despacha por nombre de clase, así que sumar `roof` u otros
tipos en el futuro requiere sólo añadir el handler y reentrenar.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


# --- Constantes del modelo ---
# Tamaño de entrada al modelo (CubiCasa5K original usa 512x512 padded).
MODEL_INPUT_SIZE = 512
# Threshold sobre la sigmoid de cada canal para considerar un pixel como
# perteneciente a la clase. Calibrable después del primer fine-tune.
PROB_THRESHOLD = 0.5
# Mínima área en m² para considerar un componente conexo como válido.
MIN_WALL_LENGTH_M = 0.5
MIN_ROOM_AREA_M2 = 0.8
MIN_OPENING_LENGTH_M = 0.4
# Vigas: lado mayor mínimo y aspecto mínimo para que cuente como "viga"
# (rectangulo alargado, no un cuadrado).
MIN_BEAM_LENGTH_M = 0.8
MIN_BEAM_ASPECT = 2.5
# Columnas: área de sección mínima y máxima en m².
MIN_COLUMN_AREA_M2 = 0.03
MAX_COLUMN_AREA_M2 = 1.0
# Losas/techos: área mínima (son grandes, tipo recinto/planta).
MIN_ROOF_AREA_M2 = 1.0

# Set legacy: si active.json no tiene `class_names`, asumimos este orden.
_LEGACY_CLASS_NAMES = ["background", "wall", "room", "opening", "beam", "column", "roof", "riostra", "cloaca", "electricidad"]


@dataclass
class MLDetectionResult:
    """Resultado de una inferencia: candidatos por tipo, compatible con
    el formato que espera `auto_detect_pipeline._create_*_elements`."""
    walls: list[dict] = field(default_factory=list)
    rooms: list[dict] = field(default_factory=list)
    openings: list[dict] = field(default_factory=list)
    beams: list[dict] = field(default_factory=list)
    columns: list[dict] = field(default_factory=list)
    roofs: list[dict] = field(default_factory=list)
    riostras: list[dict] = field(default_factory=list)
    cloacas: list[dict] = field(default_factory=list)
    electricidad: list[dict] = field(default_factory=list)
    escaleras: list[dict] = field(default_factory=list)
    # Metadata útil para logging y feedback.
    model_version: str = "unknown"
    inference_time_ms: float = 0.0


def _resolve_active_model_path(default_path: str) -> tuple[Path, dict | None]:
    """Devuelve (path, active_info) leyendo `backend/models/active.json` si existe.

    Sprint 5: `train_model.py` y `finetune_model.py` mantienen `active.json`
    apuntando a la versión productiva. Cuando no existe (ambiente fresh,
    o se borró), caemos al `settings.ML_MODEL_PATH` legacy.
    """
    active_file = Path("models/active.json")
    if not active_file.exists():
        active_file = Path("backend/models/active.json")
        
    if active_file.exists():
        try:
            data = json.loads(active_file.read_text())
            p_str = str(data.get("path", ""))
            
            # Ajuste dinámico: Si active.json se generó en el host dice "backend/models/..."
            # Pero si estamos corriendo en Docker, nuestro cwd es /app y el folder se llama "models/"
            if p_str.startswith("backend/models/") and not Path(p_str).exists():
                p_str = p_str.replace("backend/models/", "models/", 1)
                
            p = Path(p_str)
            if p.exists():
                return p, data
        except Exception:  # noqa: BLE001
            pass
            
    default_p = default_path
    if default_p.startswith("./backend/models/") and not Path(default_p).exists():
        default_p = default_p.replace("./backend/models/", "./models/", 1)
        
    return Path(default_p), None


def _resolve_class_names(active_info: dict | None) -> list[str]:
    """Extrae `class_names` del active.json. Si no hay (modelo legacy de 4
    clases, o sin active.json), devuelve el set legacy.

    Validación: la lista debe ser un list[str] y arrancar con "background"
    (canal 0). Si algo no calza, devolvemos legacy para no cargar un modelo
    con metadata corrupta.
    """
    if not active_info:
        return list(_LEGACY_CLASS_NAMES)
    names = active_info.get("class_names")
    if not isinstance(names, list) or not all(isinstance(x, str) for x in names):
        return list(_LEGACY_CLASS_NAMES)
    if not names or names[0] != "background":
        return list(_LEGACY_CLASS_NAMES)
    return list(names)


class MLDetector:
    """Wrapper sobre el modelo PyTorch. Carga el peso del disco una sola vez."""

    def __init__(self, model_path: Path | str | None = None) -> None:
        self._model = None
        self._device = None
        if model_path is not None:
            self._model_path = Path(model_path)
            self._active_info: dict | None = None
        else:
            self._model_path, self._active_info = _resolve_active_model_path(
                settings.ML_MODEL_PATH
            )
        self._model_hash: str | None = None
        self._load_lock = threading.Lock()
        self._load_attempted = False
        # Arquitectura: leemos del active.json. Sin info → legacy (4 clases).
        self._class_names: list[str] = _resolve_class_names(self._active_info)
        self._num_classes: int = len(self._class_names)

    def reload(self) -> None:
        """Descarta el modelo en memoria y vuelve a buscar el path activo
        en active.json, de modo que la próxima inferencia use el nuevo modelo.
        """
        with self._load_lock:
            self._model_path, self._active_info = _resolve_active_model_path(
                settings.ML_MODEL_PATH
            )
            self._model = None
            self._model_hash = None
            self._device = None
            self._load_attempted = False
            # Re-leer la arquitectura por si el nuevo modelo cambió el set
            # de clases (ej: pasamos de 4 a 6 canales).
            self._class_names = _resolve_class_names(self._active_info)
            self._num_classes = len(self._class_names)

    # ------------------------------------------------------------------
    # Disponibilidad
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """True si el modelo existe en disco y ML está habilitado en config."""
        if not settings.ENABLE_ML_DETECTION:
            return False
        return self._model_path.exists() and self._model_path.stat().st_size > 0

    def model_info(self) -> dict[str, Any]:
        """Información del modelo para el endpoint de status."""
        exists = self._model_path.exists()
        return {
            "enabled": settings.ENABLE_ML_DETECTION,
            "model_path": str(self._model_path),
            "model_exists": exists,
            "model_loaded": self._model is not None,
            "model_size_mb": (
                round(self._model_path.stat().st_size / (1024 * 1024), 2)
                if exists else None
            ),
            "device": self._device,
            "model_hash": self._model_hash,
            "active_version": (self._active_info or {}).get("version"),
            "active_holdout_miou": (self._active_info or {}).get("holdout_miou"),
            "active_created_at": (self._active_info or {}).get("created_at"),
        }

    # ------------------------------------------------------------------
    # Carga del modelo (lazy)
    # ------------------------------------------------------------------
    def _ensure_loaded(self) -> bool:
        """Carga el modelo en memoria si no lo hizo ya. Devuelve True si quedó
        listo para inferir."""
        if self._model is not None:
            return True
        if self._load_attempted and self._model is None:
            return False
        with self._load_lock:
            if self._model is not None:
                return True
            self._load_attempted = True
            if not self.is_available():
                logger.info(
                    "ML model not available at %s — falling back to classical detection",
                    self._model_path,
                )
                return False
            try:
                self._load_model()
                return True
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to load ML model: %s", exc)
                self._model = None
                return False

    def _load_model(self) -> None:
        """Carga el checkpoint y mueve al device correcto."""
        import torch
        import segmentation_models_pytorch as smp

        # Detección de device
        if settings.ML_DEVICE == "auto":
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self._device = settings.ML_DEVICE
        logger.info("Loading ML model on device=%s from %s", self._device, self._model_path)

        # Hash del archivo para tracking
        self._model_hash = _file_sha256(self._model_path)[:12]

        # Arquitectura: U-Net + ResNet34, con la cantidad de canales que
        # declare el active.json. Si el active.json no la trae (modelo viejo),
        # usamos legacy de 4. Cargar un checkpoint con N canales en una
        # arquitectura de M (N≠M) tira RuntimeError en load_state_dict —
        # cuando eso pasa significa que el active.json está desincronizado
        # con el .pt y hay que reentrenar.
        logger.info(
            "ML model architecture: classes=%d (%s)",
            self._num_classes, self._class_names,
        )
        model = smp.Unet(
            encoder_name="resnet34",
            encoder_weights=None,  # ya viene en el checkpoint
            in_channels=3,
            classes=self._num_classes,
        )

        state_dict = torch.load(self._model_path, map_location=self._device)
        # Algunos checkpoints guardan {"state_dict": ...}, otros directo.
        if isinstance(state_dict, dict) and "state_dict" in state_dict:
            state_dict = state_dict["state_dict"]
        model.load_state_dict(state_dict, strict=False)
        model.to(self._device)
        model.eval()
        self._model = model
        logger.info("ML model loaded successfully (hash=%s)", self._model_hash)

    # ------------------------------------------------------------------
    # Inferencia
    # ------------------------------------------------------------------
    def detect(
        self,
        image_rgb: "Any",  # np.ndarray HxWx3 uint8
        px_per_m: float | None,
        page_index: int = 0,
    ) -> MLDetectionResult:
        """Corre inferencia sobre una página rasterizada.

        Args:
            image_rgb: imagen de la página en RGB uint8.
            px_per_m: escala (pixels por metro). Si None usa default 150.
            page_index: número de página 0-indexed (para el campo `page` en
                los candidatos).

        Returns:
            MLDetectionResult con listas de candidatos por tipo. Si el modelo
            no está disponible, devuelve un resultado vacío.
        """
        if not self._ensure_loaded():
            return MLDetectionResult()

        import time
        import numpy as np
        import torch

        t0 = time.perf_counter()
        scale = px_per_m if (px_per_m and px_per_m > 0) else 150.0
        orig_h, orig_w = image_rgb.shape[:2]

        # Preprocess: resize a MODEL_INPUT_SIZE manteniendo aspect ratio + padding.
        tensor, scale_back = _preprocess(image_rgb, MODEL_INPUT_SIZE)
        tensor = tensor.to(self._device)

        # Inferencia.
        # El modelo se entrena con CrossEntropyLoss (softmax: las clases compiten
        # por cada píxel). Por eso acá usamos softmax + argmax, NO sigmoid por
        # canal: con sigmoid+threshold el objetivo de inferencia no coincide con
        # el de entrenamiento y se degradan todas las clases. `_postprocess`
        # asigna cada píxel a su clase ganadora (argmax).
        with torch.no_grad():
            logits = self._model(tensor)  # (1, C, H, W)
            probs = torch.softmax(logits, dim=1).cpu().numpy()[0]  # (C, H, W)

        # Postprocess: despacha por nombre de clase para que sumar tipos
        # nuevos solo requiera agregar el handler en `_postprocess`.
        result = _postprocess(
            probs, scale_back, orig_w, orig_h, scale, page_index,
            class_names=self._class_names,
        )
        result.model_version = self._model_hash or "loaded"
        result.inference_time_ms = (time.perf_counter() - t0) * 1000.0
        logger.info(
            "ML inference page=%s walls=%d rooms=%d openings=%d "
            "beams=%d columns=%d roofs=%d %.0fms",
            page_index + 1, len(result.walls), len(result.rooms),
            len(result.openings), len(result.beams), len(result.columns),
            len(result.roofs), result.inference_time_ms,
        )
        return result


# ----------------------------------------------------------------------
# Singleton helper
# ----------------------------------------------------------------------
_instance: MLDetector | None = None
_instance_lock = threading.Lock()


def get_ml_detector() -> MLDetector:
    """Devuelve el detector ML global (singleton). Se inicializa al primer call.
    No carga el modelo todavía — eso pasa en la primera invocación de detect().
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = MLDetector()
    return _instance


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _preprocess(image_rgb, target_size: int):
    """Reescala manteniendo aspect ratio + pad a target_size×target_size.
    Devuelve (tensor 1x3xHxW float [0,1], factor de vuelta a coords originales).
    """
    import numpy as np
    import torch

    h, w = image_rgb.shape[:2]
    scale = target_size / max(h, w)
    new_h = int(round(h * scale))
    new_w = int(round(w * scale))
    import cv2
    resized = cv2.resize(image_rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((target_size, target_size, 3), dtype=np.uint8)
    canvas[:new_h, :new_w] = resized
    # Normalización imagenet (la mayoría de pretrained la usan)
    arr = canvas.astype(np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    arr = (arr - mean) / std
    arr = arr.transpose(2, 0, 1)  # HWC → CHW
    tensor = torch.from_numpy(arr).unsqueeze(0)  # 1xCxHxW
    # Devolvemos info para mapear coords de máscara → coords originales.
    scale_back = {
        "scale": scale,
        "new_h": new_h,
        "new_w": new_w,
        "orig_h": h,
        "orig_w": w,
    }
    return tensor, scale_back


def _postprocess(
    probs,
    scale_back: dict,
    orig_w: int,
    orig_h: int,
    px_per_m: float,
    page_index: int,
    class_names: list[str],
) -> MLDetectionResult:
    """Convierte probabilidades por canal en candidatos de Detección.

    Despacha por `class_names[c]` (canal 0 = background, los siguientes son
    las clases reales). Esto desacopla el código del orden exacto de canales
    y deja que el modelo declare su propia configuración vía active.json.
    """
    import cv2
    import numpy as np

    new_h = scale_back["new_h"]
    new_w = scale_back["new_w"]

    def _to_orig(mask: np.ndarray) -> np.ndarray:
        crop = mask[:new_h, :new_w]
        return cv2.resize(crop, (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)

    result = MLDetectionResult()

    # Clase ganadora por píxel (consistente con el softmax del entrenamiento).
    # Adicionalmente exigimos confianza mínima: si ninguna clase supera
    # PROB_THRESHOLD el píxel queda como fondo (evita pintar clases dudosas).
    labelmap = probs.argmax(axis=0)
    confident = probs.max(axis=0) >= PROB_THRESHOLD

    for ch_idx, name in enumerate(class_names):
        if ch_idx == 0:  # background, no se persiste
            continue
        if ch_idx >= probs.shape[0]:
            # active.json declara más clases que canales reales — ignoramos
            # las extras en lugar de crashear.
            break
        mask = _to_orig(((labelmap == ch_idx) & confident).astype(np.uint8) * 255)
        if mask.sum() == 0:
            continue
        if name == "wall":
            _emit_walls(result, mask, px_per_m, page_index)
        elif name == "room":
            _emit_rooms(result, mask, px_per_m, page_index)
        elif name == "opening":
            _emit_openings(result, mask, px_per_m, page_index, subtype="door")
        elif name == "door":
            _emit_openings(result, mask, px_per_m, page_index, subtype="door")
        elif name == "window":
            _emit_openings(result, mask, px_per_m, page_index, subtype="window")
        elif name == "sliding_door":
            _emit_openings(result, mask, px_per_m, page_index, subtype="sliding-door")
        elif name == "beam":
            _emit_beams(result, mask, px_per_m, page_index)
        elif name == "column":
            _emit_columns(result, mask, px_per_m, page_index)
        elif name == "roof":
            _emit_roofs(result, mask, px_per_m, page_index)
        elif name == "riostra":
            _emit_riostras(result, mask, px_per_m, page_index)
        elif name == "cloaca":
            _emit_cloacas(result, mask, px_per_m, page_index)
        elif name == "electricidad":
            _emit_electricidad(result, mask, px_per_m, page_index)
        elif name == "escalera":
            _emit_escaleras(result, mask, px_per_m, page_index)
        # Tipos desconocidos los ignoramos silenciosamente — los suma quien
        # extienda los handlers (ej: futuro `roof`).

    return result


# ----------------------------------------------------------------------
# Handlers por clase
# ----------------------------------------------------------------------
def _emit_walls(result: MLDetectionResult, mask, px_per_m: float, page_index: int) -> None:
    import cv2
    import numpy as np

    skel = _skeletonize(mask)
    min_len_px = int(MIN_WALL_LENGTH_M * px_per_m)
    lines = cv2.HoughLinesP(
        skel, rho=1, theta=np.pi / 180, threshold=20,
        minLineLength=min_len_px, maxLineGap=int(0.25 * px_per_m),
    )
    if lines is None:
        return
    for idx, line in enumerate(lines, start=1):
        x1, y1, x2, y2 = (float(v) for v in line[0])
        length_px = float(np.hypot(x2 - x1, y2 - y1))
        length_m = length_px / px_per_m
        if length_m < MIN_WALL_LENGTH_M:
            continue
        result.walls.append({
            "id": f"ml_wall_{idx}",
            "type": "wall",
            "geometry": {
                "points": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                "label": f"Muro ML {idx}",
            },
            "length_m": round(length_m, 2),
            "area_m2": None,
            "height_m": 2.8,
            "page": page_index + 1,
        })


def _emit_rooms(result: MLDetectionResult, mask, px_per_m: float, page_index: int) -> None:
    import cv2

    n_labels, labels = cv2.connectedComponents(mask, connectivity=4)
    for comp_id in range(1, n_labels):
        comp = (labels == comp_id).astype("uint8") * 255
        area_px = int(comp.sum() // 255)
        area_m2 = area_px / (px_per_m * px_per_m)
        if area_m2 < MIN_ROOM_AREA_M2 or area_m2 > 400:
            continue
        contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        perim = cv2.arcLength(contour, True)
        eps = max(0.005 * perim, 3.0)
        approx = cv2.approxPolyDP(contour, eps, True)
        if len(approx) < 3:
            continue
        pts: list[float] = []
        for pt in approx:
            pts.append(round(float(pt[0][0]), 2))
            pts.append(round(float(pt[0][1]), 2))
        idx = len(result.rooms) + 1
        result.rooms.append({
            "id": f"ml_room_{idx}",
            "type": "room",
            "geometry": {"points": pts, "label": f"Recinto ML {idx}"},
            "length_m": None,
            "area_m2": round(area_m2, 2),
            "height_m": 2.8,
            "page": page_index + 1,
        })


def _emit_escaleras(result: MLDetectionResult, mask, px_per_m: float, page_index: int) -> None:
    """Escaleras: cada componente conexo → polígono con área (ocupan superficie;
    el cómputo de hormigón/revestimiento sale del m²)."""
    import cv2

    n_labels, labels = cv2.connectedComponents(mask, connectivity=4)
    for comp_id in range(1, n_labels):
        comp = (labels == comp_id).astype("uint8") * 255
        area_px = int(comp.sum() // 255)
        area_m2 = area_px / (px_per_m * px_per_m)
        if area_m2 < 1.0 or area_m2 > 40.0:
            continue
        contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        eps = max(0.005 * cv2.arcLength(contour, True), 3.0)
        approx = cv2.approxPolyDP(contour, eps, True)
        if len(approx) < 3:
            continue
        pts: list[float] = []
        for pt in approx:
            pts.append(round(float(pt[0][0]), 2))
            pts.append(round(float(pt[0][1]), 2))
        idx = len(result.escaleras) + 1
        result.escaleras.append({
            "id": f"ml_escalera_{idx}",
            "type": "escalera",
            "geometry": {"points": pts, "label": f"Escalera ML {idx}"},
            "length_m": None,
            "area_m2": round(area_m2, 2),
            "height_m": 2.8,
            "page": page_index + 1,
        })


def _emit_roofs(result: MLDetectionResult, mask, px_per_m: float, page_index: int) -> None:
    """Losas / techos: cada componente conexo grande → polígono. Mismo enfoque
    que recintos (fill area), pero con semántica de losa (altura = espesor)."""
    import cv2

    n_labels, labels = cv2.connectedComponents(mask, connectivity=4)
    for comp_id in range(1, n_labels):
        comp = (labels == comp_id).astype("uint8") * 255
        area_px = int(comp.sum() // 255)
        area_m2 = area_px / (px_per_m * px_per_m)
        if area_m2 < MIN_ROOF_AREA_M2:
            continue
        contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        perim = cv2.arcLength(contour, True)
        eps = max(0.005 * perim, 3.0)
        approx = cv2.approxPolyDP(contour, eps, True)
        if len(approx) < 3:
            continue
        pts: list[float] = []
        for pt in approx:
            pts.append(round(float(pt[0][0]), 2))
            pts.append(round(float(pt[0][1]), 2))
        idx = len(result.roofs) + 1
        result.roofs.append({
            "id": f"ml_roof_{idx}",
            "type": "roof",
            "geometry": {"points": pts, "label": f"Losa ML {idx}"},
            "length_m": None,
            "area_m2": round(area_m2, 2),
            "height_m": 0.20,  # espesor default de losa
            "page": page_index + 1,
        })


def _emit_openings(result: MLDetectionResult, mask, px_per_m: float, page_index: int, subtype: str = "door") -> None:
    import cv2

    n_labels, _labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=4
    )
    for comp_id in range(1, n_labels):
        x, y, w, h, _area = stats[comp_id]
        if max(w, h) < int(MIN_OPENING_LENGTH_M * px_per_m):
            continue
        cx, cy = centroids[comp_id]
        if w >= h:
            x1, y1 = float(x), float(cy)
            x2, y2 = float(x + w), float(cy)
        else:
            x1, y1 = float(cx), float(y)
            x2, y2 = float(cx), float(y + h)
        length_m = max(w, h) / px_per_m
        idx = len(result.openings) + 1
        result.openings.append({
            "id": f"ml_opening_{idx}",
            "type": "opening",
            "cx": float(cx),
            "cy": float(cy),
            "default_width_m": round(length_m, 2),
            "orientation": "h" if w >= h else "v",
            "label": f"Abertura ML {idx}",
            "subtype": subtype,
            "geometry": {
                "points": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                "label": f"Abertura ML {idx}",
                "subtype": subtype,
            },
            "length_m": round(length_m, 2),
            "area_m2": None,
            "height_m": 2.1,
            "page": page_index + 1,
        })


def _emit_beams(result: MLDetectionResult, mask, px_per_m: float, page_index: int) -> None:
    """Vigas: bbox de cada componente, sólo si es alargado y respeta dimensiones
    típicas. El modelo entrega "blobs de viga"; postproceso decide formato."""
    import cv2

    n_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )
    for comp_id in range(1, n_labels):
        x, y, w, h, area = stats[comp_id]
        w_m = w / px_per_m
        h_m = h / px_per_m
        major = max(w_m, h_m)
        minor = min(w_m, h_m)
        if major < MIN_BEAM_LENGTH_M:
            continue
        if minor < 0.10 or minor > 0.90:
            continue
        if minor < 1e-3 or major / minor < MIN_BEAM_ASPECT:
            continue
        if area / max(w * h, 1) < 0.30:
            continue
        idx = len(result.beams) + 1
        pts = [
            float(x), float(y),
            float(x + w), float(y),
            float(x + w), float(y + h),
            float(x), float(y + h),
        ]
        pts = [round(p, 2) for p in pts]
        result.beams.append({
            "id": f"ml_beam_{idx}",
            "type": "beam",
            "geometry": {"points": pts, "label": f"Viga ML {idx}"},
            "length_m": round(major, 2),
            "area_m2": round(w_m * h_m, 3),
            "height_m": 0.40,
            "page": page_index + 1,
        })


def _emit_columns(result: MLDetectionResult, mask, px_per_m: float, page_index: int) -> None:
    """Columnas: bbox aproximadamente cuadrado, con dimensiones típicas de
    sección de columna."""
    import cv2

    n_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )
    for comp_id in range(1, n_labels):
        x, y, w, h, area = stats[comp_id]
        w_m = w / px_per_m
        h_m = h / px_per_m
        area_m2 = (area / (px_per_m * px_per_m))
        if not (MIN_COLUMN_AREA_M2 <= area_m2 <= MAX_COLUMN_AREA_M2):
            continue
        if not (0.12 <= w_m <= 0.90 and 0.12 <= h_m <= 0.90):
            continue
        ratio = max(w_m, h_m) / max(min(w_m, h_m), 1e-3)
        if ratio > 2.5:
            continue
        if area / max(w * h, 1) < 0.55:
            continue
        idx = len(result.columns) + 1
        pts = [
            float(x), float(y),
            float(x + w), float(y),
            float(x + w), float(y + h),
            float(x), float(y + h),
        ]
        pts = [round(p, 2) for p in pts]
        result.columns.append({
            "id": f"ml_column_{idx}",
            "type": "column",
            "geometry": {"points": pts, "label": f"Columna ML {idx}"},
            "length_m": None,
            "area_m2": round(area_m2, 3),
            "height_m": 2.8,
            "page": page_index + 1,
        })


def _skeletonize(mask) -> "Any":
    """Esqueletización morfológica (algoritmo de Zhang-Suen via OpenCV).
    Reduce la máscara binaria a líneas de 1 pixel de espesor."""
    import cv2
    import numpy as np

    img = mask.copy()
    skel = np.zeros(img.shape, np.uint8)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    while True:
        eroded = cv2.erode(img, element)
        temp = cv2.dilate(eroded, element)
        temp = cv2.subtract(img, temp)
        skel = cv2.bitwise_or(skel, temp)
        img = eroded.copy()
        if cv2.countNonZero(img) == 0:
            break
    return skel


def _emit_riostras(result: MLDetectionResult, mask, px_per_m: float, page_index: int) -> None:
    import cv2
    import numpy as np

    skel = _skeletonize(mask)
    min_len_px = int(MIN_WALL_LENGTH_M * px_per_m)
    lines = cv2.HoughLinesP(
        skel, rho=1, theta=np.pi / 180, threshold=20,
        minLineLength=min_len_px, maxLineGap=int(0.25 * px_per_m),
    )
    if lines is None:
        return
    for idx, line in enumerate(lines, start=1):
        x1, y1, x2, y2 = (float(v) for v in line[0])
        length_px = float(np.hypot(x2 - x1, y2 - y1))
        length_m = length_px / px_per_m
        if length_m < MIN_WALL_LENGTH_M:
            continue
        result.riostras.append({
            "id": f"ml_riostra_{idx}",
            "type": "riostra",
            "geometry": {
                "points": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                "label": f"Riostra ML {idx}",
            },
            "length_m": round(length_m, 2),
            "area_m2": None,
            "height_m": 0.4,
            "page": page_index + 1,
        })


def _emit_cloacas(result: MLDetectionResult, mask, px_per_m: float, page_index: int) -> None:
    import cv2
    import numpy as np

    skel = _skeletonize(mask)
    min_len_px = int(MIN_WALL_LENGTH_M * px_per_m)
    lines = cv2.HoughLinesP(
        skel, rho=1, theta=np.pi / 180, threshold=20,
        minLineLength=min_len_px, maxLineGap=int(0.25 * px_per_m),
    )
    if lines is None:
        return
    for idx, line in enumerate(lines, start=1):
        x1, y1, x2, y2 = (float(v) for v in line[0])
        length_px = float(np.hypot(x2 - x1, y2 - y1))
        length_m = length_px / px_per_m
        if length_m < MIN_WALL_LENGTH_M:
            continue
        result.cloacas.append({
            "id": f"ml_cloaca_{idx}",
            "type": "cloaca",
            "geometry": {
                "points": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                "label": f"Cloaca ML {idx}",
            },
            "length_m": round(length_m, 2),
            "area_m2": None,
            "height_m": 0.1,
            "page": page_index + 1,
        })


def _emit_electricidad(result: MLDetectionResult, mask, px_per_m: float, page_index: int) -> None:
    import cv2
    import numpy as np

    skel = _skeletonize(mask)
    min_len_px = int(MIN_WALL_LENGTH_M * px_per_m)
    lines = cv2.HoughLinesP(
        skel, rho=1, theta=np.pi / 180, threshold=20,
        minLineLength=min_len_px, maxLineGap=int(0.25 * px_per_m),
    )
    if lines is None:
        return
    for idx, line in enumerate(lines, start=1):
        x1, y1, x2, y2 = (float(v) for v in line[0])
        length_px = float(np.hypot(x2 - x1, y2 - y1))
        length_m = length_px / px_per_m
        if length_m < MIN_WALL_LENGTH_M:
            continue
        result.electricidad.append({
            "id": f"ml_electricidad_{idx}",
            "type": "electricidad",
            "geometry": {
                "points": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                "label": f"Electricidad ML {idx}",
            },
            "length_m": round(length_m, 2),
            "area_m2": None,
            "height_m": 0.05,
            "page": page_index + 1,
        })

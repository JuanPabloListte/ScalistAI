"""Helpers compartidos entre `train_model.py` y `finetune_model.py`.

Contiene:
- `SyntheticDataset`: PyTorch Dataset que lee pares (image.png, mask.png).
- `build_unet_model`: arquitectura unificada para training e inference.
- `discover_samples`: encuentra todos los samples en storage/synthetic.
- `read_active_model`/`write_active_model`: pointer a la versión activa.
- `read_holdout`/`write_holdout`: holdout fijo para comparar versiones.

Constantes:
- `INPUT_SIZE`: tamaño de entrada al modelo (debe matchear con ml_detector).
- `CLASS_NAMES`/`NUM_CLASSES`: 6 clases (bg, wall, room, opening, beam, column).
  Si cambia el set, el nuevo `active.json` registra `num_classes` y `class_names`
  para que `ml_detector` reconstruya la arquitectura correcta al cargar.
- `IMAGENET_MEAN/STD`: normalización consistente con ml_detector._preprocess.

Si modificás algo acá, asegurate de que ml_detector.py siga compatible —
especialmente la arquitectura del modelo.
"""
from __future__ import annotations

import datetime as dt
import json
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np


# ----------------------------------------------------------------------
# Constantes (sincronizadas con app/services/ml_detector.py)
# ----------------------------------------------------------------------
CLASS_NAMES = ["background", "wall", "room", "door", "window", "sliding_door", "beam", "column", "roof"]
NUM_CLASSES = len(CLASS_NAMES)
INPUT_SIZE = 512

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# Pesos por clase para CrossEntropy. Vigas y columnas pesan más porque
# son raras y de pocos pixeles. El orden DEBE matchear CLASS_NAMES.
CLASS_WEIGHTS = [0.1, 1.0, 1.0, 3.0, 3.0, 3.0, 1.5, 1.8, 1.0]

# Paths convencionales
MODELS_DIR = Path("backend/models")
ACTIVE_MODEL_FILE = MODELS_DIR / "active.json"
HOLDOUT_FILE = MODELS_DIR / "holdout.json"


# ----------------------------------------------------------------------
# Dataset
# ----------------------------------------------------------------------
def discover_samples(root: Path) -> list[tuple[Path, Path]]:
    """Devuelve lista de pares (image.png, mask.png) bajo el root."""
    pairs: list[tuple[Path, Path]] = []
    for img_path in sorted(root.rglob("**/image.png")):
        mask_path = img_path.parent / "mask.png"
        if mask_path.exists():
            pairs.append((img_path, mask_path))
    return pairs


def _augment_pair(img: np.ndarray, mask: np.ndarray, rng: random.Random):
    """Augmentation estocástica train-only (img RGB uint8, mask uint8 HxW).

    Sin datos externos, la diversidad de *layouts* es la restricción dura del
    dataset (pocos planos reales, el resto son variaciones geométricas de los
    mismos). Estos ops generan, en cada epoch, vistas nuevas del mismo plano a
    distintas escalas/encuadres — lo que más se parece a "ver más planos":

      - flips horizontal/vertical (estocásticos, encima de los baked al generar);
      - scale + crop/pad: zoom-in recorta una sub-región (muros a mayor escala),
        zoom-out agrega contexto con padding. Sesgado a zoom-in porque agranda
        las estructuras finas (muros/columnas) en vez de adelgazarlas.

    La máscara se transforma con NEAREST para no inventar clases intermedias.
    """
    import cv2

    H, W = INPUT_SIZE, INPUT_SIZE

    if rng.random() < 0.5:
        img = cv2.flip(img, 1)
        mask = cv2.flip(mask, 1)
    if rng.random() < 0.5:
        img = cv2.flip(img, 0)
        mask = cv2.flip(mask, 0)

    if rng.random() < 0.8:
        s = rng.uniform(0.9, 1.35)
        nh, nw = int(round(H * s)), int(round(W * s))
        interp = cv2.INTER_AREA if s < 1.0 else cv2.INTER_LINEAR
        img_r = cv2.resize(img, (nw, nh), interpolation=interp)
        mask_r = cv2.resize(mask, (nw, nh), interpolation=cv2.INTER_NEAREST)
        if s >= 1.0:  # zoom-in: recortar 512x512
            y0 = rng.randint(0, nh - H)
            x0 = rng.randint(0, nw - W)
            img = img_r[y0:y0 + H, x0:x0 + W]
            mask = mask_r[y0:y0 + H, x0:x0 + W]
        else:  # zoom-out: pegar en canvas con padding (blanco / fondo)
            canvas_img = np.full((H, W, 3), 255, dtype=np.uint8)
            canvas_mask = np.zeros((H, W), dtype=np.uint8)
            y0 = rng.randint(0, H - nh)
            x0 = rng.randint(0, W - nw)
            canvas_img[y0:y0 + nh, x0:x0 + nw] = img_r
            canvas_mask[y0:y0 + nh, x0:x0 + nw] = mask_r
            img, mask = canvas_img, canvas_mask

    return img, mask


def build_dataset(pairs: list[tuple[Path, Path]], augment: bool = False):
    """Crea un torch Dataset desde una lista de pares. Import lazy de torch
    para que el módulo se pueda importar sin instalar PyTorch.

    `augment=True` aplica augmentation estocástica por sample (solo train; NUNCA
    en val/holdout, o las métricas dejan de ser comparables entre versiones).
    """
    import cv2
    import torch
    from torch.utils.data import Dataset

    class SyntheticDataset(Dataset):
        def __init__(self, pairs: list[tuple[Path, Path]], augment: bool):
            self.pairs = pairs
            self.augment = augment
            # RNG propio del dataset (num_workers=0, así que un solo proceso).
            self._rng = random.Random()

        def __len__(self) -> int:
            return len(self.pairs)

        def __getitem__(self, idx: int):
            n = len(self.pairs)
            # Robustez: si un sample está corrupto/ilegible (ej: PNG truncado →
            # "libpng error: IDAT: CRC error"), NO abortamos el entrenamiento.
            # Lo salteamos y usamos el siguiente legible, logueando cuál falló.
            for attempt in range(n):
                j = (idx + attempt) % n
                img_path, mask_path = self.pairs[j]
                img = cv2.imread(str(img_path))
                mask = (
                    cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
                    if img is not None else None
                )
                if img is None or mask is None:
                    print(f"[dataset] WARN sample ilegible, salteando: {img_path}", flush=True)
                    continue

                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                if img.shape[0] != INPUT_SIZE or img.shape[1] != INPUT_SIZE:
                    img = cv2.resize(img, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_AREA)
                if mask.shape[0] != INPUT_SIZE or mask.shape[1] != INPUT_SIZE:
                    mask = cv2.resize(mask, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_NEAREST)

                if self.augment:
                    img, mask = _augment_pair(img, mask, self._rng)

                # Robustez: Mapeamos clases fuera de rango (como techos=6 si entrenamos con 6 clases del 0 al 5)
                # al fondo (0) para evitar desbordamientos en la CrossEntropyLoss.
                mask[mask >= NUM_CLASSES] = 0

                img_f = img.astype(np.float32) / 255.0
                img_f = (img_f - IMAGENET_MEAN) / IMAGENET_STD
                img_f = np.ascontiguousarray(img_f.transpose(2, 0, 1))
                return (
                    torch.from_numpy(img_f).float(),
                    torch.from_numpy(np.ascontiguousarray(mask)).long(),
                )

            raise RuntimeError("No se pudo leer ningún sample legible del dataset.")

    return SyntheticDataset(pairs, augment)


# ----------------------------------------------------------------------
# Modelo
# ----------------------------------------------------------------------
def build_unet_model(num_classes: int = NUM_CLASSES, pretrained_backbone: bool = True):
    """Construye el U-Net usado tanto para training como inference.

    Si `pretrained_backbone=True`, descarga pesos de ImageNet para el encoder
    (~85MB). Para fine-tuning desde un checkpoint propio, pasar False y
    cargar el state_dict después.
    """
    import segmentation_models_pytorch as smp

    return smp.Unet(
        encoder_name="resnet34",
        encoder_weights="imagenet" if pretrained_backbone else None,
        in_channels=3,
        classes=num_classes,
    )


# ----------------------------------------------------------------------
# Métricas
# ----------------------------------------------------------------------
def compute_iou_per_class(pred, target, num_classes: int = NUM_CLASSES) -> list[float]:
    """IoU por clase para un sample (pred y target son HxW long tensors)."""
    ious: list[float] = []
    for c in range(num_classes):
        pred_c = pred == c
        target_c = target == c
        intersection = (pred_c & target_c).sum().item()
        union = (pred_c | target_c).sum().item()
        ious.append(intersection / union if union > 0 else float("nan"))
    return ious


def evaluate_on_loader(model, loader, device: str, num_classes: int = NUM_CLASSES) -> dict:
    """Devuelve mIoU + IoU por clase sobre un DataLoader. Asume modelo en eval."""
    import torch

    per_sample_ious: list[list[float]] = []
    with torch.no_grad():
        for img, mask in loader:
            img = img.to(device)
            mask = mask.to(device)
            logits = model(img)
            pred = logits.argmax(dim=1)
            for i in range(pred.shape[0]):
                per_sample_ious.append(compute_iou_per_class(pred[i], mask[i], num_classes))

    if not per_sample_ious:
        return {"miou": 0.0, "iou_per_class": {n: 0.0 for n in CLASS_NAMES[:num_classes]}}

    arr = np.array(per_sample_ious)
    iou_per_class = np.nanmean(arr, axis=0)
    miou = float(np.nanmean(iou_per_class[1:]))  # excluye background
    return {
        "miou": miou,
        "iou_per_class": {
            CLASS_NAMES[i]: float(iou_per_class[i]) for i in range(num_classes)
        },
    }


# ----------------------------------------------------------------------
# Active model pointer
# ----------------------------------------------------------------------
@dataclass
class ActiveModelInfo:
    path: str
    version: int
    holdout_miou: float | None
    created_at: str
    notes: str | None = None
    # Arquitectura del modelo. Si falta en el JSON viejo (pre-extensión a vigas/
    # columnas), defaulteamos al set legacy de 4 clases por backwards compat.
    num_classes: int = 4
    class_names: list[str] | None = None


# Set legacy: si active.json no tiene `class_names`, asumimos este orden.
_LEGACY_CLASS_NAMES = ["background", "wall", "room", "opening"]


def read_active_model() -> ActiveModelInfo | None:
    """Lee el pointer al modelo activo. None si no existe (cae al default)."""
    if not ACTIVE_MODEL_FILE.exists():
        return None
    try:
        data = json.loads(ACTIVE_MODEL_FILE.read_text())
        class_names = data.get("class_names")
        if isinstance(class_names, list) and all(isinstance(x, str) for x in class_names):
            cn = list(class_names)
        else:
            cn = None
        return ActiveModelInfo(
            path=str(data["path"]),
            version=int(data["version"]),
            holdout_miou=data.get("holdout_miou"),
            created_at=str(data.get("created_at", "")),
            notes=data.get("notes"),
            num_classes=int(data.get("num_classes", 4)),
            class_names=cn,
        )
    except Exception:  # noqa: BLE001
        return None


def write_active_model(info: ActiveModelInfo) -> None:
    """Persiste el pointer al modelo activo."""
    ACTIVE_MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_MODEL_FILE.write_text(json.dumps({
        "path": info.path,
        "version": info.version,
        "holdout_miou": info.holdout_miou,
        "created_at": info.created_at,
        "notes": info.notes,
        "num_classes": info.num_classes,
        "class_names": info.class_names or _LEGACY_CLASS_NAMES,
    }, indent=2))


def next_version() -> int:
    """Devuelve la siguiente versión disponible (v1, v2, ...)."""
    active = read_active_model()
    return (active.version + 1) if active else 1


# ----------------------------------------------------------------------
# Holdout fijo
# ----------------------------------------------------------------------
def read_holdout() -> list[Path] | None:
    """Lee la lista de paths del holdout. None si no se inicializó todavía."""
    if not HOLDOUT_FILE.exists():
        return None
    try:
        data = json.loads(HOLDOUT_FILE.read_text())
        paths = [Path(p) for p in data.get("image_paths", [])]
        # Filtrar paths que ya no existen (samples borrados)
        return [p for p in paths if p.exists()]
    except Exception:  # noqa: BLE001
        return None


def write_holdout(image_paths: list[Path], seed: int) -> None:
    """Persiste el holdout — debe ser fijo entre versiones para comparaciones válidas."""
    HOLDOUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    HOLDOUT_FILE.write_text(json.dumps({
        "image_paths": [str(p) for p in image_paths],
        "n_samples": len(image_paths),
        "seed": seed,
        "frozen_at": dt.datetime.now(dt.UTC).isoformat(),
    }, indent=2))


def initialize_or_load_holdout(all_pairs: list[tuple[Path, Path]], frac: float = 0.1, seed: int = 42) -> tuple[list[tuple[Path, Path]], list[tuple[Path, Path]]]:
    """Devuelve (train_pairs, holdout_pairs).

    Si ya existe `holdout.json`, lo carga y separa. Si no, escoge una fracción
    aleatoria y lo congela para que todas las versiones futuras comparen
    sobre el mismo holdout.
    """
    existing = read_holdout()
    if existing is not None:
        holdout_set = set(existing)
        holdout_pairs = [p for p in all_pairs if p[0] in holdout_set]
        train_pairs = [p for p in all_pairs if p[0] not in holdout_set]
        # Validar si holdout_pairs cargó algo, si no, re-inicializar
        if holdout_pairs:
            return train_pairs, holdout_pairs

    # Primera vez: agrupar por "batch" (carpeta page_X) antes de partir.
    rng = random.Random(seed)
    groups: dict[Path, list[tuple[Path, Path]]] = {}
    for pair in all_pairs:
        batch_dir = pair[0].parent.parent  # var_NNN/.. = page_X/
        groups.setdefault(batch_dir, []).append(pair)

    # Si hay pocos grupos (páginas), hacer split por grupos causaría que clases enteras
    # queden completamente fuera del train o del holdout (ej: si hay sólo 1 o 2 páginas de vigas/columnas).
    # Para datasets pequeños (<= 30 páginas), hacemos split por variación dentro de cada página.
    if len(groups) <= 30:
        print(f"[holdout] Detectados pocos grupos ({len(groups)} páginas). Realizando split por variación para asegurar representación de todas las clases.")
        holdout_pairs = []
        train_pairs = []
        for batch_dir, pairs in groups.items():
            sorted_pairs = sorted(pairs, key=lambda p: p[0].name)
            # Mezclar usando la semilla fija
            rng.shuffle(sorted_pairs)
            n_val = max(1, int(len(sorted_pairs) * frac))
            holdout_pairs.extend(sorted_pairs[:n_val])
            train_pairs.extend(sorted_pairs[n_val:])
        
        write_holdout([p[0] for p in holdout_pairs], seed)
        return train_pairs, holdout_pairs

    # Para datasets grandes, agrupar y aislar por batch completo (evita data leakage)
    group_keys = list(groups.keys())
    rng.shuffle(group_keys)
    n_target = max(1, int(len(all_pairs) * frac))

    holdout_pairs = []
    for i, k in enumerate(group_keys):
        # Siempre dejamos al menos un grupo para entrenar.
        if i >= len(group_keys) - 1:
            break
        holdout_pairs.extend(groups[k])
        if len(holdout_pairs) >= n_target:
            break

    holdout_set = {p[0] for p in holdout_pairs}
    train_pairs = [p for p in all_pairs if p[0] not in holdout_set]
    write_holdout([p[0] for p in holdout_pairs], seed)
    return train_pairs, holdout_pairs

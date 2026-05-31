"""Genera un dataset PROCEDURAL de planos sintéticos a disco.

Inventa plantas arquitectónicas/estructurales por código (ver
`app/services/procedural_generator.py`) y las persiste con el mismo formato que
`synthetic_generator` para que `scripts._common.discover_samples` las encuentre:

    <out_dir>/batch_<ts>/var_<NNNN>/
        image.png
        mask.png
        meta.json

IMPORTANTE: el directorio de salida default (`storage/procedural`) es DISTINTO
de `storage/synthetic` (planos reales). Esto es a propósito: el procedural va
SOLO al train vía `--extra-data-dir`, nunca al holdout/val. El holdout tiene que
ser de planos reales o medirías "aprendí mi generador" en vez de generalización.

Uso:
    cd backend
    python -m scripts.gen_procedural --count 3000
    # luego:
    python -m scripts.train_model --epochs 40 --extra-data-dir storage/procedural
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generador procedural de planos.")
    parser.add_argument("--count", type=int, default=2000,
                        help="Cantidad de samples a generar (default 2000)")
    parser.add_argument("--out", default="storage/procedural",
                        help="Directorio de salida (separado de storage/synthetic)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Semilla global (default: aleatoria)")
    parser.add_argument("--batch-size", type=int, default=1000,
                        help="Samples por carpeta batch_<ts> (solo organización)")
    args = parser.parse_args()

    import cv2  # noqa: F401  # validamos que OpenCV esté disponible
    from app.services.procedural_generator import generate_sample

    base_seed = args.seed if args.seed is not None else random.randint(0, 2**31 - 1)
    master = random.Random(base_seed)

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    ts = dt.datetime.now(dt.UTC).strftime("%Y%m%d_%H%M%S")
    counts_total = {"wall": 0, "room": 0, "opening": 0, "beam": 0, "column": 0, "roof": 0}
    style_total = {"arch": 0, "struct": 0}

    written = 0
    batch_idx = 0
    batch_dir: Path | None = None
    for i in range(args.count):
        if i % args.batch_size == 0:
            batch_idx += 1
            batch_dir = out_root / f"batch_{ts}_{batch_idx:03d}"
            batch_dir.mkdir(parents=True, exist_ok=True)

        rng = random.Random(master.randint(0, 2**31 - 1))
        img_rgb, mask, meta = generate_sample(rng)

        var_dir = batch_dir / f"var_{i + 1:05d}"
        var_dir.mkdir(exist_ok=True)
        # cv2 espera BGR al escribir.
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(var_dir / "image.png"), img_bgr)
        cv2.imwrite(str(var_dir / "mask.png"), mask)
        (var_dir / "meta.json").write_text(json.dumps(meta, indent=2))

        for k, v in meta["element_counts"].items():
            counts_total[k] = counts_total.get(k, 0) + v
        style_total[meta["style"]] += 1
        written += 1
        if written % 500 == 0:
            print(f"[gen] {written}/{args.count} samples...")

    # Manifest del run (snapshot_at para que el filtro --since de finetune funcione).
    manifest = {
        "snapshot_at": dt.datetime.now(dt.UTC).isoformat(),
        "source": "procedural",
        "seed": base_seed,
        "count": written,
        "styles": style_total,
        "element_counts_total": counts_total,
    }
    (out_root / f"_manifest_{ts}.json").write_text(json.dumps(manifest, indent=2))

    print("-" * 70)
    print(f"[done] {written} samples en {out_root}")
    print(f"[done] estilos: {style_total}")
    print(f"[done] elementos totales: {counts_total}")
    print(f"[done] entrenar con:  python -m scripts.train_model "
          f"--epochs 40 --extra-data-dir {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

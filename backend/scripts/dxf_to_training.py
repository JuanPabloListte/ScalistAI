"""CLI para convertir lotes de DXF en pares (image.png, mask.png) para entrenamiento.

La lógica de renderizado vive en `app/services/dxf_training.py`; este script solo
orquesta la iteración sobre un directorio y reporta el progreso.

Uso:
    cd backend
    python -m scripts.dxf_to_training --input-dir /ruta/a/dxfs --variations 12
    # luego fine-tunear:
    python -m scripts.finetune_model --epochs 20 --extra-data-dir storage/dxf_training
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Convierte DXFs en pares image+mask para training.")
    parser.add_argument("--input-dir", required=True, help="Directorio con archivos .dxf")
    parser.add_argument("--out-dir", default="storage/dxf_training",
                        help="Directorio de salida (default: storage/dxf_training)")
    parser.add_argument("--variations", type=int, default=12,
                        help="Variaciones geométricas por archivo (default: 12)")
    args = parser.parse_args()

    from app.services.dxf_training import generate_from_dxf_path

    input_dir = Path(args.input_dir)
    out_dir = Path(args.out_dir)

    dxf_files = sorted(input_dir.glob("**/*.dxf")) + sorted(input_dir.glob("**/*.DXF"))
    if not dxf_files:
        print(f"ERROR: no se encontraron .dxf en {input_dir}")
        return 1

    print(f"[setup] {len(dxf_files)} archivos DXF en {input_dir}")
    print(f"[setup] {args.variations} variaciones por archivo → {len(dxf_files) * args.variations} samples máx.")
    print(f"[setup] salida en {out_dir}")
    print("-" * 60)

    total = 0
    for dxf_path in dxf_files:
        print(f"  procesando {dxf_path.name}...")
        stem_dir = out_dir / dxf_path.stem
        n = generate_from_dxf_path(dxf_path, stem_dir, variations=args.variations)
        print(f"    → {n} variaciones generadas")
        total += n

    print("-" * 60)
    print(f"[done] {total} samples en {out_dir}")
    print(f"[done] para entrenar:")
    print(f"       python -m scripts.finetune_model --epochs 20 --extra-data-dir {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

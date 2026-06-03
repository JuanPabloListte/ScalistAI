"""Training inicial del detector de segmentación de ScalistAI.

Lee las variaciones sintéticas de `storage/synthetic/**/var_*/` y entrena
desde scratch (con backbone ResNet34 pre-entrenado en ImageNet) un U-Net
que detecta walls/rooms/openings.

Uso:
    cd backend
    python -m scripts.train_model --epochs 30 --batch-size 8

Para GPU:
    python -m scripts.train_model --device cuda --epochs 50

Salida:
- `backend/models/scalistai_seg_v1.pt`         — checkpoint del mejor modelo según mIoU val
- `backend/models/scalistai_seg_v1.history.json` — log epoch a epoch
- `backend/models/active.json`               — pointer al modelo activo
- `backend/models/holdout.json`              — lista fija de samples reservados para evaluar futuras versiones

El holdout se congela en este script. Fine-tunings posteriores
(`finetune_model.py`) usan ese mismo holdout para comparar.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

from scripts import _common as C


def train(args) -> int:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, random_split

    if args.device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = args.device
    print(f"[setup] device={device}")

    data_root = Path(args.data_dir)
    if not data_root.exists():
        print(f"ERROR: {data_root} no existe. Generá variaciones sintéticas primero "
              f"(o activá un proyecto con `allow_training_data`).")
        return 3

    pairs = C.discover_samples(data_root)
    print(f"[setup] samples encontrados: {len(pairs)}")
    if len(pairs) < 10:
        print(f"ERROR: muy pocos samples ({len(pairs)}). Mínimo recomendado: 50.")
        return 4

    # Holdout fijo (10%) — congelado para que futuras versiones comparen acá.
    # OJO: el holdout/val se carvan SOLO de --data-dir (planos reales). Los
    # samples procedurales (--extra-data-dir) van únicamente al train.
    train_pairs, holdout_pairs = C.initialize_or_load_holdout(pairs, frac=0.1, seed=42)

    # Shuffle train_pairs using a fixed seed to ensure validation split is representative 
    # of all pages and contains all classes.
    import random
    rng = random.Random(42)
    rng.shuffle(train_pairs)

    # Del resto, 20% para validación durante training (rotativo, no congelado).
    val_size = max(1, len(train_pairs) // 5)
    train_pairs_only = train_pairs[val_size:]
    val_pairs = train_pairs[:val_size]

    # Datos procedurales: SOLO al train (nunca holdout/val). Ver gen_procedural.py.
    extra_pairs: list = []
    if args.extra_data_dir:
        extra_root = Path(args.extra_data_dir)
        extra_pairs = C.discover_samples(extra_root) if extra_root.exists() else []

    # Balance: si el procedural supera ampliamente a los reales, el modelo se
    # especializa en el sintético y NO transfiere a planos reales (val_loss se
    # dispara). Replicamos los reales para que pesen ~igual que el procedural.
    if args.balance_real and extra_pairs and train_pairs_only:
        factor = max(1, round(len(extra_pairs) / max(len(train_pairs_only), 1)))
        if factor > 1:
            train_pairs_only = train_pairs_only * factor
            print(f"[setup] balance-real: reales x{factor} → {len(train_pairs_only)}")

    if extra_pairs:
        train_pairs_only = train_pairs_only + extra_pairs
        print(f"[setup] +{len(extra_pairs)} samples procedurales desde {args.extra_data_dir} (solo train)")

    # Augmentation SOLO en train. Val/holdout deterministas para métricas
    # comparables entre versiones.
    train_ds = C.build_dataset(train_pairs_only, augment=True)
    val_ds = C.build_dataset(val_pairs, augment=False)
    holdout_ds = C.build_dataset(holdout_pairs, augment=False)

    print(
        f"[setup] train={len(train_ds)} val={len(val_ds)} holdout={len(holdout_ds)}"
    )

    # num_workers > 0: decodifica PNGs + augmentation en paralelo (sino la GPU
    # se queda esperando a la CPU y el epoch tarda muchísimo). pin_memory acelera
    # la copia host→GPU.
    nw = max(0, args.num_workers)
    pin = device == "cuda"
    train_loader = DataLoader(
        train_ds, batch_size=args.batch_size, shuffle=True,
        num_workers=nw, pin_memory=pin, persistent_workers=nw > 0,
    )
    val_loader = DataLoader(
        val_ds, batch_size=args.batch_size, shuffle=False,
        num_workers=nw, pin_memory=pin, persistent_workers=nw > 0,
    )
    holdout_loader = DataLoader(
        holdout_ds, batch_size=args.batch_size, shuffle=False,
        num_workers=nw, pin_memory=pin, persistent_workers=nw > 0,
    )

    print("[setup] creando U-Net resnet34 (init: imagenet)...")
    model = C.build_unet_model(pretrained_backbone=True).to(device)

    weights = torch.tensor(C.CLASS_WEIGHTS, device=device, dtype=torch.float32)
    criterion = nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)

    version = args.version or C.next_version()
    out_path = C.MODELS_DIR / f"scalistai_seg_v{version}.pt"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    best_iou = 0.0
    history: list[dict] = []

    print(f"[train] {args.epochs} epochs, batch_size={args.batch_size}, lr={args.lr}, out={out_path}")
    print("-" * 80)

    for epoch in range(args.epochs):
        model.train()
        train_loss_sum = 0.0
        for img, mask in train_loader:
            img = img.to(device)
            mask = mask.to(device)
            optimizer.zero_grad()
            loss = criterion(model(img), mask)
            loss.backward()
            optimizer.step()
            train_loss_sum += float(loss.detach().item())
        train_loss = train_loss_sum / max(len(train_loader), 1)

        model.eval()
        val_loss_sum = 0.0
        with torch.no_grad():
            for img, mask in val_loader:
                img = img.to(device)
                mask = mask.to(device)
                val_loss_sum += float(criterion(model(img), mask).item())
        val_loss = val_loss_sum / max(len(val_loader), 1)
        val_metrics = C.evaluate_on_loader(model, val_loader, device)

        scheduler.step()

        log = (
            f"epoch={epoch+1:>3}/{args.epochs} "
            f"train_loss={train_loss:.4f} val_loss={val_loss:.4f} "
            f"miou={val_metrics['miou']:.3f} "
            + " ".join(
                f"{n[:4]}={val_metrics['iou_per_class'][n]:.3f}"
                for n in C.CLASS_NAMES[1:]
            )
        )
        history.append({
            "epoch": epoch + 1,
            "train_loss": train_loss,
            "val_loss": val_loss,
            **val_metrics,
        })

        if val_metrics["miou"] > best_iou:
            best_iou = val_metrics["miou"]
            torch.save(model.state_dict(), out_path)
            log += "  [SAVED]"
        print(log)

    # Evaluación final sobre el holdout fijo (para que el number sea comparable
    # entre versiones).
    print("-" * 80)
    print("[eval] cargando best checkpoint y evaluando sobre holdout fijo...")
    model.load_state_dict(torch.load(out_path, map_location=device))
    model.eval()
    holdout_metrics = C.evaluate_on_loader(model, holdout_loader, device)
    print(f"[eval] holdout mIoU = {holdout_metrics['miou']:.4f}")
    for n in C.CLASS_NAMES[1:]:
        print(f"        {n:10s} = {holdout_metrics['iou_per_class'][n]:.4f}")

    # Persistir history + pointer al modelo activo.
    history_path = out_path.with_suffix(".history.json")
    history_path.write_text(json.dumps({
        "epochs": history,
        "holdout_eval": holdout_metrics,
        "version": version,
    }, indent=2))

    C.write_active_model(C.ActiveModelInfo(
        path=str(out_path),
        version=version,
        holdout_miou=holdout_metrics["miou"],
        created_at=dt.datetime.now(dt.UTC).isoformat(),
        notes=f"initial training, {len(train_ds)} train samples",
        num_classes=C.NUM_CLASSES,
        class_names=list(C.CLASS_NAMES),
    ))

    print("-" * 80)
    print(f"[done] best val mIoU = {best_iou:.4f}")
    print(f"[done] holdout mIoU  = {holdout_metrics['miou']:.4f}")
    print(f"[done] checkpoint    = {out_path}")
    print(f"[done] active.json   = {C.ACTIVE_MODEL_FILE}")
    print(f"[done] holdout.json  = {C.HOLDOUT_FILE}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Training inicial del modelo de segmentación de ScalistAI.",
    )
    parser.add_argument("--data-dir", default="storage/synthetic")
    parser.add_argument("--extra-data-dir", default=None,
                        help="Dir extra (ej: procedural) que va SOLO al train, "
                             "nunca al holdout/val. Ver scripts/gen_procedural.py")
    parser.add_argument("--balance-real", action="store_true",
                        help="Replica los samples reales hasta equiparar al "
                             "procedural, para que el modelo no los ignore.")
    parser.add_argument("--version", type=int, default=None,
                        help="Número de versión (default: siguiente disponible)")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--num-workers", type=int, default=4,
                        help="Procesos para cargar datos en paralelo (0 = serial).")
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()
    return train(args)


if __name__ == "__main__":
    sys.exit(main())

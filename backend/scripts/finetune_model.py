"""Fine-tuning incremental del detector de segmentación.

Toma el modelo activo (`backend/models/active.json`) como punto de partida,
lo re-entrena con un mix de datos nuevos + replay de datos viejos, evalúa
contra el holdout fijo, y solo lo promueve a "activo" si supera al actual.

Uso:
    cd backend
    python -m scripts.finetune_model --epochs 10

Flags útiles:
    --since 2026-05-01            sólo usar batches con snapshot_at >= esa fecha
    --replay-frac 0.5             mezcla 50% datos viejos para evitar olvido
    --lr 5e-4                     LR más bajo que training inicial (default ok)
    --force-promote               promover aunque baje la métrica (NO usar en prod)

Compara mIoU del modelo nuevo vs activo en el holdout fijo de `holdout.json`.
Si mejora → guarda como `scalistai_seg_v<N+1>.pt` y actualiza `active.json`.
Si no → mantiene el anterior y deja el nuevo en disco como referencia para
diagnóstico.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
from pathlib import Path

from scripts import _common as C


def _filter_samples_since(
    pairs: list[tuple[Path, Path]], since_iso: str | None,
) -> list[tuple[Path, Path]]:
    """Filtra pares por `_manifest.json.snapshot_at` >= since_iso.

    Cada batch sintético tiene un `_manifest.json` con snapshot_at; el filtro
    se aplica a nivel batch (carpeta padre).
    """
    if not since_iso:
        return pairs
    keep: list[tuple[Path, Path]] = []
    manifest_cache: dict[Path, bool] = {}
    for img_path, mask_path in pairs:
        batch_dir = img_path.parent.parent  # var_NNN/.. = page_X/
        if batch_dir in manifest_cache:
            if manifest_cache[batch_dir]:
                keep.append((img_path, mask_path))
            continue
        manifest = batch_dir / "_manifest.json"
        ok = False
        if manifest.exists():
            try:
                m = json.loads(manifest.read_text())
                ok = m.get("snapshot_at", "") >= since_iso
            except Exception:  # noqa: BLE001
                ok = False
        manifest_cache[batch_dir] = ok
        if ok:
            keep.append((img_path, mask_path))
    return keep


def finetune(args) -> int:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader

    if args.device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = args.device
    print(f"[setup] device={device}")

    # 1. Modelo activo de partida
    active = C.read_active_model()
    if active is None:
        print(
            "ERROR: no hay modelo activo todavía. Correr primero "
            "`python -m scripts.train_model` para el training inicial."
        )
        return 2
    print(f"[setup] activo: v{active.version} ({active.path}), holdout_miou={active.holdout_miou}")
    if not Path(active.path).exists():
        print(f"ERROR: el checkpoint activo no existe en disco: {active.path}")
        return 3

    # 2. Recolectar samples + filtrar por fecha si corresponde
    data_root = Path(args.data_dir)
    if not data_root.exists():
        print(f"ERROR: {data_root} no existe.")
        return 4
    all_pairs = C.discover_samples(data_root)
    if not all_pairs:
        print("ERROR: no se encontraron samples.")
        return 5

    # Separar holdout fijo del resto (NO entrenamos sobre el holdout).
    train_pairs, holdout_pairs = C.initialize_or_load_holdout(all_pairs, frac=0.1, seed=42)
    if not holdout_pairs:
        print("ERROR: holdout.json existe pero está vacío. Borrá el archivo y reentrenar desde cero.")
        return 6

    # Datos nuevos vs viejos
    if args.since:
        new_pairs = _filter_samples_since(train_pairs, args.since)
        old_pairs = [p for p in train_pairs if p not in set(new_pairs)]
        print(f"[setup] filtro --since={args.since}: nuevos={len(new_pairs)}, viejos={len(old_pairs)}")
    else:
        # Sin filtro: tratamos todo como "nuevo" pero igual mezclamos con replay.
        new_pairs = train_pairs
        old_pairs = train_pairs
        print(f"[setup] sin filtro --since, usando todos los samples ({len(new_pairs)})")

    # Replay: mezclar parte de datos viejos para evitar catastrophic forgetting
    rng = random.Random(42)
    if old_pairs and args.replay_frac > 0:
        n_replay = max(1, int(len(new_pairs) * args.replay_frac))
        n_replay = min(n_replay, len(old_pairs))
        replay_samples = rng.sample(old_pairs, n_replay)
        train_set = new_pairs + replay_samples
        rng.shuffle(train_set)
        print(f"[setup] mix train: {len(new_pairs)} nuevos + {len(replay_samples)} replay = {len(train_set)}")
    else:
        train_set = list(new_pairs)
        print(f"[setup] sin replay (frac=0): {len(train_set)} samples")

    # Datos procedurales: SOLO al train (nunca holdout). Ver gen_procedural.py.
    extra_pairs: list = []
    if args.extra_data_dir:
        extra_root = Path(args.extra_data_dir)
        extra_pairs = C.discover_samples(extra_root) if extra_root.exists() else []

    # Balance: evita que el procedural ahogue a los reales (ver train_model).
    if args.balance_real and extra_pairs and train_set:
        factor = max(1, round(len(extra_pairs) / max(len(train_set), 1)))
        if factor > 1:
            train_set = train_set * factor
            print(f"[setup] balance-real: reales x{factor} → {len(train_set)}")

    if extra_pairs:
        train_set = train_set + extra_pairs
        rng.shuffle(train_set)
        print(f"[setup] +{len(extra_pairs)} samples procedurales desde {args.extra_data_dir} (solo train)")

    if len(train_set) < 4:
        print(f"ERROR: muy pocos samples para fine-tune ({len(train_set)}).")
        return 7

    # 3. Datasets + loaders. Augmentation SOLO en train; el holdout queda
    #    determinista para que el mIoU sea comparable entre versiones.
    train_ds = C.build_dataset(train_set, augment=True)
    holdout_ds = C.build_dataset(holdout_pairs, augment=False)
    # num_workers > 0: carga de datos en paralelo (sino la GPU espera a la CPU).
    nw = max(0, args.num_workers)
    pin = device == "cuda"
    train_loader = DataLoader(
        train_ds, batch_size=args.batch_size, shuffle=True,
        num_workers=nw, pin_memory=pin, persistent_workers=nw > 0,
    )
    holdout_loader = DataLoader(
        holdout_ds, batch_size=args.batch_size, shuffle=False,
        num_workers=nw, pin_memory=pin, persistent_workers=nw > 0,
    )

    # 4. Cargar modelo desde checkpoint activo
    print(f"[setup] cargando checkpoint activo: {active.path}")
    model = C.build_unet_model(pretrained_backbone=False).to(device)
    state_dict = torch.load(active.path, map_location=device)
    if isinstance(state_dict, dict) and "state_dict" in state_dict:
        state_dict = state_dict["state_dict"]
    model.load_state_dict(state_dict, strict=False)

    # 5. Evaluar modelo viejo en holdout (baseline)
    model.eval()
    baseline = C.evaluate_on_loader(model, holdout_loader, device)
    print(f"[baseline] mIoU activo={baseline['miou']:.4f}")
    for n in C.CLASS_NAMES[1:]:
        print(f"           {n:10s} = {baseline['iou_per_class'][n]:.4f}")

    # 6. Fine-tune — guarda el checkpoint del BEST epoch sobre holdout, no el
    #    último. Para fine-tunes largos el modelo suele oscilar y el epoch
    #    final puede ser peor que un epoch intermedio. Mantenemos el best
    #    en memoria con state_dict y lo persistimos al cierre.
    weights = torch.tensor(C.CLASS_WEIGHTS, device=device, dtype=torch.float32)
    criterion = nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    # Cosine decay: el LR fijo hacía que el holdout oscilara fuerte epoch a
    # epoch. Decaer suaviza la convergencia y estabiliza la elección del best.
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)

    print(f"[finetune] {args.epochs} epochs, lr={args.lr}, replay_frac={args.replay_frac}")
    print("-" * 80)
    history: list[dict] = []
    best_miou = -1.0
    best_state: dict | None = None
    best_epoch = 0
    best_metrics: dict | None = None
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
        scheduler.step()

        model.eval()
        ev = C.evaluate_on_loader(model, holdout_loader, device)
        history.append({
            "epoch": epoch + 1,
            "train_loss": train_loss,
            **ev,
        })
        log_line = (
            f"epoch={epoch+1:>3}/{args.epochs} "
            f"train_loss={train_loss:.4f} holdout_miou={ev['miou']:.3f} "
            + " ".join(
                f"{n[:4]}={ev['iou_per_class'][n]:.3f}"
                for n in C.CLASS_NAMES[1:]
            )
        )
        if ev["miou"] > best_miou:
            best_miou = ev["miou"]
            best_epoch = epoch + 1
            best_metrics = ev
            # Copia profunda del state_dict (los tensores se mueven al CPU
            # para no ocupar GPU).
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            log_line += "  [BEST]"
        print(log_line)

    if best_state is None or best_metrics is None:
        print("ERROR: no se obtuvo ningún epoch evaluable.")
        return 8

    new_miou = best_metrics["miou"]
    old_miou = baseline["miou"]
    delta = new_miou - old_miou
    final_history_metrics = best_metrics

    # 7. Persistir el best checkpoint (no el final).
    new_version = active.version + 1
    new_path = C.MODELS_DIR / f"scalistai_seg_v{new_version}.pt"
    new_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_state, new_path)
    print(f"[checkpoint] guardado best (epoch {best_epoch}, mIoU {best_miou:.4f})")
    history_path = new_path.with_suffix(".history.json")
    history_path.write_text(json.dumps({
        "epochs": history,
        "baseline_holdout": baseline,
        "best_epoch": best_epoch,
        "best_holdout": best_metrics,
        "delta_miou": delta,
        "promoted": False,  # se actualiza abajo si promueve
        "version": new_version,
        "from_version": active.version,
    }, indent=2))

    # 8. Decidir si promover
    print("-" * 80)
    print(f"[compare] activo v{active.version} mIoU = {old_miou:.4f}")
    print(f"[compare] nuevo  v{new_version} mIoU = {new_miou:.4f}")
    print(f"[compare] delta            = {delta:+.4f}")

    threshold = args.promote_threshold
    if delta > threshold or args.force_promote:
        reason = "force" if args.force_promote and delta <= threshold else f"delta > {threshold}"
        C.write_active_model(C.ActiveModelInfo(
            path=str(new_path),
            version=new_version,
            holdout_miou=new_miou,
            created_at=dt.datetime.now(dt.UTC).isoformat(),
            notes=f"finetune from v{active.version}, delta={delta:+.4f}, reason={reason}",
            num_classes=C.NUM_CLASSES,
            class_names=list(C.CLASS_NAMES),
        ))
        # Re-escribir history con promoted=True
        history_data = json.loads(history_path.read_text())
        history_data["promoted"] = True
        history_path.write_text(json.dumps(history_data, indent=2))
        print(f"[promote] v{new_version} promovido a activo.")
    else:
        print(f"[skip] v{new_version} NO se promueve (delta {delta:+.4f} <= {threshold}).")
        print(f"       Checkpoint guardado igual en {new_path} para diagnóstico.")
        print(f"       Para forzar promoción: --force-promote")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fine-tune incremental del modelo de segmentación.",
    )
    parser.add_argument("--data-dir", default="storage/synthetic")
    parser.add_argument("--extra-data-dir", default=None,
                        help="Dir extra (ej: procedural) que va SOLO al train, "
                             "nunca al holdout. Ver scripts/gen_procedural.py")
    parser.add_argument("--balance-real", action="store_true",
                        help="Replica los samples reales hasta equiparar al "
                             "procedural, para que el modelo no los ignore.")
    parser.add_argument("--epochs", type=int, default=10,
                        help="Menos epochs que el initial training (10-15 típico)")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--num-workers", type=int, default=4,
                        help="Procesos para cargar datos en paralelo (0 = serial).")
    parser.add_argument("--lr", type=float, default=2e-4,
                        help="LR más bajo que el training inicial (default 2e-4)")
    parser.add_argument("--replay-frac", type=float, default=0.5,
                        help="Fracción de datos viejos a mezclar con los nuevos (anti-forgetting)")
    parser.add_argument("--since", type=str, default=None,
                        help="ISO8601: solo usa samples con snapshot_at >= esa fecha como 'nuevos'")
    parser.add_argument("--promote-threshold", type=float, default=0.005,
                        help="mIoU mínima de mejora para promover el nuevo modelo (default 0.005)")
    parser.add_argument("--force-promote", action="store_true",
                        help="Promover el nuevo modelo aunque empeore (NO usar en prod)")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()
    return finetune(args)


if __name__ == "__main__":
    sys.exit(main())

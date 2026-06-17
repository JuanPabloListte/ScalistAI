from __future__ import annotations

import json
import re
import sys
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings


def _active_model_architecture_changed() -> tuple[bool, str | None]:
    """Compara `active.json.num_classes` contra el set actual del código.

    Devuelve (changed, mensaje). Si `active.json` no existe o está corrupto
    devuelve (True, motivo) — preferimos un re-entrenamiento limpio antes que
    intentar finetune sobre un activo dudoso.
    """
    try:
        from scripts._common import ACTIVE_MODEL_FILE as active_json
    except Exception:  # noqa: BLE001
        active_json = Path("storage/models/active.json")
    if not active_json.exists():
        return True, "sin active.json — primer entrenamiento"
    try:
        from scripts._common import NUM_CLASSES as EXPECTED_CLASSES
    except Exception as exc:  # noqa: BLE001
        # Si no podemos resolver la cantidad esperada, no forzamos initial —
        # mejor intentar finetune que abortar el flujo.
        return False, f"no se pudo importar scripts._common ({exc})"
    try:
        data = json.loads(active_json.read_text())
        active_classes = int(data.get("num_classes", 4))
        if active_classes != EXPECTED_CLASSES:
            return (
                True,
                f"arquitectura cambió: active={active_classes} clases, "
                f"código={EXPECTED_CLASSES} → reentrenando desde cero",
            )
        return False, None
    except Exception as exc:  # noqa: BLE001
        return True, f"active.json ilegible ({exc})"

class TrainingManager:
    """Manages background ML training / fine-tuning subprocesses and tracks their progress."""

    def __init__(self) -> None:
        self.status = "idle"  # idle, running, success, failed
        self.mode = "train"  # train | procedural — qué corre el proceso actual
        self.current_epoch = 0
        self.total_epochs = 0
        self.progress_percent = 0
        self.train_loss: float | None = None
        self.val_loss: float | None = None
        self.holdout_miou: float | None = None
        self.logs: list[str] = []
        self.error: str | None = None
        self.started_at: str | None = None
        self.completed_at: str | None = None
        self.is_initial = False
        
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": self.status,
                "mode": self.mode,
                "current_epoch": self.current_epoch,
                "total_epochs": self.total_epochs,
                "progress_percent": self.progress_percent,
                "train_loss": self.train_loss,
                "val_loss": self.val_loss,
                "holdout_miou": self.holdout_miou,
                "error": self.error,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "is_initial": self.is_initial,
                "logs_count": len(self.logs),
            }

    def get_logs(self, limit: int = 500) -> list[str]:
        with self._lock:
            return self.logs[-limit:]

    def _reset_run_state(self, mode: str, total: int) -> None:
        """Resetea el estado para una nueva corrida (asume lock tomado)."""
        self.status = "running"
        self.mode = mode
        self.current_epoch = 0
        self.total_epochs = total
        self.progress_percent = 0
        self.train_loss = None
        self.val_loss = None
        self.holdout_miou = None
        self.logs = []
        self.error = None
        self.started_at = datetime.now().isoformat()
        self.completed_at = None

    def _procedural_data_arg(self) -> list[str]:
        """DESACTIVADO TEMPORALMENTE — siempre devuelve [].

        v5 mostró que el procedural actual (rectángulos limpios + labels) está
        muy lejos de la distribución de planos reales (CAD con cotas, hatching,
        texto denso). El modelo overfitteaba al procedural y no transfería:
        `train_loss` bajaba a 0.02 mientras `val/holdout mIoU` se quedaba en
        ~0.00 — modelo inservible.

        Para reactivar, dos caminos:
          a) Sumarle ruido CAD al procedural (líneas de cota, hatching, texto
             aleatorio) para que la distribución se acerque a los reales.
          b) Usarlo como pre-train y después fine-tunear SOLO con reales.

        Mientras no esté arreglado, entrenamos solo con planos reales (440+).
        """
        return []

    def start_training(self, epochs: int = 10) -> dict[str, Any]:
        with self._lock:
            if self.status == "running":
                return {"success": False, "message": "Ya hay un proceso en ejecución."}

            self._reset_run_state("train", epochs)

            # Si la arquitectura del modelo activo difiere del set de clases
            # actual (ej: pasamos de 6 a 7 canales al sumar losas), no se puede
            # finetune — hay que entrenar desde cero.
            arch_changed, arch_reason = _active_model_architecture_changed()
            self.is_initial = arch_changed
            if arch_reason:
                self.logs.append(f"[runner] {arch_reason}")

            script = "scripts.train_model" if self.is_initial else "scripts.finetune_model"
            cmd = [sys.executable, "-m", script, "--epochs", str(epochs)]
            # Sumar el dataset procedural al train (si existe). Nunca al holdout.
            extra = self._procedural_data_arg()
            if extra:
                # --balance-real: replica los reales para que el procedural no
                # los ahogue (sino el modelo no transfiere a planos reales).
                cmd += extra + ["--balance-real"]
                self.logs.append(f"[runner] incluyendo procedural: {extra[1]} (con balance-real)")
            else:
                self.logs.append("[runner] sin dataset procedural (solo planos reales)")

            self._thread = threading.Thread(
                target=self._run, args=(cmd, True), daemon=True,
            )
            self._thread.start()

            return {
                "success": True,
                "message": "Entrenamiento iniciado en background.",
                "is_initial": self.is_initial,
            }

    def start_procedural(self, count: int = 3000) -> dict[str, Any]:
        """Genera el dataset procedural en background (scripts.gen_procedural).
        Reusa el mismo streaming de logs/progreso que el entrenamiento."""
        with self._lock:
            if self.status == "running":
                return {"success": False, "message": "Ya hay un proceso en ejecución."}

            self._reset_run_state("procedural", count)
            self.is_initial = False
            cmd = [sys.executable, "-m", "scripts.gen_procedural", "--count", str(count)]
            self._thread = threading.Thread(
                target=self._run, args=(cmd, False), daemon=True,
            )
            self._thread.start()
            return {
                "success": True,
                "message": f"Generación de {count} samples procedurales iniciada.",
            }

    def _run(self, cmd: list[str], reload_on_success: bool) -> None:
        # NO force-promote en training: dejamos que el threshold de mejora del
        # script decida (antes se forzaba y promovía modelos peores).

        with self._lock:
            self.logs.append(f"[runner] Iniciando comando: {' '.join(cmd)}")

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # line buffered
                cwd="/app"  # container app folder
            )
            
            epoch_pattern = re.compile(r"epoch=\s*(\d+)/(\d+)")
            gen_pattern = re.compile(r"\[gen\]\s*(\d+)/(\d+)")
            train_loss_pattern = re.compile(r"train_loss=([0-9.-]+)")
            val_loss_pattern = re.compile(r"val_loss=([0-9.-]+)")
            miou_pattern = re.compile(r"miou=([0-9.-]+)|holdout_miou=([0-9.-]+)")

            # Read stdout line by line
            for line in self._process.stdout:
                line_str = line.strip()
                if not line_str:
                    continue

                with self._lock:
                    self.logs.append(line_str)
                    if len(self.logs) > 2000:
                        self.logs.pop(0)

                    # Parse epoch (training) o progreso de generación procedural.
                    epoch_match = epoch_pattern.search(line_str)
                    gen_match = gen_pattern.search(line_str)
                    if epoch_match:
                        self.current_epoch = int(epoch_match.group(1))
                        self.total_epochs = int(epoch_match.group(2))
                        if self.total_epochs > 0:
                            self.progress_percent = int((self.current_epoch / self.total_epochs) * 100)
                    elif gen_match:
                        self.current_epoch = int(gen_match.group(1))
                        self.total_epochs = int(gen_match.group(2))
                        if self.total_epochs > 0:
                            self.progress_percent = int((self.current_epoch / self.total_epochs) * 100)

                    # Parse train loss
                    loss_match = train_loss_pattern.search(line_str)
                    if loss_match:
                        self.train_loss = float(loss_match.group(1))
                        
                    # Parse val loss
                    val_loss_match = val_loss_pattern.search(line_str)
                    if val_loss_match:
                        self.val_loss = float(val_loss_match.group(1))
                        
                    # Parse mIoU
                    miou_match = miou_pattern.search(line_str)
                    if miou_match:
                        val = miou_match.group(1) or miou_match.group(2)
                        if val:
                            self.holdout_miou = float(val)
                            
            self._process.wait()
            ret_code = self._process.returncode
            
            with self._lock:
                if ret_code == 0:
                    self.status = "success"
                    self.progress_percent = 100
                    self.logs.append("[runner] Proceso completado con éxito.")

                    # Solo el training recarga el modelo activo; la generación
                    # de datos no toca el modelo.
                    if reload_on_success:
                        try:
                            from app.services.ml_detector import get_ml_detector
                            get_ml_detector().reload()
                            self.logs.append("[runner] Instancia de MLDetector recargada correctamente.")
                        except Exception as e:
                            self.logs.append(f"[runner] Advertencia al recargar MLDetector: {str(e)}")
                else:
                    self.status = "failed"
                    self.error = f"El proceso falló con código {ret_code}"
                    self.logs.append(f"[runner] ERROR: El proceso falló con código {ret_code}")
                    
        except Exception as e:
            with self._lock:
                self.status = "failed"
                self.error = str(e)
                self.logs.append(f"[runner] EXCEPCIÓN: {str(e)}")
        finally:
            with self._lock:
                self.completed_at = datetime.now().isoformat()
                self._process = None


_manager: TrainingManager | None = None
_manager_lock = threading.Lock()

def get_training_manager() -> TrainingManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = TrainingManager()
    return _manager

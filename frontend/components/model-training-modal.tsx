"use client";

import { useEffect, useRef, useState } from "react";
import { api, type MlModelStatus, type TrainingStatusResponse, type TrainingStats } from "@/lib/api";

type Props = {
  onClose: () => void;
};

export function ModelTrainingModal({ onClose }: Props) {
  const [stats, setStats] = useState<TrainingStats | null>(null);
  const [mlStatus, setMlStatus] = useState<MlModelStatus | null>(null);
  const [trainingState, setTrainingState] = useState<TrainingStatusResponse["status"] | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [epochs, setEpochs] = useState<number>(10);
  const [proceduralCount, setProceduralCount] = useState<number>(3000);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [regenSummary, setRegenSummary] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const logsEndRef = useRef<HTMLDivElement>(null);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  async function loadInitialData() {
    setIsRefreshing(true);
    setError(null);
    try {
      const [s, m, t] = await Promise.all([
        api.getTrainingStats(),
        api.getMlStatus(),
        api.getTrainingStatus(),
      ]);
      setStats(s);
      setMlStatus(m);
      setTrainingState(t.status);
      setLogs(t.logs);
    } catch (err) {
      console.error(err);
      setError("No se pudieron cargar los datos del modelo.");
    } finally {
      setIsRefreshing(false);
    }
  }

  // Poll status while running
  async function pollStatus() {
    try {
      const t = await api.getTrainingStatus();
      setTrainingState(t.status);
      setLogs(t.logs);
      
      // If it finished, reload ML status to reflect new model info
      if (t.status.status !== "running") {
        const m = await api.getMlStatus();
        setMlStatus(m);
        if (pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
      }
    } catch (err) {
      console.error("Error polling training status:", err);
    }
  }

  useEffect(() => {
    loadInitialData();
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, []);

  // Set up or tear down polling based on running state
  useEffect(() => {
    if (trainingState?.status === "running") {
      if (!pollingRef.current) {
        pollingRef.current = setInterval(pollStatus, 2000);
      }
    } else {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    }
  }, [trainingState?.status]);

  // Scroll logs window to bottom
  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  async function handleStartTraining() {
    if (epochs < 1 || epochs > 100) {
      setError("La cantidad de epochs debe ser entre 1 y 100.");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const res = await api.triggerTraining(epochs);
      if (res.success) {
        // Trigger immediate poll
        pollStatus();
      } else {
        setError(res.message || "Error al iniciar el entrenamiento.");
      }
    } catch (err: any) {
      setError(err?.message || "Error de red al iniciar el entrenamiento.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleRegenerateSynthetic() {
    setIsRegenerating(true);
    setError(null);
    setRegenSummary(null);
    try {
      const res = await api.regenerateAllSynthetic();
      if (res.message) {
        // Caso: no hay proyectos con consentimiento
        setError(res.message);
      } else {
        setRegenSummary(
          `${res.variations_generated} variaciones generadas en ${res.pages_processed} páginas de ${res.plans_processed} planos.`,
        );
        // Refresh stats para que el contador de muestras quede al día.
        await loadInitialData();
      }
    } catch (err: any) {
      setError(err?.message || "Error regenerando dataset sintético.");
    } finally {
      setIsRegenerating(false);
    }
  }

  async function handleGenerateProcedural() {
    if (proceduralCount < 100 || proceduralCount > 50000) {
      setError("La cantidad de samples procedurales debe ser entre 100 y 50000.");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const res = await api.generateProcedural(proceduralCount);
      if (res.success) {
        pollStatus();
      } else {
        setError(res.message || "Error al iniciar la generación procedural.");
      }
    } catch (err: any) {
      setError(err?.message || "Error de red al iniciar la generación procedural.");
    } finally {
      setIsSubmitting(false);
    }
  }

  const isRunning = trainingState?.status === "running";
  const isGenerating = isRunning && trainingState?.mode === "procedural";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-4xl flex-col rounded-2xl bg-white shadow-2xl dark:border dark:border-slate-800 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <header className="flex items-center justify-between border-b border-slate-100 px-6 py-4 dark:border-slate-800">
          <div>
            <h3 className="text-xl font-bold text-slate-800 dark:text-slate-100">
              Entrenamiento y Calibración de Modelo
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Administración y control del pipeline de segmentación ML (U-Net ResNet34)
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          >
            <svg
              className="h-5 w-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </header>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-600 dark:border-red-900/30 dark:bg-red-950/20 dark:text-red-400">
              {error}
            </div>
          )}

          {/* Top Panel - Stats and Info */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {/* Model Status Card */}
            <div className="rounded-xl border border-slate-100 bg-slate-50/50 p-4 dark:border-slate-800 dark:bg-slate-800/40">
              <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">
                Modelo ML Activo
              </h4>
              <div className="space-y-2 text-xs">
                <div className="flex justify-between">
                  <span className="text-slate-500">Estado en memoria:</span>
                  <span className={`font-semibold ${mlStatus?.model_loaded ? "text-emerald-600 dark:text-emerald-400" : "text-amber-500"}`}>
                    {mlStatus?.model_loaded ? "Cargado" : "No cargado (Lazy)"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Versión activa:</span>
                  <span className="font-semibold text-slate-800 dark:text-slate-200">
                    {mlStatus?.active_version ? `v${mlStatus.active_version}` : "Ninguna (Fallback clásica)"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Holdout mIoU:</span>
                  <span className="font-semibold text-slate-800 dark:text-slate-200">
                    {mlStatus?.active_holdout_miou ? `${(mlStatus.active_holdout_miou * 100).toFixed(2)}%` : "N/A"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Dispositivo (Device):</span>
                  <span className="font-mono text-slate-600 dark:text-slate-400">
                    {mlStatus?.device || "auto"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Archivo:</span>
                  <span className="truncate max-w-[200px] font-mono text-slate-500" title={mlStatus?.model_path}>
                    {mlStatus?.model_path?.split("/").pop() || "Ninguno"}
                  </span>
                </div>
              </div>
            </div>

            {/* Dataset/Samples Card */}
            <div className="rounded-xl border border-slate-100 bg-slate-50/50 p-4 dark:border-slate-800 dark:bg-slate-800/40">
              <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">
                Corpus de Datos Sintéticos
              </h4>
              <div className="space-y-2 text-xs">
                <div className="flex justify-between">
                  <span className="text-slate-500">Muestras acumuladas:</span>
                  <span className="font-bold text-slate-800 dark:text-slate-200">
                    {stats?.total_samples || 0}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Batches generados:</span>
                  <span className="font-semibold text-slate-800 dark:text-slate-200">
                    {stats?.total_batches || 0}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Planos aportantes:</span>
                  <span className="font-semibold text-slate-800 dark:text-slate-200">
                    {stats?.plans_contributing || 0}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Recomendado para reentrenar:</span>
                  <span className="text-slate-600 dark:text-slate-400">
                    {stats?.recommended_min_samples || 200} muestras
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Estado de preparación:</span>
                  <span className={`font-semibold ${stats?.ready_to_train ? "text-emerald-600" : "text-slate-500"}`}>
                    {stats?.ready_to_train ? "Listo para entrenar" : "Pocas muestras"}
                  </span>
                </div>
              </div>

              {/* Acción: regenerar dataset desde elementos confirmados */}
              <div className="mt-3 border-t border-slate-200 pt-3 dark:border-slate-700">
                <button
                  type="button"
                  onClick={handleRegenerateSynthetic}
                  disabled={isRegenerating || trainingState?.status === "running"}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                  title="Vuelve a generar variaciones sintéticas a partir de los elementos confirmados en todos tus proyectos. Útil si confirmaste vigas/columnas/aberturas después de la última activación."
                >
                  {isRegenerating ? "Regenerando..." : "Regenerar dataset sintético"}
                </button>
                {regenSummary && (
                  <p className="mt-2 text-xs text-emerald-600 dark:text-emerald-400">
                    {regenSummary}
                  </p>
                )}
                <p className="mt-1.5 text-[10px] leading-snug text-slate-500 dark:text-slate-400">
                  Recorre tus proyectos con consentimiento de training y regenera variaciones de cada página con elementos confirmados. Tardá ~5s por página.
                </p>
              </div>
            </div>
          </div>

          {/* Generación de datos procedurales */}
          <div className="rounded-xl border border-slate-200 p-5 dark:border-slate-800">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <h4 className="text-base font-bold text-slate-800 dark:text-slate-200">
                  Datos Procedurales
                </h4>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Genera planos sintéticos por código (volumen + balance de clases).
                  Se usan SOLO para entrenar, nunca para el holdout.
                </p>
              </div>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5">
                  <label htmlFor="proc-input" className="text-xs text-slate-600 dark:text-slate-400">
                    Samples:
                  </label>
                  <input
                    id="proc-input"
                    type="number"
                    min={100}
                    max={50000}
                    step={500}
                    value={proceduralCount}
                    onChange={(e) => setProceduralCount(parseInt(e.target.value) || 3000)}
                    disabled={isRunning || isSubmitting}
                    className="w-24 rounded border border-slate-300 px-2 py-1.5 text-center text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 disabled:opacity-50"
                  />
                </div>
                <button
                  type="button"
                  onClick={handleGenerateProcedural}
                  disabled={isRunning || isSubmitting}
                  className="rounded-lg border border-brand px-4 py-1.5 text-sm font-semibold text-brand hover:bg-brand/10 transition disabled:opacity-50 dark:border-sky-500 dark:text-sky-400 dark:hover:bg-sky-500/10"
                >
                  {isGenerating ? "Generando..." : "Generar procedurales"}
                </button>
              </div>
            </div>
          </div>

          {/* Interactive Controls & Metrics (if running or has finished) */}
          <div className="rounded-xl border border-slate-200 p-5 dark:border-slate-800 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <h4 className="text-base font-bold text-slate-800 dark:text-slate-200">
                  Acción de Re-entrenamiento
                </h4>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Entrena el modelo (incluye los datos procedurales si existen).
                  Si cambió el set de clases, entrena desde cero automáticamente.
                </p>
              </div>

              {/* Epochs count input & trigger button */}
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5">
                  <label htmlFor="epochs-input" className="text-xs text-slate-600 dark:text-slate-400">
                    Epochs:
                  </label>
                  <input
                    id="epochs-input"
                    type="number"
                    min={1}
                    max={100}
                    value={epochs}
                    onChange={(e) => setEpochs(parseInt(e.target.value) || 10)}
                    disabled={isRunning || isSubmitting}
                    className="w-16 rounded border border-slate-300 px-2 py-1.5 text-center text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 disabled:opacity-50"
                  />
                </div>
                <button
                  type="button"
                  onClick={handleStartTraining}
                  disabled={isRunning || isSubmitting}
                  className="rounded-lg bg-brand px-4 py-1.5 text-sm font-semibold text-white hover:bg-brand-dark transition disabled:opacity-50 dark:bg-sky-500 dark:text-slate-950 dark:hover:bg-sky-400"
                >
                  {isSubmitting ? "Iniciando..." : isRunning ? "Entrenando..." : "Reentrenar ahora"}
                </button>
              </div>
            </div>

            {/* Run Progress and Metrics */}
            {(isRunning || trainingState?.status !== "idle") && trainingState && (
              <div className="pt-4 border-t border-slate-100 dark:border-slate-800 space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-slate-500 uppercase">Estado actual:</span>
                    <span
                      className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                        trainingState.status === "running"
                          ? "bg-sky-50 text-sky-600 dark:bg-sky-950/30 dark:text-sky-400"
                          : trainingState.status === "success"
                          ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-950/30 dark:text-emerald-400"
                          : "bg-red-50 text-red-600 dark:bg-red-950/30 dark:text-red-400"
                      }`}
                    >
                      {trainingState.status === "running"
                        ? "En progreso"
                        : trainingState.status === "success"
                        ? "Completado con éxito"
                        : "Error en el entrenamiento"}
                    </span>
                  </div>

                  <div className="flex gap-4 text-xs font-mono">
                    {trainingState.current_epoch > 0 && (
                      <div>
                        {trainingState.mode === "procedural" ? "Muestras" : "Epoch"}: <span className="font-semibold text-slate-800 dark:text-slate-200">{trainingState.current_epoch}/{trainingState.total_epochs}</span>
                      </div>
                    )}
                    {trainingState.train_loss !== null && (
                      <div>
                        Loss: <span className="font-semibold text-slate-800 dark:text-slate-200">{trainingState.train_loss.toFixed(4)}</span>
                      </div>
                    )}
                    {trainingState.holdout_miou !== null && (
                      <div>
                        Holdout mIoU: <span className="font-semibold text-slate-800 dark:text-slate-200">{(trainingState.holdout_miou * 100).toFixed(2)}%</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Progress Bar */}
                <div className="w-full bg-slate-100 dark:bg-slate-800 h-2.5 rounded-full overflow-hidden">
                  <div
                    className={`h-full transition-all duration-500 ${
                      trainingState.status === "success"
                        ? "bg-emerald-500"
                        : trainingState.status === "failed"
                        ? "bg-red-500"
                        : "bg-brand dark:bg-sky-500 animate-pulse"
                    }`}
                    style={{ width: `${trainingState.progress_percent}%` }}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Console logs */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
                Consola de Logs
              </h4>
              <button
                type="button"
                onClick={loadInitialData}
                disabled={isRefreshing}
                className="text-xs text-brand hover:underline dark:text-sky-400 disabled:opacity-50"
              >
                {isRefreshing ? "Actualizando..." : "Actualizar logs"}
              </button>
            </div>
            <div className="relative rounded-xl border border-slate-800 bg-slate-950 p-4 font-mono text-xs text-slate-300 shadow-inner">
              <div className="h-64 overflow-y-auto space-y-1 scrollbar-thin scrollbar-thumb-slate-800 scrollbar-track-slate-950">
                {logs.length === 0 ? (
                  <div className="text-slate-500 italic">No hay logs registrados todavía. Presiona "Reentrenar ahora" para iniciar.</div>
                ) : (
                  logs.map((log, i) => (
                    <div key={i} className="whitespace-pre-wrap leading-relaxed">
                      <span className="text-slate-600 mr-2 select-none">{String(i + 1).padStart(3, "0")}</span>
                      {log}
                    </div>
                  ))
                )}
                <div ref={logsEndRef} />
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <footer className="border-t border-slate-100 px-6 py-4 flex justify-between items-center bg-slate-50 dark:border-slate-800 dark:bg-slate-900/50">
          <div className="text-xs text-slate-500 dark:text-slate-400 max-w-md">
            Nota: El re-entrenamiento puede tardar unos minutos en CPU. El modelo entrenado se activará automáticamente como el detector por defecto.
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Cerrar panel
          </button>
        </footer>
      </div>
    </div>
  );
}

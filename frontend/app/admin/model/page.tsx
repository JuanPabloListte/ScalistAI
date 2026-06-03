"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type MlModelStatus, type TrainingStatusResponse, type TrainingStats, type User } from "@/lib/api";

export default function AdminModelPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [userLoading, setUserLoading] = useState(true);

  const [stats, setStats] = useState<TrainingStats | null>(null);
  const [mlStatus, setMlStatus] = useState<MlModelStatus | null>(null);
  const [trainingState, setTrainingState] = useState<TrainingStatusResponse["status"] | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [epochs, setEpochs] = useState<number>(10);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [regenSummary, setRegenSummary] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const logsEndRef = useRef<HTMLDivElement>(null);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  // Authenticate user is admin
  useEffect(() => {
    api.getMe()
      .then((u) => {
        setUser(u);
        setUserLoading(false);
        // Once authenticated as admin, load training metrics
        if (u.role === "admin" || u.email === "admin@gmail.com") {
          loadData();
        }
      })
      .catch((err) => {
        console.error("Error fetching user profile:", err);
        router.push("/login");
      });

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, []);

  async function loadData() {
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

  // Handle active polling setup based on running state
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
        // Caso "sin proyectos con consentimiento": no es error, sólo info.
        setRegenSummary(res.message);
      } else {
        setRegenSummary(
          `${res.variations_generated} variaciones generadas en ${res.pages_processed} páginas de ${res.plans_processed} planos.`,
        );
        // Refrescar contadores de muestras + estado.
        await loadData();
      }
    } catch (err: any) {
      setError(err?.message || "Error regenerando dataset sintético.");
    } finally {
      setIsRegenerating(false);
    }
  }

  if (userLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-300 border-t-brand-500 dark:border-slate-700 dark:border-t-brand-400" />
          Verificando credenciales…
        </div>
      </div>
    );
  }

  const isAdmin = user?.role === "admin" || user?.email === "admin@gmail.com";
  if (!isAdmin) {
    return (
      <main className="mx-auto max-w-md px-6 py-20 text-center">
        <h1 className="mb-2 text-xl font-semibold text-red-600 dark:text-red-400">Acceso denegado</h1>
        <p className="mb-6 text-sm text-slate-600 dark:text-slate-400">
          No tenés permisos para acceder a esta sección de administración.
        </p>
        <button
          onClick={() => router.push("/projects")}
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-700 dark:bg-brand-500 dark:hover:bg-brand-400"
        >
          Volver a proyectos
        </button>
      </main>
    );
  }

  const isRunning = trainingState?.status === "running";

  return (
    <main className="mx-auto max-w-5xl px-6 py-10 space-y-6">
      {/* Header */}
      <header className="flex flex-col gap-4 border-b border-slate-200 pb-5 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">
            Modelo y Calibración
          </h1>
          <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
            Administración del modelo de segmentación ML (U-Net ResNet34) y del corpus de entrenamiento.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={loadData}
            disabled={isRefreshing || isRunning}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {isRefreshing ? "Actualizando…" : "Actualizar"}
          </button>
        </div>
      </header>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-600 dark:border-red-900/30 dark:bg-red-950/20 dark:text-red-400">
          {error}
        </div>
      )}

      {/* Grid: Active Model & Corpus stats */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        {/* Model Status Card */}
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-base font-bold text-slate-800 dark:text-slate-200 mb-4">
            Modelo ML Activo
          </h2>
          <div className="space-y-3 text-sm">
            <div className="flex justify-between border-b border-slate-50 pb-2 dark:border-slate-800/50">
              <span className="text-slate-500">Estado de carga:</span>
              <span className={`font-semibold ${mlStatus?.model_loaded ? "text-emerald-600 dark:text-emerald-400" : "text-amber-500"}`}>
                {mlStatus?.model_loaded ? "Cargado" : "No cargado (Lazy)"}
              </span>
            </div>
            <div className="flex justify-between border-b border-slate-50 pb-2 dark:border-slate-800/50">
              <span className="text-slate-500">Versión activa:</span>
              <span className="font-semibold text-slate-800 dark:text-slate-200">
                {mlStatus?.active_version ? `v${mlStatus.active_version}` : "Ninguna (Clásica fallback)"}
              </span>
            </div>
            <div className="flex justify-between border-b border-slate-50 pb-2 dark:border-slate-800/50">
              <span className="text-slate-500">Holdout mIoU (Precisión):</span>
              <span className="font-semibold text-slate-800 dark:text-slate-200">
                {mlStatus?.active_holdout_miou ? `${(mlStatus.active_holdout_miou * 100).toFixed(2)}%` : "N/A"}
              </span>
            </div>
            <div className="flex justify-between border-b border-slate-50 pb-2 dark:border-slate-800/50">
              <span className="text-slate-500">Dispositivo (Device):</span>
              <span className="font-mono text-xs text-slate-600 dark:text-slate-400">
                {mlStatus?.device || "auto"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Checkpoint:</span>
              <span className="truncate max-w-[220px] font-mono text-xs text-slate-500" title={mlStatus?.model_path}>
                {mlStatus?.model_path?.split("/").pop() || "Ninguno"}
              </span>
            </div>
          </div>
        </div>

        {/* Dataset/Samples Card */}
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-base font-bold text-slate-800 dark:text-slate-200 mb-4">
            Corpus de Datos Sintéticos
          </h2>
          <div className="space-y-3 text-sm">
            <div className="flex justify-between border-b border-slate-50 pb-2 dark:border-slate-800/50">
              <span className="text-slate-500">Muestras (Samples):</span>
              <span className="font-bold text-slate-800 dark:text-slate-200">
                {stats?.total_samples || 0}
              </span>
            </div>
            <div className="flex justify-between border-b border-slate-50 pb-2 dark:border-slate-800/50">
              <span className="text-slate-500">Batches generados:</span>
              <span className="font-semibold text-slate-800 dark:text-slate-200">
                {stats?.total_batches || 0}
              </span>
            </div>
            <div className="flex justify-between border-b border-slate-50 pb-2 dark:border-slate-800/50">
              <span className="text-slate-500">Planos contribuyentes:</span>
              <span className="font-semibold text-slate-800 dark:text-slate-200">
                {stats?.plans_contributing || 0}
              </span>
            </div>
            <div className="flex justify-between border-b border-slate-50 pb-2 dark:border-slate-800/50">
              <span className="text-slate-500">Mínimo sugerido:</span>
              <span className="text-slate-600 dark:text-slate-400">
                {stats?.recommended_min_samples || 200} muestras
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Entrenamiento disponible:</span>
              <span className={`font-semibold ${stats?.ready_to_train ? "text-emerald-600 dark:text-emerald-400" : "text-amber-500"}`}>
                {stats?.ready_to_train ? "Listo" : "Pocos datos"}
              </span>
            </div>

            {/* Acción: regenerar dataset desde elementos confirmados */}
            <div className="mt-4 border-t border-slate-100 pt-4 dark:border-slate-800">
              <button
                type="button"
                onClick={handleRegenerateSynthetic}
                disabled={isRegenerating || isRunning}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                title="Recorre tus proyectos con consentimiento de training y vuelve a generar variaciones sintéticas a partir de los elementos confirmados. Útil después de pintar elementos nuevos en el editor."
              >
                {isRegenerating ? "Regenerando..." : "Regenerar dataset sintético"}
              </button>
              {regenSummary && (
                <p className="mt-2 text-xs text-emerald-600 dark:text-emerald-400">
                  {regenSummary}
                </p>
              )}
              <p className="mt-1.5 text-[10px] leading-snug text-slate-500 dark:text-slate-400">
                Procesa todas las páginas con elementos entrenables. Tarda ~5s por página.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Retraining panel */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900 space-y-4">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-slate-800 dark:text-slate-200">
              Control de Entrenamiento
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              {mlStatus?.active_version
                ? "Ajusta incrementalmente el modelo activo para aprender de las últimas correcciones manuales."
                : "Entrena el modelo inicial v1 con todo el corpus de datos sintéticos."}
            </p>
          </div>

          {/* Controls */}
          <div className="flex items-center gap-3 self-start md:self-auto">
            <div className="flex items-center gap-1.5">
              <label htmlFor="epochs-page-input" className="text-xs text-slate-600 dark:text-slate-400">
                Epochs:
              </label>
              <input
                id="epochs-page-input"
                type="number"
                min={1}
                max={100}
                value={epochs}
                onChange={(e) => setEpochs(parseInt(e.target.value) || 10)}
                disabled={isRunning || isSubmitting}
                className="w-16 rounded-md border border-slate-300 px-2 py-1.5 text-center text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 disabled:opacity-50"
              />
            </div>
            <button
              type="button"
              onClick={handleStartTraining}
              disabled={isRunning || isSubmitting}
              className="rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark transition disabled:opacity-50 dark:bg-sky-500 dark:text-slate-950 dark:hover:bg-sky-400"
            >
              {isSubmitting ? "Iniciando..." : isRunning ? "Entrenando..." : "Reentrenar ahora"}
            </button>
          </div>
        </div>

        {/* Progress & Metrics */}
        {(isRunning || (trainingState && trainingState.status !== "idle")) && trainingState && (
          <div className="pt-4 border-t border-slate-100 dark:border-slate-800 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-slate-500 uppercase">Estado:</span>
                <span
                  className={`text-xs font-bold px-2.5 py-0.5 rounded-full ${
                    trainingState.status === "running"
                      ? "bg-sky-50 text-sky-600 dark:bg-sky-950/30 dark:text-sky-400"
                      : trainingState.status === "success"
                      ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-950/30 dark:text-emerald-400"
                      : "bg-red-50 text-red-600 dark:bg-red-950/30 dark:text-red-400"
                  }`}
                >
                  {trainingState.status === "running"
                    ? "Ejecutando"
                    : trainingState.status === "success"
                    ? "Completado"
                    : "Fallido"}
                </span>
              </div>

              <div className="flex gap-4 text-xs font-mono">
                {trainingState.current_epoch > 0 && (
                  <div>
                    Epoch: <span className="font-semibold text-slate-800 dark:text-slate-200">{trainingState.current_epoch}/{trainingState.total_epochs}</span>
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
            <div className="w-full bg-slate-100 dark:bg-slate-850 h-3 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all duration-500 ${
                  trainingState.status === "success"
                    ? "bg-emerald-500 animate-none"
                    : trainingState.status === "failed"
                    ? "bg-red-500 animate-none"
                    : "bg-brand dark:bg-sky-500 animate-pulse"
                }`}
                style={{ width: `${trainingState.progress_percent}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Terminal logs */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-slate-800 dark:text-slate-200">
            Consola del Script
          </h2>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => navigator.clipboard.writeText(logs.join('\n'))}
              className="flex items-center gap-1 text-xs font-semibold text-slate-500 transition hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
              title="Copiar logs al portapapeles"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
              Copiar
            </button>
            <button
              type="button"
              onClick={loadData}
              disabled={isRefreshing}
              className="text-xs font-semibold text-brand hover:underline dark:text-sky-400 disabled:opacity-50"
            >
              {isRefreshing ? "Actualizando..." : "Actualizar logs"}
            </button>
          </div>
        </div>
        <div className="relative rounded-xl border border-slate-300 bg-slate-950 p-4 font-mono text-xs text-slate-300 dark:border-slate-700">
          <div className="h-96 overflow-y-auto space-y-1 scrollbar-thin scrollbar-thumb-slate-800 scrollbar-track-slate-950">
            {logs.length === 0 ? (
              <div className="text-slate-500 italic">No hay logs registrados. Presiona "Reentrenar ahora" para iniciar el pipeline.</div>
            ) : (
              logs.map((log, i) => (
                <div key={i} className="whitespace-pre-wrap leading-relaxed">
                  <span className="text-slate-700 mr-3 select-none">{String(i + 1).padStart(3, "0")}</span>
                  {log}
                </div>
              ))
            )}
            <div ref={logsEndRef} />
          </div>
        </div>
      </div>
    </main>
  );
}

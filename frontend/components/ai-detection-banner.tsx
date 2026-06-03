"use client";

import { useEffect, useState } from "react";

import { api, type AiStage, type AiStatus } from "@/lib/api";

const STAGE_LABELS: { key: keyof Omit<AiStatus, "started_at">; label: string }[] = [
  { key: "scales", label: "Escalas" },
  { key: "walls", label: "Muros" },
  { key: "rooms", label: "Recintos" },
  { key: "openings", label: "Aberturas" },
  { key: "columns", label: "Columnas" },
  { key: "beams", label: "Vigas" },
  { key: "roofs", label: "Techos" },
  { key: "ml", label: "ML" },
];

const POLL_INTERVAL_MS = 3000;
// Si todo arranca en pending sin start_at, asumimos que no corrio pipeline
// para este plan (ej: subido antes del feature). Ocultamos el banner.
function isPipelineIdle(s: AiStatus): boolean {
  return (
    s.started_at === null &&
    s.scales === "pending" &&
    s.walls === "pending" &&
    s.rooms === "pending" &&
    s.openings === "pending" &&
    s.columns === "pending" &&
    s.beams === "pending" &&
    s.roofs === "pending" &&
    s.ml === "pending"
  );
}

function isAllDone(s: AiStatus): boolean {
  return STAGE_LABELS.every((stage) => {
    const v = s[stage.key];
    return v === "done" || v === "failed";
  });
}

export function AiDetectionBanner({
  planId,
  onAllDone,
}: {
  planId: number;
  onAllDone?: () => void;
}) {
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function tick() {
      try {
        const s = await api.getAiStatus(planId);
        if (cancelled) return;
        setStatus(s);
        if (isAllDone(s)) {
          onAllDone?.();
          return; // dejar de polear
        }
        timer = setTimeout(tick, POLL_INTERVAL_MS);
      } catch {
        if (!cancelled) timer = setTimeout(tick, POLL_INTERVAL_MS * 2);
      }
    }
    tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [planId, onAllDone]);

  if (!status || dismissed || isPipelineIdle(status) || isAllDone(status)) {
    return null;
  }

  return (
    <div className="mb-4 flex items-start gap-3 rounded-lg border border-sky-200 bg-sky-50/70 px-4 py-3 dark:border-sky-900/60 dark:bg-sky-950/30">
      <div className="mt-0.5 h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-sky-500 border-t-transparent dark:border-sky-400 dark:border-t-transparent" />
      <div className="flex-1 text-sm">
        <p className="font-semibold text-sky-900 dark:text-sky-200">
          La IA está procesando tu plano
        </p>
        <p className="mt-0.5 text-xs text-sky-800/80 dark:text-sky-300/80">
          Detección automática en background. Vas a ver los candidatos en cuanto terminen.
        </p>
        <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {STAGE_LABELS.map(({ key, label }) => (
            <li key={key} className="flex items-center gap-1">
              <StageIcon stage={status[key]} />
              <span className="text-sky-800 dark:text-sky-300">{label}</span>
            </li>
          ))}
        </ul>
      </div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="Ocultar"
        className="rounded p-1 text-sky-700 transition hover:bg-sky-100 hover:text-sky-900 dark:text-sky-300 dark:hover:bg-sky-900/50 dark:hover:text-sky-100"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 6 6 18" />
          <path d="m6 6 12 12" />
        </svg>
      </button>
    </div>
  );
}

function StageIcon({ stage }: { stage: AiStage }) {
  if (stage === "done") return <span className="text-emerald-600 dark:text-emerald-400">✓</span>;
  if (stage === "failed") return <span className="text-red-600 dark:text-red-400">✗</span>;
  if (stage === "running") return <span className="text-sky-500">●</span>;
  return <span className="text-slate-400">○</span>;
}

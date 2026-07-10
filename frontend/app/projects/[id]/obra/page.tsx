"use client";

/**
 * Obra · Avance físico (Etapa 2 del módulo Seguimiento de Construcción).
 *
 * El diferencial: acá NO se estima un "%": el capataz registra CANTIDADES
 * ("hoy 45 m²") y el % se deriva del cómputo exacto del plano. Mobile-first:
 * registrar un avance son 10 segundos desde el teléfono en la obra.
 */

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, type WorkProgress, type TaskProgress, type ProgressEntryRow } from "@/lib/api";
import { CostosTab } from "@/components/obra/costos-tab";

function fmtARS(n: number): string {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(Math.round(n));
}
function fmtDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("es-AR", { day: "2-digit", month: "short" });
}

const STATUS_STYLE: Record<string, string> = {
  "completa": "bg-green-500/15 text-green-600 dark:text-green-400",
  "en curso": "bg-sky-500/15 text-sky-600 dark:text-sky-400",
  "atrasada": "bg-red-500/15 text-red-600 dark:text-red-400",
  "debería estar en curso": "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  "pendiente": "bg-slate-500/10 text-slate-500",
};

// Solo lectura: el registro de avance se hace desde el Cronograma (doble clic
// en la tarea → pestaña "Avance"), para tener un único lugar de edición.
function TaskRow({ t, projectId }: { t: TaskProgress; projectId: number }) {
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<ProgressEntryRow[] | null>(null);

  async function toggleHistory() {
    if (history === null) setHistory(await api.listProgress(t.task_id));
    else setHistory(null);
  }

  return (
    <div className="border-b border-slate-100 py-3 last:border-0 dark:border-slate-800/60">
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-center gap-3 text-left">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate font-semibold text-slate-800 dark:text-slate-200">{t.name}</span>
            <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${STATUS_STYLE[t.status] || ""}`}>
              {t.status}
            </span>
            {t.delay_days > 0 && (
              <span className="shrink-0 rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] font-semibold text-red-600 dark:text-red-400">
                +{t.delay_days}d
              </span>
            )}
          </div>
          <div className="mt-1.5 flex items-center gap-3">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <div className={`h-full rounded-full ${t.pct >= 100 ? "bg-green-500" : "bg-brand-500"}`}
                   style={{ width: `${Math.min(100, t.pct)}%` }} />
            </div>
            <span className="w-32 shrink-0 text-right text-xs tabular-nums text-slate-500">
              {t.qty_done.toLocaleString("es-AR")} / {t.qty_planned.toLocaleString("es-AR")} {t.unit} · {t.pct}%
            </span>
          </div>
        </div>
      </button>

      {open && (
        <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800/40">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-4 text-[11px] text-slate-500">
              <span>Plan: {fmtDate(t.planned_start)} → {fmtDate(t.planned_end)}</span>
              <span>Fin proyectado: <strong className={t.delay_days > 0 ? "text-red-500" : "text-green-600 dark:text-green-400"}>{fmtDate(t.projected_end)}</strong></span>
              {t.real_yield != null && <span>Rinde real: {t.real_yield} {t.unit}/día</span>}
            </div>
            <button onClick={toggleHistory}
                    className="rounded-lg border border-slate-300 px-3 py-2.5 text-xs text-slate-500 dark:border-slate-600 dark:text-slate-400">
              {history ? "Ocultar" : "Historial"}
            </button>
          </div>
          {history && (
            <div className="mt-3 space-y-1">
              {history.length === 0 && <p className="text-xs text-slate-400">Sin registros todavía.</p>}
              {history.map((h) => (
                <div key={h.id} className="flex items-center gap-3 rounded-lg bg-white px-3 py-1.5 text-xs dark:bg-slate-900">
                  <span className="font-medium text-slate-600 dark:text-slate-300">{fmtDate(h.date)}</span>
                  <span className="font-semibold text-slate-800 dark:text-slate-100">{h.qty_done} {t.unit}</span>
                  <span className="min-w-0 flex-1 truncate text-slate-400">{h.note}</span>
                </div>
              ))}
            </div>
          )}
          <Link href={`/projects/${projectId}/gantt`}
                className="mt-3 inline-block text-xs font-semibold text-brand-600 hover:text-brand-500 dark:text-brand-400">
            Registrar avance en el Cronograma →
          </Link>
        </div>
      )}
    </div>
  );
}

export default function ObraPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = Number(params.id);

  const [progress, setProgress] = useState<WorkProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"fisico" | "costos">("fisico");

  const load = useCallback(() => {
    api.getWorkProgress(projectId)
      .then(setProgress)
      .catch((e) => setError(String((e as Error)?.message ?? e)))
      .finally(() => setLoading(false));
  }, [projectId]);
  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="p-10 text-center text-slate-500">Cargando avance de obra…</div>;

  if (!progress) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-16 text-center">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Seguimiento de obra</h1>
        <p className="mt-3 text-slate-500">{error?.includes("baseline")
          ? "Todavía no hay un plan de obra congelado."
          : error || "Sin datos."}</p>
        <Link href={`/projects/${projectId}/gantt`}
              className="mt-6 inline-block rounded-lg bg-brand-600 px-6 py-3 font-semibold text-white hover:bg-brand-500">
          Ir al cronograma para congelar el baseline →
        </Link>
      </main>
    );
  }

  const T = progress.totals;
  const byStage = new Map<string, TaskProgress[]>();
  for (const t of progress.tasks) {
    const key = `${t.stage_order}·${t.stage}`;
    byStage.set(key, [...(byStage.get(key) || []), t]);
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-8 sm:px-6">
      <header className="mb-6">
        <button onClick={() => router.back()} className="text-sm font-medium text-slate-500 hover:text-brand-600">← Volver</button>
        <div className="mt-2 flex flex-wrap items-baseline justify-between gap-2">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white sm:text-3xl">Seguimiento de obra</h1>
          <span className="text-xs text-slate-500">Plan v{progress.version} · al {fmtDate(progress.as_of)}</span>
        </div>
        <div className="mt-4 flex gap-1 border-b border-slate-200 dark:border-slate-800">
          {([["fisico", "Avance físico"], ["costos", "Costos"]] as const).map(([k, label]) => (
            <button key={k} onClick={() => setTab(k)}
              className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition ${
                tab === k
                  ? "border-brand-600 text-brand-600 dark:text-brand-400"
                  : "border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
              }`}>
              {label}
            </button>
          ))}
        </div>
      </header>

      {tab === "costos" ? (
        <CostosTab projectId={projectId} progress={progress} />
      ) : (
      <>

      {/* KPIs */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div className="text-xs text-slate-500">Avance físico</div>
          <div className="text-2xl font-bold text-brand-600 dark:text-brand-400">{T.pct_fisico}%</div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
            <div className="h-full bg-brand-500" style={{ width: `${Math.min(100, T.pct_fisico)}%` }} />
          </div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div className="text-xs text-slate-500">Valor ganado</div>
          <div className="text-lg font-bold text-slate-900 dark:text-white">${fmtARS(T.ev)}</div>
          <div className="text-[11px] text-slate-400">de ${fmtARS(T.bac)}</div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div className="text-xs text-slate-500">Fin proyectado</div>
          <div className={`text-lg font-bold ${T.delay_days > 0 ? "text-red-600 dark:text-red-400" : "text-green-600 dark:text-green-400"}`}>
            {fmtDate(T.projected_end)}
          </div>
          <div className="text-[11px] text-slate-400">plan: {fmtDate(T.planned_end)}</div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div className="text-xs text-slate-500">Desvío de plazo</div>
          <div className={`text-2xl font-bold ${T.delay_days > 0 ? "text-red-600 dark:text-red-400" : "text-green-600 dark:text-green-400"}`}>
            {T.delay_days > 0 ? `+${T.delay_days}d` : "En fecha"}
          </div>
          {T.spi != null && <div className="text-[11px] text-slate-400">SPI {T.spi}</div>}
        </div>
      </div>

      {/* Tareas por etapa */}
      {[...byStage.entries()].map(([key, tasks]) => {
        const stage = progress.stages.find((s) => `${s.stage_order}·${s.stage}` === key);
        return (
          <section key={key} className="mb-5 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-1 flex items-center justify-between">
              <h2 className="font-bold text-slate-900 dark:text-white">{tasks[0].stage}</h2>
              <span className="text-xs font-semibold text-slate-500">{stage?.pct ?? 0}%</span>
            </div>
            {tasks.map((t) => <TaskRow key={t.task_id} t={t} projectId={projectId} />)}
          </section>
        );
      })}

      <p className="mt-4 text-center text-[11px] leading-relaxed text-slate-400">
        El % se deriva de las cantidades registradas contra el cómputo exacto del plano —
        acá no se estima a ojo. El fin proyectado usa el rendimiento real observado de cada tarea.
        Esta vista es de solo lectura: para registrar avance, editá la tarea en el{" "}
        <Link href={`/projects/${projectId}/gantt`} className="font-semibold text-brand-600 hover:text-brand-500 dark:text-brand-400">
          Cronograma
        </Link>{" "}(doble clic → pestaña Avance).
      </p>
      </>
      )}
    </main>
  );
}

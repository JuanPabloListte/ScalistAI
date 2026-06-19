"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, type Project, type ScheduleResponse, type CashflowPoint } from "@/lib/api";

const STAGE_COLORS: Record<string, string> = {
  "Fundación": "#0ea5e9",
  "Estructura": "#8b5cf6",
  "Mampostería": "#f59e0b",
  "Instalaciones": "#10b981",
  "Terminaciones": "#ef4444",
};
const fallbackColor = "#64748b";

function fmtARS(n: number): string {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(Math.round(n));
}
function fmtDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("es-AR", { day: "2-digit", month: "short", year: "2-digit" });
}

export default function ProjectGanttPage() {
  const params = useParams<{ id: string }>();
  const projectId = Number(params.id);

  const [project, setProject] = useState<Project | null>(null);
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);
  const [cashflow, setCashflow] = useState<CashflowPoint[]>([]);
  const [loading, setLoading] = useState(true);

  const [startDate, setStartDate] = useState<string>(new Date().toISOString().slice(0, 10));
  const [crews, setCrews] = useState<number>(1);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.getProject(projectId),
      api.getSchedule(projectId, { startDate, crews }),
      api.getCashflow(projectId, { startDate, crews }),
    ])
      .then(([proj, sched, cf]) => {
        setProject(proj);
        setSchedule(sched);
        setCashflow(cf);
      })
      .finally(() => setLoading(false));
  }, [projectId, startDate, crews]);

  useEffect(() => { load(); }, [load]);

  const totalDays = schedule?.total_days || 1;
  const projStart = schedule ? new Date(schedule.start_date + "T00:00:00").getTime() : 0;

  const barStyle = (taskStart: string, days: number) => {
    const s = new Date(taskStart + "T00:00:00").getTime();
    const offsetDays = (s - projStart) / 86400000;
    return {
      left: `${(offsetDays / totalDays) * 100}%`,
      width: `${Math.max(1.5, (days / totalDays) * 100)}%`,
    };
  };

  const maxMonthly = useMemo(
    () => Math.max(1, ...cashflow.map((c) => c.amount)),
    [cashflow],
  );

  if (loading) return <div className="p-10 text-center text-slate-500">Cargando cronograma…</div>;
  if (!project) return <div className="p-10 text-center">Proyecto no encontrado</div>;

  const tasks = schedule?.tasks || [];
  const hasData = tasks.length > 0;

  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <header className="mb-6">
        <Link href={`/projects/${project.id}`} className="inline-flex items-center gap-1 text-sm font-medium text-slate-500 transition hover:text-brand-600 dark:text-slate-400">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6" /></svg>
          Volver al proyecto
        </Link>
        <h1 className="mt-2 text-3xl font-bold text-slate-900 dark:text-white">Cronograma de obra</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Calculado de los cómputos y el rendimiento (rendimiento diario) de cada sistema constructivo.
        </p>
      </header>

      {/* Controles */}
      <div className="mb-6 flex flex-wrap items-end gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <label className="flex flex-col text-xs font-medium text-slate-600 dark:text-slate-400">
          Inicio de obra
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
            className="mt-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800" />
        </label>
        <label className="flex flex-col text-xs font-medium text-slate-600 dark:text-slate-400">
          Cuadrillas (paralelo)
          <input type="number" min={1} max={10} value={crews} onChange={(e) => setCrews(Math.max(1, Number(e.target.value)))}
            className="mt-1 w-28 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800" />
        </label>
        {schedule && (
          <div className="ml-auto flex gap-6 text-right">
            <div>
              <div className="text-xs text-slate-500">Duración</div>
              <div className="text-lg font-bold text-slate-900 dark:text-white">{schedule.total_days} días</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Fin estimado</div>
              <div className="text-lg font-bold text-slate-900 dark:text-white">{fmtDate(schedule.end_date)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Costo total</div>
              <div className="text-lg font-bold text-brand-600 dark:text-brand-400">${fmtARS(schedule.total_cost)}</div>
            </div>
          </div>
        )}
      </div>

      {!hasData ? (
        <div className="rounded-xl border border-dashed border-slate-300 p-10 text-center dark:border-slate-700">
          <p className="text-slate-500 dark:text-slate-400">No hay sistemas constructivos asignados a los elementos de este proyecto.</p>
          <Link href={`/projects/${project.id}`} className="mt-4 inline-block font-semibold text-brand-600 dark:text-brand-400">Ir a asignar sistemas →</Link>
        </div>
      ) : (
        <>
          {/* Gantt */}
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="min-w-[760px]">
              {tasks.map((t) => {
                const color = STAGE_COLORS[t.stage] || fallbackColor;
                return (
                  <div key={t.assembly} className="flex items-center gap-4 border-b border-slate-100 py-3 last:border-0 dark:border-slate-800/60">
                    <div className="w-64 shrink-0">
                      <div className="font-semibold text-slate-800 dark:text-slate-200">{t.assembly}</div>
                      <div className="flex items-center gap-1.5 text-xs text-slate-500">
                        <span className="inline-block h-2 w-2 rounded-full" style={{ background: color }} />
                        {t.stage} · {t.quantity.toLocaleString("es-AR")} {t.unit} · {t.duration_days}d
                      </div>
                    </div>
                    <div className="relative h-7 flex-1 rounded bg-slate-100 dark:bg-slate-800">
                      <div className="absolute flex h-full items-center justify-end rounded-md px-2 text-[10px] font-semibold text-white shadow-sm"
                        style={{ ...barStyle(t.start_date, t.duration_days), background: color }}
                        title={`${fmtDate(t.start_date)} → ${fmtDate(t.end_date)} · $${fmtARS(t.cost)}`}>
                        ${fmtARS(t.cost)}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Curva de inversión */}
          <div className="mt-8 rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <h2 className="mb-1 text-lg font-bold text-slate-900 dark:text-white">Curva de inversión</h2>
            <p className="mb-5 text-sm text-slate-500 dark:text-slate-400">Cuánto se invierte por mes y el acumulado a lo largo de la obra.</p>
            <div className="flex items-end gap-3" style={{ height: 220 }}>
              {cashflow.map((c) => {
                const accPct = (c.accumulated / (schedule?.total_cost || 1)) * 100;
                return (
                  <div key={c.month} className="flex flex-1 flex-col items-center gap-2">
                    <div className="relative flex w-full flex-1 items-end">
                      <div className="w-full rounded-t-md bg-brand-500/80 transition-all hover:bg-brand-500"
                        style={{ height: `${(c.amount / maxMonthly) * 100}%` }}
                        title={`${c.month}: $${fmtARS(c.amount)} (acum. $${fmtARS(c.accumulated)})`} />
                    </div>
                    <div className="text-[10px] font-medium text-slate-500">{c.month.slice(2)}</div>
                    <div className="text-[10px] text-slate-400">{accPct.toFixed(0)}%</div>
                  </div>
                );
              })}
            </div>
            <div className="mt-4 flex justify-between border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-800">
              <span>Inicio: {fmtDate(schedule!.start_date)}</span>
              <span>Inversión total: <strong className="text-brand-600 dark:text-brand-400">${fmtARS(schedule!.total_cost)}</strong></span>
            </div>
          </div>
        </>
      )}
    </main>
  );
}

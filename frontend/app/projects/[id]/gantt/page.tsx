"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, type Project, type ScheduleResponse, type CashflowPoint, type WorkPlanData, type WorkPlanVersion } from "@/lib/api";

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
  const router = useRouter();
  const projectId = Number(params.id);

  const [project, setProject] = useState<Project | null>(null);
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);
  const [plan, setPlan] = useState<WorkPlanData | null>(null);
  const [versions, setVersions] = useState<WorkPlanVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [startDate, setStartDate] = useState<string>(new Date().toISOString().slice(0, 10));
  const [crews, setCrews] = useState<number>(1);

  const load = useCallback(() => {
    setLoading(true);
    // Regla de verdad única: si el proyecto tiene un plan de obra persistido
    // (borrador o baseline), manda el plan; el cálculo al vuelo es simulación.
    Promise.all([api.getProject(projectId), api.getWorkPlan(projectId)])
      .then(async ([proj, wpState]) => {
        setProject(proj);
        setVersions(wpState.versions);
        if (wpState.plan) {
          setPlan(wpState.plan);
          setSchedule(wpState.plan);
        } else {
          setPlan(null);
          setSchedule(await api.getSchedule(projectId, { startDate, crews }));
        }
      })
      .catch((e) => setError(String((e as Error)?.message ?? e)))
      .finally(() => setLoading(false));
  }, [projectId, startDate, crews]);

  useEffect(() => { load(); }, [load]);

  async function act(fn: () => Promise<WorkPlanData>) {
    setActing(true);
    setError(null);
    try {
      const p = await fn();
      setPlan(p);
      setSchedule(p);
      const st = await api.getWorkPlan(projectId);
      setVersions(st.versions);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setActing(false);
    }
  }

  // Curva de inversión: distribuye el costo de cada tarea en sus días y agrega
  // por mes (misma lógica que el backend, pero sin una segunda llamada).
  const cashflow = useMemo<CashflowPoint[]>(() => {
    if (!schedule) return [];
    const monthly = new Map<string, number>();
    for (const t of schedule.tasks) {
      const start = new Date(t.start_date + "T00:00:00");
      const perDay = t.cost / Math.max(1, t.duration_days);
      for (let i = 0; i < t.duration_days; i++) {
        const d = new Date(start.getTime() + i * 86400000);
        const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
        monthly.set(key, (monthly.get(key) || 0) + perDay);
      }
    }
    let acc = 0;
    return [...monthly.keys()].sort().map((month) => {
      acc += monthly.get(month)!;
      return { month, amount: monthly.get(month)!, accumulated: acc };
    });
  }, [schedule]);

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
        <button onClick={() => router.back()} className="inline-flex items-center gap-1 text-sm font-medium text-slate-500 transition hover:text-brand-600 dark:text-slate-400">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6" /></svg>
          Volver
        </button>
        <h1 className="mt-2 text-3xl font-bold text-slate-900 dark:text-white">Cronograma de obra</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Generado de los cómputos del plano y el rendimiento diario de cada sistema constructivo.
        </p>
      </header>

      {/* Estado del plan de obra: simulación → borrador → baseline congelado */}
      <div className={`mb-4 flex flex-wrap items-center gap-3 rounded-xl border p-4 ${
        plan?.status === "active"
          ? "border-green-300 bg-green-50 dark:border-green-500/30 dark:bg-green-500/10"
          : plan?.status === "draft"
            ? "border-amber-300 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10"
            : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
      }`}>
        {plan ? (
          <>
            <span className={`rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wide ${
              plan.status === "active"
                ? "bg-green-600 text-white"
                : "bg-amber-500 text-white"
            }`}>
              {plan.status === "active" ? `Plan activo · v${plan.version}` : `Borrador · v${plan.version}`}
            </span>
            <span className="text-sm text-slate-600 dark:text-slate-300">
              {plan.status === "active"
                ? `Baseline congelado el ${plan.frozen_at ? fmtDate(plan.frozen_at.slice(0, 10)) : "—"} — inmutable; para cambiarlo, reprogramá una versión nueva.`
                : "Revisá tareas y fechas; al congelar se convierte en el baseline contra el que se mide la obra."}
            </span>
            <div className="ml-auto flex gap-2">
              {plan.status === "draft" && (
                <>
                  <button onClick={() => act(() => api.createWorkPlanDraft(projectId, { startDate, crews }))} disabled={acting}
                    className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-slate-400 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300">
                    Regenerar borrador
                  </button>
                  <button onClick={() => act(() => api.freezeWorkPlan(plan.plan_id))} disabled={acting}
                    className="rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-green-500 disabled:opacity-50">
                    {acting ? "…" : "Congelar baseline"}
                  </button>
                </>
              )}
              {plan.status === "active" && (
                <button onClick={() => act(() => api.rebaselineWorkPlan(projectId))} disabled={acting}
                  className="rounded-lg border border-green-600 px-4 py-2 text-sm font-semibold text-green-700 transition hover:bg-green-100 disabled:opacity-50 dark:text-green-400 dark:hover:bg-green-500/10">
                  {acting ? "…" : "Reprogramar (nueva versión)"}
                </button>
              )}
            </div>
          </>
        ) : (
          <>
            <span className="rounded-full bg-slate-500 px-3 py-1 text-xs font-bold uppercase tracking-wide text-white">Simulación</span>
            <span className="text-sm text-slate-600 dark:text-slate-300">
              Cronograma calculado al vuelo. Generá el plan de obra para congelar un baseline y empezar el seguimiento.
            </span>
            <button onClick={() => act(() => api.createWorkPlanDraft(projectId, { startDate, crews }))} disabled={acting}
              className="ml-auto rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-500 disabled:opacity-50">
              {acting ? "Generando…" : "Generar plan de obra"}
            </button>
          </>
        )}
        {versions.length > 1 && (
          <div className="w-full text-xs text-slate-500 dark:text-slate-400">
            Historial: {versions.map((v) => `v${v.version} (${v.status === "active" ? "activo" : v.status === "draft" ? "borrador" : "reemplazado"})`).join(" · ")}
          </div>
        )}
        {error && <div className="w-full text-sm text-red-600 dark:text-red-400">{error}</div>}
      </div>

      {/* Controles (aplican a la simulación o al regenerar el borrador) */}
      <div className="mb-6 flex flex-wrap items-end gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        {plan?.status !== "active" && (
          <>
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
          </>
        )}
        {plan?.status === "active" && (
          <div className="text-xs text-slate-500 dark:text-slate-400">
            Inicio: <strong>{fmtDate(plan.start_date)}</strong> · Cuadrillas: <strong>{plan.crews}</strong>
          </div>
        )}
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

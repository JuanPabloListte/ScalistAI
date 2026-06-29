"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, type ProjectBudgetSummary } from "@/lib/api";

function fmtARS(n: number): string {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(Math.round(n));
}

export default function PresupuestoPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = Number(params.id);

  const [data, setData] = useState<ProjectBudgetSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);

  async function download(planId: number, name: string) {
    setDownloading(true);
    try {
      const sim = await api.runSimulation(planId, name);
      await api.downloadSimulationXlsx(sim.id);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setDownloading(false);
    }
  }

  useEffect(() => {
    api.listPlans(projectId)
      .then((plans) => {
        const ready = plans.find((p) => p.status === "ready") ?? plans[0];
        if (!ready) throw new Error("Este proyecto no tiene un plano listo.");
        return api.getBudgetSummary(ready.id);
      })
      .then(setData)
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setLoading(false));
  }, [projectId]);

  if (loading) return <div className="p-8 text-slate-500">Calculando presupuesto…</div>;
  if (error) return <div className="p-8 text-red-600">{error}</div>;
  if (!data) return null;

  const maxPct = Math.max(...data.categories.map((c) => c.pct), 1);

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-center justify-between gap-3">
        <button onClick={() => router.push(`/projects/${projectId}`)}
                className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Volver al proyecto
        </button>
        <button
          onClick={() => void download(data.plan_id, data.project_name)}
          disabled={downloading}
          className="flex items-center gap-1.5 rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-dark disabled:opacity-50"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          {downloading ? "Generando…" : "Descargar Excel"}
        </button>
      </div>

      {/* HERO */}
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-900 to-slate-800 p-6 text-white shadow-sm dark:border-slate-700">
        <p className="text-sm text-slate-300">{data.project_name}</p>
        <div className="mt-1 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-400">Costo de construcción (directo)</p>
            <p className="text-4xl font-bold">${fmtARS(data.direct_cost)}</p>
            <p className="mt-1 text-sm text-slate-300">
              {data.cost_per_m2 ? <>${fmtARS(data.cost_per_m2)} /m² · </> : null}
              {fmtARS(data.area_m2)} m² cubiertos
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs uppercase tracking-wide text-slate-400">Precio de venta (c/ IVA)</p>
            <p className="text-2xl font-semibold text-emerald-400">${fmtARS(data.sale_price)}</p>
            <p className="mt-1 text-xs text-slate-400">
              {fmtARS(data.labor_hours)} h·hombre · {fmtARS(data.duration_days)} días estimados
            </p>
          </div>
        </div>
      </div>

      {/* RESUMEN DE CÓMPUTO (takeoff) */}
      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Resumen de cómputo</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <Stat label="Muros" value={`${fmtARS(data.takeoff.wall_ml)} ml`} sub={`${fmtARS(data.takeoff.wall_m2)} m²`} />
          <Stat label="Aberturas" value={`${data.takeoff.openings}`} sub={`${data.takeoff.doors} puertas · ${data.takeoff.windows} ventanas`} />
          <Stat label="Ambientes" value={`${data.takeoff.rooms}`} sub={`${fmtARS(data.takeoff.floor_m2)} m² de piso`} />
          <Stat label="Cubierta" value={`${fmtARS(data.takeoff.roof_m2)} m²`} />
          <Stat label="Columnas" value={`${data.takeoff.columns}`} />
          <Stat label="Vigas" value={`${fmtARS(data.takeoff.beams_ml)} ml`} />
          <Stat label="Cloaca" value={`${fmtARS(data.takeoff.cloaca_ml)} ml`} />
          <Stat label="Eléctrico" value={`${fmtARS(data.takeoff.electricidad_ml)} ml`} />
        </div>
      </section>

      {/* DESGLOSE POR RUBRO */}
      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="border-b border-slate-100 px-5 py-3 dark:border-slate-800">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Desglose por rubro</h2>
        </div>
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-slate-400">
            <tr>
              <th className="px-5 py-2 font-medium">Rubro</th>
              <th className="px-3 py-2 text-right font-medium">Total</th>
              <th className="px-3 py-2 text-right font-medium">$/m²</th>
              <th className="px-5 py-2 text-right font-medium">%</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {data.categories.map((c, i) => (
              <tr key={c.name} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                <td className="px-5 py-2.5">
                  <span className="text-slate-400">{i + 1}.</span>{" "}
                  <span className="text-slate-800 dark:text-slate-100">{c.name}</span>
                </td>
                <td className="px-3 py-2.5 text-right font-medium text-slate-900 dark:text-white">
                  ${fmtARS(c.total)}
                </td>
                <td className="px-3 py-2.5 text-right text-slate-500">
                  {c.per_m2 ? `$${fmtARS(c.per_m2)}` : "—"}
                </td>
                <td className="px-5 py-2.5">
                  <div className="flex items-center justify-end gap-2">
                    <div className="hidden h-1.5 w-20 overflow-hidden rounded-full bg-slate-100 sm:block dark:bg-slate-800">
                      <div className="h-full rounded-full bg-brand" style={{ width: `${(c.pct / maxPct) * 100}%` }} />
                    </div>
                    <span className="w-12 text-right tabular-nums text-slate-500">{c.pct.toFixed(1)}%</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot className="border-t border-slate-200 dark:border-slate-700">
            <tr className="font-semibold text-slate-900 dark:text-white">
              <td className="px-5 py-3">Costo directo</td>
              <td className="px-3 py-3 text-right">${fmtARS(data.direct_cost)}</td>
              <td className="px-3 py-3 text-right">{data.cost_per_m2 ? `$${fmtARS(data.cost_per_m2)}` : "—"}</td>
              <td className="px-5 py-3 text-right">100%</td>
            </tr>
          </tfoot>
        </table>
      </section>

      <p className="text-center text-xs text-slate-400">
        Materiales ${fmtARS(data.materials_total)} · Mano de obra ${fmtARS(data.labor_total)} ·
        cómputo automático sobre el plano del proyecto
      </p>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-1 text-xl font-bold text-slate-900 dark:text-white">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

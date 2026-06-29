"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  api,
  type CostSettings,
  type ForecastResult,
  type Project,
  type SimulationResult,
} from "@/lib/api";

function fmtARS(n: number): string {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(Math.round(n));
}

// Espeja el `build_price` del backend (costo directo → precio de venta). Es solo
// para mostrar en pantalla; el XLSX descargable usa la versión autoritativa.
function buildSale(direct: number, s: CostSettings) {
  const overhead = direct * s.overhead_pct;
  const subtotal = direct + overhead;
  const profit = subtotal * s.profit_pct;
  const net = subtotal + profit;
  const iva = net * s.iva_pct;
  return { overhead, profit, net, iva, total: net + iva };
}

export default function CostosPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = Number(params.id);

  const [project, setProject] = useState<Project | null>(null);
  const [planId, setPlanId] = useState<number | null>(null);
  const [sim, setSim] = useState<SimulationResult | null>(null);
  const [forecast, setForecast] = useState<ForecastResult | null>(null);
  const [settings, setSettings] = useState<CostSettings | null>(null);
  const [horizon, setHorizon] = useState(6);
  const [loading, setLoading] = useState(true);
  const [computing, setComputing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.getProject(projectId), api.listPlans(projectId), api.getCostSettings()])
      .then(([proj, plans, cs]) => {
        setProject(proj);
        setSettings(cs);
        const ready = plans.find((p) => p.status === "ready") ?? plans[0] ?? null;
        setPlanId(ready ? ready.id : null);
      })
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setLoading(false));
  }, [projectId]);

  const compute = useCallback(async () => {
    if (!planId) return;
    setComputing(true);
    setError(null);
    try {
      const s = await api.runSimulation(planId, project?.name);
      setSim(s);
      setForecast(await api.forecastCost(s.id, horizon));
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setComputing(false);
    }
  }, [planId, project?.name, horizon]);

  // Auto-calcula al cargar el plano.
  useEffect(() => {
    if (planId) void compute();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planId]);

  // Re-proyecta cuando cambia el horizonte (sin recomputar la simulación).
  useEffect(() => {
    if (sim) api.forecastCost(sim.id, horizon).then(setForecast).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [horizon]);

  async function saveSettings(patch: Partial<CostSettings>) {
    try {
      setSettings(await api.updateCostSettings(patch));
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    }
  }

  async function download() {
    if (!sim) return;
    try {
      await api.downloadSimulationXlsx(sim.id);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    }
  }

  const direct = sim ? sim.totals.materials + sim.totals.labor_cost : 0;
  const sale = sim && settings ? buildSale(direct, settings) : null;

  if (loading) {
    return <div className="p-8 text-slate-500">Cargando…</div>;
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <button
            onClick={() => router.push(`/projects/${projectId}`)}
            className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
          >
            ← Volver al proyecto
          </button>
          <h1 className="mt-1 text-2xl font-bold text-slate-900 dark:text-white">
            Presupuesto Inteligente
          </h1>
          <p className="text-sm text-slate-500">{project?.name}</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => router.push(`/projects/${projectId}/presupuesto`)}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            Presupuesto completo
          </button>
          <button
            onClick={() => void compute()}
            disabled={!planId || computing}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {computing ? "Calculando…" : "Recalcular"}
          </button>
          <button
            onClick={() => void download()}
            disabled={!sim}
            className="rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
          >
            Descargar Excel
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
          {error}
        </div>
      )}
      {!planId && !loading && (
        <div className="rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
          Este proyecto no tiene un plano listo para presupuestar.
        </div>
      )}

      {sale && sim && (
        <div className="grid gap-6 md:grid-cols-2">
          {/* Desglose a precio de venta */}
          <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Del costo al precio de venta
            </h2>
            <dl className="space-y-1.5 text-sm">
              <Row label="Materiales" value={sim.totals.materials} />
              <Row label="Mano de obra" value={sim.totals.labor_cost} />
              <Row label="Costo directo" value={direct} strong />
              <Row label="+ Gastos generales" value={sale.overhead} muted />
              <Row label="+ Beneficio" value={sale.profit} muted />
              <Row label="Precio neto (sin IVA)" value={sale.net} />
              <Row label="+ IVA" value={sale.iva} muted />
              <div className="mt-2 border-t border-slate-200 pt-2 dark:border-slate-700">
                <Row label="PRECIO DE VENTA" value={sale.total} strong highlight />
              </div>
            </dl>
            <p className="mt-3 text-xs text-slate-400">
              {sim.totals.labor_hours.toFixed(0)} horas hombre · {sim.totals.duration_days.toFixed(0)} días estimados
            </p>
          </div>

          {/* Proyección + tasas */}
          <div className="space-y-6">
            <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                  Proyección de costo (IPC)
                </h2>
                <select
                  value={horizon}
                  onChange={(e) => setHorizon(Number(e.target.value))}
                  className="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
                >
                  <option value={3} className="bg-white text-slate-900 dark:bg-slate-800 dark:text-white">3 meses</option>
                  <option value={6} className="bg-white text-slate-900 dark:bg-slate-800 dark:text-white">6 meses</option>
                  <option value={12} className="bg-white text-slate-900 dark:bg-slate-800 dark:text-white">12 meses</option>
                </select>
              </div>
              {forecast ? (
                <div>
                  <p className="text-2xl font-bold text-slate-900 dark:text-white">
                    ${fmtARS(forecast.projected_cost)}
                  </p>
                  <p className="text-sm text-slate-500">
                    en {forecast.horizon_months} meses ·{" "}
                    <span className="font-semibold text-amber-600 dark:text-amber-400">
                      +{forecast.variation.toFixed(1)}%
                    </span>{" "}
                    ({(forecast.monthly_rate * 100).toFixed(2)}%/mes, IPC real)
                  </p>
                </div>
              ) : (
                <p className="text-sm text-slate-400">Sin índice de inflación cargado.</p>
              )}
            </div>

            {settings && (
              <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
                  Tasas indirectas
                </h2>
                <div className="grid grid-cols-3 gap-3">
                  <PctInput label="Gastos grales." value={settings.overhead_pct}
                            onSave={(v) => saveSettings({ overhead_pct: v })} />
                  <PctInput label="Beneficio" value={settings.profit_pct}
                            onSave={(v) => saveSettings({ profit_pct: v })} />
                  <PctInput label="IVA" value={settings.iva_pct}
                            onSave={(v) => saveSettings({ iva_pct: v })} />
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Detalle de materiales */}
      {sim && sim.lines.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800/50">
              <tr>
                <th className="px-4 py-2">Material</th>
                <th className="px-4 py-2 text-right">Cantidad</th>
                <th className="px-4 py-2 text-right">Precio unit.</th>
                <th className="px-4 py-2 text-right">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {sim.lines
                .slice()
                .sort((a, b) => b.total - a.total)
                .map((ln) => (
                  <tr key={ln.material_id}>
                    <td className="px-4 py-2">{ln.material_name}</td>
                    <td className="px-4 py-2 text-right text-slate-500">
                      {ln.quantity.toFixed(1)} {ln.unit}
                    </td>
                    <td className="px-4 py-2 text-right text-slate-500">${fmtARS(ln.unit_cost)}</td>
                    <td className="px-4 py-2 text-right font-medium">${fmtARS(ln.total)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Row({ label, value, strong, muted, highlight }: {
  label: string; value: number; strong?: boolean; muted?: boolean; highlight?: boolean;
}) {
  return (
    <div className="flex justify-between">
      <dt className={muted ? "text-slate-400" : strong ? "font-semibold text-slate-900 dark:text-white" : "text-slate-600 dark:text-slate-300"}>
        {label}
      </dt>
      <dd className={highlight ? "text-lg font-bold text-brand" : strong ? "font-semibold text-slate-900 dark:text-white" : "text-slate-700 dark:text-slate-200"}>
        ${fmtARS(value)}
      </dd>
    </div>
  );
}

function PctInput({ label, value, onSave }: { label: string; value: number; onSave: (v: number) => void }) {
  const [draft, setDraft] = useState((value * 100).toFixed(0));
  useEffect(() => setDraft((value * 100).toFixed(0)), [value]);
  return (
    <label className="block text-xs text-slate-500">
      {label}
      <div className="mt-1 flex items-center gap-1">
        <input
          type="number"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => {
            const v = Number(draft) / 100;
            if (!Number.isNaN(v) && v !== value) onSave(v);
          }}
          className="w-full rounded border border-slate-300 bg-transparent px-2 py-1 text-sm dark:border-slate-700"
        />
        <span className="text-slate-400">%</span>
      </div>
    </label>
  );
}

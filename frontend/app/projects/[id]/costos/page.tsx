"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import Link from "next/link";

import {
  api,
  type CostSettings,
  type ForecastResult,
  type Project,
  type ProjectBudgetSummary,
  type ProjectBudgetView,
} from "@/lib/api";
import { FEATURES } from "@/lib/features";

function fmtARS(n: number): string {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(Math.round(n));
}

export default function CostosPage() {
  return FEATURES.legacyBudget ? <LegacyCostos /> : <SupplierCostos />;
}

type StageRow = { stage: string; materials: number; labor: number; total: number };

/** Materiales y mano de obra por rubro. Los materiales se escalan al neto de
 *  la lista de compras (bolsas enteras), así la tabla suma el costo directo. */
function stageRows(view: ProjectBudgetView): StageRow[] {
  const rows = new Map<string, StageRow>();
  const row = (stage: string) => {
    let r = rows.get(stage);
    if (!r) {
      r = { stage, materials: 0, labor: 0, total: 0 };
      rows.set(stage, r);
    }
    return r;
  };
  const items = (view.budget?.items ?? []).filter((i) => i.status === "ok" && i.subtotal);
  const raw = items.reduce((s, i) => s + (i.subtotal ?? 0), 0);
  const scale = raw > 0 ? (view.budget?.totals.net ?? 0) / raw : 0;
  for (const i of items) row(i.stage || "Sin rubro").materials += (i.subtotal ?? 0) * scale;
  for (const s of view.labor?.by_stage ?? []) row(s.stage).labor += s.cost;
  const out = Array.from(rows.values());
  for (const r of out) r.total = r.materials + r.labor;
  return out.filter((r) => r.total > 0).sort((a, b) => b.total - a.total);
}

/** Costos: precio de venta + proyección IPC del presupuesto del proyecto
 *  (presupuesto del proveedor × reglas + mano de obra). */
function SupplierCostos() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = Number(params.id);

  const [project, setProject] = useState<Project | null>(null);
  const [view, setView] = useState<ProjectBudgetView | null>(null);
  const [forecast, setForecast] = useState<ForecastResult | null>(null);
  const [horizon, setHorizon] = useState(6);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    Promise.all([api.getProject(projectId), api.getProjectPriceList(projectId)])
      .then(([proj, v]) => {
        setProject(proj);
        setView(v);
      })
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setLoading(false));
  }, [projectId]);

  const direct = view?.price?.direct ?? 0;
  useEffect(() => {
    if (direct <= 0) return;
    api.forecastCostByAmount(direct, horizon).then(setForecast).catch(() => setForecast(null));
  }, [direct, horizon]);

  async function download() {
    setDownloading(true);
    setError(null);
    try {
      await api.downloadProjectBudgetPdf(projectId, project?.name, "comitente");
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setDownloading(false);
    }
  }

  if (loading) return <div className="p-8 text-slate-500">Cargando…</div>;

  const price = view?.price ?? null;
  const missing = !view
    ? null
    : view.model_status === "processing"
      ? "El modelo BIM todavía se está procesando. Volvé en un momento."
      : view.model_status !== "ready"
        ? "Este proyecto no tiene un modelo IFC listo para presupuestar."
        : !price
          ? "Todavía no hay presupuesto: cargá el presupuesto del proveedor o los precios de mano de obra."
          : null;
  const rows = view && price ? stageRows(view) : [];
  const pct = (n: number) => `${Math.round(n * 100)}%`;

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
          <h1 className="mt-1 text-2xl font-bold text-slate-900 dark:text-white">Presupuesto Inteligente</h1>
          <p className="text-sm text-slate-500">
            {project?.name}
            <span className="ml-2 text-slate-400">· mismos números que Presupuesto + proyección IPC</span>
          </p>
        </div>
        <button
          onClick={() => void download()}
          disabled={!price || downloading}
          className="rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {downloading ? "Generando…" : "Descargar PDF"}
        </button>
      </div>

      {error && (
        <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
          {error}
        </div>
      )}
      {missing && (
        <div className="rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
          {missing}{" "}
          <Link href={`/projects/${projectId}/presupuesto`} className="font-semibold underline">
            Ir a Presupuesto
          </Link>
        </div>
      )}

      {price && (
        <div className="grid gap-6 md:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Del costo al precio de venta
            </h2>
            <dl className="space-y-1.5 text-sm">
              <Row label="Materiales (neto)" value={price.materials} />
              <Row label="Mano de obra" value={price.labor} />
              <Row label="Costo directo" value={price.direct} strong />
              <Row label={`+ Gastos generales (${pct(price.overhead_pct)})`} value={price.overhead} muted />
              <Row label={`+ Beneficio (${pct(price.profit_pct)})`} value={price.profit} muted />
              <Row label="Precio neto (sin IVA)" value={price.net} />
              <Row label={`+ IVA (${pct(price.iva_pct)})`} value={price.iva} muted />
              <div className="mt-2 border-t border-slate-200 pt-2 dark:border-slate-700">
                <Row label="PRECIO DE VENTA" value={price.total} strong highlight />
              </div>
            </dl>
            <p className="mt-3 text-xs text-slate-400">
              Los márgenes y la mano de obra se ajustan en{" "}
              <Link href={`/projects/${projectId}/presupuesto`} className="underline">Presupuesto</Link>.
              {view?.labor && view.labor.counts.pendientes > 0 && (
                <span className="text-amber-600 dark:text-amber-400">
                  {" "}{view.labor.counts.pendientes} ítems de mano de obra sin precio.
                </span>
              )}
            </p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Proyección de costo (IPC)</h2>
              <select
                value={horizon}
                onChange={(e) => setHorizon(Number(e.target.value))}
                className="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              >
                <option value={3}>3 meses</option>
                <option value={6}>6 meses</option>
                <option value={12}>12 meses</option>
              </select>
            </div>
            {forecast ? (
              <div>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">${fmtARS(forecast.projected_cost)}</p>
                <p className="text-sm text-slate-500">
                  sobre costo directo (${fmtARS(price.direct)}) en {forecast.horizon_months} meses ·{" "}
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
        </div>
      )}

      {rows.length > 0 && price && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800/50">
              <tr>
                <th className="px-4 py-2">Rubro</th>
                <th className="px-4 py-2 text-right">Materiales</th>
                <th className="px-4 py-2 text-right">Mano de obra</th>
                <th className="px-4 py-2 text-right">%</th>
                <th className="px-4 py-2 text-right">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {rows.map((r) => (
                <tr key={r.stage}>
                  <td className="px-4 py-2">{r.stage}</td>
                  <td className="px-4 py-2 text-right text-slate-500">${fmtARS(r.materials)}</td>
                  <td className="px-4 py-2 text-right text-slate-500">${fmtARS(r.labor)}</td>
                  <td className="px-4 py-2 text-right text-slate-500">
                    {price.direct > 0 ? ((r.total / price.direct) * 100).toFixed(1) : "0"}%
                  </td>
                  <td className="px-4 py-2 text-right font-medium">${fmtARS(r.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Motor viejo: catálogo de insumos/sistemas + paramétricos (FEATURES.legacyBudget). */
function LegacyCostos() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = Number(params.id);

  const [project, setProject] = useState<Project | null>(null);
  const [planId, setPlanId] = useState<number | null>(null);
  const [budget, setBudget] = useState<ProjectBudgetSummary | null>(null);
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
        const ready = plans.find((p) => p.status === "ready") ?? null;
        if (!ready) {
          const proc = plans.find((p) => p.status === "processing");
          const failed = plans.find((p) => p.status === "error" || p.status === "failed");
          if (proc) {
            setError("El modelo BIM todavía se está procesando. Volvé en un momento.");
          } else if (failed) {
            setError(
              failed.error_message?.trim() ||
                "El modelo BIM falló al procesarse. Subí de nuevo el archivo .ifc.",
            );
          } else {
            setError("Este proyecto no tiene un plano listo para calcular costos.");
          }
        }
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
      // Misma fuente que /presupuesto (obra gris + paramétricos).
      const b = await api.getBudgetSummary(planId);
      setBudget(b);
      try {
        setForecast(await api.forecastCostByAmount(b.direct_cost, horizon));
      } catch {
        setForecast(null);
      }
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setComputing(false);
    }
  }, [planId, horizon]);

  // Auto-calcula al cargar el plano.
  useEffect(() => {
    if (planId) void compute();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planId]);

  // Re-proyecta cuando cambia el horizonte (sin recalcular el presupuesto).
  useEffect(() => {
    if (!budget) return;
    api
      .forecastCostByAmount(budget.direct_cost, horizon)
      .then(setForecast)
      .catch(() => setForecast(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [horizon]);

  async function saveSettings(patch: Partial<CostSettings>) {
    try {
      setSettings(await api.updateCostSettings(patch));
      // Las tasas entran en sale_price del budget-summary: refrescar.
      if (planId) {
        const b = await api.getBudgetSummary(planId);
        setBudget(b);
        try {
          setForecast(await api.forecastCostByAmount(b.direct_cost, horizon));
        } catch {
          /* sin IPC */
        }
      }
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    }
  }

  async function download() {
    if (!planId || !budget) return;
    try {
      await api.downloadBudgetXlsx(planId, budget.project_name || project?.name);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    }
  }

  if (loading) {
    return <div className="p-8 text-slate-500">Cargando…</div>;
  }

  const bd = budget?.breakdown;

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
          <p className="text-sm text-slate-500">
            {project?.name}
            <span className="ml-2 text-slate-400">
              · mismos números que Presupuesto + proyección IPC
            </span>
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => void compute()}
            disabled={!planId || computing}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {computing ? "Calculando…" : "Recalcular"}
          </button>
          <button
            onClick={() => void download()}
            disabled={!budget}
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

      {budget && bd && (
        <div className="grid gap-6 md:grid-cols-2">
          {/* Desglose a precio de venta — misma fuente que /presupuesto */}
          <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Del costo al precio de venta
            </h2>
            <dl className="space-y-1.5 text-sm">
              <Row label="Materiales (obra gris)" value={budget.materials_total} />
              <Row label="Mano de obra (obra gris)" value={budget.labor_total} />
              {(budget.parametric_total ?? 0) > 0 && (
                <Row label="+ Rubros paramétricos" value={budget.parametric_total!} muted />
              )}
              <Row label="Costo directo" value={budget.direct_cost} strong />
              <Row label="+ Gastos generales" value={bd.overhead} muted />
              <Row label="+ Beneficio" value={bd.profit} muted />
              <Row label="Precio neto (sin IVA)" value={bd.direct + bd.overhead + bd.profit} />
              <Row label="+ IVA" value={bd.iva} muted />
              <div className="mt-2 border-t border-slate-200 pt-2 dark:border-slate-700">
                <Row label="PRECIO DE VENTA" value={bd.total} strong highlight />
              </div>
            </dl>
            <p
              className="mt-3 text-xs text-slate-400"
              title="Jornales = días-cuadrilla de esfuerzo (suma de tareas). El calendario real, con tareas en paralelo, está en el Cronograma (Gantt)."
            >
              {budget.labor_hours.toFixed(0)} horas hombre · {budget.duration_days.toFixed(0)} jornales
              {budget.cost_per_m2 != null && (
                <> · ${fmtARS(budget.cost_per_m2)} /m²</>
              )}
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
                    sobre costo directo (${fmtARS(budget.direct_cost)}) en {forecast.horizon_months} meses ·{" "}
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

      {/* Rubros — misma estructura que presupuesto */}
      {budget && budget.categories.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800/50">
              <tr>
                <th className="px-4 py-2">Rubro</th>
                <th className="px-4 py-2 text-right">%</th>
                <th className="px-4 py-2 text-right">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {budget.categories
                .slice()
                .sort((a, b) => b.total - a.total)
                .map((c) => (
                  <tr key={c.name}>
                    <td className="px-4 py-2">
                      {c.name}
                      {c.parametric ? (
                        <span className="ml-2 text-xs text-slate-400">(estimado)</span>
                      ) : null}
                    </td>
                    <td className="px-4 py-2 text-right text-slate-500">
                      {c.pct.toFixed(1)}%
                    </td>
                    <td className="px-4 py-2 text-right font-medium">${fmtARS(c.total)}</td>
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

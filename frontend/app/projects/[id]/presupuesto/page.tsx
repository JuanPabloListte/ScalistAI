"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type ParametricRubro, type ProjectBudgetSummary } from "@/lib/api";

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
  const [processing, setProcessing] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [isIfc, setIsIfc] = useState(false);
  const [rubros, setRubros] = useState<ParametricRubro[] | null>(null);
  const [showEditor, setShowEditor] = useState(false);
  const [savingRubros, setSavingRubros] = useState(false);

  async function saveRubros() {
    if (!rubros) return;
    setSavingRubros(true);
    try {
      await api.updateParametricRubros(rubros);
      // recargar el presupuesto para reflejar los nuevos totales
      const plans = await api.listPlans(projectId);
      const ready = plans.find((p) => p.status === "ready") ?? plans[0];
      if (ready) setData(await api.getBudgetSummary(ready.id));
      setShowEditor(false);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setSavingRubros(false);
    }
  }

  async function download(planId: number, name: string) {
    setDownloading(true);
    try {
      // Misma fuente que la pantalla (obra gris + paramétricos), no la simulación sola.
      await api.downloadBudgetXlsx(planId, name);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setDownloading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let tries = 0;
    const MAX_TRIES = 90; // ~6 min a 4s
    async function load() {
      try {
        const plans = await api.listPlans(projectId);
        setIsIfc(plans.some((p) => p.original_filename?.toLowerCase().endsWith(".ifc")));
        const ready = plans.find((p) => p.status === "ready");
        const proc = plans.find((p) => p.status === "processing");
        const failed = plans.find((p) => p.status === "error" || p.status === "failed");
        // Modelo BIM (IFC) procesándose en background -> esperar y reintentar.
        if (!ready && proc) {
          if (cancelled) return;
          if (tries >= MAX_TRIES) {
            setProcessing(false);
            setLoading(false);
            setError(
              "El procesamiento del modelo BIM está tardando demasiado. " +
                "Probá recargar la página o subí de nuevo el archivo .ifc.",
            );
            return;
          }
          setProcessing(true);
          setLoading(false);
          tries += 1;
          timer = setTimeout(load, 4000);
          return;
        }
        if (!ready && failed) {
          if (cancelled) return;
          setProcessing(false);
          setLoading(false);
          setError(
            "No se pudo procesar el modelo BIM. Verificá que el .ifc se haya " +
              "exportado con geometría y base quantities, e intentá de nuevo " +
              "desde el wizard del proyecto.",
          );
          return;
        }
        const target = ready ?? plans[0];
        if (!target) throw new Error("Este proyecto no tiene un plano listo.");
        if (target.status === "error" || target.status === "failed") {
          throw new Error(
            "El modelo BIM falló al procesarse. Subí de nuevo el archivo .ifc.",
          );
        }
        const d = await api.getBudgetSummary(target.id);
        if (cancelled) return;
        setProcessing(false);
        setData(d);
        setLoading(false);
      } catch (e) {
        if (!cancelled) {
          setError(String((e as Error)?.message ?? e));
          setLoading(false);
          setProcessing(false);
        }
      }
    }
    load();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [projectId]);

  useEffect(() => {
    api.getParametricRubros().then(setRubros).catch(() => {});
  }, []);

  if (loading) return <div className="p-8 text-slate-500">Calculando presupuesto…</div>;
  if (error) return <div className="p-8 text-red-600">{error}</div>;
  if (processing && !data) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 p-8 text-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-300 border-t-brand" />
        <p className="font-medium text-slate-700 dark:text-slate-200">Procesando el modelo BIM…</p>
        <p className="text-sm text-slate-500">Extrayendo muros, aberturas, losas y demás. Puede tardar un minuto.</p>
      </div>
    );
  }
  if (!data) return null;

  const maxPct = Math.max(...data.categories.map((c) => c.pct), 1);

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-center justify-between gap-3">
        <button onClick={() => router.push(isIfc ? "/projects" : `/projects/${projectId}`)}
                className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← {isIfc ? "Volver a proyectos" : "Volver al proyecto"}
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
              {data.area_estimated ? "≈ " : ""}{fmtARS(data.area_m2)} m² cubiertos
              {data.area_estimated && (
                <span className="ml-1 cursor-help text-amber-400/90"
                      title="El modelo IFC no trae ambientes (IfcSpace), así que el área cubierta es una ESTIMACIÓN: huella del edificio × pisos habitables, no una medida exacta. La estructura y las aberturas sí son exactas. Para área exacta, el modelo Revit necesita Rooms colocados.">
                  (estimada)
                </span>
              )}
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs uppercase tracking-wide text-slate-400">Precio de venta (c/ IVA)</p>
            <p className="text-2xl font-semibold text-emerald-400">${fmtARS(data.sale_price)}</p>
            <p className="mt-1 text-xs text-slate-400"
               title="Jornales = días-cuadrilla de esfuerzo (suma de tareas, no calendario). El tiempo real de obra, con tareas en paralelo, se ve en el Cronograma (Gantt).">
              {fmtARS(data.labor_hours)} h·hombre · {fmtARS(data.duration_days)} jornales de obra
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
          <Stat label="Vigas" value={`${fmtARS(data.takeoff.beams_ml)} ml`}
                sub={data.takeoff.escaleras ? `+ ${data.takeoff.escaleras} escaleras` : undefined} />
          <Stat label="Sanitarios"
                value={data.takeoff.sanitarios
                  ? `${data.takeoff.sanitarios} artefactos`
                  : `${fmtARS(data.takeoff.cloaca_ml)} ml`}
                sub={data.takeoff.sanitarios
                  ? (data.takeoff.cloaca_ml ? `${fmtARS(data.takeoff.cloaca_ml)} ml de cañería` : "red no modelada (≈ estimada)")
                  : undefined} />
          <Stat label="Eléctrico"
                value={data.takeoff.bocas_electricas
                  ? `${data.takeoff.bocas_electricas} bocas`
                  : `${fmtARS(data.takeoff.electricidad_ml)} ml`}
                sub={data.takeoff.bocas_electricas
                  ? (data.takeoff.electricidad_ml ? `${fmtARS(data.takeoff.electricidad_ml)} ml de tendido` : "red no modelada (≈ estimada)")
                  : undefined} />
          {((data.takeoff.pilotes ?? 0) > 0 || (data.takeoff.zapatas_ml ?? 0) > 0) && (
            <Stat label="Fundaciones"
                  value={data.takeoff.pilotes ? `${data.takeoff.pilotes} pilotes` : `${fmtARS(data.takeoff.zapatas_ml ?? 0)} ml`}
                  sub={data.takeoff.pilotes && (data.takeoff.zapatas_ml ?? 0) > 0
                    ? `+ ${fmtARS(data.takeoff.zapatas_ml ?? 0)} ml de zapatas/riostras`
                    : "del modelo BIM"} />
          )}
          {(data.takeoff.armadura_kg ?? 0) > 0 && (
            <Stat label="Armadura"
                  value={`${fmtARS(data.takeoff.armadura_kg ?? 0)} kg`}
                  sub={`${data.takeoff.armaduras} barras (exacto del modelo)`} />
          )}
          {(data.takeoff.equipos_hvac ?? 0) > 0 && (
            <Stat label="Climatización"
                  value={`${data.takeoff.equipos_hvac} equipos`}
                  sub="caldera / calefactores del modelo" />
          )}
        </div>
      </section>

      {/* DESGLOSE POR RUBRO */}
      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3 dark:border-slate-800">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Desglose por rubro</h2>
          {rubros && (
            <button onClick={() => setShowEditor((v) => !v)}
                    className="rounded-md border border-amber-300 px-2.5 py-1 text-xs font-medium text-amber-700 hover:bg-amber-50 dark:border-amber-500/40 dark:text-amber-300 dark:hover:bg-amber-500/10">
              {showEditor ? "Cerrar" : "Ajustar estimados"}
            </button>
          )}
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
            {(() => {
              const firstParam = data.categories.findIndex((c) => c.parametric);
              return data.categories.flatMap((c, i) => {
                const rows = [];
                if (i === firstParam && firstParam > 0) {
                  rows.push(
                    <tr key="__subtotal_obragris" className="bg-slate-50 text-xs dark:bg-slate-800/50">
                      <td className="px-5 py-2 font-semibold uppercase tracking-wide text-slate-500">
                        Obra gris (del modelo)
                      </td>
                      <td className="px-3 py-2 text-right font-semibold text-slate-700 dark:text-slate-200">
                        ${fmtARS(data.obra_gris_direct ?? 0)}
                      </td>
                      <td colSpan={2} className="px-5 py-2 text-right text-amber-600 dark:text-amber-400">
                        ↓ estimados (no vienen del modelo)
                      </td>
                    </tr>,
                  );
                }
                rows.push(
                  <tr key={c.name}
                      className={c.parametric
                        ? "bg-amber-50/40 hover:bg-amber-50 dark:bg-amber-500/[0.04] dark:hover:bg-amber-500/10"
                        : "hover:bg-slate-50 dark:hover:bg-slate-800/40"}>
                    <td className="px-5 py-2.5">
                      <span className="text-slate-400">{i + 1}.</span>{" "}
                      <span className={c.parametric ? "text-amber-800 dark:text-amber-200" : "text-slate-800 dark:text-slate-100"}>
                        {c.name}
                      </span>
                      {c.parametric && (
                        <span className="ml-2 cursor-help rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
                              title="Rubro estimado como % de la obra gris (el modelo IFC no lo trae). Editable en 'Ajustar estimados'.">
                          ≈ estimado
                        </span>
                      )}
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
                          <div className={`h-full rounded-full ${c.parametric ? "bg-amber-400" : "bg-brand"}`}
                               style={{ width: `${(c.pct / maxPct) * 100}%` }} />
                        </div>
                        <span className="w-12 text-right tabular-nums text-slate-500">{c.pct.toFixed(1)}%</span>
                      </div>
                    </td>
                  </tr>,
                );
                return rows;
              });
            })()}
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

      {/* EDITOR DE RUBROS PARAMÉTRICOS */}
      {showEditor && rubros && (
        <section className="rounded-xl border border-amber-200 bg-amber-50/50 p-5 dark:border-amber-500/30 dark:bg-amber-500/[0.04]">
          <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-200">Ajustar estimados</h3>
          <p className="mt-1 text-xs text-amber-700/90 dark:text-amber-300/80">
            Rubros que el modelo no trae, estimados como % de la <b>obra gris</b> (${fmtARS(data.obra_gris_direct ?? 0)}).
            Ajustá los porcentajes según tu experiencia o poné 0 para excluir un rubro.
          </p>
          <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {rubros.map((r, idx) => (
              <label key={r.key} className="flex items-center justify-between gap-3 rounded-md bg-white/70 px-3 py-2 text-sm dark:bg-slate-900/40">
                <span className="text-slate-700 dark:text-slate-200">{r.label}</span>
                <span className="flex items-center gap-1">
                  <input type="number" min="0" max="500" step="1"
                         value={Math.round(r.pct * 100)}
                         onChange={(e) => {
                           const v = Math.max(0, Number(e.target.value) || 0) / 100;
                           setRubros((prev) => prev!.map((x, i) => (i === idx ? { ...x, pct: v } : x)));
                         }}
                         className="w-16 rounded border border-slate-300 px-2 py-1 text-right dark:border-slate-600 dark:bg-slate-900" />
                  <span className="text-slate-400">%</span>
                </span>
              </label>
            ))}
          </div>
          <div className="mt-4 flex items-center gap-3">
            <button onClick={() => void saveRubros()} disabled={savingRubros}
                    className="rounded-md bg-amber-500 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-600 disabled:opacity-50">
              {savingRubros ? "Recalculando…" : "Guardar y recalcular"}
            </button>
            <button onClick={() => api.getParametricRubros().then(setRubros)}
                    className="text-xs text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
              Restablecer
            </button>
          </div>
        </section>
      )}

      {(data.parametric_total ?? 0) > 0 && (
        <div className="space-y-1.5 rounded-lg border border-amber-200 bg-amber-50/50 px-4 py-2.5 text-xs text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/[0.04] dark:text-amber-200">
          <p>
            ⚠ Los rubros marcados <b>≈ estimado</b> (${fmtARS(data.parametric_total ?? 0)}) no salen del modelo:
            son fundaciones, instalaciones y terminaciones calculadas como % de la obra gris. La estructura,
            mampostería y aberturas sí son cómputo exacto. Ajustá los % con "Ajustar estimados".
          </p>
          {((data.takeoff.sanitarios ?? 0) > 0 || (data.takeoff.bocas_electricas ?? 0) > 0) && (
            <p className="text-amber-700/90 dark:text-amber-300/80">
              Nota: las instalaciones aparecen en dos partes. Lo que el modelo trae
              (artefactos sanitarios, bocas eléctricas y sus conexiones) se computa <b>exacto</b>
              en los rubros de arriba; el <b>≈ estimado</b> de instalaciones cubre solo la <b>red faltante</b>
              (cañerías y cableado generales, no modelados) — ya se le descontó lo exacto, no hay doble conteo.
            </p>
          )}
        </div>
      )}

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

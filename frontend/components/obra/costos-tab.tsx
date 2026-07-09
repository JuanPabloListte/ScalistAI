"use client";

/**
 * Obra · Costos (Etapa 3): avance financiero con valor ganado (EVM) y el
 * killer argentino: separar cuánto del desvío es INFLACIÓN vs desvío real.
 */

import { useCallback, useEffect, useState } from "react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, type WorkCost, type ActualCostRow, type WorkProgress } from "@/lib/api";

function fmtARS(n: number): string {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(Math.round(n));
}
function fmtM(n: number): string {
  return `$${(n / 1_000_000).toFixed(1)}M`;
}
function fmtDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("es-AR", { day: "2-digit", month: "short" });
}

const KIND_LABEL: Record<string, string> = {
  material: "Materiales", mano_obra: "Mano de obra", otro: "Otros",
};

export function CostosTab({ projectId, progress }: { projectId: number; progress: WorkProgress | null }) {
  const [cost, setCost] = useState<WorkCost | null>(null);
  const [rows, setRows] = useState<ActualCostRow[]>([]);
  const [loading, setLoading] = useState(true);

  // form
  const [amount, setAmount] = useState("");
  const [kind, setKind] = useState("material");
  const [stage, setStage] = useState("");
  const [note, setNote] = useState("");
  const [date, setDate] = useState("");
  const [saving, setSaving] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [invoiceMsg, setInvoiceMsg] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([api.getWorkCost(projectId), api.listActualCosts(projectId)])
      .then(([c, r]) => { setCost(c); setRows(r); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [projectId]);
  useEffect(() => { load(); }, [load]);

  async function save() {
    const a = Number(amount);
    if (!a || a <= 0) return;
    setSaving(true);
    try {
      const c = await api.addActualCost(projectId, {
        amount: a, kind, stage: stage || undefined, note: note || undefined,
        date: date || undefined,
      });
      setCost(c);
      setRows(await api.listActualCosts(projectId));
      setAmount(""); setNote(""); setDate(""); setInvoiceMsg(null);
    } finally {
      setSaving(false);
    }
  }

  // Importar factura (PDF con texto): PROPONE monto/fecha; el usuario revisa y
  // confirma con "Registrar". No guarda nada por sí solo.
  async function importInvoice(file: File) {
    setParsing(true);
    setInvoiceMsg(null);
    try {
      const p = await api.parseInvoice(projectId, file);
      if (!p.ok) { setInvoiceMsg(p.reason || "No se pudo leer la factura."); return; }
      if (p.amount != null) setAmount(String(p.amount));
      if (p.date) setDate(p.date);
      const proveedor = [p.vendor, p.cuit ? `CUIT ${p.cuit}` : null].filter(Boolean).join(" · ");
      if (proveedor) setNote(proveedor);
      setInvoiceMsg(
        `Propuesta: $${p.amount != null ? fmtARS(p.amount) : "—"} · ${p.date || "sin fecha"}. ` +
        "Revisá y confirmá con «Registrar».");
    } catch (e) {
      setInvoiceMsg(String((e as Error)?.message ?? e));
    } finally {
      setParsing(false);
    }
  }

  async function remove(id: number) {
    await api.deleteActualCost(id);
    load();
  }

  if (loading) return <div className="p-8 text-center text-slate-500">Cargando costos…</div>;
  if (!cost) return <div className="p-8 text-center text-slate-500">Sin datos de costos.</div>;

  const e = cost.evm;
  const inf = cost.inflation;
  const cpiBad = e.cpi != null && e.cpi < 1;
  const stages = progress?.stages ?? [];
  const stageNames = [...new Set([...(cost.stages.map((s) => s.stage)), ...stages.map((s) => s.stage)])]
    .filter((s) => s && s !== "Sin asignar");

  return (
    <div className="space-y-6">
      {/* KPIs EVM */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div className="text-xs text-slate-500">Gastado (real)</div>
          <div className="text-xl font-bold text-slate-900 dark:text-white">${fmtARS(e.ac)}</div>
          <div className="text-[11px] text-slate-400">de ${fmtARS(e.bac)} presupuestado</div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div className="text-xs text-slate-500">Eficiencia de costo (CPI)</div>
          <div className={`text-xl font-bold ${cpiBad ? "text-red-600 dark:text-red-400" : "text-green-600 dark:text-green-400"}`}>
            {e.cpi ?? "—"}
          </div>
          <div className="text-[11px] text-slate-400">{cpiBad ? "gastás más de lo que avanzás" : "en presupuesto"}</div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div className="text-xs text-slate-500">Costo final proyectado (EAC)</div>
          <div className={`text-xl font-bold ${e.over_budget_at_completion > 0 ? "text-red-600 dark:text-red-400" : "text-green-600 dark:text-green-400"}`}>
            ${fmtARS(e.eac)}
          </div>
          <div className="text-[11px] text-slate-400">
            {e.over_budget_at_completion > 0 ? `+$${fmtARS(e.over_budget_at_completion)} sobre presupuesto` : "dentro del presupuesto"}
          </div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div className="text-xs text-slate-500">Valor ganado (EV)</div>
          <div className="text-xl font-bold text-brand-600 dark:text-brand-400">${fmtARS(e.ev)}</div>
          <div className="text-[11px] text-slate-400">trabajo hecho a precio de plan</div>
        </div>
      </div>

      {/* Killer feature: inflación vs desvío real */}
      {inf && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-5 dark:border-amber-500/30 dark:bg-amber-500/[0.05]">
          <h3 className="text-sm font-bold text-amber-900 dark:text-amber-200">
            ¿Gastaste de más por inflación o por desvío real?
          </h3>
          <p className="mt-1 text-xs text-amber-700/90 dark:text-amber-300/80">
            El IPC (INDEC) subió <b>{inf.accum_pct}%</b> desde que congelaste el plan
            ({fmtDate(inf.ipc_base_date)}). Separamos tu diferencia de costo:
          </p>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="rounded-lg bg-white/70 p-3 dark:bg-slate-900/40">
              <div className="text-xs text-slate-500">Por inflación (no es tu culpa)</div>
              <div className="text-lg font-bold text-slate-700 dark:text-slate-200">${fmtARS(inf.inflation_gap)}</div>
              <div className="text-[11px] text-slate-400">lo mismo, más caro por suba de precios</div>
            </div>
            <div className="rounded-lg bg-white/70 p-3 dark:bg-slate-900/40">
              <div className="text-xs text-slate-500">Desvío real (eficiencia)</div>
              <div className={`text-lg font-bold ${inf.real_variance > 0 ? "text-red-600 dark:text-red-400" : "text-green-600 dark:text-green-400"}`}>
                {inf.real_variance > 0 ? "+" : ""}${fmtARS(inf.real_variance)}
              </div>
              <div className="text-[11px] text-slate-400">
                {inf.real_variance > 0 ? "por encima del precio justo de hoy" : "por debajo del precio de hoy"}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Curva S: plan / real / proyección */}
      <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
        <h3 className="mb-1 font-bold text-slate-900 dark:text-white">Curva de inversión</h3>
        <p className="mb-4 text-xs text-slate-500">Acumulado: planificado vs gastado real vs proyección al ritmo actual.</p>
        <div style={{ height: 260 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={cost.curve} margin={{ left: 4, right: 8, top: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-slate-200 dark:text-slate-800" />
              <XAxis dataKey="month" tickFormatter={(m) => (m as string).slice(2)} fontSize={11} stroke="currentColor" className="text-slate-400" />
              <YAxis tickFormatter={fmtM} fontSize={11} width={48} stroke="currentColor" className="text-slate-400" />
              <Tooltip formatter={(v) => `$${fmtARS(Number(v))}`} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="plan" name="Plan" stroke="#94a3b8" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="real" name="Real" stroke="#0ea5e9" strokeWidth={2.5} dot={false} />
              <Line type="monotone" dataKey="projected" name="Proyección" stroke="#ef4444" strokeWidth={2} strokeDasharray="5 4" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Plan vs real por etapa */}
      {cost.stages.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100 text-left text-xs uppercase text-slate-400 dark:border-slate-800">
              <tr><th className="px-4 py-2">Etapa</th><th className="px-4 py-2 text-right">Plan</th><th className="px-4 py-2 text-right">Real</th><th className="px-4 py-2 text-right">Desvío</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {cost.stages.map((s) => {
                const dev = s.real - s.planned;
                return (
                  <tr key={s.stage}>
                    <td className="px-4 py-2 font-medium text-slate-700 dark:text-slate-200">{s.stage}</td>
                    <td className="px-4 py-2 text-right text-slate-500">${fmtARS(s.planned)}</td>
                    <td className="px-4 py-2 text-right font-medium text-slate-900 dark:text-white">{s.real ? `$${fmtARS(s.real)}` : "—"}</td>
                    <td className={`px-4 py-2 text-right ${s.real === 0 ? "text-slate-400" : dev > 0 ? "text-red-500" : "text-green-600 dark:text-green-400"}`}>
                      {s.real === 0 ? "—" : `${dev > 0 ? "+" : ""}$${fmtARS(dev)}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Cargar factura */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-bold text-slate-900 dark:text-white">Registrar costo real</h3>
          <label className="cursor-pointer rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-slate-400 dark:border-slate-600 dark:text-slate-300">
            {parsing ? "Leyendo…" : "Importar factura (PDF)"}
            <input type="file" accept="application/pdf,.pdf" className="hidden" disabled={parsing}
                   onChange={(e) => { const f = e.target.files?.[0]; if (f) importInvoice(f); e.target.value = ""; }} />
          </label>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col text-xs font-medium text-slate-600 dark:text-slate-400">
            Monto ($)
            <input type="number" min="0" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)}
                   className="mt-1 w-36 rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base dark:border-slate-600 dark:bg-slate-800" />
          </label>
          <label className="flex flex-col text-xs font-medium text-slate-600 dark:text-slate-400">
            Fecha
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
                   className="mt-1 rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm dark:border-slate-600 dark:bg-slate-800" />
          </label>
          <label className="flex flex-col text-xs font-medium text-slate-600 dark:text-slate-400">
            Tipo
            <select value={kind} onChange={(e) => setKind(e.target.value)}
                    className="mt-1 rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm dark:border-slate-600 dark:bg-slate-800">
              <option value="material">Materiales</option>
              <option value="mano_obra">Mano de obra</option>
              <option value="otro">Otros</option>
            </select>
          </label>
          <label className="flex flex-col text-xs font-medium text-slate-600 dark:text-slate-400">
            Etapa
            <select value={stage} onChange={(e) => setStage(e.target.value)}
                    className="mt-1 rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm dark:border-slate-600 dark:bg-slate-800">
              <option value="">— sin asignar —</option>
              {stageNames.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="flex min-w-32 flex-1 flex-col text-xs font-medium text-slate-600 dark:text-slate-400">
            Nota
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="proveedor / factura"
                   className="mt-1 rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm dark:border-slate-600 dark:bg-slate-800" />
          </label>
          <button onClick={save} disabled={saving || !amount}
                  className="rounded-lg bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-500 disabled:opacity-50">
            {saving ? "…" : "Registrar"}
          </button>
        </div>
        {invoiceMsg && (
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{invoiceMsg}</p>
        )}
        {rows.length > 0 && (
          <div className="mt-4 space-y-1">
            {rows.map((r) => (
              <div key={r.id} className="flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-1.5 text-xs dark:bg-slate-800/40">
                <span className="w-14 font-medium text-slate-500">{fmtDate(r.date)}</span>
                <span className="w-24 shrink-0 font-semibold text-slate-800 dark:text-slate-100">${fmtARS(r.amount)}</span>
                <span className="w-24 shrink-0 text-slate-500">{KIND_LABEL[r.kind] || r.kind}</span>
                <span className="w-28 shrink-0 truncate text-slate-500">{r.stage || "—"}</span>
                <span className="min-w-0 flex-1 truncate text-slate-400">{r.note}</span>
                <button onClick={() => remove(r.id)} className="text-red-400 hover:text-red-600" title="Borrar">✕</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

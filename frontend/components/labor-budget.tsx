"use client";

import { useEffect, useState } from "react";

import { Modal } from "@/components/modal";
import {
  api,
  type LaborItem,
  type LaborMode,
  type LaborRate,
  type ProjectBudgetView,
} from "@/lib/api";
import { money } from "@/lib/format";

const UNIT: Record<string, string> = { m2: "m²", m3: "m³", m: "m", kg: "kg", u: "u", l: "l" };
// Números como se escriben en Argentina: "21.500", "21500", "21.500,50" o "17,5".
// Con coma, los puntos son miles; sin coma, solo es miles el formato 1.234.567.
const num = (s: string) => {
  const v = s.trim().replace(/\s/g, "");
  if (v.includes(",")) return Number(v.replace(/\./g, "").replace(",", "."));
  return /^\d{1,3}(\.\d{3})+$/.test(v) ? Number(v.replace(/\./g, "")) : Number(v);
};
const qty = (n: number, d = 1) => n.toLocaleString("es-AR", { maximumFractionDigits: d });

const STATUS: Record<LaborItem["status"], { label: string; cls: string }> = {
  ok: { label: "Con precio", cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" },
  sin_precio: { label: "Falta el precio", cls: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300" },
  sin_jornal: { label: "Faltan jornales", cls: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300" },
  sin_rendimiento: { label: "Falta el rendimiento", cls: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300" },
  sin_medida: { label: "El modelo no lo trae", cls: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400" },
};

/** Filtro opcional de la mano de obra (solo la página Presupuesto lo usa). */
export type LaborFilter = { text: string; group: string };

export function matchesLaborFilter(it: { label: string; stage: string }, f?: LaborFilter): boolean {
  if (!f) return true;
  if (f.group && it.stage !== f.group) return false;
  const q = f.text.trim().toLowerCase();
  return !q || it.label.toLowerCase().includes(q);
}

/** Mano de obra por rubro: en cada tarea se elige si va tercerizada (precio
 *  del contratista por unidad) o con cuadrilla propia (rendimiento × jornales). */
export function LaborPanel({
  projectId,
  view,
  canEdit,
  isAdmin,
  onView,
  filter,
  hideTitle,
  toolbar,
}: {
  projectId: number;
  view: ProjectBudgetView;
  canEdit: boolean;
  isAdmin: boolean;
  onView: (v: ProjectBudgetView) => void;
  /** Opcional: oculta las tareas (y rubros) que no coinciden. */
  filter?: LaborFilter;
  /** Sin el título "Mano de obra" (lo da la pestaña). */
  hideTitle?: boolean;
  /** Barra de filtros que va dentro de la tarjeta, arriba (como en Materiales). */
  toolbar?: React.ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRates, setShowRates] = useState(false);
  const labor = view.labor;

  async function save(key: string, setting: { mode?: LaborMode; unit_price?: number | null } | null) {
    setBusy(true);
    setError(null);
    try {
      onView(await api.patchProjectBudgetSettings(projectId, { labor: { [key]: setting } }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setBusy(false);
    }
  }

  if (view.model_status !== "ready" || !labor) {
    return (
      <section className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
        <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">Mano de obra</h2>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Se calcula cuando el modelo IFC termina de procesarse.
        </p>
      </section>
    );
  }

  const visible = labor.items.filter((i) => i.status !== "sin_medida");
  const hidden = labor.items.length - visible.length;
  const shown = visible.filter((i) => matchesLaborFilter(i, filter));
  const stages = Array.from(new Set(shown.map((i) => i.stage)));

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
      {toolbar}
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          {!hideTitle && <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">Mano de obra</h2>}
          <p className={`${hideTitle ? "" : "mt-0.5 "}text-sm text-slate-500 dark:text-slate-400`}>
            En cada tarea elegí si la tercerizás (precio del contratista, sin IVA) o la hace tu cuadrilla
            (rendimiento × jornales). Los rendimientos y cuadrillas salen de las{" "}
            <a href="/reglas" target="_blank" className="text-brand hover:underline dark:text-sky-400">reglas de cómputo</a>.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowRates(true)}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          Jornales y márgenes
        </button>
      </div>

      {error && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}

      {visible.length === 0 ? (
        <p className="mt-4 text-sm text-slate-500 dark:text-slate-400">
          El juego de reglas «{view.rule_set?.name}» no tiene mano de obra para lo que trae el modelo.
          Agregala desde <a href="/reglas" target="_blank" className="text-brand hover:underline dark:text-sky-400">Reglas de cómputo</a>.
        </p>
      ) : shown.length === 0 ? (
        <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">Ningún ítem coincide con el filtro.</p>
      ) : (
        <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full min-w-[56rem] text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
              <tr>
                <th className="px-3 py-2 font-medium">Tarea</th>
                <th className="px-3 py-2 text-right font-medium">Cantidad</th>
                <th className="px-3 py-2 font-medium">Se cotiza</th>
                <th className="px-3 py-2 text-right font-medium">Precio por unidad</th>
                <th className="px-3 py-2 text-right font-medium">Días</th>
                <th className="px-3 py-2 text-right font-medium">Subtotal</th>
              </tr>
            </thead>
            {stages.map((stage) => {
              const items = shown.filter((i) => i.stage === stage);
              const total = items.reduce((s, i) => s + (i.cost ?? 0), 0);
              return (
                <tbody key={stage} className="border-t border-slate-200 dark:border-slate-800">
                  <tr className="bg-slate-50/60 dark:bg-slate-800/30">
                    <td colSpan={5} className="px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                      {stage}
                    </td>
                    <td className="px-3 py-1.5 text-right text-xs font-semibold tabular-nums text-slate-600 dark:text-slate-300">
                      {total ? money(total) : "—"}
                    </td>
                  </tr>
                  {items.map((it) => (
                    <LaborRow key={it.key} item={it} disabled={!canEdit || busy}
                              onMode={(mode) => save(it.key, { mode })}
                              onPrice={(price) => save(it.key, { mode: "unit", unit_price: price })}
                              onReset={() => save(it.key, null)} />
                  ))}
                </tbody>
              );
            })}
            <tfoot className="border-t border-slate-200 dark:border-slate-800">
              <tr>
                <td colSpan={5} className="px-3 py-2 text-right text-sm font-semibold text-slate-700 dark:text-slate-200">
                  Mano de obra
                </td>
                <td className="px-3 py-2 text-right text-sm font-semibold tabular-nums text-slate-900 dark:text-slate-100">
                  {money(labor.total)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {hidden > 0 && (
        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
          {hidden} {hidden === 1 ? "tarea no aplica" : "tareas no aplican"}: el modelo no trae esa medida.
        </p>
      )}

      {showRates && (
        <RatesModal
          isAdmin={isAdmin}
          onClose={() => setShowRates(false)}
          onSaved={async () => onView(await api.getProjectPriceList(projectId))}
        />
      )}
    </section>
  );
}

function LaborRow({
  item: it,
  disabled,
  onMode,
  onPrice,
  onReset,
}: {
  item: LaborItem;
  disabled: boolean;
  onMode: (m: LaborMode) => void;
  onPrice: (p: number | null) => void;
  onReset: () => void;
}) {
  const unit = UNIT[it.measure_unit] ?? it.measure_unit;
  const [price, setPrice] = useState(it.mode === "unit" && it.unit_price != null ? qty(it.unit_price, 2) : "");
  useEffect(() => {
    setPrice(it.mode === "unit" && it.unit_price != null ? qty(it.unit_price, 2) : "");
  }, [it.mode, it.unit_price]);
  const st = STATUS[it.status];

  function commit() {
    const v = price.trim() ? num(price) : null;
    if (v != null && !(v >= 0)) return;
    if (v !== (it.unit_price ?? null)) onPrice(v);
  }

  return (
    <tr className="border-t border-slate-100 align-top dark:border-slate-800/60">
      <td className="px-3 py-2">
        <div className="font-medium text-slate-800 dark:text-slate-100" title={it.notes ?? undefined}>{it.label}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
          <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${st.cls}`}>{st.label}</span>
          {it.status === "sin_jornal" && it.missing_trades.length > 0 && (
            <span>sin jornal: {it.missing_trades.join(", ")}</span>
          )}
          {it.manual && !disabled && (
            <button type="button" onClick={onReset} className="text-brand hover:underline dark:text-sky-400">
              ↺ volver a la regla
            </button>
          )}
        </div>
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-700 dark:text-slate-200">
        {qty(it.quantity)} {unit}
      </td>
      <td className="px-3 py-2">
        <select
          value={it.mode}
          disabled={disabled}
          onChange={(e) => onMode(e.target.value as LaborMode)}
          className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
        >
          <option value="unit">Tercerizado</option>
          <option value="daily">Cuadrilla propia</option>
        </select>
        {it.mode === "daily" && it.crew.length > 0 && (
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {it.crew.map((c) => `${qty(c.count)} ${c.trade.toLowerCase()}`).join(" + ")}
            {it.daily_yield ? ` · ${qty(it.daily_yield)} ${unit}/día` : ""}
          </div>
        )}
      </td>
      <td className="px-3 py-2 text-right">
        {it.mode === "unit" ? (
          <div className="flex items-center justify-end gap-1">
            <span className="text-xs text-slate-500">$</span>
            <input
              inputMode="decimal"
              value={price}
              disabled={disabled}
              placeholder={`por ${unit}`}
              aria-label={`Precio por ${unit} de ${it.label}`}
              onChange={(e) => setPrice(e.target.value)}
              onBlur={commit}
              onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
              className="w-28 rounded-md border border-slate-300 bg-white px-2 py-1 text-right text-sm tabular-nums dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            />
          </div>
        ) : (
          <span className="tabular-nums text-slate-700 dark:text-slate-200">
            {it.unit_price != null ? `${money(it.unit_price)} / ${unit}` : "—"}
          </span>
        )}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-600 dark:text-slate-300">
        {it.days != null ? qty(it.days) : "—"}
        {it.mode === "daily" && it.workdays != null && (
          <div className="text-xs text-slate-500 dark:text-slate-400">{qty(it.workdays)} jornales</div>
        )}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums text-slate-900 dark:text-slate-100">
        {it.cost != null ? money(it.cost) : "—"}
      </td>
    </tr>
  );
}

/** Precio de venta: costo directo + gastos generales + beneficio + IVA. */
export function SalePricePanel({
  projectId,
  view,
  canEdit,
  onView,
}: {
  projectId: number;
  view: ProjectBudgetView;
  canEdit: boolean;
  onView: (v: ProjectBudgetView) => void;
}) {
  const p = view.price;
  const s = view.settings;
  const [error, setError] = useState<string | null>(null);
  if (!p) return null;
  const pct = (n: number) => `${qty(n * 100, 1)}%`;

  async function save(payload: Parameters<typeof api.patchProjectBudgetSettings>[1]) {
    setError(null);
    try {
      onView(await api.patchProjectBudgetSettings(projectId, payload));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    }
  }

  const rows: { label: string; value: number; edit?: "overhead" | "profit"; strong?: boolean }[] = [
    { label: "Materiales", value: p.materials },
    { label: "Mano de obra", value: p.labor },
    { label: "Costo directo", value: p.direct, strong: true },
    { label: "Gastos generales", value: p.overhead, edit: "overhead" },
    { label: "Beneficio", value: p.profit, edit: "profit" },
    { label: "Precio sin IVA", value: p.net, strong: true },
    { label: `IVA ${pct(p.iva_pct)}`, value: p.iva },
  ];

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">Precio de venta</h2>
        {s.margins_custom && canEdit && (
          <button type="button" onClick={() => void save({ reset_margins: true })}
                  className="text-xs text-brand hover:underline dark:text-sky-400">
            ↺ Usar los márgenes de la empresa ({pct(s.org_overhead_pct)} y {pct(s.org_profit_pct)})
          </button>
        )}
      </div>
      <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
        Gastos generales sobre el costo directo; beneficio sobre el costo con gastos generales.
      </p>
      <dl className="mt-4 divide-y divide-slate-100 text-sm dark:divide-slate-800">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center justify-between gap-4 py-2">
            <dt className={`flex items-center gap-2 ${r.strong ? "font-semibold text-slate-800 dark:text-slate-100" : "text-slate-600 dark:text-slate-300"}`}>
              {r.label}
              {r.edit && (
                <PctInput
                  value={r.edit === "overhead" ? p.overhead_pct : p.profit_pct}
                  disabled={!canEdit}
                  label={r.label}
                  onCommit={(v) => void save(r.edit === "overhead" ? { overhead_pct: v } : { profit_pct: v })}
                />
              )}
            </dt>
            <dd className={`tabular-nums ${r.strong ? "font-semibold text-slate-900 dark:text-slate-100" : "text-slate-700 dark:text-slate-200"}`}>
              {money(r.value)}
            </dd>
          </div>
        ))}
        <div className="flex items-center justify-between gap-4 py-3">
          <dt className="text-base font-bold text-slate-900 dark:text-white">Precio de venta</dt>
          <dd className="text-xl font-bold tabular-nums text-brand-600 dark:text-sky-400">{money(p.total)}</dd>
        </div>
      </dl>
      {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
    </section>
  );
}

function PctInput({ value, disabled, label, onCommit }: {
  value: number; disabled: boolean; label: string; onCommit: (v: number) => void;
}) {
  const [v, setV] = useState(qty(value * 100, 2));
  useEffect(() => setV(qty(value * 100, 2)), [value]);
  return (
    <span className="flex items-center gap-1 text-xs text-slate-500">
      <input
        inputMode="decimal"
        value={v}
        disabled={disabled}
        aria-label={`${label} (%)`}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => {
          const n = Number(v.replace(",", "."));
          if (n >= 0 && Math.abs(n / 100 - value) > 1e-9) onCommit(n / 100);
        }}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        className="w-14 rounded-md border border-slate-300 bg-white px-1.5 py-0.5 text-right text-xs tabular-nums dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
      />
      %
    </span>
  );
}

/** Jornales de la empresa (costo por día con cargas sociales) y márgenes por defecto. */
function RatesModal({ isAdmin, onClose, onSaved }: {
  isAdmin: boolean; onClose: () => void; onSaved: () => Promise<void>;
}) {
  const [rates, setRates] = useState<{ trade: string; cost: string; updated_on: string | null }[] | null>(null);
  const [margins, setMargins] = useState<{ overhead: string; profit: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.listLaborRates(), api.getCostSettings()])
      .then(([r, cs]) => {
        setRates(r.map((x: LaborRate) => ({ trade: x.trade, cost: x.daily_cost ? qty(x.daily_cost, 2) : "",
                                            updated_on: x.updated_on })));
        setMargins({ overhead: qty(cs.overhead_pct * 100, 2), profit: qty(cs.profit_pct * 100, 2) });
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  async function save() {
    if (!rates || !margins) return;
    const clean = rates.filter((r) => r.trade.trim());
    if (clean.some((r) => r.cost.trim() && !(num(r.cost) >= 0))) {
      setError("Revisá los costos: tienen que ser números.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.replaceLaborRates(clean.map((r) => ({ trade: r.trade.trim(), daily_cost: r.cost.trim() ? num(r.cost) : 0 })));
      await api.updateCostSettings({
        overhead_pct: Number(margins.overhead.replace(",", ".")) / 100,
        profit_pct: Number(margins.profit.replace(",", ".")) / 100,
      });
      await onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
      setSaving(false);
    }
  }

  const input = "rounded-md border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 disabled:bg-slate-50 dark:disabled:bg-slate-900";

  return (
    <Modal size="lg" onClose={saving ? undefined : onClose}>
      <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Jornales y márgenes de la empresa</h2>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
        Valen para todos los proyectos. El jornal es lo que te cuesta un día de cada oficio, con cargas sociales.
        {!isAdmin && " Solo un administrador los puede cambiar."}
      </p>
      {!rates || !margins ? (
        <p className="mt-4 text-sm text-slate-500">{error ?? "Cargando…"}</p>
      ) : (
        <>
          <table className="mt-4 w-full text-sm">
            <thead className="text-left text-xs text-slate-500 dark:text-slate-400">
              <tr>
                <th className="pb-1 font-medium">Oficio</th>
                <th className="pb-1 text-right font-medium">Costo por día</th>
                <th className="pb-1 pl-3 font-medium">Actualizado</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rates.map((r, i) => (
                <tr key={i}>
                  <td className="py-1 pr-2">
                    <input value={r.trade} disabled={!isAdmin} aria-label="Oficio"
                           onChange={(e) => setRates(rates.map((x, j) => (j === i ? { ...x, trade: e.target.value } : x)))}
                           className={`${input} w-full`} />
                  </td>
                  <td className="py-1">
                    <span className="flex items-center justify-end gap-1">
                      <span className="text-xs text-slate-500">$</span>
                      <input value={r.cost} disabled={!isAdmin} inputMode="decimal" placeholder="0"
                             aria-label={`Costo por día de ${r.trade}`}
                             onChange={(e) => setRates(rates.map((x, j) => (j === i ? { ...x, cost: e.target.value } : x)))}
                             className={`${input} w-32 text-right tabular-nums`} />
                    </span>
                  </td>
                  <td className="py-1 pl-3 text-xs text-slate-500 dark:text-slate-400">
                    {r.updated_on ? new Date(r.updated_on + "T12:00").toLocaleDateString("es-AR") : "—"}
                  </td>
                  <td className="py-1 pl-2">
                    {isAdmin && (
                      <button type="button" aria-label={`Quitar ${r.trade}`} title="Quitar"
                              onClick={() => setRates(rates.filter((_, j) => j !== i))}
                              className="px-1 text-slate-400 hover:text-red-600">✕</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {isAdmin && (
            <button type="button" onClick={() => setRates([...rates, { trade: "", cost: "", updated_on: null }])}
                    className="mt-1 text-xs font-semibold text-brand-600 hover:underline dark:text-brand-400">
              + Agregar oficio
            </button>
          )}

          <h3 className="mt-5 text-sm font-semibold text-slate-800 dark:text-slate-100">Márgenes por defecto</h3>
          <div className="mt-2 flex flex-wrap gap-6 text-sm text-slate-600 dark:text-slate-300">
            {([["overhead", "Gastos generales"], ["profit", "Beneficio"]] as const).map(([k, label]) => (
              <label key={k} className="flex items-center gap-2">
                {label}
                <input value={margins[k]} disabled={!isAdmin} inputMode="decimal"
                       onChange={(e) => setMargins({ ...margins, [k]: e.target.value })}
                       className={`${input} w-16 text-right tabular-nums`} />
                %
              </label>
            ))}
          </div>
          {error && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
          <div className="mt-6 flex justify-end gap-2">
            <button type="button" onClick={onClose} disabled={saving}
                    className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">
              {isAdmin ? "Cancelar" : "Cerrar"}
            </button>
            {isAdmin && (
              <button type="button" onClick={() => void save()} disabled={saving}
                      className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50">
                {saving ? "Guardando…" : "Guardar"}
              </button>
            )}
          </div>
        </>
      )}
    </Modal>
  );
}

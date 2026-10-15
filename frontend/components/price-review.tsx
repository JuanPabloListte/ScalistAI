"use client";

import { useMemo, useState } from "react";

import type {
  BudgetItem,
  PriceLine,
  ProjectBudgetView,
} from "@/lib/api";

const UNIT: Record<string, string> = { kg: "kg", m3: "m³", m2: "m²", m: "m", l: "l", u: "u" };
const SALE_UNITS = ["u", "kg", "m3", "m2", "m", "l"];

const money = (n: number | null | undefined) =>
  n == null
    ? "—"
    : n.toLocaleString("es-AR", { style: "currency", currency: "ARS", maximumFractionDigits: 0 });
const num = (n: number | null | undefined, d = 2) =>
  n == null ? "—" : n.toLocaleString("es-AR", { maximumFractionDigits: d });

export function presentationLabel(p: { amount: number; unit: string }) {
  if (p.unit === "u" && p.amount === 1) return "por unidad";
  return `x ${num(p.amount)} ${UNIT[p.unit] ?? p.unit}`;
}

const STATUS: Record<string, { label: string; cls: string }> = {
  ok: { label: "Con precio", cls: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300" },
  sin_precio: { label: "Sin precio", cls: "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300" },
  sin_medida: { label: "El modelo no lo trae", cls: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400" },
  unidad_incompatible: { label: "Unidad incompatible", cls: "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300" },
  regla_invalida: { label: "Regla inválida", cls: "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300" },
};

/** Tabla de revisión: medidas del IFC × reglas × renglones del proveedor.
 *  Los cambios (elegir otro renglón, corregir una presentación) se avisan por
 *  callbacks y el padre los persiste. */
export function PriceReview({
  view,
  busy,
  onOverride,
  onPatchLine,
}: {
  view: ProjectBudgetView;
  busy?: boolean;
  onOverride: (key: string, row: number | null | "auto") => void;
  onPatchLine: (row: number, patch: { amount: number; unit: string } | null) => void;
}) {
  const budget = view.budget;
  const lines = view.price_list?.lines ?? [];
  const [showLines, setShowLines] = useState(false);
  const [showMeasures, setShowMeasures] = useState(false);

  const groups = useMemo(() => {
    const g: { label: string; items: BudgetItem[] }[] = [];
    for (const it of budget?.items ?? []) {
      let grp = g.find((x) => x.label === it.measure_label);
      if (!grp) g.push((grp = { label: it.measure_label, items: [] }));
      grp.items.push(it);
    }
    return g;
  }, [budget]);

  if (!budget) return null;
  const usedRows = new Set(budget.shopping_list.map((s) => s.row));

  return (
    <div className={`flex flex-col gap-5 ${busy ? "pointer-events-none opacity-60" : ""}`}>
      <div className="grid gap-3 sm:grid-cols-4">
        <Kpi label="Materiales (neto)" value={money(budget.totals.net)} />
        <Kpi label={`IVA ${Math.round(budget.totals.iva_rate * 100)}%`} value={money(budget.totals.iva)} />
        <Kpi label="Total con IVA" value={money(budget.totals.total)} strong />
        <Kpi
          label="Ítems"
          value={`${budget.counts.ok} con precio`}
          sub={[
            budget.counts.sin_precio ? `${budget.counts.sin_precio} sin precio` : null,
            budget.counts.sin_medida ? `${budget.counts.sin_medida} sin medida` : null,
          ].filter(Boolean).join(" · ") || undefined}
        />
      </div>

      {groups.map((g) => (
        <section key={g.label}>
          <h3 className="mb-1.5 text-sm font-semibold text-slate-800 dark:text-slate-200">{g.label}</h3>
          <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                <tr>
                  <th className="px-3 py-2 font-medium">Producto</th>
                  <th className="px-3 py-2 text-right font-medium">Cantidad</th>
                  <th className="px-3 py-2 font-medium">Renglón del proveedor</th>
                  <th className="px-3 py-2 text-right font-medium">Unidades</th>
                  <th className="px-3 py-2 text-right font-medium">Subtotal</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {g.items.map((it) => (
                  <ItemRow key={it.key} item={it} lines={lines} onOverride={onOverride} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}

      <section>
        <h3 className="mb-1.5 text-sm font-semibold text-slate-800 dark:text-slate-200">
          Lista de compras <span className="font-normal text-slate-400">· unidades enteras por renglón</span>
        </h3>
        <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
          <table className="w-full min-w-[600px] text-sm">
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {budget.shopping_list.map((s) => (
                <tr key={s.row}>
                  <td className="px-3 py-2">
                    {s.description}
                    <span className="ml-2 text-xs text-slate-400">{presentationLabel(s.presentation)}</span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.units_to_buy}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-500">{money(s.unit_price_net)}</td>
                  <td className="px-3 py-2 text-right font-medium tabular-nums">{money(s.subtotal)}</td>
                </tr>
              ))}
              {budget.shopping_list.length === 0 && (
                <tr><td className="px-3 py-3 text-xs text-slate-400">Ningún ítem tiene precio todavía.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <Collapsible
        open={showLines}
        onToggle={() => setShowLines((v) => !v)}
        title={`Renglones leídos del archivo (${lines.length})`}
        hint={`${lines.length - usedRows.size} sin usar · corregí la presentación si se leyó mal`}
      >
        <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
          <table className="w-full min-w-[640px] text-sm">
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {lines.map((ln) => (
                <LineRow key={ln.row} line={ln} used={usedRows.has(ln.row)} onPatch={onPatchLine} />
              ))}
            </tbody>
          </table>
        </div>
      </Collapsible>

      {view.measures && (
        <Collapsible
          open={showMeasures}
          onToggle={() => setShowMeasures((v) => !v)}
          title="Medidas del modelo"
          hint="lo que el presupuesto toma del IFC"
        >
          <div className="grid gap-x-8 gap-y-1 text-sm sm:grid-cols-2">
            {view.measures.measures.map((m) => (
              <div key={m.key} className="flex justify-between gap-3 border-b border-slate-100 py-1 dark:border-slate-800">
                <span className="text-slate-600 dark:text-slate-400">{m.label}</span>
                <span className="tabular-nums">{num(m.value, 1)} {UNIT[m.unit] ?? m.unit}</span>
              </div>
            ))}
            {view.measures.rebar_by_diameter.map((r) => (
              <div key={r.diameter_mm} className="flex justify-between gap-3 border-b border-slate-100 py-1 pl-4 dark:border-slate-800">
                <span className="text-slate-500">Hierro Ø{num(r.diameter_mm, 1)}</span>
                <span className="tabular-nums">{num(r.kg, 1)} kg</span>
              </div>
            ))}
          </div>
          {view.measures.warnings.length > 0 && (
            <ul className="mt-3 list-disc pl-5 text-xs text-amber-700 dark:text-amber-300">
              {view.measures.warnings.map((w) => <li key={w}>{w}</li>)}
            </ul>
          )}
        </Collapsible>
      )}
    </div>
  );
}

function ItemRow({
  item: it,
  lines,
  onOverride,
}: {
  item: BudgetItem;
  lines: PriceLine[];
  onOverride: (key: string, row: number | null | "auto") => void;
}) {
  const st = STATUS[it.status] ?? STATUS.sin_precio;
  const candidates = [it.line, ...it.alternatives].filter(Boolean).map((l) => l!.row);
  const others = lines.filter((l) => !candidates.includes(l.row));
  const value = it.line ? String(it.line.row) : "none";
  const formula =
    it.measure === "armadura_kg"
      ? `${num(it.measure_value, 1)} kg del modelo`
      : `${num(it.measure_value, 1)} ${UNIT[it.measure_unit] ?? it.measure_unit} × ${num(it.factor, 4)} ${UNIT[it.unit] ?? it.unit}`;

  return (
    <tr className="align-top">
      <td className="px-3 py-2">
        <div className="font-medium text-slate-800 dark:text-slate-200">{it.label}</div>
        <div className="text-xs text-slate-400" title={it.notes ?? undefined}>
          {formula}
          {it.waste_pct ? ` + ${num(it.waste_pct)}%` : ""}
        </div>
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
        {it.quantity == null ? "—" : `${num(it.quantity)} ${UNIT[it.unit] ?? it.unit}`}
      </td>
      <td className="px-3 py-2">
        {it.status === "sin_medida" ? (
          <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${st.cls}`}>{st.label}</span>
        ) : (
          <div className="flex flex-col gap-1">
            <select
              value={value}
              onChange={(e) => {
                const v = e.target.value;
                onOverride(it.key, v === "auto" ? "auto" : v === "none" ? null : Number(v));
              }}
              className="w-full max-w-md rounded-md border border-slate-300 bg-white px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            >
              {it.manual && <option value="auto">↺ Volver a la elección automática</option>}
              {it.line && (
                <option value={it.line.row}>
                  {it.line.description} · {money(it.line.unit_price_net)}
                </option>
              )}
              {it.alternatives.length > 0 && (
                <optgroup label="Otros candidatos">
                  {it.alternatives.map((a) => (
                    <option key={a.row} value={a.row}>
                      {a.description} · {money(a.unit_price_net)}
                    </option>
                  ))}
                </optgroup>
              )}
              <option value="none">— Sin precio —</option>
              {others.length > 0 && (
                <optgroup label="Otro renglón del archivo">
                  {others.map((l) => (
                    <option key={l.row} value={l.row}>
                      {l.description} · {money(l.unit_price_net)}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
            <div className="flex items-center gap-2">
              <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${st.cls}`}>{st.label}</span>
              {it.manual && <span className="text-[11px] text-slate-400">elegido a mano</span>}
              {it.line && (
                <span className="text-[11px] text-slate-400">{presentationLabel(it.line.presentation)}</span>
              )}
            </div>
          </div>
        )}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{num(it.units_to_buy)}</td>
      <td className="whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums">{money(it.subtotal)}</td>
    </tr>
  );
}

function LineRow({
  line: ln,
  used,
  onPatch,
}: {
  line: PriceLine;
  used: boolean;
  onPatch: (row: number, patch: { amount: number; unit: string } | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState(String(ln.presentation.amount));
  const [unit, setUnit] = useState(ln.presentation.unit);

  return (
    <tr className={used ? "" : "text-slate-400"}>
      <td className="px-3 py-1.5 text-xs text-slate-400">{ln.code ?? ln.row}</td>
      <td className="px-3 py-1.5">{ln.description}</td>
      <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">{money(ln.unit_price_net)}</td>
      <td className="whitespace-nowrap px-3 py-1.5">
        {editing ? (
          <form
            className="flex items-center gap-1"
            onSubmit={(e) => {
              e.preventDefault();
              const a = Number(amount.replace(",", "."));
              if (a > 0) onPatch(ln.row, { amount: a, unit });
              setEditing(false);
            }}
          >
            <span className="text-xs">x</span>
            <input
              autoFocus
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="w-16 rounded border border-slate-300 px-1.5 py-0.5 text-right text-xs dark:border-slate-700 dark:bg-slate-950"
            />
            <select
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
              className="rounded border border-slate-300 px-1 py-0.5 text-xs dark:border-slate-700 dark:bg-slate-950"
            >
              {SALE_UNITS.map((u) => <option key={u} value={u}>{UNIT[u]}</option>)}
            </select>
            <button type="submit" className="text-xs font-semibold text-brand-600">OK</button>
          </form>
        ) : (
          <button
            type="button"
            onClick={() => setEditing(true)}
            title="Corregir la presentación"
            className="text-xs hover:underline"
          >
            {presentationLabel(ln.presentation)}
            {ln.patched && <span className="ml-1 text-amber-600">(corregido)</span>}
          </button>
        )}
        {ln.patched && !editing && (
          <button type="button" onClick={() => onPatch(ln.row, null)} className="ml-2 text-[11px] text-slate-400 hover:underline">
            deshacer
          </button>
        )}
      </td>
      <td className="whitespace-nowrap px-3 py-1.5 text-right text-[11px]">{used ? "usado" : "sin usar"}</td>
    </tr>
  );
}

function Kpi({ label, value, sub, strong }: { label: string; value: string; sub?: string; strong?: boolean }) {
  return (
    <div className="rounded-lg border border-slate-200 px-3 py-2.5 dark:border-slate-700">
      <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
      <div className={`mt-0.5 tabular-nums ${strong ? "text-lg font-bold text-brand dark:text-sky-400" : "text-base font-semibold"}`}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-amber-600 dark:text-amber-400">{sub}</div>}
    </div>
  );
}

function Collapsible({
  open,
  onToggle,
  title,
  hint,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <button type="button" onClick={onToggle} className="flex w-full items-baseline gap-2 text-left text-sm font-semibold text-slate-800 dark:text-slate-200">
        <span className="text-slate-400">{open ? "▾" : "▸"}</span>
        {title}
        {hint && <span className="text-xs font-normal text-slate-400">· {hint}</span>}
      </button>
      {open && <div className="mt-2">{children}</div>}
    </section>
  );
}

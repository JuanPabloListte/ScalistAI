"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  api,
  isUnauthorized,
  type RuleInput,
  type RuleMode,
  type RuleSet,
  type RuleSetsMeta,
  type RuleUnit,
  type User,
} from "@/lib/api";

const UNIT_LABEL: Record<string, string> = {
  kg: "kg", m3: "m³", m2: "m²", m: "m", l: "litros", u: "unidades",
};

// Nombre corto de cada medida para las pestañas.
const TAB_LABEL: Record<string, string> = {
  muro_m2: "Muros", columna_m3: "Columnas", viga_ml: "Vigas", riostra_ml: "Riostras",
  techo_m2: "Techo", sup_cubierta_m2: "Pisos", cielorraso_m2: "Cielorrasos", armadura_kg: "Armadura",
};

// Fila en edición: listas de palabras como texto ("cemento, portland") y el
// factor como string para no pelear con el input numérico mientras se tipea.
type DraftRule = {
  uid: string;
  measure: string;
  label: string;
  keywords: string;
  exclude: string;
  unit: RuleUnit;
  factor: string;
  mode: RuleMode;
  waste: string;
  notes: string;
};

type Draft = { name: string; description: string; is_default: boolean; rules: DraftRule[] };

let uidSeq = 0;
const nextUid = () => `r${++uidSeq}`;

const splitList = (s: string) =>
  s.split(",").map((x) => x.trim()).filter(Boolean);

function toDraft(rs: RuleSet): Draft {
  return {
    name: rs.name,
    description: rs.description ?? "",
    is_default: rs.is_default,
    rules: rs.rules.map((r) => ({
      uid: nextUid(),
      measure: r.measure,
      label: r.label,
      keywords: r.keywords.join(", "),
      exclude: r.exclude_keywords.join(", "),
      unit: r.unit,
      factor: String(r.factor),
      mode: r.mode,
      waste: String(r.waste_pct),
      notes: r.notes ?? "",
    })),
  };
}

function toPayload(d: Draft, measureOrder: string[]) {
  // Se guardan agrupadas por medida, en el orden en que se ven.
  const order = (m: string) => {
    const i = measureOrder.indexOf(m);
    return i < 0 ? measureOrder.length : i;
  };
  const rules: RuleInput[] = [...d.rules]
    .map((r, i) => ({ r, i }))
    .sort((a, b) => order(a.r.measure) - order(b.r.measure) || a.i - b.i)
    .map(({ r }) => ({
      measure: r.measure,
      label: r.label.trim(),
      keywords: splitList(r.keywords),
      exclude_keywords: splitList(r.exclude),
      unit: r.mode === "rebar" ? "kg" : r.unit,
      factor: r.mode === "rebar" ? 1 : Number(r.factor.replace(",", ".")) || 0,
      mode: r.mode,
      waste_pct: Number(r.waste.replace(",", ".")) || 0,
      notes: r.notes.trim() || null,
    }));
  return {
    name: d.name.trim(),
    description: d.description.trim() || null,
    is_default: d.is_default,
    rules,
  };
}

function validate(d: Draft): string | null {
  if (!d.name.trim()) return "El juego necesita un nombre.";
  for (const r of d.rules) {
    if (!r.label.trim()) return "Hay una regla sin nombre de producto.";
    if (splitList(r.keywords).length === 0)
      return `"${r.label || "Regla"}": falta al menos una palabra para buscar en el PDF.`;
    if (r.mode !== "rebar" && !(Number(r.factor.replace(",", ".")) >= 0))
      return `"${r.label}": la cantidad tiene que ser un número.`;
  }
  return null;
}

export default function RuleSetEditorPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);

  const [me, setMe] = useState<User | null>(null);
  const [meta, setMeta] = useState<RuleSetsMeta | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [original, setOriginal] = useState<RuleSet | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.getMe(), api.getRuleSetsMeta(), api.getRuleSet(id)])
      .then(([m, mt, rs]) => {
        setMe(m);
        setMeta(mt);
        setOriginal(rs);
        setDraft(toDraft(rs));
      })
      .catch((err: unknown) => {
        if (isUnauthorized(err)) router.push("/login");
        else setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoading(false));
  }, [id, router]);

  const isAdmin = !!(me?.is_superadmin || me?.role === "admin");
  // El estándar del sistema solo lo edita el superadmin; los de la org, un admin.
  const canEdit = original?.is_system ? !!me?.is_superadmin : isAdmin;
  const [query, setQuery] = useState("");
  const [measureFilter, setMeasureFilter] = useState("");
  const q = query.trim().toLowerCase();
  const filtering = !!q || !!measureFilter;
  const matches = (r: DraftRule) =>
    (!measureFilter || r.measure === measureFilter) &&
    (!q || [r.label, r.keywords, r.exclude, r.notes].some((t) => t.toLowerCase().includes(q)));
  const measureOrder = useMemo(() => meta?.measures.map((m) => m.key) ?? [], [meta]);
  const savedPayload = useMemo(
    () => (original ? JSON.stringify(toPayload(toDraft(original), measureOrder)) : ""),
    [original, measureOrder],
  );
  const dirty = !!draft && JSON.stringify(toPayload(draft, measureOrder)) !== savedPayload;

  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  function patchRule(uid: string, patch: Partial<DraftRule>) {
    setDraft((d) => d && { ...d, rules: d.rules.map((r) => (r.uid === uid ? { ...r, ...patch } : r)) });
    setNotice(null);
  }

  function addRule(measure: string) {
    setDraft((d) => d && {
      ...d,
      rules: [...d.rules, {
        uid: nextUid(), measure, label: "", keywords: "", exclude: "", unit: "kg",
        factor: "1", mode: "fixed", waste: "0", notes: "",
      }],
    });
  }

  async function save() {
    if (!draft || !meta) return;
    const v = validate(draft);
    if (v) {
      setError(v);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const rs = await api.updateRuleSet(id, toPayload(draft, measureOrder));
      setOriginal(rs);
      setDraft(toDraft(rs));
      setNotice("Cambios guardados.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-10">
        <p className="text-slate-500 dark:text-slate-400">Cargando...</p>
      </main>
    );
  }
  if (!draft || !meta) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-10">
        <Link href="/reglas" className="text-sm text-brand hover:underline dark:text-sky-400">← Reglas de cómputo</Link>
        <p className="mt-4 text-sm text-red-600 dark:text-red-400">{error ?? "No encontrado"}</p>
      </main>
    );
  }

  const inputCls =
    "w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-800 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 disabled:bg-slate-50 disabled:text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-900";

  return (
    <main className="mx-auto max-w-6xl px-6 pb-28 pt-10">
      <Link href="/reglas" className="text-sm text-brand hover:underline dark:text-sky-400">
        ← Reglas de cómputo
      </Link>

      <section className="surface mt-3 grid gap-4 p-5 md:grid-cols-[1fr_2fr]">
        <label className="block text-sm">
          <span className="font-semibold text-slate-700 dark:text-slate-300">Nombre</span>
          <input
            value={draft.name}
            disabled={!canEdit}
            maxLength={120}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            className={`mt-1 ${inputCls}`}
          />
        </label>
        <label className="block text-sm">
          <span className="font-semibold text-slate-700 dark:text-slate-300">Descripción</span>
          <input
            value={draft.description}
            disabled={!canEdit}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            className={`mt-1 ${inputCls}`}
          />
        </label>
      </section>

      {/* TABS por medida */}
      <div className="mt-6 flex gap-4 overflow-x-auto border-b border-slate-200 dark:border-slate-800">
        {[{ key: "", label: "Todas", n: draft.rules.length },
          ...meta.measures
            .map((m) => ({ key: m.key, label: TAB_LABEL[m.key] ?? m.label,
                           n: draft.rules.filter((r) => r.measure === m.key).length }))
            .filter((t) => t.n > 0 || canEdit),
        ].map((t) => {
          const active = measureFilter === t.key;
          return (
            <button key={t.key || "all"} type="button" onClick={() => setMeasureFilter(t.key)}
                    className={`whitespace-nowrap border-b-2 px-1 pb-2 text-sm font-medium transition ${
              active
                ? "border-brand-500 text-brand-600 dark:border-brand-400 dark:text-brand-400"
                : "border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-300"
            }`}>
              {t.label} <span className="text-xs text-slate-400">{t.n}</span>
            </button>
          );
        })}
      </div>

      <div className="mt-4 flex items-center justify-between gap-4">
        <input
          type="search"
          placeholder="Filtrar..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full max-w-sm rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:focus:border-brand-400 dark:focus:ring-brand-400/20"
        />
        {filtering && (
          <span className="shrink-0 text-xs text-slate-500 dark:text-slate-400">
            {draft.rules.filter(matches).length} de {draft.rules.length} reglas
          </span>
        )}
      </div>

      <p className="mt-6 text-xs text-slate-500 dark:text-slate-400">
        Cada regla toma una medida del modelo y la convierte en un producto. El producto se busca en
        el PDF/Excel del proveedor por las palabras clave (separadas por coma: alcanza con que coincida
        una; dentro de cada una tienen que aparecer todas las palabras). Si hay varios candidatos se
        usa el más barato, y en la revisión del proyecto se puede cambiar.
      </p>

      {meta.measures.map((m) => {
        const all = draft.rules.filter((r) => r.measure === m.key);
        const rules = all.filter(matches);
        if (measureFilter && measureFilter !== m.key) return null;
        if (q && rules.length === 0) return null;
        if (!canEdit && all.length === 0) return null;
        return (
          <section key={m.key} className="mt-6">
            <h2 className="mb-2 flex items-baseline justify-between gap-2 text-sm font-semibold text-slate-800 dark:text-slate-200">
              <span>
                {m.label} <span className="font-normal text-slate-400">· por {UNIT_LABEL[m.unit] ?? m.unit}</span>
              </span>
              {canEdit && (
                <button
                  type="button"
                  onClick={() => addRule(m.key)}
                  className="text-xs font-semibold text-brand-600 hover:underline dark:text-brand-400"
                >
                  + Agregar regla
                </button>
              )}
            </h2>
            {rules.length === 0 ? (
              <p className="surface-soft px-4 py-3 text-xs text-slate-400">Sin reglas: esta medida no suma al presupuesto.</p>
            ) : (
              <div className="surface divide-y divide-slate-100 dark:divide-slate-800">
                {rules.map((r) => (
                  <RuleRow
                    key={r.uid}
                    rule={r}
                    measureUnit={m.unit}
                    meta={meta}
                    disabled={!canEdit}
                    inputCls={inputCls}
                    onChange={(p) => patchRule(r.uid, p)}
                    onDelete={() => setDraft({ ...draft, rules: draft.rules.filter((x) => x.uid !== r.uid) })}
                  />
                ))}
              </div>
            )}
          </section>
        );
      })}

      {canEdit && (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white/90 py-3 pl-16 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90">
          <div className="mx-auto flex max-w-6xl items-center justify-end gap-3 px-6">
            {error && <p className="mr-auto text-sm text-red-600 dark:text-red-400">{error}</p>}
            {!error && notice && <p className="mr-auto text-sm text-emerald-600 dark:text-emerald-400">{notice}</p>}
            {!error && !notice && dirty && <p className="mr-auto text-sm text-amber-600 dark:text-amber-400">Hay cambios sin guardar.</p>}
            <button
              type="button"
              disabled={!dirty || saving}
              onClick={() => {
                if (original) setDraft(toDraft(original));
                setError(null);
                setNotice(null);
              }}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:hover:bg-slate-800"
            >
              Descartar
            </button>
            <button
              type="button"
              disabled={!dirty || saving}
              onClick={save}
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-40"
            >
              {saving ? "Guardando…" : "Guardar cambios"}
            </button>
          </div>
        </div>
      )}
    </main>
  );
}

function RuleRow({
  rule: r,
  measureUnit,
  meta,
  disabled,
  inputCls,
  onChange,
  onDelete,
}: {
  rule: DraftRule;
  measureUnit: string;
  meta: RuleSetsMeta;
  disabled: boolean;
  inputCls: string;
  onChange: (p: Partial<DraftRule>) => void;
  onDelete: () => void;
}) {
  const [showNotes, setShowNotes] = useState(!!r.notes);
  const rebar = r.mode === "rebar";
  const per = UNIT_LABEL[measureUnit] ?? measureUnit;

  return (
    <div className="grid gap-3 p-4 lg:grid-cols-[1.3fr_1.3fr_1fr_1.4fr_0.6fr_auto]">
      <Field label="Producto">
        <input
          value={r.label}
          disabled={disabled}
          placeholder="Ej. Cemento"
          onChange={(e) => onChange({ label: e.target.value })}
          className={inputCls}
        />
      </Field>
      <Field label="Buscar en el PDF" hint="separadas por coma">
        <input
          value={r.keywords}
          disabled={disabled}
          placeholder="cemento, cemento portland"
          onChange={(e) => onChange({ keywords: e.target.value })}
          className={inputCls}
        />
      </Field>
      <Field label="Excluir">
        <input
          value={r.exclude}
          disabled={disabled}
          placeholder="opcional"
          onChange={(e) => onChange({ exclude: e.target.value })}
          className={inputCls}
        />
      </Field>
      <Field label={rebar ? "Cantidad" : r.mode === "brick_dims" ? "Cantidad (si no trae medidas)" : "Cantidad"}>
        {rebar ? (
          <p className="py-1.5 text-xs text-slate-500 dark:text-slate-400">kg exactos del modelo, por diámetro</p>
        ) : (
          <div className="flex items-center gap-1.5">
            <input
              inputMode="decimal"
              value={r.factor}
              disabled={disabled}
              onChange={(e) => onChange({ factor: e.target.value })}
              className={`${inputCls} w-20 text-right`}
            />
            <select
              value={r.unit}
              disabled={disabled}
              onChange={(e) => onChange({ unit: e.target.value as RuleUnit })}
              className={`${inputCls} w-auto`}
            >
              {meta.units.map((u) => (
                <option key={u} value={u}>{UNIT_LABEL[u] ?? u}</option>
              ))}
            </select>
            <span className="shrink-0 text-xs text-slate-500">por {per}</span>
          </div>
        )}
      </Field>
      <Field label="Desperdicio">
        <div className="flex items-center gap-1">
          <input
            inputMode="decimal"
            value={r.waste}
            disabled={disabled}
            onChange={(e) => onChange({ waste: e.target.value })}
            className={`${inputCls} w-16 text-right`}
          />
          <span className="text-xs text-slate-500">%</span>
        </div>
      </Field>
      <div className="flex items-end justify-end gap-1">
        {!disabled && (
          <button
            type="button"
            title="Borrar regla"
            aria-label="Borrar regla"
            onClick={onDelete}
            className="rounded-md p-2 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/30"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="M19 6l-1 14H6L5 6" /></svg>
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 lg:col-span-6">
        <label className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
          Cálculo
          <select
            value={r.mode}
            disabled={disabled}
            onChange={(e) => onChange({ mode: e.target.value as RuleMode })}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          >
            {meta.modes.map((m) => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </select>
        </label>
        {showNotes ? (
          <input
            value={r.notes}
            disabled={disabled}
            placeholder="Nota: de dónde sale el valor"
            onChange={(e) => onChange({ notes: e.target.value })}
            className="min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-2 py-1 text-xs italic text-slate-500 hover:border-slate-200 focus:border-slate-300 focus:outline-none disabled:hover:border-transparent dark:text-slate-400 dark:hover:border-slate-700"
          />
        ) : (
          !disabled && (
            <button type="button" onClick={() => setShowNotes(true)} className="text-xs text-slate-400 hover:text-slate-600">
              + nota
            </button>
          )
        )}
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 text-xs">
      <span className="mb-1 block font-medium text-slate-500 dark:text-slate-400">
        {label}
        {hint && <span className="font-normal text-slate-400"> · {hint}</span>}
      </span>
      {children}
    </div>
  );
}

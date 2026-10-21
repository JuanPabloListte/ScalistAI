"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  api,
  isUnauthorized,
  type CrewMember,
  type LaborMode,
  type RuleInput,
  type RuleKind,
  type RuleMode,
  type RuleSet,
  type RuleSetsMeta,
  type RuleUnit,
  type User,
} from "@/lib/api";
import { Modal } from "@/components/modal";
import { MSG_NUM_AMBIGUO, fmtInputAR, parseNumAR } from "@/lib/format";

const UNIT_LABEL: Record<string, string> = {
  kg: "kg", m3: "m³", m2: "m²", m: "m", l: "litros", u: "unidades",
};

// Nombre corto de cada medida para las pestañas.
const TAB_LABEL: Record<string, string> = {
  muro_m2: "Muros", columna_m3: "Columnas", viga_ml: "Vigas (ml)", viga_m3: "Vigas (m³)", vigueta_ml: "Viguetas", losa_m2: "Entrepisos",
  riostra_ml: "Riostras",
  techo_m2: "Techo", sup_cubierta_m2: "Pisos", cielorraso_m2: "Cielorrasos", armadura_kg: "Armadura",
};

// Rubros sugeridos para la mano de obra (se puede escribir cualquiera).
const STAGES = [
  "Trabajos preliminares", "Movimiento de suelos", "Fundaciones", "Estructura", "Mampostería",
  "Revoques", "Cubierta", "Contrapisos y carpetas", "Pisos", "Revestimientos",
  "Cielorrasos", "Instalaciones", "Terminaciones", "Pintura",
];

// Fila en edición: listas de palabras como texto ("cemento, portland") y los
// números como string para no pelear con el input numérico mientras se tipea.
type DraftRule = {
  uid: string;
  kind: RuleKind;
  measure: string;
  label: string;
  keywords: string;
  exclude: string;
  unit: RuleUnit;
  factor: string;
  mode: RuleMode;
  waste: string;
  notes: string;
  // Mano de obra
  stage: string;
  dailyYield: string;
  laborMode: LaborMode;
  unitPrice: string;
  crew: CrewMember[];
};

// Valor numérico para el payload. Si el texto no es válido devuelve el texto tal cual
// (así `dirty` sigue viendo el cambio); `validate` lo frena antes de guardar.
const num = (s: string): number => {
  const p = parseNumAR(s);
  return p.ok ? p.value : (s as unknown as number);
};

// Lee un campo numérico: valor o mensaje de error en castellano.
function readNum(
  s: string,
  { label, obligatorio = true }: { label: string; obligatorio?: boolean },
): string | null {
  const p = parseNumAR(s);
  if (!p.ok) {
    if (p.error === "vacio") return obligatorio ? `${label} es obligatorio.` : null;
    if (p.error === "ambiguo") return `${label}: ${MSG_NUM_AMBIGUO}.`;
    return `${label} tiene que ser un número.`;
  }
  if (p.value < 0) return `${label} no puede ser negativo.`;
  return null;
}

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
      kind: r.kind ?? "material",
      stage: r.stage ?? "",
      dailyYield: r.daily_yield != null ? fmtInputAR(r.daily_yield) : "",
      laborMode: r.labor_mode ?? "unit",
      unitPrice: r.unit_price != null ? fmtInputAR(r.unit_price) : "",
      crew: (r.crew ?? []).map((c) => ({ ...c })),
      measure: r.measure,
      label: r.label,
      keywords: r.keywords.join(", "),
      exclude: r.exclude_keywords.join(", "),
      unit: r.unit,
      factor: fmtInputAR(r.factor),
      mode: r.mode,
      waste: fmtInputAR(r.waste_pct),
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
    .sort((a, b) => order(a.r.measure) - order(b.r.measure)
      || Number(a.r.kind === "labor") - Number(b.r.kind === "labor") || a.i - b.i)
    .map(({ r }): RuleInput => r.kind === "labor" ? {
      kind: "labor",
      measure: r.measure,
      label: r.label.trim(),
      keywords: [],
      exclude_keywords: [],
      unit: r.unit,
      factor: 1,
      mode: "fixed",
      waste_pct: 0,
      notes: r.notes.trim() || null,
      stage: r.stage.trim() || null,
      daily_yield: r.dailyYield.trim() ? num(r.dailyYield) : null,
      labor_mode: r.laborMode,
      unit_price: r.unitPrice.trim() ? num(r.unitPrice) : null,
      crew: r.crew.filter((c) => c.trade && c.count > 0),
    } : ({
      kind: "material",
      measure: r.measure,
      label: r.label.trim(),
      keywords: splitList(r.keywords),
      exclude_keywords: splitList(r.exclude),
      unit: r.mode === "rebar" ? "kg" : r.unit,
      factor: r.mode === "rebar" ? 1 : num(r.factor),
      mode: r.mode,
      waste_pct: num(r.waste),
      notes: r.notes.trim() || null,
      stage: r.stage.trim() || null,
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
    if (r.kind === "labor") {
      if (!r.label.trim()) return "Hay una tarea de mano de obra sin nombre.";
      const ey = readNum(r.dailyYield, { label: "El rendimiento", obligatorio: false });
      if (ey) return `"${r.label}": ${ey}`;
      const ep = readNum(r.unitPrice, { label: "El precio", obligatorio: false });
      if (ep) return `"${r.label}": ${ep}`;
      continue;
    }
    if (!r.label.trim()) return "Hay una regla sin nombre de producto.";
    if (splitList(r.keywords).length === 0)
      return `"${r.label || "Regla"}": falta al menos una palabra para buscar en el PDF.`;
    if (r.mode !== "rebar") {
      const ef = readNum(r.factor, { label: "La cantidad" });
      if (ef) return `"${r.label}": ${ef.replace("es obligatorio", "es obligatoria").replace("negativo", "negativa")}`;
    }
    const w = parseNumAR(r.waste);
    if (!w.ok && w.error === "ambiguo") return `"${r.label}": ${MSG_NUM_AMBIGUO}.`;
    if (!w.ok && w.error === "vacio") return `"${r.label}": el desperdicio es obligatorio (0 si no hay).`;
    if (!w.ok || w.value < 0 || w.value > 100) return `"${r.label}": El desperdicio va de 0 a 100 %.`;
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
  const [trades, setTrades] = useState<string[]>([]);

  useEffect(() => {
    Promise.all([api.getMe(), api.getRuleSetsMeta(), api.getRuleSet(id),
                 api.listLaborRates().catch(() => [])])
      .then(([m, mt, rs, lr]) => {
        setMe(m);
        setMeta(mt);
        setTrades(lr.map((x) => x.trade));
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
    (!q || [r.label, r.keywords, r.exclude, r.notes, r.stage].some((t) => t.toLowerCase().includes(q)));
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

  // Navegación interna con cambios sin guardar: se intercepta el clic en cualquier link
  // interno (incluida la barra lateral) y se pregunta antes de salir.
  const [pendingHref, setPendingHref] = useState<string | null>(null);
  useEffect(() => {
    if (!dirty) return;
    const h = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!a || (a.target && a.target !== "_self") || a.hasAttribute("download")) return;
      const url = new URL(a.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      if (url.pathname === window.location.pathname && url.search === window.location.search) return;
      e.preventDefault();
      e.stopPropagation();
      setPendingHref(url.pathname + url.search + url.hash);
    };
    document.addEventListener("click", h, true);
    return () => document.removeEventListener("click", h, true);
  }, [dirty]);

  function patchRule(uid: string, patch: Partial<DraftRule>) {
    setDraft((d) => d && { ...d, rules: d.rules.map((r) => (r.uid === uid ? { ...r, ...patch } : r)) });
    setNotice(null);
  }

  function addRule(measure: string, kind: RuleKind = "material") {
    const unit = (meta?.measures.find((m) => m.key === measure)?.unit ?? "m2") as RuleUnit;
    setDraft((d) => d && {
      ...d,
      rules: [...d.rules, {
        uid: nextUid(), kind, measure, label: kind === "labor" ? "Mano de obra: " : "",
        keywords: "", exclude: "", unit: kind === "labor" ? unit : "kg",
        factor: "1", mode: "fixed", waste: "0", notes: "",
        stage: "", dailyYield: "", laborMode: "unit", unitPrice: "",
        crew: [{ trade: "Oficial", count: 1 }, { trade: "Ayudante", count: 1 }],
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
      {pendingHref && (
        <Modal onClose={() => setPendingHref(null)}>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Cambios sin guardar</h2>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">Tenés cambios sin guardar. ¿Salir igual?</p>
          <div className="mt-6 flex justify-end gap-2">
            <button
              type="button"
              autoFocus
              onClick={() => setPendingHref(null)}
              className="rounded-md border border-slate-300/50 bg-white/50 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-white/80 dark:border-white/10 dark:bg-slate-900/50 dark:text-slate-200 dark:hover:bg-slate-800/80"
            >
              Seguir editando
            </button>
            <button
              type="button"
              onClick={() => {
                const href = pendingHref;
                setPendingHref(null);
                router.push(href);
              }}
              className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-700"
            >
              Salir sin guardar
            </button>
          </div>
        </Modal>
      )}
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
        Cada producto se busca en el presupuesto del proveedor por sus palabras clave; si hay varios, se usa el más barato.
        La mano de obra se cotiza por rubro: tercerizada (precio por unidad) o con cuadrilla propia (rendimiento × jornales).
      </p>
      <datalist id="rubros">
        {STAGES.map((s) => <option key={s} value={s} />)}
      </datalist>
      <datalist id="oficios">
        {trades.map((s) => <option key={s} value={s} />)}
      </datalist>

      {meta.measures.map((m) => {
        const all = draft.rules.filter((r) => r.measure === m.key);
        const rules = all.filter((r) => r.kind !== "labor" && matches(r));
        const laborRules = all.filter((r) => r.kind === "labor" && matches(r));
        if (measureFilter && measureFilter !== m.key) return null;
        if (q && rules.length + laborRules.length === 0) return null;
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
                  + Agregar material
                </button>
              )}
            </h2>
            {rules.length === 0 && laborRules.length > 0 ? null : rules.length === 0 ? (
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
            {(laborRules.length > 0 || canEdit) && measureUnitOk(m.key) && (
              <div className="mt-2">
                <div className="mb-1 flex items-baseline justify-between gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    Mano de obra
                  </span>
                  {canEdit && (
                    <button
                      type="button"
                      onClick={() => addRule(m.key, "labor")}
                      className="text-xs font-semibold text-brand-600 hover:underline dark:text-brand-400"
                    >
                      + Agregar mano de obra
                    </button>
                  )}
                </div>
                {laborRules.length > 0 && (
                  <div className="surface divide-y divide-slate-100 dark:divide-slate-800">
                    {laborRules.map((r) => (
                      <LaborRow
                        key={r.uid}
                        rule={r}
                        measureUnit={m.unit}
                        disabled={!canEdit}
                        inputCls={inputCls}
                        onChange={(p) => patchRule(r.uid, p)}
                        onDelete={() => setDraft({ ...draft, rules: draft.rules.filter((x) => x.uid !== r.uid) })}
                      />
                    ))}
                  </div>
                )}
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
        <label className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
          Rubro
          <input
            value={r.stage}
            disabled={disabled}
            list="rubros"
            placeholder="según la medida"
            onChange={(e) => onChange({ stage: e.target.value })}
            className="w-40 rounded-md border border-slate-300 bg-white px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          />
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

// La armadura se cobra dentro del H°A° de columnas, vigas y losas.
const measureUnitOk = (measure: string) => measure !== "armadura_kg";

function LaborRow({
  rule: r,
  measureUnit,
  disabled,
  inputCls,
  onChange,
  onDelete,
}: {
  rule: DraftRule;
  measureUnit: string;
  disabled: boolean;
  inputCls: string;
  onChange: (p: Partial<DraftRule>) => void;
  onDelete: () => void;
}) {
  const per = UNIT_LABEL[measureUnit] ?? measureUnit;
  const setCrew = (i: number, patch: Partial<CrewMember>) =>
    onChange({ crew: r.crew.map((c, j) => (j === i ? { ...c, ...patch } : c)) });

  return (
    <div className="grid gap-3 p-4 lg:grid-cols-[1.5fr_1fr_0.9fr_1.1fr_1.6fr_auto]">
      <Field label="Tarea">
        <input
          value={r.label}
          disabled={disabled}
          placeholder="Mano de obra: mampostería"
          onChange={(e) => onChange({ label: e.target.value })}
          className={inputCls}
        />
      </Field>
      <Field label="Rubro">
        <input
          value={r.stage}
          disabled={disabled}
          list="rubros"
          placeholder="Mampostería"
          onChange={(e) => onChange({ stage: e.target.value })}
          className={inputCls}
        />
      </Field>
      <Field label="Rendimiento" hint="por día">
        <div className="flex items-center gap-1.5">
          <input
            inputMode="decimal"
            value={r.dailyYield}
            disabled={disabled}
            placeholder="8"
            onChange={(e) => onChange({ dailyYield: e.target.value })}
            className={`${inputCls} w-16 text-right`}
          />
          <span className="shrink-0 text-xs text-slate-500">{per}</span>
        </div>
      </Field>
      <Field label="Se cotiza">
        <select
          value={r.laborMode}
          disabled={disabled}
          onChange={(e) => onChange({ laborMode: e.target.value as LaborMode })}
          className={inputCls}
        >
          <option value="unit">Tercerizado</option>
          <option value="daily">Cuadrilla propia</option>
        </select>
      </Field>
      {r.laborMode === "unit" ? (
        <Field label="Precio de referencia" hint={`sin IVA, por ${per}`}>
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-slate-500">$</span>
            <input
              inputMode="decimal"
              value={r.unitPrice}
              disabled={disabled}
              placeholder="lo carga cada proyecto"
              onChange={(e) => onChange({ unitPrice: e.target.value })}
              className={`${inputCls} w-40 text-right`}
            />
          </div>
        </Field>
      ) : (
        <Field label="Cuadrilla">
          <div className="flex flex-wrap items-center gap-1.5">
            {r.crew.map((c, i) => (
              <span key={i} className="flex items-center gap-1">
                <input
                  inputMode="decimal"
                  value={c.count ? fmtInputAR(c.count) : ""}
                  disabled={disabled}
                  aria-label="Cantidad"
                  onChange={(e) => {
                    const t = e.target.value;
                    const p = parseNumAR(t);
                    if (!t.trim()) setCrew(i, { count: 0 });
                    else if (p.ok && p.value >= 0) setCrew(i, { count: p.value });
                  }}
                  className={`${inputCls} w-10 px-1 text-right`}
                />
                <input
                  value={c.trade}
                  disabled={disabled}
                  list="oficios"
                  aria-label="Oficio"
                  onChange={(e) => setCrew(i, { trade: e.target.value })}
                  className={`${inputCls} w-28`}
                />
                {!disabled && (
                  <button type="button" aria-label="Quitar de la cuadrilla" title="Quitar"
                          onClick={() => onChange({ crew: r.crew.filter((_, j) => j !== i) })}
                          className="px-1 text-slate-400 hover:text-red-600">✕</button>
                )}
              </span>
            ))}
            {!disabled && (
              <button type="button" onClick={() => onChange({ crew: [...r.crew, { trade: "Ayudante", count: 1 }] })}
                      className="text-xs font-semibold text-brand-600 hover:underline dark:text-brand-400">
                + oficio
              </button>
            )}
          </div>
        </Field>
      )}
      <div className="flex items-end justify-end gap-1">
        {!disabled && (
          <button
            type="button"
            title="Borrar tarea"
            aria-label="Borrar tarea"
            onClick={onDelete}
            className="rounded-md p-2 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/30"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="M19 6l-1 14H6L5 6" /></svg>
          </button>
        )}
      </div>
      {(r.notes || !disabled) && (
        <input
          value={r.notes}
          disabled={disabled}
          placeholder="Nota: de dónde sale el valor"
          onChange={(e) => onChange({ notes: e.target.value })}
          className="min-w-0 rounded-md border border-transparent bg-transparent px-2 py-1 text-xs italic text-slate-500 hover:border-slate-200 focus:border-slate-300 focus:outline-none disabled:hover:border-transparent lg:col-span-6 dark:text-slate-400 dark:hover:border-slate-700"
        />
      )}
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

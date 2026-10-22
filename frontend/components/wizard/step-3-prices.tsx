"use client";

import { useCallback, useEffect, useState } from "react";

import { PriceReview, type ReviewFilter } from "@/components/price-review";
import {
  api,
  ApiError,
  type IvaMode,
  type Project,
  type ProjectBudgetView,
  type RuleSet,
} from "@/lib/api";

const ACCEPT = ".pdf,.xlsx,.xlsm,.csv,application/pdf";
const MAX_BYTES = 15 * 1024 * 1024;

/** Paso "Precios" del wizard: el panel + navegación. */
export function Step3Prices({
  project,
  onSaved,
  onBack,
}: {
  project: Project;
  onSaved: () => void;
  onBack: () => void;
}) {
  return (
    <ProjectPricesPanel
      projectId={project.id}
      showShoppingList={false}
      renderFooter={({ hasList, working, noAccess }) => (
        <div className="mt-2 flex items-center justify-between">
          <button
            type="button"
            onClick={onBack}
            disabled={working}
            className="text-sm text-slate-500 hover:text-slate-900 disabled:opacity-50 dark:text-slate-400 dark:hover:text-slate-100"
          >
            ← Volver
          </button>
          <div className="flex items-center gap-4">
            {!hasList && !noAccess && (
              <button
                type="button"
                onClick={onSaved}
                className="text-sm text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
              >
                Omitir por ahora
              </button>
            )}
            <button
              type="button"
              onClick={onSaved}
              disabled={(!hasList && !noAccess) || working}
              title={hasList || noAccess ? "" : "Subí el presupuesto del proveedor para continuar"}
              className="rounded-md bg-brand px-5 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
            >
              Siguiente →
            </button>
          </div>
        </div>
      )}
    />
  );
}

/** Presupuesto del proveedor (PDF/Excel) + juego de reglas, con la revisión
 *  del cruce contra el modelo IFC. Lo usan el wizard y la página Presupuesto. */
export function ProjectPricesPanel({
  projectId,
  showIntro = true,
  showTotals = true,
  showShoppingList = true,
  renderFooter,
  onViewChange,
  onNoAccess,
  viewOverride,
  filter,
}: {
  projectId: number;
  showIntro?: boolean;
  /** false cuando la página ya muestra los totales (Presupuesto). */
  showTotals?: boolean;
  showShoppingList?: boolean;
  renderFooter?: (s: { hasList: boolean; working: boolean; noAccess: boolean }) => React.ReactNode;
  onViewChange?: (v: ProjectBudgetView) => void;
  /** Se llama si el rol del proyecto no ve la información económica (403). */
  onNoAccess?: () => void;
  /** Vista actualizada desde afuera (p. ej. al cambiar la mano de obra). */
  viewOverride?: ProjectBudgetView | null;
  /** Filtro de la revisión (solo Presupuesto). */
  filter?: ReviewFilter;
}) {
  const [view, setView] = useState<ProjectBudgetView | null>(null);

  useEffect(() => {
    if (viewOverride) setView(viewOverride);
  }, [viewOverride]);
  const [ruleSets, setRuleSets] = useState<RuleSet[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Rol sin acceso a lo económico (capataz/comitente): no es un error, solo no hay nada que cargar.
  const [noAccess, setNoAccess] = useState(false);

  useEffect(() => {
    if (view) onViewChange?.(view);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  useEffect(() => {
    Promise.all([api.getProjectPriceList(projectId), api.listRuleSets().catch(() => [] as RuleSet[])])
      .then(([v, rs]) => {
        setView(v);
        setRuleSets(rs);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 403) {
          setNoAccess(true);
          onNoAccess?.();
        } else {
          setError(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => setLoading(false));
  }, [projectId]);

  // Mientras el IFC se procesa no hay medidas: re-consultar hasta que esté.
  useEffect(() => {
    if (view?.model_status !== "processing") return;
    const t = setTimeout(() => {
      api.getProjectPriceList(projectId).then(setView).catch(() => {});
    }, 3000);
    return () => clearTimeout(t);
  }, [projectId, view]);

  const patch = useCallback(
    async (payload: Parameters<typeof api.patchProjectPriceList>[1]) => {
      setBusy(true);
      setError(null);
      try {
        setView(await api.patchProjectPriceList(projectId, payload));
      } catch (e) {
        setError(e instanceof Error ? e.message : "No se pudo guardar");
      } finally {
        setBusy(false);
      }
    },
    [projectId],
  );

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!/\.(pdf|xlsx|xlsm|csv)$/i.test(file.name)) {
      setError("Subí el presupuesto en PDF, Excel (.xlsx) o CSV.");
      return;
    }
    if (file.size > MAX_BYTES) {
      setError("El archivo supera los 15 MB.");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      setView(await api.uploadProjectPriceList(projectId, file, view?.rule_set?.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo leer el archivo");
    } finally {
      setUploading(false);
    }
  }

  if (loading) return <p className="text-sm text-slate-500">Cargando…</p>;

  if (noAccess) {
    return (
      <div className="flex flex-col gap-4">
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Tu rol en este proyecto no ve la información económica.
        </p>
        {renderFooter?.({ hasList: false, working: false, noAccess: true })}
      </div>
    );
  }

  const pl = view?.price_list;
  const overrides = pl?.overrides ?? {};
  const patches = pl?.line_patches ?? {};

  return (
    <div className="flex flex-col gap-4">
      {showIntro && <div>
        <h2 className="text-lg font-semibold">Presupuesto del proveedor</h2>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
          Subí el presupuesto del corralón en <strong>PDF o Excel</strong>. Lo cruzamos con el modelo
          IFC usando las <a href="/reglas" target="_blank" className="text-brand hover:underline dark:text-sky-400">reglas de cómputo</a>:
          cuánto cemento, arena, ladrillos y hierro lleva la obra, y a qué precio.
        </p>
      </div>}

      {pl ? (
        <div className="grid gap-px overflow-hidden rounded-xl border border-slate-200 bg-slate-200 dark:border-slate-700 dark:bg-slate-700 grid-cols-1 md:grid-cols-[1.4fr_1fr_1fr] [&>*]:min-w-0">
          <Field label="Archivo del proveedor">
            <div className="flex items-start gap-3">
              <FileIcon />
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-slate-900 dark:text-slate-100" title={pl.filename}>
                  {pl.filename}
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {[pl.supplier, pl.document_date && new Date(pl.document_date + "T12:00").toLocaleDateString("es-AR"),
                    `${pl.lines.length} renglones`].filter(Boolean).join(" · ")}
                </div>
                <FilePicker label={uploading ? "Leyendo…" : "Reemplazar archivo"} disabled={uploading || busy} onChange={handleFile} small />
              </div>
            </div>
          </Field>
          <Field label="Reglas de cómputo">
            <RuleSetSelect ruleSets={ruleSets} value={view?.rule_set?.id} disabled={busy || uploading}
                           onChange={(id) => patch({ rule_set_id: id })} />
            <a href="/reglas" target="_blank" className="mt-1.5 inline-block text-xs text-brand hover:underline dark:text-sky-400">
              Ver las reglas ↗
            </a>
          </Field>
          <Field label="IVA de los precios">
            <Select
              value={pl.iva_mode}
              disabled={busy || uploading}
              onChange={(v) => patch({ iva_mode: v as IvaMode })}
              options={[
                { value: "auto", label: "Detectar automáticamente" },
                { value: "included", label: "Incluyen IVA" },
                { value: "excluded", label: "No incluyen IVA" },
              ]}
            />
            <p className="mt-1.5 text-xs text-slate-500 dark:text-slate-400">
              {pl.iva_mode === "auto"
                ? <>Detectado: <strong className="font-medium text-slate-700 dark:text-slate-300">{pl.iva.included ? "con IVA" : "sin IVA"}</strong> · {pl.iva.method.replace(/^aritmética: /, "")}</>
                : pl.iva.included ? "Se descuenta el 21% para guardar precios netos." : "Se usan tal cual, como precios netos."}
            </p>
          </Field>
        </div>
      ) : (
        <>
          <div className="max-w-sm">
            <Field label="Reglas de cómputo" bare>
              <RuleSetSelect ruleSets={ruleSets} value={view?.rule_set?.id} disabled={busy || uploading}
                             onChange={(id) => patch({ rule_set_id: id })} />
            </Field>
          </div>
          <FilePicker
            label={uploading ? "Leyendo el archivo…" : "Hacé clic para elegir el presupuesto (PDF, Excel o CSV)"}
            disabled={uploading}
            onChange={handleFile}
          />
        </>
      )}

      {pl && pl.warnings.length > 0 && (
        <ul className="list-disc rounded-md border border-amber-200 bg-amber-50 py-2 pl-8 pr-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
          {pl.warnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}

      {pl && view?.model_status === "processing" && (
        <p className="rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-300">
          El modelo IFC todavía se está procesando. El presupuesto aparece acá apenas termine.
        </p>
      )}
      {pl && (view?.model_status === "error" || view?.model_status === "missing") && (
        <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          No hay un modelo IFC procesado: volvé al paso anterior y subilo para calcular el presupuesto.
        </p>
      )}

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      {view?.budget && (
        <PriceReview
          view={view}
          busy={busy}
          showTotals={showTotals}
          showShoppingList={showShoppingList}
          filter={filter}
          onOverride={(key, row) => {
            const next = { ...overrides };
            if (row === "auto") delete next[key];
            else next[key] = row;
            patch({ overrides: next });
          }}
          onPatchLine={(row, p) => {
            const next = { ...patches };
            if (p) next[String(row)] = p;
            else delete next[String(row)];
            patch({ line_patches: next });
          }}
        />
      )}

      {renderFooter?.({ hasList: !!pl, working: uploading || busy, noAccess: false })}
    </div>
  );
}

function Field({ label, bare, children }: { label: string; bare?: boolean; children: React.ReactNode }) {
  return (
    <div className={bare ? "" : "bg-white p-4 dark:bg-slate-800"}>
      <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </div>
      {children}
    </div>
  );
}

function Select({
  value,
  options,
  disabled,
  onChange,
}: {
  value: string;
  options: { value: string; label: string }[];
  disabled?: boolean;
  onChange: (v: string) => void;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 w-full cursor-pointer appearance-none rounded-lg border border-slate-300 bg-white pl-3 pr-9 text-sm text-slate-900 transition hover:border-slate-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:hover:border-slate-500"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      <svg className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="m6 9 6 6 6-6" />
      </svg>
    </div>
  );
}

function RuleSetSelect({
  ruleSets,
  value,
  disabled,
  onChange,
}: {
  ruleSets: RuleSet[];
  value: number | undefined;
  disabled?: boolean;
  onChange: (id: number) => void;
}) {
  return (
    <Select
      value={value != null ? String(value) : ""}
      disabled={disabled}
      onChange={(v) => onChange(Number(v))}
      options={ruleSets.map((rs) => ({
        value: String(rs.id),
        label: rs.name,
      }))}
    />
  );
}

function FileIcon() {
  return (
    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-300">
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <path d="M14 2v6h6" />
        <path d="M8 13h8M8 17h5" />
      </svg>
    </div>
  );
}

function FilePicker({
  label,
  disabled,
  onChange,
  small,
}: {
  label: string;
  disabled: boolean;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  small?: boolean;
}) {
  return (
    <label
      className={
        small
          ? `mt-1.5 inline-block cursor-pointer text-xs font-medium text-brand hover:underline dark:text-sky-400 ${disabled ? "pointer-events-none opacity-50" : ""}`
          : `flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed px-6 py-10 text-center transition ${
              disabled
                ? "border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900"
                : "border-slate-300 hover:border-brand dark:border-slate-600 dark:hover:border-sky-400"
            }`
      }
    >
      <input type="file" accept={ACCEPT} onChange={onChange} disabled={disabled} className="hidden" />
      <span className={small ? "" : "font-medium"}>{label}</span>
      {!small && (
        <span className="text-xs text-slate-500 dark:text-slate-400">
          PDF con texto (no escaneado), Excel o CSV · máx 15 MB
        </span>
      )}
    </label>
  );
}

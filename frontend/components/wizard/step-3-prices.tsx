"use client";

import { useCallback, useEffect, useState } from "react";

import { PriceReview } from "@/components/price-review";
import {
  api,
  type IvaMode,
  type Project,
  type ProjectBudgetView,
  type RuleSet,
} from "@/lib/api";

const ACCEPT = ".pdf,.xlsx,.xlsm,.csv,application/pdf";
const MAX_BYTES = 15 * 1024 * 1024;

/** Paso "Precios": presupuesto del proveedor (PDF/Excel) + juego de reglas,
 *  con la revisión del cruce contra el modelo IFC. */
export function Step3Prices({
  project,
  onSaved,
  onBack,
}: {
  project: Project;
  onSaved: () => void;
  onBack: () => void;
}) {
  const [view, setView] = useState<ProjectBudgetView | null>(null);
  const [ruleSets, setRuleSets] = useState<RuleSet[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.getProjectPriceList(project.id), api.listRuleSets()])
      .then(([v, rs]) => {
        setView(v);
        setRuleSets(rs);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [project.id]);

  // Mientras el IFC se procesa no hay medidas: re-consultar hasta que esté.
  useEffect(() => {
    if (view?.model_status !== "processing") return;
    const t = setTimeout(() => {
      api.getProjectPriceList(project.id).then(setView).catch(() => {});
    }, 3000);
    return () => clearTimeout(t);
  }, [project.id, view]);

  const patch = useCallback(
    async (payload: Parameters<typeof api.patchProjectPriceList>[1]) => {
      setBusy(true);
      setError(null);
      try {
        setView(await api.patchProjectPriceList(project.id, payload));
      } catch (e) {
        setError(e instanceof Error ? e.message : "No se pudo guardar");
      } finally {
        setBusy(false);
      }
    },
    [project.id],
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
      setView(await api.uploadProjectPriceList(project.id, file, view?.rule_set?.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo leer el archivo");
    } finally {
      setUploading(false);
    }
  }

  if (loading) return <p className="text-sm text-slate-500">Cargando…</p>;

  const pl = view?.price_list;
  const overrides = pl?.overrides ?? {};
  const patches = pl?.line_patches ?? {};

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-semibold">Presupuesto del proveedor</h2>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
          Subí el presupuesto del corralón en <strong>PDF o Excel</strong>. Lo cruzamos con el modelo
          IFC usando las <a href="/reglas" target="_blank" className="text-brand hover:underline dark:text-sky-400">reglas de cómputo</a>:
          cuánto cemento, arena, ladrillos y hierro lleva la obra, y a qué precio.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <label className="text-sm">
          <span className="font-semibold text-slate-700 dark:text-slate-300">Reglas de cómputo</span>
          <select
            value={view?.rule_set?.id ?? ""}
            disabled={busy || uploading}
            onChange={(e) => patch({ rule_set_id: Number(e.target.value) })}
            className="mt-1 block rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          >
            {ruleSets.map((rs) => (
              <option key={rs.id} value={rs.id}>
                {rs.name}{rs.is_default ? " (por defecto)" : ""}
              </option>
            ))}
          </select>
        </label>

        {pl && (
          <label className="text-sm">
            <span className="font-semibold text-slate-700 dark:text-slate-300">Los precios del archivo</span>
            <select
              value={pl.iva_mode}
              disabled={busy || uploading}
              onChange={(e) => patch({ iva_mode: e.target.value as IvaMode })}
              className="mt-1 block rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            >
              <option value="auto">
                Detectar ({pl.iva_mode === "auto" ? (pl.iva.included ? "con IVA" : "sin IVA") : "automático"})
              </option>
              <option value="included">Incluyen IVA</option>
              <option value="excluded">No incluyen IVA</option>
            </select>
          </label>
        )}
      </div>

      {pl ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 px-4 py-3 text-sm dark:border-slate-700">
          <div>
            <div className="font-medium">{pl.filename}</div>
            <div className="text-xs text-slate-500 dark:text-slate-400">
              {[pl.supplier, pl.document_date && new Date(pl.document_date + "T12:00").toLocaleDateString("es-AR"),
                `${pl.lines.length} renglones`,
                pl.iva.included ? "precios con IVA → se guardan netos" : "precios sin IVA",
              ].filter(Boolean).join(" · ")}
              {pl.iva_mode === "auto" && <span className="text-slate-400"> ({pl.iva.method})</span>}
            </div>
          </div>
          <FilePicker label={uploading ? "Leyendo…" : "Reemplazar archivo"} disabled={uploading || busy} onChange={handleFile} small />
        </div>
      ) : (
        <FilePicker
          label={uploading ? "Leyendo el archivo…" : "Hacé clic para elegir el presupuesto (PDF, Excel o CSV)"}
          disabled={uploading}
          onChange={handleFile}
        />
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

      <div className="mt-2 flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          disabled={uploading}
          className="text-sm text-slate-500 hover:text-slate-900 disabled:opacity-50 dark:text-slate-400 dark:hover:text-slate-100"
        >
          ← Volver
        </button>
        <div className="flex items-center gap-4">
          {!pl && (
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
            disabled={!pl || uploading || busy}
            title={pl ? "" : "Subí el presupuesto del proveedor para continuar"}
            className="rounded-md bg-brand px-5 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
          >
            Siguiente →
          </button>
        </div>
      </div>
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
          ? `cursor-pointer rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800 ${disabled ? "pointer-events-none opacity-50" : ""}`
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

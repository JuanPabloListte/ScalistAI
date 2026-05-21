"use client";

import { useState } from "react";

import { api, type Plan } from "@/lib/api";

type Props = {
  plan: Plan;
  onClose: () => void;
  onUpdated: (plan: Plan) => void;
  onCalibrateManually: (page: number) => void;
};

export function ScalesModal({ plan, onClose, onUpdated, onCalibrateManually }: Props) {
  const dpi = plan.dpi ?? 150;
  const pageCount = plan.page_count ?? 0;
  const scales = plan.page_scales ?? {};
  const detectedCount = Object.keys(scales).length;

  // mm/m → cuántos pixeles equivalen a 1 metro real, dado un denominador 1:N
  function denominatorFromPxPerM(pxPerM: number): number {
    return (dpi * 1000) / (25.4 * pxPerM);
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-xl dark:bg-slate-800"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-slate-200 px-6 py-4 dark:border-slate-700">
          <div>
            <h3 className="text-lg font-semibold">Escalas calibradas</h3>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {detectedCount} de {pageCount} páginas con escala · {dpi} DPI
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
          >
            Cerrar
          </button>
        </header>

        <div className="overflow-y-auto px-6 py-4">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500 dark:text-slate-400">
              <tr>
                <th className="py-2 pr-2">Pág</th>
                <th className="py-2 pr-2">Escala 1:N</th>
                <th className="py-2 pr-2">px/m</th>
                <th className="py-2 pr-2 text-right">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
              {Array.from({ length: pageCount }, (_, i) => i + 1).map((page) => {
                const pxPerM = scales[String(page)] ?? null;
                const initialDenom = pxPerM
                  ? Math.round(denominatorFromPxPerM(pxPerM))
                  : null;
                return (
                  <ScaleRow
                    key={page}
                    page={page}
                    pxPerM={pxPerM}
                    initialDenom={initialDenom}
                    planId={plan.id}
                    onUpdated={onUpdated}
                    onCalibrateManually={() => {
                      onCalibrateManually(page);
                      onClose();
                    }}
                  />
                );
              })}
            </tbody>
          </table>
        </div>

        <footer className="border-t border-slate-200 px-6 py-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
          Tip: "Calibrar" abre el visor en esa página para que marques dos puntos sobre
          una cota conocida — útil cuando el plano impreso no coincide con la escala
          nominal del PDF.
        </footer>
      </div>
    </div>
  );
}

function ScaleRow({
  page,
  pxPerM,
  initialDenom,
  planId,
  onUpdated,
  onCalibrateManually,
}: {
  page: number;
  pxPerM: number | null;
  initialDenom: number | null;
  planId: number;
  onUpdated: (p: Plan) => void;
  onCalibrateManually: () => void;
}) {
  const [denomInput, setDenomInput] = useState(initialDenom ? String(initialDenom) : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dirty = (initialDenom ? String(initialDenom) : "") !== denomInput.trim();

  async function save() {
    const value = parseFloat(denomInput.replace(",", "."));
    if (!Number.isFinite(value) || value <= 0) {
      setError("Valor inválido");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await api.setScaleRatio(planId, page, value);
      onUpdated(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  async function clear() {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.clearPageScale(planId, page);
      onUpdated(updated);
      setDenomInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <tr>
      <td className="py-2 pr-2 font-medium">{page}</td>
      <td className="py-2 pr-2">
        <div className="flex items-center gap-1">
          <span className="text-slate-500 dark:text-slate-400">1:</span>
          <input
            type="text"
            inputMode="decimal"
            value={denomInput}
            onChange={(e) => setDenomInput(e.target.value)}
            placeholder="—"
            className="w-20 rounded border border-slate-300 px-2 py-1 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
          />
        </div>
        {error && <span className="text-xs text-red-600 dark:text-red-400">{error}</span>}
      </td>
      <td className="py-2 pr-2 text-slate-500 dark:text-slate-400">
        {pxPerM ? pxPerM.toFixed(2) : "—"}
      </td>
      <td className="py-2 pr-2 text-right">
        <div className="flex justify-end gap-1">
          <button
            type="button"
            onClick={save}
            disabled={busy || !dirty || !denomInput.trim()}
            className="rounded border border-brand px-2 py-1 text-xs font-medium text-brand hover:bg-brand hover:text-white disabled:opacity-30 dark:border-sky-400 dark:text-sky-400 dark:hover:bg-sky-400 dark:hover:text-slate-900"
          >
            {busy ? "..." : "Guardar"}
          </button>
          <button
            type="button"
            onClick={onCalibrateManually}
            disabled={busy}
            className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-30 dark:border-slate-600 dark:hover:bg-slate-700"
            title="Marcar dos puntos sobre el plano"
          >
            Calibrar
          </button>
          {pxPerM !== null && (
            <button
              type="button"
              onClick={clear}
              disabled={busy}
              className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-500 hover:bg-red-50 hover:text-red-600 disabled:opacity-30 dark:border-slate-600 dark:text-slate-400 dark:hover:bg-red-950/40 dark:hover:text-red-400"
              title="Borrar la escala de esta página"
            >
              ✕
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

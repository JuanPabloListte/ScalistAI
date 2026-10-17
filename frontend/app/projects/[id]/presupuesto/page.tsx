"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { LegacyBudget } from "@/components/legacy-budget";
import { ProjectPricesPanel } from "@/components/wizard/step-3-prices";
import { api, isUnauthorized, type Project, type ProjectBudgetView } from "@/lib/api";
import { FEATURES } from "@/lib/features";
import { money } from "@/lib/format";

export default function PresupuestoPage() {
  return FEATURES.legacyBudget ? <LegacyBudget /> : <SupplierBudget />;
}

/** Presupuesto de materiales: presupuesto del proveedor × reglas × IFC. */
function SupplierBudget() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = Number(params.id);

  const [project, setProject] = useState<Project | null>(null);
  const [view, setView] = useState<ProjectBudgetView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch((e) => {
      if (isUnauthorized(e)) router.push("/login");
      else setError(e instanceof Error ? e.message : String(e));
    });
  }, [projectId, router]);

  async function download() {
    setDownloading(true);
    setError(null);
    try {
      await api.downloadProjectBudgetXlsx(projectId, project?.name);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo generar el Excel");
    } finally {
      setDownloading(false);
    }
  }

  const budget = view?.budget;
  const pl = view?.price_list;

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex items-center justify-between gap-3">
        <Link href="/projects" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Volver a proyectos
        </Link>
        <button
          type="button"
          onClick={() => void download()}
          disabled={!budget || downloading || project?.status !== "active"}
          title={
            project && project.status !== "active"
              ? "El Excel se descarga cuando el proyecto está creado"
              : budget ? "" : "Subí el presupuesto del proveedor para poder exportar"
          }
          className="flex items-center gap-1.5 rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-dark disabled:opacity-50"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
          {downloading ? "Generando…" : "Descargar Excel"}
        </button>
      </div>

      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-900 to-slate-800 p-6 text-white shadow-sm dark:border-slate-700">
        <p className="text-sm text-slate-300">{project?.name ?? " "}</p>
        <div className="mt-1 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-400">Materiales (neto)</p>
            <p className="text-4xl font-bold tabular-nums">{budget ? money(budget.totals.net) : "—"}</p>
            <p className="mt-1 text-sm text-slate-300">
              {pl
                ? [pl.supplier ?? pl.filename, view?.rule_set?.name && `reglas: ${view.rule_set.name}`]
                    .filter(Boolean).join(" · ")
                : "Falta el presupuesto del proveedor"}
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs uppercase tracking-wide text-slate-400">Total con IVA</p>
            <p className="text-2xl font-semibold tabular-nums text-emerald-400">
              {budget ? money(budget.totals.total) : "—"}
            </p>
            {budget && budget.counts.sin_precio > 0 && (
              <p className="mt-1 text-xs text-amber-300">{budget.counts.sin_precio} ítems sin precio</p>
            )}
          </div>
        </div>
      </div>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      <section className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
        <ProjectPricesPanel projectId={projectId} showIntro={!pl} showTotals={false} onViewChange={setView} />
      </section>
    </main>
  );
}

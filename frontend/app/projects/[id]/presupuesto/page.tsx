"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { LaborPanel, SalePricePanel, matchesLaborFilter } from "@/components/labor-budget";
import { LegacyBudget } from "@/components/legacy-budget";
import { matchesReviewFilter } from "@/components/price-review";
import { ProjectNotFound } from "@/components/project-not-found";
import { ProjectPricesPanel } from "@/components/wizard/step-3-prices";
import { api, ApiError, isUnauthorized, type Project, type ProjectBudgetView, type User } from "@/lib/api";
import { FEATURES } from "@/lib/features";
import { money } from "@/lib/format";

export default function PresupuestoPage() {
  return FEATURES.legacyBudget ? (
    <LegacyBudget />
  ) : (
    <Suspense fallback={null}>
      <SupplierBudget />
    </Suspense>
  );
}

type Tab = "materiales" | "mano-de-obra";

const FIELD_CLS =
  "rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:focus:border-brand-400 dark:focus:ring-brand-400/20";

/** Buscador + select de grupo + "N de M" + Limpiar (mismo estilo que Reglas). */
function FilterBar({
  value,
  onChange,
  groups,
  allLabel,
  groupLabel,
  shown,
  total,
  placeholder,
}: {
  value: { text: string; group: string };
  onChange: (v: { text: string; group: string }) => void;
  groups: string[];
  allLabel: string;
  groupLabel: string;
  shown: number;
  total: number;
  placeholder: string;
}) {
  const filtering = !!value.text.trim() || !!value.group;
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <input
        type="search"
        placeholder={placeholder}
        aria-label={placeholder}
        value={value.text}
        onChange={(e) => onChange({ ...value, text: e.target.value })}
        className={`w-full max-w-sm ${FIELD_CLS}`}
      />
      <select
        aria-label={groupLabel}
        value={value.group}
        onChange={(e) => onChange({ ...value, group: e.target.value })}
        className={`max-w-[16rem] ${FIELD_CLS}`}
      >
        <option value="">{allLabel}</option>
        {groups.map((g) => <option key={g} value={g}>{g}</option>)}
      </select>
      {filtering && (
        <>
          <span className="text-xs text-slate-500 dark:text-slate-400">{shown} de {total} ítems</span>
          <button
            type="button"
            onClick={() => onChange({ text: "", group: "" })}
            className="text-xs font-medium text-brand-600 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/40 dark:text-brand-400"
          >
            Limpiar
          </button>
        </>
      )}
    </div>
  );
}

/** Presupuesto de obra: materiales (proveedor × reglas × IFC), mano de obra
 *  por rubro y precio de venta. */
function SupplierBudget() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const projectId = Number(params.id);
  const tab: Tab = searchParams.get("tab") === "mano-de-obra" ? "mano-de-obra" : "materiales";
  const [matFilter, setMatFilter] = useState({ text: "", group: "" });
  const [laborFilter, setLaborFilter] = useState({ text: "", group: "" });

  function selectTab(t: Tab) {
    router.replace(t === "materiales" ? `/projects/${projectId}/presupuesto` : `/projects/${projectId}/presupuesto?tab=${t}`,
                   { scroll: false });
  }

  const [project, setProject] = useState<Project | null>(null);
  const [view, setView] = useState<ProjectBudgetView | null>(null);
  // Vista que devuelve la mano de obra: se la pasa al panel del proveedor.
  const [laborView, setLaborView] = useState<ProjectBudgetView | null>(null);
  const [me, setMe] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [noAccess, setNoAccess] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [pdfMenu, setPdfMenu] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);

  useEffect(() => {
    api.getMe().then(setMe).catch(() => {});
    api.getProject(projectId).then(setProject).catch((e) => {
      if (isUnauthorized(e)) router.push("/login");
      else if (e instanceof ApiError && e.status === 404) setNotFound(true);
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

  async function downloadPdf(audience: "comitente" | "interno") {
    setPdfMenu(false);
    setPdfBusy(true);
    setError(null);
    try {
      await api.downloadProjectBudgetPdf(projectId, project?.name, audience);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo generar el PDF");
    } finally {
      setPdfBusy(false);
    }
  }

  const budget = view?.budget;
  const pl = view?.price_list;
  const price = view?.price;
  const pending = (budget?.counts.sin_precio ?? 0) + (view?.labor?.counts.pendientes ?? 0);
  const matItems = useMemo(() => view?.budget?.items ?? [], [view]);
  const matGroups = useMemo(() => Array.from(new Set(matItems.map((i) => i.measure_label))), [matItems]);
  const matShown = matItems.filter((i) => matchesReviewFilter(i, matFilter)).length;
  const laborItems = useMemo(
    () => (view?.model_status === "ready" ? (view.labor?.items ?? []).filter((i) => i.status !== "sin_medida") : []),
    [view],
  );
  const laborGroups = useMemo(() => Array.from(new Set(laborItems.map((i) => i.stage))), [laborItems]);
  const laborShown = laborItems.filter((i) => matchesLaborFilter(i, laborFilter)).length;
  const onLaborView = (v: ProjectBudgetView) => {
    setView(v);
    setLaborView(v);
  };

  if (notFound) return <ProjectNotFound />;

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex items-center justify-between gap-3">
        <Link href="/projects" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Volver a proyectos
        </Link>
        <div className="flex items-center gap-2">
        <div className="relative">
          <button
            type="button"
            onClick={() => setPdfMenu((o) => !o)}
            disabled={!price || pdfBusy || project?.status !== "active"}
            title={
              project && project.status !== "active"
                ? "El PDF se descarga cuando el proyecto está creado"
                : price ? "" : "Todavía no hay importes"
            }
            aria-haspopup="menu"
            aria-expanded={pdfMenu}
            className="flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {pdfBusy ? "Generando…" : "Descargar PDF"}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9" /></svg>
          </button>
          {pdfMenu && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setPdfMenu(false)} />
              <div role="menu" className="absolute right-0 z-20 mt-1.5 w-72 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900">
                <button type="button" role="menuitem" onClick={() => void downloadPdf("comitente")}
                        className="block w-full px-4 py-2.5 text-left hover:bg-slate-50 dark:hover:bg-slate-800">
                  <span className="block text-sm font-semibold text-slate-800 dark:text-slate-100">Para el comitente</span>
                  <span className="block text-xs text-slate-500 dark:text-slate-400">Precio por rubro, con tus márgenes incluidos</span>
                </button>
                <button type="button" role="menuitem" onClick={() => void downloadPdf("interno")}
                        className="block w-full border-t border-slate-100 px-4 py-2.5 text-left hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800">
                  <span className="block text-sm font-semibold text-slate-800 dark:text-slate-100">Interno</span>
                  <span className="block text-xs text-slate-500 dark:text-slate-400">Costos, gastos generales y beneficio por separado</span>
                </button>
              </div>
            </>
          )}
        </div>
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
      </div>

      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-900 to-slate-800 p-6 text-white shadow-sm dark:border-slate-700">
        <p className="text-sm text-slate-300">{project?.name ?? " "}</p>
        <div className="mt-1 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-400">Precio de venta</p>
            <p className="text-4xl font-bold tabular-nums">{price ? money(price.total) : "—"}</p>
            <p className="mt-1 text-sm text-slate-300">
              {pl
                ? [pl.supplier ?? pl.filename, view?.rule_set?.name && `reglas: ${view.rule_set.name}`]
                    .filter(Boolean).join(" · ")
                : noAccess ? "" : "Falta el presupuesto del proveedor"}
            </p>
          </div>
          <div className="flex gap-8 text-right">
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-400">Materiales</p>
              <p className="text-xl font-semibold tabular-nums">{price ? money(price.materials) : "—"}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-400">Mano de obra</p>
              <p className="text-xl font-semibold tabular-nums">{price ? money(price.labor) : "—"}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-400">Costo directo</p>
              <p className="text-xl font-semibold tabular-nums text-emerald-400">{price ? money(price.direct) : "—"}</p>
              {pending > 0 && <p className="mt-1 text-xs text-amber-300">{pending} ítems sin precio</p>}
            </div>
          </div>
        </div>
      </div>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      <div role="tablist" aria-label="Presupuesto" className="flex gap-4 overflow-x-auto border-b border-slate-200 dark:border-slate-800">
        {([
          { key: "materiales", label: "Materiales", n: matItems.length },
          { key: "mano-de-obra", label: "Mano de obra", n: laborItems.length },
        ] as { key: Tab; label: string; n: number }[]).map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key}
                  onClick={() => selectTab(t.key)}
                  className={`whitespace-nowrap border-b-2 px-1 pb-2 text-sm font-medium transition ${
            tab === t.key
              ? "border-brand-500 text-brand-600 dark:border-brand-400 dark:text-brand-400"
              : "border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-300"
          }`}>
            {t.label} <span className="text-xs text-slate-400">{t.n}</span>
          </button>
        ))}
      </div>

      {/* Ambos paneles quedan montados (ocultos) para no perder la carga ni los filtros al cambiar de pestaña. */}
      <section role="tabpanel" hidden={tab !== "materiales"}
               className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
        {matItems.length > 0 && (
          <FilterBar value={matFilter} onChange={setMatFilter} groups={matGroups} allLabel="Todas"
                     groupLabel="Medida" shown={matShown} total={matItems.length}
                     placeholder="Buscar producto o renglón del proveedor…" />
        )}
        <ProjectPricesPanel projectId={projectId} showIntro={!pl} showTotals={false} onViewChange={setView} onNoAccess={() => setNoAccess(true)}
                            viewOverride={laborView} filter={matFilter} />
      </section>

      <div role="tabpanel" hidden={tab !== "mano-de-obra"} className="space-y-4">
        {view && (
          <LaborPanel projectId={projectId} view={view} canEdit filter={laborFilter} hideTitle
                      isAdmin={!!(me?.is_superadmin || me?.role === "admin")} onView={onLaborView}
                      toolbar={laborItems.length > 0 ? (
                        <FilterBar value={laborFilter} onChange={setLaborFilter} groups={laborGroups}
                                   allLabel="Todos" groupLabel="Rubro" shown={laborShown}
                                   total={laborItems.length} placeholder="Buscar tarea de mano de obra…" />
                      ) : undefined} />
        )}
      </div>

      {view && <SalePricePanel projectId={projectId} view={view} canEdit onView={onLaborView} />}
    </main>
  );
}

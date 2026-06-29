"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { AiDetectionBanner } from "@/components/ai-detection-banner";
import { PlanViewer } from "@/components/plan-viewer";
import { ScalesModal } from "@/components/scales-modal";
import { api, type Plan, type Project } from "@/lib/api";

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = Number(params.id);

  const [project, setProject] = useState<Project | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [activePlanId, setActivePlanId] = useState<number | null>(null);
  const [scalesModalOpen, setScalesModalOpen] = useState(false);
  const [viewMenuOpen, setViewMenuOpen] = useState(false);
  const [calRequest, setCalRequest] = useState<{ page: number; ts: number } | null>(null);
  const [activeTabId, setActiveTabId] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getProject(projectId), api.listPlans(projectId)])
      .then(([proj, planList]) => {
        if (cancelled) return;
        setProject(proj);
        setPlans(planList);
        const firstReady = planList.find((p) => p.status === "ready");
        if (firstReady) setActivePlanId(firstReady.id);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof Error && err.message.includes("401")) {
          router.push("/login");
        } else {
          setError(err.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, router]);

  const activePlan = plans.find((p) => p.id === activePlanId) ?? null;

  const availableTabs = useMemo(() => {
    if (!activePlan) return [];
    const roles = activePlan.page_roles ?? {};
    const deleted = new Set(activePlan.deleted_pages ?? []);
    const pageCount = activePlan.page_count ?? 0;
    const allPages = Array.from({ length: pageCount }, (_, i) => i + 1).filter((p) => !deleted.has(p));

    const wallsPages: number[] = [];
    const roomsPages: number[] = [];
    const openingsPages: number[] = [];
    const beamsPages: number[] = [];
    const roofsPages: number[] = [];
    const columnsPages: number[] = [];
    const riostrasPages: number[] = [];
    const cloacasPages: number[] = [];
    const electricidadPages: number[] = [];

    for (const p of allPages) {
      const pRoles = roles[String(p)] ?? [];
      if (pRoles.includes("walls")) wallsPages.push(p);
      if (pRoles.includes("rooms")) roomsPages.push(p);
      if (pRoles.includes("openings")) openingsPages.push(p);
      if (pRoles.includes("beams")) beamsPages.push(p);
      if (pRoles.includes("roofs")) roofsPages.push(p);
      if (pRoles.includes("columns")) columnsPages.push(p);
      if (pRoles.includes("riostras")) riostrasPages.push(p);
      if (pRoles.includes("cloacas")) cloacasPages.push(p);
      if (pRoles.includes("electricidad")) electricidadPages.push(p);
    }

    const tabs = [];
    if (wallsPages.length > 0) {
      tabs.push({ id: "walls", label: "Muros", pages: wallsPages });
    }
    if (roomsPages.length > 0) {
      tabs.push({ id: "rooms", label: "Recinto", pages: roomsPages });
    }
    if (openingsPages.length > 0) {
      tabs.push({ id: "openings", label: "Abertura", pages: openingsPages });
    }
    if (beamsPages.length > 0) {
      tabs.push({ id: "beams", label: "Viga", pages: beamsPages });
    }
    if (roofsPages.length > 0) {
      tabs.push({ id: "roofs", label: "Techo / Losa", pages: roofsPages });
    }
    if (columnsPages.length > 0) {
      tabs.push({ id: "columns", label: "Columna", pages: columnsPages });
    }
    if (riostrasPages.length > 0) {
      tabs.push({ id: "riostras", label: "Riostras", pages: riostrasPages });
    }
    if (cloacasPages.length > 0) {
      tabs.push({ id: "cloacas", label: "Cloacas", pages: cloacasPages });
    }
    if (electricidadPages.length > 0) {
      tabs.push({ id: "electricidad", label: "Electricidad", pages: electricidadPages });
    }

    if (tabs.length === 0 && allPages.length > 0) {
      tabs.push({ id: "all", label: "Planos", pages: allPages });
    }
    return tabs;
  }, [activePlan]);

  useEffect(() => {
    if (availableTabs.length > 0) {
      if (!activeTabId || !availableTabs.some((t) => t.id === activeTabId)) {
        setActiveTabId(availableTabs[0].id);
      }
    }
  }, [availableTabs, activeTabId]);

  const activeTab = availableTabs.find((t) => t.id === activeTabId) ?? null;
  const allowedPages = activeTab ? activeTab.pages : undefined;

  if (!project) {
    return (
      <main className="mx-auto max-w-4xl px-6 py-10">
        <p className="text-slate-500 dark:text-slate-400">{error ?? "Cargando..."}</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-screen-2xl px-6 py-8">
      <header className="mb-6">
        <a
          href="/projects"
          className="inline-flex items-center gap-1 text-sm font-medium text-slate-500 transition hover:text-brand-600 dark:text-slate-400 dark:hover:text-brand-400"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6"/></svg>
          Volver a proyectos
        </a>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">
          {project.name}
        </h1>
      </header>

      {activePlanId !== null && (
        <AiDetectionBanner planId={activePlanId} />
      )}

      {error && <p className="mb-4 text-sm text-red-600 dark:text-red-400">{error}</p>}

      {activePlan ? (
        <section className="mb-8">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">{activePlan.original_filename}</h2>
              <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                {activePlan.scale_source === "dxf"
                  ? "Importado de DXF"
                  : `${activePlan.dpi} DPI`}{" "}
                · {activePlan.page_count ?? "?"} página
                {activePlan.page_count === 1 ? "" : "s"}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setScalesModalOpen(true)}
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-brand-400 hover:text-brand-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-brand-500/60 dark:hover:text-brand-300"
              >
                Tabla de escalas
                {activePlan.page_scales &&
                  Object.keys(activePlan.page_scales).length > 0 &&
                  ` · ${Object.keys(activePlan.page_scales).length}`}
              </button>
              <div className="relative">
                <button
                  onClick={() => setViewMenuOpen((o) => !o)}
                  className="flex items-center gap-1.5 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-700"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
                  Ver resultados
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className={`transition ${viewMenuOpen ? "rotate-180" : ""}`}><polyline points="6 9 12 15 18 9"/></svg>
                </button>
                {viewMenuOpen && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setViewMenuOpen(false)} />
                    <div className="absolute right-0 z-20 mt-1.5 w-60 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900">
                      <ViewMenuItem href={`/projects/${project.id}/presupuesto`} title="Presupuesto completo" desc="Cómputo y costos del proyecto" />
                      <ViewMenuItem href={`/projects/${project.id}/costos`} title="Presupuesto Inteligente" desc="Precio de venta + proyección" />
                      <ViewMenuItem href={`/projects/${project.id}/gantt`} title="Cronograma (Gantt)" desc="Plan de obra en el tiempo" />
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* Pestañas: borde inferior coloreado por categoría, sin fondo tinted
              para no ensuciar la jerarquía visual. El color del borde sigue
              la convención del wizard (muros=emerald, recintos=sky, etc). */}
          {availableTabs.length > 1 && (
            <div className="mb-5 border-b border-slate-200 dark:border-slate-800">
              <div className="flex flex-wrap gap-x-1 gap-y-0 -mb-px" role="tablist">
                {availableTabs.map((t) => {
                  const isActive = t.id === activeTabId;
                  const activeColor: Record<string, string> = {
                    walls: "border-emerald-500 text-emerald-700 dark:border-emerald-400 dark:text-emerald-300",
                    rooms: "border-sky-500 text-sky-700 dark:border-sky-400 dark:text-sky-300",
                    openings: "border-amber-500 text-amber-700 dark:border-amber-400 dark:text-amber-300",
                    beams: "border-purple-500 text-purple-700 dark:border-purple-400 dark:text-purple-300",
                    roofs: "border-teal-500 text-teal-700 dark:border-teal-400 dark:text-teal-300",
                    columns: "border-pink-500 text-pink-700 dark:border-pink-400 dark:text-pink-300",
                    all: "border-brand-500 text-brand-700 dark:border-brand-400 dark:text-brand-300",
                  };
                  const tabClass = isActive
                    ? activeColor[t.id] ?? activeColor.all
                    : "border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300 dark:text-slate-400 dark:hover:text-slate-200 dark:hover:border-slate-700";
                  return (
                    <button
                      key={t.id}
                      role="tab"
                      aria-selected={isActive}
                      onClick={() => setActiveTabId(t.id)}
                      className={`flex items-center gap-1.5 border-b-2 px-3.5 py-2.5 text-sm font-medium transition ${tabClass}`}
                    >
                      <span>{t.label}</span>
                      <span
                        className={`rounded-md px-1.5 py-0 text-[10px] font-semibold ${
                          isActive
                            ? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                            : "bg-slate-100 text-slate-500 dark:bg-slate-800/70 dark:text-slate-400"
                        }`}
                      >
                        {t.pages.length}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          <PlanViewer
            planId={activePlan.id}
            pageCount={activePlan.page_count}
            pageScales={activePlan.page_scales}
            deletedPages={activePlan.deleted_pages}
            scaleSource={activePlan.scale_source}
            planDpi={activePlan.dpi}
            calRequest={calRequest}
            allowedPages={allowedPages}
            activeCategory={activeTabId}
            onPlanUpdated={(updated) =>
              setPlans((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
            }
          />
        </section>
      ) : (
        <section className="rounded-xl border-2 border-dashed border-slate-300 px-6 py-12 text-center text-slate-500 dark:border-slate-700 dark:text-slate-400">
          <p>Este proyecto no tiene planos para visualizar.</p>
        </section>
      )}

      {scalesModalOpen && activePlan && (
        <ScalesModal
          plan={activePlan}
          onClose={() => setScalesModalOpen(false)}
          onUpdated={(updated) =>
            setPlans((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
          }
          onCalibrateManually={(page) => {
            setCalRequest({ page, ts: Date.now() });
            setScalesModalOpen(false);
          }}
        />
      )}
    </main>
  );
}

function ViewMenuItem({ href, title, desc }: { href: string; title: string; desc: string }) {
  return (
    <a
      href={href}
      className="block border-b border-slate-100 px-4 py-2.5 last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/60"
    >
      <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</p>
      <p className="text-xs text-slate-500 dark:text-slate-400">{desc}</p>
    </a>
  );
}

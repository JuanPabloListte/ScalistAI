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

    for (const p of allPages) {
      const pRoles = roles[String(p)] ?? [];
      if (pRoles.includes("walls")) wallsPages.push(p);
      if (pRoles.includes("rooms")) roomsPages.push(p);
      if (pRoles.includes("openings")) openingsPages.push(p);
      if (pRoles.includes("beams")) beamsPages.push(p);
      if (pRoles.includes("roofs")) roofsPages.push(p);
      if (pRoles.includes("columns")) columnsPages.push(p);
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
    <main className="mx-auto max-w-screen-2xl px-6 py-10">
      <header className="mb-6">
        <a href="/projects" className="text-sm text-brand hover:underline dark:text-sky-400">
          ← Volver
        </a>
        <h1 className="mt-2 text-3xl font-bold text-brand dark:text-sky-400">{project.name}</h1>
      </header>

      {activePlanId !== null && (
        <AiDetectionBanner planId={activePlanId} />
      )}

      {error && <p className="mb-4 text-sm text-red-600 dark:text-red-400">{error}</p>}

      {activePlan ? (
        <section className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">{activePlan.original_filename}</h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {activePlan.dpi} DPI · {activePlan.page_count ?? "?"} página
                {activePlan.page_count === 1 ? "" : "s"}
              </p>
            </div>
            <button
              onClick={() => setScalesModalOpen(true)}
              className="rounded border border-brand px-3 py-1 text-sm font-medium text-brand hover:bg-brand hover:text-white dark:border-sky-400 dark:text-sky-400 dark:hover:bg-sky-400 dark:hover:text-slate-900"
            >
              Tabla de escalas
              {activePlan.page_scales &&
                Object.keys(activePlan.page_scales).length > 0 &&
                ` (${Object.keys(activePlan.page_scales).length})`}
            </button>
          </div>

          {/* Sistema de Pestañas con diseño Premium */}
          {availableTabs.length > 1 && (
            <div className="mb-6 border-b border-slate-200 dark:border-slate-700">
              <div className="flex gap-2" role="tablist">
                {availableTabs.map((t) => {
                  const isActive = t.id === activeTabId;
                  let tabColors = "";
                  if (isActive) {
                    if (t.id === "walls") {
                      tabColors = "border-emerald-500 text-emerald-600 dark:border-emerald-400 dark:text-emerald-400 bg-emerald-50/30 dark:bg-emerald-950/20";
                    } else if (t.id === "rooms") {
                      tabColors = "border-sky-500 text-sky-600 dark:border-sky-400 dark:text-sky-400 bg-sky-50/30 dark:bg-sky-950/20";
                    } else if (t.id === "openings") {
                      tabColors = "border-amber-500 text-amber-600 dark:border-amber-400 dark:text-amber-400 bg-amber-50/30 dark:bg-amber-950/20";
                    } else if (t.id === "beams") {
                      tabColors = "border-purple-500 text-purple-600 dark:border-purple-400 dark:text-purple-400 bg-purple-50/30 dark:bg-purple-950/20";
                    } else if (t.id === "roofs") {
                      tabColors = "border-teal-500 text-teal-600 dark:border-teal-400 dark:text-teal-400 bg-teal-50/30 dark:bg-teal-950/20";
                    } else if (t.id === "columns") {
                      tabColors = "border-pink-500 text-pink-600 dark:border-pink-400 dark:text-pink-400 bg-pink-50/30 dark:bg-pink-950/20";
                    } else {
                      tabColors = "border-brand text-brand dark:border-sky-400 dark:text-sky-400 bg-slate-50 dark:bg-slate-800/40";
                    }
                  } else {
                    tabColors = "border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 hover:border-slate-300 dark:hover:border-slate-600";
                  }
                  return (
                    <button
                      key={t.id}
                      role="tab"
                      aria-selected={isActive}
                      onClick={() => setActiveTabId(t.id)}
                      className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-semibold transition ${tabColors}`}
                    >
                      {t.label}
                      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                        isActive
                          ? t.id === "walls"
                            ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-300"
                            : t.id === "rooms"
                              ? "bg-sky-100 text-sky-800 dark:bg-sky-900/50 dark:text-sky-300"
                              : t.id === "openings"
                                ? "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300"
                                : t.id === "beams"
                                  ? "bg-purple-100 text-purple-800 dark:bg-purple-900/50 dark:text-purple-300"
                                  : t.id === "roofs"
                                    ? "bg-teal-100 text-teal-800 dark:bg-teal-900/50 dark:text-teal-300"
                                    : t.id === "columns"
                                      ? "bg-pink-100 text-pink-800 dark:bg-pink-900/50 dark:text-pink-300"
                                      : "bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-300"
                          : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                      }`}>
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

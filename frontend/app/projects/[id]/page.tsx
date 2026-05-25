"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

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

  if (!project) {
    return (
      <main className="mx-auto max-w-4xl px-6 py-10">
        <p className="text-slate-500 dark:text-slate-400">{error ?? "Cargando..."}</p>
      </main>
    );
  }

  const activePlan = plans.find((p) => p.id === activePlanId) ?? null;

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
          <PlanViewer
            planId={activePlan.id}
            pageCount={activePlan.page_count}
            pageScales={activePlan.page_scales}
            deletedPages={activePlan.deleted_pages}
            scaleSource={activePlan.scale_source}
            planDpi={activePlan.dpi}
            calRequest={calRequest}
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

"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { PlanViewer } from "@/components/plan-viewer";
import { ScalesModal } from "@/components/scales-modal";
import { api, type Plan, type Project } from "@/lib/api";

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = Number(params.id);

  const [project, setProject] = useState<Project | null>(null);
  const [uploading, setUploading] = useState(false);
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

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const plan = await api.uploadPlan(projectId, file);
      setPlans((prev) => [plan, ...prev]);
      if (plan.status === "ready") setActivePlanId(plan.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

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
        {project.description && (
          <p className="mt-2 whitespace-pre-line text-sm text-slate-600 dark:text-slate-300">
            {project.description}
          </p>
        )}
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">Estado: {project.status}</p>
      </header>

      <section className="mb-8 rounded-xl bg-white p-6 shadow dark:bg-slate-800 dark:shadow-slate-950/50">
        <h2 className="mb-3 text-lg font-semibold">Subir plano (PDF)</h2>
        <input
          type="file"
          accept="application/pdf"
          onChange={handleUpload}
          disabled={uploading}
          className="block w-full text-sm text-slate-500 dark:text-slate-400
            file:mr-4 file:rounded-md file:border-0
            file:bg-brand file:px-4 file:py-2 file:text-sm file:font-semibold
            file:text-white hover:file:bg-brand-dark"
        />
        {uploading && (
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
            Procesando PDF (rasterizando a 300 DPI + binarizando)...
          </p>
        )}
        {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
      </section>

      {activePlan && (
        <section className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">{activePlan.original_filename}</h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {activePlan.dpi} DPI · {activePlan.page_count ?? "?"} página
                {activePlan.page_count === 1 ? "" : "s"} · estado {activePlan.status}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => setScalesModalOpen(true)}
                className="rounded border border-brand px-3 py-1 text-sm font-medium text-brand hover:bg-brand hover:text-white dark:border-sky-400 dark:text-sky-400 dark:hover:bg-sky-400 dark:hover:text-slate-900"
              >
                Tabla de escalas
                {activePlan.page_scales &&
                  Object.keys(activePlan.page_scales).length > 0 &&
                  ` (${Object.keys(activePlan.page_scales).length})`}
              </button>
              <button
                onClick={() => setActivePlanId(null)}
                className="text-sm text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
              >
                Cerrar
              </button>
            </div>
          </div>
          <PlanViewer
            planId={activePlan.id}
            pageCount={activePlan.page_count}
            pageScales={activePlan.page_scales}
            scaleSource={activePlan.scale_source}
            planDpi={activePlan.dpi}
            calRequest={calRequest}
            onScaleCalibrated={(updated) =>
              setPlans((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
            }
          />
        </section>
      )}

      <section>
        <h2 className="mb-3 text-lg font-semibold">Planos subidos</h2>
        {plans.length === 0 ? (
          <p className="text-slate-500 dark:text-slate-400">
            Todavía no hay planos en este proyecto.
          </p>
        ) : (
          <ul className="divide-y divide-slate-200 rounded-xl bg-white shadow dark:divide-slate-700 dark:bg-slate-800 dark:shadow-slate-950/50">
            {plans.map((p) => (
              <li key={p.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="font-medium">{p.original_filename}</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Estado: {p.status} · subido {new Date(p.created_at).toLocaleString()}
                  </p>
                </div>
                {p.status === "ready" && (
                  <button
                    onClick={() => setActivePlanId(p.id)}
                    disabled={activePlanId === p.id}
                    className="rounded-md border border-brand px-3 py-1 text-sm font-medium text-brand hover:bg-brand hover:text-white disabled:opacity-50 dark:border-sky-400 dark:text-sky-400 dark:hover:bg-sky-400 dark:hover:text-slate-900"
                  >
                    {activePlanId === p.id ? "Visible" : "Ver"}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

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

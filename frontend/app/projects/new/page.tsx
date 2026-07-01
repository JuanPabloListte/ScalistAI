"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { IFC_WIZARD_STEPS, Stepper, WIZARD_STEPS } from "@/components/wizard/stepper";
import { Step1Basics } from "@/components/wizard/step-1-basics";
import { Step2Plan } from "@/components/wizard/step-2-plan";
import { Step3PageRoles } from "@/components/wizard/step-3-page-roles";
import { Step3Location } from "@/components/wizard/step-3-location";
import { Step4Building } from "@/components/wizard/step-4-building";
import { Step5Review } from "@/components/wizard/step-5-review";
import { api, type Project } from "@/lib/api";

function NewProjectWizardInner() {
  const router = useRouter();
  const params = useSearchParams();
  const resumeId = params.get("id");
  const editMode = params.get("edit") === "1";

  const [step, setStep] = useState(1);
  const [project, setProject] = useState<Project | null>(null);
  const [isIfc, setIsIfc] = useState(false);
  const [loading, setLoading] = useState(!!resumeId);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!resumeId) return;
    Promise.all([
      api.getProject(Number(resumeId)),
      api.listPlans(Number(resumeId)).catch(() => []),
    ])
      .then(([p, plans]) => {
        setProject(p);
        if (p.status === "active" && !editMode) {
          router.replace(`/projects/${p.id}`);
          return;
        }
        const ifc = plans.some((pl) => pl.original_filename?.toLowerCase().endsWith(".ifc"));
        setIsIfc(ifc);
        // edit: arranca en lo editable; wizard normal: siguiente al completado.
        let startStep = editMode ? 3 : Math.min(6, Math.max(1, p.wizard_step + 1));
        if (ifc && startStep === 3) startStep = 4; // IFC no tiene paso "Páginas"
        setStep(startStep);
      })
      .catch((err) => {
        if (err instanceof Error && err.message.includes("401")) {
          router.push("/login");
          return;
        }
        setLoadError(err instanceof Error ? err.message : "No se pudo cargar el proyecto");
      })
      .finally(() => setLoading(false));
  }, [resumeId, router, editMode]);

  const goBack = useCallback(
    () => setStep((s) => (isIfc && s === 4 ? 2 : Math.max(1, s - 1))),
    [isIfc],
  );
  const jumpTo = useCallback((target: number) => setStep(target), []);

  if (loading) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-10">
        <p className="text-sm text-slate-500">Cargando proyecto...</p>
      </main>
    );
  }

  if (loadError) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-10">
        <p className="text-sm text-red-600 dark:text-red-400">{loadError}</p>
      </main>
    );
  }

  const maxReached = project ? Math.max(step, project.wizard_step) : step;

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <Link
        href="/projects"
        className="text-sm text-brand hover:underline dark:text-sky-400"
      >
        ← Cancelar
      </Link>

      <h1 className="mt-2 text-3xl font-bold text-brand dark:text-sky-400">Nuevo proyecto</h1>

      <Stepper currentStep={step} maxReached={maxReached} onJump={jumpTo}
               steps={isIfc ? IFC_WIZARD_STEPS : WIZARD_STEPS} />

      <div className="rounded-xl bg-white p-6 shadow dark:bg-slate-800 dark:shadow-slate-950/50">
        {step === 1 && (
          <Step1Basics
            project={project}
            onCreated={(p) => {
              setProject(p);
              setStep(2);
            }}
          />
        )}

        {step === 2 && project && (
          <Step2Plan
            project={project}
            onUploaded={(plan) => {
              const ifc = plan?.original_filename?.toLowerCase().endsWith(".ifc") ?? false;
              setIsIfc(ifc);
              setStep(ifc ? 4 : 3); // IFC salta "Páginas"
            }}
            onBack={goBack}
          />
        )}

        {step === 3 && project && (
          <Step3PageRoles
            project={project}
            onSaved={() => setStep(4)}
            onBack={goBack}
          />
        )}

        {step === 4 && project && (
          <Step3Location
            project={project}
            onSaved={(p) => {
              setProject(p);
              setStep(5);
            }}
            onBack={goBack}
          />
        )}

        {step === 5 && project && (
          <Step4Building
            project={project}
            onSaved={(p) => {
              setProject(p);
              setStep(6);
            }}
            onBack={goBack}
          />
        )}

        {step === 6 && project && (
          <Step5Review
            project={project}
            onActivate={(p) => router.push(isIfc ? `/projects/${p.id}/presupuesto` : `/projects/${p.id}`)}
            onBack={goBack}
            onEditStep={jumpTo}
          />
        )}
      </div>

      {project && (
        <p className="mt-3 text-xs text-slate-400 dark:text-slate-500">
          Proyecto borrador #{project.id} · Tus cambios se guardan al avanzar.
        </p>
      )}
    </main>
  );
}

import { Suspense } from "react";

export default function NewProjectWizard() {
  return (
    <Suspense fallback={<main className="mx-auto max-w-2xl px-6 py-10"><p className="text-sm text-slate-500">Cargando...</p></main>}>
      <NewProjectWizardInner />
    </Suspense>
  );
}

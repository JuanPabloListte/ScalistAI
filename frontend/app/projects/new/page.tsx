"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { IFC_WIZARD_STEPS, Stepper } from "@/components/wizard/stepper";
import { Step1Basics } from "@/components/wizard/step-1-basics";
import { Step2Plan } from "@/components/wizard/step-2-plan";
// PIVOTE IFC: Step3PageRoles (páginas PDF / capas DXF) desactivado — reactivar
// junto con WIZARD_STEPS y la rama step===3 al volver a PDF/DXF/DWG.
// import { Step3PageRoles } from "@/components/wizard/step-3-page-roles";
import { Step3Location } from "@/components/wizard/step-3-location";
import { Step4Building } from "@/components/wizard/step-4-building";
import { Step5Review } from "@/components/wizard/step-5-review";
import { api, isUnauthorized, type Project } from "@/lib/api";

function NewProjectWizardInner() {
  const router = useRouter();
  const params = useSearchParams();
  const resumeId = params.get("id");
  const editMode = params.get("edit") === "1";

  const [step, setStep] = useState(1);
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(!!resumeId);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!resumeId) return;
    api
      .getProject(Number(resumeId))
      .then((p) => {
        setProject(p);
        if (p.status === "active" && !editMode) {
          router.replace(`/projects/${p.id}`);
          return;
        }
        // edit: arranca en ubicación; wizard normal: siguiente al completado.
        let startStep = editMode ? 4 : Math.min(6, Math.max(1, p.wizard_step + 1));
        // PIVOTE IFC: no hay paso "Páginas" (step 3).
        if (startStep === 3) startStep = 4;
        setStep(startStep);
      })
      .catch((err) => {
        if (isUnauthorized(err)) {
          router.push("/login");
          return;
        }
        setLoadError(err instanceof Error ? err.message : "No se pudo cargar el proyecto");
      })
      .finally(() => setLoading(false));
  }, [resumeId, router, editMode]);

  const goBack = useCallback(
    () => setStep((s) => (s === 4 ? 2 : Math.max(1, s - 1))),
    [],
  );
  const jumpTo = useCallback((target: number) => {
    // PIVOTE IFC: el step 3 (páginas) no existe — redirigir a ubicación.
    setStep(target === 3 ? 4 : target);
  }, []);

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

      {/* PIVOTE IFC: siempre IFC_WIZARD_STEPS */}
      <Stepper currentStep={step} maxReached={maxReached} onJump={jumpTo}
               steps={IFC_WIZARD_STEPS} />

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
            onUploaded={() => {
              // PIVOTE IFC: siempre salta "Páginas" → ubicación
              setStep(4);
            }}
            onBack={goBack}
          />
        )}

        {/* PIVOTE IFC: step 3 (páginas PDF / capas DXF) desactivado.
        {step === 3 && project && (
          <Step3PageRoles
            project={project}
            onSaved={() => setStep(4)}
            onBack={goBack}
          />
        )}
        */}

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
            onActivate={(p) => router.push(`/projects/${p.id}/presupuesto`)}
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

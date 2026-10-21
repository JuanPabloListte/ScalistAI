"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ProjectNotFound } from "@/components/project-not-found";
import { IFC_WIZARD_STEPS, Stepper } from "@/components/wizard/stepper";
import { Step1Basics } from "@/components/wizard/step-1-basics";
import { Step2Plan } from "@/components/wizard/step-2-plan";
import { Step3Location } from "@/components/wizard/step-3-location";
import { Step3Prices } from "@/components/wizard/step-3-prices";
import { Step4Building } from "@/components/wizard/step-4-building";
import { Step5Review } from "@/components/wizard/step-5-review";
import { api, ApiError, isUnauthorized, type Project } from "@/lib/api";
import { FEATURES } from "@/lib/features";

// Paso interno "Construcción" (5) oculto → se salta a Revisión (6).
const skipHidden = (s: number) => (s === 5 && !FEATURES.wizardBuildingStep ? 6 : s);

function NewProjectWizardInner() {
  const router = useRouter();
  const params = useSearchParams();
  const resumeId = params.get("id");
  const editMode = params.get("edit") === "1";

  const [step, setStep] = useState(1);
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(!!resumeId);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

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
        // IFC: el índice 3 ya no es "Páginas" sino "Precios" (proveedor).
        setStep(skipHidden(startStep));
      })
      .catch((err) => {
        if (isUnauthorized(err)) {
          router.push("/login");
          return;
        }
        if (err instanceof ApiError && err.status === 404) setNotFound(true);
        else setLoadError(err instanceof Error ? err.message : "No se pudo cargar el proyecto");
      })
      .finally(() => setLoading(false));
  }, [resumeId, router, editMode]);

  const goBack = useCallback(
    () => setStep((s) => {
      if (s === 4) return 3;
      if (s === 6 && !FEATURES.wizardBuildingStep) return 4;
      return Math.max(1, s - 1);
    }),
    [],
  );
  const jumpTo = useCallback((target: number) => {
    setStep(skipHidden(target));
  }, []);

  if (loading) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-10">
        <p className="text-sm text-slate-500">Cargando proyecto...</p>
      </main>
    );
  }

  if (notFound) return <ProjectNotFound />;

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
              // IFC: después del modelo va el presupuesto del proveedor.
              setStep(3);
            }}
            onBack={goBack}
          />
        )}

        {step === 3 && project && (
          <Step3Prices
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
              setStep(skipHidden(5));
            }}
            onBack={goBack}
          />
        )}

        {step === 5 && FEATURES.wizardBuildingStep && project && (
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

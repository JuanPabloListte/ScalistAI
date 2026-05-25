"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Stepper } from "@/components/wizard/stepper";
import { Step1Basics } from "@/components/wizard/step-1-basics";
import { Step2Plan } from "@/components/wizard/step-2-plan";
import { Step3Location } from "@/components/wizard/step-3-location";
import { Step4Building } from "@/components/wizard/step-4-building";
import { Step5Review } from "@/components/wizard/step-5-review";
import { api, type Project } from "@/lib/api";

export default function NewProjectWizard() {
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
        // Si esta active y NO es edit explicito, ir al detalle.
        if (p.status === "active" && !editMode) {
          router.replace(`/projects/${p.id}`);
          return;
        }
        // En edit mode arrancamos en el paso 3 (lo primero "editable" mas alla
        // del nombre); en wizard normal arrancamos en el siguiente al completado.
        const startStep = editMode ? 3 : Math.min(5, Math.max(1, p.wizard_step + 1));
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
  }, [resumeId, router]);

  const goNext = useCallback(() => setStep((s) => Math.min(5, s + 1)), []);
  const goBack = useCallback(() => setStep((s) => Math.max(1, s - 1)), []);
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
    <main className="mx-auto max-w-2xl px-6 py-10">
      <Link
        href="/projects"
        className="text-sm text-brand hover:underline dark:text-sky-400"
      >
        ← Cancelar
      </Link>

      <h1 className="mt-2 text-3xl font-bold text-brand dark:text-sky-400">Nuevo proyecto</h1>

      <Stepper currentStep={step} maxReached={maxReached} onJump={jumpTo} />

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
            onUploaded={() => setStep(3)}
            onBack={goBack}
          />
        )}

        {step === 3 && project && (
          <Step3Location
            project={project}
            onSaved={(p) => {
              setProject(p);
              setStep(4);
            }}
            onBack={goBack}
          />
        )}

        {step === 4 && project && (
          <Step4Building
            project={project}
            onSaved={(p) => {
              setProject(p);
              setStep(5);
            }}
            onBack={goBack}
          />
        )}

        {step === 5 && project && (
          <Step5Review
            project={project}
            onActivate={(p) => router.push(`/projects/${p.id}`)}
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

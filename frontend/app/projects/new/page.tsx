"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api, type Project } from "@/lib/api";

type Step = 1 | 2;

const STEPS: { num: Step; label: string }[] = [
  { num: 1, label: "Datos del proyecto" },
  { num: 2, label: "Subir plano" },
];

export default function NewProjectWizard() {
  const router = useRouter();

  const [step, setStep] = useState<Step>(1);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [project, setProject] = useState<Project | null>(null);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmitStep1(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setError(null);
    setSubmitting(true);
    try {
      const created = await api.createProject(name.trim(), description);
      setProject(created);
      setStep(2);
    } catch (err) {
      if (err instanceof Error && err.message.includes("401")) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Error desconocido");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    if (!project) return;
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await api.uploadPlan(project.id, file);
      router.push(`/projects/${project.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido");
      setUploading(false);
      e.target.value = "";
    }
  }

  function skipUpload() {
    if (project) router.push(`/projects/${project.id}`);
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <Link
        href="/projects"
        className="text-sm text-brand hover:underline dark:text-sky-400"
      >
        ← Cancelar
      </Link>

      <h1 className="mt-2 text-3xl font-bold text-brand dark:text-sky-400">Nuevo proyecto</h1>

      <Stepper currentStep={step} />

      <div className="rounded-xl bg-white p-6 shadow dark:bg-slate-800 dark:shadow-slate-950/50">
        {step === 1 && (
          <form onSubmit={handleSubmitStep1} className="flex flex-col gap-4">
            <h2 className="text-lg font-semibold">Datos del proyecto</h2>

            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Nombre *</span>
              <input
                type="text"
                required
                maxLength={255}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Ej: Edificio Belgrano, Torre A"
                className="rounded-md border border-slate-300 px-3 py-2 focus:border-brand focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-400"
              />
            </label>

            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Descripción</span>
              <textarea
                rows={4}
                maxLength={2000}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Tipo de obra, ubicación, observaciones..."
                className="resize-none rounded-md border border-slate-300 px-3 py-2 focus:border-brand focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-400"
              />
              <span className="text-xs text-slate-500 dark:text-slate-400">
                Opcional · {description.length}/2000
              </span>
            </label>

            {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

            <div className="mt-2 flex justify-end">
              <button
                type="submit"
                disabled={submitting || !name.trim()}
                className="rounded-md bg-brand px-5 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
              >
                {submitting ? "Guardando..." : "Siguiente →"}
              </button>
            </div>
          </form>
        )}

        {step === 2 && project && (
          <div className="flex flex-col gap-4">
            <h2 className="text-lg font-semibold">Subir plano del proyecto</h2>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              Subí un PDF del plano. El sistema lo rasteriza a 300 DPI y lo binariza
              automáticamente para que puedas visualizarlo y trabajarlo después.
            </p>

            <label
              className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition ${
                uploading
                  ? "border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900"
                  : "border-slate-300 hover:border-brand dark:border-slate-600 dark:hover:border-sky-400"
              }`}
            >
              <input
                type="file"
                accept="application/pdf"
                onChange={handleUpload}
                disabled={uploading}
                className="hidden"
              />
              <UploadIcon />
              <span className="font-medium">
                {uploading
                  ? "Procesando PDF (rasterizando + binarizando)..."
                  : "Hacé clic para elegir un PDF"}
              </span>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                Máximo 50 MB · solo archivos .pdf
              </span>
            </label>

            {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

            <div className="mt-2 flex items-center justify-between">
              <button
                type="button"
                onClick={() => setStep(1)}
                disabled={uploading}
                className="text-sm text-slate-500 hover:text-slate-900 disabled:opacity-50 dark:text-slate-400 dark:hover:text-slate-100"
              >
                ← Volver
              </button>
              <button
                type="button"
                onClick={skipUpload}
                disabled={uploading}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
              >
                Saltar y subir luego
              </button>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

function Stepper({ currentStep }: { currentStep: Step }) {
  return (
    <ol className="my-6 flex items-center gap-2">
      {STEPS.map((s, idx) => {
        const active = s.num === currentStep;
        const done = s.num < currentStep;
        return (
          <li key={s.num} className="flex flex-1 items-center gap-2">
            <div
              className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-sm font-semibold transition ${
                active
                  ? "border-brand bg-brand text-white dark:border-sky-400 dark:bg-sky-400 dark:text-slate-900"
                  : done
                    ? "border-brand bg-white text-brand dark:border-sky-400 dark:bg-slate-800 dark:text-sky-400"
                    : "border-slate-300 bg-white text-slate-400 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-500"
              }`}
            >
              {done ? "✓" : s.num}
            </div>
            <span
              className={`text-sm ${
                active
                  ? "font-semibold text-slate-900 dark:text-slate-100"
                  : "text-slate-500 dark:text-slate-400"
              }`}
            >
              {s.label}
            </span>
            {idx < STEPS.length - 1 && (
              <div className="ml-2 h-px flex-1 bg-slate-300 dark:bg-slate-600" />
            )}
          </li>
        );
      })}
    </ol>
  );
}

function UploadIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="32"
      height="32"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="text-slate-400 dark:text-slate-500"
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  );
}

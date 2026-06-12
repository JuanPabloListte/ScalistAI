"use client";

import { useEffect, useState } from "react";

import { api, type Plan, type Project } from "@/lib/api";

export function Step2Plan({
  project,
  onUploaded,
  onBack,
}: {
  project: Project;
  onUploaded: (plan?: Plan) => void;
  onBack: () => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [existingPlans, setExistingPlans] = useState<Plan[] | null>(null);

  useEffect(() => {
    let mounted = true;
    api
      .listPlans(project.id)
      .then((plans) => {
        if (mounted) setExistingPlans(plans);
      })
      .catch(() => {
        if (mounted) setExistingPlans([]);
      });
    return () => {
      mounted = false;
    };
  }, [project.id]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const plan = await api.uploadPlan(project.id, file);
      onUploaded(plan);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido");
      setUploading(false);
      e.target.value = "";
    }
  }

  const hasPlan = (existingPlans?.length ?? 0) > 0;

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold">Subir plano del proyecto</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Subí el plano en PDF, DXF o DWG. Si es PDF, en el paso siguiente asignás
        qué páginas usar para cada tipo de detección. Si es DXF/DWG, en el paso
        siguiente mapeás las capas del archivo a tipos de elementos, con la
        precisión exacta del CAD.
      </p>

      {hasPlan && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
          ✓ Ya tenés {existingPlans!.length} plano
          {existingPlans!.length > 1 ? "s" : ""} subido
          {existingPlans!.length > 1 ? "s" : ""}. Podés subir otro o continuar.
        </div>
      )}

      <label
        className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition ${
          uploading
            ? "border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900"
            : "border-slate-300 hover:border-brand dark:border-slate-600 dark:hover:border-sky-400"
        }`}
      >
        <input
          type="file"
          accept="application/pdf,.pdf,.dxf,.dwg"
          onChange={handleUpload}
          disabled={uploading}
          className="hidden"
        />
        <UploadIcon />
        <span className="font-medium">
          {uploading
            ? "Procesando plano..."
            : hasPlan
              ? "Subir otro plano"
              : "Hacé clic para elegir un archivo"}
        </span>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          Máximo 50 MB · archivos .pdf, .dxf o .dwg
        </span>
      </label>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      <div className="mt-2 flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          disabled={uploading}
          className="text-sm text-slate-500 hover:text-slate-900 disabled:opacity-50 dark:text-slate-400 dark:hover:text-slate-100"
        >
          ← Volver
        </button>
        <button
          type="button"
          onClick={() => onUploaded(existingPlans?.[0])}
          disabled={uploading || !hasPlan}
          className="rounded-md bg-brand px-5 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
          title={hasPlan ? "" : "Subí al menos un plano para continuar"}
        >
          Siguiente →
        </button>
      </div>
    </div>
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

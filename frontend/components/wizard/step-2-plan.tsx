"use client";

import { useEffect, useState } from "react";

import { api, type Plan, type Project } from "@/lib/api";
import { IfcParseProgress, IfcQualityCard, planErrorMessage } from "@/components/ifc-status";

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
  const [latestPlan, setLatestPlan] = useState<Plan | null>(null);

  useEffect(() => {
    let mounted = true;
    api
      .listPlans(project.id)
      .then((plans) => {
        if (!mounted) return;
        setExistingPlans(plans);
        const ifc = plans.filter((p) =>
          p.original_filename?.toLowerCase().endsWith(".ifc"),
        );
        setLatestPlan(ifc[0] ?? plans[0] ?? null);
      })
      .catch(() => {
        if (mounted) setExistingPlans([]);
      });
    return () => {
      mounted = false;
    };
  }, [project.id]);

  // Poll mientras el último IFC sigue processing (progreso + semáforo).
  useEffect(() => {
    if (!latestPlan || latestPlan.status !== "processing") return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const plans = await api.listPlans(project.id);
        if (cancelled) return;
        setExistingPlans(plans);
        const ifc = plans.filter((p) =>
          p.original_filename?.toLowerCase().endsWith(".ifc"),
        );
        const current =
          ifc.find((p) => p.id === latestPlan!.id) ?? ifc[0] ?? null;
        setLatestPlan(current);
        if (current?.status === "processing") {
          timer = setTimeout(poll, 2000);
        }
      } catch {
        if (!cancelled) timer = setTimeout(poll, 4000);
      }
    }

    timer = setTimeout(poll, 2000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [project.id, latestPlan?.id, latestPlan?.status]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    // PIVOTE IFC: validación dura (el `accept` del input es solo un hint del
    // selector). Quitar este bloque al reactivar PDF/DXF/DWG.
    if (!file.name.toLowerCase().endsWith(".ifc")) {
      setError("Por ahora solo aceptamos modelos BIM en formato .ifc. La carga de PDF/DXF/DWG está temporalmente deshabilitada.");
      e.target.value = "";
      return;
    }
    const MAX_IFC_BYTES = 500 * 1024 * 1024;
    if (file.size > MAX_IFC_BYTES) {
      setError("El archivo supera el máximo de 500 MB.");
      e.target.value = "";
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const plan = await api.uploadPlan(project.id, file);
      setLatestPlan(plan);
      setExistingPlans((prev) => [plan, ...(prev ?? []).filter((p) => p.id !== plan.id)]);
      onUploaded(plan);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido");
      e.target.value = "";
    } finally {
      setUploading(false);
    }
  }

  const hasPlan = (existingPlans?.length ?? 0) > 0;
  const processing = latestPlan?.status === "processing";
  const failed =
    latestPlan?.status === "error" || latestPlan?.status === "failed";

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold">Subir modelo BIM (IFC)</h2>
      {/* ─── PIVOTE IFC (jul-2026): la carga de PDF/DXF/DWG está DESACTIVADA
          temporalmente — el MVP se centra en el flujo IFC, que devuelve el
          cómputo exacto. Para REACTIVAR los otros formatos: restaurar el
          `accept` multi-formato del input y el copy original de abajo.
          Copy original:
            "Subí el plano en PDF, DXF o DWG. Si es PDF, en el paso siguiente
             asignás qué páginas usar para cada tipo de detección. Si es
             DXF/DWG, en el paso siguiente mapeás las capas del archivo a
             tipos de elementos, con la precisión exacta del CAD."
          accept original: "application/pdf,.pdf,.dxf,.dwg,.ifc"          ─── */}
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Subí el modelo BIM en formato <strong>IFC</strong> (exportado desde
        Revit, ArchiCAD u otro software BIM). El cómputo de materiales sale
        exacto del modelo: cantidades, niveles y recetas por elemento, directo
        al presupuesto.
      </p>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Tip: al exportar el IFC activá “base quantities” e incluí los ambientes
        (rooms/spaces) para obtener superficies exactas.
      </p>

      {hasPlan && !processing && !failed && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
          ✓ Ya tenés {existingPlans!.length} plano
          {existingPlans!.length > 1 ? "s" : ""} subido
          {existingPlans!.length > 1 ? "s" : ""}. Podés subir otro o continuar.
        </div>
      )}

      {latestPlan?.ifc_quality && (
        <IfcQualityCard quality={latestPlan.ifc_quality} />
      )}

      {processing && latestPlan && (
        <div className="rounded-md border border-sky-200 bg-sky-50 px-3 py-3 dark:border-sky-500/30 dark:bg-sky-500/10">
          <IfcParseProgress plan={latestPlan} />
        </div>
      )}

      {failed && latestPlan && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          {planErrorMessage(
            latestPlan,
            "No se pudo procesar el modelo BIM. Subí de nuevo el archivo .ifc.",
          )}
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
          // PIVOTE IFC: accept restringido a .ifc (antes: "application/pdf,.pdf,.dxf,.dwg,.ifc")
          accept=".ifc"
          onChange={handleUpload}
          disabled={uploading}
          className="hidden"
        />
        <UploadIcon />
        <span className="font-medium">
          {uploading
            ? "Subiendo archivo…"
            : hasPlan
              ? "Subir otro modelo"
              : "Hacé clic para elegir un archivo .ifc"}
        </span>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {/* PIVOTE IFC — copy original: "PDF, DXF o DWG (máx 50 MB) · modelo BIM IFC (máx 500 MB)" */}
          Modelo BIM IFC (máx 500 MB)
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

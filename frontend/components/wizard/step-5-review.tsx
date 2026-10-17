"use client";

import { useEffect, useState } from "react";

import { api, type Plan, type Project, type ProjectBudgetView } from "@/lib/api";
import { IfcParseProgress, IfcQualityCard, planErrorMessage } from "@/components/ifc-status";
import { ShoppingList } from "@/components/price-review";

import { FEATURES } from "@/lib/features";
import { BUILDING_FIELDS } from "./step-4-building";

export function Step5Review({
  project,
  onActivate,
  onBack,
  onEditStep,
}: {
  project: Project;
  onActivate: (project: Project) => void;
  onBack: () => void;
  onEditStep: (step: number) => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bimStatus, setBimStatus] = useState<"unknown" | "ready" | "processing" | "error" | "none">(
    "unknown",
  );
  const [bimPlan, setBimPlan] = useState<Plan | null>(null);
  const [prices, setPrices] = useState<ProjectBudgetView | null>(null);

  useEffect(() => {
    api.getProjectPriceList(project.id).then(setPrices).catch(() => setPrices(null));
  }, [project.id]);

  // Bloquea "Crear proyecto" mientras el IFC sigue en el worker.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let tries = 0;
    const MAX_TRIES = 90;

    async function poll() {
      try {
        const plans = await api.listPlans(project.id);
        if (cancelled) return;
        const ifc = plans.filter((p) =>
          p.original_filename?.toLowerCase().endsWith(".ifc"),
        );
        if (ifc.length === 0) {
          setBimStatus(plans.length > 0 ? "ready" : "none");
          setBimPlan(null);
          return;
        }
        const ready = ifc.find((p) => p.status === "ready");
        if (ready) {
          setBimStatus("ready");
          setBimPlan(ready);
          return;
        }
        const proc = ifc.find((p) => p.status === "processing");
        if (proc) {
          setBimStatus("processing");
          setBimPlan(proc);
          if (tries < MAX_TRIES) {
            tries += 1;
            timer = setTimeout(poll, 2500);
          } else {
            setBimStatus("error");
            setError(
              "El procesamiento del modelo BIM está tardando demasiado. " +
                "Volvé al paso del modelo y subí el archivo de nuevo.",
            );
          }
          return;
        }
        const failed = ifc.find((p) => p.status === "error" || p.status === "failed");
        setBimStatus("error");
        setBimPlan(failed ?? ifc[0] ?? null);
        if (failed?.error_message) {
          setError(failed.error_message);
        }
      } catch {
        if (!cancelled) setBimStatus("none");
      }
    }

    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [project.id]);

  async function handleActivate() {
    setError(null);
    if (bimStatus === "processing") {
      setError("El modelo BIM todavía se está procesando. Esperá un momento.");
      return;
    }
    if (bimStatus === "error") {
      setError("El modelo BIM no está listo. Subí de nuevo el archivo .ifc.");
      return;
    }
    setSubmitting(true);
    try {
      // Re-check justo antes de activar (evita race con el worker).
      const plans = await api.listPlans(project.id);
      const ifc = plans.filter((p: Plan) =>
        p.original_filename?.toLowerCase().endsWith(".ifc"),
      );
      if (ifc.length > 0 && !ifc.some((p) => p.status === "ready")) {
        const stillProc = ifc.some((p) => p.status === "processing");
        const failed = ifc.find((p) => p.status === "error" || p.status === "failed");
        setBimStatus(stillProc ? "processing" : "error");
        setError(
          stillProc
            ? "El modelo BIM todavía se está procesando. Esperá un momento."
            : planErrorMessage(failed, "El modelo BIM no se pudo procesar. Subí de nuevo el .ifc."),
        );
        return;
      }
      const activated = await api.activateProject(project.id);
      onActivate(activated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error activando el proyecto");
    } finally {
      setSubmitting(false);
    }
  }

  const canActivate =
    !submitting && bimStatus !== "processing" && bimStatus !== "unknown" && bimStatus !== "error";

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold">Revisar y crear</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Revisá los datos antes de finalizar. Podés volver a cualquier paso desde
        el listado de arriba.
      </p>

      {bimStatus === "processing" && (
        <div className="rounded-md border border-sky-200 bg-sky-50 px-3 py-3 dark:border-sky-500/30 dark:bg-sky-500/10">
          {bimPlan ? (
            <IfcParseProgress plan={bimPlan} />
          ) : (
            <div className="flex items-center gap-2 text-xs text-sky-700 dark:text-sky-300">
              <div className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-sky-300 border-t-sky-600" />
              Procesando el modelo BIM… el proyecto se podrá crear cuando termine el cómputo.
            </div>
          )}
        </div>
      )}
      {bimStatus === "ready" && bimPlan?.ifc_quality && (
        <IfcQualityCard quality={bimPlan.ifc_quality} />
      )}
      {bimStatus === "ready" && !bimPlan?.ifc_quality && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
          ✓ Modelo BIM listo para el presupuesto.
        </div>
      )}
      {bimStatus === "error" && bimPlan && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          {planErrorMessage(bimPlan, "El modelo BIM no está listo. Subí de nuevo el archivo .ifc.")}
        </div>
      )}

      <Section title="Datos básicos" onEdit={() => onEditStep(1)}>
        <Row label="Nombre" value={project.name} />
        <Row label="Descripción" value={project.description || "—"} />
      </Section>

      {/* Steps: 1 Datos · 2 Modelo · 3 Precios · 4 Ubicación · 5 Construcción (oculto) · 6 Review */}
      <Section title="Presupuesto del proveedor" onEdit={() => onEditStep(3)}>
        {prices?.price_list ? (
          <>
            <Row label="Archivo" value={prices.price_list.filename} />
            {prices.price_list.supplier && <Row label="Proveedor" value={prices.price_list.supplier} />}
            <Row label="Reglas de cómputo" value={prices.rule_set?.name ?? "—"} />
            <Row
              label="Materiales (neto)"
              value={
                prices.budget
                  ? prices.budget.totals.net.toLocaleString("es-AR", {
                      style: "currency", currency: "ARS", maximumFractionDigits: 0,
                    })
                  : "se calcula cuando termine el modelo"
              }
            />
            {prices.budget && prices.budget.counts.sin_precio > 0 && (
              <Row label="Sin precio" value={`${prices.budget.counts.sin_precio} ítems`} />
            )}
          </>
        ) : (
          <Row label="Archivo" value="Sin cargar (podés agregarlo después)" />
        )}
      </Section>

      {/* Cierre: qué hay que comprar y cuánto sale, antes de crear el proyecto. */}
      {prices?.budget && (
        <div className="rounded-md border border-slate-200 p-4 dark:border-slate-700">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h3 className="font-semibold text-slate-900 dark:text-slate-100">Lista de compras</h3>
            {prices.budget.counts.sin_precio > 0 && (
              <button
                type="button"
                onClick={() => onEditStep(3)}
                className="text-xs text-amber-600 hover:underline dark:text-amber-400"
              >
                {prices.budget.counts.sin_precio} ítems sin precio · revisar
              </button>
            )}
          </div>
          <ShoppingList budget={prices.budget} />
        </div>
      )}

      <Section title="Localización" onEdit={() => onEditStep(4)}>
        <Row label="Dirección" value={project.address || "—"} />
        <Row
          label="Coordenadas"
          value={
            project.latitude !== null && project.longitude !== null
              ? `${project.latitude.toFixed(5)}, ${project.longitude.toFixed(5)}`
              : "—"
          }
        />
        {project.city && <Row label="Ciudad" value={project.city} />}
        {project.country && <Row label="País" value={project.country} />}
      </Section>

      {FEATURES.wizardBuildingStep && (
      <Section title="Construcción" onEdit={() => onEditStep(5)}>
        <Row
          label="Tipo"
          value={
            project.building_type
              ? capitalize(project.building_type)
              : "—"
          }
        />
        {project.building_type && project.building_info &&
          BUILDING_FIELDS[project.building_type].map((field) => (
            <Row
              key={field.key}
              label={field.label}
              value={`${project.building_info?.[field.key] ?? "—"}${
                field.suffix ? ` ${field.suffix}` : ""
              }`}
            />
          ))}
      </Section>
      )}

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}


      <div className="mt-4 flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          disabled={submitting}
          className="text-sm text-slate-500 hover:text-slate-900 disabled:opacity-50 dark:text-slate-400 dark:hover:text-slate-100"
        >
          ← Volver
        </button>
        <button
          type="button"
          onClick={handleActivate}
          disabled={!canActivate}
          className="rounded-md bg-brand px-6 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
          title={
            bimStatus === "processing"
              ? "Esperá a que termine el procesamiento del BIM"
              : bimStatus === "error"
                ? "El modelo BIM falló"
                : ""
          }
        >
          {submitting
            ? "Creando..."
            : bimStatus === "processing"
              ? "Esperando BIM…"
              : "Crear proyecto ✓"}
        </button>
      </div>

    </div>
  );
}

function Section({
  title,
  onEdit,
  children,
}: {
  title: string;
  onEdit: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-slate-200 p-4 dark:border-slate-700">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
        <button
          type="button"
          onClick={onEdit}
          className="text-sm text-brand hover:underline dark:text-sky-400"
        >
          Editar
        </button>
      </div>
      <dl className="space-y-1 text-sm">{children}</dl>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="text-right text-slate-900 dark:text-slate-100">{value}</dd>
    </div>
  );
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

"use client";

import { useState } from "react";

import { api, type Project } from "@/lib/api";

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

  async function handleActivate() {
    setError(null);
    setSubmitting(true);
    try {
      const activated = await api.activateProject(project.id);
      onActivate(activated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error activando el proyecto");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold">Revisar y crear</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Revisá los datos antes de finalizar. Podés volver a cualquier paso desde
        el listado de arriba.
      </p>

      <Section title="Datos básicos" onEdit={() => onEditStep(1)}>
        <Row label="Nombre" value={project.name} />
        <Row label="Descripción" value={project.description || "—"} />
      </Section>

      <Section title="Localización" onEdit={() => onEditStep(3)}>
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

      <Section title="Construcción" onEdit={() => onEditStep(4)}>
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

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      <div className="mt-2 flex items-center justify-between">
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
          disabled={submitting}
          className="rounded-md bg-brand px-6 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {submitting ? "Creando..." : "Crear proyecto ✓"}
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

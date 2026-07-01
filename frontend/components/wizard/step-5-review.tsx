"use client";

import Link from "next/link";
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
  const [allowTraining, setAllowTraining] = useState(true);
  const [showTerms, setShowTerms] = useState(false);

  async function handleActivate() {
    setError(null);
    setSubmitting(true);
    try {
      if (!allowTraining) {
        await api.setTrainingConsent(project.id, false);
      }
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

      <div className="mt-2 flex items-start gap-3 rounded-md bg-slate-50 p-4 dark:bg-slate-800/50">
        <div className="flex h-5 items-center">
          <input
            id="allow-training"
            type="checkbox"
            checked={allowTraining}
            onChange={(e) => setAllowTraining(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand dark:border-slate-600 dark:bg-slate-900"
          />
        </div>
        <div className="text-sm">
          <label htmlFor="allow-training" className="font-medium text-slate-700 dark:text-slate-200">
            Acepto compartir estos planos anonimizados para entrenar el modelo
          </label>
          <p className="text-slate-500 dark:text-slate-400">
            Al marcar esta casilla, permitís que los datos de este proyecto se usen de forma segura y anónima para mejorar ScalistAI. Podés leer más en los{" "}
            <button type="button" onClick={() => setShowTerms(true)} className="font-semibold text-brand hover:underline dark:text-sky-400">
              Términos y Condiciones
            </button>.
          </p>
        </div>
      </div>

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
          disabled={submitting}
          className="rounded-md bg-brand px-6 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {submitting ? "Creando..." : "Crear proyecto ✓"}
        </button>
      </div>

      {showTerms && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-sm">
          <div className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-xl bg-white p-6 shadow-2xl dark:bg-slate-900 dark:ring-1 dark:ring-slate-800">
            <button onClick={() => setShowTerms(false)} className="absolute right-4 top-4 text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100">
              <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
            <h2 className="mb-4 pr-8 text-2xl font-bold text-slate-900 dark:text-white">Términos y Condiciones de Uso de Datos</h2>
            <div className="space-y-4 text-sm text-slate-600 dark:text-slate-300">
              <p><strong>1. Privacidad y Propiedad Intelectual:</strong> En ScalistAI entendemos que los planos arquitectónicos y los diseños son propiedad intelectual confidencial de tu estudio y tus clientes. Mantenemos la confidencialidad estricta de todos los documentos originales subidos a la plataforma.</p>
              <p><strong>2. Entrenamiento del Modelo (Opt-Out):</strong> Si elegís dejarnos usar tus datos para entrenamiento, ScalistAI procesará la geometría básica (líneas de muros, recintos y aberturas) para generar "variaciones sintéticas". Extraemos exclusivamente las coordenadas geométricas puras, las distorsionamos aleatoriamente, y las usamos como casos de prueba anónimos para enseñarle a la IA a reconocer muros con mayor precisión.</p>
              <p><strong>3. Anonimización Garantizada:</strong> Toda la información que pueda identificar a un cliente, como los cajetines, rótulos, direcciones, nombres de proyectos, textos descriptivos, y cotas numéricas, <strong>es ignorada y destruida</strong> antes de que la geometría entre al motor de entrenamiento. El modelo solo ve "líneas blancas sobre fondo negro".</p>
              <p><strong>4. Revocación del Consentimiento:</strong> Podés elegir no participar en este programa en cualquier momento desmarcando la casilla de entrenamiento al crear un proyecto, o desactivándolo desde la configuración del proyecto. Si lo hacés, tus planos quedarán en un entorno aislado (Sandboxed) y no contribuirán al modelo global de ScalistAI.</p>
            </div>
            <div className="mt-8 flex justify-end">
              <button type="button" onClick={() => setShowTerms(false)} className="rounded-md bg-brand px-5 py-2 font-semibold text-white hover:bg-brand-dark">
                Entendido
              </button>
            </div>
          </div>
        </div>
      )}
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

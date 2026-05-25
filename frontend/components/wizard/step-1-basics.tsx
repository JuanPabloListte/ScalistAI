"use client";

import { useState } from "react";

import { api, type Project } from "@/lib/api";

export function Step1Basics({
  project,
  onCreated,
}: {
  project: Project | null;
  onCreated: (project: Project) => void;
}) {
  const [name, setName] = useState(project?.name ?? "");
  const [description, setDescription] = useState(project?.description ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setError(null);
    setSubmitting(true);
    try {
      const result = project
        ? await api.updateProject(project.id, {
            name: name.trim(),
            description: description.trim() || null,
          })
        : await api.createProject(name.trim(), description);
      onCreated(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
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
          placeholder="Tipo de obra, observaciones..."
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
  );
}

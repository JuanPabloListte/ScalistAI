"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, type Project } from "@/lib/api";
import { BUILDING_FIELDS } from "@/components/wizard/step-4-building";

const TYPE_LABEL: Record<string, string> = {
  casa: "Casa",
  edificio: "Edificio",
  condominio: "Condominio",
  comercial: "Comercial",
};

export default function ProjectsPage() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [planCounts, setPlanCounts] = useState<Record<number, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<Project | null>(null);
  const [deleting, setDeleting] = useState<Project | null>(null);

  useEffect(() => {
    api
      .listProjects()
      .then(async (list) => {
        setProjects(list);
        // Traer conteo de planos en paralelo. Errores por proyecto se ignoran.
        const counts = await Promise.all(
          list.map((p) =>
            api
              .listPlans(p.id)
              .then((plans) => [p.id, plans.length] as const)
              .catch(() => [p.id, 0] as const),
          ),
        );
        setPlanCounts(Object.fromEntries(counts));
      })
      .catch((err) => {
        if (err instanceof Error && err.message.includes("401")) {
          router.push("/login");
        } else {
          setError(err.message);
        }
      })
      .finally(() => setLoading(false));
  }, [router]);

  function handleUpdated(updated: Project) {
    setProjects((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
    setEditing(null);
  }

  function handleDeleted(id: number) {
    setProjects((prev) => prev.filter((p) => p.id !== id));
    setDeleting(null);
  }

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-brand dark:text-sky-400">Proyectos</h1>
      </header>

      <div className="mb-8 flex justify-end">
        <Link
          href="/projects/new"
          className="rounded-md bg-brand px-5 py-2 font-semibold text-white hover:bg-brand-dark"
        >
          + Nuevo proyecto
        </Link>
      </div>

      {error && <p className="mb-4 text-sm text-red-600 dark:text-red-400">{error}</p>}

      {loading ? (
        <p className="text-slate-500 dark:text-slate-400">Cargando...</p>
      ) : projects.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-slate-300 px-6 py-12 text-center text-slate-500 dark:border-slate-700 dark:text-slate-400">
          <p className="mb-3">Todavía no tenés proyectos.</p>
          <Link
            href="/projects/new"
            className="font-medium text-brand hover:underline dark:text-sky-400"
          >
            Creá el primero →
          </Link>
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => {
            const isDraft = p.status === "draft";
            const href = isDraft ? `/projects/new?id=${p.id}` : `/projects/${p.id}`;
            const planCount = planCounts[p.id];
            const buildingFieldsList = p.building_type
              ? BUILDING_FIELDS[p.building_type]
              : [];
            return (
              <li
                key={p.id}
                className="group relative flex flex-col rounded-xl bg-white p-4 shadow transition hover:shadow-md dark:bg-slate-800 dark:shadow-slate-950/50"
              >
                <div className="absolute right-2 top-2 flex items-center gap-1 opacity-0 transition group-hover:opacity-100">
                  <IconButton
                    label="Editar proyecto"
                    onClick={() => setEditing(p)}
                  >
                    <MoreIcon />
                  </IconButton>
                  <IconButton
                    label="Eliminar proyecto"
                    variant="danger"
                    onClick={() => setDeleting(p)}
                  >
                    <TrashIcon />
                  </IconButton>
                </div>

                <Link href={href} className="flex flex-1 flex-col">
                  <div className="flex flex-wrap items-center gap-2 pr-16">
                    <h2 className="font-semibold text-brand dark:text-sky-400">{p.name}</h2>
                    {isDraft && (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/50 dark:text-amber-300">
                        Borrador · paso {p.wizard_step}/5
                      </span>
                    )}
                  </div>

                  {p.description && (
                    <p className="mt-2 line-clamp-3 text-sm text-slate-600 dark:text-slate-300">
                      {p.description}
                    </p>
                  )}

                  <div className="mt-3 flex flex-1 flex-col gap-1 text-xs text-slate-500 dark:text-slate-400">
                    {p.address && (
                      <p className="flex items-center gap-1">
                        <span aria-hidden>📍</span>
                        <span className="line-clamp-1">{p.address}</span>
                      </p>
                    )}
                    {p.building_type && (
                      <p className="flex items-center gap-1">
                        <span aria-hidden>🏗️</span>
                        <span>{TYPE_LABEL[p.building_type] ?? p.building_type}</span>
                        {p.building_info && buildingFieldsList[0] && (
                          <span className="text-slate-400 dark:text-slate-500">
                            · {p.building_info[buildingFieldsList[0].key]}
                            {buildingFieldsList[0].suffix
                              ? ` ${buildingFieldsList[0].suffix}`
                              : ""}
                          </span>
                        )}
                      </p>
                    )}
                    {planCount !== undefined && (
                      <p className="flex items-center gap-1">
                        <span aria-hidden>📄</span>
                        <span>
                          {planCount === 0
                            ? "Sin planos"
                            : `${planCount} plano${planCount === 1 ? "" : "s"}`}
                        </span>
                      </p>
                    )}
                  </div>

                  <p className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-400 dark:border-slate-700 dark:text-slate-500">
                    {new Date(p.created_at).toLocaleDateString()}
                    {isDraft ? " · Continuar wizard →" : " · Abrir editor →"}
                  </p>
                </Link>

                {!isDraft && (
                  <Link
                    href={`/projects/new?id=${p.id}&edit=1`}
                    className="mt-2 inline-block text-xs font-medium text-brand hover:underline dark:text-sky-400"
                  >
                    Editar datos del proyecto
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {editing && (
        <EditProjectModal
          project={editing}
          onCancel={() => setEditing(null)}
          onSaved={handleUpdated}
        />
      )}

      {deleting && (
        <DeleteProjectModal
          project={deleting}
          onCancel={() => setDeleting(null)}
          onDeleted={() => handleDeleted(deleting.id)}
        />
      )}
    </main>
  );
}

function IconButton({
  children,
  label,
  onClick,
  variant = "default",
}: {
  children: React.ReactNode;
  label: string;
  onClick: () => void;
  variant?: "default" | "danger";
}) {
  const baseColor =
    variant === "danger"
      ? "text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/50 dark:hover:text-red-400"
      : "text-slate-400 hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-700 dark:hover:text-slate-100";
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={`rounded-md p-2 transition ${baseColor}`}
    >
      {children}
    </button>
  );
}

function EditProjectModal({
  project,
  onCancel,
  onSaved,
}: {
  project: Project;
  onCancel: () => void;
  onSaved: (p: Project) => void;
}) {
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateProject(project.id, {
        name: name.trim(),
        description: description.trim() || null,
      });
      onSaved(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal onClose={onCancel}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold">Editar proyecto</h2>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Nombre *</span>
          <input
            type="text"
            required
            maxLength={255}
            value={name}
            onChange={(e) => setName(e.target.value)}
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
            className="resize-none rounded-md border border-slate-300 px-3 py-2 focus:border-brand focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-400"
          />
        </label>

        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

        <div className="mt-2 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={saving || !name.trim()}
            className="rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
          >
            {saving ? "Guardando..." : "Guardar cambios"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function DeleteProjectModal({
  project,
  onCancel,
  onDeleted,
}: {
  project: Project;
  onCancel: () => void;
  onDeleted: () => void;
}) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDelete() {
    setDeleting(true);
    setError(null);
    try {
      await api.deleteProject(project.id);
      onDeleted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido");
      setDeleting(false);
    }
  }

  return (
    <Modal onClose={deleting ? undefined : onCancel}>
      <div className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold">Eliminar proyecto</h2>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          ¿Eliminar <span className="font-semibold">{project.name}</span>? Se borran también
          todos los planos cargados y los archivos asociados. Esta acción no se puede deshacer.
        </p>

        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

        <div className="mt-2 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={deleting}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleDelete}
            disabled={deleting}
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
          >
            {deleting ? "Eliminando..." : "Eliminar"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function Modal({
  children,
  onClose,
}: {
  children: React.ReactNode;
  onClose?: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl dark:bg-slate-800"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

function MoreIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="5" cy="12" r="1.5" />
      <circle cx="12" cy="12" r="1.5" />
      <circle cx="19" cy="12" r="1.5" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
      <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

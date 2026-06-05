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
    <main className="mx-auto max-w-7xl px-6 py-10">
      <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">Proyectos</h1>
          <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
            {loading
              ? " "
              : projects.length === 0
                ? "Empezá tu primer proyecto"
                : `${projects.length} proyecto${projects.length === 1 ? "" : "s"} en total`}
          </p>
        </div>
      </header>

      {error && <p className="mb-4 text-sm text-red-600 dark:text-red-400">{error}</p>}

      {loading ? (
        <ProjectsLoadingSkeleton />
      ) : projects.length === 0 ? (
        <Link
          href="/projects/new"
          className="group block rounded-xl border-2 border-dashed border-slate-300 bg-white px-6 py-16 text-center transition hover:border-brand-400 hover:bg-brand-50/30 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-brand-500/60 dark:hover:bg-brand-500/5"
        >
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-400 transition group-hover:bg-brand-100 group-hover:text-brand-600 dark:bg-slate-800 dark:group-hover:bg-brand-500/10 dark:group-hover:text-brand-400">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
          </div>
          <p className="mb-1 text-base font-semibold text-slate-700 group-hover:text-brand-700 dark:text-slate-200 dark:group-hover:text-brand-300">
            Crear primer proyecto
          </p>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Subí un plano y empezá a cuantificar tus materiales.
          </p>
        </Link>
      ) : (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <li className="min-h-[180px]">
            <Link
              href="/projects/new"
              className="group flex h-full min-h-[180px] flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-300 bg-white p-5 text-center transition hover:border-brand-400 hover:bg-brand-50/30 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-brand-500/60 dark:hover:bg-brand-500/5"
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-400 transition group-hover:bg-brand-100 group-hover:text-brand-600 dark:bg-slate-800 dark:group-hover:bg-brand-500/10 dark:group-hover:text-brand-400">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
              </div>
              <span className="text-sm font-semibold text-slate-600 group-hover:text-brand-700 dark:text-slate-300 dark:group-hover:text-brand-300">
                Nuevo proyecto
              </span>
            </Link>
          </li>
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
                className="group relative flex flex-col rounded-xl border border-slate-200 bg-white p-5 transition hover:border-brand-300 hover:shadow-surface-lg dark:border-slate-800 dark:bg-slate-900 dark:hover:border-brand-500/40"
              >
                <div className="absolute right-2 top-2 flex items-center gap-0.5 opacity-0 transition group-hover:opacity-100 focus-within:opacity-100">
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
                    <h2 className="text-base font-semibold tracking-tight text-slate-900 transition-colors group-hover:text-brand-700 dark:text-slate-100 dark:group-hover:text-brand-300">{p.name}</h2>
                    {isDraft && (
                      <span className="rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                        Borrador · {p.wizard_step}/5
                      </span>
                    )}
                  </div>

                  {p.description && (
                    <p className="mt-1.5 line-clamp-2 text-sm text-slate-500 dark:text-slate-400">
                      {p.description}
                    </p>
                  )}

                  <div className="mt-3 flex flex-1 flex-col gap-1 text-xs text-slate-500 dark:text-slate-400">
                    {p.address && (
                      <p className="flex items-center gap-1.5">
                        <MapPinIcon />
                        <span className="line-clamp-1">{p.address}</span>
                      </p>
                    )}
                    {p.building_type && (
                      <p className="flex items-center gap-1.5">
                        <BuildingIcon />
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
                      <p className="flex items-center gap-1.5">
                        <FileIcon />
                        <span>
                          {planCount === 0
                            ? "Sin planos"
                            : `${planCount} plano${planCount === 1 ? "" : "s"}`}
                        </span>
                      </p>
                    )}
                  </div>

                  <p className="mt-4 border-t border-slate-100 pt-2.5 text-[11px] text-slate-400 dark:border-slate-800 dark:text-slate-500">
                    {new Date(p.created_at).toLocaleDateString()}
                    <span className="text-slate-300 dark:text-slate-600"> · </span>
                    <span className="font-medium text-slate-500 group-hover:text-brand-600 dark:text-slate-400 dark:group-hover:text-brand-400">
                      {isDraft ? "Continuar wizard →" : "Abrir editor →"}
                    </span>
                  </p>
                </Link>

                {!isDraft && (
                  <Link
                    href={`/projects/new?id=${p.id}&edit=1`}
                    className="mt-1.5 inline-block text-[11px] font-medium text-slate-500 hover:text-brand-600 hover:underline dark:text-slate-400 dark:hover:text-brand-400"
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

/** Skeleton de cards mientras cargan los proyectos. Tres filas placeholders
 *  con la misma altura y proporciones que las cards reales, así no salta
 *  el layout cuando vuelven los datos. */
function ProjectsLoadingSkeleton() {
  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <li
          key={i}
          className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900"
        >
          <div className="h-4 w-2/3 rounded bg-slate-200 dark:bg-slate-800 animate-pulse" />
          <div className="h-3 w-full rounded bg-slate-200/70 dark:bg-slate-800/70 animate-pulse" />
          <div className="h-3 w-5/6 rounded bg-slate-200/70 dark:bg-slate-800/70 animate-pulse" />
          <div className="mt-auto h-3 w-1/3 rounded bg-slate-200/50 dark:bg-slate-800/50 animate-pulse" />
        </li>
      ))}
    </ul>
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
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:focus:border-brand-400 dark:focus:ring-brand-400/20"
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
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={saving || !name.trim()}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:opacity-50 dark:bg-brand-500 dark:hover:bg-brand-400"
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
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleDelete}
            disabled={deleting}
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-700 disabled:opacity-50"
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-surface-lg dark:border-slate-700 dark:bg-slate-900"
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

function MapPinIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-slate-400">
      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  );
}

function BuildingIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-slate-400">
      <rect x="4" y="2" width="16" height="20" rx="2" ry="2" />
      <path d="M9 22v-4h6v4" />
      <path d="M8 6h.01" />
      <path d="M16 6h.01" />
      <path d="M12 6h.01" />
      <path d="M12 10h.01" />
      <path d="M12 14h.01" />
      <path d="M16 10h.01" />
      <path d="M16 14h.01" />
      <path d="M8 10h.01" />
      <path d="M8 14h.01" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-slate-400">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  );
}

"use client";

import { useEffect, useMemo, useState } from "react";

import { api, type JobRole } from "@/lib/api";

type Props = {
  /** null = equipo propio (GET /team/job-roles); number = admin org */
  organizationId?: number | null;
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  disabled?: boolean;
};

export function JobRolesPicker({
  organizationId = null,
  selectedIds,
  onChange,
  disabled,
}: Props) {
  const [roles, setRoles] = useState<JobRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [filter, setFilter] = useState("");

  function load() {
    setLoading(true);
    const req =
      organizationId != null
        ? api.listOrgJobRoles(organizationId)
        : api.listTeamJobRoles();
    req
      .then(setRoles)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [organizationId]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return roles;
    return roles.filter((r) => r.name.toLowerCase().includes(q));
  }, [roles, filter]);

  function toggle(id: number) {
    if (disabled) return;
    if (selectedIds.includes(id)) onChange(selectedIds.filter((x) => x !== id));
    else onChange([...selectedIds, id]);
  }

  return (
    <div className="block text-sm">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="font-semibold text-slate-700 dark:text-slate-300">
          Roles de obra
        </span>
        <button
          type="button"
          disabled={disabled}
          onClick={() => setShowAdd(true)}
          className="text-xs font-semibold text-brand-600 hover:underline disabled:opacity-50 dark:text-brand-400"
        >
          + Agregar rol
        </button>
      </div>
      <p className="mb-2 text-[11px] text-slate-500 dark:text-slate-400">
        Oficio / función en obra (podés elegir varios). Independiente del permiso Admin/Member.
      </p>

      <input
        type="search"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Buscar rol…"
        disabled={disabled || loading}
        className="mb-2 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
      />

      {loading ? (
        <p className="text-xs text-slate-500">Cargando roles…</p>
      ) : error ? (
        <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
      ) : (
        <div className="max-h-44 space-y-0.5 overflow-y-auto rounded-md border border-slate-200 p-1.5 dark:border-slate-700">
          {filtered.length === 0 ? (
            <p className="px-2 py-3 text-center text-xs text-slate-500">Sin resultados</p>
          ) : (
            filtered.map((r) => {
              const on = selectedIds.includes(r.id);
              return (
                <label
                  key={r.id}
                  className={`flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-slate-50 dark:hover:bg-slate-800/60 ${
                    on ? "bg-brand-50/70 dark:bg-brand-500/10" : ""
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={disabled}
                    onChange={() => toggle(r.id)}
                    className="rounded border-slate-300"
                  />
                  <span className="text-slate-800 dark:text-slate-200">{r.name}</span>
                </label>
              );
            })
          )}
        </div>
      )}

      {selectedIds.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {roles
            .filter((r) => selectedIds.includes(r.id))
            .map((r) => (
              <span
                key={r.id}
                className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300"
              >
                {r.name}
              </span>
            ))}
        </div>
      )}

      {showAdd && (
        <AddJobRoleModal
          organizationId={organizationId}
          onCancel={() => setShowAdd(false)}
          onCreated={(role) => {
            setRoles((prev) =>
              [...prev, role].sort((a, b) => a.name.localeCompare(b.name, "es")),
            );
            onChange([...selectedIds, role.id]);
            setShowAdd(false);
          }}
        />
      )}
    </div>
  );
}

/** Catálogo de roles de obra (solo admin). Listar + crear. */
export function ManageJobRolesModal({
  organizationId = null,
  onClose,
}: {
  organizationId?: number | null;
  onClose: () => void;
}) {
  const [roles, setRoles] = useState<JobRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [filter, setFilter] = useState("");

  function load() {
    setLoading(true);
    setError(null);
    const req =
      organizationId != null
        ? api.listOrgJobRoles(organizationId)
        : api.listTeamJobRoles();
    req
      .then(setRoles)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [organizationId]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return roles;
    return roles.filter((r) => r.name.toLowerCase().includes(q));
  }, [roles, filter]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-xl border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-900"
      >
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4 dark:border-slate-800">
          <div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
              Roles de obra
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Catálogo de oficios/funciones de la organización. Se asignan al crear o editar un usuario.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
            aria-label="Cerrar"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
          </button>
        </div>

        <div className="flex items-center gap-2 border-b border-slate-100 px-5 py-3 dark:border-slate-800">
          <input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Buscar rol…"
            className="min-w-0 flex-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          />
          <button
            type="button"
            onClick={() => setShowAdd(true)}
            className="shrink-0 rounded-md bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-700"
          >
            + Agregar rol
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
          {loading ? (
            <p className="text-sm text-slate-500">Cargando…</p>
          ) : error ? (
            <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
          ) : filtered.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-500">Sin roles</p>
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {filtered.map((r) => (
                <li
                  key={r.id}
                  className="flex items-center justify-between gap-2 py-2 text-sm text-slate-800 dark:text-slate-200"
                >
                  <span>{r.name}</span>
                  {r.is_default && (
                    <span className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
                      default
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="border-t border-slate-100 px-5 py-3 text-right dark:border-slate-800">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
          >
            Cerrar
          </button>
        </div>
      </div>

      {showAdd && (
        <AddJobRoleModal
          organizationId={organizationId}
          onCancel={() => setShowAdd(false)}
          onCreated={(role) => {
            setRoles((prev) =>
              [...prev, role].sort((a, b) => a.name.localeCompare(b.name, "es")),
            );
            setShowAdd(false);
          }}
        />
      )}
    </div>
  );
}

function AddJobRoleModal({
  organizationId,
  onCancel,
  onCreated,
}: {
  organizationId?: number | null;
  onCancel: () => void;
  onCreated: (role: JobRole) => void;
}) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handle(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const role =
        organizationId != null
          ? await api.createOrgJobRole(organizationId, name.trim())
          : await api.createTeamJobRole(name.trim());
      onCreated(role);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error");
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
      onClick={onCancel}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handle}
        className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-700 dark:bg-slate-900"
      >
        <h3 className="text-base font-semibold text-slate-900 dark:text-white">
          Nuevo rol de obra
        </h3>
        <p className="mt-1 text-xs text-slate-500">
          Se agrega al catálogo de tu organización y queda disponible para todos los usuarios.
        </p>
        <label className="mt-4 block text-sm">
          <span className="font-semibold text-slate-700 dark:text-slate-300">Nombre</span>
          <input
            required
            autoFocus
            maxLength={120}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ej. Impermeabilizador de terrazas"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          />
        </label>
        {err && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{err}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={saving || !name.trim()}
            className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {saving ? "Guardando…" : "Crear rol"}
          </button>
        </div>
      </form>
    </div>
  );
}

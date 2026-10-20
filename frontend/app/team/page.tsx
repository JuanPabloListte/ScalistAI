"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, isUnauthorized, type OrgUser, type User } from "@/lib/api";
import { JobRolesPicker, ManageJobRolesModal } from "@/components/job-roles-picker";
import { EditIcon, TrashIcon } from "@/components/icons";
import { LetterheadCard } from "@/components/letterhead-card";
import { ConfirmModal, Modal } from "@/components/modal";

export default function TeamPage() {
  const router = useRouter();
  const [me, setMe] = useState<User | null>(null);
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [showJobRoles, setShowJobRoles] = useState(false);
  const [editing, setEditing] = useState<OrgUser | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<OrgUser | null>(null);

  useEffect(() => {
    Promise.all([api.getMe(), api.listTeam()])
      .then(([m, list]) => {
        setMe(m);
        setUsers(list);
      })
      .catch((err: unknown) => {
        if (isUnauthorized(err)) router.push("/login");
        else setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoading(false));
  }, [router]);

  function reload() {
    api.listTeam().then(setUsers).catch(() => {});
  }

  const isAdmin = me?.is_superadmin || me?.role === "admin";

  if (loading) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-10">
        <p className="text-slate-500 dark:text-slate-400">Cargando...</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <header className="mb-6 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">
            Mi equipo
          </h1>
          <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
            {users.length} usuario{users.length === 1 ? "" : "s"} en tu organización
            {!isAdmin && " · solo lectura"}
          </p>
        </div>
        {isAdmin && (
          <button
            type="button"
            onClick={() => setShowJobRoles(true)}
            className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            Roles de obra
          </button>
        )}
      </header>

      {error && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </p>
      )}

      {isAdmin && <LetterheadCard canEdit />}

      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {isAdmin && (
          <li>
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="group flex h-full min-h-[120px] w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-300/50 bg-white/20 p-4 text-center backdrop-blur-sm transition hover:border-cyan-400 hover:bg-cyan-50/30 dark:border-white/10 dark:bg-slate-900/30 dark:hover:border-cyan-500/60 dark:hover:bg-cyan-500/10"
            >
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-slate-400 transition group-hover:bg-brand-100 group-hover:text-brand-600 dark:bg-slate-800 dark:group-hover:bg-brand-500/10 dark:group-hover:text-brand-400">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
              </div>
              <span className="text-sm font-semibold text-slate-600 group-hover:text-brand-700 dark:text-slate-300 dark:group-hover:text-brand-300">
                Nuevo usuario
              </span>
            </button>
          </li>
        )}

        {users.map((u) => {
          const isSelf = me?.id === u.id;
          return (
            <li
              key={u.id}
              className="group relative flex flex-col surface p-4 transition hover:border-cyan-300/50 hover:shadow-cyan-500/10 dark:hover:border-cyan-500/40 dark:hover:shadow-cyan-500/10"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">
                    {u.email}
                    {isSelf && (
                      <span className="ml-1.5 text-xs font-normal text-slate-400">(vos)</span>
                    )}
                  </p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                      u.role === "admin"
                        ? "bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300"
                        : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                    }`}>
                      {u.role}
                    </span>
                    {isAdmin &&
                      (u.job_roles ?? []).map((r) => (
                        <span
                          key={r.id}
                          className="rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 dark:bg-amber-950/40 dark:text-amber-300"
                        >
                          {r.name}
                        </span>
                      ))}
                  </div>
                </div>
                {isAdmin && !isSelf && (
                  <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
                    <button
                      onClick={() => setEditing(u)}
                      aria-label="Editar"
                      className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                    >
                      <EditIcon />
                    </button>
                    <button
                      onClick={() => setConfirmDelete(u)}
                      aria-label="Eliminar"
                      className="rounded-md p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40 dark:hover:text-red-400"
                    >
                      <TrashIcon />
                    </button>
                  </div>
                )}
              </div>
              <p className="mt-3 text-[11px] text-slate-400 dark:text-slate-500">
                Desde {new Date(u.created_at).toLocaleDateString()}
              </p>
            </li>
          );
        })}
      </ul>

      {isAdmin && showJobRoles && (
        <ManageJobRolesModal onClose={() => setShowJobRoles(false)} />
      )}


      {creating && (
        <UserModal
          mode="create"
          onCancel={() => setCreating(false)}
          onSubmit={async (payload) => {
            await api.createTeamUser(payload as any);
            setCreating(false);
            reload();
          }}
        />
      )}

      {editing && (
        <UserModal
          mode="edit"
          user={editing}
          onCancel={() => setEditing(null)}
          onSubmit={async (payload) => {
            await api.updateTeamUser(editing.id, payload);
            setEditing(null);
            reload();
          }}
        />
      )}

      {confirmDelete && (
        <ConfirmModal
          title="Eliminar usuario"
          message={`¿Eliminar a ${confirmDelete.email}? No se puede deshacer.`}
          onCancel={() => setConfirmDelete(null)}
          onConfirm={async () => {
            await api.deleteTeamUser(confirmDelete.id);
            setConfirmDelete(null);
            reload();
          }}
        />
      )}
    </main>
  );
}

function UserModal({
  mode,
  user,
  onCancel,
  onSubmit,
}: {
  mode: "create" | "edit";
  user?: OrgUser;
  onCancel: () => void;
  onSubmit: (payload: {
    email: string;
    password?: string;
    role: "admin" | "member";
    job_role_ids: number[];
  }) => Promise<void>;
}) {
  const [email, setEmail] = useState(user?.email ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"admin" | "member">((user?.role as "admin" | "member") ?? "member");
  const [jobRoleIds, setJobRoleIds] = useState<number[]>(
    () => (user?.job_roles ?? []).map((r) => r.id),
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handle(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const payload: {
        email: string;
        password?: string;
        role: "admin" | "member";
        job_role_ids: number[];
      } = {
        email: email.trim(),
        role,
        job_role_ids: jobRoleIds,
      };
      if (password) payload.password = password;
      await onSubmit(payload);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error");
      setSaving(false);
    }
  }

  return (
    <Modal size="lg" onClose={onCancel}>
      <form onSubmit={handle}>
        <h2 className="mb-4 text-lg font-semibold text-slate-900 dark:text-white">
          {mode === "create" ? "Nuevo usuario" : "Editar usuario"}
        </h2>

        <div className="space-y-4">
          <label className="block text-sm">
            <span className="font-semibold text-slate-700 dark:text-slate-300">Email</span>
            <input
              required
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            />
          </label>

          <label className="block text-sm">
            <span className="font-semibold text-slate-700 dark:text-slate-300">
              Password{" "}
              {mode === "edit" && (
                <span className="text-xs font-normal text-slate-500">(vacío = no cambiar)</span>
              )}
            </span>
            <input
              required={mode === "create"}
              type="text"
              minLength={mode === "create" ? 8 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            />
            {mode === "create" && (
              <span className="mt-1 block text-[10px] text-slate-500">Copiala antes de guardar.</span>
            )}
          </label>

          <label className="block text-sm">
            <span className="font-semibold text-slate-700 dark:text-slate-300">Permiso</span>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as "admin" | "member")}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            >
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
          </label>

          <JobRolesPicker
            selectedIds={jobRoleIds}
            onChange={setJobRoleIds}
            disabled={saving}
          />
        </div>

        {err && <p className="mt-4 text-sm text-red-600 dark:text-red-400">{err}</p>}

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="rounded-md border border-slate-300/50 bg-white/50 px-4 py-2 text-sm font-medium hover:bg-white/80 dark:border-white/10 dark:bg-slate-900/50 dark:text-slate-200 dark:hover:bg-slate-800/80"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={saving}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50 dark:bg-brand-500"
          >
            {saving ? "Guardando..." : "Guardar"}
          </button>
        </div>
      </form>
    </Modal>
  );
}


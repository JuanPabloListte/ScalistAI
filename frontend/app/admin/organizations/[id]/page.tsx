"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, type OrganizationDetail, type OrgUser } from "@/lib/api";

const STATUS_LABEL: Record<string, { label: string; tone: string }> = {
  active: { label: "Activa", tone: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300" },
  past_due: { label: "Vencida", tone: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300" },
  canceled: { label: "Cancelada", tone: "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300" },
  trialing: { label: "Trial", tone: "bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300" },
};

export default function OrgDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const orgId = parseInt(params.id, 10);

  const [org, setOrg] = useState<OrganizationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [creatingUser, setCreatingUser] = useState(false);
  const [editingUser, setEditingUser] = useState<OrgUser | null>(null);
  const [editingOrg, setEditingOrg] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<OrgUser | null>(null);
  const [confirmDeleteOrg, setConfirmDeleteOrg] = useState(false);

  useEffect(() => {
    if (!orgId) return;
    api
      .getOrganization(orgId)
      .then(setOrg)
      .catch((err: Error) => {
        if (err.message.includes("401")) router.push("/login");
        else if (err.message.includes("403")) setError("Solo superadmin puede ver esta página.");
        else setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [orgId, router]);

  function reload() {
    api.getOrganization(orgId).then(setOrg).catch(() => {});
  }

  if (loading) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-10">
        <p className="text-slate-500 dark:text-slate-400">Cargando...</p>
      </main>
    );
  }

  if (error || !org) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-10">
        <Link href="/admin/organizations" className="text-sm text-brand-600 hover:underline">← Volver</Link>
        <p className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
          {error ?? "Organización no encontrada."}
        </p>
      </main>
    );
  }

  const status = STATUS_LABEL[org.subscription_status] ?? {
    label: org.subscription_status,
    tone: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  };

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <Link href="/admin/organizations" className="text-sm text-brand-600 hover:underline">
        ← Organizaciones
      </Link>

      <header className="mt-3 mb-8 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">
              {org.name}
            </h1>
            <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${status.tone}`}>
              {status.label}
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Creada {new Date(org.created_at).toLocaleDateString()} · {org.users.length} usuario
            {org.users.length === 1 ? "" : "s"}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setEditingOrg(true)}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            Editar
          </button>
          <button
            onClick={() => setConfirmDeleteOrg(true)}
            className="rounded-md border border-red-200 bg-red-50 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-100 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300 dark:hover:bg-red-900/40"
          >
            Eliminar
          </button>
        </div>
      </header>

      <h2 className="mb-3 text-base font-semibold text-slate-800 dark:text-slate-200">
        Usuarios de la organización
      </h2>

      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <li>
          <button
            type="button"
            onClick={() => setCreatingUser(true)}
            className="group flex h-full min-h-[120px] w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-300 bg-white p-4 text-center transition hover:border-brand-400 hover:bg-brand-50/30 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-brand-500/60 dark:hover:bg-brand-500/5"
          >
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-slate-400 transition group-hover:bg-brand-100 group-hover:text-brand-600 dark:bg-slate-800 dark:group-hover:bg-brand-500/10 dark:group-hover:text-brand-400">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
            </div>
            <span className="text-sm font-semibold text-slate-600 group-hover:text-brand-700 dark:text-slate-300 dark:group-hover:text-brand-300">
              Nuevo usuario
            </span>
          </button>
        </li>

        {org.users.map((u) => (
          <li
            key={u.id}
            className="group relative flex flex-col rounded-xl border border-slate-200 bg-white p-4 transition hover:border-brand-300 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-brand-500/40"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">
                  {u.email}
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                    u.role === "admin"
                      ? "bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300"
                      : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                  }`}>
                    {u.role}
                  </span>
                  {u.is_superadmin && (
                    <span className="rounded-md bg-purple-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-purple-700 dark:bg-purple-950/40 dark:text-purple-300">
                      Superadmin
                    </span>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
                <button
                  onClick={() => setEditingUser(u)}
                  aria-label="Editar usuario"
                  className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                >
                  <EditIcon />
                </button>
                <button
                  onClick={() => setConfirmDelete(u)}
                  aria-label="Eliminar usuario"
                  className="rounded-md p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40 dark:hover:text-red-400"
                >
                  <TrashIcon />
                </button>
              </div>
            </div>
            <p className="mt-3 text-[11px] text-slate-400 dark:text-slate-500">
              Creado {new Date(u.created_at).toLocaleDateString()}
            </p>
          </li>
        ))}
      </ul>

      {creatingUser && (
        <UserModal
          mode="create"
          onCancel={() => setCreatingUser(false)}
          onSubmit={async (payload) => {
            await api.createOrgUser(org.id, payload);
            setCreatingUser(false);
            reload();
          }}
        />
      )}

      {editingUser && (
        <UserModal
          mode="edit"
          user={editingUser}
          onCancel={() => setEditingUser(null)}
          onSubmit={async (payload) => {
            await api.updateOrgUser(editingUser.id, payload);
            setEditingUser(null);
            reload();
          }}
        />
      )}

      {editingOrg && (
        <EditOrgModal
          org={org}
          onCancel={() => setEditingOrg(false)}
          onSubmit={async (payload) => {
            await api.updateOrganization(org.id, payload);
            setEditingOrg(false);
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
            await api.deleteOrgUser(confirmDelete.id);
            setConfirmDelete(null);
            reload();
          }}
        />
      )}

      {confirmDeleteOrg && (
        <ConfirmModal
          title="Eliminar organización"
          message={`¿Eliminar ${org.name}? Se borrarán todos los usuarios y proyectos. No se puede deshacer.`}
          onCancel={() => setConfirmDeleteOrg(false)}
          onConfirm={async () => {
            await api.deleteOrganization(org.id);
            router.push("/admin/organizations");
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
  onSubmit: (payload: { email: string; password: string; role: "admin" | "member" }) => Promise<void>;
}) {
  const [email, setEmail] = useState(user?.email ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"admin" | "member">((user?.role as "admin" | "member") ?? "member");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handle(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const payload: any = { email: email.trim(), role };
      if (password) payload.password = password;
      if (mode === "create") payload.password = password;
      await onSubmit(payload);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error");
      setSaving(false);
    }
  }

  return (
    <Modal onCancel={onCancel}>
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
              Password {mode === "edit" && <span className="text-xs font-normal text-slate-500">(dejar vacío para no cambiar)</span>}
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
              <span className="mt-1 block text-[10px] text-slate-500">Copiala antes de guardar, no se vuelve a mostrar.</span>
            )}
          </label>

          <label className="block text-sm">
            <span className="font-semibold text-slate-700 dark:text-slate-300">Rol</span>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as "admin" | "member")}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            >
              <option value="member">Member (usuario normal)</option>
              <option value="admin">Admin (puede gestionar el equipo)</option>
            </select>
          </label>
        </div>

        {err && <p className="mt-4 text-sm text-red-600 dark:text-red-400">{err}</p>}

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
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

function EditOrgModal({
  org,
  onCancel,
  onSubmit,
}: {
  org: OrganizationDetail;
  onCancel: () => void;
  onSubmit: (payload: { name?: string; subscription_status?: string }) => Promise<void>;
}) {
  const [name, setName] = useState(org.name);
  const [subscription, setSubscription] = useState(org.subscription_status);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handle(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      await onSubmit({ name: name.trim(), subscription_status: subscription });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error");
      setSaving(false);
    }
  }

  return (
    <Modal onCancel={onCancel}>
      <form onSubmit={handle}>
        <h2 className="mb-4 text-lg font-semibold text-slate-900 dark:text-white">Editar organización</h2>
        <div className="space-y-4">
          <label className="block text-sm">
            <span className="font-semibold text-slate-700 dark:text-slate-300">Nombre</span>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            />
          </label>
          <label className="block text-sm">
            <span className="font-semibold text-slate-700 dark:text-slate-300">Estado de suscripción</span>
            <select
              value={subscription}
              onChange={(e) => setSubscription(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            >
              <option value="active">Activa</option>
              <option value="trialing">Trial</option>
              <option value="past_due">Vencida</option>
              <option value="canceled">Cancelada</option>
            </select>
          </label>
        </div>
        {err && <p className="mt-4 text-sm text-red-600 dark:text-red-400">{err}</p>}
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={saving}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50 dark:bg-brand-500"
          >
            Guardar
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ConfirmModal({
  title,
  message,
  onCancel,
  onConfirm,
}: {
  title: string;
  message: string;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handle() {
    setLoading(true);
    setErr(null);
    try {
      await onConfirm();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error");
      setLoading(false);
    }
  }

  return (
    <Modal onCancel={loading ? undefined : onCancel}>
      <h2 className="text-lg font-semibold text-slate-900 dark:text-white">{title}</h2>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{message}</p>
      {err && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{err}</p>}
      <div className="mt-6 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={loading}
          className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          Cancelar
        </button>
        <button
          type="button"
          onClick={handle}
          disabled={loading}
          className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
        >
          {loading ? "Eliminando..." : "Eliminar"}
        </button>
      </div>
    </Modal>
  );
}

function Modal({
  children,
  onCancel,
}: {
  children: React.ReactNode;
  onCancel?: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-surface-lg dark:border-slate-700 dark:bg-slate-900"
      >
        {children}
      </div>
    </div>
  );
}

function EditIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4Z" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

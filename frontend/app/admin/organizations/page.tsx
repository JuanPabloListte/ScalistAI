"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, ApiError, isUnauthorized, type OrganizationListItem } from "@/lib/api";

const STATUS_LABEL: Record<string, { label: string; tone: string }> = {
  active: { label: "Activa", tone: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300" },
  past_due: { label: "Vencida", tone: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300" },
  canceled: { label: "Cancelada", tone: "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300" },
  trialing: { label: "Trial", tone: "bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300" },
};

export default function AdminOrganizationsPage() {
  const router = useRouter();
  const [orgs, setOrgs] = useState<OrganizationListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    api
      .listOrganizations()
      .then((list) => setOrgs(list))
      .catch((err: unknown) => {
        if (isUnauthorized(err)) router.push("/login");
        else if (err instanceof ApiError && err.status === 403)
          setError("Solo superadmin puede ver esta página.");
        else setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoading(false));
  }, [router]);

  function handleCreated(o: OrganizationListItem) {
    setOrgs((prev) => [o, ...prev]);
    setCreating(false);
  }

  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">
          Administración · Organizaciones
        </h1>
        <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
          {loading
            ? " "
            : orgs.length === 0
              ? "Aún no hay organizaciones"
              : `${orgs.length} organizacion${orgs.length === 1 ? "" : "es"}`}
        </p>
      </header>

      {error && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </p>
      )}

      {loading ? (
        <p className="text-slate-500 dark:text-slate-400">Cargando...</p>
      ) : (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <li className="min-h-[160px]">
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="group flex h-full min-h-[160px] w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-300 bg-white p-5 text-center transition hover:border-brand-400 hover:bg-brand-50/30 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-brand-500/60 dark:hover:bg-brand-500/5"
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-400 transition group-hover:bg-brand-100 group-hover:text-brand-600 dark:bg-slate-800 dark:group-hover:bg-brand-500/10 dark:group-hover:text-brand-400">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
              </div>
              <span className="text-sm font-semibold text-slate-600 group-hover:text-brand-700 dark:text-slate-300 dark:group-hover:text-brand-300">
                Nueva organización
              </span>
            </button>
          </li>

          {orgs.map((o) => {
            const status = STATUS_LABEL[o.subscription_status] ?? {
              label: o.subscription_status,
              tone: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
            };
            return (
              <li key={o.id}>
                <Link
                  href={`/admin/organizations/${o.id}`}
                  className="group flex h-full min-h-[160px] flex-col rounded-xl border border-slate-200 bg-white p-5 transition hover:border-brand-300 hover:shadow-surface-lg dark:border-slate-800 dark:bg-slate-900 dark:hover:border-brand-500/40"
                >
                  <div className="flex items-start justify-between gap-2">
                    <h2 className="text-base font-semibold text-slate-900 group-hover:text-brand-700 dark:text-slate-100 dark:group-hover:text-brand-300">
                      {o.name}
                    </h2>
                    <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${status.tone}`}>
                      {status.label}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-1 flex-col gap-1 text-xs text-slate-500 dark:text-slate-400">
                    <p>
                      <strong>{o.user_count}</strong> usuario{o.user_count === 1 ? "" : "s"}
                    </p>
                    <p>
                      <strong>{o.project_count}</strong> proyecto{o.project_count === 1 ? "" : "s"}
                    </p>
                  </div>
                  <p className="mt-4 border-t border-slate-100 pt-2.5 text-[11px] text-slate-400 dark:border-slate-800 dark:text-slate-500">
                    Creada {new Date(o.created_at).toLocaleDateString()}
                    <span className="text-slate-300 dark:text-slate-600"> · </span>
                    <span className="font-medium text-slate-500 group-hover:text-brand-600 dark:text-slate-400 dark:group-hover:text-brand-400">
                      Ver detalle →
                    </span>
                  </p>
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      {creating && <CreateOrgModal onCancel={() => setCreating(false)} onSaved={handleCreated} />}
    </main>
  );
}

function CreateOrgModal({
  onCancel,
  onSaved,
}: {
  onCancel: () => void;
  onSaved: (o: OrganizationListItem) => void;
}) {
  const [name, setName] = useState("");
  const [subscription, setSubscription] = useState("active");
  const [withAdmin, setWithAdmin] = useState(true);
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const detail = await api.createOrganization({
        name: name.trim(),
        subscription_status: subscription,
        admin_email: withAdmin ? adminEmail.trim() : undefined,
        admin_password: withAdmin ? adminPassword : undefined,
      });
      onSaved({
        ...detail,
        user_count: detail.users.length,
        project_count: 0,
      });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
      onClick={onCancel}
    >
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-surface-lg dark:border-slate-700 dark:bg-slate-900"
      >
        <h2 className="mb-1 text-lg font-semibold text-slate-900 dark:text-white">Nueva organización</h2>
        <p className="mb-5 text-xs text-slate-500 dark:text-slate-400">
          Creá una organización y opcionalmente su primer admin.
        </p>

        <div className="space-y-4">
          <label className="block text-sm">
            <span className="font-semibold text-slate-700 dark:text-slate-300">Nombre</span>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Estudio Pérez SRL"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
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

          <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={withAdmin}
                onChange={(e) => setWithAdmin(e.target.checked)}
              />
              <span className="font-semibold text-slate-700 dark:text-slate-300">Crear admin inicial</span>
            </label>
            {withAdmin && (
              <div className="mt-3 space-y-3">
                <label className="block text-sm">
                  <span className="text-xs font-medium text-slate-600 dark:text-slate-400">Email del admin</span>
                  <input
                    required={withAdmin}
                    type="email"
                    value={adminEmail}
                    onChange={(e) => setAdminEmail(e.target.value)}
                    placeholder="admin@empresa.com"
                    className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                  />
                </label>
                <label className="block text-sm">
                  <span className="text-xs font-medium text-slate-600 dark:text-slate-400">Password (mín. 8)</span>
                  <input
                    required={withAdmin}
                    type="text"
                    value={adminPassword}
                    onChange={(e) => setAdminPassword(e.target.value)}
                    minLength={8}
                    className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                  />
                  <span className="mt-1 block text-[10px] text-slate-500 dark:text-slate-400">
                    Copiala antes de guardar, no se vuelve a mostrar.
                  </span>
                </label>
              </div>
            )}
          </div>
        </div>

        {err && <p className="mt-4 text-sm text-red-600 dark:text-red-400">{err}</p>}

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={saving || !name.trim() || (withAdmin && (!adminEmail.trim() || adminPassword.length < 8))}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50 dark:bg-brand-500 dark:hover:bg-brand-400"
          >
            {saving ? "Creando..." : "Crear"}
          </button>
        </div>
      </form>
    </div>
  );
}

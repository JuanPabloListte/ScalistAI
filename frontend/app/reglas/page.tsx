"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ConfirmModal, Overlay } from "@/components/rule-sets-ui";
import { api, isUnauthorized, type RuleSet, type User } from "@/lib/api";

export default function RuleSetsPage() {
  const router = useRouter();
  const [me, setMe] = useState<User | null>(null);
  const [sets, setSets] = useState<RuleSet[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState<{ copyFrom: RuleSet | null } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<RuleSet | null>(null);

  useEffect(() => {
    Promise.all([api.getMe(), api.listRuleSets()])
      .then(([m, list]) => {
        setMe(m);
        setSets(list);
      })
      .catch((err: unknown) => {
        if (isUnauthorized(err)) router.push("/login");
        else setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoading(false));
  }, [router]);

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
            Reglas de cómputo
          </h1>
          <p className="mt-0.5 max-w-2xl text-sm text-slate-500 dark:text-slate-400">
            Cómo se pasa del modelo IFC a los productos del presupuesto del proveedor
            (cuánto cemento por m² de muro, cuántos ladrillos, cuánto hierro).
            Al crear un proyecto elegís qué juego usar.
            {!isAdmin && " · Solo lectura: los cambios los hace un admin."}
          </p>
        </div>
        {isAdmin && (
          <button
            type="button"
            onClick={() => setCreating({ copyFrom: sets.find((s) => s.is_default) ?? null })}
            className="shrink-0 rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-700"
          >
            + Nuevo juego
          </button>
        )}
      </header>

      {error && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </p>
      )}

      <ul className="grid gap-3 sm:grid-cols-2">
        {sets.map((s) => (
          <li key={s.id} className="surface flex flex-col p-5">
            <div className="flex items-start justify-between gap-3">
              <Link
                href={`/reglas/${s.id}`}
                className="text-base font-semibold text-slate-900 hover:underline dark:text-slate-100"
              >
                {s.name}
              </Link>
              {s.is_default && (
                <span className="shrink-0 rounded-md bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-700 dark:bg-brand-500/15 dark:text-brand-300">
                  Por defecto
                </span>
              )}
            </div>
            {s.description && (
              <p className="mt-1 line-clamp-2 text-sm text-slate-500 dark:text-slate-400">
                {s.description}
              </p>
            )}
            <p className="mt-2 text-xs text-slate-400">
              {s.rules.length} regla{s.rules.length === 1 ? "" : "s"} · actualizado{" "}
              {new Date(s.updated_at).toLocaleDateString("es-AR")}
            </p>
            <div className="mt-4 flex flex-wrap gap-2 text-sm">
              <Link
                href={`/reglas/${s.id}`}
                className="rounded-md border border-slate-300 px-3 py-1.5 font-medium hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
              >
                {isAdmin ? "Editar" : "Ver"}
              </Link>
              {isAdmin && (
                <>
                  <button
                    type="button"
                    onClick={() => setCreating({ copyFrom: s })}
                    className="rounded-md border border-slate-300 px-3 py-1.5 font-medium hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
                  >
                    Duplicar
                  </button>
                  <button
                    type="button"
                    disabled={sets.length <= 1}
                    title={sets.length <= 1 ? "Tiene que quedar al menos un juego" : undefined}
                    onClick={() => setConfirmDelete(s)}
                    className="rounded-md px-3 py-1.5 font-medium text-red-600 hover:bg-red-50 disabled:opacity-40 dark:text-red-400 dark:hover:bg-red-950/30"
                  >
                    Borrar
                  </button>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>

      {creating && (
        <CreateRuleSetModal
          sets={sets}
          initialCopyFrom={creating.copyFrom}
          onCancel={() => setCreating(null)}
          onCreated={(rs) => router.push(`/reglas/${rs.id}`)}
        />
      )}

      {confirmDelete && (
        <ConfirmModal
          title={`¿Borrar "${confirmDelete.name}"?`}
          body={
            confirmDelete.is_default
              ? "Es el juego por defecto: otro pasa a ser el predeterminado. Los proyectos que lo usaban quedan sin juego asignado."
              : "Los proyectos que lo usaban quedan sin juego asignado."
          }
          onCancel={() => setConfirmDelete(null)}
          onConfirm={async () => {
            await api.deleteRuleSet(confirmDelete.id);
            setConfirmDelete(null);
            setSets(await api.listRuleSets());
          }}
        />
      )}
    </main>
  );
}

function CreateRuleSetModal({
  sets,
  initialCopyFrom,
  onCancel,
  onCreated,
}: {
  sets: RuleSet[];
  initialCopyFrom: RuleSet | null;
  onCancel: () => void;
  onCreated: (rs: RuleSet) => void;
}) {
  const [name, setName] = useState(initialCopyFrom ? `${initialCopyFrom.name} (copia)` : "");
  const [copyFrom, setCopyFrom] = useState<string>(initialCopyFrom ? String(initialCopyFrom.id) : "");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const rs = await api.createRuleSet({
        name: name.trim(),
        copy_from_id: copyFrom ? Number(copyFrom) : null,
      });
      onCreated(rs);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error");
      setSaving(false);
    }
  }

  return (
    <Overlay onClose={onCancel}>
      <form onSubmit={submit}>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Nuevo juego de reglas</h2>
        <label className="mt-4 block text-sm">
          <span className="font-semibold text-slate-700 dark:text-slate-300">Nombre</span>
          <input
            required
            autoFocus
            maxLength={120}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ej. Obra económica"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          />
        </label>
        <label className="mt-3 block text-sm">
          <span className="font-semibold text-slate-700 dark:text-slate-300">Partir de</span>
          <select
            value={copyFrom}
            onChange={(e) => setCopyFrom(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          >
            {sets.map((s) => (
              <option key={s.id} value={s.id}>
                Copia de “{s.name}”
              </option>
            ))}
            <option value="">Vacío (sin reglas)</option>
          </select>
        </label>
        {err && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{err}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={saving || !name.trim()}
            className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {saving ? "Creando…" : "Crear"}
          </button>
        </div>
      </form>
    </Overlay>
  );
}

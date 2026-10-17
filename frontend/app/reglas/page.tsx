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
  const [query, setQuery] = useState("");

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
  const canEdit = (s: RuleSet) => (s.is_system ? !!me?.is_superadmin : !!isAdmin);
  const q = query.trim().toLowerCase();
  const visible = q
    ? sets.filter((s) =>
        [s.name, s.description ?? "", ...s.rules.map((r) => r.label)].some((t) => t.toLowerCase().includes(q)))
    : sets;

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
            {" "}El estándar se usa por defecto y no se modifica: duplicalo para tener tu propia versión.
            {!isAdmin && " · Solo lectura: los cambios los hace un admin."}
          </p>
        </div>
        {isAdmin && (
          <button
            type="button"
            onClick={() => setCreating({ copyFrom: sets.find((s) => s.is_system) ?? null })}
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

      {sets.length > 3 && (
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar juego o producto…"
          className="mb-4 w-full max-w-sm rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
        />
      )}

      <ul className="grid gap-3 sm:grid-cols-2">
        {visible.map((s) => (
          <li key={s.id} className="surface flex flex-col p-5">
            <div className="flex items-start justify-between gap-3">
              <Link
                href={`/reglas/${s.id}`}
                className="text-base font-semibold text-slate-900 hover:underline dark:text-slate-100"
              >
                {s.name}
              </Link>
              <div className="flex shrink-0 gap-1.5">
                {s.is_system && (
                  <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    Estándar
                  </span>
                )}
                {s.is_default && (
                  <span className="rounded-md bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-700 dark:bg-brand-500/15 dark:text-brand-300">
                    Por defecto
                  </span>
                )}
              </div>
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
                {canEdit(s) ? "Editar" : "Ver"}
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
                  {!s.is_system && <button
                    type="button"
                    onClick={() => setConfirmDelete(s)}
                    className="rounded-md px-3 py-1.5 font-medium text-red-600 hover:bg-red-50 disabled:opacity-40 dark:text-red-400 dark:hover:bg-red-950/30"
                  >
                    Borrar
                  </button>}
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
            "Los proyectos que lo usaban pasan a usar el juego estándar."
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

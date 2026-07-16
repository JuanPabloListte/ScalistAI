"use client";

import { useCallback, useEffect, useState } from "react";

import { api, type OrgUser, type ProjectMember } from "@/lib/api";

const ROLE_OPTIONS: { value: "jefe_obra" | "capataz" | "comitente"; label: string; hint: string }[] = [
  { value: "jefe_obra", label: "Jefe de obra", hint: "Todo: presupuesto, costos, plan y equipo" },
  { value: "capataz", label: "Capataz", hint: "Registra avance y ve el cronograma, sin importes" },
  { value: "comitente", label: "Comitente", hint: "Solo lectura de avance, sin nada financiero" },
];

/**
 * Equipo del proyecto: asigna a cada usuario un ROL DE PERMISO (jefe de obra /
 * capataz / comitente). Distinto del oficio (albañil, electricista…).
 * Si el proyecto no tiene miembros, cualquiera de la organización lo ve
 * completo (comportamiento histórico) — se avisa en la UI.
 */
export function ProjectTeam({ projectId }: { projectId: number }) {
  const [members, setMembers] = useState<ProjectMember[] | null>(null);
  const [canManage, setCanManage] = useState(false);
  const [team, setTeam] = useState<OrgUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pickUser, setPickUser] = useState<number | "">("");
  const [pickRole, setPickRole] = useState<"jefe_obra" | "capataz" | "comitente">("capataz");

  const load = useCallback(() => {
    api.getProjectMembers(projectId)
      .then((s) => { setMembers(s.members); setCanManage(s.can_manage_members); })
      .catch((e) => setError(String((e as Error)?.message ?? e)));
    api.listTeam().then(setTeam).catch(() => setTeam([]));
  }, [projectId]);
  useEffect(() => { load(); }, [load]);

  async function add() {
    if (!pickUser) return;
    setBusy(true); setError(null);
    try {
      await api.upsertProjectMember(projectId, Number(pickUser), pickRole);
      setPickUser("");
      load();
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally { setBusy(false); }
  }

  async function changeRole(userId: number, role: string) {
    setBusy(true); setError(null);
    try { await api.upsertProjectMember(projectId, userId, role); load(); }
    catch (e) { setError(String((e as Error)?.message ?? e)); }
    finally { setBusy(false); }
  }

  async function remove(userId: number) {
    setBusy(true); setError(null);
    try { await api.removeProjectMember(projectId, userId); load(); }
    catch (e) { setError(String((e as Error)?.message ?? e)); }
    finally { setBusy(false); }
  }

  if (members === null) return <p className="text-sm text-slate-500">Cargando equipo…</p>;

  const assignedIds = new Set(members.map((m) => m.user_id));
  const available = team.filter((u) => !assignedIds.has(u.id) && !u.is_superadmin);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="font-bold text-slate-900 dark:text-white">Equipo del proyecto</h3>
        <span className="text-xs text-slate-400">roles de permiso · distinto del oficio</span>
      </div>

      {members.length === 0 && (
        <p className="mb-3 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/20 dark:border-amber-800/40 dark:text-amber-300">
          Sin miembros asignados: por ahora cualquier integrante de la organización ve el proyecto completo.
          Asigná gente para restringir por rol (el capataz y el comitente dejan de ver los importes).
        </p>
      )}

      <div className="space-y-2">
        {members.map((m) => (
          <div key={m.user_id} className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-100 px-3 py-2 text-sm dark:border-slate-800">
            <span className="min-w-0 flex-1 truncate font-medium text-slate-800 dark:text-slate-200">
              {m.email}
              {m.job_roles.length > 0 && (
                <span className="ml-2 text-xs font-normal text-slate-400">· {m.job_roles.join(", ")}</span>
              )}
            </span>
            {canManage ? (
              <>
                <select value={m.role} disabled={busy}
                        onChange={(e) => changeRole(m.user_id, e.target.value)}
                        className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs dark:border-slate-600 dark:bg-slate-800">
                  {ROLE_OPTIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
                <button onClick={() => remove(m.user_id)} disabled={busy}
                        className="text-red-400 hover:text-red-600" title="Quitar del proyecto">✕</button>
              </>
            ) : (
              <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {m.role_label}
              </span>
            )}
          </div>
        ))}
      </div>

      {canManage && (
        <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
          <label className="flex flex-col text-xs font-medium text-slate-500 dark:text-slate-400">
            Usuario
            <select value={pickUser} onChange={(e) => setPickUser(e.target.value ? Number(e.target.value) : "")}
                    className="mt-1 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800">
              <option value="">— elegir —</option>
              {available.map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
            </select>
          </label>
          <label className="flex flex-col text-xs font-medium text-slate-500 dark:text-slate-400">
            Rol
            <select value={pickRole} onChange={(e) => setPickRole(e.target.value as typeof pickRole)}
                    className="mt-1 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800"
                    title={ROLE_OPTIONS.find((r) => r.value === pickRole)?.hint}>
              {ROLE_OPTIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </label>
          <button onClick={add} disabled={busy || !pickUser}
                  className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-500 disabled:opacity-50">
            {busy ? "…" : "Agregar"}
          </button>
          <p className="w-full text-[11px] text-slate-400">{ROLE_OPTIONS.find((r) => r.value === pickRole)?.hint}</p>
        </div>
      )}

      {error && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{error}</p>}
    </div>
  );
}

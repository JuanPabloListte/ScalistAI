"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import {
  api,
  type Project,
  type ProjectChanges,
} from "@/lib/api";

function fmtARS(n: number): string {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(Math.round(n));
}

function fmtPct(n: number): string {
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}%`;
}

function computeStatusLabel(status: string): string {
  if (status === "changed") return "cambió";
  if (status === "added") return "nueva en cómputo";
  if (status === "removed") return "solo en plan";
  return status;
}

function versionStatusLabel(status: string): string {
  if (status === "active") return "activo";
  if (status === "draft") return "borrador";
  if (status === "superseded") return "superseded";
  if (status === "closed") return "cerrado";
  return status;
}

export default function ChangesPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = Number(params.id);

  const [project, setProject] = useState<Project | null>(null);
  const [data, setData] = useState<ProjectChanges | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openCompute, setOpenCompute] = useState(true);
  const [openPrices, setOpenPrices] = useState(true);
  const [openVersions, setOpenVersions] = useState(true);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([api.getProject(projectId), api.getProjectChanges(projectId)])
      .then(([proj, changes]) => {
        setProject(proj);
        setData(changes);
        setOpenCompute(changes.summary.n_compute_changed > 0);
        setOpenPrices(changes.summary.n_price_changed > 0);
        setOpenVersions(true);
      })
      .catch((e) => setError(String((e as Error)?.message ?? e)))
      .finally(() => setLoading(false));
  }, [projectId]);

  const summary = data?.summary;
  const computeRows = (data?.compute.tasks ?? []).filter((r) => r.status !== "same");
  const priceRows = (data?.prices.materials ?? []).filter((r) => r.status !== "same");
  const hasBaseline = data?.prices.baseline_plan_id != null;

  return (
    <div className="mx-auto max-w-5xl p-6">
      <button
        type="button"
        onClick={() => {
          // No usar /projects/[id]: en IFC esa ruta hace replace → presupuesto.
          if (typeof window !== "undefined" && window.history.length > 1) {
            router.back();
          } else {
            router.push(`/projects/${projectId}/gantt`);
          }
        }}
        className="mb-4 text-xs font-medium text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
      >
        ← Volver
      </button>

      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">
          Cambios
        </h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {project?.name ?? `Proyecto #${projectId}`} — qué se movió desde el baseline
        </p>
      </header>

      {loading && (
        <p className="text-sm text-slate-500">Cargando cambios…</p>
      )}
      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700 dark:border-red-800/40 dark:bg-red-950/20 dark:text-red-400">
          {error}
        </div>
      )}

      {!loading && data && summary && (
        <>
          <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Kpi
              label="Presupuesto (directo)"
              value={summary.budget_direct != null ? `$${fmtARS(summary.budget_direct)}` : "—"}
            />
            <Kpi
              label="Plan de obra"
              value={summary.plan_total != null ? `$${fmtARS(summary.plan_total)}` : "—"}
            />
            <Kpi
              label="Cómputo IFC"
              value={summary.compute_total != null ? `$${fmtARS(summary.compute_total)}` : "—"}
            />
            <Kpi
              label="Cambios cómputo"
              value={String(summary.n_compute_changed)}
              accent={summary.n_compute_changed > 0 ? "amber" : "emerald"}
            />
            <Kpi
              label="Cambios precio"
              value={String(summary.n_price_changed)}
              accent={summary.n_price_changed > 0 ? "amber" : "emerald"}
            />
          </div>

          {/* Cómputo */}
          <Section
            title="Cómputo (IFC)"
            subtitle="Plan vigente vs cómputo actual del modelo"
            open={openCompute}
            onToggle={() => setOpenCompute((v) => !v)}
            badge={
              summary.n_compute_changed > 0
                ? `${summary.n_compute_changed} cambio(s)`
                : "sin drift"
            }
            badgeTone={summary.n_compute_changed > 0 ? "amber" : "emerald"}
          >
            {computeRows.length === 0 ? (
              <p className="text-xs text-slate-500">Sin drift vs cómputo actual.</p>
            ) : (
              <>
                <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
                  <table className="w-full text-xs">
                    <thead className="bg-slate-50 text-left text-slate-500 dark:bg-slate-800/60">
                      <tr>
                        <th className="px-3 py-2 font-medium">Tarea</th>
                        <th className="px-3 py-2 font-medium">Estado</th>
                        <th className="px-3 py-2 font-medium text-right">Cant. plan</th>
                        <th className="px-3 py-2 font-medium text-right">Cant. cómputo</th>
                        <th className="px-3 py-2 font-medium text-right">$ plan</th>
                        <th className="px-3 py-2 font-medium text-right">$ cómputo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {computeRows.map((r) => (
                        <tr
                          key={`${r.name}-${r.status}-${r.assembly_id ?? ""}-${r.level ?? ""}`}
                          className="border-t border-slate-100 dark:border-slate-800"
                        >
                          <td className="px-3 py-2 text-slate-800 dark:text-slate-200">
                            {r.name}
                            {r.level ? (
                              <span className="ml-1 text-slate-400">· {r.level}</span>
                            ) : null}
                          </td>
                          <td className="px-3 py-2">
                            <StatusPill status={r.status} label={computeStatusLabel(r.status)} />
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {r.qty_plan != null ? r.qty_plan.toFixed(2) : "—"}
                            {r.unit ? ` ${r.unit}` : ""}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {r.qty_compute != null ? r.qty_compute.toFixed(2) : "—"}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {r.cost_plan != null ? `$${fmtARS(r.cost_plan)}` : "—"}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {r.cost_compute != null ? `$${fmtARS(r.cost_compute)}` : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {summary.n_compute_changed > 0 && (
                  <p className="mt-3 text-xs text-slate-500">
                    Para regenerar el borrador desde el cómputo sin tocar el baseline,{" "}
                    <Link
                      href={`/projects/${projectId}/gantt`}
                      className="font-semibold text-emerald-700 hover:underline dark:text-emerald-400"
                    >
                      ir al Gantt →
                    </Link>
                  </p>
                )}
              </>
            )}
          </Section>

          {/* Precios */}
          <Section
            title="Precios (desde baseline)"
            subtitle={
              hasBaseline
                ? `Snapshot v${data.prices.baseline_version ?? "?"} vs catálogo vivo`
                : "Sin baseline congelado"
            }
            open={openPrices}
            onToggle={() => setOpenPrices((v) => !v)}
            badge={
              !hasBaseline
                ? "sin baseline"
                : summary.n_price_changed > 0
                  ? `${summary.n_price_changed} cambio(s)`
                  : "sin drift"
            }
            badgeTone={
              !hasBaseline ? "slate" : summary.n_price_changed > 0 ? "amber" : "emerald"
            }
          >
            {!hasBaseline ? (
              <p className="text-xs text-slate-500">
                Congelá un plan de obra para anclar precios. Hasta entonces no hay drift
                de catálogo medible contra baseline.
              </p>
            ) : priceRows.length === 0 ? (
              <p className="text-xs text-slate-500">
                Precios del catálogo alineados al snapshot del baseline.
              </p>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 text-left text-slate-500 dark:bg-slate-800/60">
                    <tr>
                      <th className="px-3 py-2 font-medium">Material</th>
                      <th className="px-3 py-2 font-medium text-right">Baseline</th>
                      <th className="px-3 py-2 font-medium text-right">Vivo</th>
                      <th className="px-3 py-2 font-medium text-right">Δ</th>
                      <th className="px-3 py-2 font-medium text-right">Δ%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {priceRows.map((r) => (
                      <tr
                        key={r.material_id}
                        className="border-t border-slate-100 dark:border-slate-800"
                      >
                        <td className="px-3 py-2 text-slate-800 dark:text-slate-200">
                          {r.name}
                          {r.unit ? (
                            <span className="ml-1 text-slate-400">/ {r.unit}</span>
                          ) : null}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          ${fmtARS(r.price_baseline)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {r.price_live != null ? `$${fmtARS(r.price_live)}` : "—"}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {r.delta != null ? (
                            <span className={r.delta > 0 ? "text-amber-700 dark:text-amber-300" : "text-emerald-700 dark:text-emerald-300"}>
                              {r.delta > 0 ? "+" : ""}{fmtARS(r.delta)}
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {r.delta_pct != null ? (
                            <span className={r.delta_pct > 0 ? "text-amber-700 dark:text-amber-300" : "text-emerald-700 dark:text-emerald-300"}>
                              {fmtPct(r.delta_pct)}
                            </span>
                          ) : r.status === "missing_live" ? (
                            <span className="text-slate-400">fuera de catálogo</span>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

          {/* Plan versions */}
          <Section
            title="Plan de obra"
            subtitle="Historial de versiones del cronograma"
            open={openVersions}
            onToggle={() => setOpenVersions((v) => !v)}
            badge={
              summary.active_version != null
                ? `activo v${summary.active_version}`
                : summary.draft_version != null
                  ? `borrador v${summary.draft_version}`
                  : "sin plan"
            }
            badgeTone="slate"
          >
            {data.versions.length === 0 ? (
              <p className="text-xs text-slate-500">
                Todavía no hay plan de obra. Generá un borrador desde el Gantt.
              </p>
            ) : (
              <ul className="space-y-2">
                {data.versions.map((v) => (
                  <li
                    key={v.plan_id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-700"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-slate-800 dark:text-slate-100">
                        v{v.version}
                      </span>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                          v.status === "active"
                            ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
                            : v.status === "draft"
                              ? "bg-sky-100 text-sky-800 dark:bg-sky-950/40 dark:text-sky-300"
                              : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                        }`}
                      >
                        {versionStatusLabel(v.status)}
                      </span>
                      <span className="text-slate-400">
                        {v.frozen_at
                          ? `congelado ${v.frozen_at.slice(0, 10)}`
                          : v.created_at
                            ? `creado ${v.created_at.slice(0, 10)}`
                            : ""}
                      </span>
                    </div>
                    <div className="tabular-nums text-slate-600 dark:text-slate-300">
                      ${fmtARS(v.total_cost)} · {v.task_count} tarea(s)
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </>
      )}
    </div>
  );
}

function Kpi({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: "amber" | "emerald";
}) {
  const valueClass =
    accent === "amber"
      ? "text-amber-700 dark:text-amber-300"
      : accent === "emerald"
        ? "text-emerald-700 dark:text-emerald-300"
        : "text-slate-900 dark:text-white";
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className={`mt-1 text-lg font-semibold tabular-nums ${valueClass}`}>{value}</div>
    </div>
  );
}

function Section({
  title,
  subtitle,
  open,
  onToggle,
  badge,
  badgeTone,
  children,
}: {
  title: string;
  subtitle: string;
  open: boolean;
  onToggle: () => void;
  badge: string;
  badgeTone: "amber" | "emerald" | "slate";
  children: ReactNode;
}) {
  const badgeClass =
    badgeTone === "amber"
      ? "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-300"
      : badgeTone === "emerald"
        ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300"
        : "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300";

  return (
    <section className="mb-4 rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left"
      >
        <div>
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">{title}</h2>
          <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`rounded-md border px-2 py-1 text-[11px] font-semibold ${badgeClass}`}>
            {badge}
          </span>
          <span className="text-slate-400 text-xs">{open ? "▾" : "▸"}</span>
        </div>
      </button>
      {open && <div className="border-t border-slate-100 px-4 py-3 dark:border-slate-800">{children}</div>}
    </section>
  );
}

function StatusPill({ status, label }: { status: string; label: string }) {
  const cls =
    status === "added"
      ? "bg-sky-100 text-sky-800 dark:bg-sky-950/40 dark:text-sky-300"
      : status === "removed"
        ? "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200"
        : "bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300";
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${cls}`}>
      {label}
    </span>
  );
}

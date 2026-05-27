"use client";

import { useEffect, useMemo, useState } from "react";

import { api, type PageRole, type Plan, type Project } from "@/lib/api";

const ROLE_DEFS: { value: PageRole; label: string; description: string; color: string }[] = [
  {
    value: "walls",
    label: "Muros",
    description: "Plano para detección de paredes (ej: replanteo de muros)",
    color: "emerald",
  },
  {
    value: "openings",
    label: "Aberturas",
    description: "Plano para puertas y ventanas (ej: planilla de carpinterías)",
    color: "amber",
  },
  {
    value: "rooms",
    label: "Recintos",
    description: "Plano para ambientes/lozas (ej: planta arquitectónica con nombres)",
    color: "sky",
  },
];

const COLOR_STYLES: Record<string, { active: string; idle: string; ring: string }> = {
  emerald: {
    active: "bg-emerald-600 text-white border-emerald-600 dark:bg-emerald-500 dark:border-emerald-500",
    idle: "bg-white text-emerald-700 border-emerald-300 hover:bg-emerald-50 dark:bg-slate-800 dark:text-emerald-400 dark:border-emerald-700 dark:hover:bg-emerald-950/50",
    ring: "ring-emerald-500",
  },
  amber: {
    active: "bg-amber-600 text-white border-amber-600 dark:bg-amber-500 dark:border-amber-500",
    idle: "bg-white text-amber-700 border-amber-300 hover:bg-amber-50 dark:bg-slate-800 dark:text-amber-400 dark:border-amber-700 dark:hover:bg-amber-950/50",
    ring: "ring-amber-500",
  },
  sky: {
    active: "bg-sky-600 text-white border-sky-600 dark:bg-sky-500 dark:border-sky-500",
    idle: "bg-white text-sky-700 border-sky-300 hover:bg-sky-50 dark:bg-slate-800 dark:text-sky-400 dark:border-sky-700 dark:hover:bg-sky-950/50",
    ring: "ring-sky-500",
  },
};

type PageRoleMap = Record<string, PageRole[]>;

function rolesEqual(a: PageRole[], b: PageRole[]): boolean {
  if (a.length !== b.length) return false;
  const setB = new Set(b);
  return a.every((r) => setB.has(r));
}

export function Step3PageRoles({
  project,
  onSaved,
  onBack,
}: {
  project: Project;
  onSaved: () => void;
  onBack: () => void;
}) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [thumbs, setThumbs] = useState<Record<number, string>>({});
  const [loadingPlan, setLoadingPlan] = useState(true);
  const [pageRoles, setPageRoles] = useState<PageRoleMap>({});
  const [saving, setSaving] = useState(false);
  const [zoomedPage, setZoomedPage] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [skipAiDetection, setSkipAiDetection] = useState(false);

  // Cargar el plano activo del proyecto
  useEffect(() => {
    let cancelled = false;
    setLoadingPlan(true);
    api
      .listPlans(project.id)
      .then((plans) => {
        if (cancelled) return;
        const active = plans[plans.length - 1] ?? null;
        setPlan(active);
        if (active?.page_roles) {
          setPageRoles({ ...active.page_roles });
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "No se pudo cargar el plano");
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingPlan(false);
      });
    return () => {
      cancelled = true;
    };
  }, [project.id]);

  // Cargar thumbnails de cada página
  useEffect(() => {
    if (!plan?.page_count) return;
    const deleted = new Set(plan.deleted_pages ?? []);
    const blobs: string[] = [];
    let cancelled = false;

    async function loadAll() {
      const newThumbs: Record<number, string> = {};
      for (let p = 1; p <= (plan!.page_count ?? 0); p++) {
        if (deleted.has(p)) continue;
        if (cancelled) break;
        try {
          const blob = await api.fetchPlanRaster(plan!.id, p);
          if (cancelled) break;
          const url = URL.createObjectURL(blob);
          blobs.push(url);
          newThumbs[p] = url;
          // Render parcial mientras siguen cargando
          setThumbs((prev) => ({ ...prev, [p]: url }));
        } catch {
          // si una página falla seguimos con las demás
        }
      }
      if (!cancelled) setThumbs(newThumbs);
    }
    loadAll();

    return () => {
      cancelled = true;
      blobs.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [plan?.id, plan?.page_count, plan?.deleted_pages]);

  function togglePageRole(page: number, role: PageRole) {
    setPageRoles((prev) => {
      const key = String(page);
      const current = prev[key] ?? [];
      const has = current.includes(role);
      const next = has ? current.filter((r) => r !== role) : [...current, role];
      const newMap = { ...prev };
      if (next.length === 0) delete newMap[key];
      else newMap[key] = next;
      return newMap;
    });
  }

  function clearAll() {
    setPageRoles({});
  }

  async function handleSave() {
    if (!plan) return;
    setSaving(true);
    setError(null);
    try {
      await api.setPageRoles(plan.id, pageRoles, skipAiDetection);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar");
      setSaving(false);
    }
  }

  const activePages = useMemo(() => {
    if (!plan?.page_count) return [] as number[];
    const deleted = new Set(plan.deleted_pages ?? []);
    return Array.from({ length: plan.page_count }, (_, i) => i + 1).filter(
      (p) => !deleted.has(p),
    );
  }, [plan?.page_count, plan?.deleted_pages]);

  const summary = useMemo(() => {
    let walls = 0, openings = 0, rooms = 0;
    for (const roles of Object.values(pageRoles)) {
      if (roles.includes("walls")) walls++;
      if (roles.includes("openings")) openings++;
      if (roles.includes("rooms")) rooms++;
    }
    return { walls, openings, rooms };
  }, [pageRoles]);

  // Modificado: comparar con el estado guardado en plan.page_roles
  const isDirty = useMemo(() => {
    const stored = plan?.page_roles ?? {};
    const keysA = Object.keys(pageRoles);
    const keysB = Object.keys(stored);
    if (keysA.length !== keysB.length) return true;
    for (const k of keysA) {
      if (!stored[k] || !rolesEqual(pageRoles[k], stored[k])) return true;
    }
    return false;
  }, [pageRoles, plan?.page_roles]);

  useEffect(() => {
    if (zoomedPage === null) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setZoomedPage(null);
      } else if (e.key === "ArrowLeft") {
        const idx = activePages.indexOf(zoomedPage);
        if (idx > 0) setZoomedPage(activePages[idx - 1]);
      } else if (e.key === "ArrowRight") {
        const idx = activePages.indexOf(zoomedPage);
        if (idx < activePages.length - 1) setZoomedPage(activePages[idx + 1]);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [zoomedPage, activePages]);

  const canContinue =
    Object.keys(pageRoles).length > 0 || Object.keys(plan?.page_roles ?? {}).length > 0;

  if (loadingPlan) {
    return (
      <div className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Asignar páginas a detectores</h2>
        <p className="text-sm text-slate-500">Cargando plano…</p>
      </div>
    );
  }

  if (!plan) {
    return (
      <div className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Asignar páginas a detectores</h2>
        <p className="text-sm text-red-600 dark:text-red-400">
          No se encontró ningún plano subido. Volvé al paso anterior.
        </p>
        <div>
          <button
            type="button"
            onClick={onBack}
            className="text-sm text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
          >
            ← Volver
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-semibold">Asignar páginas a detectores</h2>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
          Marcá qué páginas usar para cada tipo de detección. Cada plano profesional
          suele estar dividido: un plano para muros, otro para aberturas, otro para
          recintos. Asignando explícitamente, la IA evita procesar páginas que no
          corresponden y los resultados son mucho más precisos.
        </p>
      </div>

      {/* Leyenda de roles */}
      <div className="flex flex-wrap gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900/40">
        {ROLE_DEFS.map((r) => {
          const styles = COLOR_STYLES[r.color];
          return (
            <div
              key={r.value}
              className={`flex items-start gap-2 rounded-md border px-3 py-2 text-xs ${styles.idle}`}
            >
              <span className="font-semibold">{r.label}</span>
              <span className="opacity-75">{r.description}</span>
            </div>
          );
        })}
      </div>

      {/* Grilla de miniaturas */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {activePages.map((page) => {
          const roles = pageRoles[String(page)] ?? [];
          const thumb = thumbs[page];
          return (
            <div
              key={page}
              className={`flex flex-col gap-2 rounded-lg border bg-white p-2 transition dark:bg-slate-800 ${
                roles.length > 0
                  ? "border-brand shadow-md ring-2 ring-brand/30 dark:border-sky-400 dark:ring-sky-400/30"
                  : "border-slate-200 dark:border-slate-700"
              }`}
            >
              <div 
                onClick={() => setZoomedPage(page)}
                className="relative h-32 overflow-hidden rounded bg-slate-100 dark:bg-slate-900 cursor-pointer group"
                title="Hacé clic para ampliar"
              >
                {thumb ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={thumb}
                    alt={`Página ${page}`}
                    className="h-full w-full object-contain transition-transform duration-200 group-hover:scale-105"
                  />
                ) : (
                  <div className="flex h-full items-center justify-center text-xs text-slate-400">
                    Cargando…
                  </div>
                )}
                {/* Hover overlay effect */}
                <div className="absolute inset-0 bg-slate-950/20 opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex items-center justify-center">
                  <span className="rounded bg-slate-950/80 px-2 py-1 text-[10px] font-semibold text-white shadow backdrop-blur-xs">
                    Ampliar 🔍
                  </span>
                </div>
                <span className="absolute left-1.5 top-1.5 rounded bg-slate-900/80 px-1.5 py-0.5 text-xs font-semibold text-white">
                  p. {page}
                </span>
              </div>
              <div className="flex flex-wrap gap-1">
                {ROLE_DEFS.map((r) => {
                  const active = roles.includes(r.value);
                  const styles = COLOR_STYLES[r.color];
                  return (
                    <button
                      key={r.value}
                      type="button"
                      onClick={() => togglePageRole(page, r.value)}
                      className={`rounded-full border px-2 py-0.5 text-xs font-medium transition ${
                        active ? styles.active : styles.idle
                      }`}
                    >
                      {r.label}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* Resumen */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-900/40">
        <div className="flex flex-wrap gap-3 text-slate-700 dark:text-slate-300">
          <span>
            <strong>{summary.walls}</strong> p. para muros
          </span>
          <span className="text-slate-400">·</span>
          <span>
            <strong>{summary.openings}</strong> p. para aberturas
          </span>
          <span className="text-slate-400">·</span>
          <span>
            <strong>{summary.rooms}</strong> p. para recintos
          </span>
        </div>
        {Object.keys(pageRoles).length > 0 && (
          <button
            type="button"
            onClick={clearAll}
            className="text-xs text-slate-500 underline hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
          >
            Limpiar todo
          </button>
        )}
      </div>

      {/* Manual Configuration Toggle */}
      <div className="rounded-md border border-slate-200 bg-white p-3 text-sm dark:border-slate-800 dark:bg-slate-900/60">
        <label className="flex cursor-pointer items-start gap-2.5 text-slate-700 dark:text-slate-300">
          <input
            type="checkbox"
            checked={skipAiDetection}
            onChange={(e) => setSkipAiDetection(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand focus:ring-1 focus:ring-brand dark:border-slate-600 dark:bg-slate-900"
          />
          <div>
            <span className="font-semibold text-slate-800 dark:text-slate-100">
              Configuración manual de elementos de construcción
            </span>
            <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
              Desactiva la detección automática por IA en segundo plano. Podrás dibujar todos los elementos manualmente en el visor del plano.
            </p>
          </div>
        </label>
      </div>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      <div className="mt-2 flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          disabled={saving}
          className="text-sm text-slate-500 hover:text-slate-900 disabled:opacity-50 dark:text-slate-400 dark:hover:text-slate-100"
        >
          ← Volver
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving || !canContinue}
          className="rounded-md bg-brand px-5 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
          title={
            !canContinue
              ? "Asigná al menos una página a un rol para continuar"
              : isDirty
                ? "Guardar y disparar detección IA"
                : "Continuar al siguiente paso"
          }
        >
          {saving ? "Guardando..." : isDirty ? "Guardar y continuar →" : "Continuar →"}
        </button>
      </div>

      {zoomedPage !== null && (
        <div 
          className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-slate-950/85 p-4 backdrop-blur-xs transition-opacity duration-300"
          onClick={() => setZoomedPage(null)}
        >
          {/* Modal content container */}
          <div 
            className="relative flex max-h-[90vh] max-w-[90vw] flex-col items-center justify-center rounded-xl bg-slate-900 p-2 shadow-2xl border border-slate-700/50"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header info */}
            <div className="absolute top-4 left-4 z-10 flex items-center gap-2 rounded-full bg-slate-950/70 px-3 py-1.5 text-xs font-semibold text-white">
              <span>Página {zoomedPage} de {activePages.length}</span>
            </div>

            {/* Close Button */}
            <button
              onClick={() => setZoomedPage(null)}
              className="absolute top-4 right-4 z-10 flex h-8 w-8 items-center justify-center rounded-full bg-slate-950/70 text-lg font-bold text-white hover:bg-slate-800 transition"
              title="Cerrar (Esc)"
            >
              ×
            </button>

            {/* Navigation buttons */}
            <div className="absolute inset-y-0 left-0 right-0 flex items-center justify-between px-2 pointer-events-none">
              <button
                disabled={activePages.indexOf(zoomedPage) === 0}
                onClick={(e) => {
                  e.stopPropagation();
                  const idx = activePages.indexOf(zoomedPage);
                  if (idx > 0) setZoomedPage(activePages[idx - 1]);
                }}
                className="pointer-events-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-950/60 text-xl font-bold text-white hover:bg-slate-800 disabled:opacity-30 disabled:pointer-events-none transition"
                title="Anterior (←)"
              >
                ‹
              </button>
              <button
                disabled={activePages.indexOf(zoomedPage) === activePages.length - 1}
                onClick={(e) => {
                  e.stopPropagation();
                  const idx = activePages.indexOf(zoomedPage);
                  if (idx < activePages.length - 1) setZoomedPage(activePages[idx + 1]);
                }}
                className="pointer-events-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-950/60 text-xl font-bold text-white hover:bg-slate-800 disabled:opacity-30 disabled:pointer-events-none transition"
                title="Siguiente (→)"
              >
                ›
              </button>
            </div>

            {/* Image */}
            {thumbs[zoomedPage] ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={thumbs[zoomedPage]}
                alt={`Página ${zoomedPage} ampliada`}
                className="max-h-[80vh] max-w-[85vw] object-contain rounded"
              />
            ) : (
              <div className="flex h-64 w-64 items-center justify-center text-sm text-slate-400">
                Cargando…
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

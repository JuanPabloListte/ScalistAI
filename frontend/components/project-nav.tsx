"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { api, type ProjectRole } from "@/lib/api";

type Tab = { key: string; label: string; financial: boolean };

const TABS: Tab[] = [
  { key: "presupuesto", label: "Presupuesto", financial: true },
  { key: "gantt", label: "Cronograma", financial: false },
  { key: "obra", label: "Obra", financial: false },
  // El backend exige permiso financiero para /changes (montos y diferencias de costo).
  { key: "changes", label: "Cambios", financial: true },
];

/** Barra común de las pantallas de un proyecto: volver a proyectos, nombre y
 *  pestañas (links reales). Capataz y comitente no ven lo económico, así que
 *  no se les muestran Presupuesto ni Cambios. Hasta conocer el rol se reserva
 *  el lugar de las pestañas sin mostrarlas, para que no aparezcan ni
 *  desaparezcan de golpe. */
export function ProjectNav({
  projectId,
  containerClass = "max-w-6xl px-6",
}: {
  projectId: number;
  /** Ancho y márgenes del contenido, para alinear con la página. */
  containerClass?: string;
}) {
  const pathname = usePathname();
  const [name, setName] = useState<string | null>(null);
  const [role, setRole] = useState<ProjectRole | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    api.getProject(projectId).then((p) => !cancelled && setName(p.name)).catch(() => {});
    api
      .getProjectMembers(projectId)
      .then((m) => !cancelled && setRole(m.my_role))
      .catch(() => !cancelled && setRole(null)); // si falla, el backend decide en cada página
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const hideFinancial = role === "capataz" || role === "comitente";
  const tabs = TABS.filter((t) => !(hideFinancial && t.financial));

  return (
    <nav aria-label="Proyecto" className="border-b border-slate-200 dark:border-slate-800">
      <div className={`mx-auto ${containerClass} pt-4`}>
        <div className="flex items-baseline gap-3">
          <Link
            href="/projects"
            className="shrink-0 rounded text-sm text-slate-500 hover:text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/40 dark:text-slate-400 dark:hover:text-slate-200"
          >
            ← Proyectos
          </Link>
          <p className="min-w-0 truncate text-base font-semibold text-slate-900 dark:text-slate-100">
            {name ?? " "}
          </p>
        </div>
        <div className="-mb-px mt-3 flex min-h-[2rem] gap-4 overflow-x-auto">
          {role !== undefined &&
            tabs.map((t) => {
              const href = `/projects/${projectId}/${t.key}`;
              const active = pathname === href || pathname.startsWith(`${href}/`);
              return (
                <Link
                  key={t.key}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`whitespace-nowrap border-b-2 px-1 pb-2 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/40 ${
                    active
                      ? "border-brand-500 text-brand-600 dark:border-brand-400 dark:text-brand-400"
                      : "border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-300"
                  }`}
                >
                  {t.label}
                </Link>
              );
            })}
        </div>
      </div>
    </nav>
  );
}

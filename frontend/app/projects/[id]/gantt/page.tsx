"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import { api, type Project, type Plan, type DetectedElement, type Assembly } from "@/lib/api";

type GanttTask = {
  id: number;
  name: string;
  qty: number;
  unit: string;
  dailyYield: number;
  days: number;
  startDate: number;
};

export default function ProjectGanttPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = Number(params.id);

  const [project, setProject] = useState<Project | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [elements, setElements] = useState<DetectedElement[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.getProject(projectId),
      api.listPlans(projectId)
    ])
    .then(async ([proj, planList]) => {
      if (cancelled) return;
      setProject(proj);
      setPlans(planList);
      
      const allElems: DetectedElement[] = [];
      for (const p of planList) {
        if (p.status === "ready" || p.status === "success") {
          const els = await api.listElements(p.id);
          allElems.push(...els);
        }
      }
      if (!cancelled) setElements(allElems);
    })
    .finally(() => {
      if (!cancelled) setLoading(false);
    });
    
    return () => { cancelled = true; };
  }, [projectId]);

  const tasks = useMemo(() => {
    // Agrupar elementos por Assembly para crear las tareas
    const taskMap = new Map<number, { assembly: Assembly, totalQty: number }>();
    
    for (const el of elements) {
      if (!el.assemblies) continue;
      
      let elQty = 0;
      if (el.type === "wall" || el.type === "opening") elQty = el.area_m2 || 0;
      else if (el.type === "room" || el.type === "roof") elQty = el.area_m2 || 0;
      else if (el.type === "beam" || el.type === "column") elQty = el.length_m || 0;

      for (const a of el.assemblies) {
        if (!taskMap.has(a.id)) {
          taskMap.set(a.id, { assembly: a, totalQty: 0 });
        }
        taskMap.get(a.id)!.totalQty += elQty;
      }
    }

    const taskList: GanttTask[] = [];
    let currentDay = 0;

    for (const { assembly, totalQty } of taskMap.values()) {
      if (totalQty <= 0) continue;
      
      const dy = assembly.daily_yield && assembly.daily_yield > 0 ? assembly.daily_yield : 1; // fallback a 1
      const days = Math.ceil(totalQty / dy);
      
      let unit = "m²";
      if (["beam", "column"].includes(assembly.applies_to)) unit = "ml";

      taskList.push({
        id: assembly.id,
        name: assembly.name,
        qty: totalQty,
        unit,
        dailyYield: dy,
        days: days,
        startDate: currentDay, // Tareas secuenciales por ahora
      });
      currentDay += days;
    }

    return taskList;
  }, [elements]);

  if (loading) return <div className="p-10 text-center">Cargando cronograma...</div>;
  if (!project) return <div className="p-10 text-center">Proyecto no encontrado</div>;

  const totalDays = tasks.length > 0 ? tasks[tasks.length - 1].startDate + tasks[tasks.length - 1].days : 0;

  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <header className="mb-6">
        <Link
          href={`/projects/${project.id}`}
          className="inline-flex items-center gap-1 text-sm font-medium text-slate-500 transition hover:text-brand-600 dark:text-slate-400 dark:hover:text-brand-400"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6"/></svg>
          Volver a Visor
        </Link>
        <h1 className="mt-2 text-3xl font-bold text-slate-900 dark:text-white">
          Cronograma Estimado (Gantt)
        </h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Duración total estimada: <strong>{totalDays} días</strong> laborales. Calculado automáticamente en base a los cómputos detectados y el rendimiento diario configurado en tus Sistemas Constructivos.
        </p>
      </header>

      {tasks.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 p-10 text-center dark:border-slate-700">
          <p className="text-slate-500 dark:text-slate-400">
            No hay sistemas asignados a los elementos de este proyecto, o no se han detectado métricas.
          </p>
          <Link href={`/projects/${project.id}`} className="mt-4 inline-block font-semibold text-brand-600 dark:text-brand-400">
            Ir al visor a asignar sistemas
          </Link>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900 p-6">
          <table className="w-full min-w-[800px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800">
                <th className="py-3 text-left font-semibold text-slate-700 dark:text-slate-300 w-1/4">Tarea / Sistema</th>
                <th className="py-3 text-center font-semibold text-slate-700 dark:text-slate-300 w-24">Cantidad</th>
                <th className="py-3 text-center font-semibold text-slate-700 dark:text-slate-300 w-24">Duración</th>
                <th className="py-3 text-left font-semibold text-slate-700 dark:text-slate-300">Cronograma (Días)</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map(t => (
                <tr key={t.id} className="border-b border-slate-100 dark:border-slate-800/50">
                  <td className="py-4 text-slate-800 dark:text-slate-200 pr-4">
                    <div className="font-semibold">{t.name}</div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">Rendimiento: {t.dailyYield} {t.unit}/día</div>
                  </td>
                  <td className="py-4 text-center text-slate-600 dark:text-slate-400">
                    {t.qty.toFixed(1)} {t.unit}
                  </td>
                  <td className="py-4 text-center text-slate-600 dark:text-slate-400">
                    {t.days} d
                  </td>
                  <td className="py-4">
                    <div className="relative h-6 w-full rounded bg-slate-100 dark:bg-slate-800">
                      {totalDays > 0 && (
                        <div 
                          className="absolute h-full rounded-md bg-brand-500 opacity-90 shadow-sm"
                          style={{
                            left: \`\${(t.startDate / totalDays) * 100}%\`,
                            width: \`\${Math.max(1, (t.days / totalDays) * 100)}%\`
                          }}
                        />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}

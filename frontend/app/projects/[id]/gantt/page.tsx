"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import Link from "next/link";
import { 
  api, 
  type Project, 
  type ScheduleResponse, 
  type CashflowPoint, 
  type WorkPlanData, 
  type WorkPlanVersion, 
  type WorkProgress, 
  type OrgUser 
} from "@/lib/api";
import { 
  Check, AlertTriangle, Play, CheckCircle, Ban, HelpCircle, X, 
  Plus, Calendar, Clock, User, Clipboard, FileText, 
  ArrowRight, Search, Filter, Lock, Unlock, ChevronRight, Trash2, Edit
} from "lucide-react";

const STAGE_COLORS: Record<string, string> = {
  "Fundación": "#0ea5e9",
  "Estructura": "#8b5cf6",
  "Mampostería": "#f59e0b",
  "Instalaciones": "#10b981",
  "Terminaciones": "#ef4444",
};
const fallbackColor = "#64748b";

function fmtARS(n: number): string {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(Math.round(n));
}
function fmtDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("es-AR", { day: "2-digit", month: "short", year: "2-digit" });
}

type TaskJiraMetadata = {
  status: "Pendiente" | "En progreso" | "En revisión" | "Completada" | "Bloqueada" | "Cancelada";
  priority: "Baja" | "Media" | "Alta" | "Crítica";
  isBlocked: boolean;
  blockedReason: string;
  assignees: string[];
  description: string;
  history: { date: string; change: string }[];
  startDateOverride?: string;
  endDateOverride?: string;
  durationOverride?: number;
};

export default function ProjectGanttPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = Number(params.id);

  const [project, setProject] = useState<Project | null>(null);
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);
  const [plan, setPlan] = useState<WorkPlanData | null>(null);
  const [versions, setVersions] = useState<WorkPlanVersion[]>([]);
  const [progress, setProgress] = useState<WorkProgress | null>(null);
  const [team, setTeam] = useState<OrgUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [startDate, setStartDate] = useState<string>(new Date().toISOString().slice(0, 10));
  const [crews, setCrews] = useState<number>(1);

  // Jira & Gantt interactive states
  const [manualTasks, setManualTasks] = useState<any[]>([]);
  const [jiraMetadata, setJiraMetadata] = useState<Record<string, TaskJiraMetadata>>({});
  const [activeTask, setActiveTask] = useState<any | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [activeModalTab, setActiveModalTab] = useState<"detail" | "responsibles" | "history">("detail");

  // Top Filter states
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [assigneeFilter, setAssigneeFilter] = useState("");

  // New task form state
  const [newAssembly, setNewAssembly] = useState("");
  const [newStage, setNewStage] = useState("Fundación");
  const [newDuration, setNewDuration] = useState(5);
  const [newStartDate, setNewStartDate] = useState(new Date().toISOString().slice(0, 10));
  const [newDescription, setNewDescription] = useState("");
  const [newPriority, setNewPriority] = useState<"Baja" | "Media" | "Alta" | "Crítica">("Media");
  const [newStatus, setNewStatus] = useState<"Pendiente" | "En progreso" | "En revisión" | "Completada" | "Bloqueada" | "Cancelada">("Pendiente");
  const [newAssignees, setNewAssignees] = useState<string[]>([]);
  const [newPredecessor, setNewPredecessor] = useState<string>("");
  const [newIsBlocked, setNewIsBlocked] = useState<boolean>(false);
  const [newBlockedReason, setNewBlockedReason] = useState<string>("");

  // Drag & drop state
  const [liveDrag, setLiveDrag] = useState<{ taskName: string; daysOffset: number; durationDays: number } | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const dragInfo = useRef<{
    taskName: string;
    initialLeft: number;
    initialWidth: number;
    initialMouseX: number;
    daysOffset: number;
    durationDays: number;
    isManual: boolean;
    taskId?: number;
  } | null>(null);

  // Load team users and metadata from LocalStorage
  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.getProject(projectId),
      api.getWorkPlan(projectId),
      api.listTeam().catch(() => [] as OrgUser[])
    ])
      .then(async ([proj, wpState, teamUsers]) => {
        setProject(proj);
        setVersions(wpState.versions);
        setTeam(teamUsers);
        
        if (wpState.plan) {
          setPlan(wpState.plan);
          setSchedule(wpState.plan);
          if (wpState.plan.status === "active") {
            api.getWorkProgress(projectId).then(setProgress).catch(() => setProgress(null));
          }
        } else {
          setPlan(null);
          setSchedule(await api.getSchedule(projectId, { startDate, crews }));
        }

        // LocalStorage loading
        if (typeof window !== "undefined") {
          const mt = localStorage.getItem(`gantt_manual_tasks_${projectId}`);
          if (mt) setManualTasks(JSON.parse(mt));
          const jm = localStorage.getItem(`gantt_jira_metadata_${projectId}`);
          if (jm) setJiraMetadata(JSON.parse(jm));
        }
      })
      .catch((e) => setError(String((e as Error)?.message ?? e)))
      .finally(() => setLoading(false));
  }, [projectId, startDate, crews]);

  useEffect(() => { load(); }, [load]);

  const saveManualTasks = (tasksList: any[]) => {
    setManualTasks(tasksList);
    localStorage.setItem(`gantt_manual_tasks_${projectId}`, JSON.stringify(tasksList));
  };

  const saveJiraMetadata = (meta: Record<string, TaskJiraMetadata>) => {
    setJiraMetadata(meta);
    localStorage.setItem(`gantt_jira_metadata_${projectId}`, JSON.stringify(meta));
  };

  const teamNames = useMemo(() => {
    const list = team.map(u => u.email.split('@')[0]);
    if (list.length === 0) {
      return ["Juan Pérez", "María Gómez", "Carlos Plaza", "Laura Flores", "Pedro Martínez"];
    }
    return list;
  }, [team]);

  const getTaskMeta = useCallback((taskName: string): TaskJiraMetadata => {
    const defaultMeta: TaskJiraMetadata = {
      status: "Pendiente",
      priority: "Media",
      isBlocked: false,
      blockedReason: "",
      assignees: [],
      description: "",
      history: [
        { date: new Date().toLocaleDateString("es-AR"), change: "Tarea inicializada en el cronograma." }
      ]
    };
    return {
      ...defaultMeta,
      ...(jiraMetadata[taskName] || {})
    };
  }, [jiraMetadata]);

  // Combine API and Manual tasks
  const allTasks = useMemo(() => {
    const apiTasks = schedule?.tasks || [];
    const formattedApiTasks = apiTasks.map((t, idx) => {
      const meta = jiraMetadata[t.assembly] || {};
      const start = meta.startDateOverride || t.start_date;
      const duration = meta.durationOverride || t.duration_days;
      
      const startDateObj = new Date(start + "T00:00:00");
      const endDateObj = new Date(startDateObj.getTime() + duration * 86400000);
      const end = endDateObj.toISOString().slice(0, 10);

      return {
        id: idx + 1,
        assembly: t.assembly,
        stage: t.stage,
        stage_order: t.stage_order,
        duration_days: duration,
        start_date: start,
        end_date: end,
        cost: t.cost,
        quantity: t.quantity,
        unit: t.unit,
        isManual: false,
        taskId: (t as any).id || (t as any).task_id || idx + 1,
      };
    });

    const formattedManualTasks = manualTasks.map((t, idx) => {
      const meta = jiraMetadata[t.assembly] || {};
      const start = meta.startDateOverride || t.start_date;
      const duration = meta.durationOverride || t.duration_days;
      
      const startDateObj = new Date(start + "T00:00:00");
      const endDateObj = new Date(startDateObj.getTime() + duration * 86400000);
      const end = endDateObj.toISOString().slice(0, 10);

      return {
        id: formattedApiTasks.length + idx + 1,
        assembly: t.assembly,
        stage: t.stage,
        stage_order: t.stage_order || 10,
        duration_days: duration,
        start_date: start,
        end_date: end,
        cost: t.cost || 0,
        quantity: t.quantity || 1,
        unit: t.unit || "un",
        isManual: true,
        taskId: `manual_${idx}`,
      };
    });

    const combined = [...formattedApiTasks, ...formattedManualTasks];
    return combined.sort((a, b) => {
      if (a.stage_order !== b.stage_order) return a.stage_order - b.stage_order;
      return new Date(a.start_date).getTime() - new Date(b.start_date).getTime();
    });
  }, [schedule, manualTasks, jiraMetadata]);

  // View bounds recalculation
  const { totalDays, projStart, scheduleEndDate, scheduleTotalCost } = useMemo(() => {
    if (allTasks.length === 0) {
      return { totalDays: 1, projStart: Date.now(), scheduleEndDate: "", scheduleTotalCost: 0 };
    }
    const dates = allTasks.map(t => new Date(t.start_date + "T00:00:00").getTime());
    const endDates = allTasks.map(t => new Date(t.end_date + "T00:00:00").getTime());
    const minStart = Math.min(...dates);
    const maxEnd = Math.max(...endDates);
    const daysCount = Math.max(1, Math.ceil((maxEnd - minStart) / 86400000));
    const totalCost = allTasks.reduce((acc, t) => acc + t.cost, 0);
    return {
      totalDays: daysCount,
      projStart: minStart,
      scheduleEndDate: new Date(maxEnd).toISOString().slice(0, 10),
      scheduleTotalCost: totalCost
    };
  }, [allTasks]);

  // Filtering
  const filteredTasks = useMemo(() => {
    return allTasks.filter(t => {
      const meta = getTaskMeta(t.assembly);
      const matchSearch = t.assembly.toLowerCase().includes(searchTerm.toLowerCase());
      const matchStatus = !statusFilter || meta.status === statusFilter;
      const matchPriority = !priorityFilter || meta.priority === priorityFilter;
      const matchAssignee = !assigneeFilter || meta.assignees.includes(assigneeFilter);
      return matchSearch && matchStatus && matchPriority && matchAssignee;
    });
  }, [allTasks, searchTerm, statusFilter, priorityFilter, assigneeFilter, getTaskMeta]);

  // Dynamic Cashflow monthly calculation
  const cashflow = useMemo<CashflowPoint[]>(() => {
    if (allTasks.length === 0) return [];
    const monthly = new Map<string, number>();
    for (const t of allTasks) {
      const start = new Date(t.start_date + "T00:00:00");
      const perDay = t.cost / Math.max(1, t.duration_days);
      for (let i = 0; i < t.duration_days; i++) {
        const d = new Date(start.getTime() + i * 86400000);
        const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
        monthly.set(key, (monthly.get(key) || 0) + perDay);
      }
    }
    let acc = 0;
    return [...monthly.keys()].sort().map((month) => {
      acc += monthly.get(month)!;
      return { month, amount: monthly.get(month)!, accumulated: acc };
    });
  }, [allTasks]);

  const maxMonthly = useMemo(() => Math.max(1, ...cashflow.map((c) => c.amount)), [cashflow]);

  async function act(fn: () => Promise<WorkPlanData>) {
    setActing(true);
    setError(null);
    try {
      const p = await fn();
      setPlan(p);
      setSchedule(p);
      const st = await api.getWorkPlan(projectId);
      setVersions(st.versions);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setActing(false);
    }
  }

  // Descarga del reporte PDF: no toca el estado del plan (a diferencia de act()).
  async function downloadReport() {
    setActing(true);
    setError(null);
    try {
      await api.downloadWorkReport(projectId, project?.name);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setActing(false);
    }
  }

  // Task overrides updater
  const updateTaskDates = async (taskName: string, start: string, end: string, duration: number, isManual: boolean, taskId?: any) => {
    if (isManual) {
      const updated = manualTasks.map(t => {
        if (t.assembly === taskName) {
          return { ...t, start_date: start, end_date: end, duration_days: duration };
        }
        return t;
      });
      saveManualTasks(updated);
    } else {
      if (plan && plan.status === "draft" && typeof taskId === "number") {
        try {
          await api.updateWorkTask(taskId, { planned_start: start, duration_days: duration });
          load();
        } catch (e) {
          setError("No se pudo actualizar la tarea en el servidor. Asegurate de estar en modo Borrador.");
        }
      } else {
        const updatedMeta = { ...jiraMetadata };
        if (!updatedMeta[taskName]) updatedMeta[taskName] = {} as any;
        updatedMeta[taskName] = {
          ...updatedMeta[taskName],
          startDateOverride: start,
          endDateOverride: end,
          durationOverride: duration,
          history: [
            ...(updatedMeta[taskName].history || []),
            { date: new Date().toLocaleDateString("es-AR"), change: `Fechas reprogramadas: ${fmtDate(start)} al ${fmtDate(end)} (${duration} días)` }
          ]
        };
        saveJiraMetadata(updatedMeta);
      }
    }
  };

  const getStageOrder = (stage: string) => {
    const orders: Record<string, number> = {
      "Fundación": 0,
      "Estructura": 1,
      "Mampostería": 2,
      "Instalaciones": 3,
      "Terminaciones": 4,
    };
    return orders[stage] !== undefined ? orders[stage] : 10;
  };

  const handleAddTask = () => {
    if (!newAssembly.trim()) return;
    if (allTasks.some(t => t.assembly === newAssembly)) {
      alert("Ya existe una tarea con ese nombre");
      return;
    }

    // Predecessor snaps the start date of B to end date of A
    let finalStartDate = newStartDate;
    if (newPredecessor) {
      const predTask = allTasks.find(t => t.assembly === newPredecessor);
      if (predTask) {
        finalStartDate = predTask.end_date;
      }
    }

    const startDateObj = new Date(finalStartDate + "T00:00:00");
    const endDateObj = new Date(startDateObj.getTime() + newDuration * 86400000);
    const newEndDateStr = endDateObj.toISOString().slice(0, 10);

    const task = {
      assembly: newAssembly,
      stage: newStage,
      stage_order: getStageOrder(newStage),
      duration_days: newDuration,
      start_date: finalStartDate,
      end_date: newEndDateStr,
      cost: 0,
      quantity: 1,
      unit: "un"
    };

    saveManualTasks([...manualTasks, task]);
    
    const updatedMeta = { ...jiraMetadata };
    updatedMeta[newAssembly] = {
      status: newStatus,
      priority: newPriority,
      isBlocked: newIsBlocked,
      blockedReason: newBlockedReason,
      assignees: newAssignees,
      description: newDescription,
      history: [
        { date: new Date().toLocaleDateString("es-AR"), change: "Tarea creada manualmente con campos avanzados." }
      ]
    };
    if (newPredecessor) {
      updatedMeta[newAssembly].startDateOverride = finalStartDate;
      updatedMeta[newAssembly].endDateOverride = newEndDateStr;
      updatedMeta[newAssembly].durationOverride = newDuration;
      updatedMeta[newAssembly].history.push({
        date: new Date().toLocaleDateString("es-AR"),
        change: `Dependencia creada vinculada a tarea "${newPredecessor}".`
      });
    }
    saveJiraMetadata(updatedMeta);
    
    // Reset form states
    setIsAddModalOpen(false);
    setNewAssembly("");
    setNewDescription("");
    setNewPriority("Media");
    setNewStatus("Pendiente");
    setNewAssignees([]);
    setNewPredecessor("");
    setNewIsBlocked(false);
    setNewBlockedReason("");
  };

  const handleDeleteTask = (taskName: string) => {
    if (confirm(`¿Estás seguro de eliminar la tarea "${taskName}"?`)) {
      saveManualTasks(manualTasks.filter(t => t.assembly !== taskName));
      const updatedMeta = { ...jiraMetadata };
      delete updatedMeta[taskName];
      saveJiraMetadata(updatedMeta);
      setIsDrawerOpen(false);
      setActiveTask(null);
    }
  };

  const updateTaskMetaField = (taskName: string, field: string, value: any, changeText: string) => {
    const updatedMeta = { ...jiraMetadata };
    const current = getTaskMeta(taskName);
    
    updatedMeta[taskName] = {
      ...current,
      [field]: value,
      history: [
        ...(current.history || []),
        { date: new Date().toLocaleDateString("es-AR"), change: changeText }
      ]
    };
    saveJiraMetadata(updatedMeta);
    
    if (activeTask && activeTask.assembly === taskName) {
      setActiveTask((prev: any) => ({ ...prev, [field]: value }));
    }
  };

  // Drag handlers
  const startDrag = (e: React.MouseEvent, task: any) => {
    e.preventDefault();
    e.stopPropagation();
    const tOffset = (new Date(task.start_date + "T00:00:00").getTime() - projStart) / 86400000;
    dragInfo.current = {
      taskName: task.assembly,
      initialLeft: tOffset * 16,
      initialWidth: task.duration_days * 16,
      initialMouseX: e.clientX,
      daysOffset: 0,
      durationDays: task.duration_days,
      isManual: task.isManual,
      taskId: task.taskId,
    };
    setIsDragging(true);
    document.addEventListener("mousemove", handleDragMove);
    document.addEventListener("mouseup", handleDragEnd);
  };

  const startResize = (e: React.MouseEvent, task: any) => {
    e.preventDefault();
    e.stopPropagation();
    dragInfo.current = {
      taskName: task.assembly,
      initialLeft: 0,
      initialWidth: task.duration_days * 16,
      initialMouseX: e.clientX,
      daysOffset: 0,
      durationDays: task.duration_days,
      isManual: task.isManual,
      taskId: task.taskId,
    };
    setIsResizing(true);
    document.addEventListener("mousemove", handleResizeMove);
    document.addEventListener("mouseup", handleResizeEnd);
  };

  const handleDragMove = (e: MouseEvent) => {
    if (!dragInfo.current) return;
    const deltaX = e.clientX - dragInfo.current.initialMouseX;
    const deltaDays = Math.round(deltaX / 16);
    dragInfo.current.daysOffset = deltaDays;
    setLiveDrag({
      taskName: dragInfo.current.taskName,
      daysOffset: deltaDays,
      durationDays: dragInfo.current.durationDays
    });
  };

  const handleResizeMove = (e: MouseEvent) => {
    if (!dragInfo.current) return;
    const deltaX = e.clientX - dragInfo.current.initialMouseX;
    const deltaDays = Math.round(deltaX / 16);
    const newDuration = Math.max(1, dragInfo.current.durationDays + deltaDays);
    setLiveDrag({
      taskName: dragInfo.current.taskName,
      daysOffset: 0,
      durationDays: newDuration
    });
  };

  const handleDragEnd = async () => {
    document.removeEventListener("mousemove", handleDragMove);
    document.removeEventListener("mouseup", handleDragEnd);
    setIsDragging(false);
    if (dragInfo.current && liveDrag) {
      const { taskName, daysOffset, isManual, taskId } = dragInfo.current;
      if (daysOffset !== 0) {
        const t = allTasks.find(x => x.assembly === taskName);
        if (t) {
          const originalStart = new Date(t.start_date + "T00:00:00");
          const newStart = new Date(originalStart.getTime() + daysOffset * 86400000);
          const newStartDateStr = newStart.toISOString().slice(0, 10);
          const newEndDate = new Date(newStart.getTime() + t.duration_days * 86400000);
          const newEndDateStr = newEndDate.toISOString().slice(0, 10);
          await updateTaskDates(taskName, newStartDateStr, newEndDateStr, t.duration_days, isManual, taskId);
        }
      }
    }
    setLiveDrag(null);
    dragInfo.current = null;
  };

  const handleResizeEnd = async () => {
    document.removeEventListener("mousemove", handleResizeMove);
    document.removeEventListener("mouseup", handleResizeEnd);
    setIsResizing(false);
    if (dragInfo.current && liveDrag) {
      const { taskName, isManual, taskId } = dragInfo.current;
      const newDuration = liveDrag.durationDays;
      if (newDuration !== dragInfo.current.durationDays) {
        const t = allTasks.find(x => x.assembly === taskName);
        if (t) {
          const start = new Date(t.start_date + "T00:00:00");
          const newEnd = new Date(start.getTime() + newDuration * 86400000);
          const newEndDateStr = newEnd.toISOString().slice(0, 10);
          await updateTaskDates(taskName, t.start_date, newEndDateStr, newDuration, isManual, taskId);
        }
      }
    }
    setLiveDrag(null);
    dragInfo.current = null;
  };

  const getPriorityBadge = (priority: string) => {
    switch (priority) {
      case "Baja": return <span className="text-green-500 font-medium font-mono">↓ Baja</span>;
      case "Alta": return <span className="text-orange-500 font-medium font-mono">↑ Alta</span>;
      case "Crítica": return <span className="text-red-500 font-bold font-mono animate-pulse">!! Crítica</span>;
      default: return <span className="text-slate-400 font-medium font-mono">• Media</span>;
    }
  };

  const getStatusColor = (status: string, isBlocked: boolean) => {
    if (isBlocked || status === "Bloqueada") return "#dc2626"; // Rojo
    switch (status) {
      case "En progreso": return "#2563eb"; // Azul
      case "En revisión": return "#7c3aed"; // Violeta
      case "Completada": return "#16a34a"; // Verde
      case "Cancelada": return "#ea580c"; // Naranja
      default: return "#94a3b8"; // Gris (Pendiente)
    }
  };

  if (loading) return <div className="p-10 text-center text-slate-500">Cargando cronograma…</div>;
  if (!project) return <div className="p-10 text-center">Proyecto no encontrado</div>;

  const hasData = allTasks.length > 0;

  return (
    <main className="mx-auto max-w-none px-6 md:px-10 py-10">
      <header className="mb-6 flex justify-between items-end">
        <div>
          <button onClick={() => router.back()} className="inline-flex items-center gap-1 text-sm font-medium text-slate-500 transition hover:text-brand-600 dark:text-slate-400">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6" /></svg>
            Volver
          </button>
          <h1 className="mt-2 text-3xl font-bold text-slate-900 dark:text-white">Cronograma de obra</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Planificación profesional centralizada y gestión integrada de estados, prioridades y bloqueos.
          </p>
        </div>
      </header>

      {/* Estado del plan de obra: simulación → borrador → baseline congelado */}
      <div className={`mb-4 flex flex-wrap items-center gap-3 rounded-xl border p-4 ${
        plan?.status === "active"
          ? "border-green-300 bg-green-50 dark:border-green-500/30 dark:bg-green-500/10"
          : plan?.status === "draft"
            ? "border-amber-300 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10"
            : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
      }`}>
        {plan ? (
          <>
            <span className={`rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wide ${
              plan.status === "active"
                ? "bg-green-600 text-white"
                : "bg-amber-500 text-white"
            }`}>
              {plan.status === "active" ? `Plan activo · v${plan.version}` : `Borrador · v${plan.version}`}
            </span>
            <span className="text-sm text-slate-600 dark:text-slate-300">
              {plan.status === "active"
                ? `Baseline congelado el ${plan.frozen_at ? fmtDate(plan.frozen_at.slice(0, 10)) : "—"} — inmutable; para cambiarlo, reprogramá una versión nueva.`
                : "Revisá tareas y fechas; al congelar se convierte en el baseline contra el que se mide la obra."}
            </span>
            <div className="ml-auto flex gap-2">
              {plan.status === "draft" && (
                <>
                  <button onClick={() => act(() => api.createWorkPlanDraft(projectId, { startDate, crews }))} disabled={acting}
                    className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-slate-400 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300">
                    Regenerar borrador
                  </button>
                  <button onClick={() => act(() => api.freezeWorkPlan(plan.plan_id))} disabled={acting}
                    className="rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-green-500 disabled:opacity-50">
                    {acting ? "…" : "Congelar baseline"}
                  </button>
                </>
              )}
              {plan.status === "active" && (
                <>
                  <Link href={`/projects/${projectId}/obra`}
                    className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-500">
                    Registrar avances →
                  </Link>
                  <button onClick={downloadReport} disabled={acting}
                    className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-slate-400 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300">
                    {acting ? "…" : "Reporte PDF"}
                  </button>
                  <button onClick={() => act(() => api.rebaselineWorkPlan(projectId))} disabled={acting}
                    className="rounded-lg border border-green-600 px-4 py-2 text-sm font-semibold text-green-700 transition hover:bg-green-100 disabled:opacity-50 dark:text-green-400 dark:hover:bg-green-500/10">
                    {acting ? "…" : "Reprogramar (nueva versión)"}
                  </button>
                </>
              )}
            </div>
          </>
        ) : (
          <>
            <span className="rounded-full bg-slate-500 px-3 py-1 text-xs font-bold uppercase tracking-wide text-white">Simulación</span>
            <span className="text-sm text-slate-600 dark:text-slate-300">
              Cronograma calculado al vuelo. Generá el plan de obra para congelar un baseline y empezar el seguimiento.
            </span>
            <button onClick={() => act(() => api.createWorkPlanDraft(projectId, { startDate, crews }))} disabled={acting}
              className="ml-auto rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-500 disabled:opacity-50">
              {acting ? "Generando…" : "Generar plan de obra"}
            </button>
          </>
        )}
        {versions.length > 1 && (
          <div className="w-full text-xs text-slate-500 dark:text-slate-400">
            Historial: {versions.map((v) => `v${v.version} (${v.status === "active" ? "activo" : v.status === "draft" ? "borrador" : "reemplazado"})`).join(" · ")}
          </div>
        )}
        {error && <div className="w-full text-sm text-red-600 dark:text-red-400">{error}</div>}
      </div>

      {/* Controles & Filtros */}
      <div className="mb-6 flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        
        {/* Superior: Parámetros del plan */}
        <div className="flex flex-wrap items-end gap-4 border-b border-slate-100 dark:border-slate-800 pb-4">
          {plan?.status !== "active" && (
            <>
              <label className="flex flex-col text-xs font-medium text-slate-600 dark:text-slate-400">
                Inicio de obra
                <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
                  className="mt-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800" />
              </label>
              <label className="flex flex-col text-xs font-medium text-slate-600 dark:text-slate-400">
                Cuadrillas (paralelo)
                <input type="number" min={1} max={10} value={crews} onChange={(e) => setCrews(Math.max(1, Number(e.target.value)))}
                  className="mt-1 w-28 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800" />
              </label>
            </>
          )}
          {plan?.status === "active" && (
            <div className="text-xs text-slate-500 dark:text-slate-400 self-center">
              Inicio: <strong>{fmtDate(plan.start_date)}</strong> · Cuadrillas: <strong>{plan.crews}</strong>
            </div>
          )}
          
          <div className="ml-auto flex gap-6 text-right">
            <div>
              <div className="text-xs text-slate-500">Duración</div>
              <div className="text-lg font-bold text-slate-900 dark:text-white">{totalDays} días</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Fin estimado</div>
              <div className="text-lg font-bold text-slate-900 dark:text-white">{fmtDate(scheduleEndDate)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Costo total</div>
              <div className="text-lg font-bold text-brand-600 dark:text-brand-400">${fmtARS(scheduleTotalCost)}</div>
            </div>
          </div>
        </div>

        {/* Inferior: Búsqueda y Filtros Jira */}
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input 
              type="text" 
              placeholder="Buscar tarea..." 
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-9 pr-4 py-1.5 w-full rounded-md border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs"
            />
          </div>

          <div className="flex items-center gap-2">
            <Filter className="h-3.5 w-3.5 text-slate-400" />
            <select 
              value={statusFilter} 
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-2 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs"
            >
              <option value="">Todos los Estados</option>
              <option value="Pendiente">Pendiente</option>
              <option value="En progreso">En progreso</option>
              <option value="En revisión">En revisión</option>
              <option value="Completada">Completada</option>
              <option value="Bloqueada">Bloqueada</option>
              <option value="Cancelada">Cancelada</option>
            </select>

            <select 
              value={priorityFilter} 
              onChange={(e) => setPriorityFilter(e.target.value)}
              className="px-2 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs"
            >
              <option value="">Todas las Prioridades</option>
              <option value="Baja">Baja</option>
              <option value="Media">Media</option>
              <option value="Alta">Alta</option>
              <option value="Crítica">Crítica</option>
            </select>

            <select 
              value={assigneeFilter} 
              onChange={(e) => setAssigneeFilter(e.target.value)}
              className="px-2 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs"
            >
              <option value="">Cualquier Responsable</option>
              {teamNames.map(name => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>

            <button 
              onClick={() => setIsAddModalOpen(true)}
              className="bg-brand-600 hover:bg-brand-500 text-white rounded-md px-3 py-1.5 text-xs font-semibold flex items-center gap-1.5 shadow-sm transition-colors ml-2"
            >
              <Plus className="h-3.5 w-3.5" /> Crear Tarea
            </button>
          </div>
        </div>

      </div>

      {!hasData ? (
        <div className="rounded-xl border border-dashed border-slate-300 p-10 text-center dark:border-slate-700">
          <p className="text-slate-500 dark:text-slate-400">No hay tareas asignadas en este proyecto.</p>
          <Link href={`/projects/${project.id}`} className="mt-4 inline-block font-semibold text-brand-600 dark:text-brand-400">Ir a asignar sistemas →</Link>
        </div>
      ) : (
        <>
          {/* Gantt Enterprise Split View */}
          <div className="mb-8 rounded-xl border border-slate-200 bg-white shadow-md dark:border-slate-800 dark:bg-slate-900 overflow-hidden">
            <div className="flex min-w-full overflow-x-auto">
              
              {/* Left Panel: WBS Table (Sticky left) */}
              <div className="sticky left-0 z-20 shrink-0 border-r border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-950 shadow-[4px_0_8px_-3px_rgba(0,0,0,0.15)] w-[640px]">
                {/* Table Header */}
                <div className="flex h-20 border-b border-slate-200 dark:border-slate-800 font-semibold text-xs text-slate-500 dark:text-slate-400 uppercase tracking-wider items-center bg-slate-100 dark:bg-slate-900 px-3">
                  <div className="w-8 shrink-0">ID</div>
                  <div className="w-40 shrink-0 truncate pl-2">Tarea</div>
                  <div className="w-14 shrink-0 text-center">Dur.</div>
                  <div className="w-16 shrink-0 text-center">Inicio</div>
                  <div className="w-16 shrink-0 text-center">Fin</div>
                  <div className="w-12 shrink-0 text-center">%</div>
                  <div className="w-12 shrink-0 text-center">Pred.</div>
                  <div className="w-16 shrink-0 text-center">Prior.</div>
                  <div className="w-20 shrink-0 text-right">Etapa</div>
                </div>
                
                {/* Table Body */}
                <div className="divide-y divide-slate-100 dark:divide-slate-800/60 bg-white dark:bg-slate-900">
                  {(() => {
                    const maxDurationPerStage: Record<string, number> = {};
                    allTasks.forEach((t) => {
                      maxDurationPerStage[t.stage] = Math.max(maxDurationPerStage[t.stage] || 0, t.duration_days);
                    });

                    const stageTasks: Record<number, typeof allTasks> = {};
                    allTasks.forEach((t) => {
                      if (!stageTasks[t.stage_order]) stageTasks[t.stage_order] = [];
                      stageTasks[t.stage_order].push(t);
                    });

                    return filteredTasks.map((t, idx) => {
                      const id = t.id;
                      const prog = progress?.tasks.find((p) => p.name === t.assembly);
                      const pct = prog ? prog.pct : 0;
                      const meta = getTaskMeta(t.assembly);
                      
                      // Predecessors list mapping
                      let predecessorsStr = "-";
                      if (t.stage_order > 0) {
                        const prevOrders = Object.keys(stageTasks)
                          .map(Number)
                          .filter((o) => o < t.stage_order)
                          .sort((a, b) => b - a);
                        if (prevOrders.length > 0) {
                          const closestPrevOrder = prevOrders[0];
                          const prevTasks = stageTasks[closestPrevOrder];
                          predecessorsStr = prevTasks
                            .map((pt) => allTasks.findIndex((o) => o.assembly === pt.assembly) + 1)
                            .join(",");
                        }
                      }

                      return (
                        <div 
                          key={t.assembly} 
                          onDoubleClick={() => {
                            setActiveTask(t);
                            setIsDrawerOpen(true);
                            setActiveModalTab("detail");
                          }}
                          className="flex h-10 items-center px-3 text-xs bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors cursor-pointer group"
                        >
                          <div className="w-8 shrink-0 font-mono text-slate-400">{id}</div>
                          <div className="w-40 shrink-0 font-medium text-slate-800 dark:text-slate-200 truncate pl-2 flex items-center gap-1.5">
                            {meta.isBlocked && <span title={`Bloqueada: ${meta.blockedReason}`}><Ban className="h-3 w-3 text-red-500" /></span>}
                            <span className="truncate" title={t.assembly}>{t.assembly}</span>
                          </div>
                          <div className="w-14 shrink-0 text-center text-slate-600 dark:text-slate-400 font-mono">{t.duration_days}d</div>
                          <div className="w-16 shrink-0 text-center text-slate-500 dark:text-slate-400 font-mono">{t.start_date.slice(8,10)}/{t.start_date.slice(5,7)}</div>
                          <div className="w-16 shrink-0 text-center text-slate-500 dark:text-slate-400 font-mono">{t.end_date.slice(8,10)}/{t.end_date.slice(5,7)}</div>
                          
                          {/* Quick change % dropdown/input click */}
                          <div className="w-12 shrink-0 text-center font-bold text-slate-700 dark:text-slate-300 font-mono">
                            {pct > 0 ? `${pct}%` : "0%"}
                          </div>

                          <div className="w-12 shrink-0 text-center text-slate-400 font-mono" title={`Fin a Comienzo con ID ${predecessorsStr}`}>{predecessorsStr}</div>
                          <div className="w-16 shrink-0 text-center flex items-center justify-center">{getPriorityBadge(meta.priority)}</div>
                          <div className="w-20 shrink-0 text-right text-[10px] font-semibold text-slate-400 truncate" title={t.stage}>{t.stage}</div>
                        </div>
                      );
                    });
                  })()}
                </div>
              </div>

              {/* Right Panel: WBS Timeline / Gantt Chart */}
              <div className="flex-1 relative overflow-x-auto select-none bg-slate-950/20">
                {(() => {
                  const DAY_WIDTH = 16;
                  const ROW_HEIGHT = 40;

                  // Generate days list
                  const days: { dateStr: string; dayNum: number; isWeekend: boolean }[] = [];
                  const start = new Date(projStart);
                  for (let i = 0; i < totalDays; i++) {
                    const d = new Date(start.getTime() + i * 86400000);
                    const dayOfWeek = d.getDay();
                    days.push({
                      dateStr: d.toISOString().slice(0,10),
                      dayNum: d.getDate(),
                      isWeekend: dayOfWeek === 0 || dayOfWeek === 6,
                    });
                  }

                  // Group by months for Month header
                  const monthBlocks: { label: string; width: number }[] = [];
                  let currentMonth = "";
                  let currentDays = 0;
                  days.forEach((day, i) => {
                    const mName = new Date(day.dateStr + "T00:00:00").toLocaleDateString("es-AR", { month: "long", year: "numeric" });
                    const mNameCap = mName.charAt(0).toUpperCase() + mName.slice(1);
                    if (i === 0) {
                      currentMonth = mNameCap;
                      currentDays = 1;
                    } else if (mNameCap === currentMonth) {
                      currentDays++;
                    } else {
                      monthBlocks.push({ label: currentMonth, width: currentDays * DAY_WIDTH });
                      currentMonth = mNameCap;
                      currentDays = 1;
                    }
                  });
                  monthBlocks.push({ label: currentMonth, width: currentDays * DAY_WIDTH });

                  // Group by weeks
                  const weekBlocks: { label: string; width: number }[] = [];
                  const totalWeeks = Math.ceil(totalDays / 7);
                  for (let i = 0; i < totalWeeks; i++) {
                    const daysInWeek = Math.min(7, totalDays - i * 7);
                    weekBlocks.push({
                      label: `S${i + 1}`,
                      width: daysInWeek * DAY_WIDTH,
                    });
                  }

                  // Predecessors list mapping
                  const maxDurationPerStage: Record<string, number> = {};
                  allTasks.forEach((t) => {
                    maxDurationPerStage[t.stage] = Math.max(maxDurationPerStage[t.stage] || 0, t.duration_days);
                  });

                  const stageTasks: Record<number, typeof allTasks> = {};
                  allTasks.forEach((t) => {
                    if (!stageTasks[t.stage_order]) stageTasks[t.stage_order] = [];
                    stageTasks[t.stage_order].push(t);
                  });

                  // Render dependencies SVG paths
                  const depPaths: string[] = [];
                  filteredTasks.forEach((t, idx) => {
                    if (t.stage_order > 0) {
                      const prevOrders = Object.keys(stageTasks)
                        .map(Number)
                        .filter((o) => o < t.stage_order)
                        .sort((a, b) => b - a);
                      if (prevOrders.length > 0) {
                        const closestPrevOrder = prevOrders[0];
                        const prevTasks = stageTasks[closestPrevOrder];
                        
                        prevTasks.forEach((pt) => {
                          const pIdx = filteredTasks.findIndex((o) => o.assembly === pt.assembly);
                          if (pIdx !== -1) {
                            const pTask = filteredTasks[pIdx];
                            
                            const pOffset = (new Date(pTask.start_date + "T00:00:00").getTime() - projStart) / 86400000;
                            const xA = (pOffset + pTask.duration_days) * DAY_WIDTH;
                            const yA = pIdx * ROW_HEIGHT + ROW_HEIGHT / 2;

                            const cOffset = (new Date(t.start_date + "T00:00:00").getTime() - projStart) / 86400000;
                            const xB = cOffset * DAY_WIDTH;
                            const yB = idx * ROW_HEIGHT + ROW_HEIGHT / 2;

                            const arrowSpacing = 8;
                            if (xB >= xA + arrowSpacing) {
                              depPaths.push(`M ${xA} ${yA} L ${xA + arrowSpacing} ${yA} L ${xA + arrowSpacing} ${yB} L ${xB} ${yB}`);
                            } else {
                              const yMid = (yA + yB) / 2;
                              depPaths.push(`M ${xA} ${yA} L ${xA + arrowSpacing} ${yA} L ${xA + arrowSpacing} ${yMid} L ${xB - arrowSpacing} ${yMid} L ${xB - arrowSpacing} ${yB} L ${xB} ${yB}`);
                            }
                          }
                        });
                      }
                    }
                  });

                  return (
                    <div style={{ width: totalDays * DAY_WIDTH }}>
                      {/* Timeline Header (Months + Weeks + Days) */}
                      <div className="sticky top-0 z-10 bg-slate-100 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800">
                        {/* Months Row */}
                        <div className="flex h-7 border-b border-slate-200 dark:border-slate-800 text-[10px] font-bold text-slate-600 dark:text-slate-400 items-center">
                          {monthBlocks.map((b, i) => (
                            <div key={i} className="shrink-0 border-r border-slate-200 dark:border-slate-800/80 px-2 truncate" style={{ width: b.width }}>
                              {b.label}
                            </div>
                          ))}
                        </div>
                        {/* Weeks Row */}
                        <div className="flex h-6 border-b border-slate-200 dark:border-slate-800 text-[9px] font-semibold text-slate-500 dark:text-slate-400 items-center bg-slate-50 dark:bg-slate-900/60">
                          {weekBlocks.map((b, i) => (
                            <div key={i} className="shrink-0 border-r border-slate-200 dark:border-slate-800/80 px-2 truncate text-center" style={{ width: b.width }}>
                              {b.label}
                            </div>
                          ))}
                        </div>
                        {/* Days/Dates Row */}
                        <div className="flex h-7 text-[9px] text-slate-500 dark:text-slate-400 font-mono items-center">
                          {days.map((d, i) => (
                            <div key={i} className={`flex flex-col h-full shrink-0 border-r border-slate-200/50 dark:border-slate-800/50 items-center justify-center ${d.isWeekend ? "bg-slate-200/40 dark:bg-slate-800/20" : ""}`} style={{ width: DAY_WIDTH }}>
                              <span className="font-bold text-[10px]">{d.dayNum}</span>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Timeline Body (Gantt grid + bars) */}
                      <div className="relative divide-y divide-slate-100 dark:divide-slate-800/60 bg-white dark:bg-slate-900/40">
                        
                        {/* Vertical Grid Reference Lines */}
                        <div className="absolute inset-y-0 left-0 right-0 flex pointer-events-none">
                          {days.map((d, i) => (
                            <div key={i} className={`h-full shrink-0 border-r border-slate-100 dark:border-slate-800/20 ${d.isWeekend ? "bg-slate-100/10 dark:bg-slate-800/5" : ""}`} style={{ width: DAY_WIDTH }} />
                          ))}
                        </div>

                        {/* SVG Dependencies Layer */}
                        <svg className="absolute inset-0 w-full h-full pointer-events-none z-10">
                          <defs>
                            <marker id="arrow" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                              <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#64748b" />
                            </marker>
                          </defs>
                          {depPaths.map((p, i) => (
                            <path key={i} d={p} fill="none" stroke="rgba(100, 116, 139, 0.45)" strokeWidth="1.2" markerEnd="url(#arrow)" />
                          ))}
                        </svg>

                        {/* Gantt Bars Rows */}
                        {filteredTasks.map((t, idx) => {
                          const prog = progress?.tasks.find((p) => p.name === t.assembly);
                          const pct = prog ? prog.pct : 0;
                          const meta = getTaskMeta(t.assembly);
                          const isCompleted = meta.status === "Completada";
                          
                          // Determine if task is critical path (longest in stage and not completed)
                          const isCritical = t.duration_days === maxDurationPerStage[t.stage] && !isCompleted;
                          const statusColor = getStatusColor(meta.status, meta.isBlocked);

                          // Position Calculation
                          const tOffset = (new Date(t.start_date + "T00:00:00").getTime() - projStart) / 86400000;
                          let leftPos = tOffset * DAY_WIDTH;
                          let barWidth = t.duration_days * DAY_WIDTH;

                          // Drag & drop calculations overlay
                          if (liveDrag && liveDrag.taskName === t.assembly) {
                            leftPos = (tOffset + liveDrag.daysOffset) * DAY_WIDTH;
                            barWidth = liveDrag.durationDays * DAY_WIDTH;
                          }

                          return (
                            <div 
                              key={t.assembly} 
                              onDoubleClick={() => {
                                setActiveTask(t);
                                setIsDrawerOpen(true);
                                setActiveModalTab("detail");
                              }}
                              className="flex h-10 items-center relative hover:bg-slate-50/50 dark:hover:bg-slate-800/10 transition-colors cursor-pointer"
                            >
                              
                              {/* Task Bar */}
                              <div 
                                className={`absolute h-6 rounded shadow-sm flex items-center justify-between px-2 text-[10px] font-semibold text-white group select-none transition-transform duration-200 hover:scale-[1.01] hover:shadow ${
                                  isCritical ? "shadow-[0_0_8px_rgba(239,68,68,0.6)] border-2 border-red-500" : ""
                                }`}
                                style={{
                                  left: leftPos,
                                  width: Math.max(16, barWidth),
                                  backgroundColor: statusColor,
                                  cursor: isDragging || isResizing ? "grabbing" : "grab"
                                }}
                                onMouseDown={(e) => startDrag(e, t)}
                                title={`${t.assembly} · ${t.duration_days} días · ${fmtDate(t.start_date)} al ${fmtDate(t.end_date)}`}
                              >
                                
                                {/* Inner progress highlight strip */}
                                {pct > 0 && (
                                  <div className="absolute bottom-0 left-0 h-1 rounded-bl-sm bg-white/70"
                                       style={{ width: `${Math.min(100, pct)}%` }} />
                                )}
                                
                                <span className="truncate pr-1 flex items-center gap-1">
                                  {meta.isBlocked && <Ban className="h-2.5 w-2.5 shrink-0" />}
                                  {pct > 0 ? `${pct}%` : ""}
                                </span>
                                
                                <span className="font-mono">${fmtARS(t.cost)}</span>

                                {/* Resize handle (right edge) */}
                                <div 
                                  className="absolute right-0 top-0 bottom-0 w-1.5 bg-white/20 hover:bg-white/40 cursor-col-resize rounded-r"
                                  onMouseDown={(e) => startResize(e, t)}
                                />
                              </div>

                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })()}
              </div>

            </div>
          </div>

          {/* Curva de inversión */}
          <div className="mt-8 rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <h2 className="mb-1 text-lg font-bold text-slate-900 dark:text-white">Curva de inversión</h2>
            <p className="mb-5 text-sm text-slate-500 dark:text-slate-400">Cuánto se invierte por mes y el acumulado a lo largo de la obra.</p>
            <div className="flex items-end gap-3" style={{ height: 220 }}>
              {cashflow.map((c) => {
                const accPct = (c.accumulated / (scheduleTotalCost || 1)) * 100;
                return (
                  <div key={c.month} className="flex flex-1 flex-col items-center gap-2">
                    <div className="relative flex w-full flex-1 items-end">
                      <div className="w-full rounded-t-md bg-brand-500/80 transition-all hover:bg-brand-500"
                        style={{ height: `${(c.amount / maxMonthly) * 100}%` }}
                        title={`${c.month}: $${fmtARS(c.amount)} (acum. $${fmtARS(c.accumulated)})`} />
                    </div>
                    <div className="text-[10px] font-medium text-slate-500">{c.month.slice(2)}</div>
                    <div className="text-[10px] text-slate-400">{accPct.toFixed(0)}%</div>
                  </div>
                );
              })}
            </div>
            <div className="mt-4 flex justify-between border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-800">
              <span>Inicio: {fmtDate(allTasks[0]?.start_date)}</span>
              <span>Inversión total: <strong className="text-brand-600 dark:text-brand-400">${fmtARS(scheduleTotalCost)}</strong></span>
            </div>
          </div>
        </>
      )}

      {/* Details Side-Drawer Panel */}
      {isDrawerOpen && activeTask && (() => {
        const meta = getTaskMeta(activeTask.assembly);
        const stageTasks: Record<number, typeof allTasks> = {};
        allTasks.forEach((t) => {
          if (!stageTasks[t.stage_order]) stageTasks[t.stage_order] = [];
          stageTasks[t.stage_order].push(t);
        });

        // Predecessors list mapping
        let predecessorsList: number[] = [];
        if (activeTask.stage_order > 0) {
          const prevOrders = Object.keys(stageTasks)
            .map(Number)
            .filter((o) => o < activeTask.stage_order)
            .sort((a, b) => b - a);
          if (prevOrders.length > 0) {
            predecessorsList = stageTasks[prevOrders[0]].map((pt) => allTasks.findIndex((o) => o.assembly === pt.assembly) + 1);
          }
        }

        // Successors list mapping
        let successorsList: number[] = [];
        const nextOrders = Object.keys(stageTasks)
          .map(Number)
          .filter((o) => o > activeTask.stage_order)
          .sort((a, b) => a - b);
        if (nextOrders.length > 0) {
          successorsList = stageTasks[nextOrders[0]].map((pt) => allTasks.findIndex((o) => o.assembly === pt.assembly) + 1);
        }

        return (
          <div className="fixed inset-0 z-50 overflow-hidden flex items-center justify-center">
            <div className="absolute inset-0 bg-slate-900/60 backdrop-blur-sm transition-opacity" onClick={() => setIsDrawerOpen(false)} />
            <div className="relative max-w-lg w-full bg-white dark:bg-slate-900 shadow-2xl rounded-xl border border-slate-200 dark:border-slate-800 p-6 flex flex-col h-[580px] animate-scale-up">
              
              {/* Header */}
              <div className="flex justify-between items-center border-b border-slate-100 dark:border-slate-800 pb-4 mb-4">
                <div className="flex items-center gap-2">
                  <Clipboard className="h-5 w-5 text-brand-600" />
                  <h3 className="text-lg font-bold text-slate-900 dark:text-white truncate max-w-[280px]" title={activeTask.assembly}>
                    {activeTask.assembly}
                  </h3>
                </div>
                <button onClick={() => setIsDrawerOpen(false)} className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800">
                  <X className="h-5 w-5 text-slate-400" />
                </button>
              </div>

              {/* Tabs Navigation */}
              <div className="flex border-b border-slate-200 dark:border-slate-800 mb-4 text-xs font-semibold text-slate-500">
                <button 
                  onClick={() => setActiveModalTab("detail")} 
                  className={`pb-2 px-1 border-b-2 transition-colors ${activeModalTab === "detail" ? "border-brand-600 text-brand-600 dark:text-brand-400 font-bold" : "border-transparent hover:text-slate-800 dark:hover:text-slate-200"}`}
                >
                  Detalle
                </button>
                <button 
                  onClick={() => setActiveModalTab("responsibles")} 
                  className={`ml-4 pb-2 px-1 border-b-2 transition-colors ${activeModalTab === "responsibles" ? "border-brand-600 text-brand-600 dark:text-brand-400 font-bold" : "border-transparent hover:text-slate-800 dark:hover:text-slate-200"}`}
                >
                  Responsable
                </button>
                <button 
                  onClick={() => setActiveModalTab("history")} 
                  className={`ml-4 pb-2 px-1 border-b-2 transition-colors ${activeModalTab === "history" ? "border-brand-600 text-brand-600 dark:text-brand-400 font-bold" : "border-transparent hover:text-slate-800 dark:hover:text-slate-200"}`}
                >
                  Historial
                </button>
              </div>

              {/* Body (Scrollable fields) */}
              <div className="flex-1 overflow-y-auto space-y-4 pr-1 text-xs">
                
                {activeModalTab === "detail" && (
                  <>
                    {/* Description */}
                    <div className="flex flex-col gap-1">
                      <label className="font-semibold text-slate-500 dark:text-slate-400">Descripción / Notas</label>
                      <textarea 
                        value={meta.description} 
                        onChange={(e) => updateTaskMetaField(activeTask.assembly, "description", e.target.value, "Descripción modificada.")}
                        placeholder="Detalles sobre el alcance, mano de obra o especificaciones..."
                        className="p-2 w-full h-20 rounded border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 focus:outline-none focus:ring-1 focus:ring-brand-500"
                      />
                    </div>

                    {/* Grid: Dates, Duration, Stage */}
                    <div className="grid grid-cols-2 gap-3">
                      <div className="flex flex-col gap-1">
                        <label className="font-semibold text-slate-500 dark:text-slate-400">Inicio Estimado</label>
                        <input 
                          type="date" 
                          value={activeTask.start_date}
                          onChange={(e) => {
                            const start = e.target.value;
                            const duration = activeTask.duration_days;
                            const startDateObj = new Date(start + "T00:00:00");
                            const endDateObj = new Date(startDateObj.getTime() + duration * 86400000);
                            const end = endDateObj.toISOString().slice(0, 10);
                            updateTaskDates(activeTask.assembly, start, end, duration, activeTask.isManual, activeTask.taskId);
                          }}
                          className="p-1.5 border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 rounded font-mono"
                        />
                      </div>

                      <div className="flex flex-col gap-1">
                        <label className="font-semibold text-slate-500 dark:text-slate-400">Duración (Días)</label>
                        <input 
                          type="number" 
                          min={1}
                          value={activeTask.duration_days}
                          onChange={(e) => {
                            const duration = Math.max(1, Number(e.target.value));
                            const start = activeTask.start_date;
                            const startDateObj = new Date(start + "T00:00:00");
                            const endDateObj = new Date(startDateObj.getTime() + duration * 86400000);
                            const end = endDateObj.toISOString().slice(0, 10);
                            updateTaskDates(activeTask.assembly, start, end, duration, activeTask.isManual, activeTask.taskId);
                          }}
                          className="p-1.5 border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 rounded font-mono"
                        />
                      </div>
                    </div>

                    {/* Status and Priority dropdowns */}
                    <div className="grid grid-cols-2 gap-3">
                      <div className="flex flex-col gap-1">
                        <label className="font-semibold text-slate-500 dark:text-slate-400">Estado de Gestión</label>
                        <select 
                          value={meta.status}
                          onChange={(e) => updateTaskMetaField(activeTask.assembly, "status", e.target.value, `Estado cambiado a ${e.target.value}`)}
                          className="p-1.5 border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 rounded font-semibold"
                        >
                          <option value="Pendiente">Pendiente</option>
                          <option value="En progreso">En progreso</option>
                          <option value="En revisión">En revisión</option>
                          <option value="Completada">Completada</option>
                          <option value="Bloqueada">Bloqueada</option>
                          <option value="Cancelada">Cancelada</option>
                        </select>
                      </div>

                      <div className="flex flex-col gap-1">
                        <label className="font-semibold text-slate-500 dark:text-slate-400">Prioridad</label>
                        <select 
                          value={meta.priority}
                          onChange={(e) => updateTaskMetaField(activeTask.assembly, "priority", e.target.value, `Prioridad cambiada a ${e.target.value}`)}
                          className="p-1.5 border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 rounded font-semibold"
                        >
                          <option value="Baja">Baja</option>
                          <option value="Media">Media</option>
                          <option value="Alta">Alta</option>
                          <option value="Crítica">Crítica</option>
                        </select>
                      </div>
                    </div>

                    {/* Blocked checkbox and reason */}
                    <div className="flex flex-col gap-2 p-3 bg-slate-50 dark:bg-slate-800/40 rounded border border-slate-200 dark:border-slate-800">
                      <label className="flex items-center gap-2 font-semibold text-slate-700 dark:text-slate-300">
                        <input 
                          type="checkbox" 
                          checked={meta.isBlocked}
                          onChange={(e) => updateTaskMetaField(activeTask.assembly, "isBlocked", e.target.checked, e.target.checked ? "Tarea marcada como BLOQUEADA." : "Bloqueo removido.")}
                          className="rounded border-slate-300 text-red-600 focus:ring-red-500 h-4 w-4"
                        />
                        ¿La tarea está Bloqueada?
                      </label>
                      {meta.isBlocked && (
                        <div className="flex flex-col gap-1 mt-1">
                          <label className="font-semibold text-red-600 dark:text-red-400">Motivo del bloqueo</label>
                          <input 
                            type="text" 
                            value={meta.blockedReason}
                            onChange={(e) => updateTaskMetaField(activeTask.assembly, "blockedReason", e.target.value, "Motivo de bloqueo actualizado.")}
                            placeholder="ej. Falta de materiales, Esperando certificación..."
                            className="p-1.5 border border-red-300 bg-red-50 dark:border-red-900/30 dark:bg-red-950/20 text-slate-800 dark:text-slate-200 rounded text-xs"
                          />
                        </div>
                      )}
                    </div>

                    {/* Predecessors and Successors (WBS ID display) */}
                    <div className="grid grid-cols-2 gap-3 p-2.5 bg-slate-100/50 dark:bg-slate-800/10 border border-slate-200 dark:border-slate-800 rounded">
                      <div>
                        <span className="font-semibold text-slate-500 dark:text-slate-400">Predecesoras (IDs):</span>
                        <div className="mt-1 font-mono text-slate-700 dark:text-slate-300 font-semibold">{predecessorsList.length > 0 ? predecessorsList.join(", ") : "-"}</div>
                      </div>
                      <div>
                        <span className="font-semibold text-slate-500 dark:text-slate-400">Sucesoras (IDs):</span>
                        <div className="mt-1 font-mono text-slate-700 dark:text-slate-300 font-semibold">{successorsList.length > 0 ? successorsList.join(", ") : "-"}</div>
                      </div>
                    </div>
                  </>
                )}

                {activeModalTab === "responsibles" && (
                  <div className="space-y-3">
                    <label className="font-semibold text-slate-500 dark:text-slate-400 text-sm block">Responsables Asignados al Equipo</label>
                    <div className="p-3 bg-slate-50 dark:bg-slate-800/20 border border-slate-200 dark:border-slate-800 rounded space-y-2">
                      {teamNames.map(name => {
                        const checked = meta.assignees.includes(name);
                        return (
                          <label key={name} className="flex items-center gap-2 text-slate-700 dark:text-slate-300 hover:text-slate-900 cursor-pointer py-0.5">
                            <input 
                              type="checkbox" 
                              checked={checked}
                              onChange={(e) => {
                                const list = e.target.checked 
                                  ? [...meta.assignees, name]
                                  : meta.assignees.filter(n => n !== name);
                                updateTaskMetaField(activeTask.assembly, "assignees", list, e.target.checked ? `Asignado a ${name}` : `Removido responsable ${name}`);
                              }}
                              className="rounded border-slate-300 text-brand-600 focus:ring-brand-500 h-4 w-4"
                            />
                            <span className="text-xs font-medium">{name}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                )}

                {activeModalTab === "history" && (
                  <div className="space-y-3">
                    <label className="font-semibold text-slate-500 dark:text-slate-400 text-sm block">Historial de Cambios</label>
                    <div className="space-y-2 divide-y divide-slate-100 dark:divide-slate-800/50 max-h-[45vh] overflow-y-auto pr-1">
                      {(meta.history || []).map((h, i) => (
                        <div key={i} className="flex gap-3 text-xs pt-2 font-mono">
                          <span className="shrink-0 text-slate-400 dark:text-slate-500 font-bold">{h.date}</span>
                          <span className="text-slate-700 dark:text-slate-300">{h.change}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

              </div>

              {/* Footer Actions */}
              <div className="border-t border-slate-100 dark:border-slate-800 pt-4 flex gap-2">
                {activeTask.isManual && (
                  <button 
                    onClick={() => handleDeleteTask(activeTask.assembly)}
                    className="border border-red-200 text-red-600 hover:bg-red-50 hover:border-red-300 rounded px-3 py-2 text-xs font-semibold flex items-center gap-1.5 transition-colors"
                  >
                    <Trash2 className="h-4 w-4" /> Eliminar Tarea
                  </button>
                )}
                <button 
                  onClick={() => setIsDrawerOpen(false)}
                  className="ml-auto bg-slate-900 hover:bg-slate-800 dark:bg-slate-800 dark:hover:bg-slate-700 text-white rounded px-4 py-2 text-xs font-semibold transition-colors"
                >
                  Cerrar Detalle
                </button>
              </div>

            </div>
          </div>
        );
      })()}

      {/* Task Creation Modal */}
      {isAddModalOpen && (
        <div className="fixed inset-0 z-50 overflow-hidden flex items-center justify-center">
          <div className="absolute inset-0 bg-slate-900/60 backdrop-blur-sm" onClick={() => setIsAddModalOpen(false)} />
          <div className="relative bg-white dark:bg-slate-900 shadow-2xl rounded-xl border border-slate-200 dark:border-slate-800 p-6 max-w-lg w-full animate-scale-up text-xs space-y-4 max-h-[90vh] overflow-y-auto">
            
            <div className="flex justify-between items-center border-b border-slate-100 dark:border-slate-800 pb-3 mb-1">
              <h3 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
                <Plus className="h-5 w-5 text-brand-600" /> Crear Nueva Tarea
              </h3>
              <button onClick={() => setIsAddModalOpen(false)} className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800">
                <X className="h-4 w-4 text-slate-400" />
              </button>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="font-semibold text-slate-600 dark:text-slate-400">Nombre de la Tarea</label>
              <input 
                type="text" 
                value={newAssembly}
                onChange={(e) => setNewAssembly(e.target.value)}
                placeholder="ej. Nivelación de Terreno, Trámites Municipales..."
                className="p-2 border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 rounded font-semibold text-xs"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="font-semibold text-slate-600 dark:text-slate-400">Descripción / Notas</label>
              <textarea 
                value={newDescription}
                onChange={(e) => setNewDescription(e.target.value)}
                placeholder="ej. Alcance de los trabajos, materiales específicos, etc..."
                className="p-2 border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 rounded text-xs h-16 resize-none"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Etapa de la Obra</label>
                <select 
                  value={newStage} 
                  onChange={(e) => setNewStage(e.target.value)}
                  className="p-2 border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 rounded font-semibold text-xs"
                >
                  <option value="Fundación">Fundación</option>
                  <option value="Estructura">Estructura</option>
                  <option value="Mampostería">Mampostería</option>
                  <option value="Instalaciones">Instalaciones</option>
                  <option value="Terminaciones">Terminaciones</option>
                </select>
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Duración (Días)</label>
                <input 
                  type="number" 
                  min={1}
                  value={newDuration}
                  onChange={(e) => setNewDuration(Math.max(1, Number(e.target.value)))}
                  className="p-2 border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 rounded font-mono text-xs"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Fecha de Inicio</label>
                <input 
                  type="date" 
                  value={newStartDate}
                  disabled={!!newPredecessor}
                  onChange={(e) => setNewStartDate(e.target.value)}
                  className="p-2 border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 rounded font-mono text-xs disabled:opacity-50"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Predecesora (Dependencia)</label>
                <select 
                  value={newPredecessor} 
                  onChange={(e) => {
                    const predName = e.target.value;
                    setNewPredecessor(predName);
                    if (predName) {
                      const predTask = allTasks.find(t => t.assembly === predName);
                      if (predTask) {
                        setNewStartDate(predTask.end_date);
                      }
                    }
                  }}
                  className="p-2 border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 rounded font-semibold text-xs"
                >
                  <option value="">Ninguna</option>
                  {allTasks.map(t => (
                    <option key={t.assembly} value={t.assembly}>{t.assembly} ({t.stage})</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Estado Inicial</label>
                <select 
                  value={newStatus} 
                  onChange={(e) => setNewStatus(e.target.value as any)}
                  className="p-2 border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 rounded font-semibold text-xs"
                >
                  <option value="Pendiente">Pendiente</option>
                  <option value="En progreso">En progreso</option>
                  <option value="En revisión">En revisión</option>
                  <option value="Completada">Completada</option>
                  <option value="Bloqueada">Bloqueada</option>
                  <option value="Cancelada">Cancelada</option>
                </select>
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Prioridad</label>
                <select 
                  value={newPriority} 
                  onChange={(e) => setNewPriority(e.target.value as any)}
                  className="p-2 border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 rounded font-semibold text-xs"
                >
                  <option value="Baja">Baja</option>
                  <option value="Media">Media</option>
                  <option value="Alta">Alta</option>
                  <option value="Crítica">Crítica</option>
                </select>
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="font-semibold text-slate-600 dark:text-slate-400">Asignar Responsables</label>
              <div className="max-h-24 overflow-y-auto p-2 bg-slate-50 dark:bg-slate-800/30 border border-slate-200 dark:border-slate-800 rounded space-y-1">
                {teamNames.map(name => {
                  const checked = newAssignees.includes(name);
                  return (
                    <label key={name} className="flex items-center gap-2 text-slate-700 dark:text-slate-300 hover:text-slate-900 cursor-pointer">
                      <input 
                        type="checkbox" 
                        checked={checked}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setNewAssignees([...newAssignees, name]);
                          } else {
                            setNewAssignees(newAssignees.filter(n => n !== name));
                          }
                        }}
                        className="rounded border-slate-300 text-brand-600 focus:ring-brand-500 h-3.5 w-3.5"
                      />
                      <span>{name}</span>
                    </label>
                  );
                })}
              </div>
            </div>

            <div className="flex flex-col gap-2 p-3 bg-slate-50 dark:bg-slate-800/40 rounded border border-slate-200 dark:border-slate-800">
              <label className="flex items-center gap-2 font-semibold text-slate-700 dark:text-slate-300">
                <input 
                  type="checkbox" 
                  checked={newIsBlocked}
                  onChange={(e) => setNewIsBlocked(e.target.checked)}
                  className="rounded border-slate-300 text-red-600 focus:ring-red-500 h-4 w-4"
                />
                ¿Comienza Bloqueada?
              </label>
              {newIsBlocked && (
                <div className="flex flex-col gap-1 mt-1">
                  <label className="font-semibold text-red-600 dark:text-red-400">Motivo del bloqueo</label>
                  <input 
                    type="text" 
                    value={newBlockedReason}
                    onChange={(e) => setNewBlockedReason(e.target.value)}
                    placeholder="ej. Falta de materiales, Esperando aprobación..."
                    className="p-1.5 border border-red-300 bg-red-50 dark:border-red-900/30 dark:bg-red-950/20 text-slate-800 dark:text-slate-200 rounded text-xs"
                  />
                </div>
              )}
            </div>

            <div className="pt-2 flex justify-end gap-2">
              <button 
                onClick={() => setIsAddModalOpen(false)}
                className="px-4 py-2 border border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 rounded font-semibold transition-colors"
              >
                Cancelar
              </button>
              <button 
                onClick={handleAddTask}
                disabled={!newAssembly.trim()}
                className="px-4 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white rounded font-semibold transition-colors"
              >
                Crear Tarea
              </button>
            </div>

          </div>
        </div>
      )}

    </main>
  );
}

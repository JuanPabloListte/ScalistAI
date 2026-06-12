"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { api, type PageClassification, type PageRole, type Plan, type Project } from "@/lib/api";

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
    description: "Plano para ambientes (ej: planta arquitectónica con nombres)",
    color: "sky",
  },
  {
    value: "beams",
    label: "Vigas",
    description: "Plano para vigas (ej: plano de estructuras o encofrado)",
    color: "purple",
  },
  {
    value: "roofs",
    label: "Techos / Losas",
    description: "Plano para techos, losas y cubiertas (ej: plano de cubiertas)",
    color: "teal",
  },
  {
    value: "columns",
    label: "Columnas",
    description: "Plano para columnas y pilares (ej: replanteo de estructuras)",
    color: "pink",
  },
  {
    value: "riostras",
    label: "Riostras",
    description: "Plano para vigas riostras y encadenados (ej: replanteo de fundaciones)",
    color: "orange",
  },
  {
    value: "cloacas",
    label: "Cloacas",
    description: "Plano para instalación sanitaria (ej: desagües cloacales)",
    color: "green",
  },
  {
    value: "electricidad",
    label: "Electricidad",
    description: "Plano para instalación eléctrica (ej: iluminación y tomas)",
    color: "yellow",
  },
  {
    value: "cortes",
    label: "Cortes",
    description: "Corte / elevación / fachada — solo referencia, no genera elementos",
    color: "slate",
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
  purple: {
    active: "bg-purple-600 text-white border-purple-600 dark:bg-purple-500 dark:border-purple-500",
    idle: "bg-white text-purple-700 border-purple-300 hover:bg-purple-50 dark:bg-slate-800 dark:text-purple-400 dark:border-purple-700 dark:hover:bg-purple-950/50",
    ring: "ring-purple-500",
  },
  teal: {
    active: "bg-teal-600 text-white border-teal-600 dark:bg-teal-500 dark:border-teal-500",
    idle: "bg-white text-teal-700 border-teal-300 hover:bg-teal-50 dark:bg-slate-800 dark:text-teal-400 dark:border-teal-700 dark:hover:bg-teal-950/50",
    ring: "ring-teal-500",
  },
  pink: {
    active: "bg-pink-600 text-white border-pink-600 dark:bg-pink-500 dark:border-pink-500",
    idle: "bg-white text-pink-700 border-pink-300 hover:bg-pink-50 dark:bg-slate-800 dark:text-pink-400 dark:border-pink-700 dark:hover:bg-pink-950/50",
    ring: "ring-pink-500",
  },
  orange: {
    active: "bg-orange-600 text-white border-orange-600 dark:bg-orange-500 dark:border-orange-500",
    idle: "bg-white text-orange-700 border-orange-300 hover:bg-orange-50 dark:bg-slate-800 dark:text-orange-400 dark:border-orange-700 dark:hover:bg-orange-950/50",
    ring: "ring-orange-500",
  },
  green: {
    active: "bg-green-600 text-white border-green-600 dark:bg-green-500 dark:border-green-500",
    idle: "bg-white text-green-700 border-green-300 hover:bg-green-50 dark:bg-slate-800 dark:text-green-400 dark:border-green-700 dark:hover:bg-green-950/50",
    ring: "ring-green-500",
  },
  yellow: {
    active: "bg-yellow-600 text-white border-yellow-600 dark:bg-yellow-500 dark:border-yellow-500",
    idle: "bg-white text-yellow-700 border-yellow-300 hover:bg-yellow-50 dark:bg-slate-800 dark:text-yellow-400 dark:border-yellow-700 dark:hover:bg-yellow-950/50",
    ring: "ring-yellow-500",
  },
  slate: {
    active: "bg-slate-600 text-white border-slate-600 dark:bg-slate-500 dark:border-slate-500",
    idle: "bg-white text-slate-700 border-slate-300 hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700 dark:hover:bg-slate-950/50",
    ring: "ring-slate-500",
  },
};

// Opciones de mapeo capa CAD → tipo de elemento (valores que espera el backend).
const DXF_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "wall", label: "Muros" },
  { value: "opening", label: "Aberturas" },
  { value: "room", label: "Recintos" },
  { value: "beam", label: "Vigas" },
  { value: "roof", label: "Techos / Losas" },
  { value: "column", label: "Columnas" },
  { value: "riostra", label: "Riostras" },
  { value: "cloaca", label: "Cloacas" },
  { value: "electricidad", label: "Electricidad" },
  { value: "escalera", label: "Escalera" },
];
const DXF_ELEMENT_VALUES = new Set(DXF_TYPE_OPTIONS.map((o) => o.value));
// La capa se ve de fondo pero no genera elementos.
const DXF_CONTEXT = "context";
// Import de elementos desde capas CAD: deshabilitado. Una lámina trae la misma
// puerta dibujada en planta, cortes y fachadas → elementos duplicados y mal
// ubicados. El CAD entra como fondo visual (recortes = páginas, escala del
// archivo) y los elementos se generan con IA o dibujo manual, igual que un PDF.
const DXF_LAYER_MAPPING_ENABLED = false;

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
  const [classifications, setClassifications] = useState<PageClassification[]>([]);
  const [suggestionsApplied, setSuggestionsApplied] = useState(false);

  const isDxf = plan?.original_filename?.toLowerCase().endsWith(".dxf") || plan?.original_filename?.toLowerCase().endsWith(".dwg");
  const [dxfLayers, setDxfLayers] = useState<import("@/lib/api").DxfLayer[]>([]);
  const [dxfMapping, setDxfMapping] = useState<Record<string, string | null>>({});
  const [dxfInfo, setDxfInfo] = useState<import("@/lib/api").DxfInfo | null>(null);
  const [dxfUnit, setDxfUnit] = useState<"mm" | "cm" | "m">("m");
  const [layerPreviews, setLayerPreviews] = useState<Record<string, string>>({});
  const [zoomedLayer, setZoomedLayer] = useState<string | null>(null);

  // Recortes de vistas: una lámina CAD trae plantas, cortes y planillas
  // juntas; el usuario dibuja un rectángulo por cada vista a computar y cada
  // recorte se convierte en una página del plano.
  const [overviewUrl, setOverviewUrl] = useState<string | null>(null);
  const [overviewNat, setOverviewNat] = useState<{ w: number; h: number } | null>(null);
  const [dxfRegions, setDxfRegions] = useState<number[][]>([]); // [x1,y1,x2,y2] en unidades de dibujo
  // Tipo de cada recorte (paralelo a dxfRegions): "planta" genera elementos,
  // "corte" es solo referencia visual de alturas (fachadas/elevaciones).
  const [dxfRegionTypes, setDxfRegionTypes] = useState<import("@/lib/api").DxfRegionType[]>([]);
  const [regionDraft, setRegionDraft] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null);
  const [ovZoom, setOvZoom] = useState(1); // zoom del overview para reconocer las vistas
  const [ovMode, setOvMode] = useState<"crop" | "pan">("crop"); // arrastre: recortar o mover
  const overviewRef = useRef<HTMLDivElement>(null);
  const ovScrollRef = useRef<HTMLDivElement>(null);
  const draftStart = useRef<{ x: number; y: number } | null>(null);
  const panStart = useRef<{ mx: number; my: number; sl: number; st: number } | null>(null);
  // Padding fijo que get_dxf_overview deja alrededor del contenido (px de imagen).
  const OVERVIEW_PAD = 10;

  const unitFactor = dxfUnit === "mm" ? 0.001 : dxfUnit === "cm" ? 0.01 : 1;

  useEffect(() => {
    if (!plan || !isDxf) return;
    let url: string | null = null;
    let cancelled = false;
    api
      .fetchDxfOverview(plan.id)
      .then((blob) => {
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setOverviewUrl(url);
      })
      .catch(() => {
        /* sin overview el usuario igual puede mapear capas (recorte = todo) */
      });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [plan, isDxf]);

  // Ctrl+rueda = zoom del overview centrado en el cursor (como en CAD).
  useEffect(() => {
    const el = ovScrollRef.current;
    if (!el || !overviewUrl) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left + el.scrollLeft;
      const my = e.clientY - rect.top + el.scrollTop;
      setOvZoom((prev) => {
        const next = Math.min(8, Math.max(1, prev * (e.deltaY < 0 ? 1.25 : 0.8)));
        if (next === prev) return prev;
        const r = next / prev;
        requestAnimationFrame(() => {
          el.scrollLeft = mx * r - (e.clientX - rect.left);
          el.scrollTop = my * r - (e.clientY - rect.top);
        });
        return next;
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [overviewUrl]);

  // Fracción [0..1] del cursor dentro de la imagen del overview.
  function overviewFrac(e: React.MouseEvent): { x: number; y: number } {
    const rect = overviewRef.current!.getBoundingClientRect();
    return {
      x: Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1),
      y: Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1),
    };
  }

  // Fracción de imagen (incluye padding) → unidades de dibujo (y crece hacia arriba).
  function fracToUnits(fx: number, fy: number): [number, number] | null {
    if (!dxfInfo || !overviewNat) return null;
    const [gx1, gy1, gx2, gy2] = dxfInfo.overview.bounds;
    const cx = Math.min(Math.max((fx * overviewNat.w - OVERVIEW_PAD) / (overviewNat.w - 2 * OVERVIEW_PAD), 0), 1);
    const cy = Math.min(Math.max((fy * overviewNat.h - OVERVIEW_PAD) / (overviewNat.h - 2 * OVERVIEW_PAD), 0), 1);
    return [gx1 + cx * (gx2 - gx1), gy2 - cy * (gy2 - gy1)];
  }

  // Región en unidades → estilo CSS (porcentajes sobre la imagen completa).
  function regionStyle(r: number[]): React.CSSProperties {
    if (!dxfInfo || !overviewNat) return { display: "none" };
    const [gx1, gy1, gx2, gy2] = dxfInfo.overview.bounds;
    const W = Math.max(gx2 - gx1, 1e-9);
    const H = Math.max(gy2 - gy1, 1e-9);
    const padX = OVERVIEW_PAD / overviewNat.w;
    const padY = OVERVIEW_PAD / overviewNat.h;
    const sx = (f: number) => (padX + f * (1 - 2 * padX)) * 100;
    const sy = (f: number) => (padY + f * (1 - 2 * padY)) * 100;
    const left = sx((r[0] - gx1) / W);
    const right = sx((r[2] - gx1) / W);
    const top = sy((gy2 - r[3]) / H);
    const bottom = sy((gy2 - r[1]) / H);
    return {
      left: `${left}%`,
      top: `${top}%`,
      width: `${right - left}%`,
      height: `${bottom - top}%`,
    };
  }

  function handleOverviewMouseDown(e: React.MouseEvent) {
    if (!overviewUrl || !overviewNat) return;
    e.preventDefault();
    const el = ovScrollRef.current;
    // Botón del medio (como en CAD) o modo "mover": panear, no recortar.
    if ((ovMode === "pan" || e.button === 1) && el) {
      panStart.current = { mx: e.clientX, my: e.clientY, sl: el.scrollLeft, st: el.scrollTop };
      return;
    }
    if (e.button !== 0) return;
    const p = overviewFrac(e);
    draftStart.current = p;
    setRegionDraft({ x1: p.x, y1: p.y, x2: p.x, y2: p.y });
  }

  function handleOverviewMouseMove(e: React.MouseEvent) {
    if (panStart.current && ovScrollRef.current) {
      const el = ovScrollRef.current;
      el.scrollLeft = panStart.current.sl - (e.clientX - panStart.current.mx);
      el.scrollTop = panStart.current.st - (e.clientY - panStart.current.my);
      return;
    }
    if (!draftStart.current) return;
    const p = overviewFrac(e);
    setRegionDraft({ x1: draftStart.current.x, y1: draftStart.current.y, x2: p.x, y2: p.y });
  }

  function handleOverviewMouseUp() {
    panStart.current = null;
    const draft = regionDraft;
    draftStart.current = null;
    setRegionDraft(null);
    if (!draft) return;
    if (Math.abs(draft.x2 - draft.x1) < 0.02 || Math.abs(draft.y2 - draft.y1) < 0.02) return;
    const a = fracToUnits(Math.min(draft.x1, draft.x2), Math.min(draft.y1, draft.y2)); // arriba-izq
    const b = fracToUnits(Math.max(draft.x1, draft.x2), Math.max(draft.y1, draft.y2)); // abajo-der
    if (!a || !b) return;
    setDxfRegions((prev) => [...prev, [a[0], b[1], b[0], a[1]]]);
    setDxfRegionTypes((prev) => [...prev, "planta"]);
  }

  useEffect(() => {
    if (plan && isDxf) {
      api.getDxfInfo(plan.id).then((info) => {
         setDxfInfo(info);
         setDxfLayers(info.layers);
         setDxfUnit(info.suggested_unit);
         if (info.overview?.regions?.length) {
           setDxfRegions(info.overview.regions);
           const types = info.overview.region_types ?? [];
           setDxfRegionTypes(
             info.overview.regions.map((_, i) => types[i] ?? "planta"),
           );
         }
         const initialMapping: Record<string, string | null> = {};
         info.layers.forEach(l => {
           if (DXF_LAYER_MAPPING_ENABLED) {
             // Si no hay tipo sugerido, la ocultamos por defecto para mantener
             // el plano limpio. El usuario puede habilitarlas si las necesita.
             initialMapping[l.name] = l.suggested_type || null;
           } else {
             // Modo solo-visual: todas las capas se ven de fondo, ninguna
             // genera elementos (la visibilidad CAD off/frozen la respeta el back).
             initialMapping[l.name] = DXF_CONTEXT;
           }
         });
         setDxfMapping(initialMapping);
      }).catch((err) => {
        setError(
          err instanceof Error
            ? `No se pudieron cargar las capas del CAD: ${err.message}`
            : "No se pudieron cargar las capas del CAD",
        );
      });
    }
  }, [plan, isDxf]);

  // Vistas previas por capa (la capa resaltada sobre el plano en gris).
  // Solo si el mapeo de capas está activo: cada preview es un render del server.
  useEffect(() => {
    if (!DXF_LAYER_MAPPING_ENABLED) return;
    if (!plan || !isDxf || dxfLayers.length === 0) return;
    let cancelled = false;
    const urls: string[] = [];

    (async () => {
      for (const layer of dxfLayers) {
        if (cancelled) break;
        try {
          const blob = await api.fetchDxfLayerPreview(plan.id, layer.name);
          if (cancelled) break;
          const url = URL.createObjectURL(blob);
          urls.push(url);
          setLayerPreviews((prev) => ({ ...prev, [layer.name]: url }));
        } catch {
          // si una capa falla seguimos con las demás
        }
      }
    })();

    return () => {
      cancelled = true;
      urls.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [plan, isDxf, dxfLayers]);

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

  // Auto-clasificación: cargar sugerencias de roles y pre-llenar si no hay roles guardados
  useEffect(() => {
    if (!plan || isDxf || suggestionsApplied) return;
    const hasExistingRoles = plan.page_roles && Object.keys(plan.page_roles).length > 0;
    if (hasExistingRoles) {
      setSuggestionsApplied(true);
      return;
    }
    let cancelled = false;
    api
      .suggestRoles(plan.id)
      .then((cls) => {
        if (cancelled) return;
        setClassifications(cls);
        const suggested: Record<string, PageRole[]> = {};
        for (const c of cls) {
          if (c.suggested_roles.length > 0) {
            suggested[String(c.page)] = c.suggested_roles;
          }
        }
        if (Object.keys(suggested).length > 0) {
          setPageRoles(suggested);
        }
        setSuggestionsApplied(true);
      })
      .catch(() => {
        if (!cancelled) setSuggestionsApplied(true);
      });
    return () => { cancelled = true; };
  }, [plan, isDxf, suggestionsApplied]);

  // Cargar thumbnails de cada página (solo PDF; el flujo CAD muestra capas)
  useEffect(() => {
    if (!plan?.page_count || isDxf) return;
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
  }, [plan?.id, plan?.page_count, plan?.deleted_pages, isDxf]);

  useEffect(() => {
    if (zoomedLayer === null) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setZoomedLayer(null);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [zoomedLayer]);

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
      if (isDxf) {
        // La unidad PRIMERO: el apply re-encuadra y crea los elementos
        // leyendo este override; al revés, la escala elegida se ignora.
        await api.setDxfScale(plan.id, dxfUnit);
        await api.applyDxfLayers(
          plan.id,
          dxfMapping,
          dxfRegions.length > 0 ? dxfRegions : undefined,
          dxfRegions.length > 0 ? dxfRegionTypes : undefined,
        );
      } else {
        await api.setPageRoles(plan.id, pageRoles, skipAiDetection);
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
    } finally {
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
    let walls = 0, openings = 0, rooms = 0, beams = 0, roofs = 0, columns = 0;
    let riostras = 0, cloacas = 0, electricidad = 0, cortes = 0;
    for (const roles of Object.values(pageRoles)) {
      if (roles.includes("walls")) walls++;
      if (roles.includes("openings")) openings++;
      if (roles.includes("rooms")) rooms++;
      if (roles.includes("beams")) beams++;
      if (roles.includes("roofs")) roofs++;
      if (roles.includes("columns")) columns++;
      if (roles.includes("riostras")) riostras++;
      if (roles.includes("cloacas")) cloacas++;
      if (roles.includes("electricidad")) electricidad++;
      if (roles.includes("cortes")) cortes++;
    }
    return { walls, openings, rooms, beams, roofs, columns, riostras, cloacas, electricidad, cortes };
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

  const canContinue = isDxf
    ? dxfRegions.length > 0 &&
      (!DXF_LAYER_MAPPING_ENABLED ||
        Object.values(dxfMapping).some((val) => val !== null && DXF_ELEMENT_VALUES.has(val)))
    : Object.keys(pageRoles).length > 0 || Object.keys(plan?.page_roles ?? {}).length > 0;

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
        <h2 className="text-lg font-semibold">
          {isDxf
            ? DXF_LAYER_MAPPING_ENABLED
              ? "Mapear capas del CAD"
              : "Preparar el plano CAD"
            : "Asignar páginas a detectores"}
        </h2>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
          {isDxf
            ? DXF_LAYER_MAPPING_ENABLED
              ? "Asigná cada capa del archivo a un tipo de elemento. Los elementos se crean con la geometría exacta del CAD, sin IA. Las capas en \"Solo fondo\" se ven en el plano sin generar elementos; las ignoradas se ocultan."
              : "Confirmá la escala y recortá las plantas que quieras computar. Cada recorte se convierte en una página del plano, con la escala exacta del archivo. Después dibujás los elementos o usás la detección con IA, igual que con un PDF."
            : "Marcá qué páginas usar para cada tipo de detección. La IA evita procesar páginas que no corresponden y los resultados son mucho más precisos."}
        </p>
      </div>

      {/* Layout: sidebar izquierdo + grilla de páginas */}
      <div className="flex gap-5 items-start">

        {/* Sidebar: leyenda de roles (solo PDF; para CAD el select ya explica cada tipo) */}
        {!isDxf && (
        <div className="w-52 shrink-0">
          <div className="sticky top-4 flex flex-col gap-1.5">
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">
              Tipos de detección
            </p>
            {ROLE_DEFS.map((r) => {
              const styles = COLOR_STYLES[r.color];
              const borderColor = styles.active.split(" ")[0].replace("bg-", "border-");
              const dotColor = styles.active.split(" ")[0];
              return (
                <div
                  key={r.value}
                  className={`flex flex-col gap-0.5 rounded-lg border-y border-r border-l-4 bg-white px-3 py-2 dark:bg-slate-900 ${borderColor}`}
                >
                  <div className="flex items-center gap-1.5">
                    <div className={`h-2 w-2 shrink-0 rounded-full ${dotColor}`} />
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-100">
                      {r.label}
                    </span>
                  </div>
                  <p className="text-[10px] leading-snug text-slate-500 dark:text-slate-400 pl-3.5">
                    {r.description}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
        )}

        <div className="flex-1 min-w-0">
          {isDxf ? (
            <div className="flex flex-col gap-6">
              {/* Unit Confirmation UI */}
              {dxfInfo && (
                <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-4 shadow-sm dark:border-indigo-900/50 dark:bg-indigo-950/30">
                  <h3 className="mb-2 text-sm font-semibold text-indigo-900 dark:text-indigo-200">
                    Confirmar escala del plano
                  </h3>
                  <div className="flex flex-wrap items-center gap-4 text-sm text-indigo-800 dark:text-indigo-300">
                    <span>
                      Tu dibujo CAD mide <strong>{dxfInfo.width_units} &times; {dxfInfo.height_units}</strong> unidades. ¿En qué escala está dibujado?
                    </span>
                    <select
                      className="rounded border border-indigo-300 bg-white px-2 py-1 text-sm font-medium text-indigo-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-indigo-700 dark:bg-slate-900 dark:text-indigo-100"
                      value={dxfUnit}
                      onChange={(e) => setDxfUnit(e.target.value as any)}
                    >
                      <option value="mm">Milímetros</option>
                      <option value="cm">Centímetros</option>
                      <option value="m">Metros</option>
                    </select>
                    <span className="ml-2 font-mono text-xs opacity-75">
                      = {(dxfInfo.width_units * (dxfUnit === "mm" ? 0.001 : dxfUnit === "cm" ? 0.01 : 1)).toFixed(1)}m &times; {(dxfInfo.height_units * (dxfUnit === "mm" ? 0.001 : dxfUnit === "cm" ? 0.01 : 1)).toFixed(1)}m reales
                    </span>
                  </div>
                </div>
              )}

              {/* Recortes de vistas a computar */}
              <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900/40">
                <h3 className="mb-1 text-sm font-semibold text-slate-800 dark:text-slate-100">
                  Recortá las vistas a computar
                </h3>
                <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
                  Una lámina CAD suele traer plantas, cortes, fachadas y planillas juntas.
                  Dibujá un rectángulo sobre cada <strong>planta</strong> que quieras computar:
                  cada recorte será una página del plano, con su zoom y escala propios.
                  Si recortás un <strong>corte o fachada</strong> (sirven para ver alturas),
                  marcalo con el botón de la vista: se va a ver como página pero
                  no genera elementos — computarlo duplicaría muros.
                  Lo que quede afuera no genera elementos.
                </p>
                {/* Controles de zoom del overview */}
                <div className="mb-2 flex items-center gap-2">
                  <div className="flex overflow-hidden rounded border border-slate-300 dark:border-slate-600">
                    <button
                      type="button"
                      onClick={() => setOvMode("crop")}
                      className={`px-2.5 py-1 text-xs font-semibold transition ${
                        ovMode === "crop"
                          ? "bg-brand text-white"
                          : "bg-white text-slate-600 hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                      }`}
                      title="Arrastrá para dibujar un recorte"
                    >
                      Recortar
                    </button>
                    <button
                      type="button"
                      onClick={() => setOvMode("pan")}
                      className={`px-2.5 py-1 text-xs font-semibold transition ${
                        ovMode === "pan"
                          ? "bg-brand text-white"
                          : "bg-white text-slate-600 hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                      }`}
                      title="Arrastrá para moverte por la lámina (también: botón del medio del mouse)"
                    >
                      Mover
                    </button>
                  </div>
                  <div className="h-5 w-px bg-slate-300 dark:bg-slate-600" />
                  <button
                    type="button"
                    onClick={() => setOvZoom((z) => Math.max(1, z / 1.5))}
                    className="flex h-7 w-7 items-center justify-center rounded border border-slate-300 bg-white text-sm font-bold text-slate-600 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                    title="Alejar"
                  >
                    −
                  </button>
                  <span className="w-12 text-center text-xs font-mono text-slate-500 dark:text-slate-400">
                    {Math.round(ovZoom * 100)}%
                  </span>
                  <button
                    type="button"
                    onClick={() => setOvZoom((z) => Math.min(8, z * 1.5))}
                    className="flex h-7 w-7 items-center justify-center rounded border border-slate-300 bg-white text-sm font-bold text-slate-600 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                    title="Acercar"
                  >
                    +
                  </button>
                  {ovZoom > 1 && (
                    <button
                      type="button"
                      onClick={() => setOvZoom(1)}
                      className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                    >
                      Ajustar
                    </button>
                  )}
                  <span className="ml-auto text-[11px] text-slate-400 dark:text-slate-500">
                    Ctrl + rueda = zoom · botón del medio = mover
                  </span>
                </div>
                <div
                  ref={ovScrollRef}
                  className="max-h-[70vh] overflow-auto rounded border border-slate-300 bg-white dark:border-slate-600"
                >
                <div
                  ref={overviewRef}
                  className={`relative select-none ${ovMode === "pan" ? "cursor-grab active:cursor-grabbing" : "cursor-crosshair"}`}
                  style={{ width: `${ovZoom * 100}%` }}
                  onMouseDown={handleOverviewMouseDown}
                  onMouseMove={handleOverviewMouseMove}
                  onMouseUp={handleOverviewMouseUp}
                  onMouseLeave={handleOverviewMouseUp}
                >
                  {overviewUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={overviewUrl}
                      alt="Lámina completa del CAD"
                      className="block w-full"
                      draggable={false}
                      onLoad={(e) =>
                        setOverviewNat({
                          w: e.currentTarget.naturalWidth,
                          h: e.currentTarget.naturalHeight,
                        })
                      }
                    />
                  ) : (
                    <div className="flex h-48 items-center justify-center text-xs text-slate-400">
                      Generando vista de la lámina…
                    </div>
                  )}
                  {dxfRegions.map((r, i) => {
                    const isCorte = dxfRegionTypes[i] === "corte";
                    return (
                    <div
                      key={i}
                      className={`absolute border-2 ${isCorte ? "border-slate-500 bg-slate-500/10" : "border-brand bg-sky-500/10"}`}
                      style={regionStyle(r)}
                    >
                      <span className={`absolute left-0 top-0 rounded-br px-1.5 py-0.5 text-[10px] font-bold text-white ${isCorte ? "bg-slate-600" : "bg-brand"}`}>
                        Vista {i + 1}{isCorte ? " · Corte" : ""}
                      </span>
                      <button
                        type="button"
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation();
                          setDxfRegionTypes((prev) =>
                            prev.map((t, j) => (j === i ? (t === "corte" ? "planta" : "corte") : t)),
                          );
                        }}
                        className={`absolute bottom-0 left-0 rounded-tr px-1.5 py-0.5 text-[10px] font-bold text-white ${
                          isCorte ? "bg-slate-600 hover:bg-slate-700" : "bg-emerald-600 hover:bg-emerald-700"
                        }`}
                        title={isCorte
                          ? "Vista de corte/fachada: se ve pero no genera elementos. Clic para marcarla como planta."
                          : "Vista de planta: genera elementos. Clic para marcarla como corte (solo referencia de alturas)."}
                      >
                        {isCorte ? "Corte (sin cómputo)" : "Planta"}
                      </button>
                      <button
                        type="button"
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation();
                          setDxfRegions((prev) => prev.filter((_, j) => j !== i));
                          setDxfRegionTypes((prev) => prev.filter((_, j) => j !== i));
                        }}
                        className="absolute right-0 top-0 flex h-5 w-5 items-center justify-center rounded-bl bg-red-600 text-xs font-bold text-white hover:bg-red-700"
                        title="Quitar recorte"
                      >
                        ×
                      </button>
                    </div>
                    );
                  })}
                  {regionDraft && (
                    <div
                      className="absolute border-2 border-dashed border-brand bg-sky-500/10 pointer-events-none"
                      style={{
                        left: `${Math.min(regionDraft.x1, regionDraft.x2) * 100}%`,
                        top: `${Math.min(regionDraft.y1, regionDraft.y2) * 100}%`,
                        width: `${Math.abs(regionDraft.x2 - regionDraft.x1) * 100}%`,
                        height: `${Math.abs(regionDraft.y2 - regionDraft.y1) * 100}%`,
                      }}
                    />
                  )}
                </div>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {dxfRegions.length === 0 ? (
                    <span className="text-xs font-semibold text-amber-600 dark:text-amber-400">
                      Dibujá al menos un recorte para continuar
                    </span>
                  ) : (
                    dxfRegions.map((r, i) => (
                      <span
                        key={i}
                        className={
                          dxfRegionTypes[i] === "corte"
                            ? "rounded-full border border-slate-300 bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300"
                            : "rounded-full border border-sky-300 bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-800 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-200"
                        }
                      >
                        Vista {i + 1}{dxfRegionTypes[i] === "corte" ? " (corte)" : ""}: {((r[2] - r[0]) * unitFactor).toFixed(1)} × {((r[3] - r[1]) * unitFactor).toFixed(1)} m
                      </span>
                    ))
                  )}
                  {dxfRegions.length > 0 && (
                    <button
                      type="button"
                      onClick={() => { setDxfRegions([]); setDxfRegionTypes([]); }}
                      className="text-[11px] text-slate-500 underline hover:text-slate-800 dark:hover:text-slate-200"
                    >
                      Limpiar recortes
                    </button>
                  )}
                </div>
              </div>

              {/* Grilla de capas (solo si el import de elementos por capa está activo) */}
              {DXF_LAYER_MAPPING_ENABLED && (
              <div className="flex flex-col rounded-lg border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-900/40">
              {/* Header */}
              <div className="grid grid-cols-[1fr_80px_220px] items-center gap-4 border-b border-slate-200 px-4 py-3 text-xs font-semibold text-slate-500 dark:border-slate-700 dark:text-slate-400">
                <div>Capa</div>
                <div className="text-right">Ents.</div>
                <div>Tipo de elemento</div>
              </div>
              
              {/* Body */}
              <div className="flex flex-col divide-y divide-slate-100 dark:divide-slate-800/60 max-h-[500px] overflow-y-auto custom-scrollbar">
                {dxfLayers.length === 0 && !error && (
                  <div className="p-8 text-center text-sm text-slate-500">
                    Leyendo capas del archivo CAD…
                  </div>
                )}
                {dxfLayers.map((layer) => {
                  const mapped = dxfMapping[layer.name];
                  return (
                    <div key={layer.name} className="grid grid-cols-[1fr_80px_220px] items-center gap-4 px-4 py-2.5 transition hover:bg-slate-50 dark:hover:bg-slate-800/40">
                      <div
                        className={`flex items-center gap-3 overflow-hidden ${layerPreviews[layer.name] ? "cursor-zoom-in" : ""}`}
                        onClick={() => layerPreviews[layer.name] && setZoomedLayer(layer.name)}
                        title={layerPreviews[layer.name] ? "Clic para ver la capa resaltada en el plano" : layer.name}
                      >
                        <div className="h-3.5 w-3.5 shrink-0 rounded-sm shadow-sm" style={{ backgroundColor: `rgb(${layer.color_rgb.join(',')})` }} />
                        <span className="truncate text-sm font-medium font-mono text-slate-700 hover:underline dark:text-slate-200">
                          {layer.name}
                        </span>
                        {layerPreviews[layer.name] && <span className="shrink-0 text-xs opacity-50">ver</span>}
                      </div>
                      <div className="text-right text-sm font-mono text-slate-500 dark:text-slate-500">
                        {layer.entity_count}
                      </div>
                      <div>
                        <select
                          className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm font-medium text-slate-700 shadow-sm transition hover:border-slate-400 focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-slate-500 dark:focus:border-sky-500 dark:focus:ring-sky-500"
                          value={mapped || ""}
                          onChange={(e) => setDxfMapping(prev => ({ ...prev, [layer.name]: e.target.value || null }))}
                        >
                          <option value="">Ignorar (ocultar)</option>
                          <option value={DXF_CONTEXT}>Solo fondo (sin elementos)</option>
                          {DXF_TYPE_OPTIONS.map((o) => (
                            <option key={o.value} value={o.value}>{o.label}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                  );
                })}
              </div>
              </div>
              )}
            </div>
          ) : (
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
                    Ampliar
                  </span>
                </div>
                <span className="absolute left-1.5 top-1.5 rounded bg-slate-900/80 px-1.5 py-0.5 text-xs font-semibold text-white">
                  p. {page}
                </span>
                {(() => {
                  const cls = classifications.find((c) => c.page === page);
                  if (!cls || cls.view_type === "otro") return null;
                  const labels: Record<string, { text: string; bg: string }> = {
                    planta: { text: "Planta", bg: "bg-emerald-600" },
                    corte: { text: "Corte/Elev.", bg: "bg-slate-600" },
                    planilla: { text: "Planilla", bg: "bg-amber-600" },
                    estructura: { text: "Estructura", bg: "bg-purple-600" },
                    instalacion: { text: "Instalación", bg: "bg-green-600" },
                    techos: { text: "Techos", bg: "bg-teal-600" },
                  };
                  const l = labels[cls.view_type];
                  if (!l) return null;
                  return (
                    <span className={`absolute right-1.5 top-1.5 rounded ${l.bg} px-1.5 py-0.5 text-[10px] font-semibold text-white`}>
                      {l.text}
                    </span>
                  );
                })()}
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
                      className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold transition ${
                        active
                          ? `${styles.active} shadow-md scale-105`
                          : styles.idle
                      }`}
                    >
                      {active && <span aria-hidden>✓</span>}
                      <span>{r.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
          )}
        </div>{/* end flex-1 pages column */}
      </div>{/* end flex sidebar+pages row */}

      {/* Resumen (CAD): capas que generan elementos */}
      {DXF_LAYER_MAPPING_ENABLED && isDxf && dxfLayers.length > 0 && (
        <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-300">
          <strong>
            {Object.values(dxfMapping).filter((v) => v !== null && DXF_ELEMENT_VALUES.has(v)).length}
          </strong>{" "}
          de {dxfLayers.length} capas generan elementos ·{" "}
          {Object.values(dxfMapping).filter((v) => v === DXF_CONTEXT).length} solo fondo ·{" "}
          {Object.values(dxfMapping).filter((v) => !v).length} ocultas
        </div>
      )}

      {/* Resumen (PDF) */}
      {!isDxf && (
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
          <span className="text-slate-400">·</span>
          <span>
            <strong>{summary.beams}</strong> p. para vigas
          </span>
          <span className="text-slate-400">·</span>
          <span>
            <strong>{summary.roofs}</strong> p. para techos
          </span>
          <span className="text-slate-400">·</span>
          <span>
            <strong>{summary.columns}</strong> p. para columnas
          </span>
          <span className="text-slate-400">·</span>
          <span>
            <strong>{summary.riostras}</strong> p. para riostras
          </span>
          <span className="text-slate-400">·</span>
          <span>
            <strong>{summary.cloacas}</strong> p. para cloacas
          </span>
          <span className="text-slate-400">·</span>
          <span>
            <strong>{summary.electricidad}</strong> p. para electricidad
          </span>
          {summary.cortes > 0 && (<>
          <span className="text-slate-400">·</span>
          <span>
            <strong>{summary.cortes}</strong> p. cortes/elev.
          </span>
          </>)}
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
      )}

      {/* Manual Configuration Toggle (solo PDF: el flujo CAD nunca usa IA) */}
      {!isDxf && (
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
      )}

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
              ? isDxf
                ? "Asigná al menos una capa a un tipo de elemento para continuar"
                : "Asigná al menos una página a un rol para continuar"
              : isDxf
                ? "Crear elementos desde las capas mapeadas"
                : isDirty
                  ? "Guardar y disparar detección IA"
                  : "Continuar al siguiente paso"
          }
        >
          {saving
            ? "Guardando..."
            : isDxf
              ? "Aplicar capas y continuar →"
              : isDirty
                ? "Guardar y continuar →"
                : "Continuar →"}
        </button>
      </div>

      {zoomedLayer !== null && layerPreviews[zoomedLayer] && (
        <div
          className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-slate-950/85 p-4 backdrop-blur-xs"
          onClick={() => setZoomedLayer(null)}
        >
          <div
            className="relative flex max-h-[90vh] max-w-[90vw] flex-col items-center gap-3 rounded-xl bg-slate-900 p-4 shadow-2xl border border-slate-700/50"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex w-full items-center justify-between gap-4">
              <span className="truncate text-sm font-semibold text-white" title={zoomedLayer}>
                Capa: {zoomedLayer}
              </span>
              <button
                onClick={() => setZoomedLayer(null)}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-950/70 text-lg font-bold text-white hover:bg-slate-800 transition"
                title="Cerrar"
              >
                ×
              </button>
            </div>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={layerPreviews[zoomedLayer]}
              alt={`Capa ${zoomedLayer} ampliada`}
              className="max-h-[72vh] max-w-[85vw] rounded bg-white object-contain"
            />
            <select
              className="w-full rounded border-slate-300 bg-slate-50 p-2 text-sm font-semibold dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              value={dxfMapping[zoomedLayer] || ""}
              onChange={(e) =>
                setDxfMapping((prev) => ({ ...prev, [zoomedLayer]: e.target.value || null }))
              }
            >
              <option value="">Ignorar (ocultar del plano)</option>
              <option value={DXF_CONTEXT}>Solo fondo (sin elementos)</option>
              {DXF_TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
        </div>
      )}

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
                className="max-h-[72vh] max-w-[85vw] object-contain rounded"
              />
            ) : (
              <div className="flex h-64 w-64 items-center justify-center text-sm text-slate-400">
                Cargando…
              </div>
            )}

            {/* Chips de rol — permite marcar mientras ves la página ampliada */}
            <div className="mt-3 flex flex-col items-center gap-2">
              <span className="text-xs uppercase tracking-wide text-slate-400">
                Asignar rol a esta página
              </span>
              <div className="flex flex-wrap items-center justify-center gap-2">
                {ROLE_DEFS.map((r) => {
                  const currentRoles = pageRoles[String(zoomedPage)] ?? [];
                  const active = currentRoles.includes(r.value);
                  const styles = COLOR_STYLES[r.color];
                  return (
                    <button
                      key={r.value}
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        togglePageRole(zoomedPage, r.value);
                      }}
                      className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-semibold transition ${
                        active
                          ? `${styles.active} shadow-lg scale-105`
                          : styles.idle
                      }`}
                    >
                      {active && <span aria-hidden>✓</span>}
                      <span>{r.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

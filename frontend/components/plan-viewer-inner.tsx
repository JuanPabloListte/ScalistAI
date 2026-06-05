"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";

const Plan3DViewer = dynamic(() => import("./plan-3d-viewer"), {
  ssr: false,
});

import {
  api,
  type DetectedElement,
  type ElementGeometry,
  type ElementType,
  type Assembly,
  type MaterialSummaryItem,
  type Plan,
} from "@/lib/api";

type Props = {
  planId: number;
  pageCount?: number | null;
  pageScales?: Record<string, number> | null;
  deletedPages?: number[] | null;
  scaleSource?: string | null;
  planDpi?: number | null;
  calRequest?: { page: number; ts: number } | null;
  allowedPages?: number[] | null;
  /** Tab activa del proyecto (walls/rooms/openings/beams/roofs/columns/all).
   *  Filtra el dibujo en el canvas y la lista de elementos del sidebar al
   *  tipo correspondiente, sin afectar los contadores globales (que siguen
   *  mostrando totales por tipo para contexto). */
  activeCategory?: string | null;
  onPlanUpdated?: (plan: Plan) => void;
  height?: number;
};

type Point = { x: number; y: number };
type Tool = "pan" | "wall" | "room" | "opening" | "beam" | "roof" | "column" | "riostra" | "cloaca" | "electricidad";

// Subtipos de abertura. El valor se persiste en `geometry.subtype`.
// `defaultW_m` / `defaultH_m` son los valores físicos típicos en obra; se
// usan al crear y como fallback en el cómputo si el usuario no editó el alto.
// Cuando una abertura cae sobre un muro:
//   - `subtractsPerimeter=true`  → resta `width` al largo del muro (zócalo)
//   - `subtractsPerimeter=false` → solo resta `width × height` al m² del muro
type OpeningSubtype = {
  value: "door" | "window" | "sliding-door";
  label: string;
  defaultW_m: number;
  defaultH_m: number;
  subtractsPerimeter: boolean;
};
const OPENING_SUBTYPES: OpeningSubtype[] = [
  { value: "door",         label: "Puerta",         defaultW_m: 0.9, defaultH_m: 2.1, subtractsPerimeter: true  },
  { value: "window",       label: "Ventana",        defaultW_m: 1.2, defaultH_m: 1.2, subtractsPerimeter: false },
  { value: "sliding-door", label: "Puerta ventana", defaultW_m: 1.8, defaultH_m: 2.1, subtractsPerimeter: true  },
];
const DEFAULT_OPENING_SUBTYPE: OpeningSubtype["value"] = "door";

const ZOOM_STEP = 1.1;
const MIN_SCALE = 0.02;
const MAX_SCALE = 8;
const FIT_MARGIN = 0.9;
const CLOSE_POLYGON_PX = 14; // distancia en pantalla para cerrar polígono
const MIN_SEGMENT_M = 0.05; // ignorar clics muy próximos

function distM(p1: Point, p2: Point, pxPerM: number): number {
  return Math.hypot(p2.x - p1.x, p2.y - p1.y) / pxPerM;
}

function polygonAreaM2(pts: Point[], pxPerM: number): number {
  if (pts.length < 3) return 0;
  let acc = 0;
  for (let i = 0; i < pts.length; i++) {
    const j = (i + 1) % pts.length;
    acc += pts[i].x * pts[j].y - pts[j].x * pts[i].y;
  }
  return Math.abs(acc / 2) / (pxPerM * pxPerM);
}

function polygonPerimeterM(pts: Point[], pxPerM: number): number {
  if (pts.length < 2) return 0;
  let perim = 0;
  for (let i = 0; i < pts.length; i++) {
    const j = (i + 1) % pts.length;
    perim += Math.hypot(pts[j].x - pts[i].x, pts[j].y - pts[i].y);
  }
  return perim / pxPerM;
}

function chunkPoints(flat: number[]): Point[] {
  const out: Point[] = [];
  for (let i = 0; i + 1 < flat.length; i += 2) {
    out.push({ x: flat[i], y: flat[i + 1] });
  }
  return out;
}

function calculatePolygonCentroid(pts: Point[]): Point {
  let A = 0;
  let cx = 0;
  let cy = 0;
  const n = pts.length;
  if (n < 3) return pts[0] || { x: 0, y: 0 };
  
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    const x0 = pts[i].x;
    const y0 = pts[i].y;
    const x1 = pts[j].x;
    const y1 = pts[j].y;
    const factor = (x0 * y1 - x1 * y0);
    A += factor;
    cx += (x0 + x1) * factor;
    cy += (y0 + y1) * factor;
  }
  
  A = A / 2;
  if (A === 0) return pts[0]; // fallback
  
  cx = cx / (6 * A);
  cy = cy / (6 * A);
  return { x: cx, y: cy };
}


// Largo geométrico (calculado desde la línea dibujada). Solo aplica a wall/opening.
function geometricLengthM(el: DetectedElement, pxPerM: number | null): number | null {
  if (!pxPerM) return null;
  if (el.type !== "wall" && el.type !== "opening") return null;
  const [x1, y1, x2, y2] = el.geometry.points;
  if ([x1, y1, x2, y2].some((v) => v == null)) return null;
  return Math.hypot(x2 - x1, y2 - y1) / pxPerM;
}

// Conjuntos aplicables a un tipo de elemento.
function applicableAssemblies(type: ElementType, all: Assembly[]): Assembly[] {
  return all.filter((a) => {
    const applies = a.applies_to;
    if (type === "wall") return applies === "wall";
    if (type === "room") return ["room_floor", "room_wall", "room_perimeter"].includes(applies);
    if (type === "opening") return ["opening", "opening_perimeter"].includes(applies);
    if (type === "beam") return applies === "beam";
    if (type === "roof") return applies === "roof";
    if (type === "column") return applies === "column";
    if (type === "riostra") return applies === "riostra" || applies === "beam"; // a riostra is like a foundation beam
    if (type === "cloaca") return applies === "cloaca";
    if (type === "electricidad") return applies === "electricidad";
    return false;
  });
}

export default function PlanViewerInner({
  planId,
  pageCount = 1,
  pageScales = null,
  deletedPages = null,
  scaleSource = null,
  planDpi: _planDpi = 150,
  calRequest = null,
  allowedPages = null,
  activeCategory = null,
  onPlanUpdated,
  height = 640,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const dragStart = useRef<{ x: number; y: number; px: number; py: number } | null>(null);
  const hasMovedDuringDrag = useRef(false);

  const [page, setPage] = useState(() => {
    if (allowedPages && allowedPages.length > 0) {
      const deleted = new Set(deletedPages ?? []);
      const active = allowedPages.filter((p) => !deleted.has(p));
      if (active.length > 0) return active[0];
    }
    if (deletedPages && deletedPages.length > 0) {
      const deleted = new Set(deletedPages);
      const total = Math.max(1, pageCount ?? 1);
      const active = Array.from({ length: total }, (_, i) => i + 1).filter((p) => !deleted.has(p));
      if (active.length > 0) return active[0];
    }
    return 1;
  });
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [dims, setDims] = useState({ w: 0, h: height });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rendered, setRendered] = useState<number | null>(null);
  const [statusTotal, setStatusTotal] = useState<number | null>(null);

  const [scale, setScale] = useState(1);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);

  // Herramienta activa
  const [tool, setTool] = useState<Tool>("pan");
  const [activePoints, setActivePoints] = useState<Point[]>([]);
  const [isFreehandDrawing, setIsFreehandDrawing] = useState(false);
  const [isFreehandMode, setIsFreehandMode] = useState(true);
  const [mousePos, setMousePos] = useState<Point | null>(null);
  const [drawError, setDrawError] = useState<string | null>(null);
  // Subtipo seleccionado para la próxima abertura que se dibuje. Persiste entre
  // dibujos de la sesión; el usuario lo cambia desde el dropdown que aparece
  // cuando `tool === "opening"`.
  const [openingSubtype, setOpeningSubtype] = useState<OpeningSubtype["value"]>(DEFAULT_OPENING_SUBTYPE);
  const [showOpeningMenu, setShowOpeningMenu] = useState(false);
  const [showElectricidadMenu, setShowElectricidadMenu] = useState(false);
  const [showDrawingTools, setShowDrawingTools] = useState(true);

  // Elementos persistidos
  const [elements, setElements] = useState<DetectedElement[]>([]);
  const [elementsLoading, setElementsLoading] = useState(false);
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const selectedElement = useMemo(() => {
    if (selectedIds.size !== 1) return null;
    const id = Array.from(selectedIds)[0];
    return elements.find((e) => e.id === id) || null;
  }, [selectedIds, elements]);

  const [hideAiElements, setHideAiElements] = useState(false);
  const visibleElements = useMemo(() => {
    if (hideAiElements) {
      return elements.filter((e) => e.source !== "ai");
    }
    return elements;
  }, [elements, hideAiElements]);

  // Elementos visibles SÓLO en la página actual (para el lienzo 2D y contadores)
  const pageVisibleElements = useMemo(() => {
    return visibleElements.filter((e) => e.page === page);
  }, [visibleElements, page]);

  // displayElements = pageVisibleElements filtrados por la tab activa del proyecto.
  // Si el usuario está parado en "Muros", solo se renderizan/listan walls aunque
  // la página también tenga rooms/openings/etc. Los contadores agregados siguen
  // usando `pageVisibleElements` para mostrar el panorama completo de la página.
  const displayElements = useMemo(() => {
    const tabToType: Record<string, ElementType> = {
      walls: "wall",
      rooms: "room",
      openings: "opening",
      beams: "beam",
      roofs: "roof",
      columns: "column",
      riostras: "riostra",
      cloacas: "cloaca",
      electricidad: "electricidad",
    };
    const target = activeCategory ? tabToType[activeCategory] : null;
    if (!target) return pageVisibleElements; // "all" o sin tab → no filtra
    return pageVisibleElements.filter((e) => e.type === target);
  }, [pageVisibleElements, activeCategory]);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<{ ids: number[]; label: string } | null>(null);
  const [scaleModalOpen, setScaleModalOpen] = useState(false);
  const [scaleFactor, setScaleFactor] = useState("1");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkAssignOpen, setBulkAssignOpen] = useState(false);
  const [bulkAssignMaterialId, setBulkAssignMaterialId] = useState<number | null>(null);

  // Catálogo de materiales y cómputo
  const [assembliesList, setAssembliesList] = useState<Assembly[]>([]);
  const [summary, setSummary] = useState<MaterialSummaryItem[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [exporting, setExporting] = useState(false);

  // Páginas eliminadas
  const [confirmDeletePage, setConfirmDeletePage] = useState<number | null>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [pageBusy, setPageBusy] = useState(false);

  const [show3D, setShow3D] = useState(false);

  // Estado local para arrastrar vertices
  const [draggingVertex, setDraggingVertex] = useState<{
    elementId: number;
    pointIndex: number;
  } | null>(null);

  // Candidatos de Detección IA
  const [wallCandidates, setWallCandidates] = useState<any[]>([]);
  const [roomCandidates, setRoomCandidates] = useState<any[]>([]);
  const [openingCandidates, setOpeningCandidates] = useState<any[]>([]);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<Set<string>>(new Set());

  // Carga de Detección IA
  const [detectingWalls, setDetectingWalls] = useState(false);
  const [detectingRooms, setDetectingRooms] = useState(false);
  const [detectingOpenings, setDetectingOpenings] = useState(false);
  const [detectionError, setDetectionError] = useState<string | null>(null);
  const [iaPanelOpen, setIaPanelOpen] = useState(true);

  // Calibración
  const [calibrating, setCalibrating] = useState(false);
  const [calPoints, setCalPoints] = useState<Point[]>([]);
  const [distanceModalOpen, setDistanceModalOpen] = useState(false);
  const [distanceInput, setDistanceInput] = useState("");
  const [savingScale, setSavingScale] = useState(false);
  const [calError, setCalError] = useState<string | null>(null);
  const [autoDetecting, setAutoDetecting] = useState(false);

  // Auto-detect
  const [detectedPreview, setDetectedPreview] = useState<Record<string, number> | null>(null);
  const [selectedPages, setSelectedPages] = useState<Record<string, boolean>>({});
  const [editedScales, setEditedScales] = useState<Record<string, string>>({});
  const [savingBulk, setSavingBulk] = useState(false);

  const [recommendedPages, setRecommendedPages] = useState<{
    page: number;
    score: number;
    recommended: boolean;
    reason: string;
    override?: "recommended" | "rejected" | null;
  }[]>([]);
  const [loadingRecommendations, setLoadingRecommendations] = useState(false);
  const [overridingPage, setOverridingPage] = useState(false);

  const currentRec = useMemo(
    () => recommendedPages.find((r) => r.page === page) ?? null,
    [recommendedPages, page],
  );

  const totalPages = Math.max(1, statusTotal ?? pageCount ?? 1);
  const currentPageScale = pageScales?.[String(page)] ?? null;
  const drawingDisabled = !currentPageScale;
  const activePages = useMemo(() => {
    if (allowedPages) {
      const deleted = new Set(deletedPages ?? []);
      return allowedPages.filter((p) => !deleted.has(p));
    }
    const deleted = new Set(deletedPages ?? []);
    return Array.from({ length: totalPages }, (_, i) => i + 1).filter((p) => !deleted.has(p));
  }, [totalPages, deletedPages, allowedPages]);

  // Si la página actual quedó eliminada, saltar a la primera activa
  useEffect(() => {
    if (activePages.length > 0 && !activePages.includes(page)) {
      setPage(activePages[0]);
    }
  }, [activePages, page]);

  // Reset al cambiar de plan
  useEffect(() => {
    if (allowedPages && allowedPages.length > 0) {
      const deleted = new Set(deletedPages ?? []);
      const active = allowedPages.filter((p) => !deleted.has(p));
      if (active.length > 0) {
        setPage(active[0]);
      } else {
        setPage(1);
      }
    } else {
      const deleted = new Set(deletedPages ?? []);
      const total = Math.max(1, pageCount ?? 1);
      const active = Array.from({ length: total }, (_, i) => i + 1).filter((p) => !deleted.has(p));
      setPage(active[0] ?? 1);
    }
    setRendered(null);
    setStatusTotal(null);
    setTool("pan");
    setActivePoints([]);
    setMousePos(null);
    setHoveredId(null);
    setElements([]);
    setWallCandidates([]);
    setRoomCandidates([]);
    setOpeningCandidates([]);
    setSelectedCandidateIds(new Set());
    setDetectionError(null);
  }, [planId]);

  // Reset estado de dibujo al cambiar página
  useEffect(() => {
    setActivePoints([]);
    setMousePos(null);
    setHoveredId(null);
    setSelectedIds(new Set());
    setEditingId(null);
    setWallCandidates([]);
    setRoomCandidates([]);
    setOpeningCandidates([]);
    setSelectedCandidateIds(new Set());
    setDetectionError(null);
  }, [page]);

  useEffect(() => {
    if (!calRequest) return;
    setPage(calRequest.page);
    setCalibrating(true);
    setCalPoints([]);
    setCalError(null);
    setTool("pan");
    setActivePoints([]);
  }, [calRequest?.ts, calRequest?.page]);

  useEffect(() => {
    api.startPrewarm(planId).catch(() => {});
  }, [planId]);

  useEffect(() => {
    setLoadingRecommendations(true);
    api.recommendPages(planId)
      .then((data) => {
        setRecommendedPages(data);
      })
      .catch(() => {})
      .finally(() => {
        setLoadingRecommendations(false);
      });
  }, [planId]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    async function tick() {
      try {
        const status = await api.getRenderStatus(planId);
        if (cancelled) return;
        setStatusTotal(status.total);
        setRendered(status.rendered);
        if (status.total === 0 || status.rendered < status.total) {
          timer = setTimeout(tick, 1500);
        }
      } catch {
        if (!cancelled) timer = setTimeout(tick, 3000);
      }
    }
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [planId]);

  async function runDetectWalls() {
    if (!currentPageScale) return;
    setDetectingWalls(true);
    setDetectionError(null);
    try {
      const res = await api.detectWalls(planId, page);
      setWallCandidates(res);
      setSelectedCandidateIds((prev) => {
        const next = new Set(prev);
        res.forEach((c) => next.add(c.id));
        return next;
      });
    } catch (err) {
      setDetectionError(err instanceof Error ? err.message : "Error al detectar muros");
    } finally {
      setDetectingWalls(false);
    }
  }

  async function runDetectRooms() {
    if (!currentPageScale) return;
    setDetectingRooms(true);
    setDetectionError(null);
    try {
      const res = await api.detectRooms(planId, page);
      setRoomCandidates(res);
      setSelectedCandidateIds((prev) => {
        const next = new Set(prev);
        res.forEach((c) => next.add(c.id));
        return next;
      });
    } catch (err) {
      setDetectionError(err instanceof Error ? err.message : "Error al detectar recintos");
    } finally {
      setDetectingRooms(false);
    }
  }

  async function runDetectOpenings() {
    if (!currentPageScale) return;
    setDetectingOpenings(true);
    setDetectionError(null);
    try {
      const res = await api.detectOpenings(planId, page);
      const cleaned = res.map((c, idx) => ({
        ...c,
        id: `opening_candidate_${idx + 1}`,
      }));
      setOpeningCandidates(cleaned);
      setSelectedCandidateIds((prev) => {
        const next = new Set(prev);
        cleaned.forEach((c) => next.add(c.id));
        return next;
      });
    } catch (err) {
      setDetectionError(err instanceof Error ? err.message : "Error al detectar aberturas");
    } finally {
      setDetectingOpenings(false);
    }
  }

  function toggleCandidateSelected(candidateId: string, multi: boolean = false) {
    setSelectedCandidateIds((prev) => {
      if (multi) {
        const next = new Set(prev);
        if (next.has(candidateId)) {
          next.delete(candidateId);
        } else {
          next.add(candidateId);
        }
        return next;
      } else {
        if (prev.has(candidateId) && prev.size === 1) return new Set();
        return new Set([candidateId]);
      }
    });
  }

  function discardCandidates(type?: "wall" | "room" | "opening") {
    if (!type || type === "wall") {
      setWallCandidates([]);
      setSelectedCandidateIds((prev) => {
        const next = new Set(prev);
        wallCandidates.forEach((c) => next.delete(c.id));
        return next;
      });
    }
    if (!type || type === "room") {
      setRoomCandidates([]);
      setSelectedCandidateIds((prev) => {
        const next = new Set(prev);
        roomCandidates.forEach((c) => next.delete(c.id));
        return next;
      });
    }
    if (!type || type === "opening") {
      setOpeningCandidates([]);
      setSelectedCandidateIds((prev) => {
        const next = new Set(prev);
        openingCandidates.forEach((c) => next.delete(c.id));
        return next;
      });
    }
  }

  async function confirmCandidateWalls() {
    const selectedWalls = wallCandidates.filter((c) => selectedCandidateIds.has(c.id));
    if (selectedWalls.length === 0) {
      discardCandidates("wall");
      return;
    }
    setBulkBusy(true);
    try {
      const created = await api.createElementsBulk(planId, selectedWalls);
      setElements((prev) => [...prev, ...created]);
      discardCandidates("wall");
    } catch (err) {
      setDetectionError(err instanceof Error ? err.message : "Error al guardar muros detectados");
    } finally {
      setBulkBusy(false);
    }
  }

  async function confirmCandidateRooms() {
    const selectedRooms = roomCandidates.filter((c) => selectedCandidateIds.has(c.id));
    if (selectedRooms.length === 0) {
      discardCandidates("room");
      return;
    }
    setBulkBusy(true);
    try {
      const created = await api.createElementsBulk(planId, selectedRooms);
      setElements((prev) => [...prev, ...created]);
      discardCandidates("room");
    } catch (err) {
      setDetectionError(err instanceof Error ? err.message : "Error al guardar recintos detectados");
    } finally {
      setBulkBusy(false);
    }
  }

  async function confirmCandidateOpenings() {
    const selectedOpenings = openingCandidates.filter((c) => selectedCandidateIds.has(c.id));
    if (selectedOpenings.length === 0) {
      discardCandidates("opening");
      return;
    }
    setBulkBusy(true);
    try {
      const payload = selectedOpenings.map((c) => ({
        page,
        cx: c.cx,
        cy: c.cy,
        default_width_m: c.default_width_m,
        label: c.label,
        subtype: c.subtype,
      }));
      const created = await api.createOpeningsBulk(planId, payload);
      setElements((prev) => [...prev, ...created]);
      discardCandidates("opening");
    } catch (err) {
      setDetectionError(err instanceof Error ? err.message : "Error al guardar aberturas detectadas");
    } finally {
      setBulkBusy(false);
    }
  }

  useEffect(() => {
    // Evita pedir el raster de una pagina marcada como eliminada — el backend
    // devuelve 410 y, ademas, no queremos disparar la regeneracion del PNG
    // cacheado para una pagina que el usuario ya descarto.
    if ((deletedPages ?? []).includes(page)) {
      setImgUrl(null);
      setLoading(false);
      return;
    }

    let blobUrl: string | null = null;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setImgUrl(null);
    setNatural(null);

    api
      .fetchPlanRaster(planId, page)
      .then((blob) => {
        if (cancelled) return;
        blobUrl = URL.createObjectURL(blob);
        setImgUrl(blobUrl);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Error desconocido");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [planId, page, deletedPages]);

  // Cargar elementos (todos los del plan para el visor 3D)
  useEffect(() => {
    let cancelled = false;
    setElementsLoading(true);
    api
      .listElements(planId)
      .then((data) => {
        if (!cancelled) setElements(data);
      })
      .catch(() => {
        if (!cancelled) setElements([]);
      })
      .finally(() => {
        if (!cancelled) setElementsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [planId]);

  // Catálogo de materiales (una vez por montaje)
  useEffect(() => {
    let cancelled = false;
    api
      .listAssemblies()
      .then((data) => {
        if (!cancelled) setAssembliesList(data);
      })
      .catch((err) => {
        if (!cancelled) setAssembliesList([]);
        console.error("Error loading assemblies:", err);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Cómputo agregado: recargar cuando cambia plan, página, o cualquier cosa
  // que pueda alterar las cantidades (asignación, edición de length/area/height).
  const summaryDeps = elements
    .map((e) => `${e.id}:${e.length_m}:${e.area_m2}:${e.height_m}:${e.assemblies.map((a) => a.id).join(",")}`)
    .join("|");
  useEffect(() => {
    if (draggingVertex) return;
    let cancelled = false;
    setSummaryLoading(true);
    api
      .getMaterialsSummary(planId, page)
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch(() => {
        if (!cancelled) setSummary([]);
      })
      .finally(() => {
        if (!cancelled) setSummaryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [planId, page, summaryDeps, draggingVertex]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setDims({ w: el.clientWidth, h: el.clientHeight || height });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [height]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const direction = e.deltaY > 0 ? 1 / ZOOM_STEP : ZOOM_STEP;
      const newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale * direction));
      const ratio = newScale / scale;
      setScale(newScale);
      setPos({
        x: px - (px - pos.x) * ratio,
        y: py - (py - pos.y) * ratio,
      });
    };

    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => {
      el.removeEventListener("wheel", handleWheel);
    };
  }, [scale, pos]);

  useEffect(() => {
    if (!natural || dims.w === 0) return;
    const fit = Math.min(dims.w / natural.w, dims.h / natural.h);
    const s = Math.min(fit * FIT_MARGIN, 1);
    setScale(s);
    setPos({
      x: (dims.w - natural.w * s) / 2,
      y: (dims.h - natural.h * s) / 2,
    });
  }, [natural, dims]);

  function onImgLoad(e: React.SyntheticEvent<HTMLImageElement>) {
    const img = e.currentTarget;
    setNatural({ w: img.naturalWidth, h: img.naturalHeight });
    setLoading(false);
  }

  function screenToImage(screenX: number, screenY: number): Point {
    return { x: (screenX - pos.x) / scale, y: (screenY - pos.y) / scale };
  }

  function imageToScreen(p: Point): Point {
    return { x: pos.x + p.x * scale, y: pos.y + p.y * scale };
  }

  function zoomAtCenter(direction: 1 | -1) {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const px = rect.width / 2;
    const py = rect.height / 2;
    const factor = direction === 1 ? ZOOM_STEP : 1 / ZOOM_STEP;
    const newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale * factor));
    const ratio = newScale / scale;
    setScale(newScale);
    setPos({
      x: px - (px - pos.x) * ratio,
      y: py - (py - pos.y) * ratio,
    });
  }

  function selectTool(t: Tool) {
    setTool(t);
    setActivePoints([]);
    setDrawError(null);
  }

  // Indicador: ¿estoy cerca del primer punto del polígono?
  const isClosingRoom = useMemo(() => {
    const isPolygonTool = tool === "room" || tool === "roof";
    if (!isPolygonTool || activePoints.length < 3 || !mousePos) return false;
    const dx = (mousePos.x - activePoints[0].x) * scale;
    const dy = (mousePos.y - activePoints[0].y) * scale;
    return Math.hypot(dx, dy) < CLOSE_POLYGON_PX;
  }, [tool, activePoints, mousePos, scale]);

  // Crear muro, abertura, viga, riostra, cloaca, electricidad (2 puntos → 1 elemento)
  const createSegmentElement = useCallback(
    async (pts: Point[], type: "wall" | "opening" | "beam" | "riostra" | "cloaca" | "electricidad") => {
      if (!currentPageScale || pts.length !== 2) return;
      const lengthM = distM(pts[0], pts[1], currentPageScale);
      if (lengthM < MIN_SEGMENT_M) {
        setDrawError("Segmento demasiado corto, ignorado");
        setTimeout(() => setDrawError(null), 2000);
        return;
      }
      setDrawError(null);
      // Para aberturas: el subtipo activo decide alto default y se persiste
      // en geometry.subtype. El usuario lo puede editar después en el sidebar.
      const subtype = type === "opening"
        ? OPENING_SUBTYPES.find((s) => s.value === openingSubtype) ?? OPENING_SUBTYPES[0]
        : null;
      const defaultHeight = type === "opening"
        ? subtype!.defaultH_m
        : type === "beam" ? 0.40 : type === "riostra" ? 0.40 : type === "cloaca" ? 0.11 : type === "electricidad" ? 0.05 : 2.8;
      try {
        const el = await api.createElement(planId, {
          page,
          type,
          geometry: {
            points: [pts[0].x, pts[0].y, pts[1].x, pts[1].y],
            ...(subtype ? { subtype: subtype.value } : {}),
          },
          length_m: lengthM,
          height_m: defaultHeight,
        });
        setElements((prev) => [...prev, el]);
      } catch (err) {
        setDrawError(err instanceof Error ? err.message : "Error al guardar");
      }
    },
    [planId, page, currentPageScale, openingSubtype],
  );

  // Crear columna como un punto (1 punto → 1 elemento)
  const createPointElement = useCallback(
    async (pt: Point, type: "column" = "column") => {
      if (!currentPageScale) return;
      // Default: 30x30 cm -> area = 0.09 m2, perimeter = 1.2 m
      const areaM2 = 0.09;
      const perimM = 1.2;
      setDrawError(null);
      try {
        const el = await api.createElement(planId, {
          page,
          type,
          geometry: {
            points: [pt.x, pt.y],
          },
          area_m2: areaM2,
          length_m: perimM,
          height_m: 2.8,
        });
        setElements((prev) => [...prev, el]);
      } catch (err) {
        setDrawError(err instanceof Error ? err.message : "Error al guardar");
      }
    },
    [planId, page, currentPageScale],
  );

  // Crear recinto o techo (>= 3 puntos → polígono cerrado)
  const createPolygonElement = useCallback(
    async (pts: Point[], type: "room" | "roof" = "room") => {
      if (!currentPageScale || pts.length < 3) return;
      const areaM2 = polygonAreaM2(pts, currentPageScale);
      const perimM = polygonPerimeterM(pts, currentPageScale);
      if (areaM2 < 0.01) {
        const typeLabel = type === "room" ? "Recinto" : "Techo";
        setDrawError(`${typeLabel} con área insignificante`);
        setTimeout(() => setDrawError(null), 2000);
        return;
      }
      setDrawError(null);
      const flat = pts.flatMap((p) => [p.x, p.y]);
      try {
        const el = await api.createElement(planId, {
          page,
          type,
          geometry: { points: flat },
          area_m2: areaM2,
          length_m: perimM,
          height_m: type === "roof" ? 0.20 : 2.8,
        });
        setElements((prev) => [...prev, el]);
      } catch (err) {
        setDrawError(err instanceof Error ? err.message : "Error al guardar");
      }
    },
    [planId, page, currentPageScale],
  );

  const createPolylineElement = useCallback(
    async (pts: Point[], type: "cloaca" | "electricidad") => {
      if (!currentPageScale || pts.length < 2) return;
      let lengthM = 0;
      for (let i = 0; i < pts.length - 1; i++) {
        lengthM += distM(pts[i], pts[i + 1], currentPageScale);
      }
      if (lengthM < MIN_SEGMENT_M) {
        setDrawError("Trazo demasiado corto, ignorado");
        setTimeout(() => setDrawError(null), 2000);
        return;
      }
      setDrawError(null);
      const defaultHeight = type === "cloaca" ? 0.11 : 0.05;
      const flat = pts.flatMap((p) => [p.x, p.y]);
      try {
        const el = await api.createElement(planId, {
          page,
          type,
          geometry: { points: flat },
          length_m: lengthM,
          height_m: defaultHeight,
        });
        setElements((prev) => [...prev, el]);
      } catch (err) {
        setDrawError(err instanceof Error ? err.message : "Error al guardar");
      }
    },
    [planId, page, currentPageScale],
  );

  function handleDrawClick(p: Point) {
    if (tool === "column") {
      void createPointElement(p, "column");
      return;
    }
    if (tool === "wall" || tool === "opening" || tool === "beam" || tool === "riostra" || tool === "cloaca" || (tool === "electricidad" && !isFreehandMode)) {
      if (activePoints.length === 0) {
        setActivePoints([p]);
        return;
      }
      const pts = [...activePoints, p];
      setActivePoints([]);
      void createSegmentElement(pts, tool as "wall" | "opening" | "beam" | "riostra" | "cloaca" | "electricidad");
      return;
    }
    if (tool === "room" || tool === "roof") {
      if (activePoints.length >= 3 && isClosingRoom) {
        const pts = activePoints;
        setActivePoints([]);
        void createPolygonElement(pts, tool);
        return;
      }
      setActivePoints((prev) => [...prev, p]);
    }
  }

  function onMouseDown(e: React.MouseEvent<HTMLDivElement>) {
    if (e.button !== 0 || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    if (calibrating) {
      const imgPoint = screenToImage(sx, sy);
      if (calPoints.length < 2) {
        const next = [...calPoints, imgPoint];
        setCalPoints(next);
        if (next.length === 2) setDistanceModalOpen(true);
      }
      return;
    }

    if (tool !== "pan" && !drawingDisabled) {
      const imgPoint = screenToImage(sx, sy);
      if (tool === "electricidad" && isFreehandMode) {
        setIsFreehandDrawing(true);
        setActivePoints([imgPoint]);
      } else {
        handleDrawClick(imgPoint);
      }
      return;
    }

    // Pan
    setDragging(true);
    hasMovedDuringDrag.current = false;
    dragStart.current = { x: e.clientX, y: e.clientY, px: pos.x, py: pos.y };
  }

  function onMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    if (isFreehandDrawing && tool === "electricidad") {
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const imgPoint = screenToImage(sx, sy);
      
      setActivePoints((prev) => {
        if (prev.length === 0) return [imgPoint];
        const lastP = prev[prev.length - 1];
        const dx = imgPoint.x - lastP.x;
        const dy = imgPoint.y - lastP.y;
        const dist = Math.hypot(dx, dy);
        if (dist > 10 / scale) {
          return [...prev, imgPoint];
        }
        return prev;
      });
      return;
    }

    if (draggingVertex) {
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const imgPoint = screenToImage(sx, sy);
      if (!imgPoint) return;

      setElements((prev) =>
        prev.map((el) => {
          if (el.id !== draggingVertex.elementId) return el;
          const pts = [...el.geometry.points];
          pts[draggingVertex.pointIndex] = imgPoint.x;
          pts[draggingVertex.pointIndex + 1] = imgPoint.y;
          const metrics = getCalculatedMetrics(el.type, pts, currentPageScale);
          return {
            ...el,
            geometry: {
              ...el.geometry,
              points: pts,
            },
            ...metrics,
          };
        })
      );
      return;
    }

    if (dragging && dragStart.current) {
      const dx = e.clientX - dragStart.current.x;
      const dy = e.clientY - dragStart.current.y;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
        hasMovedDuringDrag.current = true;
      }
      setPos({ x: dragStart.current.px + dx, y: dragStart.current.py + dy });
      return;
    }
    // Actualizar mousePos para preview de dibujo / calibración
    if ((tool !== "pan" || calibrating) && containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      setMousePos(screenToImage(sx, sy));
    }
  }

  function onMouseLeave() {
    if (isFreehandDrawing && tool === "electricidad") {
      setIsFreehandDrawing(false);
      const pts = activePoints;
      setActivePoints([]);
      if (pts.length >= 2) {
        void createPolylineElement(pts, "electricidad");
      }
      return;
    }

    if (draggingVertex) {
      const elementId = draggingVertex.elementId;
      setDraggingVertex(null);
      const el = elements.find((item) => item.id === elementId);
      if (el) {
        void finalizeElementGeometry(el);
      }
      return;
    }
    setDragging(false);
    dragStart.current = null;
    setMousePos(null);
  }

  function onMouseUp() {
    if (isFreehandDrawing && tool === "electricidad") {
      setIsFreehandDrawing(false);
      const pts = activePoints;
      setActivePoints([]);
      if (pts.length >= 2) {
        void createPolylineElement(pts, "electricidad");
      }
      return;
    }

    if (draggingVertex) {
      const elementId = draggingVertex.elementId;
      setDraggingVertex(null);
      const el = elements.find((item) => item.id === elementId);
      if (el) {
        void finalizeElementGeometry(el);
      }
      return;
    }
    setDragging(false);
    dragStart.current = null;
  }

  function onDoubleClick() {
    // Doble-click cierra polígono activo si tiene >= 3 puntos
    const isPolygonTool = tool === "room" || tool === "roof";
    if (isPolygonTool && activePoints.length >= 3) {
      const pts = activePoints;
      setActivePoints([]);
      void createPolygonElement(pts, tool);
    } else if (!isPolygonTool && activePoints.length > 0) {
      const pts = activePoints;
      setActivePoints([]);
      if (tool === "electricidad" && isFreehandMode && pts.length >= 2) {
        void createPolylineElement(pts, "electricidad");
      }
    }
  }

  function resetView() {
    if (!natural || dims.w === 0) return;
    const fit = Math.min(dims.w / natural.w, dims.h / natural.h);
    const s = Math.min(fit * FIT_MARGIN, 1);
    setScale(s);
    setPos({
      x: (dims.w - natural.w * s) / 2,
      y: (dims.h - natural.h * s) / 2,
    });
  }

  function goToPage(n: number) {
    if (activePages.length === 0) return;
    if (activePages.includes(n)) {
      if (n !== page) setPage(n);
      return;
    }
    // Si la página pedida no es válida (eliminada o fuera de rango), ir a la más cercana activa
    const closest = activePages.reduce((prev, curr) =>
      Math.abs(curr - n) < Math.abs(prev - n) ? curr : prev,
    );
    if (closest !== page) setPage(closest);
  }

  function goToFirstActive() {
    if (activePages.length > 0) setPage(activePages[0]);
  }

  function goToLastActive() {
    if (activePages.length > 0) setPage(activePages[activePages.length - 1]);
  }

  function goToPrevActive() {
    const idx = activePages.indexOf(page);
    if (idx > 0) setPage(activePages[idx - 1]);
  }

  function goToNextActive() {
    const idx = activePages.indexOf(page);
    if (idx >= 0 && idx < activePages.length - 1) setPage(activePages[idx + 1]);
  }

  async function applyPageOverride(
    targetPage: number,
    next: "recommended" | "rejected" | null,
  ) {
    setOverridingPage(true);
    try {
      const updatedPlan = await api.setPageOverride(planId, targetPage, next);
      onPlanUpdated?.(updatedPlan);
      // Recargar recomendaciones para reflejar el override
      const recs = await api.recommendPages(planId);
      setRecommendedPages(recs);
    } catch (err) {
      setDrawError(
        err instanceof Error ? err.message : "Error guardando override",
      );
    } finally {
      setOverridingPage(false);
    }
  }

  async function applyDeletePage(p: number) {
    setPageBusy(true);
    try {
      const updated = await api.deletePage(planId, p);
      onPlanUpdated?.(updated);
      setConfirmDeletePage(null);
      setDeleteConfirmText("");
      const recs = await api.recommendPages(planId);
      setRecommendedPages(recs);
    } catch (err) {
      setDrawError(err instanceof Error ? err.message : "Error al eliminar página");
    } finally {
      setPageBusy(false);
    }
  }

  function startCalibration() {
    setCalibrating(true);
    setCalPoints([]);
    setCalError(null);
    selectTool("pan");
  }

  async function runAutoDetect() {
    setAutoDetecting(true);
    setCalError(null);
    try {
      const preview = await api.previewAutoDetectScales(planId);
      const initialSelected: Record<string, boolean> = {};
      const initialEdited: Record<string, string> = {};
      Object.entries(preview).forEach(([pageStr, denom]) => {
        initialSelected[pageStr] = true;
        initialEdited[pageStr] = String(denom);
      });
      setSelectedPages(initialSelected);
      setEditedScales(initialEdited);
      setDetectedPreview(preview);
    } catch (err) {
      setCalError(err instanceof Error ? err.message : "Error al detectar escalas");
    } finally {
      setAutoDetecting(false);
    }
  }

  async function submitBulkScales(e: React.FormEvent) {
    e.preventDefault();
    if (!detectedPreview) return;
    const payload: Record<string, number> = {};
    let hasInvalid = false;
    Object.entries(editedScales).forEach(([pageStr, valueStr]) => {
      if (!selectedPages[pageStr]) return;
      const denom = parseFloat(valueStr.replace(",", "."));
      if (!Number.isFinite(denom) || denom <= 0) hasInvalid = true;
      else payload[pageStr] = denom;
    });
    if (hasInvalid) {
      setCalError("Hay escalas inválidas o vacías");
      return;
    }
    if (Object.keys(payload).length === 0) {
      setDetectedPreview(null);
      return;
    }
    setSavingBulk(true);
    setCalError(null);
    try {
      const updated = await api.setBulkScaleRatios(planId, payload);
      onPlanUpdated?.(updated);
      setDetectedPreview(null);
    } catch (err) {
      setCalError(err instanceof Error ? err.message : "Error al guardar las escalas");
    } finally {
      setSavingBulk(false);
    }
  }

  function cancelCalibration() {
    setCalibrating(false);
    setCalPoints([]);
    setDistanceModalOpen(false);
    setDistanceInput("");
    setCalError(null);
  }

  async function submitCalibration(e: React.FormEvent) {
    e.preventDefault();
    if (calPoints.length !== 2) return;
    const meters = parseFloat(distanceInput.replace(",", "."));
    if (!Number.isFinite(meters) || meters <= 0) {
      setCalError("Distancia inválida");
      return;
    }
    setSavingScale(true);
    setCalError(null);
    try {
      const updated = await api.calibrateScale(
        planId,
        calPoints[0],
        calPoints[1],
        meters,
        page,
      );
      onPlanUpdated?.(updated);
      setDistanceModalOpen(false);
      setDistanceInput("");
      setCalPoints([]);
      setCalibrating(false);
    } catch (err) {
      setCalError(err instanceof Error ? err.message : "Error desconocido");
    } finally {
      setSavingScale(false);
    }
  }

  function toggleSelected(id: number, multi: boolean = false) {
    setSelectedIds((prev) => {
      if (multi) {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      } else {
        if (prev.has(id) && prev.size === 1) return new Set();
        return new Set([id]);
      }
    });
  }

  function getCalculatedMetrics(elType: string, points: number[], scaleVal: number | null) {
    if (!scaleVal) return { length_m: null, area_m2: null };
    if (elType === "wall" || elType === "opening") {
      if (points.length < 4) return { length_m: null, area_m2: null };
      const dx = (points[2] - points[0]) / scaleVal;
      const dy = (points[3] - points[1]) / scaleVal;
      const len = parseFloat(Math.sqrt(dx * dx + dy * dy).toFixed(2));
      return { length_m: len, area_m2: null };
    } else if (elType === "room") {
      const pts = chunkPoints(points);
      if (pts.length < 3) return { length_m: null, area_m2: null };
      const area = parseFloat(polygonAreaM2(pts, scaleVal).toFixed(2));
      const perim = parseFloat(polygonPerimeterM(pts, scaleVal).toFixed(2));
      return { length_m: perim, area_m2: area };
    }
    return { length_m: null, area_m2: null };
  }

  async function finalizeElementGeometry(el: DetectedElement) {
    const metrics = getCalculatedMetrics(el.type, el.geometry.points, currentPageScale);
    try {
      const updated = await api.updateElement(planId, el.id, {
        geometry: el.geometry,
        length_m: metrics.length_m,
        area_m2: metrics.area_m2,
      });
      setElements((prev) => prev.map((item) => (item.id === el.id ? updated : item)));
    } catch (err) {
      setDrawError(err instanceof Error ? err.message : "Error al actualizar geometría");
    }
  }

  const startDragVertex = (e: React.MouseEvent, elementId: number, pointIndex: number) => {
    e.stopPropagation();
    setDraggingVertex({ elementId, pointIndex });
  };

  const startDragMidpoint = (
    e: React.MouseEvent,
    elementId: number,
    edgeIndex: number,
    mx: number,
    my: number
  ) => {
    e.stopPropagation();
    const el = elements.find((item) => item.id === elementId);
    if (!el || el.type !== "room") return;
    const pts = [...el.geometry.points];
    
    // Insertar nuevo vértice en el índice (edgeIndex + 1) * 2
    const insertIndex = (edgeIndex + 1) * 2;
    pts.splice(insertIndex, 0, mx, my);
    
    setElements((prev) =>
      prev.map((item) => {
        if (item.id !== elementId) return item;
        return {
          ...item,
          geometry: {
            ...item.geometry,
            points: pts,
          },
        };
      })
    );
    
    setDraggingVertex({ elementId, pointIndex: insertIndex });
  };

  const deleteVertex = (e: React.MouseEvent, elementId: number, pointIndex: number) => {
    e.stopPropagation();
    const el = elements.find((item) => item.id === elementId);
    if (!el || el.type !== "room") return;
    const pts = [...el.geometry.points];
    if (pts.length <= 6) return; // Mínimo 3 vértices
    
    pts.splice(pointIndex, 2);
    const metrics = getCalculatedMetrics(el.type, pts, currentPageScale);
    const updatedGeometry = { ...el.geometry, points: pts };

    setElements((prev) =>
      prev.map((item) => {
        if (item.id !== elementId) return item;
        return {
          ...item,
          geometry: updatedGeometry,
          ...metrics,
        };
      })
    );

    void api.updateElement(planId, elementId, {
      geometry: updatedGeometry,
      length_m: metrics.length_m,
      area_m2: metrics.area_m2,
    });
  };

  const autoAdjustRoomToWalls = async (roomId: number) => {
    const room = elements.find((el) => el.id === roomId);
    if (!room || room.type !== "room") return;

    // Obtener muros de la pagina actual
    const pageWalls = elements.filter(
      (el) => el.type === "wall" && el.page === room.page
    );

    if (pageWalls.length === 0) {
      setDrawError("No hay muros dibujados en esta pagina para ajustar el recinto.");
      return;
    }

    const pts = room.geometry.points;
    if (pts.length < 6) return;

    let sumX = 0;
    let sumY = 0;
    const count = pts.length / 2;
    for (let i = 0; i < pts.length; i += 2) {
      sumX += pts[i];
      sumY += pts[i + 1];
    }
    const cx = sumX / count;
    const cy = sumY / count;

    let leftX: number | null = null;
    let rightX: number | null = null;
    let topY: number | null = null;
    let bottomY: number | null = null;

    const tol = 120; // pixeles de tolerancia (~60cm)

    for (const wall of pageWalls) {
      const [wx1, wy1, wx2, wy2] = wall.geometry.points;
      const dx = Math.abs(wx2 - wx1);
      const dy = Math.abs(wy2 - wy1);
      const isVertical = dy >= dx;

      if (isVertical) {
        const xAvg = (wx1 + wx2) / 2;
        const yMin = Math.min(wy1, wy2);
        const yMax = Math.max(wy1, wy2);

        if (yMin - tol <= cy && cy <= yMax + tol) {
          if (xAvg < cx) {
            if (leftX === null || xAvg > leftX) {
              leftX = xAvg;
            }
          } else if (xAvg > cx) {
            if (rightX === null || xAvg < rightX) {
              rightX = xAvg;
            }
          }
        }
      } else {
        const yAvg = (wy1 + wy2) / 2;
        const xMin = Math.min(wx1, wx2);
        const xMax = Math.max(wx1, wx2);

        if (xMin - tol <= cx && cx <= xMax + tol) {
          if (yAvg < cy) {
            if (topY === null || yAvg > topY) {
              topY = yAvg;
            }
          } else if (yAvg > cy) {
            if (bottomY === null || yAvg < bottomY) {
              bottomY = yAvg;
            }
          }
        }
      }
    }

    let minX = pts[0];
    let maxX = pts[0];
    let minY = pts[1];
    let maxY = pts[1];
    for (let i = 0; i < pts.length; i += 2) {
      if (pts[i] < minX) minX = pts[i];
      if (pts[i] > maxX) maxX = pts[i];
      if (pts[i + 1] < minY) minY = pts[i + 1];
      if (pts[i + 1] > maxY) maxY = pts[i + 1];
    }

    const xmin = leftX !== null ? leftX : minX;
    const xmax = rightX !== null ? rightX : maxX;
    const ymin = topY !== null ? topY : minY;
    const ymax = bottomY !== null ? bottomY : maxY;

    const newPts = [
      xmin, ymin,
      xmax, ymin,
      xmax, ymax,
      xmin, ymax
    ];

    const metrics = getCalculatedMetrics("room", newPts, currentPageScale);
    const updatedGeometry = { ...room.geometry, points: newPts };

    setElements((prev) =>
      prev.map((item) => {
        if (item.id !== roomId) return item;
        return {
          ...item,
          geometry: updatedGeometry,
          ...metrics,
        };
      })
    );

    try {
      await api.updateElement(planId, roomId, {
        geometry: updatedGeometry,
        length_m: metrics.length_m,
        area_m2: metrics.area_m2,
      });
    } catch (err) {
      setDrawError(err instanceof Error ? err.message : "Error al ajustar recinto");
    }
  };

  function selectAll() {
    setSelectedIds(new Set(displayElements.map((e) => e.id)));
  }

  function clearSelection() {
    setSelectedIds(new Set());
  }

  function requestDelete(ids: number[]) {
    if (ids.length === 0) return;
    const label =
      ids.length === 1
        ? (() => {
            const el = elements.find((e) => e.id === ids[0]);
            return el?.geometry.label ?? labelFor(el?.type ?? "wall", 1);
          })()
        : `${ids.length} elementos`;
    setConfirmDelete({ ids, label });
  }

  async function applyDelete(ids: number[]) {
    setBulkBusy(true);
    try {
      if (ids.length === 1) {
        await api.deleteElement(planId, ids[0]);
      } else {
        await api.bulkDeleteElements(planId, ids);
      }
      setElements((prev) => prev.filter((e) => !ids.includes(e.id)));
      setSelectedIds((prev) => {
        const next = new Set(prev);
        ids.forEach((id) => next.delete(id));
        return next;
      });
      if (editingId !== null && ids.includes(editingId)) setEditingId(null);
      setConfirmDelete(null);
    } catch (err) {
      setDrawError(err instanceof Error ? err.message : "Error al eliminar");
    } finally {
      setBulkBusy(false);
    }
  }

  async function applyScale(factor: number) {
    if (!Number.isFinite(factor) || factor <= 0) {
      setDrawError("Factor inválido");
      return;
    }
    const targets = elements.filter((e) => selectedIds.has(e.id));
    if (targets.length === 0) return;
    setBulkBusy(true);
    try {
      const updated = await Promise.all(
        targets.map((el) => {
          const patch: { length_m?: number; area_m2?: number } = {};
          if (el.length_m != null) patch.length_m = el.length_m * factor;
          if (el.area_m2 != null) patch.area_m2 = el.area_m2 * factor * factor;
          return api.updateElement(planId, el.id, patch);
        }),
      );
      setElements((prev) => prev.map((el) => updated.find((u) => u.id === el.id) ?? el));
      setScaleModalOpen(false);
      setScaleFactor("1");
    } catch (err) {
      setDrawError(err instanceof Error ? err.message : "Error al escalar");
    } finally {
      setBulkBusy(false);
    }
  }

  async function assignAssemblyToElement(elementId: number, assemblyId: number) {
    try {
      const updated = await api.assignAssembly(planId, elementId, assemblyId);
      setElements((prev) => prev.map((e) => (e.id === elementId ? updated : e)));
    } catch (err) {
      setDrawError(err instanceof Error ? err.message : "Error al asignar sistema constructivo");
    }
  }

  async function removeAssemblyFromElement(elementId: number, assemblyId: number) {
    try {
      const updated = await api.removeAssembly(planId, elementId, assemblyId);
      setElements((prev) => prev.map((e) => (e.id === elementId ? updated : e)));
    } catch (err) {
      setDrawError(err instanceof Error ? err.message : "Error al quitar sistema constructivo");
    }
  }

  async function applyBulkAssignAssembly(assemblyId: number) {
    const ids = [...selectedIds];
    if (ids.length === 0) return;
    setBulkBusy(true);
    try {
      const updated = await api.bulkAssignAssembly(planId, ids, assemblyId);
      setElements((prev) => prev.map((el) => updated.find((u) => u.id === el.id) ?? el));
      setBulkAssignOpen(false);
    } catch (err) {
      setDrawError(err instanceof Error ? err.message : "Error al asignar en lote");
    } finally {
      setBulkBusy(false);
    }
  }

  async function downloadXlsx() {
    setExporting(true);
    try {
      const blob = await api.exportXlsx(planId, page);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `computo_plan${planId}_p${page}.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      setDrawError(err instanceof Error ? err.message : "Error al exportar");
    } finally {
      setExporting(false);
    }
  }

  async function updateElementInline(
    id: number,
    patch: { label?: string; height_m?: number; length_m?: number; subtype?: string },
  ) {
    const el = elements.find((e) => e.id === id);
    if (!el) return;
    const apiPatch: { geometry?: ElementGeometry; height_m?: number; length_m?: number } = {};
    // Label y subtype viven dentro de `geometry`; los merge-amos en el mismo
    // objeto si vienen los dos en el mismo patch para no perder uno.
    if (patch.label !== undefined || patch.subtype !== undefined) {
      apiPatch.geometry = {
        ...el.geometry,
        ...(patch.label !== undefined ? { label: patch.label } : {}),
        ...(patch.subtype !== undefined ? { subtype: patch.subtype } : {}),
      };
    }
    if (patch.height_m !== undefined) {
      apiPatch.height_m = patch.height_m;
    }
    if (patch.length_m !== undefined) {
      apiPatch.length_m = patch.length_m;
    }
    if (Object.keys(apiPatch).length === 0) return;
    try {
      const updated = await api.updateElement(planId, id, apiPatch);
      setElements((prev) => prev.map((e) => (e.id === id ? updated : e)));
    } catch (err) {
      setDrawError(err instanceof Error ? err.message : "Error al guardar");
    }
  }

  // Teclado: Esc cancela, Enter cierra polígono, Ctrl+Z deshace último punto
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      const tgt = e.target as HTMLElement | null;
      if (tgt && ["INPUT", "TEXTAREA"].includes(tgt.tagName)) return;

      if (e.key === "Escape") {
        if (calibrating) {
          cancelCalibration();
        } else if (activePoints.length > 0) {
          setActivePoints([]);
        } else if (tool !== "pan") {
          selectTool("pan");
        }
        return;
      }
      const isPolygonTool = tool === "room" || tool === "roof";
      if (e.key === "Enter") {
        if (isPolygonTool && activePoints.length >= 3) {
          e.preventDefault();
          const pts = activePoints;
          setActivePoints([]);
          void createPolygonElement(pts, tool);
          return;
        } else if (!isPolygonTool && activePoints.length > 0) {
          e.preventDefault();
          const pts = activePoints;
          setActivePoints([]);
          if ((tool === "cloaca" || tool === "electricidad") && pts.length >= 2) {
            void createPolylineElement(pts, tool);
          }
          return;
        }
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && activePoints.length > 0) {
        e.preventDefault();
        setActivePoints((prev) => prev.slice(0, -1));
        return;
      }
      // Atajos de herramienta
      if (e.key.toLowerCase() === "h") selectTool("pan");
      if (!drawingDisabled) {
        if (e.key.toLowerCase() === "l") selectTool("wall");
        if (e.key.toLowerCase() === "p") selectTool("room");
        if (e.key.toLowerCase() === "o") selectTool("opening");
        if (e.key.toLowerCase() === "v") selectTool("beam");
        if (e.key.toLowerCase() === "t") selectTool("roof");
        if (e.key.toLowerCase() === "c") selectTool("column");
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [calibrating, activePoints, tool, drawingDisabled, createPolygonElement, createPolylineElement]);

  const processing = rendered !== null && rendered < totalPages;
  const detectedCount = pageScales ? Object.keys(pageScales).length : 0;
  const cursor = draggingVertex
    ? "grabbing"
    : calibrating
      ? "crosshair"
      : dragging
        ? "grabbing"
        : tool !== "pan" && !drawingDisabled
          ? "crosshair"
          : imgUrl
            ? "grab"
            : "default";

  // === Contadores del sidebar para la PÁGINA ACTUAL ===
  const totalWallM = pageVisibleElements
    .filter((e) => e.type === "wall")
    .reduce((acc, w) => acc + (w.length_m || 0), 0);
  const totalRoomM2 = pageVisibleElements
    .filter((e) => e.type === "room")
    .reduce((acc, r) => acc + (r.area_m2 || 0), 0);
  const totalOpenings = pageVisibleElements.filter((e) => e.type === "opening").length;

  const totalBeamsM = pageVisibleElements
    .filter((e) => e.type === "beam")
    .reduce((acc, b) => acc + (b.length_m || 0), 0);
  const totalRoofsM2 = pageVisibleElements
    .filter((e) => e.type === "roof")
    .reduce((acc, r) => acc + (r.area_m2 || 0), 0);
  const totalColumns = pageVisibleElements.filter((e) => e.type === "column").length;

  return (
    <div className="flex flex-col gap-3">
      {processing && (
        <div className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs dark:border-sky-900 dark:bg-sky-950/40">
          <div className="mb-1 flex items-center justify-between text-sky-800 dark:text-sky-200">
            <span>
              Procesando páginas en segundo plano: {rendered} de {totalPages}
            </span>
            <span className="text-sky-600 dark:text-sky-400">
              {Math.round(((rendered ?? 0) / totalPages) * 100)}%
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-sky-200 dark:bg-sky-900">
            <div
              className="h-full bg-sky-500 transition-all dark:bg-sky-400"
              style={{ width: `${((rendered ?? 0) / totalPages) * 100}%` }}
            />
          </div>
        </div>
      )}



      <div className="flex flex-col gap-3 lg:flex-row" style={{ minHeight: height + 80 }}>
        {/* PANEL IZQUIERDO — Elementos */}
        <aside className="flex w-full shrink-0 flex-col rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 lg:w-72">
          <div className="mb-1 flex items-center justify-between gap-2">
            <h3 className="text-sm font-bold text-slate-800 dark:text-slate-100">
              Elementos
            </h3>
            {displayElements.length > 0 && (
              <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400 select-none">
                <input
                  type="checkbox"
                  checked={selectedIds.size === displayElements.length && displayElements.length > 0}
                  ref={(el) => {
                    if (el) {
                      el.indeterminate =
                        selectedIds.size > 0 && selectedIds.size < displayElements.length;
                    }
                  }}
                  onChange={(e) => (e.target.checked ? selectAll() : clearSelection())}
                  className="h-3.5 w-3.5 rounded border-slate-300 text-brand focus:ring-1 focus:ring-brand dark:border-slate-600 dark:bg-slate-900"
                />
                Todos
              </label>
            )}
          </div>
          <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
            Página {page} · {displayElements.length} dibujado{displayElements.length === 1 ? "" : "s"}
          </p>

          {/* Totales */}
          <div className="mb-3 grid grid-cols-3 gap-x-2 gap-y-2 rounded-lg border border-slate-100 bg-slate-50/50 p-2 text-center text-[10px] dark:border-slate-800 dark:bg-slate-950/40">
            <div>
              <div className="font-semibold text-slate-700 dark:text-slate-200">
                {totalWallM.toFixed(1)} m
              </div>
              <div className="text-[9px] text-slate-400">Muros</div>
            </div>
            <div>
              <div className="font-semibold text-slate-700 dark:text-slate-200">
                {totalRoomM2.toFixed(1)} m²
              </div>
              <div className="text-[9px] text-slate-400">Recintos</div>
            </div>
            <div>
              <div className="font-semibold text-slate-700 dark:text-slate-200">
                {totalOpenings}
              </div>
              <div className="text-[9px] text-slate-400">Abert.</div>
            </div>
            <div>
              <div className="font-semibold text-slate-700 dark:text-slate-200">
                {totalBeamsM.toFixed(1)} m
              </div>
              <div className="text-[9px] text-slate-400">Vigas</div>
            </div>
            <div>
              <div className="font-semibold text-slate-700 dark:text-slate-200">
                {totalRoofsM2.toFixed(1)} m²
              </div>
              <div className="text-[9px] text-slate-400">Techos</div>
            </div>
            <div>
              <div className="font-semibold text-slate-700 dark:text-slate-200">
                {totalColumns}
              </div>
              <div className="text-[9px] text-slate-400">Cols.</div>
            </div>
          </div>

          {/* Detección con IA */}
          <div className="mb-3 rounded-lg border border-slate-200 dark:border-slate-800">
            <button
              type="button"
              onClick={() => setIaPanelOpen((v) => !v)}
              className="flex w-full items-center justify-between px-3 py-2 text-xs font-bold text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800/40 rounded-t-lg"
            >
              <span>Detección con IA</span>
              <ChevronIcon open={iaPanelOpen} />
            </button>

            {iaPanelOpen && (
              <div className="border-t border-slate-100 dark:border-slate-800 p-2.5 space-y-2">
                {detectionError && (
                  <div className="rounded bg-red-50 dark:bg-red-950/40 p-2 text-[10px] text-red-600 dark:text-red-400">
                    {detectionError}
                  </div>
                )}

                <div className="grid grid-cols-3 gap-1.5">
                  <button
                    type="button"
                    onClick={runDetectWalls}
                    disabled={!currentPageScale || detectingWalls || bulkBusy}
                    className="flex flex-col items-center justify-center rounded border border-slate-200 bg-white hover:bg-slate-50 py-1.5 text-[10px] font-semibold text-slate-700 disabled:opacity-40 disabled:cursor-not-allowed dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                    title={!currentPageScale ? "Calibrá la página primero" : "Detectar muros estructurales"}
                  >
                    {detectingWalls ? "..." : "Muros"}
                  </button>
                  <button
                    type="button"
                    onClick={runDetectRooms}
                    disabled={!currentPageScale || detectingRooms || bulkBusy}
                    className="flex flex-col items-center justify-center rounded border border-slate-200 bg-white hover:bg-slate-50 py-1.5 text-[10px] font-semibold text-slate-700 disabled:opacity-40 disabled:cursor-not-allowed dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                    title={!currentPageScale ? "Calibrá la página primero" : "Detectar recintos"}
                  >
                    {detectingRooms ? "..." : "Recintos"}
                  </button>
                  <button
                    type="button"
                    onClick={runDetectOpenings}
                    disabled={!currentPageScale || detectingOpenings || bulkBusy}
                    className="flex flex-col items-center justify-center rounded border border-slate-200 bg-white hover:bg-slate-50 py-1.5 text-[10px] font-semibold text-slate-700 disabled:opacity-40 disabled:cursor-not-allowed dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                    title={!currentPageScale ? "Calibrá la página primero" : "Detectar aberturas"}
                  >
                    {detectingOpenings ? "..." : "Aberturas"}
                  </button>
                </div>

                {/* Ocultar Detección de IA */}
                <button
                  type="button"
                  onClick={() => setHideAiElements((v) => !v)}
                  className={`flex w-full items-center justify-center gap-1.5 rounded border py-1.5 text-[11px] font-semibold transition-colors ${
                    hideAiElements
                      ? "border-sky-500 bg-sky-50 text-sky-700 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-400"
                      : "border-slate-200 bg-white hover:bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                  }`}
                >
                  {hideAiElements ? "Mostrar dibujos IA" : "Ocultar dibujos IA"}
                </button>

                {/* Resumen Candidatos Muros */}
                {!hideAiElements && wallCandidates.length > 0 && (() => {
                  const selCount = wallCandidates.filter((c) => selectedCandidateIds.has(c.id)).length;
                  return (
                    <div className="rounded-lg bg-sky-50/50 border border-sky-100 p-2 space-y-1.5 dark:bg-sky-950/20 dark:border-sky-900/50">
                      <div className="flex items-center justify-between text-[10px]">
                        <span className="font-bold text-sky-700 dark:text-sky-400">
                          Muros AI ({selCount}/{wallCandidates.length})
                        </span>
                      </div>
                      <div className="flex gap-1.5">
                        <button
                          type="button"
                          onClick={confirmCandidateWalls}
                          disabled={bulkBusy}
                          className="flex-1 rounded bg-sky-600 hover:bg-sky-500 text-white font-semibold text-[9px] py-1 transition-all disabled:opacity-50"
                        >
                          Aceptar
                        </button>
                        <button
                          type="button"
                          onClick={() => discardCandidates("wall")}
                          disabled={bulkBusy}
                          className="rounded border border-slate-300 hover:bg-slate-100 text-slate-600 font-semibold text-[9px] px-2 py-1 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 transition-all disabled:opacity-50"
                        >
                          Descartar
                        </button>
                      </div>
                    </div>
                  );
                })()}

                {/* Resumen Candidatos Recintos */}
                {!hideAiElements && roomCandidates.length > 0 && (() => {
                  const selCount = roomCandidates.filter((c) => selectedCandidateIds.has(c.id)).length;
                  return (
                    <div className="rounded-lg bg-emerald-50/50 border border-emerald-100 p-2 space-y-1.5 dark:bg-emerald-950/20 dark:border-emerald-900/50">
                      <div className="flex items-center justify-between text-[10px]">
                        <span className="font-bold text-emerald-700 dark:text-emerald-400">
                          Recintos AI ({selCount}/{roomCandidates.length})
                        </span>
                      </div>
                      <div className="flex gap-1.5">
                        <button
                          type="button"
                          onClick={confirmCandidateRooms}
                          disabled={bulkBusy}
                          className="flex-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-[9px] py-1 transition-all disabled:opacity-50"
                        >
                          Aceptar
                        </button>
                        <button
                          type="button"
                          onClick={() => discardCandidates("room")}
                          disabled={bulkBusy}
                          className="rounded border border-slate-300 hover:bg-slate-100 text-slate-600 font-semibold text-[9px] px-2 py-1 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 transition-all disabled:opacity-50"
                        >
                          Descartar
                        </button>
                      </div>
                    </div>
                  );
                })()}

                {/* Resumen Candidatos Aberturas */}
                {!hideAiElements && openingCandidates.length > 0 && (() => {
                  const selCount = openingCandidates.filter((c) => selectedCandidateIds.has(c.id)).length;
                  return (
                    <div className="rounded-lg bg-amber-50/50 border border-amber-100 p-2 space-y-1.5 dark:bg-amber-950/20 dark:border-amber-900/50">
                      <div className="flex items-center justify-between text-[10px]">
                        <span className="font-bold text-amber-700 dark:text-amber-400">
                          Aberturas AI ({selCount}/{openingCandidates.length})
                        </span>
                      </div>
                      <div className="flex gap-1.5">
                        <button
                          type="button"
                          onClick={confirmCandidateOpenings}
                          disabled={bulkBusy}
                          className="flex-1 rounded bg-amber-600 hover:bg-amber-500 text-white font-semibold text-[9px] py-1 transition-all disabled:opacity-50"
                        >
                          Aceptar
                        </button>
                        <button
                          type="button"
                          onClick={() => discardCandidates("opening")}
                          disabled={bulkBusy}
                          className="rounded border border-slate-300 hover:bg-slate-100 text-slate-600 font-semibold text-[9px] px-2 py-1 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 transition-all disabled:opacity-50"
                        >
                          Descartar
                        </button>
                      </div>
                    </div>
                  );
                })()}
              </div>
            )}
          </div>

          {/* Barra de acciones bulk */}
          {selectedIds.size > 0 && (
            <div className="mb-2 flex items-center justify-between gap-1 rounded-lg border border-brand/30 bg-sky-50/60 px-2 py-1.5 text-xs dark:border-sky-800 dark:bg-sky-950/30">
              <span className="font-semibold text-brand dark:text-sky-300">
                {selectedIds.size} seleccionado{selectedIds.size === 1 ? "" : "s"}
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setBulkAssignOpen(true)}
                  className="rounded px-1.5 py-0.5 text-slate-600 hover:bg-white dark:text-slate-300 dark:hover:bg-slate-800"
                  title="Asignar el mismo material a todos los seleccionados"
                >
                  Asignar
                </button>
                <button
                  type="button"
                  onClick={() => setScaleModalOpen(true)}
                  className="rounded px-1.5 py-0.5 text-slate-600 hover:bg-white dark:text-slate-300 dark:hover:bg-slate-800"
                  title="Escalar dimensiones de los elementos seleccionados"
                >
                  Escalar
                </button>
                <button
                  type="button"
                  onClick={() => requestDelete([...selectedIds])}
                  className="rounded px-1.5 py-0.5 text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40"
                  title="Eliminar seleccionados"
                >
                  Eliminar
                </button>
                <button
                  type="button"
                  onClick={clearSelection}
                  className="rounded px-1.5 py-0.5 text-slate-500 hover:bg-white dark:text-slate-400 dark:hover:bg-slate-800"
                  title="Limpiar selección"
                  aria-label="Limpiar selección"
                >
                  ×
                </button>
              </div>
            </div>
          )}

          {elementsLoading ? (
            <p className="py-4 text-center text-xs text-slate-400">Cargando elementos...</p>
          ) : displayElements.length === 0 ? (
            <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-slate-300 px-3 py-6 text-center text-xs text-slate-400 dark:border-slate-700 dark:text-slate-500">
              <div>
                <p className="font-medium">Sin elementos en esta página</p>
                <p className="mt-1 font-normal text-slate-500 dark:text-slate-400">
                  {hideAiElements ? "Se ocultaron los elementos de la IA." : "Activá Muro, Recinto o Abertura."}
                </p>
              </div>
            </div>
          ) : (
            <ul className="max-h-[480px] flex-1 space-y-1.5 overflow-y-auto pr-1">
              {displayElements.map((el, idx) => {
                const selected = selectedIds.has(el.id);
                const editing = editingId === el.id;
                const hovered = hoveredId === el.id;
                return (
                  <li
                    key={el.id}
                    onMouseEnter={() => setHoveredId(el.id)}
                    onMouseLeave={() => setHoveredId(null)}
                    className={`rounded-md border text-xs transition ${
                      selected
                        ? "border-brand bg-sky-50/70 dark:border-sky-500 dark:bg-sky-950/40"
                        : hovered || editing
                          ? "border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50"
                          : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
                    }`}
                  >
                    <div className="flex items-center gap-2 px-2 py-1.5">
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={() => toggleSelected(el.id, true)}
                        onClick={(e) => e.stopPropagation()}
                        className="h-3.5 w-3.5 shrink-0 rounded border-slate-300 text-brand focus:ring-1 focus:ring-brand dark:border-slate-600 dark:bg-slate-900"
                        aria-label="Seleccionar elemento"
                      />
                      <button
                        type="button"
                        onClick={() => setEditingId(editing ? null : el.id)}
                        className="flex min-w-0 flex-1 items-center gap-2 text-left"
                        aria-expanded={editing}
                      >
                        <span
                          className="h-2.5 w-2.5 shrink-0 rounded-sm"
                          style={{
                            backgroundColor:
                              el.type === "wall" ? "#16A34A"
                              : el.type === "room" ? "#2563EB"
                              : el.type === "beam" ? "#7C3AED"
                              : el.type === "roof" ? "#0D9488"
                              : el.type === "column" ? "#F43F5E"
                              : "#D97706",
                          }}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <p className="truncate font-semibold text-slate-700 dark:text-slate-200">
                              {el.geometry.label ?? labelFor(el.type, idx + 1)}
                            </p>
                            {el.type === "opening" && (
                              <span className="shrink-0 rounded-sm bg-amber-100 px-1.5 py-0 text-[9px] font-semibold uppercase tracking-wide text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                                {OPENING_SUBTYPES.find(
                                  (s) => s.value === (el.geometry.subtype ?? DEFAULT_OPENING_SUBTYPE),
                                )?.label ?? "Puerta"}
                              </span>
                            )}
                          </div>
                          <p className="text-[10px] text-slate-400">
                            {el.type === "wall" && `${el.length_m?.toFixed(2)} m · alt ${(el.height_m ?? 2.8).toFixed(2)} m`}
                            {el.type === "room" && `${el.area_m2?.toFixed(2)} m² · perím ${el.length_m?.toFixed(2)} m`}
                            {el.type === "opening" && `${el.length_m?.toFixed(2)} m ancho · alt ${(el.height_m ?? 2.1).toFixed(2)} m`}
                            {el.type === "beam" && `${el.length_m?.toFixed(2)} m · alt ${(el.height_m ?? 0.40).toFixed(2)} m`}
                            {el.type === "roof" && `${el.area_m2?.toFixed(2)} m²`}
                            {el.type === "column" && `${el.area_m2?.toFixed(2)} m² · alt ${(el.height_m ?? 2.8).toFixed(2)} m`}
                          </p>
                        </div>
                        <ChevronIcon open={editing} />
                      </button>
                      <button
                        type="button"
                        onClick={() => requestDelete([el.id])}
                        title="Eliminar"
                        aria-label="Eliminar elemento"
                        className="shrink-0 rounded p-1 text-slate-400 transition hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40 dark:hover:text-red-400"
                      >
                        <TrashIcon />
                      </button>
                    </div>
                    {editing && (
                      <>
                        <InlineEditForm
                          element={el}
                          defaultLabel={el.geometry.label ?? labelFor(el.type, idx + 1)}
                          pageScale={currentPageScale}
                          onSave={(patch) => updateElementInline(el.id, patch)}
                          onAutoAdjust={autoAdjustRoomToWalls}
                        />
                        <ElementAssembliesBlock
                          element={el}
                          assembliesList={assembliesList}
                          onAssign={(assemblyId) => assignAssemblyToElement(el.id, assemblyId)}
                          onRemove={(assemblyId) => removeAssemblyFromElement(el.id, assemblyId)}
                        />
                      </>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </aside>

        {/* CANVAS CENTRAL */}
        <div className="min-w-0 flex-1">

          {/* Controles de página */}
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-sm">
            {activePages.length > 1 ? (
              <>
                <div className="flex items-center gap-1">
                  <PageButton
                    onClick={goToFirstActive}
                    disabled={page === activePages[0]}
                    title="Primera página"
                  >
                    «
                  </PageButton>
                  <PageButton
                    onClick={goToPrevActive}
                    disabled={page === activePages[0]}
                    title="Anterior"
                  >
                    ‹ Anterior
                  </PageButton>
                </div>
                <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                  <span>Página</span>
                  <input
                    type="number"
                    min={1}
                    max={totalPages}
                    value={page}
                    onChange={(e) => goToPage(Number(e.target.value) || 1)}
                    className="w-16 rounded border border-slate-300 px-2 py-1 text-center dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
                  />
                  <span>de {totalPages}</span>
                  <PageOverrideToggle
                    rec={currentRec}
                    busy={overridingPage}
                    onChange={(next) => applyPageOverride(page, next)}
                  />
                  <button
                    type="button"
                    onClick={() => setConfirmDeletePage(page)}
                    title="Ocultar esta página de la vista"
                    aria-label="Eliminar página"
                    className="ml-2 flex items-center gap-1 rounded border border-red-200 bg-red-50 px-2 py-1 text-xs font-semibold text-red-600 hover:bg-red-100 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-400 dark:hover:bg-red-950/60"
                  >
                    <TrashIcon />
                    Eliminar
                  </button>
                </div>
                <div className="flex items-center gap-1">
                  <PageButton
                    onClick={goToNextActive}
                    disabled={page === activePages[activePages.length - 1]}
                    title="Siguiente"
                  >
                    Siguiente ›
                  </PageButton>
                  <PageButton
                    onClick={goToLastActive}
                    disabled={page === activePages[activePages.length - 1]}
                    title="Última página"
                  >
                    »
                  </PageButton>
                </div>
              </>
            ) : (
              <div className="flex w-full items-center justify-between gap-2 text-slate-600 dark:text-slate-300">
                <span>
                  Página {page} de {totalPages}
                  {activePages.length === 1 && totalPages > 1 && (
                    <span className="ml-2 text-xs text-slate-400">
                      (única página activa)
                    </span>
                  )}
                </span>
                {totalPages > 1 && activePages.length > 1 && (
                  <button
                    type="button"
                    onClick={() => setConfirmDeletePage(page)}
                    title="Ocultar esta página de la vista"
                    className="flex items-center gap-1 rounded border border-red-200 bg-red-50 px-2 py-1 text-xs font-semibold text-red-600 hover:bg-red-100 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-400 dark:hover:bg-red-950/60"
                  >
                    <TrashIcon />
                    Eliminar página
                  </button>
                )}
              </div>
            )}
          </div>


          {calibrating && (
            <div className="mb-2 flex items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs dark:border-amber-700 dark:bg-amber-950/40">
              <span className="text-amber-800 dark:text-amber-200">
                {calPoints.length === 0
                  ? "Hacé clic en el primer punto de una cota conocida."
                  : calPoints.length === 1
                    ? "Ahora hacé clic en el segundo punto."
                    : "Ingresá la distancia real entre los dos puntos."}
              </span>
              <button
                type="button"
                onClick={cancelCalibration}
                className="rounded border border-amber-400 px-2 py-1 text-amber-700 hover:bg-amber-100 dark:border-amber-600 dark:text-amber-300 dark:hover:bg-amber-900"
              >
                Cancelar
              </button>
            </div>
          )}

          {!currentPageScale && !calibrating && (
            <div className="mb-2 flex items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs dark:border-amber-700 dark:bg-amber-950/40">
              <span className="text-amber-800 dark:text-amber-200">
                Esta página no está calibrada. Calibrala para habilitar el dibujo.
              </span>
              <button
                type="button"
                onClick={startCalibration}
                className="rounded bg-amber-500 px-2.5 py-1 text-white hover:bg-amber-600"
              >
                Calibrar
              </button>
            </div>
          )}

          {/* Banner de instrucciones de dibujo */}
          {!calibrating && tool !== "pan" && !drawingDisabled && (
            <div className="mb-2 flex items-center justify-between gap-3 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs dark:border-sky-800 dark:bg-sky-950/40">
              <span className="text-sky-800 dark:text-sky-200">
                {tool === "wall" && (
                  activePoints.length === 0
                    ? "Muro · clic en el punto inicial."
                    : "Clic en el punto final."
                )}
                {tool === "opening" && (
                  activePoints.length === 0
                    ? "Abertura · clic en un extremo."
                    : "Clic en el otro extremo."
                )}
                {tool === "room" && (
                  activePoints.length === 0
                    ? "Recinto · clic para colocar el primer vértice."
                    : activePoints.length < 3
                      ? `Colocá al menos ${3 - activePoints.length} vértice${3 - activePoints.length === 1 ? "" : "s"} más.`
                      : isClosingRoom
                        ? "Clic para cerrar el polígono."
                        : "Más clics para agregar vértices · Enter o doble-clic para cerrar."
                )}
              </span>

              <span className="text-sky-600 dark:text-sky-300">
                Esc cancela · Ctrl+Z deshace
              </span>
            </div>
          )}

          {drawError && (
            <div className="mb-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
              {drawError}
            </div>
          )}

          {/* Canvas + barra flotante */}
          <div className="relative">
            <div
              ref={containerRef}
              onMouseDown={show3D ? undefined : onMouseDown}
              onMouseMove={show3D ? undefined : onMouseMove}
              onMouseUp={show3D ? undefined : onMouseUp}
              onMouseLeave={show3D ? undefined : onMouseLeave}
              onDoubleClick={show3D ? undefined : onDoubleClick}
              onContextMenu={(e) => e.preventDefault()}
              onClick={show3D ? undefined : (e) => {
                if (!hasMovedDuringDrag.current) {
                  setSelectedIds(new Set());
                }
              }}
              className="relative overflow-hidden rounded-xl border border-slate-200 bg-slate-100 dark:border-slate-700 dark:bg-slate-950"
              style={{ height, cursor: show3D ? "default" : cursor }}
            >
              {show3D ? (
                <Plan3DViewer
                  elements={visibleElements}
                  scale={currentPageScale ?? 100}
                  page={page}
                  onClose={() => setShow3D(false)}
                  onUpdateElement={updateElementInline}
                />
              ) : (
                <>
              {loading && (
                <div className="flex h-full items-center justify-center text-sm text-slate-500 dark:text-slate-400">
                  Procesando página {page}...
                </div>
              )}
              {error && !loading && (
                <div className="flex h-full items-center justify-center text-sm text-red-600 dark:text-red-400">
                  {error}
                </div>
              )}
              {imgUrl && (
                <img
                  src={imgUrl}
                  alt={`Página ${page}`}
                  onLoad={onImgLoad}
                  draggable={false}
                  style={{
                    position: "absolute",
                    left: 0,
                    top: 0,
                    transform: `translate(${pos.x}px, ${pos.y}px) scale(${scale})`,
                    transformOrigin: "0 0",
                    maxWidth: "none",
                    userSelect: "none",
                    pointerEvents: "none",
                    visibility: natural ? "visible" : "hidden",
                  }}
                />
              )}

              {/* Overlay SVG: elementos + preview + calibración */}
              {natural && (
                <svg className="pointer-events-none absolute inset-0 h-full w-full">
                  <defs>
                    <filter id="shadow-glow" x="-20%" y="-20%" width="140%" height="140%">
                      <feDropShadow dx="0" dy="4" stdDeviation="6" floodColor="rgba(0,0,0,0.25)" />
                    </filter>
                    <filter id="shadow-glow-sm" x="-20%" y="-20%" width="140%" height="140%">
                      <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor="rgba(0,0,0,0.3)" />
                    </filter>
                    <filter id="wall-shadow" x="-50%" y="-50%" width="200%" height="200%">
                      <feGaussianBlur in="SourceAlpha" stdDeviation="1.4" />
                      <feOffset dx="0" dy="1.2" result="off" />
                      <feComponentTransfer><feFuncA type="linear" slope="0.35" /></feComponentTransfer>
                      <feMerge>
                        <feMergeNode />
                        <feMergeNode in="SourceGraphic" />
                      </feMerge>
                    </filter>
                    <style>{`
                      @keyframes scalistai-pulse { 0%,100% { opacity: 0.55; } 50% { opacity: 1; } }
                      @keyframes scalistai-dash { to { stroke-dashoffset: -24; } }
                      .scalistai-pulse { animation: scalistai-pulse 1.6s ease-in-out infinite; }
                      .scalistai-dash { animation: scalistai-dash 1.4s linear infinite; }
                    `}</style>
                  </defs>
                  <g
                    transform={`translate(${pos.x}, ${pos.y}) scale(${scale})`}
                  >
                    {/* Recintos (atrás) */}
                    {displayElements
                      .filter((el) => el.type === "room")
                      .map((el) => {
                        const pts = chunkPoints(el.geometry.points);
                        const ptsStr = pts.map((p) => `${p.x},${p.y}`).join(" ");
                        const hovered = hoveredId === el.id;
                        const sel = selectedIds.has(el.id);
                        
                        // Plan0 style colors
                        const fillColor = sel ? "rgba(192, 232, 255, 0.45)" : hovered ? "rgba(192, 232, 255, 0.35)" : "rgba(192, 232, 255, 0.25)";
                        const strokeColor = sel ? "#2563EB" : hovered ? "#3B82F6" : "#60A5FA";
                        
                        const centroid = calculatePolygonCentroid(pts);
                        const labelText = (el.geometry.label || "Recinto").toUpperCase();
                        const areaText = el.area_m2 ? `${el.area_m2.toFixed(1)} m²` : "";
                        const pillText = areaText ? `${labelText} · ${areaText}` : labelText;
                        // Largo visual del pill — basado en caracteres aproximados
                        const pillW = pillText.length * 6.6 + 22;

                        return (
                          <g key={el.id} style={{ transition: "all 0.2s ease" }}>
                            {sel && (
                              <polygon
                                points={ptsStr}
                                fill="rgba(37, 99, 235, 0.1)"
                                className="pointer-events-none"
                              />
                            )}
                            <polygon
                              points={ptsStr}
                              fill={fillColor}
                              stroke={strokeColor}
                              strokeWidth={(sel || hovered ? 3 : 2) / scale}
                              strokeLinejoin="round"
                              filter={sel || hovered ? "url(#shadow-glow)" : "none"}
                              className={`pointer-events-auto cursor-pointer transition-all duration-200 ${draggingVertex ? "pointer-events-none" : ""}`}
                              onMouseEnter={() => {
                                if (!draggingVertex) setHoveredId(el.id);
                              }}
                              onMouseLeave={() => {
                                if (!draggingVertex) setHoveredId(null);
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleSelected(el.id, e.shiftKey || e.metaKey || e.ctrlKey);
                              }}
                            />
                            {/* Pill Label — limpio, alta contraste, tipografía tracked */}
                            <g
                              transform={`translate(${centroid.x}, ${centroid.y}) scale(${1 / scale})`}
                              className="pointer-events-none transition-all duration-200"
                            >
                              {/* Outline blanco sutil para contraste sobre cualquier fondo */}
                              <rect
                                x={-pillW / 2 - 1}
                                y={-13}
                                width={pillW + 2}
                                height={26}
                                rx={13}
                                fill="#FFFFFF"
                                opacity={0.35}
                              />
                              <rect
                                x={-pillW / 2}
                                y={-12}
                                width={pillW}
                                height={24}
                                rx={12}
                                fill={sel ? "#1D4ED8" : "#0F172A"}
                                opacity={sel || hovered ? 0.96 : 0.82}
                                filter="url(#shadow-glow-sm)"
                              />
                              <text
                                x={0}
                                y={4}
                                fill="#FFFFFF"
                                fontSize={10.5}
                                fontWeight="700"
                                textAnchor="middle"
                                style={{ letterSpacing: "0.04em" }}
                                className="font-sans"
                              >
                                {pillText}
                              </text>
                            </g>
                          </g>
                        );
                      })}

                    {/* Techos */}
                    {displayElements
                      .filter((el) => el.type === "roof")
                      .map((el) => {
                        const pts = chunkPoints(el.geometry.points);
                        const ptsStr = pts.map((p) => `${p.x},${p.y}`).join(" ");
                        const hovered = hoveredId === el.id;
                        const sel = selectedIds.has(el.id);
                        
                        const fillColor = sel ? "rgba(20, 184, 166, 0.45)" : hovered ? "rgba(20, 184, 166, 0.35)" : "rgba(20, 184, 166, 0.25)";
                        const strokeColor = sel ? "#0D9488" : hovered ? "#14B8A6" : "#2DD4BF";
                        
                        const centroid = calculatePolygonCentroid(pts);
                        const labelText = (el.geometry.label || "Techo").toUpperCase();
                        const areaText = el.area_m2 ? `${el.area_m2.toFixed(1)} m²` : "";
                        const pillText = areaText ? `${labelText} · ${areaText}` : labelText;
                        const pillW = pillText.length * 6.6 + 22;

                        return (
                          <g key={el.id} style={{ transition: "all 0.2s ease" }}>
                            {sel && (
                              <polygon
                                points={ptsStr}
                                fill="rgba(13, 148, 136, 0.1)"
                                className="pointer-events-none"
                              />
                            )}
                            <polygon
                              points={ptsStr}
                              fill={fillColor}
                              stroke={strokeColor}
                              strokeWidth={(sel || hovered ? 3 : 2) / scale}
                              strokeLinejoin="round"
                              filter={sel || hovered ? "url(#shadow-glow)" : "none"}
                              className={`pointer-events-auto cursor-pointer transition-all duration-200 ${draggingVertex ? "pointer-events-none" : ""}`}
                              onMouseEnter={() => {
                                if (!draggingVertex) setHoveredId(el.id);
                              }}
                              onMouseLeave={() => {
                                if (!draggingVertex) setHoveredId(null);
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleSelected(el.id, e.shiftKey || e.metaKey || e.ctrlKey);
                              }}
                            />
                            <g
                              transform={`translate(${centroid.x}, ${centroid.y}) scale(${1 / scale})`}
                              className="pointer-events-none transition-all duration-200"
                            >
                              <rect
                                x={-pillW / 2 - 1}
                                y={-13}
                                width={pillW + 2}
                                height={26}
                                rx={13}
                                fill="#FFFFFF"
                                opacity={0.35}
                              />
                              <rect
                                x={-pillW / 2}
                                y={-12}
                                width={pillW}
                                height={24}
                                rx={12}
                                fill={sel ? "#0F766E" : "#115E59"}
                                opacity={sel || hovered ? 0.96 : 0.82}
                                filter="url(#shadow-glow-sm)"
                              />
                              <text
                                x={0}
                                y={4}
                                fill="#FFFFFF"
                                fontSize={10.5}
                                fontWeight="700"
                                textAnchor="middle"
                                style={{ letterSpacing: "0.04em" }}
                                className="font-sans"
                              >
                                {pillText}
                              </text>
                            </g>
                          </g>
                        );
                      })}

                    {/* Columnas */}
                    {displayElements
                      .filter((el) => el.type === "column")
                      .map((el) => {
                        const isPointCol = el.geometry.points.length === 2;
                        let cx = 0;
                        let cy = 0;
                        let r = 10;
                        let ptsStr = "";
                        let centroid = { x: 0, y: 0 };

                        if (isPointCol) {
                          cx = el.geometry.points[0];
                          cy = el.geometry.points[1];
                          r = 0.15 * (currentPageScale || 60);
                          centroid = { x: cx, y: cy };
                        } else {
                          const pts = chunkPoints(el.geometry.points);
                          ptsStr = pts.map((p) => `${p.x},${p.y}`).join(" ");
                          centroid = calculatePolygonCentroid(pts);
                        }

                        const hovered = hoveredId === el.id;
                        const sel = selectedIds.has(el.id);
                        
                        const fillColor = sel ? "rgba(244, 63, 94, 0.45)" : hovered ? "rgba(244, 63, 94, 0.35)" : "rgba(244, 63, 94, 0.25)";
                        const strokeColor = sel ? "#E11D48" : hovered ? "#F43F5E" : "#FB7185";
                        
                        const labelText = (el.geometry.label || "Columna").toUpperCase();
                        const areaText = el.area_m2 ? `${el.area_m2.toFixed(1)} m²` : "";
                        const pillText = areaText ? `${labelText} · ${areaText}` : labelText;
                        const pillW = pillText.length * 6.6 + 22;

                        return (
                          <g key={el.id} style={{ transition: "all 0.2s ease" }}>
                            {isPointCol ? (
                              <>
                                {sel && (
                                  <circle
                                    cx={cx}
                                    cy={cy}
                                    r={r + 3}
                                    fill="rgba(225, 29, 72, 0.1)"
                                    className="pointer-events-none"
                                  />
                                )}
                                <circle
                                  cx={cx}
                                  cy={cy}
                                  r={r}
                                  fill={fillColor}
                                  stroke={strokeColor}
                                  strokeWidth={(sel || hovered ? 3 : 2) / scale}
                                  filter={sel || hovered ? "url(#shadow-glow)" : "none"}
                                  className={`pointer-events-auto cursor-pointer transition-all duration-200 ${draggingVertex ? "pointer-events-none" : ""}`}
                                  onMouseEnter={() => {
                                    if (!draggingVertex) setHoveredId(el.id);
                                  }}
                                  onMouseLeave={() => {
                                    if (!draggingVertex) setHoveredId(null);
                                  }}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    toggleSelected(el.id, e.shiftKey || e.metaKey || e.ctrlKey);
                                  }}
                                />
                              </>
                            ) : (
                              <>
                                {sel && (
                                  <polygon
                                    points={ptsStr}
                                    fill="rgba(225, 29, 72, 0.1)"
                                    className="pointer-events-none"
                                  />
                                )}
                                <polygon
                                  points={ptsStr}
                                  fill={fillColor}
                                  stroke={strokeColor}
                                  strokeWidth={(sel || hovered ? 3 : 2) / scale}
                                  strokeLinejoin="round"
                                  filter={sel || hovered ? "url(#shadow-glow)" : "none"}
                                  className={`pointer-events-auto cursor-pointer transition-all duration-200 ${draggingVertex ? "pointer-events-none" : ""}`}
                                  onMouseEnter={() => {
                                    if (!draggingVertex) setHoveredId(el.id);
                                  }}
                                  onMouseLeave={() => {
                                    if (!draggingVertex) setHoveredId(null);
                                  }}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    toggleSelected(el.id, e.shiftKey || e.metaKey || e.ctrlKey);
                                  }}
                                />
                              </>
                            )}
                            <g
                              transform={`translate(${centroid.x}, ${centroid.y}) scale(${1 / scale})`}
                              className="pointer-events-none transition-all duration-200"
                            >
                              <rect
                                x={-pillW / 2 - 1}
                                y={-13}
                                width={pillW + 2}
                                height={26}
                                rx={13}
                                fill="#FFFFFF"
                                opacity={0.35}
                              />
                              <rect
                                x={-pillW / 2}
                                y={-12}
                                width={pillW}
                                height={24}
                                rx={12}
                                fill={sel ? "#BE123C" : "#9F1239"}
                                opacity={sel || hovered ? 0.96 : 0.82}
                                filter="url(#shadow-glow-sm)"
                              />
                              <text
                                x={0}
                                y={4}
                                fill="#FFFFFF"
                                fontSize={10.5}
                                fontWeight="700"
                                textAnchor="middle"
                                style={{ letterSpacing: "0.04em" }}
                                className="font-sans"
                              >
                                {pillText}
                              </text>
                            </g>
                          </g>
                        );
                      })}

                    {/* Candidatos Recintos */}
                    {!hideAiElements && roomCandidates.map((c) => {
                      const pts = chunkPoints(c.geometry.points);
                      const ptsStr = pts.map((p) => `${p.x},${p.y}`).join(" ");
                      const selected = selectedCandidateIds.has(c.id);
                      return (
                        <polygon
                          key={c.id}
                          points={ptsStr}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleCandidateSelected(c.id, e.shiftKey || e.metaKey || e.ctrlKey);
                          }}
                          className={`pointer-events-auto cursor-pointer transition-all duration-200 ${draggingVertex ? "pointer-events-none" : ""}`}
                          fill={selected ? "rgba(59, 130, 246, 0.25)" : "rgba(96, 165, 250, 0.15)"}
                          stroke={selected ? "#2563EB" : "#3B82F6"}
                          strokeWidth={(selected ? 2.5 : 2) / scale}
                          strokeDasharray={`${8 / scale} ${4 / scale}`}
                          strokeLinejoin="round"
                          opacity={1}
                        />
                      );
                    })}

                    {/* Muros */}
                    {displayElements
                      .filter((el) => el.type === "wall")
                      .map((el) => {
                        const [x1, y1, x2, y2] = el.geometry.points;
                        const hovered = hoveredId === el.id;
                        const sel = selectedIds.has(el.id);
                        // Espesor visual del muro: 8px base, +1 hover, halo de selección detrás
                        const baseW = 8 / scale;
                        const hoverW = 9.5 / scale;
                        const w = hovered ? hoverW : baseW;
                        return (
                          <g key={el.id} style={{ transition: "all 0.2s ease" }}>
                            {sel && (
                              <line
                                x1={x1}
                                y1={y1}
                                x2={x2}
                                y2={y2}
                                stroke="#3B82F6"
                                strokeWidth={(8 / scale) + (12 / scale)}
                                strokeLinecap="round"
                                opacity={0.35}
                              />
                            )}
                            <line
                              x1={x1}
                              y1={y1}
                              x2={x2}
                              y2={y2}
                              stroke="transparent"
                              strokeWidth={34 / scale}
                              className={`pointer-events-auto cursor-pointer ${draggingVertex ? "pointer-events-none" : ""}`}
                              onMouseEnter={() => {
                                if (!draggingVertex) setHoveredId(el.id);
                              }}
                              onMouseLeave={() => {
                                if (!draggingVertex) setHoveredId(null);
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleSelected(el.id, e.shiftKey || e.metaKey || e.ctrlKey);
                              }}
                            />
                            <line
                              x1={x1}
                              y1={y1}
                              x2={x2}
                              y2={y2}
                              stroke={hovered ? "#334155" : "#1E293B"}
                              strokeWidth={(hovered ? 10 : 8) / scale}
                              strokeLinecap="round"
                              opacity={1}
                              className="pointer-events-none transition-colors duration-200"
                            />
                          </g>
                        );
                      })}

                    {/* Vigas */}
                    {displayElements
                      .filter((el) => el.type === "beam")
                      .map((el) => {
                        const [x1, y1, x2, y2] = el.geometry.points;
                        const hovered = hoveredId === el.id;
                        const sel = selectedIds.has(el.id);
                        const baseW = 8 / scale;
                        const hoverW = 9.5 / scale;
                        const w = hovered ? hoverW : baseW;
                        return (
                          <g key={el.id} style={{ transition: "all 0.2s ease" }}>
                            {sel && (
                              <line
                                x1={x1}
                                y1={y1}
                                x2={x2}
                                y2={y2}
                                stroke="#3B82F6"
                                strokeWidth={(8 / scale) + (12 / scale)}
                                strokeLinecap="round"
                                opacity={0.35}
                              />
                            )}
                            <line
                              x1={x1}
                              y1={y1}
                              x2={x2}
                              y2={y2}
                              stroke="transparent"
                              strokeWidth={34 / scale}
                              className={`pointer-events-auto cursor-pointer ${draggingVertex ? "pointer-events-none" : ""}`}
                              onMouseEnter={() => {
                                if (!draggingVertex) setHoveredId(el.id);
                              }}
                              onMouseLeave={() => {
                                if (!draggingVertex) setHoveredId(null);
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleSelected(el.id, e.shiftKey || e.metaKey || e.ctrlKey);
                              }}
                            />
                            <line
                              x1={x1}
                              y1={y1}
                              x2={x2}
                              y2={y2}
                              stroke={hovered ? "#6D28D9" : "#7C3AED"}
                              strokeWidth={w}
                              strokeLinecap="round"
                              opacity={1}
                              className="pointer-events-none transition-colors duration-200"
                            />
                          </g>
                        );
                      })}

                    {/* Riostras */}
                    {displayElements
                      .filter((el) => el.type === "riostra")
                      .map((el) => {
                        const [x1, y1, x2, y2] = el.geometry.points;
                        const hovered = hoveredId === el.id;
                        const sel = selectedIds.has(el.id);
                        const baseW = 8 / scale;
                        const hoverW = 9.5 / scale;
                        const w = hovered ? hoverW : baseW;
                        return (
                          <g key={el.id} style={{ transition: "all 0.2s ease" }}>
                            {sel && (
                              <line
                                x1={x1}
                                y1={y1}
                                x2={x2}
                                y2={y2}
                                stroke="#F97316"
                                strokeWidth={(8 / scale) + (12 / scale)}
                                strokeLinecap="round"
                                opacity={0.35}
                              />
                            )}
                            <line
                              x1={x1}
                              y1={y1}
                              x2={x2}
                              y2={y2}
                              stroke="transparent"
                              strokeWidth={34 / scale}
                              className={`pointer-events-auto cursor-pointer ${draggingVertex ? "pointer-events-none" : ""}`}
                              onMouseEnter={() => {
                                if (!draggingVertex) setHoveredId(el.id);
                              }}
                              onMouseLeave={() => {
                                if (!draggingVertex) setHoveredId(null);
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleSelected(el.id, e.shiftKey || e.metaKey || e.ctrlKey);
                              }}
                            />
                            <line
                              x1={x1}
                              y1={y1}
                              x2={x2}
                              y2={y2}
                              stroke={hovered ? "#EA580C" : "#F97316"}
                              strokeWidth={w}
                              strokeLinecap="round"
                              opacity={1}
                              className="pointer-events-none transition-colors duration-200"
                            />
                          </g>
                        );
                      })}

                    {/* Cloacas */}
                    {displayElements
                      .filter((el) => el.type === "cloaca")
                      .map((el) => {
                        const pts = el.geometry.points;
                        const hovered = hoveredId === el.id;
                        const sel = selectedIds.has(el.id);
                        const baseW = 6 / scale;
                        const hoverW = 7.5 / scale;
                        const w = hovered ? hoverW : baseW;
                        const ptsStr = pts.reduce((acc: string, val: number, i: number) => acc + val + (i % 2 === 0 ? "," : " "), "").trim();
                        return (
                          <g key={el.id} style={{ transition: "all 0.2s ease" }}>
                            {sel && (
                              <polyline
                                points={ptsStr}
                                fill="none"
                                stroke="#15803D"
                                strokeWidth={(6 / scale) + (12 / scale)}
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                opacity={0.35}
                              />
                            )}
                            <polyline
                              points={ptsStr}
                              fill="none"
                              stroke="transparent"
                              strokeWidth={34 / scale}
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              className={`pointer-events-auto cursor-pointer ${draggingVertex ? "pointer-events-none" : ""}`}
                              onMouseEnter={() => {
                                if (!draggingVertex) setHoveredId(el.id);
                              }}
                              onMouseLeave={() => {
                                if (!draggingVertex) setHoveredId(null);
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleSelected(el.id, e.shiftKey || e.metaKey || e.ctrlKey);
                              }}
                            />
                            <polyline
                              points={ptsStr}
                              fill="none"
                              stroke={hovered ? "#166534" : "#15803D"}
                              strokeWidth={w}
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeDasharray={`${8 / scale} ${6 / scale}`}
                              opacity={1}
                              className="pointer-events-none transition-colors duration-200"
                            />
                          </g>
                        );
                      })}

                    {/* Electricidad */}
                    {displayElements
                      .filter((el) => el.type === "electricidad")
                      .map((el) => {
                        const pts = el.geometry.points;
                        const hovered = hoveredId === el.id;
                        const sel = selectedIds.has(el.id);
                        const baseW = 4 / scale;
                        const hoverW = 5.5 / scale;
                        const w = hovered ? hoverW : baseW;
                        const ptsStr = pts.reduce((acc: string, val: number, i: number) => acc + val + (i % 2 === 0 ? "," : " "), "").trim();
                        return (
                          <g key={el.id} style={{ transition: "all 0.2s ease" }}>
                            {sel && (
                              <polyline
                                points={ptsStr}
                                fill="none"
                                stroke="#EAB308"
                                strokeWidth={(4 / scale) + (12 / scale)}
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                opacity={0.35}
                              />
                            )}
                            <polyline
                              points={ptsStr}
                              fill="none"
                              stroke="transparent"
                              strokeWidth={34 / scale}
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              className={`pointer-events-auto cursor-pointer ${draggingVertex ? "pointer-events-none" : ""}`}
                              onMouseEnter={() => {
                                if (!draggingVertex) setHoveredId(el.id);
                              }}
                              onMouseLeave={() => {
                                if (!draggingVertex) setHoveredId(null);
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleSelected(el.id, e.shiftKey || e.metaKey || e.ctrlKey);
                              }}
                            />
                            <polyline
                              points={ptsStr}
                              fill="none"
                              stroke={hovered ? "#CA8A04" : "#EAB308"}
                              strokeWidth={w}
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              opacity={1}
                              className="pointer-events-none transition-colors duration-200"
                            />
                          </g>
                        );
                      })}

                    {/* Candidatos Muros */}
                    {!hideAiElements && wallCandidates.map((c) => {
                      const pts = c.geometry.points;
                      if (pts.length < 4) return null;
                      const [x1, y1, x2, y2] = pts;
                      const selected = selectedCandidateIds.has(c.id);
                      return (
                        <g
                          key={c.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleCandidateSelected(c.id, e.shiftKey || e.metaKey || e.ctrlKey);
                          }}
                          className={`pointer-events-auto cursor-pointer transition-all duration-200 ${draggingVertex ? "pointer-events-none" : ""}`}
                        >
                          <line
                            x1={x1}
                            y1={y1}
                            x2={x2}
                            y2={y2}
                            stroke="transparent"
                            strokeWidth={24 / scale}
                          />
                          <line
                            x1={x1}
                            y1={y1}
                            x2={x2}
                            y2={y2}
                            stroke={selected ? "#1E293B" : "#64748B"}
                            strokeWidth={(selected ? 8 : 5.5) / scale}
                            strokeLinecap="round"
                            strokeDasharray={`${10 / scale} ${6 / scale}`}
                            opacity={1}
                          />
                        </g>
                      );
                    })}

                    {/* Aberturas — símbolos arquitectónicos según subtipo */}
                    {displayElements
                      .filter((el) => el.type === "opening")
                      .map((el) => {
                        const [x1, y1, x2, y2] = el.geometry.points;
                        const hovered = hoveredId === el.id;
                        const sel = selectedIds.has(el.id);
                        const subtype = (el.geometry.subtype || "door").toLowerCase();
                        const isWindow = subtype.includes("window") || subtype.includes("ventana");
                        const isSliding = subtype.includes("sliding") || subtype.includes("corrediza");

                        const dx = x2 - x1;
                        const dy = y2 - y1;
                        const L = Math.hypot(dx, dy);
                        if (L < 0.01) return null;
                        const ux = dx / L;
                        const uy = dy / L;
                        // Perpendicular hacia donde se dibuja el barrido / espesor
                        const nx = -uy;
                        const ny = ux;

                        // Paleta: ámbar para puertas, sky-blue para ventanas
                        const baseColor = isWindow ? "#0EA5E9" : "#D97706";
                        const hotColor = isWindow ? "#0284C7" : "#B45309";
                        const color = hovered ? hotColor : baseColor;
                        const sw = (hovered ? 2.4 : 2.0) / scale;
                        const off = 3.5 / scale; // separación de jambas

                        // Endpoint del barrido (puerta abierta 90°)
                        const swingX = x1 + nx * L;
                        const swingY = y1 + ny * L;

                        return (
                          <g key={el.id} style={{ transition: "all 0.2s ease" }}>
                            {/* Halo de selección */}
                            {sel && (
                              <line
                                x1={x1}
                                y1={y1}
                                x2={x2}
                                y2={y2}
                                stroke={baseColor}
                                strokeWidth={16 / scale}
                                strokeLinecap="round"
                                opacity={0.22}
                              />
                            )}
                            {/* Hit area invisible */}
                            <line
                              x1={x1}
                              y1={y1}
                              x2={x2}
                              y2={y2}
                              stroke="transparent"
                              strokeWidth={28 / scale}
                              className={`pointer-events-auto cursor-pointer ${draggingVertex ? "pointer-events-none" : ""}`}
                              onMouseEnter={() => {
                                if (!draggingVertex) setHoveredId(el.id);
                              }}
                              onMouseLeave={() => {
                                if (!draggingVertex) setHoveredId(null);
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleSelected(el.id, e.shiftKey || e.metaKey || e.ctrlKey);
                              }}
                            />
                            {/* "Hueco" en el muro — línea blanca gruesa que interrumpe el trazo */}
                            <line
                              x1={x1}
                              y1={y1}
                              x2={x2}
                              y2={y2}
                              stroke="#FFFFFF"
                              strokeWidth={11 / scale}
                              strokeLinecap="butt"
                              className="pointer-events-none"
                            />

                            {isWindow ? (
                              <g className="pointer-events-none">
                                {/* Jamba superior */}
                                <line
                                  x1={x1 + nx * off}
                                  y1={y1 + ny * off}
                                  x2={x2 + nx * off}
                                  y2={y2 + ny * off}
                                  stroke={color}
                                  strokeWidth={sw}
                                  strokeLinecap="round"
                                />
                                {/* Vidrio (línea central, más fina) */}
                                <line
                                  x1={x1}
                                  y1={y1}
                                  x2={x2}
                                  y2={y2}
                                  stroke={color}
                                  strokeWidth={sw * 0.6}
                                  strokeLinecap="round"
                                  opacity={0.85}
                                />
                                {/* Jamba inferior */}
                                <line
                                  x1={x1 - nx * off}
                                  y1={y1 - ny * off}
                                  x2={x2 - nx * off}
                                  y2={y2 - ny * off}
                                  stroke={color}
                                  strokeWidth={sw}
                                  strokeLinecap="round"
                                />
                                {/* Marcas de jamba en extremos */}
                                <line
                                  x1={x1 + nx * (off + 1.5 / scale)}
                                  y1={y1 + ny * (off + 1.5 / scale)}
                                  x2={x1 - nx * (off + 1.5 / scale)}
                                  y2={y1 - ny * (off + 1.5 / scale)}
                                  stroke={color}
                                  strokeWidth={sw}
                                  strokeLinecap="round"
                                />
                                <line
                                  x1={x2 + nx * (off + 1.5 / scale)}
                                  y1={y2 + ny * (off + 1.5 / scale)}
                                  x2={x2 - nx * (off + 1.5 / scale)}
                                  y2={y2 - ny * (off + 1.5 / scale)}
                                  stroke={color}
                                  strokeWidth={sw}
                                  strokeLinecap="round"
                                />
                              </g>
                            ) : isSliding ? (
                              <g className="pointer-events-none">
                                {/* Corrediza: 2 panels desplazados perpendicularmente */}
                                <line
                                  x1={x1 + nx * (off * 0.6)}
                                  y1={y1 + ny * (off * 0.6)}
                                  x2={(x1 + x2) / 2 + nx * (off * 0.6)}
                                  y2={(y1 + y2) / 2 + ny * (off * 0.6)}
                                  stroke={color}
                                  strokeWidth={sw * 1.4}
                                  strokeLinecap="round"
                                />
                                <line
                                  x1={(x1 + x2) / 2 - nx * (off * 0.6)}
                                  y1={(y1 + y2) / 2 - ny * (off * 0.6)}
                                  x2={x2 - nx * (off * 0.6)}
                                  y2={y2 - ny * (off * 0.6)}
                                  stroke={color}
                                  strokeWidth={sw * 1.4}
                                  strokeLinecap="round"
                                />
                                {/* Marcas de jamba */}
                                <line
                                  x1={x1 + nx * off}
                                  y1={y1 + ny * off}
                                  x2={x1 - nx * off}
                                  y2={y1 - ny * off}
                                  stroke={color}
                                  strokeWidth={sw}
                                  strokeLinecap="round"
                                />
                                <line
                                  x1={x2 + nx * off}
                                  y1={y2 + ny * off}
                                  x2={x2 - nx * off}
                                  y2={y2 - ny * off}
                                  stroke={color}
                                  strokeWidth={sw}
                                  strokeLinecap="round"
                                />
                              </g>
                            ) : (
                              <g className="pointer-events-none">
                                {/* Puerta: hoja perpendicular + arco de barrido 90° */}
                                {/* Arco (más sutil) */}
                                <path
                                  d={`M ${x2} ${y2} A ${L} ${L} 0 0 1 ${swingX} ${swingY}`}
                                  fill="none"
                                  stroke={color}
                                  strokeWidth={sw * 0.55}
                                  strokeLinecap="round"
                                  opacity={0.55}
                                />
                                {/* Hoja de puerta */}
                                <line
                                  x1={x1}
                                  y1={y1}
                                  x2={swingX}
                                  y2={swingY}
                                  stroke={color}
                                  strokeWidth={sw * 1.4}
                                  strokeLinecap="round"
                                />
                                {/* Marcas de jamba en cada extremo */}
                                <line
                                  x1={x1 + nx * off}
                                  y1={y1 + ny * off}
                                  x2={x1 - nx * off}
                                  y2={y1 - ny * off}
                                  stroke={color}
                                  strokeWidth={sw}
                                  strokeLinecap="round"
                                />
                                <line
                                  x1={x2 + nx * off}
                                  y1={y2 + ny * off}
                                  x2={x2 - nx * off}
                                  y2={y2 - ny * off}
                                  stroke={color}
                                  strokeWidth={sw}
                                  strokeLinecap="round"
                                />
                              </g>
                            )}
                          </g>
                        );
                      })}

                    {/* Candidatos Aberturas — preview con símbolos arquitectónicos */}
                    {!hideAiElements && openingCandidates.map((c) => {
                      const selected = selectedCandidateIds.has(c.id);
                      const subtype = (c.subtype || "door").toLowerCase();
                      const isWindow = subtype.includes("window") || subtype.includes("ventana");
                      const isSliding = subtype.includes("sliding") || subtype.includes("corrediza");

                      // Computamos endpoints desde cx/cy + orientación + ancho
                      const pxPerM = currentPageScale || 150;
                      const cx = typeof c.cx === "number" ? c.cx : null;
                      const cy = typeof c.cy === "number" ? c.cy : null;
                      const widthM = typeof c.default_width_m === "number" ? c.default_width_m : 0.8;
                      const orientation = (c.orientation || "h").toLowerCase();

                      let x1: number, y1: number, x2: number, y2: number;
                      if (cx != null && cy != null) {
                        const half = (widthM / 2) * pxPerM;
                        if (orientation === "v") {
                          x1 = cx; y1 = cy - half;
                          x2 = cx; y2 = cy + half;
                        } else {
                          x1 = cx - half; y1 = cy;
                          x2 = cx + half; y2 = cy;
                        }
                      } else if (c.bbox && c.bbox.length >= 4) {
                        // Fallback: usar bbox
                        const [bx1, by1, bx2, by2] = c.bbox;
                        const bw = bx2 - bx1;
                        const bh = by2 - by1;
                        if (bw >= bh) {
                          x1 = bx1; y1 = (by1 + by2) / 2;
                          x2 = bx2; y2 = (by1 + by2) / 2;
                        } else {
                          x1 = (bx1 + bx2) / 2; y1 = by1;
                          x2 = (bx1 + bx2) / 2; y2 = by2;
                        }
                      } else {
                        return null;
                      }

                      const dx = x2 - x1;
                      const dy = y2 - y1;
                      const L = Math.hypot(dx, dy);
                      if (L < 0.01) return null;
                      const ux = dx / L;
                      const uy = dy / L;
                      const nx = -uy;
                      const ny = ux;

                      const baseColor = isWindow ? "#0284C7" : "#D97706";
                      const dimColor = isWindow ? "#38BDF8" : "#F59E0B";
                      const color = selected ? baseColor : dimColor;
                      const sw = (selected ? 2.5 : 1.8) / scale;
                      const off = 3.5 / scale;
                      const swingX = x1 + nx * L;
                      const swingY = y1 + ny * L;

                      // Posición del label (un poco arriba del centro perpendicular)
                      const midX = (x1 + x2) / 2 + nx * (L * 0.6);
                      const midY = (y1 + y2) / 2 + ny * (L * 0.6);

                      return (
                        <g
                          key={c.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleCandidateSelected(c.id, e.shiftKey || e.metaKey || e.ctrlKey);
                          }}
                          className={`pointer-events-auto cursor-pointer select-none transition-all duration-200 ${draggingVertex ? "pointer-events-none" : ""}`}
                        >
                          {/* Hit area */}
                          <rect
                            x={Math.min(x1, x2, swingX) - 10 / scale}
                            y={Math.min(y1, y2, swingY) - 10 / scale}
                            width={Math.abs(Math.max(x1, x2, swingX) - Math.min(x1, x2, swingX)) + 20 / scale}
                            height={Math.abs(Math.max(y1, y2, swingY) - Math.min(y1, y2, swingY)) + 20 / scale}
                            fill="transparent"
                          />
                          {/* Hueco en muro */}
                          <line
                            x1={x1}
                            y1={y1}
                            x2={x2}
                            y2={y2}
                            stroke="#FFFFFF"
                            strokeWidth={9 / scale}
                            strokeLinecap="butt"
                            opacity={0.85}
                          />

                          {isWindow ? (
                            <g>
                              <line
                                x1={x1 + nx * off} y1={y1 + ny * off}
                                x2={x2 + nx * off} y2={y2 + ny * off}
                                stroke={color} strokeWidth={sw} strokeLinecap="round"
                                strokeDasharray={`${6 / scale} ${4 / scale}`}
                                className={selected ? "scalistai-dash" : "scalistai-dash scalistai-pulse"}
                              />
                              <line
                                x1={x1 - nx * off} y1={y1 - ny * off}
                                x2={x2 - nx * off} y2={y2 - ny * off}
                                stroke={color} strokeWidth={sw} strokeLinecap="round"
                                strokeDasharray={`${6 / scale} ${4 / scale}`}
                                className={selected ? "scalistai-dash" : "scalistai-dash scalistai-pulse"}
                              />
                            </g>
                          ) : isSliding ? (
                            <g>
                              <line
                                x1={x1 + nx * off * 0.6} y1={y1 + ny * off * 0.6}
                                x2={(x1 + x2) / 2 + nx * off * 0.6} y2={(y1 + y2) / 2 + ny * off * 0.6}
                                stroke={color} strokeWidth={sw * 1.3} strokeLinecap="round"
                                strokeDasharray={`${6 / scale} ${4 / scale}`}
                                className={selected ? "scalistai-dash" : "scalistai-dash scalistai-pulse"}
                              />
                              <line
                                x1={(x1 + x2) / 2 - nx * off * 0.6} y1={(y1 + y2) / 2 - ny * off * 0.6}
                                x2={x2 - nx * off * 0.6} y2={y2 - ny * off * 0.6}
                                stroke={color} strokeWidth={sw * 1.3} strokeLinecap="round"
                                strokeDasharray={`${6 / scale} ${4 / scale}`}
                                className={selected ? "scalistai-dash" : "scalistai-dash scalistai-pulse"}
                              />
                            </g>
                          ) : (
                            <g>
                              <path
                                d={`M ${x2} ${y2} A ${L} ${L} 0 0 1 ${swingX} ${swingY}`}
                                fill="none"
                                stroke={color}
                                strokeWidth={sw * 0.55}
                                opacity={0.6}
                                strokeDasharray={`${4 / scale} ${3 / scale}`}
                                className={selected ? "scalistai-dash" : "scalistai-dash scalistai-pulse"}
                              />
                              <line
                                x1={x1} y1={y1} x2={swingX} y2={swingY}
                                stroke={color} strokeWidth={sw * 1.3} strokeLinecap="round"
                                strokeDasharray={`${6 / scale} ${4 / scale}`}
                                className={selected ? "scalistai-dash" : "scalistai-dash scalistai-pulse"}
                              />
                            </g>
                          )}

                          {/* Label flotante */}
                          {c.label && (
                            <g transform={`translate(${midX}, ${midY}) scale(${1 / scale})`} className="pointer-events-none">
                              <rect
                                x={-c.label.length * 3.2 - 6}
                                y={-8}
                                width={c.label.length * 6.4 + 12}
                                height={16}
                                rx={8}
                                fill={selected ? baseColor : "#475569"}
                                opacity={0.92}
                              />
                              <text
                                x={0}
                                y={3.5}
                                textAnchor="middle"
                                fontSize={10}
                                fontWeight={600}
                                fill="#FFFFFF"
                              >
                                {c.label}
                              </text>
                            </g>
                          )}
                        </g>
                      );
                    })}

                    {/* Preview de dibujo en curso — segmento (wall/opening/beam) */}
                    {(tool === "wall" || tool === "opening" || tool === "beam") &&
                      activePoints.length === 1 &&
                      mousePos && (
                        <line
                          x1={activePoints[0].x}
                          y1={activePoints[0].y}
                          x2={mousePos.x}
                          y2={mousePos.y}
                          stroke={tool === "wall" ? "#16A34A" : tool === "beam" ? "#7C3AED" : "#D97706"}
                          strokeWidth={6 / scale}
                          strokeLinecap="round"
                          strokeDasharray={`${6 / scale} ${4 / scale}`}
                          opacity={0.55}
                        />
                      )}

                     {/* Preview polígono (room/roof) */}
                    {(tool === "room" || tool === "roof") && activePoints.length > 0 && (() => {
                      const pts = mousePos ? [...activePoints, mousePos] : activePoints;
                      const ptsStr = pts.map((p) => `${p.x},${p.y}`).join(" ");
                      const fillColor =
                        tool === "room" ? "rgba(37, 99, 235, 0.15)"
                        : "rgba(13, 148, 136, 0.15)";
                      const strokeColor =
                        tool === "room" ? "#2563EB"
                        : "#0D9488";
                      return (
                        <polygon
                          points={ptsStr}
                          fill={fillColor}
                          stroke={strokeColor}
                          strokeWidth={2 / scale}
                          strokeDasharray={`${6 / scale} ${4 / scale}`}
                        />
                      );
                    })()}

                    {/* Puntos del dibujo activo */}
                    {activePoints.map((p, i) => {
                      const isFirstClosing = i === 0 && isClosingRoom;
                      const color =
                        isFirstClosing ? "#fbbf24"
                        : tool === "wall" ? "#16A34A"
                        : tool === "beam" ? "#7C3AED"
                        : tool === "opening" ? "#D97706"
                        : tool === "room" ? "#2563EB"
                        : tool === "roof" ? "#0D9488"
                        : "#F43F5E";
                      return (
                        <circle
                          key={i}
                          cx={p.x}
                          cy={p.y}
                          r={(isFirstClosing ? 8 : 5) / scale}
                          fill={color}
                          stroke="#ffffff"
                          strokeWidth={1.5 / scale}
                        />
                      );
                    })}

                    {/* Calibración */}
                    {calPoints.length === 2 && (
                      <line
                        x1={calPoints[0].x}
                        y1={calPoints[0].y}
                        x2={calPoints[1].x}
                        y2={calPoints[1].y}
                        stroke="#dc2626"
                        strokeWidth={2 / scale}
                        strokeDasharray={`${6 / scale} ${4 / scale}`}
                      />
                    )}
                    {calPoints.map((p, i) => (
                      <g key={`cal-${i}`}>
                        <circle cx={p.x} cy={p.y} r={6 / scale} fill="#dc2626" />
                        <circle
                          cx={p.x}
                          cy={p.y}
                          r={10 / scale}
                          fill="none"
                          stroke="#dc2626"
                          strokeWidth={1.5 / scale}
                        />
                      </g>
                    ))}

                    {/* Drag Handles for Selected Element */}
                    {selectedElement && (
                      <g>
                        {selectedElement.type === "wall" && (() => {
                          const pts = selectedElement.geometry.points;
                          if (pts.length < 4) return null;
                          const [x1, y1, x2, y2] = pts;
                          return (
                            <>
                              <g
                                className="pointer-events-auto cursor-move select-none"
                                onMouseDown={(e) => startDragVertex(e, selectedElement.id, 0)}
                              >
                                <circle cx={x1} cy={y1} r={22 / scale} fill="transparent" />
                                <circle cx={x1} cy={y1} r={6 / scale} fill="#3B82F6" stroke="#ffffff" strokeWidth={1.5 / scale} className="transition-colors hover:fill-[#2563EB]" />
                              </g>
                              <g
                                className="pointer-events-auto cursor-move select-none"
                                onMouseDown={(e) => startDragVertex(e, selectedElement.id, 2)}
                              >
                                <circle cx={x2} cy={y2} r={22 / scale} fill="transparent" />
                                <circle cx={x2} cy={y2} r={6 / scale} fill="#3B82F6" stroke="#ffffff" strokeWidth={1.5 / scale} className="transition-colors hover:fill-[#2563EB]" />
                              </g>
                            </>
                          );
                        })()}
                        {selectedElement.type === "opening" && (() => {
                          const pts = selectedElement.geometry.points;
                          if (pts.length < 4) return null;
                          const [x1, y1, x2, y2] = pts;
                          return (
                            <>
                              <g
                                className="pointer-events-auto cursor-move select-none"
                                onMouseDown={(e) => startDragVertex(e, selectedElement.id, 0)}
                              >
                                <circle cx={x1} cy={y1} r={22 / scale} fill="transparent" />
                                <circle cx={x1} cy={y1} r={6 / scale} fill="#ea580c" stroke="#ffffff" strokeWidth={1.5 / scale} className="transition-colors hover:fill-[#c2410c]" />
                              </g>
                              <g
                                className="pointer-events-auto cursor-move select-none"
                                onMouseDown={(e) => startDragVertex(e, selectedElement.id, 2)}
                              >
                                <circle cx={x2} cy={y2} r={22 / scale} fill="transparent" />
                                <circle cx={x2} cy={y2} r={6 / scale} fill="#ea580c" stroke="#ffffff" strokeWidth={1.5 / scale} className="transition-colors hover:fill-[#c2410c]" />
                              </g>
                            </>
                          );
                        })()}
                        {selectedElement.type === "room" && (() => {
                          const pts = selectedElement.geometry.points;
                          const handles: React.ReactNode[] = [];
                          const numPoints = pts.length / 2;

                          // 1. Renderizar vertices reales
                          for (let i = 0; i < numPoints; i++) {
                            const x = pts[i * 2];
                            const y = pts[i * 2 + 1];
                            const pointIndex = i * 2;
                            handles.push(
                              <g
                                key={`vertex-${i}`}
                                className="pointer-events-auto cursor-move select-none"
                                onMouseDown={(e) => startDragVertex(e, selectedElement.id, pointIndex)}
                                onDoubleClick={(e) => deleteVertex(e, selectedElement.id, pointIndex)}
                              >
                                <title>Doble clic para eliminar vertice</title>
                                <circle cx={x} cy={y} r={22 / scale} fill="transparent" />
                                <circle cx={x} cy={y} r={6 / scale} fill="#3B82F6" stroke="#ffffff" strokeWidth={1.5 / scale} className="transition-colors hover:fill-[#2563EB]" />
                              </g>
                            );
                          }

                          // 2. Renderizar tiradores intermedios (midpoints) para subdividir segmentos
                          for (let i = 0; i < numPoints; i++) {
                            const next = (i + 1) % numPoints;
                            const x1 = pts[i * 2];
                            const y1 = pts[i * 2 + 1];
                            const x2 = pts[next * 2];
                            const y2 = pts[next * 2 + 1];
                            const mx = (x1 + x2) / 2;
                            const my = (y1 + y2) / 2;
                            const edgeIndex = i;

                            handles.push(
                              <g
                                key={`midpoint-${i}`}
                                className="pointer-events-auto cursor-pointer opacity-60 hover:opacity-100 transition-opacity"
                                onMouseDown={(e) => startDragMidpoint(e, selectedElement.id, edgeIndex, mx, my)}
                              >
                                <title>Arrastra para crear un nuevo vertice</title>
                                <circle cx={mx} cy={my} r={22 / scale} fill="transparent" />
                                <circle cx={mx} cy={my} r={4.5 / scale} fill="#3B82F6" stroke="#ffffff" strokeWidth={1 / scale} />
                              </g>
                            );
                          }

                          return handles;
                        })()}
                      </g>
                    )}
                  </g>
                </svg>
              )}
            </>
          )}
        </div>

            {/* Barra flotante inferior-derecha */}
            {!calibrating && !show3D && (
              <div className="pointer-events-none absolute bottom-3 right-3">
                <div className="pointer-events-auto flex items-center gap-1 rounded-lg border border-slate-200 bg-white p-1 shadow-surface dark:border-slate-700 dark:bg-slate-900">
                  <ToolbarIconButton onClick={resetView} title="Centrar (F)" ariaLabel="Centrar vista">
                    <CenterIcon />
                  </ToolbarIconButton>
                  <ToolbarIconButton onClick={() => zoomAtCenter(1)} title="Acercar (+)" ariaLabel="Acercar">
                    <PlusIcon />
                  </ToolbarIconButton>
                  <ToolbarIconButton onClick={() => zoomAtCenter(-1)} title="Alejar (-)" ariaLabel="Alejar">
                    <MinusIcon />
                  </ToolbarIconButton>

                  <span className="mx-0.5 h-6 w-px bg-slate-200 dark:bg-slate-700" />

                  <ToolbarIconButton
                    onClick={() => setShow3D(true)}
                    disabled={drawingDisabled}
                    title={drawingDisabled ? "Vista 3D — calibrá la página primero" : "Vista 3D"}
                    ariaLabel="Cambiar a vista 3D"
                  >
                    <CubeIcon />
                  </ToolbarIconButton>

                  <span className="mx-0.5 h-6 w-px bg-slate-200 dark:bg-slate-700" />

                  <ToolbarToolButton
                    active={tool === "pan"}
                    onClick={() => selectTool("pan")}
                    title="Mover (H)"
                    ariaLabel="Mano — mover/arrastrar"
                  >
                    <HandIcon />
                  </ToolbarToolButton>

                  <button
                    type="button"
                    onClick={() => setShowDrawingTools((prev) => !prev)}
                    className="flex h-8 w-4 items-center justify-center text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 transition"
                    title={showDrawingTools ? "Ocultar herramientas de dibujo" : "Mostrar herramientas de dibujo"}
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ transform: showDrawingTools ? "rotate(180deg)" : "rotate(0deg)" }}>
                      <path d="m9 18 6-6-6-6" />
                    </svg>
                  </button>

                  {showDrawingTools && (
                    <>
                      <ToolbarToolButton
                        active={tool === "wall"}
                        onClick={() => selectTool("wall")}
                        disabled={drawingDisabled}
                        title="Muro (L)"
                        ariaLabel="Dibujar muro"
                      >
                        <WallIcon />
                      </ToolbarToolButton>
                      <ToolbarToolButton
                        active={tool === "room"}
                        onClick={() => selectTool("room")}
                        disabled={drawingDisabled}
                        title="Recinto (P)"
                        ariaLabel="Dibujar recinto"
                      >
                        <RoomIcon />
                      </ToolbarToolButton>
                      <div className="relative flex">
                        <ToolbarToolButton
                          active={tool === "opening"}
                          onClick={() => selectTool("opening")}
                          disabled={drawingDisabled}
                          title={`Abertura (O) - ${OPENING_SUBTYPES.find(s => s.value === openingSubtype)?.label ?? "Puerta"}`}
                          ariaLabel="Dibujar abertura"
                        >
                          <OpeningIcon />
                        </ToolbarToolButton>
                        <button
                          type="button"
                          disabled={drawingDisabled}
                          onClick={() => setShowOpeningMenu((p) => !p)}
                          className={`flex w-4 items-center justify-center rounded-r-md transition disabled:cursor-not-allowed disabled:opacity-40 hover:bg-slate-100 dark:hover:bg-slate-800 ${tool === "opening" ? "text-sky-600 dark:text-sky-400 bg-sky-50 dark:bg-sky-900/30" : "text-slate-500 dark:text-slate-400"}`}
                          title="Elegir tipo de abertura"
                        >
                          <ChevronIcon open={showOpeningMenu} />
                        </button>
                        {showOpeningMenu && (
                          <div className="absolute top-[110%] left-1/2 mt-1 w-40 -translate-x-1/2 rounded-md border border-slate-200 bg-white p-1.5 shadow-xl dark:border-slate-700 dark:bg-slate-800 z-50">
                            <div className="px-2 py-1 mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">Tipo de Abertura</div>
                            {OPENING_SUBTYPES.map((s) => (
                              <button
                                key={s.value}
                                type="button"
                                onClick={() => {
                                  setOpeningSubtype(s.value);
                                  setShowOpeningMenu(false);
                                  if (tool !== "opening") selectTool("opening");
                                }}
                                className={`flex w-full items-center rounded-sm px-2 py-1.5 text-xs font-medium transition ${openingSubtype === s.value ? "bg-sky-50 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300" : "text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700"}`}
                              >
                                {s.label}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                      <ToolbarToolButton
                        active={tool === "beam"}
                        onClick={() => selectTool("beam")}
                        disabled={drawingDisabled}
                        title="Viga (V)"
                        ariaLabel="Dibujar viga"
                      >
                        <BeamIcon />
                      </ToolbarToolButton>
                      <ToolbarToolButton
                        active={tool === "roof"}
                        onClick={() => selectTool("roof")}
                        disabled={drawingDisabled}
                        title="Techo (T)"
                        ariaLabel="Dibujar techo"
                      >
                        <RoofIcon />
                      </ToolbarToolButton>
                      <ToolbarToolButton
                        active={tool === "column"}
                        onClick={() => selectTool("column")}
                        disabled={drawingDisabled}
                        title="Columna (C)"
                        ariaLabel="Dibujar columna"
                      >
                        <ColumnIcon />
                      </ToolbarToolButton>
                      <ToolbarToolButton
                        active={tool === "riostra"}
                        onClick={() => selectTool("riostra")}
                        disabled={drawingDisabled}
                        title="Riostra"
                        ariaLabel="Dibujar riostra"
                      >
                        <RiostraIcon />
                      </ToolbarToolButton>
                      <ToolbarToolButton
                        active={tool === "cloaca"}
                        onClick={() => selectTool("cloaca")}
                        disabled={drawingDisabled}
                        title="Cloaca"
                        ariaLabel="Dibujar cloaca"
                      >
                        <CloacaIcon />
                      </ToolbarToolButton>
                      <div className="relative flex">
                        <ToolbarToolButton
                          active={tool === "electricidad"}
                          onClick={() => selectTool("electricidad")}
                          disabled={drawingDisabled}
                          title={`Electricidad - ${isFreehandMode ? "Mano alzada" : "Línea recta"}`}
                          ariaLabel="Dibujar electricidad"
                        >
                          <ElectricidadIcon />
                        </ToolbarToolButton>
                        <button
                          type="button"
                          disabled={drawingDisabled}
                          onClick={() => setShowElectricidadMenu((p) => !p)}
                          className={`flex w-4 items-center justify-center rounded-r-md transition disabled:cursor-not-allowed disabled:opacity-40 hover:bg-slate-100 dark:hover:bg-slate-800 ${tool === "electricidad" ? "text-sky-600 dark:text-sky-400 bg-sky-50 dark:bg-sky-900/30" : "text-slate-500 dark:text-slate-400"}`}
                          title="Elegir modo de dibujo"
                        >
                          <ChevronIcon open={showElectricidadMenu} />
                        </button>
                        {showElectricidadMenu && (
                          <div className="absolute top-[110%] left-1/2 mt-1 w-40 -translate-x-1/2 rounded-md border border-slate-200 bg-white p-1.5 shadow-xl dark:border-slate-700 dark:bg-slate-800 z-50">
                            <div className="px-2 py-1 mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">Modo de dibujo</div>
                            {[
                              { value: true, label: "Mano alzada" },
                              { value: false, label: "Línea recta" },
                            ].map((opt) => (
                              <button
                                key={String(opt.value)}
                                type="button"
                                onClick={() => {
                                  setIsFreehandMode(opt.value);
                                  setShowElectricidadMenu(false);
                                  if (tool !== "electricidad") selectTool("electricidad");
                                }}
                                className={`flex w-full items-center rounded-sm px-2 py-1.5 text-xs font-medium transition ${isFreehandMode === opt.value ? "bg-sky-50 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300" : "text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700"}`}
                              >
                                {opt.label}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>


          {/* Metadatos */}
          {natural && (
            <div className="mt-2 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500 dark:text-slate-400">
              <div className="flex flex-wrap items-center gap-3">
                <span>
                  {natural.w} × {natural.h} px · {Math.round(scale * 100)}%
                </span>
                <span>
                  {currentPageScale
                    ? `Esc. pág. ${page}: ${currentPageScale.toFixed(2)} px/m${
                        scaleSource ? ` (${scaleSource})` : ""
                      }`
                    : `Página ${page}: sin calibrar`}
                </span>
                {detectedCount > 0 && (
                  <span className="text-slate-400 dark:text-slate-500">
                    {detectedCount} de {totalPages} con escala
                  </span>
                )}
                {calError && (
                  <span className="text-red-600 dark:text-red-400">{calError}</span>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {!calibrating && (
                  <>
                    <button
                      type="button"
                      onClick={runAutoDetect}
                      disabled={autoDetecting}
                      className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-200 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-700"
                      title="Lee el texto del PDF y detecta escalas tipo 'Esc 1:100'"
                    >
                      {autoDetecting ? "Detectando..." : "Auto-detectar escalas"}
                    </button>
                    <button
                      type="button"
                      onClick={startCalibration}
                      className="rounded border border-brand px-2 py-1 font-medium text-brand hover:bg-brand hover:text-white dark:border-sky-400 dark:text-sky-400 dark:hover:bg-sky-400 dark:hover:text-slate-900"
                    >
                      {currentPageScale ? "Recalibrar página" : "Calibrar página"}
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>

        {/* PANEL DERECHO — Cómputo */}
        <aside className="flex w-full shrink-0 flex-col rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 lg:w-72">
          <div className="mb-1 flex items-center justify-between gap-2">
            <h3 className="text-sm font-bold text-slate-800 dark:text-slate-100">
              Cómputo
            </h3>
            <button
              type="button"
              onClick={downloadXlsx}
              disabled={exporting || summary.length === 0}
              title="Exportar a Excel"
              className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {exporting ? "..." : "XLSX"}
            </button>
          </div>
          <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
            Página {page} · cantidades por material
          </p>

          {summaryLoading ? (
            <p className="py-4 text-center text-xs text-slate-400">Calculando...</p>
          ) : summary.length === 0 ? (
            <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-slate-300 px-3 py-6 text-center text-xs text-slate-400 dark:border-slate-700 dark:text-slate-500">
              <div>
                <p className="font-medium">Sin materiales asignados</p>
                <p className="mt-1">
                  Asigná materiales a los elementos para ver el cómputo agregado.
                </p>
              </div>
            </div>
          ) : (
            <>
              <div className="max-h-[420px] flex-1 space-y-1.5 overflow-y-auto pr-1">
                {summary.map((item) => (
                  <div
                    key={item.material.id}
                    className="rounded-md border border-slate-100 bg-slate-50/30 px-2 py-1.5 dark:border-slate-800 dark:bg-slate-950/30"
                  >
                    <div className="flex items-start justify-between gap-2 text-xs">
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-semibold text-slate-700 dark:text-slate-200">
                          {item.material.name}
                        </p>
                        <p className="text-[10px] text-slate-400">{item.material.category}</p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="font-bold text-brand dark:text-sky-400">
                          {item.quantity.toLocaleString(undefined, {
                            minimumFractionDigits: 1,
                            maximumFractionDigits: 2,
                          })}
                          <span className="ml-1 text-[10px] font-semibold text-slate-500">
                            {item.unit}
                          </span>
                        </p>
                        {item.subtotal > 0 && (
                          <p className="text-[10px] text-slate-500">
                            ${item.subtotal.toLocaleString(undefined, {
                              minimumFractionDigits: 2,
                              maximumFractionDigits: 2,
                            })}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              {summary.some((s) => s.subtotal > 0) && (
                <div className="mt-2 flex items-center justify-between rounded-md border border-brand/30 bg-sky-50/60 px-2 py-1.5 text-xs font-bold dark:border-sky-800 dark:bg-sky-950/30">
                  <span className="text-slate-700 dark:text-slate-200">Total estimado</span>
                  <span className="text-brand dark:text-sky-300">
                    ${summary.reduce((a, s) => a + s.subtotal, 0).toLocaleString(undefined, {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}
                  </span>
                </div>
              )}
            </>
          )}
        </aside>
      </div>

      {/* Modal confirmación eliminar */}
      {confirmDelete && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
          onClick={() => !bulkBusy && setConfirmDelete(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="flex w-full max-w-sm flex-col gap-4 rounded-xl bg-white p-6 shadow-xl dark:bg-slate-800"
          >
            <h3 className="text-lg font-semibold">Eliminar elemento{confirmDelete.ids.length === 1 ? "" : "s"}</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              ¿Eliminar <span className="font-semibold">{confirmDelete.label}</span>? Esta acción no se puede deshacer.
            </p>
            <div className="mt-2 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmDelete(null)}
                disabled={bulkBusy}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => applyDelete(confirmDelete.ids)}
                disabled={bulkBusy}
                className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
              >
                {bulkBusy ? "Eliminando..." : "Eliminar"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal eliminar página */}
      {confirmDeletePage != null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
          onClick={() => {
            if (!pageBusy) {
              setConfirmDeletePage(null);
              setDeleteConfirmText("");
            }
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="flex w-full max-w-sm flex-col gap-4 rounded-xl bg-white p-6 shadow-xl dark:bg-slate-800"
          >
            <h3 className="text-lg font-semibold text-red-600 dark:text-red-400">Eliminar página {confirmDeletePage}</h3>
            <div className="text-sm text-slate-600 dark:text-slate-300 space-y-2">
              <p>
                Esta acción <strong>modificará el archivo PDF original</strong> eliminando la página físicamente.
                Todos los elementos dibujados en ella se perderán y las páginas posteriores cambiarán de numeración.
              </p>
              <p className="font-semibold text-red-600 dark:text-red-400">Esta acción NO se puede deshacer.</p>
              <p>Escribe <strong>ELIMINAR</strong> para confirmar:</p>
            </div>
            
            <input
              type="text"
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder="ELIMINAR"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-red-500 focus:outline-none focus:ring-1 focus:ring-red-500 dark:border-slate-600 dark:bg-slate-900 dark:text-white"
            />

            <div className="mt-2 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setConfirmDeletePage(null);
                  setDeleteConfirmText("");
                }}
                disabled={pageBusy}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => applyDeletePage(confirmDeletePage)}
                disabled={pageBusy || deleteConfirmText !== "ELIMINAR"}
                className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
              >
                {pageBusy ? "Eliminando..." : "Eliminar página"}

              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal bulk-assign assembly */}
      {bulkAssignOpen && (() => {
        const selectedElements = elements.filter((e) => selectedIds.has(e.id));
        const selectedTypes = Array.from(new Set(selectedElements.map((e) => e.type)));
        const bulkApplicable = assembliesList.filter((a) =>
          selectedTypes.every((t) => applicableAssemblies(t, [a]).length > 0),
        );
        return (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
            onClick={() => !bulkBusy && setBulkAssignOpen(false)}
          >
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (bulkAssignMaterialId != null) applyBulkAssignAssembly(bulkAssignMaterialId);
              }}
              onClick={(e) => e.stopPropagation()}
              className="flex w-full max-w-sm flex-col gap-4 rounded-xl bg-white p-6 shadow-xl dark:bg-slate-800"
            >
              <div>
                <h3 className="text-lg font-semibold">
                  Asignar sistema a {selectedIds.size} elemento{selectedIds.size === 1 ? "" : "s"}
                </h3>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  Tipos seleccionados: {selectedTypes.map((t) => labelFor(t, 0).split(" ")[0]).join(", ")}
                </p>
              </div>

              {assembliesList.length === 0 ? (
                <p className="text-sm text-slate-600 dark:text-slate-300">
                  No hay sistemas constructivos.{" "}
                  <a href="/materials" className="font-medium text-brand hover:underline dark:text-sky-400">
                    Crear sistema →
                  </a>
                </p>
              ) : bulkApplicable.length === 0 ? (
                <p className="text-sm text-slate-600 dark:text-slate-300">
                  Ningún sistema aplica a la mezcla de tipos seleccionada.
                  Probá seleccionar elementos de un solo tipo.
                </p>
              ) : (
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">Sistema Constructivo</span>
                  <select
                    autoFocus
                    required
                    value={bulkAssignMaterialId ?? ""}
                    onChange={(e) => setBulkAssignMaterialId(parseInt(e.target.value, 10))}
                    className="w-full rounded-md border border-slate-300 px-3 py-2 focus:border-brand focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-white"
                  >
                    <option value="" disabled>
                      Seleccionar sistema...
                    </option>
                    {bulkApplicable.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                  <span className="text-[11px] text-slate-500 dark:text-slate-400">
                    Si el material ya está asignado a algún elemento de la selección, se omite.
                  </span>
                </label>
              )}

              <div className="mt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setBulkAssignOpen(false)}
                  disabled={bulkBusy}
                  className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={bulkBusy || bulkAssignMaterialId == null || bulkApplicable.length === 0}
                  className="rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
                >
                  {bulkBusy ? "Asignando..." : "Asignar"}
                </button>
              </div>
            </form>
          </div>
        );
      })()}

      {/* Modal escalar selección */}
      {scaleModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
          onClick={() => !bulkBusy && setScaleModalOpen(false)}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              applyScale(parseFloat(scaleFactor.replace(",", ".")));
            }}
            onClick={(e) => e.stopPropagation()}
            className="flex w-full max-w-sm flex-col gap-4 rounded-xl bg-white p-6 shadow-xl dark:bg-slate-800"
          >
            <div>
              <h3 className="text-lg font-semibold">
                Escalar {selectedIds.size} elemento{selectedIds.size === 1 ? "" : "s"}
              </h3>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Multiplica las dimensiones físicas (largo, perímetro, área) por el factor.
                Útil cuando la escala del plano se recalibra después de dibujar.
              </p>
            </div>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Factor</span>
              <input
                type="text"
                inputMode="decimal"
                autoFocus
                value={scaleFactor}
                onChange={(e) => setScaleFactor(e.target.value)}
                className="rounded-md border border-slate-300 px-3 py-2 text-lg focus:border-brand focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-400"
              />
              <span className="text-[11px] text-slate-500 dark:text-slate-400">
                Ej: 0.5 reduce a la mitad · 2 duplica · 1.1 aumenta 10%. Las áreas se escalan al cuadrado.
              </span>
            </label>
            <div className="mt-2 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setScaleModalOpen(false)}
                disabled={bulkBusy}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={bulkBusy || !scaleFactor.trim()}
                className="rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
              >
                {bulkBusy ? "Aplicando..." : "Aplicar"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Modal calibración */}
      {distanceModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
          onClick={cancelCalibration}
        >
          <form
            onSubmit={submitCalibration}
            onClick={(e) => e.stopPropagation()}
            className="flex w-full max-w-sm flex-col gap-4 rounded-xl bg-white p-6 shadow-xl dark:bg-slate-800"
          >
            <h3 className="text-lg font-semibold">Distancia real</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              ¿Cuántos metros mide la línea marcada entre los dos puntos?
            </p>
            <input
              type="text"
              inputMode="decimal"
              autoFocus
              placeholder="Ej: 5.40"
              value={distanceInput}
              onChange={(e) => setDistanceInput(e.target.value)}
              className="rounded-md border border-slate-300 px-3 py-2 text-lg focus:border-brand focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-400"
            />
            {calError && <p className="text-sm text-red-600 dark:text-red-400">{calError}</p>}
            <div className="mt-2 flex justify-end gap-2">
              <button
                type="button"
                onClick={cancelCalibration}
                disabled={savingScale}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={savingScale || !distanceInput.trim()}
                className="rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
              >
                {savingScale ? "Guardando..." : "Guardar"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Modal de auto-detección */}
      {detectedPreview !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
          onClick={() => setDetectedPreview(null)}
        >
          <form
            onSubmit={submitBulkScales}
            onClick={(e) => e.stopPropagation()}
            className="flex w-full max-w-lg flex-col gap-4 rounded-xl bg-white p-6 shadow-xl dark:bg-slate-800"
          >
            <div>
              <h3 className="text-lg font-semibold">Confirmar escalas detectadas</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                El sistema escaneó el texto de los planos y detectó las siguientes escalas. Marca cuáles deseas aplicar y edítalas si es necesario.
              </p>
            </div>

            <div className="max-h-60 overflow-y-auto divide-y divide-slate-100 dark:divide-slate-700 pr-1">
              {Object.keys(detectedPreview).length === 0 ? (
                <p className="py-4 text-center text-sm text-slate-500 dark:text-slate-400">
                  No se detectó texto con formatos de escala (ej: "Esc 1:100") en ninguna página.
                </p>
              ) : (
                Object.keys(detectedPreview)
                  .sort((a, b) => Number(a) - Number(b))
                  .map((pageStr) => (
                    <div key={pageStr} className="flex items-center justify-between py-2 text-sm">
                      <label className="flex items-center gap-2 cursor-pointer select-none">
                        <input
                          type="checkbox"
                          checked={!!selectedPages[pageStr]}
                          onChange={(e) =>
                            setSelectedPages((prev) => ({
                              ...prev,
                              [pageStr]: e.target.checked,
                            }))
                          }
                          className="rounded border-slate-300 text-brand focus:ring-brand dark:border-slate-600 dark:bg-slate-900"
                        />
                        <span className="font-medium">Página {pageStr}</span>
                      </label>

                      <div className="flex items-center gap-1.5">
                        <span className="text-slate-500 dark:text-slate-400">1 :</span>
                        <input
                          type="text"
                          inputMode="decimal"
                          value={editedScales[pageStr] ?? ""}
                          disabled={!selectedPages[pageStr]}
                          onChange={(e) =>
                            setEditedScales((prev) => ({
                              ...prev,
                              [pageStr]: e.target.value,
                            }))
                          }
                          className="w-20 rounded-md border border-slate-300 px-2 py-1 text-center focus:border-brand focus:outline-none disabled:opacity-50 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-400"
                        />
                      </div>
                    </div>
                  ))
              )}
            </div>

            {calError && <p className="text-sm text-red-600 dark:text-red-400">{calError}</p>}

            <div className="mt-2 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDetectedPreview(null)}
                disabled={savingBulk}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={savingBulk || Object.keys(detectedPreview).length === 0}
                className="rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
              >
                {savingBulk ? "Guardando..." : "Confirmar y Aplicar"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

function labelFor(type: ElementType, n: number): string {
  if (type === "wall") return `Muro ${n}`;
  if (type === "room") return `Recinto ${n}`;
  if (type === "opening") return `Abertura ${n}`;
  if (type === "beam") return `Viga ${n}`;
  if (type === "roof") return `Techo ${n}`;
  if (type === "column") return `Columna ${n}`;
  return `Elemento ${n}`;
}

function PageOverrideToggle({
  rec,
  busy,
  onChange,
}: {
  rec: {
    recommended: boolean;
    override?: "recommended" | "rejected" | null;
    reason?: string;
  } | null;
  busy: boolean;
  onChange: (next: "recommended" | "rejected" | null) => void;
}) {
  // Estado actual: forzada, rechazada o automatica
  const current: "recommended" | "rejected" | "auto" = rec?.override
    ? rec.override
    : "auto";

  // Que dice el algoritmo (lo mostramos como pista cuando esta en auto)
  const autoLabel = rec?.recommended ? "auto: planta" : "auto: no planta";
  const title =
    current === "recommended"
      ? "Marcada manualmente como planta. Click para volver al algoritmo."
      : current === "rejected"
        ? "Marcada manualmente como NO planta. Click para volver al algoritmo."
        : `Algoritmo: ${rec?.reason || "sin senales"}. Click para forzar manualmente.`;

  function cycle() {
    if (busy) return;
    // auto -> recommended -> rejected -> auto
    if (current === "auto") onChange("recommended");
    else if (current === "recommended") onChange("rejected");
    else onChange(null);
  }

  const styles =
    current === "recommended"
      ? "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800/60 dark:bg-emerald-950/40 dark:text-emerald-300"
      : current === "rejected"
        ? "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800/60 dark:bg-amber-950/40 dark:text-amber-300"
        : "border-slate-300 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300";

  const label =
    current === "recommended"
      ? "✓ Planta"
      : current === "rejected"
        ? "✗ No planta"
        : autoLabel;

  return (
    <button
      type="button"
      onClick={cycle}
      disabled={busy}
      title={title}
      className={`ml-2 inline-flex items-center gap-1 rounded border px-2 py-1 text-xs font-semibold transition disabled:opacity-50 ${styles}`}
    >
      {label}
    </button>
  );
}

function PageButton({
  children,
  onClick,
  disabled,
  title,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="rounded border border-slate-300 px-2 py-1 text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-700"
    >
      {children}
    </button>
  );
}

function ToolbarIconButton({
  children,
  onClick,
  title,
  ariaLabel,
  disabled = false,
}: {
  children: React.ReactNode;
  onClick: () => void;
  title: string;
  ariaLabel: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={ariaLabel}
      className="flex h-8 w-8 items-center justify-center rounded-md text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-40 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100"
    >
      {children}
    </button>
  );
}

function ToolbarToolButton({
  children,
  active,
  onClick,
  disabled = false,
  title,
  ariaLabel,
}: {
  children: React.ReactNode;
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  title: string;
  ariaLabel: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={disabled ? `${title} — calibrá la página primero` : title}
      aria-label={ariaLabel}
      aria-pressed={active}
      className={`flex h-8 w-8 items-center justify-center rounded-md transition disabled:cursor-not-allowed disabled:opacity-40 ${
        active
          ? "bg-brand text-white shadow-sm dark:bg-sky-500 dark:text-slate-950"
          : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100"
      }`}
    >
      {children}
    </button>
  );
}

function CenterIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3" />
      <path d="M12 19v3" />
      <path d="M2 12h3" />
      <path d="M19 12h3" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </svg>
  );
}

function MinusIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12h14" />
    </svg>
  );
}

function HandIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 11V6a2 2 0 1 0-4 0v5" />
      <path d="M14 10V4a2 2 0 1 0-4 0v6" />
      <path d="M10 10.5V6a2 2 0 1 0-4 0v8" />
      <path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15" />
    </svg>
  );
}

function WallIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 8h18" />
      <path d="M3 16h18" />
      <path d="M7 4v4" />
      <path d="M14 4v4" />
      <path d="M10 12v4" />
      <path d="M17 12v4" />
      <path d="M7 20v-4" />
      <path d="M14 20v-4" />
    </svg>
  );
}

function RoomIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="1.5" />
      <path d="M3 9h6V3" opacity="0.4" />
    </svg>
  );
}

function OpeningIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 21V5a2 2 0 0 1 2-2h7" />
      <path d="M12 21V3" />
      <path d="M21 21V11a4 4 0 0 0-4-4h-2" />
      <path d="M16 12h.01" />
    </svg>
  );
}

function BeamIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 6h16" strokeDasharray="2 2" />
      <path d="M4 18h16" strokeDasharray="2 2" />
      <rect x="6" y="8" width="12" height="8" rx="1" />
    </svg>
  );
}

function RoofIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m2 16 10-10 10 10" />
      <path d="M12 6v14" />
      <path d="M3 20h18" />
    </svg>
  );
}

function ColumnIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="5" y="3" width="6" height="18" rx="0.5" />
      <rect x="13" y="3" width="6" height="18" rx="0.5" />
    </svg>
  );
}

function CubeIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m21 16-9 5-9-5V8l9-5 9 5v8z" />
      <path d="M12 22V12" />
      <path d="m12 12 8.7-5" />
      <path d="m12 12-8.7-5" />
    </svg>
  );
}

function RiostraIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 3l18 18" />
      <path d="M21 3L3 21" />
    </svg>
  );
}

function CloacaIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 22V2" />
      <path d="M20 22V2" />
      <path d="M4 12h16" />
      <path d="M8 2h8" />
      <path d="M8 22h8" />
    </svg>
  );
}

function ElectricidadIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

function ElementAssembliesBlock({
  element,
  assembliesList,
  onAssign,
  onRemove,
}: {
  element: DetectedElement;
  assembliesList: Assembly[];
  onAssign: (assemblyId: number) => void;
  onRemove: (assemblyId: number) => void;
}) {
  const assignedIds = new Set(element.assemblies.map((a) => a.id));
  const available = applicableAssemblies(element.type, assembliesList).filter(
    (a) => !assignedIds.has(a.id),
  );

  return (
    <div className="space-y-1.5 border-t border-slate-200 px-2 pb-2.5 pt-2 dark:border-slate-800">
      <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-wide text-slate-400">
        <span>Sistemas Constructivos</span>
        {element.assemblies.length > 0 && (
          <span className="text-slate-300">{element.assemblies.length}</span>
        )}
      </div>

      {element.assemblies.length > 0 && (
        <div className="space-y-1">
          {element.assemblies.map((a) => (
            <div
              key={a.id}
              className="flex items-center justify-between gap-2 rounded bg-slate-100/60 px-1.5 py-1 text-[11px] dark:bg-slate-800/40"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-slate-700 dark:text-slate-200" title={a.name}>
                  {a.name}
                </p>
              </div>
              <button
                type="button"
                onClick={() => onRemove(a.id)}
                title="Quitar sistema"
                aria-label={`Quitar sistema ${a.name}`}
                className="rounded p-0.5 text-slate-400 transition hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40 dark:hover:text-red-400"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M18 6 6 18" />
                  <path d="m6 6 12 12" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}

      {available.length > 0 ? (
        <select
          value=""
          onChange={(e) => {
            const val = e.target.value;
            if (val) onAssign(parseInt(val, 10));
          }}
          className="w-full rounded border border-dashed border-slate-300 bg-white px-1.5 py-1 text-[11px] text-slate-600 focus:border-brand focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:focus:border-sky-400"
        >
          <option value="">+ Asignar sistema</option>
          {available.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      ) : assembliesList.length === 0 ? (
        <p className="text-[10px] italic text-slate-400">
          No hay sistemas en el catálogo. <a href="/materials" className="text-brand hover:underline dark:text-sky-400">Crear catálogo</a>
        </p>
      ) : (
        <p className="text-[10px] italic text-slate-400">
          Todos los sistemas aplicables ya están asignados.
        </p>
      )}
    </div>
  );
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`text-slate-400 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

function InlineEditForm({
  element,
  defaultLabel,
  pageScale,
  onSave,
  onAutoAdjust,
}: {
  element: DetectedElement;
  defaultLabel: string;
  pageScale: number | null;
  onSave: (patch: { label?: string; height_m?: number; length_m?: number; subtype?: string }) => void;
  onAutoAdjust?: (roomId: number) => void;
}) {
  const defaultHeight = element.type === "opening" ? 2.1 : 2.8;
  const [label, setLabel] = useState(defaultLabel);
  const [heightStr, setHeightStr] = useState(String(element.height_m ?? defaultHeight));
  const [lengthStr, setLengthStr] = useState(
    element.length_m != null ? element.length_m.toFixed(3) : "",
  );
  const currentSubtype =
    element.type === "opening"
      ? (element.geometry.subtype ?? DEFAULT_OPENING_SUBTYPE)
      : null;

  // Re-sync inputs cuando el elemento cambia (post-save o cambio de pestaña)
  useEffect(() => {
    setLabel(element.geometry.label ?? defaultLabel);
    setHeightStr(String(element.height_m ?? defaultHeight));
    setLengthStr(element.length_m != null ? element.length_m.toFixed(3) : "");
  }, [element.id, element.geometry.label, element.height_m, element.length_m, defaultLabel, defaultHeight]);

  const canEditLength = element.type === "wall" || element.type === "opening";
  const lengthInputLabel = element.type === "opening" ? "Ancho (m)" : "Largo (m)";

  const geoLength = geometricLengthM(element, pageScale);
  const isEdited =
    canEditLength &&
    geoLength != null &&
    element.length_m != null &&
    Math.abs(geoLength - element.length_m) > 0.01;

  function commitLabel() {
    const trimmed = label.trim();
    if (trimmed && trimmed !== (element.geometry.label ?? defaultLabel)) {
      onSave({ label: trimmed });
    } else {
      setLabel(element.geometry.label ?? defaultLabel);
    }
  }

  function commitHeight() {
    const parsed = parseFloat(heightStr.replace(",", "."));
    if (Number.isFinite(parsed) && parsed > 0 && parsed !== element.height_m) {
      onSave({ height_m: parsed });
    } else {
      setHeightStr(String(element.height_m ?? defaultHeight));
    }
  }

  function commitLength() {
    const parsed = parseFloat(lengthStr.replace(",", "."));
    if (
      Number.isFinite(parsed) &&
      parsed > 0 &&
      element.length_m != null &&
      Math.abs(parsed - element.length_m) > 0.001
    ) {
      onSave({ length_m: parsed });
    } else if (element.length_m != null) {
      setLengthStr(element.length_m.toFixed(3));
    }
  }

  function restoreFromGeometry() {
    if (geoLength == null) return;
    setLengthStr(geoLength.toFixed(3));
    onSave({ length_m: geoLength });
  }

  return (
    <div className="space-y-1.5 border-t border-slate-200 px-2 pt-2 pb-2.5 dark:border-slate-800">
      <label className="flex items-center justify-between gap-2 text-[11px]">
        <span className="text-slate-500 dark:text-slate-400">Nombre</span>
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          onBlur={commitLabel}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              (e.target as HTMLInputElement).blur();
            }
          }}
          className="w-36 rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[11px] text-slate-700 focus:border-brand focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:focus:border-sky-400"
        />
      </label>

      {element.type === "opening" && (
        <label className="flex items-center justify-between gap-2 text-[11px]">
          <span className="text-slate-500 dark:text-slate-400">Tipo</span>
          <select
            value={currentSubtype ?? DEFAULT_OPENING_SUBTYPE}
            onChange={(e) => {
              const v = e.target.value as OpeningSubtype["value"];
              if (v !== currentSubtype) onSave({ subtype: v });
            }}
            className="w-36 rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[11px] text-slate-700 focus:border-brand focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:focus:border-sky-400"
          >
            {OPENING_SUBTYPES.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </label>
      )}

      {canEditLength && (
        <label className="flex items-center justify-between gap-2 text-[11px]">
          <span className="flex items-center gap-1.5 text-slate-500 dark:text-slate-400">
            {lengthInputLabel}
            {isEdited && (
              <button
                type="button"
                onClick={restoreFromGeometry}
                title={`Editado a mano. Valor de la geometría: ${geoLength?.toFixed(3)} m. Clic para restaurar.`}
                className="rounded-full bg-amber-100 px-1.5 py-[1px] text-[9px] font-semibold uppercase leading-tight text-amber-700 hover:bg-amber-200 dark:bg-amber-900/50 dark:text-amber-300 dark:hover:bg-amber-900/70"
              >
                editado
              </button>
            )}
          </span>
          <input
            type="text"
            inputMode="decimal"
            value={lengthStr}
            onChange={(e) => setLengthStr(e.target.value)}
            onBlur={commitLength}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                (e.target as HTMLInputElement).blur();
              }
            }}
            className="w-36 rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[11px] text-slate-700 focus:border-brand focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:focus:border-sky-400"
          />
        </label>
      )}

      <label className="flex items-center justify-between gap-2 text-[11px]">
        <span className="text-slate-500 dark:text-slate-400">Altura (m)</span>
        <input
          type="text"
          inputMode="decimal"
          value={heightStr}
          onChange={(e) => setHeightStr(e.target.value)}
          onBlur={commitHeight}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              (e.target as HTMLInputElement).blur();
            }
          }}
          className="w-36 rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[11px] text-slate-700 focus:border-brand focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:focus:border-sky-400"
        />
      </label>

      {element.type === "room" && onAutoAdjust && (
        <button
          type="button"
          onClick={() => onAutoAdjust(element.id)}
          className="w-full mt-1 px-1.5 py-1 text-[10px] font-semibold text-center text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 rounded transition dark:text-emerald-300 dark:bg-emerald-950/20 dark:border-emerald-900/40 dark:hover:bg-emerald-950/40 focus:outline-none"
        >
          Ajustar a muros
        </button>
      )}

      <div className="flex items-center justify-between gap-2 pt-0.5 text-[10px] text-slate-400">
        <span>
          {element.type === "wall" && `Dibujado ${geoLength?.toFixed(2) ?? "—"} m`}
          {element.type === "room" && `Área ${element.area_m2?.toFixed(2)} m² · Perím ${element.length_m?.toFixed(2)} m`}
          {element.type === "opening" && `Dibujado ${geoLength?.toFixed(2) ?? "—"} m`}
        </span>
        <span className="text-slate-300">Enter guarda</span>
      </div>
    </div>
  );
}

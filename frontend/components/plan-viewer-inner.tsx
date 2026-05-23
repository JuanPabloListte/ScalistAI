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
  type Material,
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
  onPlanUpdated?: (plan: Plan) => void;
  height?: number;
};

type Point = { x: number; y: number };
type Tool = "pan" | "wall" | "room" | "opening";

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

// Largo geométrico (calculado desde la línea dibujada). Solo aplica a wall/opening.
function geometricLengthM(el: DetectedElement, pxPerM: number | null): number | null {
  if (!pxPerM) return null;
  if (el.type !== "wall" && el.type !== "opening") return null;
  const [x1, y1, x2, y2] = el.geometry.points;
  if ([x1, y1, x2, y2].some((v) => v == null)) return null;
  return Math.hypot(x2 - x1, y2 - y1) / pxPerM;
}

// Materiales aplicables a un tipo de elemento (al menos un yield compatible).
function applicableMaterials(type: ElementType, all: Material[]): Material[] {
  return all.filter((mat) =>
    mat.yields.some((y) => {
      if (type === "wall") return y.applies_to === "wall";
      if (type === "room") return ["room_floor", "room_wall", "room_perimeter"].includes(y.applies_to);
      if (type === "opening") return ["opening", "opening_perimeter"].includes(y.applies_to);
      return false;
    }),
  );
}

export default function PlanViewerInner({
  planId,
  pageCount = 1,
  pageScales = null,
  deletedPages = null,
  scaleSource = null,
  planDpi: _planDpi = 150,
  calRequest = null,
  onPlanUpdated,
  height = 640,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const dragStart = useRef<{ x: number; y: number; px: number; py: number } | null>(null);

  const [page, setPage] = useState(1);
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
  const [mousePos, setMousePos] = useState<Point | null>(null);
  const [drawError, setDrawError] = useState<string | null>(null);

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
  const [editingId, setEditingId] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<{ ids: number[]; label: string } | null>(null);
  const [scaleModalOpen, setScaleModalOpen] = useState(false);
  const [scaleFactor, setScaleFactor] = useState("1");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkAssignOpen, setBulkAssignOpen] = useState(false);
  const [bulkAssignMaterialId, setBulkAssignMaterialId] = useState<number | null>(null);

  // Catálogo de materiales y cómputo
  const [materialsList, setMaterialsList] = useState<Material[]>([]);
  const [summary, setSummary] = useState<MaterialSummaryItem[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [exporting, setExporting] = useState(false);

  // Páginas eliminadas
  const [confirmDeletePage, setConfirmDeletePage] = useState<number | null>(null);
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

  const totalPages = Math.max(1, statusTotal ?? pageCount ?? 1);
  const currentPageScale = pageScales?.[String(page)] ?? null;
  const drawingDisabled = !currentPageScale;
  const activePages = useMemo(() => {
    const deleted = new Set(deletedPages ?? []);
    return Array.from({ length: totalPages }, (_, i) => i + 1).filter((p) => !deleted.has(p));
  }, [totalPages, deletedPages]);

  // Si la página actual quedó eliminada, saltar a la primera activa
  useEffect(() => {
    if (activePages.length > 0 && !activePages.includes(page)) {
      setPage(activePages[0]);
    }
  }, [activePages, page]);

  // Reset al cambiar de plan
  useEffect(() => {
    setPage(1);
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

  function toggleCandidateSelected(candidateId: string) {
    setSelectedCandidateIds((prev) => {
      const next = new Set(prev);
      if (next.has(candidateId)) {
        next.delete(candidateId);
      } else {
        next.add(candidateId);
      }
      return next;
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
  }, [planId, page]);

  // Cargar elementos al cambiar plan/página
  useEffect(() => {
    let cancelled = false;
    setElementsLoading(true);
    api
      .listElements(planId, page)
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
  }, [planId, page]);

  // Catálogo de materiales (una vez por montaje)
  useEffect(() => {
    let cancelled = false;
    api
      .listMaterials()
      .then((data) => {
        if (!cancelled) setMaterialsList(data);
      })
      .catch(() => {
        if (!cancelled) setMaterialsList([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Cómputo agregado: recargar cuando cambia plan, página, o cualquier cosa
  // que pueda alterar las cantidades (asignación, edición de length/area/height).
  const summaryDeps = elements
    .map((e) => `${e.id}:${e.length_m}:${e.area_m2}:${e.height_m}:${e.materials.map((m) => m.id).join(",")}`)
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
    if (tool !== "room" || activePoints.length < 3 || !mousePos) return false;
    const dx = (mousePos.x - activePoints[0].x) * scale;
    const dy = (mousePos.y - activePoints[0].y) * scale;
    return Math.hypot(dx, dy) < CLOSE_POLYGON_PX;
  }, [tool, activePoints, mousePos, scale]);

  // Crear muro o abertura (2 puntos → 1 elemento)
  const createSegmentElement = useCallback(
    async (pts: Point[], type: "wall" | "opening") => {
      if (!currentPageScale || pts.length !== 2) return;
      const lengthM = distM(pts[0], pts[1], currentPageScale);
      if (lengthM < MIN_SEGMENT_M) {
        setDrawError("Segmento demasiado corto, ignorado");
        setTimeout(() => setDrawError(null), 2000);
        return;
      }
      setDrawError(null);
      try {
        const el = await api.createElement(planId, {
          page,
          type,
          geometry: {
            points: [pts[0].x, pts[0].y, pts[1].x, pts[1].y],
          },
          length_m: lengthM,
          height_m: type === "opening" ? 2.1 : 2.8,
        });
        setElements((prev) => [...prev, el]);
      } catch (err) {
        setDrawError(err instanceof Error ? err.message : "Error al guardar");
      }
    },
    [planId, page, currentPageScale],
  );

  // Crear recinto (>= 3 puntos → polígono cerrado)
  const createRoomElement = useCallback(
    async (pts: Point[]) => {
      if (!currentPageScale || pts.length < 3) return;
      const areaM2 = polygonAreaM2(pts, currentPageScale);
      const perimM = polygonPerimeterM(pts, currentPageScale);
      if (areaM2 < 0.01) {
        setDrawError("Recinto con área insignificante");
        setTimeout(() => setDrawError(null), 2000);
        return;
      }
      setDrawError(null);
      const flat = pts.flatMap((p) => [p.x, p.y]);
      try {
        const el = await api.createElement(planId, {
          page,
          type: "room",
          geometry: { points: flat },
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

  function handleDrawClick(p: Point) {
    if (tool === "wall" || tool === "opening") {
      if (activePoints.length === 0) {
        setActivePoints([p]);
        return;
      }
      const pts = [...activePoints, p];
      setActivePoints([]);
      void createSegmentElement(pts, tool);
      return;
    }
    if (tool === "room") {
      if (activePoints.length >= 3 && isClosingRoom) {
        const pts = activePoints;
        setActivePoints([]);
        void createRoomElement(pts);
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
      handleDrawClick(imgPoint);
      return;
    }

    // Pan
    setDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY, px: pos.x, py: pos.y };
  }

  function onMouseMove(e: React.MouseEvent<HTMLDivElement>) {
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
    if (tool === "room" && activePoints.length >= 3) {
      const pts = activePoints;
      setActivePoints([]);
      void createRoomElement(pts);
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

  async function applyDeletePage(p: number) {
    setPageBusy(true);
    try {
      const updated = await api.deletePage(planId, p);
      onPlanUpdated?.(updated);
      setConfirmDeletePage(null);
    } catch (err) {
      setDrawError(err instanceof Error ? err.message : "Error al eliminar página");
    } finally {
      setPageBusy(false);
    }
  }

  async function handleRestorePage(p: number) {
    try {
      const updated = await api.restorePage(planId, p);
      onPlanUpdated?.(updated);
    } catch (err) {
      setDrawError(err instanceof Error ? err.message : "Error al restaurar página");
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

  function toggleSelected(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
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

  function selectAll() {
    setSelectedIds(new Set(elements.map((e) => e.id)));
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

  async function assignMaterialToElement(elementId: number, materialId: number) {
    try {
      const updated = await api.assignMaterial(planId, elementId, materialId);
      setElements((prev) => prev.map((e) => (e.id === elementId ? updated : e)));
    } catch (err) {
      setDrawError(err instanceof Error ? err.message : "Error al asignar material");
    }
  }

  async function removeMaterialFromElement(elementId: number, materialId: number) {
    try {
      const updated = await api.removeMaterial(planId, elementId, materialId);
      setElements((prev) => prev.map((e) => (e.id === elementId ? updated : e)));
    } catch (err) {
      setDrawError(err instanceof Error ? err.message : "Error al quitar material");
    }
  }

  async function applyBulkAssign(materialId: number) {
    const ids = [...selectedIds];
    if (ids.length === 0) return;
    setBulkBusy(true);
    try {
      const updated = await api.bulkAssignMaterial(planId, ids, materialId);
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
    patch: { label?: string; height_m?: number; length_m?: number },
  ) {
    const el = elements.find((e) => e.id === id);
    if (!el) return;
    const apiPatch: { geometry?: ElementGeometry; height_m?: number; length_m?: number } = {};
    if (patch.label !== undefined) {
      apiPatch.geometry = { ...el.geometry, label: patch.label };
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
      if (e.key === "Enter" && tool === "room" && activePoints.length >= 3) {
        e.preventDefault();
        const pts = activePoints;
        setActivePoints([]);
        void createRoomElement(pts);
        return;
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
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [calibrating, activePoints, tool, drawingDisabled, createRoomElement]);

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

  // Totales de la página actual (sidebar izquierdo)
  const totalWallM = elements
    .filter((e) => e.type === "wall")
    .reduce((acc, e) => acc + (e.length_m ?? 0), 0);
  const totalRoomM2 = elements
    .filter((e) => e.type === "room")
    .reduce((acc, e) => acc + (e.area_m2 ?? 0), 0);
  const totalOpenings = elements.filter((e) => e.type === "opening").length;

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
            {elements.length > 0 && (
              <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400 select-none">
                <input
                  type="checkbox"
                  checked={selectedIds.size === elements.length && elements.length > 0}
                  ref={(el) => {
                    if (el) {
                      el.indeterminate =
                        selectedIds.size > 0 && selectedIds.size < elements.length;
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
            Página {page} · {elements.length} dibujado{elements.length === 1 ? "" : "s"}
          </p>

          {/* Totales */}
          <div className="mb-3 grid grid-cols-3 gap-2 rounded-lg border border-slate-100 bg-slate-50/50 p-2 text-center text-[11px] dark:border-slate-800 dark:bg-slate-950/40">
            <div>
              <div className="font-semibold text-slate-700 dark:text-slate-200">
                {totalWallM.toFixed(2)} m
              </div>
              <div className="text-slate-400">Muros</div>
            </div>
            <div>
              <div className="font-semibold text-slate-700 dark:text-slate-200">
                {totalRoomM2.toFixed(2)} m²
              </div>
              <div className="text-slate-400">Recintos</div>
            </div>
            <div>
              <div className="font-semibold text-slate-700 dark:text-slate-200">
                {totalOpenings}
              </div>
              <div className="text-slate-400">Abert.</div>
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

                {/* Resumen Candidatos Muros */}
                {wallCandidates.length > 0 && (() => {
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
                {roomCandidates.length > 0 && (() => {
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
                {openingCandidates.length > 0 && (() => {
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
          ) : elements.length === 0 ? (
            <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-slate-300 px-3 py-6 text-center text-xs text-slate-400 dark:border-slate-700 dark:text-slate-500">
              <div>
                <p className="font-medium">Sin elementos en esta página</p>
                <p className="mt-1">Activá Muro, Recinto o Abertura.</p>
              </div>
            </div>
          ) : (
            <ul className="max-h-[480px] flex-1 space-y-1.5 overflow-y-auto pr-1">
              {elements.map((el, idx) => {
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
                        onChange={() => toggleSelected(el.id)}
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
                              el.type === "wall" ? "#2563eb"
                              : el.type === "room" ? "#22c55e"
                              : "#ea580c",
                          }}
                        />
                        <div className="min-w-0 flex-1">
                          <p className="truncate font-semibold text-slate-700 dark:text-slate-200">
                            {el.geometry.label ?? labelFor(el.type, idx + 1)}
                          </p>
                          <p className="text-[10px] text-slate-400">
                            {el.type === "wall" && `${el.length_m?.toFixed(2)} m · alt ${(el.height_m ?? 2.8).toFixed(2)} m`}
                            {el.type === "room" && `${el.area_m2?.toFixed(2)} m² · perím ${el.length_m?.toFixed(2)} m`}
                            {el.type === "opening" && `${el.length_m?.toFixed(2)} m ancho · alt ${(el.height_m ?? 2.1).toFixed(2)} m`}
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
                        />
                        <ElementMaterialsBlock
                          element={el}
                          materialsList={materialsList}
                          onAssign={(materialId) => assignMaterialToElement(el.id, materialId)}
                          onRemove={(materialId) => removeMaterialFromElement(el.id, materialId)}
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

          {/* Páginas ocultadas */}
          {(deletedPages ?? []).length > 0 && (
            <div className="mb-2 flex flex-wrap items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50/40 px-2.5 py-1.5 text-xs dark:border-slate-800 dark:bg-slate-950/30">
              <span className="font-semibold text-slate-500 dark:text-slate-400">
                Páginas ocultadas:
              </span>
              {(deletedPages ?? [])
                .slice()
                .sort((a, b) => a - b)
                .map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => handleRestorePage(p)}
                    title="Restaurar página"
                    className="inline-flex items-center gap-1 rounded-full bg-slate-200 px-2 py-0.5 font-medium text-slate-700 transition hover:bg-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                  >
                    Pág. {p}
                    <span className="text-slate-400" aria-hidden>
                      +
                    </span>
                    <span className="sr-only">Restaurar</span>
                  </button>
                ))}
            </div>
          )}

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
              className="relative overflow-hidden rounded-xl border border-slate-200 bg-slate-100 dark:border-slate-700 dark:bg-slate-950"
              style={{ height, cursor: show3D ? "default" : cursor }}
            >
              {show3D ? (
                <Plan3DViewer
                  elements={elements}
                  scale={currentPageScale ?? 100}
                  page={page}
                  onClose={() => setShow3D(false)}
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
                  <g
                    transform={`translate(${pos.x}, ${pos.y}) scale(${scale})`}
                    className={draggingVertex ? "pointer-events-none" : ""}
                  >
                    {/* Recintos (atrás) */}
                    {elements
                      .filter((el) => el.type === "room")
                      .map((el) => {
                        const pts = chunkPoints(el.geometry.points);
                        const ptsStr = pts.map((p) => `${p.x},${p.y}`).join(" ");
                        const hovered = hoveredId === el.id;
                        const sel = selectedIds.has(el.id);
                        return (
                          <g key={el.id}>
                            <polygon
                              points={ptsStr}
                              fill={hovered ? "rgba(34, 197, 94, 0.45)" : "rgba(34, 197, 94, 0.22)"}
                              stroke={hovered ? "#16a34a" : "#22c55e"}
                              strokeWidth={(hovered ? 3 : 2) / scale}
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
                                toggleSelected(el.id);
                              }}
                            />
                            {sel && (
                              <polygon
                                points={ptsStr}
                                fill="none"
                                stroke="#1f4e8c"
                                strokeWidth={3 / scale}
                                strokeDasharray={`${8 / scale} ${4 / scale}`}
                                strokeLinejoin="round"
                              />
                            )}
                          </g>
                        );
                      })}

                    {/* Candidatos Recintos */}
                    {roomCandidates.map((c) => {
                      const pts = chunkPoints(c.geometry.points);
                      const ptsStr = pts.map((p) => `${p.x},${p.y}`).join(" ");
                      const selected = selectedCandidateIds.has(c.id);
                      return (
                        <polygon
                          key={c.id}
                          points={ptsStr}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleCandidateSelected(c.id);
                          }}
                          className="pointer-events-auto cursor-pointer"
                          fill={selected ? "rgba(16, 185, 129, 0.15)" : "rgba(148, 163, 184, 0.05)"}
                          stroke={selected ? "#10b981" : "#94a3b8"}
                          strokeWidth={(selected ? 2 : 1) / scale}
                          strokeDasharray={`${6 / scale} ${4 / scale}`}
                          opacity={0.8}
                        />
                      );
                    })}

                    {/* Muros */}
                    {elements
                      .filter((el) => el.type === "wall")
                      .map((el) => {
                        const [x1, y1, x2, y2] = el.geometry.points;
                        const hovered = hoveredId === el.id;
                        const sel = selectedIds.has(el.id);
                        return (
                          <g key={el.id}>
                            {sel && (
                              <line
                                x1={x1}
                                y1={y1}
                                x2={x2}
                                y2={y2}
                                stroke="#1f4e8c"
                                strokeWidth={12 / scale}
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
                              strokeWidth={24 / scale}
                              className={`pointer-events-auto cursor-pointer ${draggingVertex ? "pointer-events-none" : ""}`}
                              onMouseEnter={() => {
                                if (!draggingVertex) setHoveredId(el.id);
                              }}
                              onMouseLeave={() => {
                                if (!draggingVertex) setHoveredId(null);
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleSelected(el.id);
                              }}
                            />
                            <line
                              x1={x1}
                              y1={y1}
                              x2={x2}
                              y2={y2}
                              stroke={hovered ? "#3b82f6" : "#2563eb"}
                              strokeWidth={(hovered ? 8 : 6) / scale}
                              strokeLinecap="round"
                              opacity={0.85}
                              className="pointer-events-none"
                            />
                          </g>
                        );
                      })}

                    {/* Candidatos Muros */}
                    {wallCandidates.map((c) => {
                      const pts = c.geometry.points;
                      if (pts.length < 4) return null;
                      const [x1, y1, x2, y2] = pts;
                      const selected = selectedCandidateIds.has(c.id);
                      return (
                        <g
                          key={c.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleCandidateSelected(c.id);
                          }}
                          className="pointer-events-auto cursor-pointer"
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
                            stroke={selected ? "#eab308" : "#94a3b8"}
                            strokeWidth={(selected ? 8 : 4) / scale}
                            strokeLinecap="square"
                            strokeDasharray={`${6 / scale} ${4 / scale}`}
                            opacity={selected ? 0.9 : 0.4}
                          />
                        </g>
                      );
                    })}

                    {/* Aberturas */}
                    {elements
                      .filter((el) => el.type === "opening")
                      .map((el) => {
                        const [x1, y1, x2, y2] = el.geometry.points;
                        const hovered = hoveredId === el.id;
                        const sel = selectedIds.has(el.id);
                        return (
                          <g key={el.id}>
                            {sel && (
                              <line
                                x1={x1}
                                y1={y1}
                                x2={x2}
                                y2={y2}
                                stroke="#1f4e8c"
                                strokeWidth={14 / scale}
                                strokeLinecap="square"
                                opacity={0.35}
                              />
                            )}
                            <line
                              x1={x1}
                              y1={y1}
                              x2={x2}
                              y2={y2}
                              stroke="transparent"
                              strokeWidth={24 / scale}
                              className={`pointer-events-auto cursor-pointer ${draggingVertex ? "pointer-events-none" : ""}`}
                              onMouseEnter={() => {
                                if (!draggingVertex) setHoveredId(el.id);
                              }}
                              onMouseLeave={() => {
                                if (!draggingVertex) setHoveredId(null);
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleSelected(el.id);
                              }}
                            />
                            <line
                              x1={x1}
                              y1={y1}
                              x2={x2}
                              y2={y2}
                              stroke={hovered ? "#fb923c" : "#ea580c"}
                              strokeWidth={(hovered ? 10 : 8) / scale}
                              strokeLinecap="square"
                              opacity={0.9}
                              className="pointer-events-none"
                            />
                          </g>
                        );
                      })}

                    {/* Candidatos Aberturas */}
                    {openingCandidates.map((c) => {
                      const bbox = c.bbox;
                      if (!bbox || bbox.length < 4) return null;
                      const [bx1, by1, bx2, by2] = bbox;
                      const selected = selectedCandidateIds.has(c.id);
                      return (
                        <g
                          key={c.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleCandidateSelected(c.id);
                          }}
                          className="pointer-events-auto cursor-pointer select-none"
                        >
                          <rect
                            x={bx1}
                            y={by1}
                            width={bx2 - bx1}
                            height={by2 - by1}
                            fill={selected ? "rgba(245, 158, 11, 0.15)" : "rgba(148, 163, 184, 0.05)"}
                            stroke={selected ? "#f59e0b" : "#94a3b8"}
                            strokeWidth={(selected ? 1.5 : 1) / scale}
                            strokeDasharray={`${4 / scale} ${3 / scale}`}
                          />
                          <text
                            x={(bx1 + bx2) / 2}
                            y={(by1 + by2) / 2 + 3 / scale}
                            textAnchor="middle"
                            fontSize={`${Math.max(9, 10 / scale)}px`}
                            className="font-bold fill-amber-700 dark:fill-amber-400 select-none pointer-events-none"
                          >
                            {c.label}
                          </text>
                        </g>
                      );
                    })}

                    {/* Preview de dibujo en curso — segmento (wall/opening) */}
                    {(tool === "wall" || tool === "opening") &&
                      activePoints.length === 1 &&
                      mousePos && (
                        <line
                          x1={activePoints[0].x}
                          y1={activePoints[0].y}
                          x2={mousePos.x}
                          y2={mousePos.y}
                          stroke={tool === "wall" ? "#2563eb" : "#ea580c"}
                          strokeWidth={6 / scale}
                          strokeLinecap="round"
                          strokeDasharray={`${6 / scale} ${4 / scale}`}
                          opacity={0.55}
                        />
                      )}

                    {/* Preview polígono (room) */}
                    {tool === "room" && activePoints.length > 0 && (() => {
                      const pts = mousePos ? [...activePoints, mousePos] : activePoints;
                      const ptsStr = pts.map((p) => `${p.x},${p.y}`).join(" ");
                      return (
                        <polygon
                          points={ptsStr}
                          fill="rgba(34, 197, 94, 0.15)"
                          stroke="#22c55e"
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
                        : tool === "wall" ? "#2563eb"
                        : tool === "opening" ? "#ea580c"
                        : "#22c55e";
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
                              <circle
                                cx={x1}
                                cy={y1}
                                r={6 / scale}
                                fill="#2563eb"
                                stroke="#ffffff"
                                strokeWidth={1.5 / scale}
                                className="pointer-events-auto cursor-move hover:scale-125 transition-transform"
                                onMouseDown={(e) => startDragVertex(e, selectedElement.id, 0)}
                              />
                              <circle
                                cx={x2}
                                cy={y2}
                                r={6 / scale}
                                fill="#2563eb"
                                stroke="#ffffff"
                                strokeWidth={1.5 / scale}
                                className="pointer-events-auto cursor-move hover:scale-125 transition-transform"
                                onMouseDown={(e) => startDragVertex(e, selectedElement.id, 2)}
                              />
                            </>
                          );
                        })()}
                        {selectedElement.type === "opening" && (() => {
                          const pts = selectedElement.geometry.points;
                          if (pts.length < 4) return null;
                          const [x1, y1, x2, y2] = pts;
                          return (
                            <>
                              <circle
                                cx={x1}
                                cy={y1}
                                r={6 / scale}
                                fill="#ea580c"
                                stroke="#ffffff"
                                strokeWidth={1.5 / scale}
                                className="pointer-events-auto cursor-move hover:scale-125 transition-transform"
                                onMouseDown={(e) => startDragVertex(e, selectedElement.id, 0)}
                              />
                              <circle
                                cx={x2}
                                cy={y2}
                                r={6 / scale}
                                fill="#ea580c"
                                stroke="#ffffff"
                                strokeWidth={1.5 / scale}
                                className="pointer-events-auto cursor-move hover:scale-125 transition-transform"
                                onMouseDown={(e) => startDragVertex(e, selectedElement.id, 2)}
                              />
                            </>
                          );
                        })()}
                        {selectedElement.type === "room" && (() => {
                          const pts = selectedElement.geometry.points;
                          const handles: React.ReactNode[] = [];
                          for (let i = 0; i < pts.length; i += 2) {
                            const x = pts[i];
                            const y = pts[i + 1];
                            const pointIndex = i;
                            handles.push(
                              <circle
                                key={i}
                                cx={x}
                                cy={y}
                                r={6 / scale}
                                fill="#22c55e"
                                stroke="#ffffff"
                                strokeWidth={1.5 / scale}
                                className="pointer-events-auto cursor-move hover:scale-125 transition-transform"
                                onMouseDown={(e) => startDragVertex(e, selectedElement.id, pointIndex)}
                              />
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
                <div className="pointer-events-auto flex items-center gap-1 rounded-xl border border-slate-200 bg-white/95 p-1 shadow-lg backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
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
                  <ToolbarToolButton
                    active={tool === "opening"}
                    onClick={() => selectTool("opening")}
                    disabled={drawingDisabled}
                    title="Abertura (O)"
                    ariaLabel="Dibujar abertura"
                  >
                    <OpeningIcon />
                  </ToolbarToolButton>
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
          onClick={() => !pageBusy && setConfirmDeletePage(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="flex w-full max-w-sm flex-col gap-4 rounded-xl bg-white p-6 shadow-xl dark:bg-slate-800"
          >
            <h3 className="text-lg font-semibold">Eliminar página {confirmDeletePage}</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              La página queda oculta de la navegación y se eliminan los elementos dibujados en ella.
              Podés restaurarla después desde la lista de páginas ocultadas, pero los elementos no
              se recuperan.
            </p>
            <div className="mt-2 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmDeletePage(null)}
                disabled={pageBusy}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => applyDeletePage(confirmDeletePage)}
                disabled={pageBusy}
                className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
              >
                {pageBusy ? "Eliminando..." : "Eliminar página"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal bulk-assign material */}
      {bulkAssignOpen && (() => {
        const selectedElements = elements.filter((e) => selectedIds.has(e.id));
        const selectedTypes = Array.from(new Set(selectedElements.map((e) => e.type)));
        const bulkApplicable = materialsList.filter((mat) =>
          selectedTypes.every((t) => applicableMaterials(t, [mat]).length > 0),
        );
        return (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
            onClick={() => !bulkBusy && setBulkAssignOpen(false)}
          >
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (bulkAssignMaterialId != null) applyBulkAssign(bulkAssignMaterialId);
              }}
              onClick={(e) => e.stopPropagation()}
              className="flex w-full max-w-sm flex-col gap-4 rounded-xl bg-white p-6 shadow-xl dark:bg-slate-800"
            >
              <div>
                <h3 className="text-lg font-semibold">
                  Asignar material a {selectedIds.size} elemento{selectedIds.size === 1 ? "" : "s"}
                </h3>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  Tipos seleccionados: {selectedTypes.map((t) => labelFor(t, 0).split(" ")[0]).join(", ")}
                </p>
              </div>

              {materialsList.length === 0 ? (
                <p className="text-sm text-slate-600 dark:text-slate-300">
                  El catálogo está vacío.{" "}
                  <a href="/materials" className="font-medium text-brand hover:underline dark:text-sky-400">
                    Crear materiales →
                  </a>
                </p>
              ) : bulkApplicable.length === 0 ? (
                <p className="text-sm text-slate-600 dark:text-slate-300">
                  Ningún material del catálogo aplica a la mezcla de tipos seleccionada.
                  Probá seleccionar elementos de un solo tipo.
                </p>
              ) : (
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium">Material</span>
                  <select
                    autoFocus
                    value={bulkAssignMaterialId ?? ""}
                    onChange={(e) =>
                      setBulkAssignMaterialId(e.target.value ? parseInt(e.target.value, 10) : null)
                    }
                    className="rounded-md border border-slate-300 px-3 py-2 focus:border-brand focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-400"
                  >
                    <option value="">Seleccioná un material</option>
                    {bulkApplicable.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name} ({m.category} · {m.unit})
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
  return `Abertura ${n}`;
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

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

function ElementMaterialsBlock({
  element,
  materialsList,
  onAssign,
  onRemove,
}: {
  element: DetectedElement;
  materialsList: Material[];
  onAssign: (materialId: number) => void;
  onRemove: (materialId: number) => void;
}) {
  const assignedIds = new Set(element.materials.map((m) => m.id));
  const available = applicableMaterials(element.type, materialsList).filter(
    (m) => !assignedIds.has(m.id),
  );

  return (
    <div className="space-y-1.5 border-t border-slate-200 px-2 pb-2.5 pt-2 dark:border-slate-800">
      <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-wide text-slate-400">
        <span>Materiales</span>
        {element.materials.length > 0 && (
          <span className="text-slate-300">{element.materials.length}</span>
        )}
      </div>

      {element.materials.length > 0 && (
        <div className="space-y-1">
          {element.materials.map((m) => (
            <div
              key={m.id}
              className="flex items-center justify-between gap-2 rounded bg-slate-100/60 px-1.5 py-1 text-[11px] dark:bg-slate-800/40"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-slate-700 dark:text-slate-200" title={m.name}>
                  {m.name}
                </p>
                <p className="text-[9px] text-slate-400">{m.unit}</p>
              </div>
              <button
                type="button"
                onClick={() => onRemove(m.id)}
                title="Quitar material"
                aria-label={`Quitar material ${m.name}`}
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
          <option value="">+ Asignar material</option>
          {available.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name} ({m.category} · {m.unit})
            </option>
          ))}
        </select>
      ) : materialsList.length === 0 ? (
        <p className="text-[10px] italic text-slate-400">
          No hay materiales en el catálogo. <a href="/materials" className="text-brand hover:underline dark:text-sky-400">Crear catálogo</a>
        </p>
      ) : (
        <p className="text-[10px] italic text-slate-400">
          Todos los materiales aplicables ya están asignados.
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
}: {
  element: DetectedElement;
  defaultLabel: string;
  pageScale: number | null;
  onSave: (patch: { label?: string; height_m?: number; length_m?: number }) => void;
}) {
  const defaultHeight = element.type === "opening" ? 2.1 : 2.8;
  const [label, setLabel] = useState(defaultLabel);
  const [heightStr, setHeightStr] = useState(String(element.height_m ?? defaultHeight));
  const [lengthStr, setLengthStr] = useState(
    element.length_m != null ? element.length_m.toFixed(3) : "",
  );

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

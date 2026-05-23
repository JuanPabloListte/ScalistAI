"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  api,
  type DetectedElement,
  type ElementType,
  type Plan,
} from "@/lib/api";

type Props = {
  planId: number;
  pageCount?: number | null;
  pageScales?: Record<string, number> | null;
  scaleSource?: string | null;
  planDpi?: number | null;
  calRequest?: { page: number; ts: number } | null;
  onScaleCalibrated?: (plan: Plan) => void;
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

export default function PlanViewerInner({
  planId,
  pageCount = 1,
  pageScales = null,
  scaleSource = null,
  planDpi: _planDpi = 150,
  calRequest = null,
  onScaleCalibrated,
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
  }, [planId]);

  // Reset estado de dibujo al cambiar página
  useEffect(() => {
    setActivePoints([]);
    setMousePos(null);
    setHoveredId(null);
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
    setDragging(false);
    dragStart.current = null;
    setMousePos(null);
  }

  function onMouseUp() {
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
    const clamped = Math.max(1, Math.min(totalPages, n));
    if (clamped !== page) setPage(clamped);
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
      onScaleCalibrated?.(updated);
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
      onScaleCalibrated?.(updated);
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

  async function deleteElementById(id: number) {
    try {
      await api.deleteElement(planId, id);
      setElements((prev) => prev.filter((e) => e.id !== id));
    } catch (err) {
      setDrawError(err instanceof Error ? err.message : "Error al eliminar");
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
  const cursor = calibrating
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
        <aside className="w-full shrink-0 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 lg:w-72">
          <h3 className="mb-1 text-sm font-bold text-slate-800 dark:text-slate-100">
            Elementos
          </h3>
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

          {elementsLoading ? (
            <p className="text-center text-xs text-slate-400 py-4">Cargando elementos...</p>
          ) : elements.length === 0 ? (
            <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-slate-300 px-3 py-6 text-center text-xs text-slate-400 dark:border-slate-700 dark:text-slate-500">
              <div>
                <p className="font-medium">Sin elementos en esta página</p>
                <p className="mt-1">Activá Muro, Recinto o Abertura.</p>
              </div>
            </div>
          ) : (
            <ul className="max-h-[420px] space-y-1.5 overflow-y-auto pr-1">
              {elements.map((el, idx) => (
                <li
                  key={el.id}
                  onMouseEnter={() => setHoveredId(el.id)}
                  onMouseLeave={() => setHoveredId(null)}
                  className={`flex items-center justify-between gap-2 rounded-md border px-2 py-1.5 text-xs transition ${
                    hoveredId === el.id
                      ? "border-brand bg-sky-50/60 dark:border-sky-500 dark:bg-sky-950/30"
                      : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
                  }`}
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-sm"
                      style={{
                        backgroundColor:
                          el.type === "wall" ? "#2563eb"
                          : el.type === "room" ? "#22c55e"
                          : "#ea580c",
                      }}
                    />
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-slate-700 dark:text-slate-200">
                        {el.geometry.label ?? labelFor(el.type, idx + 1)}
                      </p>
                      <p className="text-[10px] text-slate-400">
                        {el.type === "wall" && `${el.length_m?.toFixed(2)} m`}
                        {el.type === "room" && `${el.area_m2?.toFixed(2)} m²`}
                        {el.type === "opening" && `${el.length_m?.toFixed(2)} m ancho`}
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => deleteElementById(el.id)}
                    title="Eliminar"
                    aria-label="Eliminar elemento"
                    className="rounded p-1 text-slate-400 transition hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40 dark:hover:text-red-400"
                  >
                    <TrashIcon />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        {/* CANVAS CENTRAL */}
        <div className="min-w-0 flex-1">
          {/* Controles de página */}
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-sm">
            {totalPages > 1 ? (
              <>
                <div className="flex items-center gap-1">
                  <PageButton onClick={() => goToPage(1)} disabled={page === 1} title="Primera página">
                    «
                  </PageButton>
                  <PageButton onClick={() => goToPage(page - 1)} disabled={page === 1} title="Anterior">
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
                </div>
                <div className="flex items-center gap-1">
                  <PageButton
                    onClick={() => goToPage(page + 1)}
                    disabled={page === totalPages}
                    title="Siguiente"
                  >
                    Siguiente ›
                  </PageButton>
                  <PageButton
                    onClick={() => goToPage(totalPages)}
                    disabled={page === totalPages}
                    title="Última página"
                  >
                    »
                  </PageButton>
                </div>
              </>
            ) : (
              <div />
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
              onMouseDown={onMouseDown}
              onMouseMove={onMouseMove}
              onMouseUp={onMouseUp}
              onMouseLeave={onMouseLeave}
              onDoubleClick={onDoubleClick}
              onContextMenu={(e) => e.preventDefault()}
              className="relative overflow-hidden rounded-xl border border-slate-200 bg-slate-100 dark:border-slate-700 dark:bg-slate-950"
              style={{ height, cursor }}
            >
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
                  <g transform={`translate(${pos.x}, ${pos.y}) scale(${scale})`}>
                    {/* Recintos (atrás) */}
                    {elements
                      .filter((el) => el.type === "room")
                      .map((el) => {
                        const pts = chunkPoints(el.geometry.points);
                        const ptsStr = pts.map((p) => `${p.x},${p.y}`).join(" ");
                        const hovered = hoveredId === el.id;
                        return (
                          <polygon
                            key={el.id}
                            points={ptsStr}
                            fill={hovered ? "rgba(34, 197, 94, 0.45)" : "rgba(34, 197, 94, 0.22)"}
                            stroke={hovered ? "#16a34a" : "#22c55e"}
                            strokeWidth={(hovered ? 3 : 2) / scale}
                            strokeLinejoin="round"
                          />
                        );
                      })}

                    {/* Muros */}
                    {elements
                      .filter((el) => el.type === "wall")
                      .map((el) => {
                        const [x1, y1, x2, y2] = el.geometry.points;
                        const hovered = hoveredId === el.id;
                        return (
                          <line
                            key={el.id}
                            x1={x1}
                            y1={y1}
                            x2={x2}
                            y2={y2}
                            stroke={hovered ? "#3b82f6" : "#2563eb"}
                            strokeWidth={(hovered ? 8 : 6) / scale}
                            strokeLinecap="round"
                            opacity={0.85}
                          />
                        );
                      })}

                    {/* Aberturas */}
                    {elements
                      .filter((el) => el.type === "opening")
                      .map((el) => {
                        const [x1, y1, x2, y2] = el.geometry.points;
                        const hovered = hoveredId === el.id;
                        return (
                          <line
                            key={el.id}
                            x1={x1}
                            y1={y1}
                            x2={x2}
                            y2={y2}
                            stroke={hovered ? "#fb923c" : "#ea580c"}
                            strokeWidth={(hovered ? 10 : 8) / scale}
                            strokeLinecap="square"
                            opacity={0.9}
                          />
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
                  </g>
                </svg>
              )}
            </div>

            {/* Barra flotante inferior-derecha */}
            {!calibrating && (
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

        {/* PANEL DERECHO — Cómputo (placeholder Etapa 5) */}
        <aside className="w-full shrink-0 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 lg:w-72">
          <h3 className="mb-1 text-sm font-bold text-slate-800 dark:text-slate-100">
            Cómputo
          </h3>
          <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
            Cantidades acumuladas por material.
          </p>
          <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-slate-300 px-3 py-6 text-center text-xs text-slate-400 dark:border-slate-700 dark:text-slate-500">
            <div>
              <p className="font-medium">Sin materiales asignados</p>
              <p className="mt-1">
                Asigná materiales a los elementos para ver el cómputo agregado.
              </p>
            </div>
          </div>
        </aside>
      </div>

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
}: {
  children: React.ReactNode;
  onClick: () => void;
  title: string;
  ariaLabel: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={ariaLabel}
      className="flex h-8 w-8 items-center justify-center rounded-md text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100"
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

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

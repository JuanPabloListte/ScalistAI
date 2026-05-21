"use client";

import { useEffect, useRef, useState } from "react";

import { api, type Plan } from "@/lib/api";

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

const ZOOM_STEP = 1.1;
const MIN_SCALE = 0.02;
const MAX_SCALE = 8;
const FIT_MARGIN = 0.9;

export default function PlanViewerInner({
  planId,
  pageCount = 1,
  pageScales = null,
  scaleSource = null,
  planDpi: _planDpi = 150, // reservado para futuras conversiones; no se usa acá
  calRequest = null,
  onScaleCalibrated,
  height = 600,
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

  // Calibración
  const [calibrating, setCalibrating] = useState(false);
  const [calPoints, setCalPoints] = useState<Point[]>([]);
  const [distanceModalOpen, setDistanceModalOpen] = useState(false);
  const [distanceInput, setDistanceInput] = useState("");
  const [savingScale, setSavingScale] = useState(false);
  const [calError, setCalError] = useState<string | null>(null);
  const [autoDetecting, setAutoDetecting] = useState(false);

  // Estados para previsualizar/editar auto-detección
  const [detectedPreview, setDetectedPreview] = useState<Record<string, number> | null>(null);
  const [selectedPages, setSelectedPages] = useState<Record<string, boolean>>({});
  const [editedScales, setEditedScales] = useState<Record<string, string>>({});
  const [savingBulk, setSavingBulk] = useState(false);

  const totalPages = Math.max(1, statusTotal ?? pageCount ?? 1);

  useEffect(() => {
    setPage(1);
    setRendered(null);
    setStatusTotal(null);
  }, [planId]);

  // Disparado por el modal de escalas cuando el usuario hace clic en "Calibrar"
  // de una fila: saltamos a esa página y entramos en modo calibración.
  useEffect(() => {
    if (!calRequest) return;
    setPage(calRequest.page);
    setCalibrating(true);
    setCalPoints([]);
    setCalError(null);
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

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setDims({ w: el.clientWidth, h: height });
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

    setDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY, px: pos.x, py: pos.y };
  }

  function onMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    if (!dragging || !dragStart.current) return;
    const dx = e.clientX - dragStart.current.x;
    const dy = e.clientY - dragStart.current.y;
    setPos({ x: dragStart.current.px + dx, y: dragStart.current.py + dy });
  }

  function endDrag() {
    setDragging(false);
    dragStart.current = null;
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
  }

  async function runAutoDetect() {
    setAutoDetecting(true);
    setCalError(null);
    try {
      const preview = await api.previewAutoDetectScales(planId);

      // Inicializar selecciones y escalas editables
      const initialSelected: Record<string, boolean> = {};
      const initialEdited: Record<string, string> = {};

      Object.entries(preview).forEach(([pageStr, denom]) => {
        initialSelected[pageStr] = true; // seleccionadas por defecto
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
      if (!selectedPages[pageStr]) return; // saltear si no está seleccionada

      const denom = parseFloat(valueStr.replace(",", "."));
      if (!Number.isFinite(denom) || denom <= 0) {
        hasInvalid = true;
      } else {
        payload[pageStr] = denom;
      }
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

  const processing = rendered !== null && rendered < totalPages;
  const cursor = calibrating ? "crosshair" : dragging ? "grabbing" : imgUrl ? "grab" : "default";
  const currentPageScale = pageScales?.[String(page)] ?? null;
  const detectedCount = pageScales ? Object.keys(pageScales).length : 0;

  return (
    <div className="relative">
      {processing && (
        <div className="mb-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs dark:border-sky-900 dark:bg-sky-950/40">
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

      {/* Banner de modo calibración */}
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

      <div
        ref={containerRef}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={endDrag}
        onMouseLeave={endDrag}
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

        {/* Overlay SVG: línea + puntos de calibración */}
        {natural && calPoints.length > 0 && (
          <svg className="pointer-events-none absolute inset-0 h-full w-full">
            {calPoints.length === 2 &&
              (() => {
                const a = imageToScreen(calPoints[0]);
                const b = imageToScreen(calPoints[1]);
                return (
                  <line
                    x1={a.x}
                    y1={a.y}
                    x2={b.x}
                    y2={b.y}
                    stroke="#dc2626"
                    strokeWidth={2}
                    strokeDasharray="6 4"
                  />
                );
              })()}
            {calPoints.map((p, i) => {
              const s = imageToScreen(p);
              return (
                <g key={i}>
                  <circle cx={s.x} cy={s.y} r={6} fill="#dc2626" />
                  <circle cx={s.x} cy={s.y} r={10} fill="none" stroke="#dc2626" strokeWidth={1.5} />
                </g>
              );
            })}
          </svg>
        )}
      </div>

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
            <button
              type="button"
              onClick={resetView}
              className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-200 dark:border-slate-600 dark:hover:bg-slate-700"
            >
              Centrar
            </button>
          </div>
        </div>
      )}

      {/* Modal para ingresar distancia */}
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

      {/* Modal de confirmación de escalas auto-detectadas */}
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

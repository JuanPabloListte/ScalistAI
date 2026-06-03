"use client";

import React, { useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { DetectedElement } from "@/lib/api";

// ---------------------------------------------------------------------------
// Texturas procedurales — generadas en canvas, sin assets externos (0 KB).
// Se aplican SOLO en el modo "plaster"; en "blueprint" mantenemos el look
// abstracto con colores planos y bordes brillantes.
// ---------------------------------------------------------------------------
function makeCanvas(size = 256): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = size;
  c.height = size;
  return c;
}

function noise(ctx: CanvasRenderingContext2D, w: number, h: number, intensity: number) {
  const img = ctx.getImageData(0, 0, w, h);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const n = (Math.random() - 0.5) * intensity * 255;
    d[i] = Math.max(0, Math.min(255, d[i] + n));
    d[i + 1] = Math.max(0, Math.min(255, d[i + 1] + n));
    d[i + 2] = Math.max(0, Math.min(255, d[i + 2] + n));
  }
  ctx.putImageData(img, 0, 0);
}

function texFromCanvas(c: HTMLCanvasElement, repeatU = 4, repeatV = 4): THREE.Texture {
  const t = new THREE.CanvasTexture(c);
  t.wrapS = THREE.RepeatWrapping;
  t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(repeatU, repeatV);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

function makePlasterTexture(): THREE.Texture {
  const c = makeCanvas(256);
  const ctx = c.getContext("2d")!;
  // Base blanca apenas amarillenta
  ctx.fillStyle = "#f5f1ea";
  ctx.fillRect(0, 0, 256, 256);
  noise(ctx, 256, 256, 0.08);
  return texFromCanvas(c, 6, 6);
}

function makeConcreteTexture(): THREE.Texture {
  const c = makeCanvas(256);
  const ctx = c.getContext("2d")!;
  ctx.fillStyle = "#b8b8b3";
  ctx.fillRect(0, 0, 256, 256);
  noise(ctx, 256, 256, 0.15);
  // Manchas oscuras irregulares
  ctx.globalAlpha = 0.18;
  for (let i = 0; i < 40; i++) {
    ctx.fillStyle = Math.random() < 0.5 ? "#7a7a76" : "#d4d4d0";
    const x = Math.random() * 256;
    const y = Math.random() * 256;
    const r = 4 + Math.random() * 18;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  return texFromCanvas(c, 4, 4);
}

function makeWoodTexture(): THREE.Texture {
  const c = makeCanvas(512);
  const ctx = c.getContext("2d")!;
  // Base de madera
  ctx.fillStyle = "#9b6b3f";
  ctx.fillRect(0, 0, 512, 512);
  // Veta vertical (planchas)
  ctx.globalAlpha = 0.35;
  for (let i = 0; i < 50; i++) {
    ctx.strokeStyle = Math.random() < 0.5 ? "#7a4f2e" : "#b07d4d";
    ctx.lineWidth = 1 + Math.random() * 2;
    const x = Math.random() * 512;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x + (Math.random() - 0.5) * 12, 512);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
  // Separaciones entre planchas (cada 128 px)
  ctx.strokeStyle = "#5a3a1d";
  ctx.lineWidth = 2;
  for (let x = 0; x < 512; x += 128) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, 512);
    ctx.stroke();
  }
  noise(ctx, 512, 512, 0.06);
  return texFromCanvas(c, 2, 2);
}

function makeTileTexture(): THREE.Texture {
  const c = makeCanvas(256);
  const ctx = c.getContext("2d")!;
  // Base tipo porcelanato claro
  ctx.fillStyle = "#e8e6e0";
  ctx.fillRect(0, 0, 256, 256);
  noise(ctx, 256, 256, 0.05);
  // Junta (4 baldosas por tile, junta gris fina)
  ctx.strokeStyle = "#a8a5a0";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(128, 0); ctx.lineTo(128, 256);
  ctx.moveTo(0, 128); ctx.lineTo(256, 128);
  ctx.stroke();
  return texFromCanvas(c, 5, 5);
}

type ProceduralTextures = {
  plaster: THREE.Texture;
  concrete: THREE.Texture;
  wood: THREE.Texture;
  tile: THREE.Texture;
};

function createTextures(): ProceduralTextures {
  return {
    plaster: makePlasterTexture(),
    concrete: makeConcreteTexture(),
    wood: makeWoodTexture(),
    tile: makeTileTexture(),
  };
}

// ---------------------------------------------------------------------------
// Sanitización de dimensiones físicas.
// En la DB nada garantiza que `height_m` venga como número limpio: puede ser
// string (Pydantic/JSON), null, NaN, 0, valores absurdos (negativos o miles).
// `safeMeters` lo cohersiona a número, aplica fallback, y clampea a un rango
// realista para que el render no explote ni dibuje muros gigantes o invertidos.
// ---------------------------------------------------------------------------
function safeMeters(
  raw: number | string | null | undefined,
  fallback: number,
  min = 0.05,
  max = 30,
): number {
  const n = typeof raw === "number" ? raw : raw != null ? Number(raw) : NaN;
  if (!Number.isFinite(n) || n <= 0) return fallback;
  return Math.max(min, Math.min(max, n));
}

// ---------------------------------------------------------------------------
// Presets de cámara — animan posición y target con interpolación suave.
// Se calculan en función del `maxDim` para que sirvan a cualquier escala.
// ---------------------------------------------------------------------------
type CameraPreset = "plan" | "iso" | "front" | "side" | "reset";

function getPresetPose(preset: CameraPreset, maxDim: number): {
  position: THREE.Vector3;
  target: THREE.Vector3;
} {
  // Math.max para que cuando bounds.maxDim sea chico la cámara igual no se
  // meta dentro de los meshes.
  const d = Math.max(maxDim, 5);
  switch (preset) {
    case "plan":
      // Vista cenital (planta), apenas inclinada para evitar gimbal lock.
      return {
        position: new THREE.Vector3(0.001, d * 1.6, 0.001),
        target: new THREE.Vector3(0, 0, 0),
      };
    case "iso":
      // Isométrica clásica desde la esquina noreste.
      return {
        position: new THREE.Vector3(d * 0.75, d * 0.85, d * 0.75),
        target: new THREE.Vector3(0, d * 0.15, 0),
      };
    case "front":
      // Fachada (vista frontal): cámara baja, mirando al edificio de frente.
      return {
        position: new THREE.Vector3(0, d * 0.35, d * 1.4),
        target: new THREE.Vector3(0, d * 0.25, 0),
      };
    case "side":
      // Lateral (90° desde fachada).
      return {
        position: new THREE.Vector3(d * 1.4, d * 0.35, 0),
        target: new THREE.Vector3(0, d * 0.25, 0),
      };
    case "reset":
    default:
      // Misma pose con la que arranca la cámara en la primera render.
      return {
        position: new THREE.Vector3(0, d * 0.8, d * 1.1),
        target: new THREE.Vector3(0, 0, 0),
      };
  }
}

/**
 * Sub-componente que tiene que vivir DENTRO del <Canvas> para tener acceso
 * a la cámara y a los OrbitControls (con `makeDefault`). Cada vez que cambia
 * `preset`, anima cámara y target con un easeOut hasta llegar.
 */
// ---------------------------------------------------------------------------
// Info panel del elemento seleccionado en 3D.
// Muestra tipo, label, dimensiones y materiales asignados. Es read-only: la
// edición sigue siendo desde el sidebar del visor 2D — pero clickear acá en
// 3D selecciona el mismo elemento, lo que da una sensación de continuidad
// entre las dos vistas. El usuario lee acá, edita allá, y como `elements`
// fluye por prop, los cambios se reflejan en el render automáticamente.
// ---------------------------------------------------------------------------
function SelectionInfoPanel({
  element,
  onClose,
  onUpdateElement,
}: {
  element: DetectedElement;
  onClose: () => void;
  onUpdateElement?: (id: number, patch: { height_m?: number; length_m?: number; label?: string; subtype?: string }) => void;
}) {
  const TYPE_LABELS: Record<string, string> = {
    wall: "Muro",
    room: "Recinto",
    opening: "Abertura",
    beam: "Viga",
    column: "Columna",
    roof: "Techo / Losa",
  };
  const OPENING_SUBTYPE_LABELS: Record<string, string> = {
    door: "Puerta",
    window: "Ventana",
    "sliding-door": "Puerta ventana",
  };
  const typeLabel = TYPE_LABELS[element.type] ?? element.type;
  const subtype = element.type === "opening"
    ? OPENING_SUBTYPE_LABELS[(element.geometry.subtype as string) ?? "door"] ?? null
    : null;
  const label = (element.geometry.label as string) ?? `${typeLabel} #${element.id}`;

  // Ya no usamos el arreglo `dim`, renderizamos directo

  const materials = element.materials ?? [];

  return (
    <div className="absolute bottom-4 right-4 z-30 w-72 rounded-xl bg-white/95 dark:bg-slate-900/95 backdrop-blur border border-slate-200 dark:border-slate-700 shadow-2xl overflow-hidden">
      <div className="flex items-start justify-between gap-2 border-b border-slate-100 dark:border-slate-800 px-3 py-2 bg-cyan-50/60 dark:bg-cyan-950/30">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] uppercase tracking-wider font-bold text-cyan-700 dark:text-cyan-300">
              {typeLabel}
            </span>
            {subtype && (
              <span className="rounded-sm bg-amber-100 px-1.5 py-0 text-[9px] font-semibold uppercase tracking-wide text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                {subtype}
              </span>
            )}
          </div>
          <p className="truncate text-sm font-bold text-slate-800 dark:text-slate-100" title={label}>
            {label}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Cerrar"
          className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 6 6 18" />
            <path d="m6 6 12 12" />
          </svg>
        </button>
      </div>

      <div className="px-3 py-2.5 space-y-2">
        <div className="grid grid-cols-2 gap-1 text-[11px]">
          {element.length_m != null && (
            <label className="flex flex-col gap-0.5 rounded bg-slate-50 dark:bg-slate-800/50 px-2 py-1">
              <span className="text-[9px] uppercase tracking-wide text-slate-400">
                {element.type === "opening" ? "Ancho (m)" : element.type === "room" ? "Perímetro (m)" : "Largo (m)"}
              </span>
              <input
                key={`l-${element.id}`}
                type="number"
                step="0.05"
                defaultValue={element.length_m.toFixed(2)}
                disabled={element.type === "room" || !onUpdateElement}
                onBlur={(e) => {
                  const val = parseFloat(e.target.value);
                  if (!isNaN(val) && val > 0 && val !== element.length_m) {
                    onUpdateElement?.(element.id, { length_m: val });
                  } else {
                    e.target.value = element.length_m!.toFixed(2);
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") e.currentTarget.blur();
                }}
                className="w-full bg-transparent font-semibold text-slate-700 focus:outline-none dark:text-slate-200 disabled:opacity-70"
              />
            </label>
          )}

          {element.height_m != null && (
            <label className="flex flex-col gap-0.5 rounded bg-slate-50 dark:bg-slate-800/50 px-2 py-1">
              <span className="text-[9px] uppercase tracking-wide text-slate-400">
                {element.type === "roof" ? "Espesor (m)" : element.type === "beam" ? "Peralte (m)" : "Altura (m)"}
              </span>
              <input
                key={`h-${element.id}`}
                type="number"
                step="0.05"
                defaultValue={element.height_m.toFixed(2)}
                disabled={!onUpdateElement}
                onBlur={(e) => {
                  const val = parseFloat(e.target.value);
                  if (!isNaN(val) && val > 0 && val !== element.height_m) {
                    onUpdateElement?.(element.id, { height_m: val });
                  } else {
                    e.target.value = element.height_m!.toFixed(2);
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") e.currentTarget.blur();
                }}
                className="w-full bg-transparent font-semibold text-slate-700 focus:outline-none dark:text-slate-200 disabled:opacity-70"
              />
            </label>
          )}
          
          {element.area_m2 != null && (
            <div className="flex flex-col gap-0.5 rounded bg-slate-50 dark:bg-slate-800/50 px-2 py-1">
              <span className="text-[9px] uppercase tracking-wide text-slate-400">Área</span>
              <span className="font-semibold text-slate-700 dark:text-slate-200">{element.area_m2.toFixed(2)} m²</span>
            </div>
          )}
        </div>
        
        {element.type === "opening" && onUpdateElement && (
           <label className="flex flex-col gap-0.5 rounded bg-slate-50 dark:bg-slate-800/50 px-2 py-1">
             <span className="text-[9px] uppercase tracking-wide text-slate-400">Subtipo</span>
             <select
               value={element.geometry.subtype || "door"}
               onChange={(e) => onUpdateElement(element.id, { subtype: e.target.value })}
               className="w-full bg-transparent text-xs font-semibold text-slate-700 focus:outline-none dark:text-slate-200"
             >
               <option value="door">Puerta</option>
               <option value="window">Ventana</option>
               <option value="sliding-door">Puerta ventana</option>
             </select>
           </label>
        )}

        <div>
          <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-wide text-slate-400 mb-1 mt-1.5">
            <span>Materiales</span>
            {materials.length > 0 && <span className="text-slate-300">{materials.length}</span>}
          </div>
          {materials.length === 0 ? (
            <p className="text-[10px] italic text-slate-400">Sin materiales asignados</p>
          ) : (
            <ul className="space-y-0.5">
              {materials.map((m) => (
                <li
                  key={m.id}
                  className="flex items-center justify-between gap-2 rounded bg-slate-50 dark:bg-slate-800/40 px-1.5 py-1 text-[11px]"
                >
                  <span className="truncate font-medium text-slate-700 dark:text-slate-200" title={m.name}>
                    {m.name}
                  </span>
                  <span className="shrink-0 text-[9px] text-slate-400">{m.unit}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <p className="text-[9px] italic text-slate-400 pt-1">
          Podés editar dimensiones directamente acá. Cambios auto-guardados.
        </p>
      </div>
    </div>
  );
}

/**
 * Botón visual de preset de cámara. Mantengo el estilo consistente con los
 * tabs de estilo (blueprint/plaster) para que la barra superior se sienta
 * coherente.
 */
function PresetButton({
  onClick,
  children,
  title,
}: {
  onClick: () => void;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="text-[10px] uppercase tracking-wider font-bold px-2 py-1 rounded-md text-slate-600 hover:bg-cyan-500 hover:text-slate-950 dark:text-slate-300 dark:hover:bg-cyan-500 dark:hover:text-slate-950 transition-colors"
    >
      {children}
    </button>
  );
}

function CameraRig({ preset, maxDim }: { preset: CameraPreset | null; maxDim: number }) {
  const camera = useThree((s) => s.camera);
  // `controls` solo está disponible si OrbitControls tiene `makeDefault`.
  const controls = useThree((s) => s.controls as unknown as {
    target: THREE.Vector3;
    update: () => void;
    enabled: boolean;
  } | null);

  const targetPos = useRef(new THREE.Vector3());
  const targetLookAt = useRef(new THREE.Vector3());
  const active = useRef(false);

  React.useEffect(() => {
    if (!preset) return;
    const pose = getPresetPose(preset, maxDim);
    targetPos.current.copy(pose.position);
    targetLookAt.current.copy(pose.target);
    active.current = true;
  }, [preset, maxDim]);

  useFrame((_, dt) => {
    if (!active.current || !controls) return;
    // Lerp suave hacia la pose objetivo. ~0.12 por frame ⇒ ~0.5s total.
    const k = 1 - Math.exp(-dt * 5);
    camera.position.lerp(targetPos.current, k);
    controls.target.lerp(targetLookAt.current, k);
    controls.update();
    // Cortar cuando ya estamos cerca para no quedar "vibrando".
    if (
      camera.position.distanceTo(targetPos.current) < 0.01 &&
      controls.target.distanceTo(targetLookAt.current) < 0.01
    ) {
      camera.position.copy(targetPos.current);
      controls.target.copy(targetLookAt.current);
      controls.update();
      active.current = false;
    }
  });

  return null;
}


interface Plan3DViewerProps {
  elements: DetectedElement[];
  scale: number; // px_per_m
  page: number;
  onClose: () => void;
  onUpdateElement?: (id: number, patch: { height_m?: number; length_m?: number; label?: string; subtype?: string }) => void;
}

export default function Plan3DViewer({ elements, scale, page, onClose, onUpdateElement }: Plan3DViewerProps) {
  const [styleMode, setStyleMode] = useState<"blueprint" | "plaster">(() => {
    if (typeof window !== "undefined") {
      return document.documentElement.classList.contains("dark") ? "blueprint" : "plaster";
    }
    return "blueprint";
  });

  React.useEffect(() => {
    const isDark = document.documentElement.classList.contains("dark");
    setStyleMode(isDark ? "blueprint" : "plaster");

    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.attributeName === "class") {
          const currentlyDark = document.documentElement.classList.contains("dark");
          setStyleMode(currentlyDark ? "blueprint" : "plaster");
        }
      });
    });

    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });

    return () => observer.disconnect();
  }, []);

  // 1. Mostrar todos los elementos del plano (junta todas las páginas/capas)
  const pageElements = elements;

  // 2. Encontrar límites físicos en metros para centrar el modelo
  const bounds = useMemo(() => {
    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;

    pageElements.forEach((el) => {
      if (el.type === "wall" || el.type === "opening" || el.type === "beam") {
        const pts = el.geometry.points;
        if (pts.length >= 4) {
          const x1 = pts[0] / scale;
          const y1 = pts[1] / scale;
          const x2 = pts[2] / scale;
          const y2 = pts[3] / scale;
          minX = Math.min(minX, x1, x2);
          maxX = Math.max(maxX, x1, x2);
          minY = Math.min(minY, y1, y2);
          maxY = Math.max(maxY, y1, y2);
        }
      } else if (el.type === "room" || el.type === "roof" || el.type === "column") {
        const pts = el.geometry.points;
        for (let i = 0; i < pts.length; i += 2) {
          const x = pts[i] / scale;
          const y = pts[i + 1] / scale;
          minX = Math.min(minX, x);
          maxX = Math.max(maxX, x);
          minY = Math.min(minY, y);
          maxY = Math.max(maxY, y);
        }
      }
    });

    const cx = minX !== Infinity ? (minX + maxX) / 2 : 0;
    const cy = minY !== Infinity ? (minY + maxY) / 2 : 0;
    const sizeX = maxX - minX > 0 ? maxX - minX : 10;
    const sizeY = maxY - minY > 0 ? maxY - minY : 10;

    return { cx, cy, maxDim: Math.max(sizeX, sizeY) };
  }, [pageElements, scale]);

  // 3. Agrupar muros, aberturas y recintos en metros relativos al centro
  const walls = useMemo(() => pageElements.filter((el) => el.type === "wall"), [pageElements]);
  const openings = useMemo(() => pageElements.filter((el) => el.type === "opening"), [pageElements]);
  const rooms = useMemo(() => pageElements.filter((el) => el.type === "room"), [pageElements]);
  const columns = useMemo(() => pageElements.filter((el) => el.type === "column"), [pageElements]);
  const roofs = useMemo(() => pageElements.filter((el) => el.type === "roof"), [pageElements]);
  const beams = useMemo(() => pageElements.filter((el) => el.type === "beam"), [pageElements]);

  // Espesor estándar de muros (15 cm)
  const WALL_THICKNESS = 0.15;

  // Renderizar muros segmentados alrededor de las aberturas
  const wallMeshes = useMemo(() => {
    // `elementId` apunta al DetectedElement subyacente. Para muros partidos
    // por aberturas, todos los fragmentos comparten el mismo elementId (el muro
    // original) y por eso clickear cualquier fragmento selecciona el muro entero.
    // Para sub-meshes generados por aberturas (lintel/sill/glass/jamb),
    // elementId apunta a la abertura.
    const list: Array<{
      id: string;
      elementId: number;
      position: [number, number, number];
      args: [number, number, number];
      rotationY: number;
      type: "solid" | "lintel" | "sill" | "glass" | "jamb";
    }> = [];

    // Marco de aberturas: tamaño en metros del jamb (caño vertical a los
    // costados) y leve sobresaliente respecto del muro para que se vea.
    const JAMB_W = 0.06;
    const JAMB_DEPTH = WALL_THICKNESS * 1.08;

    walls.forEach((wall) => {
      const pts = wall.geometry.points;
      if (pts.length < 4) return;

      const wx1 = pts[0] / scale - bounds.cx;
      const wy1 = pts[1] / scale - bounds.cy;
      const wx2 = pts[2] / scale - bounds.cx;
      const wy2 = pts[3] / scale - bounds.cy;

      const dx = wx2 - wx1;
      const dy = wy2 - wy1;
      const length = Math.sqrt(dx * dx + dy * dy);
      if (length === 0) return;

      const angle = Math.atan2(dy, dx);
      const height = safeMeters(wall.height_m, 2.8, 0.5, 12);

      // Buscar aberturas sobre este muro
      const wallOpenings: Array<{
        tStart: number;
        tEnd: number;
        subtype: string;
        width_m: number;
        opId: number;
      }> = [];

      openings.forEach((op) => {
        const oPts = op.geometry.points;
        if (oPts.length < 4) return;

        const ocx = (oPts[0] + oPts[2]) / 2 / scale - bounds.cx;
        const ocy = (oPts[1] + oPts[3]) / 2 / scale - bounds.cy;

        // Proyectar el centro de la abertura sobre el muro
        const lineLenSq = dx * dx + dy * dy;
        const t = ((ocx - wx1) * dx + (ocy - wy1) * dy) / lineLenSq;

        if (t >= 0.0 && t <= 1.0) {
          const projX = wx1 + t * dx;
          const projY = wy1 + t * dy;
          const dist = Math.sqrt((ocx - projX) ** 2 + (ocy - projY) ** 2);

          // Si está a menos de 30 cm del muro, la consideramos parte de él
          if (dist < 0.3) {
            const w_m = op.length_m || 0.8;
            const w_norm = w_m / length;
            const tStart = Math.max(0.0, t - w_norm / 2);
            const tEnd = Math.min(1.0, t + w_norm / 2);
            wallOpenings.push({ tStart, tEnd, subtype: op.geometry.subtype || "door", width_m: w_m, opId: op.id });
          }
        }
      });

      // Si no hay aberturas en este muro, renderizarlo sólido completo
      if (wallOpenings.length === 0) {
        const mx = wx1 + dx / 2;
        const my = wy1 + dy / 2;
        list.push({
          id: `${wall.id}-solid`,
          elementId: wall.id,
          position: [mx, height / 2, my],
          args: [length, WALL_THICKNESS, height],
          rotationY: -angle,
          type: "solid",
        });
        return;
      }

      // Ordenar las aberturas por tStart
      wallOpenings.sort((a, b) => a.tStart - b.tStart);

      // Segmentar la pared
      let currentT = 0.0;
      wallOpenings.forEach((op, idx) => {
        // 1. Tramo sólido antes de la abertura
        if (op.tStart > currentT) {
          const subLen = (op.tStart - currentT) * length;
          if (subLen > 0.05) {
            const midT = (currentT + op.tStart) / 2;
            const mx = wx1 + midT * dx;
            const my = wy1 + midT * dy;
            list.push({
              id: `${wall.id}-segment-${idx}-solid`,
              elementId: wall.id,
              position: [mx, height / 2, my],
              args: [subLen, WALL_THICKNESS, height],
              rotationY: -angle,
              type: "solid",
            });
          }
        }

        // 2. Procesar la abertura misma (dintel y antepecho)
        const opLen = (op.tEnd - op.tStart) * length;
        const opMidT = (op.tStart + op.tEnd) / 2;
        const opx = wx1 + opMidT * dx;
        const opy = wy1 + opMidT * dy;

        const isWindow = op.subtype.includes("window") || op.subtype.includes("ventana");
        const doorHeight = 2.1;
        const windowSillHeight = 0.9;
        const windowHeaderHeight = 2.1;

        if (isWindow) {
          // Bloque bajo la ventana (Sill/Antepecho)
          if (windowSillHeight > 0) {
            list.push({
              id: `${wall.id}-op-${idx}-sill`,
              elementId: op.opId,
              position: [opx, windowSillHeight / 2, opy],
              args: [opLen, WALL_THICKNESS, windowSillHeight],
              rotationY: -angle,
              type: "sill",
            });
          }
          // Bloque sobre la ventana (Header/Dintel)
          if (height > windowHeaderHeight) {
            const topHeight = height - windowHeaderHeight;
            list.push({
              id: `${wall.id}-op-${idx}-header`,
              elementId: op.opId,
              position: [opx, windowHeaderHeight + topHeight / 2, opy],
              args: [opLen, WALL_THICKNESS, topHeight],
              rotationY: -angle,
              type: "lintel",
            });
          }
          // Panel de vidrio translúcido
          const glassHeight = windowHeaderHeight - windowSillHeight;
          list.push({
            id: `${wall.id}-op-${idx}-glass`,
            elementId: op.opId,
            position: [opx, windowSillHeight + glassHeight / 2, opy],
            args: [opLen, WALL_THICKNESS * 0.2, glassHeight],
            rotationY: -angle,
            type: "glass",
          });
        } else {
          // Es una puerta: solo bloque superior (lintel)
          if (height > doorHeight) {
            const topHeight = height - doorHeight;
            list.push({
              id: `${wall.id}-op-${idx}-lintel`,
              elementId: op.opId,
              position: [opx, doorHeight + topHeight / 2, opy],
              args: [opLen, WALL_THICKNESS, topHeight],
              rotationY: -angle,
              type: "lintel",
            });
          }
        }

        // Marco (jambas): dos columnas finas a los costados del vano. Le da
        // sensación de "ventana enmarcada" / "puerta enmarcada" sin tener que
        // hacer un CSG real (que en r3f es costoso).
        const dirX = Math.cos(angle);
        const dirY = Math.sin(angle);
        const halfOpen = opLen / 2;
        const halfJamb = JAMB_W / 2;
        const off = Math.max(halfOpen - halfJamb, 0);
        const jambVertCenter = isWindow
          ? (windowSillHeight + windowHeaderHeight) / 2
          : doorHeight / 2;
        const jambHeight = isWindow ? windowHeaderHeight - windowSillHeight : doorHeight;
        if (jambHeight > 0.05) {
          list.push({
            id: `${wall.id}-op-${idx}-jamb-l`,
            elementId: op.opId,
            position: [opx - dirX * off, jambVertCenter, opy - dirY * off],
            args: [JAMB_W, JAMB_DEPTH, jambHeight],
            rotationY: -angle,
            type: "jamb",
          });
          list.push({
            id: `${wall.id}-op-${idx}-jamb-r`,
            elementId: op.opId,
            position: [opx + dirX * off, jambVertCenter, opy + dirY * off],
            args: [JAMB_W, JAMB_DEPTH, jambHeight],
            rotationY: -angle,
            type: "jamb",
          });
        }

        currentT = op.tEnd;
      });

      // 3. Tramo sólido final después de la última abertura
      if (currentT < 1.0) {
        const subLen = (1.0 - currentT) * length;
        if (subLen > 0.05) {
          const midT = (currentT + 1.0) / 2;
          const mx = wx1 + midT * dx;
          const my = wy1 + midT * dy;
          list.push({
            id: `${wall.id}-segment-last-solid`,
            elementId: wall.id,
            position: [mx, height / 2, my],
            args: [subLen, WALL_THICKNESS, height],
            rotationY: -angle,
            type: "solid",
          });
        }
      }
    });

    return list;
  }, [walls, openings, scale, bounds]);

  // Renderizar suelos de los cuartos (extrusión plana 2D)
  const roomFloors = useMemo(() => {
    const list: Array<{
      id: string;
      elementId: number;
      shape: THREE.Shape;
      label: string;
      area: number;
    }> = [];

    rooms.forEach((room) => {
      const pts = room.geometry.points;
      if (pts.length < 6) return;

      const shape = new THREE.Shape();
      const x0 = pts[0] / scale - bounds.cx;
      const y0 = pts[1] / scale - bounds.cy;
      shape.moveTo(x0, y0);

      for (let i = 2; i < pts.length; i += 2) {
        const x = pts[i] / scale - bounds.cx;
        const y = pts[i + 1] / scale - bounds.cy;
        shape.lineTo(x, y);
      }
      shape.closePath();

      list.push({
        id: String(room.id),
        elementId: room.id,
        shape,
        label: room.geometry.label || "Recinto",
        area: room.area_m2 || 0,
      });
    });

    return list;
  }, [rooms, scale, bounds]);

  // Columnas 3D
  const columnMeshes = useMemo(() => {
    const list: Array<{
      id: string;
      elementId: number;
      shape: THREE.Shape;
      height: number;
    }> = [];
    columns.forEach((col) => {
      const pts = col.geometry.points;
      if (pts.length < 2) return;
      
      const shape = new THREE.Shape();
      if (pts.length === 2) {
        // Columna de punto (1 clic) -> Generamos un prisma cuadrado de 30x30 cm
        const cx = pts[0] / scale - bounds.cx;
        const cy = pts[1] / scale - bounds.cy;
        const r = 0.15; // 15 cm de radio -> 30 cm de lado
        shape.moveTo(cx - r, cy - r);
        shape.lineTo(cx + r, cy - r);
        shape.lineTo(cx + r, cy + r);
        shape.lineTo(cx - r, cy + r);
      } else {
        // Columna de polígono antiguo (fallback)
        shape.moveTo(pts[0] / scale - bounds.cx, pts[1] / scale - bounds.cy);
        for (let i = 2; i < pts.length; i += 2) {
          shape.lineTo(pts[i] / scale - bounds.cx, pts[i + 1] / scale - bounds.cy);
        }
      }
      shape.closePath();
      list.push({
        id: String(col.id),
        elementId: col.id,
        shape,
        height: safeMeters(col.height_m, 2.8, 0.5, 12),
      });
    });
    return list;
  }, [columns, scale, bounds]);

  // Techos / Losas 3D
  const roofMeshes = useMemo(() => {
    const list: Array<{
      id: string;
      elementId: number;
      shape: THREE.Shape;
      thickness: number;
      elevation: number;
    }> = [];
    // Elevación = altura promedio de muros (la losa apoya en su cara
    // superior). Antes era fijo en 2.8.
    const wallHeightsForRoof = walls
      .map((w) => safeMeters(w.height_m, NaN, 0.5, 12))
      .filter((h) => Number.isFinite(h));
    const refElevation = wallHeightsForRoof.length > 0
      ? wallHeightsForRoof.reduce((a, b) => a + b, 0) / wallHeightsForRoof.length
      : 2.8;
    roofs.forEach((roof) => {
      const pts = roof.geometry.points;
      if (pts.length < 6) return;
      const shape = new THREE.Shape();
      shape.moveTo(pts[0] / scale - bounds.cx, pts[1] / scale - bounds.cy);
      for (let i = 2; i < pts.length; i += 2) {
        shape.lineTo(pts[i] / scale - bounds.cx, pts[i + 1] / scale - bounds.cy);
      }
      shape.closePath();
      list.push({
        id: String(roof.id),
        elementId: roof.id,
        shape,
        thickness: safeMeters(roof.height_m, 0.15, 0.05, 1.0),
        elevation: refElevation,
      });
    });
    return list;
  }, [roofs, walls, scale, bounds]);

  // Vigas 3D — la elevación de la viga apoya en la cara superior de los
  // muros. Antes asumíamos `wallH = 2.8` hardcoded; eso colgaba las vigas
  // en el aire si los muros eran 5.6m (doble altura) o las hundía si eran
  // 2.4m. Ahora calculamos el alto típico de muros del plano y lo usamos
  // como referencia.
  const beamMeshes = useMemo(() => {
    // Promedio de alturas de muros válidas; cae a 2.8 si no hay muros.
    const wallHeights = walls
      .map((w) => safeMeters(w.height_m, NaN, 0.5, 12))
      .filter((h) => Number.isFinite(h));
    const refWallH = wallHeights.length > 0
      ? wallHeights.reduce((a, b) => a + b, 0) / wallHeights.length
      : 2.8;

    const list: Array<{
      id: string;
      elementId: number;
      position: [number, number, number];
      args: [number, number, number];
      rotationY: number;
    }> = [];
    beams.forEach((beam) => {
      const pts = beam.geometry.points;
      if (pts.length < 4) return;
      const bx1 = pts[0] / scale - bounds.cx;
      const by1 = pts[1] / scale - bounds.cy;
      const bx2 = pts[2] / scale - bounds.cx;
      const by2 = pts[3] / scale - bounds.cy;
      const dx = bx2 - bx1;
      const dy = by2 - by1;
      const length = Math.sqrt(dx * dx + dy * dy);
      if (length === 0) return;
      const angle = Math.atan2(dy, dx);
      const beamH = safeMeters(beam.height_m, 0.40, 0.1, 3);
      const elev = refWallH - beamH / 2;
      list.push({
        id: String(beam.id),
        elementId: beam.id,
        position: [bx1 + dx / 2, elev, by1 + dy / 2],
        args: [length, 0.15, beamH],
        rotationY: -angle,
      });
    });
    return list;
  }, [beams, walls, scale, bounds]);

  // Texturas procedurales — se crean una sola vez por instancia.
  // En blueprint mode se ignoran (usamos colores planos para mantener el
  // look CAD abstracto).
  const textures = useMemo<ProceduralTextures>(() => createTextures(), []);
  const useTex = styleMode === "plaster";

  // Preset de cámara seleccionado por el usuario. `null` = no se forzó nada,
  // queda en control libre del OrbitControls. Cuando seteamos uno, el
  // `CameraRig` (dentro del Canvas) anima hasta esa pose y vuelve a null.
  const [cameraPreset, setCameraPreset] = useState<CameraPreset | null>(null);
  function applyPreset(p: CameraPreset) {
    setCameraPreset(null);
    // Forzar un re-trigger aunque sea el mismo preset (microtask).
    setTimeout(() => setCameraPreset(p), 0);
  }

  // Selección: el id del elemento clickeado en 3D. Al hover, lo destacamos.
  // El info panel flotante usa selectedId para mostrar tipo, dimensiones y
  // materiales. Click en vacío deselecciona.
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const selectedElement = useMemo(
    () => (selectedId != null ? pageElements.find((e) => e.id === selectedId) ?? null : null),
    [selectedId, pageElements],
  );
  function handlePick(elementId: number | null, e?: { stopPropagation: () => void }) {
    if (e) e.stopPropagation();
    setSelectedId(elementId);
  }

  // Props que se aplican a cada mesh para que sea pickable: click + hover +
  // cursor pointer. `domElement` se setea desde el sub-componente del cursor
  // dentro del Canvas.
  function pickHandlers(elementId: number) {
    return {
      onClick: (e: { stopPropagation: () => void }) => handlePick(elementId, e),
      onPointerOver: (e: { stopPropagation: () => void }) => {
        e.stopPropagation();
        setHoveredId(elementId);
      },
      onPointerOut: (e: { stopPropagation: () => void }) => {
        e.stopPropagation();
        setHoveredId((id) => (id === elementId ? null : id));
      },
    };
  }

  // Color emisivo del overlay de selección/hover. Devuelve null si el mesh no
  // está ni seleccionado ni hovered (caso común — usa material normal).
  function pickEmissive(elementId: number): { color: string; intensity: number } | null {
    if (selectedId === elementId) return { color: "#22d3ee", intensity: 0.6 };
    if (hoveredId === elementId) return { color: "#ffffff", intensity: 0.18 };
    return null;
  }

  // Colores y Materiales según el modo seleccionado
  const theme = useMemo(() => {
    const isBlue = styleMode === "blueprint";
    return {
      bg: isBlue ? "#080d16" : "#f1f5f9",
      grid: isBlue ? "#16253c" : "#cbd5e1",
      wallColor: isBlue ? "#14b8a6" : "#ffffff",
      wallOpacity: isBlue ? 0.35 : 1.0,
      wallBorderColor: isBlue ? "#22d3ee" : "#475569",
      lintelColor: isBlue ? "#0891b2" : "#e2e8f0",
      lintelOpacity: isBlue ? 0.35 : 1.0,
      sillColor: isBlue ? "#0d9488" : "#ffffff",
      sillOpacity: isBlue ? 0.35 : 1.0,
      glassColor: isBlue ? "#38bdf8" : "#93c5fd",
      glassOpacity: isBlue ? 0.6 : 0.4,
      floorColor: isBlue ? "#1e293b" : "#e2e8f0",
      floorOpacity: isBlue ? 0.2 : 0.8,
    };
  }, [styleMode]);

  return (
    <div
      className="relative w-full h-full flex flex-col overflow-hidden bg-slate-100 dark:bg-slate-950"
      style={{ cursor: hoveredId != null ? "pointer" : "default" }}
    >
      {/* Controles Flotantes 3D */}
      <div className="absolute top-4 left-4 z-30 flex items-center gap-2 rounded-xl bg-white/90 dark:bg-slate-900/95 backdrop-blur border border-slate-200 dark:border-slate-700 px-3 py-2 shadow-2xl">
        <span className="text-xs font-bold text-slate-600 dark:text-slate-300 mr-2">Estilo 3D:</span>
        <button
          onClick={() => setStyleMode("blueprint")}
          className={`text-[10px] uppercase tracking-wider font-extrabold px-2.5 py-1.5 rounded-md transition-all ${
            styleMode === "blueprint"
              ? "bg-cyan-500 text-slate-950 shadow"
              : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
          }`}
        >
          CAD Blueprint
        </button>
        <button
          onClick={() => setStyleMode("plaster")}
          className={`text-[10px] uppercase tracking-wider font-extrabold px-2.5 py-1.5 rounded-md transition-all ${
            styleMode === "plaster"
              ? "bg-cyan-500 text-slate-950 shadow"
              : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
          }`}
        >
          Render Blanco
        </button>
      </div>

      <div className="absolute top-4 right-4 z-30 flex items-center gap-2">
        {/* Presets de cámara */}
        <div className="flex items-center gap-1 rounded-xl bg-white/90 dark:bg-slate-900/95 backdrop-blur border border-slate-200 dark:border-slate-700 px-1.5 py-1.5 shadow-2xl">
          <span className="text-[10px] uppercase tracking-wider font-bold text-slate-500 dark:text-slate-400 px-1.5">Vista</span>
          <PresetButton onClick={() => applyPreset("plan")} title="Planta cenital">Planta</PresetButton>
          <PresetButton onClick={() => applyPreset("iso")} title="Vista isométrica">Iso</PresetButton>
          <PresetButton onClick={() => applyPreset("front")} title="Fachada frontal">Frente</PresetButton>
          <PresetButton onClick={() => applyPreset("side")} title="Fachada lateral">Lateral</PresetButton>
          <PresetButton onClick={() => applyPreset("reset")} title="Restaurar vista inicial">Reset</PresetButton>
        </div>
        <button
          onClick={onClose}
          className="text-xs font-extrabold bg-red-600 hover:bg-red-500 text-white px-3.5 py-2 rounded-xl transition-all shadow-lg flex items-center gap-1.5"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
          Volver a 2D
        </button>
      </div>

      {/* Escena Canvas 3D */}
      <div className="flex-1 w-full h-full relative" style={{ backgroundColor: theme.bg }}>
        <Canvas
          camera={{ position: [0, bounds.maxDim * 0.8, bounds.maxDim * 1.1], fov: 45 }}
          shadows={{ type: THREE.PCFSoftShadowMap }}
          gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: useTex ? 1.05 : 1.0 }}
          onPointerMissed={() => setSelectedId(null)}
        >
          <color attach="background" args={[theme.bg]} />

          {/* Ambient bajo: el grueso de la luz lo aporta hemisphere + directional */}
          <ambientLight intensity={useTex ? 0.25 : 0.7} />

          {/* HemisphereLight: simula cielo (arriba) y rebote del piso (abajo).
              Le da volumen y suaviza sombras duras. */}
          <hemisphereLight
            args={[
              useTex ? "#e8f1ff" : "#ffffff",
              useTex ? "#d6cfb4" : "#cbd5e1",
              useTex ? 0.55 : 0.35,
            ]}
          />

          {/* Luz direccional principal (sol) — con sombras suaves */}
          <directionalLight
            position={[bounds.maxDim * 0.6, bounds.maxDim * 1.5, bounds.maxDim * 0.8]}
            intensity={useTex ? 1.15 : 0.8}
            castShadow
            shadow-mapSize={[2048, 2048]}
            shadow-bias={-0.0005}
            shadow-camera-left={-bounds.maxDim}
            shadow-camera-right={bounds.maxDim}
            shadow-camera-top={bounds.maxDim}
            shadow-camera-bottom={-bounds.maxDim}
            shadow-camera-near={0.1}
            shadow-camera-far={bounds.maxDim * 4}
          />

          {/* Luz de relleno opuesta — sutil, para que el lado opuesto no quede negro */}
          {useTex && (
            <directionalLight
              position={[-bounds.maxDim * 0.5, bounds.maxDim * 0.7, -bounds.maxDim * 0.5]}
              intensity={0.25}
            />
          )}

          <group rotation={[-Math.PI / 2, 0, 0]}>
            {/* Ground plane neutro que recibe sombras (solo en plaster) */}
            {useTex && (
              <mesh
                receiveShadow
                position={[0, 0, -0.02]}
                rotation={[0, 0, 0]}
              >
                <planeGeometry args={[bounds.maxDim * 6, bounds.maxDim * 6]} />
                <meshStandardMaterial color="#dad6cc" roughness={1.0} metalness={0.0} />
              </mesh>
            )}
            {/* Grid sutil (más visible en blueprint, opacidad baja en plaster) */}
            <gridHelper
              args={[
                bounds.maxDim * 3,
                Math.round(bounds.maxDim * 1.5),
                theme.grid,
                theme.grid,
              ]}
              position={[0, 0, useTex ? 0.001 : -0.01]}
              rotation={[Math.PI / 2, 0, 0]}
            />

            {/* Suelos de Recintos */}
            {roomFloors.map((rf) => {
              const em = pickEmissive(rf.elementId);
              return (
                <mesh
                  key={rf.id}
                  receiveShadow
                  position={[0, 0, 0.005]}
                  {...pickHandlers(rf.elementId)}
                >
                  <extrudeGeometry
                    args={[rf.shape, { depth: 0.04, bevelEnabled: false }]}
                  />
                  <meshStandardMaterial
                    color={useTex ? "#ffffff" : theme.floorColor}
                    map={useTex ? textures.wood : undefined}
                    roughness={0.7}
                    metalness={0.05}
                    transparent={styleMode === "blueprint"}
                    opacity={theme.floorOpacity}
                    emissive={em ? em.color : "#000000"}
                    emissiveIntensity={em ? em.intensity : 0}
                  />
                </mesh>
              );
            })}

            {/* Columnas — hormigón visto en plaster, color plano en blueprint */}
            {columnMeshes.map((cm) => {
              const em = pickEmissive(cm.elementId);
              return (
                <mesh
                  key={cm.id}
                  castShadow
                  receiveShadow
                  position={[0, 0, 0]}
                  {...pickHandlers(cm.elementId)}
                >
                  <extrudeGeometry
                    args={[cm.shape, { depth: cm.height, bevelEnabled: false }]}
                  />
                  <meshStandardMaterial
                    color={styleMode === "blueprint" ? "#EC4899" : "#dcdcd8"}
                    map={useTex ? textures.concrete : undefined}
                    roughness={0.85}
                    metalness={0.0}
                    transparent={styleMode === "blueprint"}
                    opacity={styleMode === "blueprint" ? 0.45 : 1.0}
                    emissive={em ? em.color : "#000000"}
                    emissiveIntensity={em ? em.intensity : 0}
                  />
                </mesh>
              );
            })}

            {/* Techos / Losas — hormigón armado */}
            {roofMeshes.map((rm) => {
              const em = pickEmissive(rm.elementId);
              return (
                <mesh
                  key={rm.id}
                  castShadow
                  receiveShadow
                  position={[0, 0, rm.elevation]}
                  {...pickHandlers(rm.elementId)}
                >
                  <extrudeGeometry
                    args={[rm.shape, { depth: rm.thickness, bevelEnabled: false }]}
                  />
                  <meshStandardMaterial
                    color={styleMode === "blueprint" ? "#0D9488" : "#c8c8c2"}
                    map={useTex ? textures.concrete : undefined}
                    roughness={0.9}
                    metalness={0.0}
                    transparent={styleMode === "blueprint"}
                    opacity={styleMode === "blueprint" ? 0.35 : 1.0}
                    emissive={em ? em.color : "#000000"}
                    emissiveIntensity={em ? em.intensity : 0}
                  />
                </mesh>
              );
            })}

            {/* Vigas — hormigón */}
            {beamMeshes.map((bm) => {
              const em = pickEmissive(bm.elementId);
              return (
                <mesh
                  key={bm.id}
                  position={[bm.position[0], bm.position[2], bm.position[1]]}
                  rotation={[0, 0, bm.rotationY]}
                  castShadow
                  receiveShadow
                  {...pickHandlers(bm.elementId)}
                >
                  <boxGeometry args={bm.args} />
                  <meshStandardMaterial
                    color={styleMode === "blueprint" ? "#7C3AED" : "#d0d0ca"}
                    map={useTex ? textures.concrete : undefined}
                    transparent={styleMode === "blueprint"}
                    opacity={styleMode === "blueprint" ? 0.45 : 1.0}
                    roughness={0.85}
                    metalness={0.0}
                    emissive={em ? em.color : "#000000"}
                    emissiveIntensity={em ? em.intensity : 0}
                  />
                </mesh>
              );
            })}

            {/* Muros extruidos (subdivididos) */}
            {wallMeshes.map((mesh) => {
              const color =
                mesh.type === "glass"
                  ? theme.glassColor
                  : mesh.type === "lintel"
                    ? theme.lintelColor
                    : mesh.type === "sill"
                      ? theme.sillColor
                      : mesh.type === "jamb"
                        ? styleMode === "blueprint" ? "#cffafe" : "#7a6a5a"
                        : theme.wallColor;

              const opacity =
                mesh.type === "glass"
                  ? theme.glassOpacity
                  : mesh.type === "lintel"
                    ? theme.lintelOpacity
                    : mesh.type === "sill"
                      ? theme.sillOpacity
                      : mesh.type === "jamb"
                        ? styleMode === "blueprint" ? 0.5 : 1.0
                        : theme.wallOpacity;

              // jamb usa textura tipo aluminio/madera: probamos con concrete
              // para sensación de aluminio anodizado. Si en el futuro
              // distinguimos por subtype, podemos cambiar entre concrete (alu)
              // y wood.
              const map =
                useTex && mesh.type !== "glass"
                  ? mesh.type === "jamb"
                    ? textures.concrete
                    : textures.plaster
                  : undefined;

              const em = pickEmissive(mesh.elementId);
              return (
                <mesh
                  key={mesh.id}
                  position={[mesh.position[0], mesh.position[2], mesh.position[1]]}
                  rotation={[0, 0, mesh.rotationY]}
                  castShadow
                  receiveShadow
                  {...pickHandlers(mesh.elementId)}
                >
                  <boxGeometry args={mesh.args} />
                  <meshStandardMaterial
                    color={color}
                    map={map}
                    transparent={styleMode === "blueprint" || mesh.type === "glass"}
                    opacity={opacity}
                    roughness={
                      mesh.type === "glass" ? 0.05 : mesh.type === "jamb" ? 0.5 : 0.85
                    }
                    metalness={
                      mesh.type === "glass" ? 0.95 : mesh.type === "jamb" ? 0.4 : 0.0
                    }
                    envMapIntensity={mesh.type === "glass" ? 1.5 : 0.6}
                    emissive={em ? em.color : "#000000"}
                    emissiveIntensity={em ? em.intensity : 0}
                  />
                  {/* Bordes brillantes en estilo Blueprint */}
                  {styleMode === "blueprint" && mesh.type !== "glass" && (
                    <lineSegments>
                      <edgesGeometry args={[new THREE.BoxGeometry(...mesh.args)]} />
                      <lineBasicMaterial color={theme.wallBorderColor} linewidth={1} />
                    </lineSegments>
                  )}
                </mesh>
              );
            })}
          </group>

          <OrbitControls
            makeDefault
            enableDamping
            dampingFactor={0.05}
            maxPolarAngle={Math.PI / 2 - 0.02} // Evita ir por debajo del suelo
            minDistance={2}
            maxDistance={bounds.maxDim * 3}
          />
          <CameraRig preset={cameraPreset} maxDim={bounds.maxDim} />
        </Canvas>
      </div>

      {/* Info panel del elemento seleccionado — flota abajo-derecha */}
      {selectedElement && (
        <SelectionInfoPanel
          element={selectedElement}
          onClose={() => setSelectedId(null)}
          onUpdateElement={onUpdateElement}
        />
      )}

      {/* Indicador de ayuda */}
      <div className="absolute bottom-4 left-4 z-30 rounded-lg bg-white/80 dark:bg-slate-900/85 backdrop-blur px-3 py-1.5 border border-slate-200 dark:border-slate-700/60 text-[10px] text-slate-500 dark:text-slate-400 font-medium">
        Click: seleccionar elemento · Orbitar arrastrando · Scroll: zoom
      </div>
    </div>
  );
}

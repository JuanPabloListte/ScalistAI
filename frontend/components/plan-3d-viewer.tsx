"use client";

import React, { useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { DetectedElement } from "@/lib/api";

interface Plan3DViewerProps {
  elements: DetectedElement[];
  scale: number; // px_per_m
  page: number;
  onClose: () => void;
}

export default function Plan3DViewer({ elements, scale, page, onClose }: Plan3DViewerProps) {
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

  // 1. Filtrar los elementos por página
  const pageElements = useMemo(() => {
    return elements.filter((el) => el.page === page);
  }, [elements, page]);

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
    const list: Array<{
      id: string;
      position: [number, number, number];
      args: [number, number, number];
      rotationY: number;
      type: "solid" | "lintel" | "sill" | "glass";
    }> = [];

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
      const height = wall.height_m || 2.8;

      // Buscar aberturas sobre este muro
      const wallOpenings: Array<{
        tStart: number;
        tEnd: number;
        subtype: string;
        width_m: number;
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
            wallOpenings.push({ tStart, tEnd, subtype: op.geometry.subtype || "door", width_m: w_m });
          }
        }
      });

      // Si no hay aberturas en este muro, renderizarlo sólido completo
      if (wallOpenings.length === 0) {
        const mx = wx1 + dx / 2;
        const my = wy1 + dy / 2;
        list.push({
          id: `${wall.id}-solid`,
          position: [mx, height / 2, my],
          args: [length, height, WALL_THICKNESS],
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
              position: [mx, height / 2, my],
              args: [subLen, height, WALL_THICKNESS],
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
              position: [opx, windowSillHeight / 2, opy],
              args: [opLen, windowSillHeight, WALL_THICKNESS],
              rotationY: -angle,
              type: "sill",
            });
          }
          // Bloque sobre la ventana (Header/Dintel)
          if (height > windowHeaderHeight) {
            const topHeight = height - windowHeaderHeight;
            list.push({
              id: `${wall.id}-op-${idx}-header`,
              position: [opx, windowHeaderHeight + topHeight / 2, opy],
              args: [opLen, topHeight, WALL_THICKNESS],
              rotationY: -angle,
              type: "lintel",
            });
          }
          // Panel de vidrio translúcido
          const glassHeight = windowHeaderHeight - windowSillHeight;
          list.push({
            id: `${wall.id}-op-${idx}-glass`,
            position: [opx, windowSillHeight + glassHeight / 2, opy],
            args: [opLen, glassHeight, WALL_THICKNESS * 0.2],
            rotationY: -angle,
            type: "glass",
          });
        } else {
          // Es una puerta: solo bloque superior (lintel)
          if (height > doorHeight) {
            const topHeight = height - doorHeight;
            list.push({
              id: `${wall.id}-op-${idx}-lintel`,
              position: [opx, doorHeight + topHeight / 2, opy],
              args: [opLen, topHeight, WALL_THICKNESS],
              rotationY: -angle,
              type: "lintel",
            });
          }
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
            position: [mx, height / 2, my],
            args: [subLen, height, WALL_THICKNESS],
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
        shape,
        height: col.height_m || 2.8,
      });
    });
    return list;
  }, [columns, scale, bounds]);

  // Techos / Losas 3D
  const roofMeshes = useMemo(() => {
    const list: Array<{
      id: string;
      shape: THREE.Shape;
      thickness: number;
      elevation: number;
    }> = [];
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
        shape,
        thickness: 0.15,
        elevation: 2.8,
      });
    });
    return list;
  }, [roofs, scale, bounds]);

  // Vigas 3D
  const beamMeshes = useMemo(() => {
    const list: Array<{
      id: string;
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
      const beamH = beam.height_m || 0.40;
      const wallH = 2.8;
      const elev = wallH - beamH / 2;
      list.push({
        id: String(beam.id),
        position: [bx1 + dx / 2, elev, by1 + dy / 2],
        args: [length, beamH, 0.15],
        rotationY: -angle,
      });
    });
    return list;
  }, [beams, scale, bounds]);

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
    <div className="relative w-full h-full flex flex-col overflow-hidden bg-slate-100 dark:bg-slate-950">
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
          shadows
        >
          <color attach="background" args={[theme.bg]} />
          <ambientLight intensity={styleMode === "blueprint" ? 0.7 : 0.6} />

          {/* Luz direccional que genera profundidad */}
          <directionalLight
            position={[bounds.maxDim * 0.5, bounds.maxDim * 1.5, bounds.maxDim * 0.8]}
            intensity={styleMode === "blueprint" ? 0.8 : 1.2}
            castShadow
            shadow-mapSize={[2048, 2048]}
          />

          <group rotation={[-Math.PI / 2, 0, 0]}>
            {/* Suelo base del plano */}
            <gridHelper
              args={[bounds.maxDim * 3, Math.round(bounds.maxDim * 1.5), theme.grid, theme.grid]}
              position={[0, 0, -0.01]}
              rotation={[Math.PI / 2, 0, 0]}
            />

            {/* Suelos de Recintos */}
            {roomFloors.map((rf) => (
              <mesh key={rf.id} receiveShadow position={[0, 0, 0.005]}>
                <extrudeGeometry
                  args={[
                    rf.shape,
                    {
                      depth: 0.04,
                      bevelEnabled: false,
                    },
                  ]}
                />
                <meshStandardMaterial
                  color={theme.floorColor}
                  roughness={0.6}
                  metalness={0.1}
                  transparent={styleMode === "blueprint"}
                  opacity={theme.floorOpacity}
                />
              </mesh>
            ))}

            {/* Columnas */}
            {columnMeshes.map((cm) => (
              <mesh key={cm.id} castShadow receiveShadow position={[0, 0, 0]}>
                <extrudeGeometry
                  args={[
                    cm.shape,
                    {
                      depth: cm.height,
                      bevelEnabled: false,
                    },
                  ]}
                />
                <meshStandardMaterial
                  color={styleMode === "blueprint" ? "#EC4899" : "#CBD5E1"}
                  roughness={0.5}
                  metalness={0.1}
                  transparent={styleMode === "blueprint"}
                  opacity={styleMode === "blueprint" ? 0.45 : 1.0}
                />
              </mesh>
            ))}

            {/* Techos / Losas */}
            {roofMeshes.map((rm) => (
              <mesh key={rm.id} castShadow receiveShadow position={[0, 0, rm.elevation]}>
                <extrudeGeometry
                  args={[
                    rm.shape,
                    {
                      depth: rm.thickness,
                      bevelEnabled: false,
                    },
                  ]}
                />
                <meshStandardMaterial
                  color={styleMode === "blueprint" ? "#0D9488" : "#E2E8F0"}
                  roughness={0.6}
                  metalness={0.1}
                  transparent={styleMode === "blueprint"}
                  opacity={styleMode === "blueprint" ? 0.35 : 1.0}
                />
              </mesh>
            ))}

            {/* Vigas */}
            {beamMeshes.map((bm) => (
              <mesh
                key={bm.id}
                position={[bm.position[0], bm.position[2], bm.position[1]]}
                rotation={[Math.PI / 2, 0, bm.rotationY]}
                castShadow
                receiveShadow
              >
                <boxGeometry args={bm.args} />
                <meshStandardMaterial
                  color={styleMode === "blueprint" ? "#7C3AED" : "#E2E8F0"}
                  transparent={styleMode === "blueprint"}
                  opacity={styleMode === "blueprint" ? 0.45 : 1.0}
                  roughness={0.5}
                  metalness={0.1}
                />
              </mesh>
            ))}

            {/* Muros extruidos (subdivididos) */}
            {wallMeshes.map((mesh) => {
              const color =
                mesh.type === "glass"
                  ? theme.glassColor
                  : mesh.type === "lintel"
                    ? theme.lintelColor
                    : mesh.type === "sill"
                      ? theme.sillColor
                      : theme.wallColor;

              const opacity =
                mesh.type === "glass"
                  ? theme.glassOpacity
                  : mesh.type === "lintel"
                    ? theme.lintelOpacity
                    : mesh.type === "sill"
                      ? theme.sillOpacity
                      : theme.wallOpacity;

              return (
                <mesh
                  key={mesh.id}
                  position={[mesh.position[0], mesh.position[2], mesh.position[1]]}
                  rotation={[Math.PI / 2, 0, mesh.rotationY]}
                  castShadow
                  receiveShadow
                >
                  <boxGeometry args={mesh.args} />
                  <meshStandardMaterial
                    color={color}
                    transparent={styleMode === "blueprint" || mesh.type === "glass"}
                    opacity={opacity}
                    roughness={mesh.type === "glass" ? 0.1 : 0.5}
                    metalness={mesh.type === "glass" ? 0.9 : 0.0}
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
            enableDamping
            dampingFactor={0.05}
            maxPolarAngle={Math.PI / 2 - 0.02} // Evita ir por debajo del suelo
            minDistance={2}
            maxDistance={bounds.maxDim * 3}
          />
        </Canvas>
      </div>

      {/* Indicador de ayuda */}
      <div className="absolute bottom-4 left-4 z-30 rounded-lg bg-white/80 dark:bg-slate-900/85 backdrop-blur px-3 py-1.5 border border-slate-200 dark:border-slate-700/60 text-[10px] text-slate-500 dark:text-slate-400 font-medium">
        Click Izquierdo: Orbitar | Click Derecho / Shift + Click: Mover cámara | Scroll: Zoom
      </div>
    </div>
  );
}

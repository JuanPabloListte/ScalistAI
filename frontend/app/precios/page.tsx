"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { api, type PriceSeriesPoint, type PriceSeriesProduct } from "@/lib/api";

function fmtARS(n: number): string {
  return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(Math.round(n));
}

// Punto proyectado para el gráfico: última fecha real + horizonte (meses).
function projectionOf(p: PriceSeriesProduct): { t: number; price: number } | null {
  if (p.forecast_method === "sin_dato" || p.points.length === 0) return null;
  const lastDate = p.points[p.points.length - 1].date;
  const d = new Date(lastDate);
  d.setMonth(d.getMonth() + p.horizon_months);
  return { t: d.getTime(), price: p.projected_price };
}

// Color por proveedor/fuente — deja ver la dispersión entre cotizaciones.
function sourceColor(source: string): string {
  const s = source.toLowerCase();
  if (s.includes("cormac")) return "#f59e0b";
  if (s.includes("carignani")) return "#3b82f6";
  if (s.includes("2448")) return "#10b981";
  if (s.includes("zárate") || s.includes("zarate")) return "#8b5cf6";
  if (s.includes("ferrocons")) return "#f43f5e";
  return "#94a3b8";
}

function PriceChart({ points, projection }: {
  points: PriceSeriesPoint[];
  projection: { t: number; price: number } | null;
}) {
  const W = 560, H = 140, PAD_L = 10, PAD_R = 10, PAD_T = 14, PAD_B = 24;
  const pts = [...points].sort((a, b) => a.date.localeCompare(b.date));
  const ts = pts.map((p) => new Date(p.date).getTime());
  const prices = pts.map((p) => p.price);
  // El dominio incluye el punto proyectado (futuro y, normalmente, mayor precio).
  const extraT = projection ? [projection.t] : [];
  const extraP = projection ? [projection.price] : [];
  const tMin = Math.min(...ts), tMax = Math.max(...ts, ...extraT);
  const pMin = Math.min(...prices, ...extraP), pMax = Math.max(...prices, ...extraP);
  const x = (t: number) =>
    PAD_L + (tMax === tMin ? (W - PAD_L - PAD_R) / 2 : ((t - tMin) / (tMax - tMin)) * (W - PAD_L - PAD_R));
  const y = (p: number) =>
    PAD_T + (pMax === pMin ? (H - PAD_T - PAD_B) / 2 : (1 - (p - pMin) / (pMax - pMin)) * (H - PAD_T - PAD_B));

  // Línea de tendencia: media por fecha única (evita zigzag entre proveedores del mismo día).
  const byDate = new Map<string, number[]>();
  pts.forEach((p) => {
    const a = byDate.get(p.date) ?? [];
    a.push(p.price);
    byDate.set(p.date, a);
  });
  const verts = [...byDate.entries()]
    .map(([d, arr]) => ({ t: new Date(d).getTime(), p: arr.reduce((s, v) => s + v, 0) / arr.length, d }))
    .sort((a, b) => a.t - b.t);
  const path = verts.map((v, i) => `${i ? "L" : "M"}${x(v.t).toFixed(1)},${y(v.p).toFixed(1)}`).join(" ");
  const last = verts[verts.length - 1];

  // Etiqueta de año en la x de su primera aparición.
  const yearAt = new Map<number, number>();
  verts.forEach((v) => {
    const yr = new Date(v.d).getFullYear();
    if (!yearAt.has(yr)) yearAt.set(yr, v.t);
  });

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img">
      {/* línea de tendencia (histórico real) */}
      {verts.length > 1 && (
        <path d={path} fill="none" stroke="#64748b" strokeWidth={1.5} />
      )}
      {/* tramo de proyección (punteado, ámbar) */}
      {projection && (
        <>
          <path d={`M${x(last.t)},${y(last.p)} L${x(projection.t)},${y(projection.price)}`}
                fill="none" stroke="#f59e0b" strokeWidth={1.5} strokeDasharray="4 3" />
          <circle cx={x(projection.t)} cy={y(projection.price)} r={4} fill="none"
                  stroke="#f59e0b" strokeWidth={1.5}>
            <title>{`proyectado · $${fmtARS(projection.price)}`}</title>
          </circle>
          <text x={x(projection.t)} y={y(projection.price) - 8} fontSize={11}
                fill="#d97706" textAnchor="end" fontWeight={600}>
            ${fmtARS(projection.price)}
          </text>
        </>
      )}
      {/* puntos reales (uno por cotización, color por fuente) */}
      {pts.map((p, i) => (
        <circle key={i} cx={x(ts[i])} cy={y(p.price)} r={4} fill={sourceColor(p.source)} stroke="white" strokeWidth={1}>
          <title>{`${p.date} · $${fmtARS(p.price)} · ${p.source}`}</title>
        </circle>
      ))}
      {/* etiqueta primer y último precio real */}
      <text x={x(verts[0].t)} y={y(verts[0].p) - 8} fontSize={11} fill="#94a3b8" textAnchor="middle">
        ${fmtARS(verts[0].p)}
      </text>
      {verts.length > 1 && (
        <text x={x(last.t)} y={y(last.p) - 8} fontSize={11}
              fill="#0f172a" textAnchor="middle" className="dark:fill-white" fontWeight={600}>
          ${fmtARS(last.p)}
        </text>
      )}
      {/* eje X: años */}
      {[...yearAt.entries()].map(([yr, t]) => (
        <text key={yr} x={x(t)} y={H - 6} fontSize={11} fill="#94a3b8" textAnchor="middle">
          {yr}
        </text>
      ))}
    </svg>
  );
}

export default function PreciosPage() {
  const router = useRouter();
  const [products, setProducts] = useState<PriceSeriesProduct[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getPriceSeries()
      .then(setProducts)
      .catch((e) => setError(String(e?.message ?? e)));
  }, []);

  if (error) {
    return <div className="p-8 text-red-600">{error}</div>;
  }
  if (!products) {
    return <div className="p-8 text-slate-500">Cargando…</div>;
  }

  // Agrupa por categoría.
  const byCategory = new Map<string, PriceSeriesProduct[]>();
  for (const p of products) {
    const a = byCategory.get(p.category) ?? [];
    a.push(p);
    byCategory.set(p.category, a);
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div>
        <button onClick={() => router.push("/")}
                className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Volver
        </button>
        <h1 className="mt-1 text-2xl font-bold text-slate-900 dark:text-white">Inteligencia de Precios</h1>
        <p className="text-sm text-slate-500">
          Evolución histórica REAL de tus materiales · {products.length} productos · datos de cotizaciones y proveedores
        </p>
      </div>

      {products.length === 0 && (
        <div className="rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
          Todavía no hay productos con serie de precios. Cargá precios y unilos con el matching de materiales.
        </div>
      )}

      {[...byCategory.entries()].map(([category, items]) => (
        <div key={category} className="space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{category}</h2>
          <div className="grid gap-4 md:grid-cols-2">
            {items.map((p) => (
              <div key={p.id} className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                <div className="mb-1 flex items-start justify-between gap-2">
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-white">{p.name}</h3>
                  {p.change_pct !== null && (
                    <span className={`shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold ${
                      p.change_pct >= 0
                        ? "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
                        : "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
                    }`}>
                      {p.change_pct >= 0 ? "+" : ""}{fmtARS(p.change_pct)}%
                    </span>
                  )}
                </div>
                <p className="mb-2 text-xs text-slate-400">
                  ${fmtARS(p.first_price)} → ${fmtARS(p.last_price)} / {p.unit} · {p.points.length} puntos
                </p>
                <PriceChart points={p.points} projection={projectionOf(p)} />
                {p.forecast_method !== "sin_dato" && (
                  <div className="mt-2 border-t border-slate-100 pt-2 text-xs dark:border-slate-800">
                    <div className="flex items-center justify-between">
                      <span className="text-slate-500">
                        Proyección {p.horizon_months}m
                        <span className="ml-1 text-slate-400">
                          ({p.forecast_method === "serie_propia" ? "según tu serie" : "según IPC"})
                        </span>
                      </span>
                      <span className="font-semibold text-amber-600 dark:text-amber-400">
                        ${fmtARS(p.projected_price)} (+{fmtARS(p.forecast_variation_pct)}%)
                      </span>
                    </div>
                    {p.beats_inflation !== null && p.ipc_monthly_rate !== null && (
                      <div className="mt-0.5 text-slate-400">
                        {(p.forecast_rate * 100).toFixed(1)}%/mes vs IPC {(p.ipc_monthly_rate * 100).toFixed(1)}%/mes ·{" "}
                        <span className={p.beats_inflation ? "text-amber-600 dark:text-amber-400" : "text-emerald-600 dark:text-emerald-400"}>
                          {p.beats_inflation ? "sube más que la inflación" : "por debajo de la inflación"}
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

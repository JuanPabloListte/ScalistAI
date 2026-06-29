"use client";

import { useEffect, useId, useState } from "react";
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
  const uid = useId().replace(/:/g, "");
  const W = 600, H = 172, PAD_L = 48, PAD_R = 56, PAD_T = 26, PAD_B = 30;
  const baseline = H - PAD_B;
  const pts = [...points].sort((a, b) => a.date.localeCompare(b.date));
  const ts = pts.map((p) => new Date(p.date).getTime());
  const prices = pts.map((p) => p.price);
  const extraT = projection ? [projection.t] : [];
  const extraP = projection ? [projection.price] : [];
  const tMin = Math.min(...ts), tMax = Math.max(...ts, ...extraT);
  const pMin = Math.min(...prices, ...extraP), pMax = Math.max(...prices, ...extraP);
  const x = (t: number) =>
    PAD_L + (tMax === tMin ? (W - PAD_L - PAD_R) / 2 : ((t - tMin) / (tMax - tMin)) * (W - PAD_L - PAD_R));
  const y = (p: number) =>
    PAD_T + (pMax === pMin ? (baseline - PAD_T) / 2 : (1 - (p - pMin) / (pMax - pMin)) * (baseline - PAD_T));

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
  const line = verts.map((v, i) => `${i ? "L" : "M"}${x(v.t).toFixed(1)},${y(v.p).toFixed(1)}`).join(" ");
  const area = `${line} L${x(verts[verts.length - 1].t).toFixed(1)},${baseline} L${x(verts[0].t).toFixed(1)},${baseline} Z`;
  const last = verts[verts.length - 1];

  // Anclaje de etiqueta según posición (evita que se corte en los bordes).
  const anchor = (xv: number): "start" | "middle" | "end" =>
    xv < PAD_L + 16 ? "start" : xv > W - PAD_R - 16 ? "end" : "middle";

  const yearAt = new Map<number, number>();
  verts.forEach((v) => {
    const yr = new Date(v.d).getFullYear();
    if (!yearAt.has(yr)) yearAt.set(yr, v.t);
  });

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img">
      <defs>
        <linearGradient id={`grad-${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#6366f1" stopOpacity={0.22} />
          <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
        </linearGradient>
      </defs>

      {/* grilla horizontal suave + precio en el eje Y */}
      {[0, 0.5, 1].map((f) => {
        const val = pMin + f * (pMax - pMin);
        const gy = y(val);
        return (
          <g key={f}>
            <line x1={PAD_L} y1={gy} x2={W - PAD_R} y2={gy} stroke="#94a3b8" strokeOpacity={0.14} strokeWidth={1} />
            <text x={PAD_L - 8} y={gy + 3} fontSize={10} fill="#94a3b8" textAnchor="end">${fmtARS(val)}</text>
          </g>
        );
      })}

      {/* área + línea del histórico */}
      {verts.length > 1 && <path d={area} fill={`url(#grad-${uid})`} stroke="none" />}
      {verts.length > 1 && (
        <path d={line} fill="none" stroke="#6366f1" strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
      )}

      {/* divisor real | proyección */}
      {projection && (
        <line x1={x(last.t)} y1={PAD_T - 4} x2={x(last.t)} y2={baseline}
              stroke="#94a3b8" strokeOpacity={0.25} strokeWidth={1} strokeDasharray="2 3" />
      )}

      {/* tramo de proyección (punteado, ámbar) */}
      {projection && (
        <>
          <path d={`M${x(last.t)},${y(last.p)} L${x(projection.t)},${y(projection.price)}`}
                fill="none" stroke="#f59e0b" strokeWidth={2.5} strokeDasharray="5 4" strokeLinecap="round" />
          <circle cx={x(projection.t)} cy={y(projection.price)} r={7} fill="#f59e0b" fillOpacity={0.15} />
          <circle cx={x(projection.t)} cy={y(projection.price)} r={4} fill="white" stroke="#f59e0b" strokeWidth={2}>
            <title>{`proyectado · $${fmtARS(projection.price)}`}</title>
          </circle>
          <text x={x(projection.t)} y={y(projection.price) - 11} fontSize={11.5}
                fill="#d97706" textAnchor={anchor(x(projection.t))} fontWeight={700}>
            ${fmtARS(projection.price)}
          </text>
          <text x={x(projection.t)} y={baseline + 16} fontSize={10} fill="#d97706"
                textAnchor={anchor(x(projection.t))} opacity={0.85}>
            proy.
          </text>
        </>
      )}

      {/* puntos reales (uno por cotización, color por fuente) */}
      {pts.map((p, i) => (
        <circle key={i} cx={x(ts[i])} cy={y(p.price)} r={4} fill={sourceColor(p.source)} stroke="white" strokeWidth={1.5}>
          <title>{`${p.date} · $${fmtARS(p.price)} · ${p.source}`}</title>
        </circle>
      ))}

      {/* eje X: años */}
      {[...yearAt.entries()].map(([yr, t]) => (
        <text key={yr} x={x(t)} y={baseline + 16} fontSize={11} fill="#94a3b8" textAnchor={anchor(x(t))}>
          {yr}
        </text>
      ))}
    </svg>
  );
}

const SORTS = {
  name: "Nombre (A-Z)",
  change: "Mayor variación histórica",
  projection: "Mayor proyección",
} as const;
type SortKey = keyof typeof SORTS;
const RENDER_CAP = 48; // tope de gráficos renderizados a la vez (perf con miles)

export default function PreciosPage() {
  const router = useRouter();
  const [products, setProducts] = useState<PriceSeriesProduct[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState<SortKey>("name");

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

  const categories = [...new Set(products.map((p) => p.category))].sort();
  const q = query.trim().toLowerCase();
  const filtered = products
    .filter((p) => (!q || p.name.toLowerCase().includes(q)) && (!category || p.category === category))
    .sort((a, b) => {
      if (sort === "change") return (b.change_pct ?? -Infinity) - (a.change_pct ?? -Infinity);
      if (sort === "projection") return b.forecast_variation_pct - a.forecast_variation_pct;
      return a.name.localeCompare(b.name);
    });
  const shown = filtered.slice(0, RENDER_CAP);

  const selectClass =
    "rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200";

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      <div>
        <button onClick={() => router.push("/")}
                className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Volver
        </button>
        <h1 className="mt-1 text-2xl font-bold text-slate-900 dark:text-white">Inteligencia de Precios</h1>
        <p className="text-sm text-slate-500">
          Evolución histórica REAL de tus materiales · {products.length} productos
        </p>
      </div>

      {products.length === 0 ? (
        <div className="rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
          Todavía no hay productos con serie de precios. Cargá precios y unilos con el matching de materiales.
        </div>
      ) : (
        <>
          {/* Barra de filtros (sticky para listas largas) */}
          <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar material…"
              className="w-56 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 placeholder:text-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
            />
            <select value={category} onChange={(e) => setCategory(e.target.value)} className={selectClass}>
              <option value="">Todos los rubros</option>
              {categories.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} className={selectClass}>
              {Object.entries(SORTS).map(([k, label]) => (
                <option key={k} value={k}>{label}</option>
              ))}
            </select>
            <span className="ml-auto text-xs text-slate-400">
              {filtered.length === products.length
                ? `${products.length} productos`
                : `${filtered.length} de ${products.length}`}
            </span>
          </div>

          {shown.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">Sin resultados.</p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {shown.map((p) => <ProductCard key={p.id} p={p} />)}
            </div>
          )}

          {filtered.length > RENDER_CAP && (
            <p className="text-center text-xs text-slate-400">
              Mostrando {RENDER_CAP} de {filtered.length}. Refiná la búsqueda o el rubro para ver el resto.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function ProductCard({ p }: { p: PriceSeriesProduct }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-1 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-slate-900 dark:text-white">{p.name}</h3>
          <span className="text-[10px] uppercase tracking-wide text-slate-400">{p.category}</span>
        </div>
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
  );
}

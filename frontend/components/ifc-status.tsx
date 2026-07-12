"use client";

import type { IfcQuality, Plan } from "@/lib/api";

const LEVEL_STYLE = {
  green: {
    border: "border-emerald-200 dark:border-emerald-500/30",
    bg: "bg-emerald-50 dark:bg-emerald-500/10",
    text: "text-emerald-800 dark:text-emerald-300",
    dot: "bg-emerald-500",
    title: "Calidad del modelo: buena",
  },
  yellow: {
    border: "border-amber-200 dark:border-amber-500/30",
    bg: "bg-amber-50 dark:bg-amber-500/10",
    text: "text-amber-800 dark:text-amber-300",
    dot: "bg-amber-500",
    title: "Calidad del modelo: aceptable",
  },
  red: {
    border: "border-red-200 dark:border-red-500/30",
    bg: "bg-red-50 dark:bg-red-500/10",
    text: "text-red-800 dark:text-red-300",
    dot: "bg-red-500",
    title: "Calidad del modelo: baja",
  },
} as const;

export function IfcQualityCard({ quality }: { quality: IfcQuality }) {
  const style = LEVEL_STYLE[quality.level] ?? LEVEL_STYLE.yellow;
  return (
    <div className={`rounded-md border px-3 py-2 text-sm ${style.border} ${style.bg} ${style.text}`}>
      <div className="flex items-center gap-2 font-medium">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${style.dot}`} />
        {style.title}
        {quality.schema ? (
          <span className="font-normal opacity-70">· {quality.schema}</span>
        ) : null}
      </div>
      {quality.checks && quality.checks.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 text-xs opacity-90">
          {quality.checks.map((c) => (
            <li key={c.id}>
              {c.ok ? "✓" : "○"} {c.label}
            </li>
          ))}
        </ul>
      )}
      {quality.warnings && quality.warnings.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 text-xs opacity-80">
          {quality.warnings.map((w) => (
            <li key={w}>⚠ {w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function IfcParseProgress({ plan }: { plan: Plan }) {
  const pct = Math.max(0, Math.min(100, plan.parse_progress ?? 0));
  const stage = plan.parse_stage || "Procesando…";
  return (
    <div className="w-full space-y-2">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="font-medium text-slate-700 dark:text-slate-200">{stage}</span>
        <span className="tabular-nums text-slate-500">{pct}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
        <div
          className="h-full rounded-full bg-brand transition-[width] duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-xs text-slate-500">
        Extrayendo muros, aberturas, losas y demás del modelo BIM.
      </p>
    </div>
  );
}

export function planErrorMessage(plan: Plan | undefined | null, fallback: string): string {
  const msg = plan?.error_message?.trim();
  return msg || fallback;
}

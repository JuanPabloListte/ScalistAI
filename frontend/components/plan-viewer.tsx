"use client";

import dynamic from "next/dynamic";

import type { Plan } from "@/lib/api";

const PlanViewerInner = dynamic(() => import("./plan-viewer-inner"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[600px] items-center justify-center rounded-xl border border-slate-200 bg-slate-100 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-400">
      Cargando visor...
    </div>
  ),
});

export function PlanViewer(props: {
  planId: number;
  pageCount?: number | null;
  pageScales?: Record<string, number> | null;
  deletedPages?: number[] | null;
  scaleSource?: string | null;
  planDpi?: number | null;
  calRequest?: { page: number; ts: number } | null;
  onPlanUpdated?: (plan: Plan) => void;
  height?: number;
}) {
  return <PlanViewerInner {...props} />;
}

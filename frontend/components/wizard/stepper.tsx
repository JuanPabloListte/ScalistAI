"use client";

// `num` = índice INTERNO del wizard (matchea currentStep / onJump). `display`
// = número VISIBLE en el círculo (secuencial 1..N). En IFC el paso interno 3
// ("Páginas") no existe, así que display desacopla la numeración mostrada
// (1..5) del índice interno (1,2,4,5,6) — antes se veía "1,2,4,5,6".
type WizardStep = { num: number; label: string; display?: number };

export const WIZARD_STEPS: WizardStep[] = [
  { num: 1, label: "Datos" },
  // PIVOTE IFC: label histórico "Plano PDF" — reactivar con PDF/DXF/DWG.
  { num: 2, label: "Plano PDF" },
  { num: 3, label: "Páginas" },
  { num: 4, label: "Ubicación" },
  { num: 5, label: "Construcción" },
  { num: 6, label: "Revisión" },
];

// IFC: modelo BIM exacto -> sin "Páginas" (no tiene láminas).
// PIVOTE IFC (jul-2026): este es el stepper activo del MVP.
export const IFC_WIZARD_STEPS: WizardStep[] = [
  { num: 1, label: "Datos", display: 1 },
  { num: 2, label: "Modelo BIM", display: 2 },
  { num: 4, label: "Ubicación", display: 3 },
  { num: 5, label: "Construcción", display: 4 },
  { num: 6, label: "Revisión", display: 5 },
];

export function Stepper({
  currentStep,
  maxReached,
  onJump,
  // PIVOTE IFC: default = IFC (antes era WIZARD_STEPS)
  steps = IFC_WIZARD_STEPS,
}: {
  currentStep: number;
  maxReached: number;
  onJump?: (step: number) => void;
  steps?: WizardStep[];
}) {
  return (
    <ol className="my-6 flex items-center gap-2">
      {steps.map((s, idx) => {
        const active = s.num === currentStep;
        const done = s.num < currentStep || s.num <= maxReached;
        const clickable = onJump && s.num <= maxReached && s.num !== currentStep;
        return (
          <li key={s.num} className="flex flex-1 items-center gap-2">
            <button
              type="button"
              disabled={!clickable}
              onClick={() => clickable && onJump?.(s.num)}
              className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-sm font-semibold transition ${
                active
                  ? "border-brand bg-brand text-white dark:border-sky-400 dark:bg-sky-400 dark:text-slate-900"
                  : done
                    ? "border-brand bg-white text-brand dark:border-sky-400 dark:bg-slate-800 dark:text-sky-400"
                    : "border-slate-300 bg-white text-slate-400 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-500"
              } ${clickable ? "cursor-pointer hover:scale-105" : "cursor-default"}`}
            >
              {done && !active ? "✓" : (s.display ?? s.num)}
            </button>
            <span
              className={`hidden text-sm sm:inline ${
                active
                  ? "font-semibold text-slate-900 dark:text-slate-100"
                  : "text-slate-500 dark:text-slate-400"
              }`}
            >
              {s.label}
            </span>
            {idx < steps.length - 1 && (
              <div className="ml-1 h-px flex-1 bg-slate-300 dark:bg-slate-600" />
            )}
          </li>
        );
      })}
    </ol>
  );
}

// Feature flags del frontend. Foco actual: armado del presupuesto.
// Las secciones apagadas se ocultan del menú y sus rutas redirigen a
// /projects, pero el código queda intacto para reincorporarlas: basta con
// setear la variable en "true" (.env) y reiniciar el frontend.
export const FEATURES = {
  /** /precios — Inteligencia de Precios */
  priceIntelligence: process.env.NEXT_PUBLIC_FEATURE_PRICE_INTELLIGENCE === "true",
  /** /materials — Cómputos / Sistemas (Insumos Base + Sistemas Constructivos) */
  computos: process.env.NEXT_PUBLIC_FEATURE_COMPUTOS === "true",
  /** Paso "Construcción" del wizard (tipo de obra). Con IFC se autocompleta
   *  desde el modelo, así que por defecto no se le pide al usuario. */
  wizardBuildingStep: process.env.NEXT_PUBLIC_FEATURE_WIZARD_BUILDING === "true",
  /** Presupuesto viejo (insumos/sistemas + paramétricos + mano de obra). El
   *  actual sale del presupuesto del proveedor × reglas de cómputo. */
  legacyBudget: process.env.NEXT_PUBLIC_FEATURE_LEGACY_BUDGET === "true",
  /** Landing: cotizador de planes (sección Precios y "Calcular mi precio"). */
  landingPricing: process.env.NEXT_PUBLIC_FEATURE_LANDING_PRICING === "true",
} as const;

/** Prefijos de ruta de las secciones apagadas. */
export const DISABLED_PATHS: string[] = [
  ...(FEATURES.priceIntelligence ? [] : ["/precios"]),
  ...(FEATURES.computos ? [] : ["/materials"]),
];

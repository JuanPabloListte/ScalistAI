// Feature flags del frontend. Foco actual: armado del presupuesto.
// Las secciones apagadas se ocultan del menú y sus rutas redirigen a
// /projects, pero el código queda intacto para reincorporarlas: basta con
// setear la variable en "true" (.env) y reiniciar el frontend.
export const FEATURES = {
  /** /precios — Inteligencia de Precios */
  priceIntelligence: process.env.NEXT_PUBLIC_FEATURE_PRICE_INTELLIGENCE === "true",
  /** /admin/model — Modelo ML (superadmin) */
  mlModel: process.env.NEXT_PUBLIC_FEATURE_ML_MODEL === "true",
} as const;

/** Prefijos de ruta de las secciones apagadas. */
export const DISABLED_PATHS: string[] = [
  ...(FEATURES.priceIntelligence ? [] : ["/precios"]),
  ...(FEATURES.mlModel ? [] : ["/admin/model"]),
];

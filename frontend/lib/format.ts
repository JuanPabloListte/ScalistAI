// Formato de números, moneda y fechas (es-AR). Fuente única para todas las pantallas.

const ARS_INT = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 });
const ARS_CURRENCY = new Intl.NumberFormat("es-AR", {
  style: "currency",
  currency: "ARS",
  maximumFractionDigits: 0,
});

/** Pesos redondeados, sin símbolo: 1234567.8 → "1.234.568". */
export function fmtARS(n: number): string {
  return ARS_INT.format(Math.round(n));
}

/** Pesos con símbolo: 1234567 → "$ 1.234.567"; null/undefined → "—". */
export function money(n: number | null | undefined): string {
  return n == null ? "—" : ARS_CURRENCY.format(n);
}

/** Número con hasta `decimals` decimales; null/undefined → "—". */
export function fmtNum(n: number | null | undefined, decimals = 2): string {
  return n == null ? "—" : n.toLocaleString("es-AR", { maximumFractionDigits: decimals });
}

/** Fecha ISO (YYYY-MM-DD) → "05 mar" o, con año, "05 mar 26". Vacía → "—". */
export function fmtDate(iso: string, { withYear = false }: { withYear?: boolean } = {}): string {
  if (!iso) return "—";
  return new Date(iso + "T00:00:00").toLocaleDateString("es-AR", {
    day: "2-digit",
    month: "short",
    ...(withYear ? { year: "2-digit" } : {}),
  });
}

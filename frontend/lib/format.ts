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

export type ParseNumAR =
  | { ok: true; value: number }
  | { ok: false; error: "vacio" | "invalido" | "ambiguo" };

/** Mensaje para el caso "ambiguo" de parseNumAR. */
export const MSG_NUM_AMBIGUO = "Usá coma para los decimales (12,5) y punto para los miles (12.500)";

/**
 * Texto tipeado en formato es-AR → número. Coma = decimal, punto = miles (grupos de 3).
 * "12.500" → 12500, "1.234,5" → 1234.5, "16,5" → 16.5, "-5" → -5.
 * "12.5" / "0.025" (un punto que no es de miles) es ambiguo: no se adivina.
 * No valida rangos: eso lo hace quien llama.
 */
export function parseNumAR(input: string): ParseNumAR {
  const s = input.trim();
  if (!s) return { ok: false, error: "vacio" };
  const empiezaCero = /^-?0\./;
  if (s.includes(",")) {
    if (!/^-?(\d{1,3}(\.\d{3})+|\d+),\d+$/.test(s) || empiezaCero.test(s))
      return { ok: false, error: "invalido" };
    return { ok: true, value: Number(s.replace(/\./g, "").replace(",", ".")) };
  }
  if (/^-?\d+$/.test(s)) return { ok: true, value: Number(s) };
  if (/^-?\d{1,3}(\.\d{3})+$/.test(s) && !empiezaCero.test(s))
    return { ok: true, value: Number(s.replace(/\./g, "")) };
  if (/^-?\d+\.\d+$/.test(s)) return { ok: false, error: "ambiguo" };
  return { ok: false, error: "invalido" };
}

/** Número → texto para un input es-AR: coma decimal, sin miles ni ceros de más (16.5 → "16,5"). */
export function fmtInputAR(n: number): string {
  return n.toLocaleString("es-AR", { useGrouping: false, maximumFractionDigits: 10 });
}

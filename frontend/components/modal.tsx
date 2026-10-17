"use client";

import { useState, type ReactNode } from "react";

const SIZES = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  "2xl": "max-w-2xl",
} as const;

/** Ventana modal: fondo oscurecido + panel. Clic afuera = onClose (si se pasa). */
export function Modal({
  children,
  onClose,
  size = "md",
}: {
  children: ReactNode;
  /** Sin onClose (p. ej. mientras guarda) el clic afuera no cierra. */
  onClose?: () => void;
  size?: keyof typeof SIZES;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className={`surface max-h-[90vh] w-full overflow-y-auto p-6 ${SIZES[size]}`}
      >
        {children}
      </div>
    </div>
  );
}

/** Confirmación de una acción destructiva. Si onConfirm falla, muestra el error y queda abierta. */
export function ConfirmModal({
  title,
  message,
  confirmLabel = "Eliminar",
  busyLabel = "Eliminando...",
  onCancel,
  onConfirm,
}: {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  busyLabel?: string;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handle() {
    setBusy(true);
    setErr(null);
    try {
      await onConfirm();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error");
      setBusy(false);
    }
  }

  return (
    <Modal onClose={busy ? undefined : onCancel}>
      <h2 className="text-lg font-semibold text-slate-900 dark:text-white">{title}</h2>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{message}</p>
      {err && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{err}</p>}
      <div className="mt-6 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="rounded-md border border-slate-300/50 bg-white/50 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-white/80 disabled:opacity-50 dark:border-white/10 dark:bg-slate-900/50 dark:text-slate-200 dark:hover:bg-slate-800/80"
        >
          Cancelar
        </button>
        <button
          type="button"
          onClick={handle}
          disabled={busy}
          className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-700 disabled:opacity-50"
        >
          {busy ? busyLabel : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";

import { api, type Letterhead } from "@/lib/api";

const MAX_LOGO_BYTES = 2 * 1024 * 1024;

/** Membrete del presupuesto en PDF: logo y datos de contacto del estudio. */
export function LetterheadCard({ canEdit }: { canEdit: boolean }) {
  const [data, setData] = useState<Letterhead | null>(null);
  const [logoUrl, setLogoUrl] = useState<string | null>(null);
  const [contact, setContact] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function loadLogo(has: boolean) {
    setLogoUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return null;
    });
    if (!has) return;
    try {
      setLogoUrl(URL.createObjectURL(await api.fetchLogo()));
    } catch {
      /* sin logo */
    }
  }

  useEffect(() => {
    api.getLetterhead()
      .then((d) => {
        setData(d);
        setContact(d.contact_info ?? "");
        void loadLogo(d.has_logo);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  async function run(fn: () => Promise<Letterhead>, ok: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const d = await fn();
      setData(d);
      await loadLogo(d.has_logo);
      setNotice(ok);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setBusy(false);
    }
  }

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!/\.(png|jpe?g)$/i.test(file.name)) {
      setError("Subí el logo en PNG o JPG.");
      return;
    }
    if (file.size > MAX_LOGO_BYTES) {
      setError("El logo supera los 2 MB.");
      return;
    }
    void run(() => api.uploadLogo(file), "Logo actualizado.");
  }

  if (!data) {
    return error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null;
  }

  return (
    <section className="mb-8 rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
      <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">Membrete del presupuesto</h2>
      <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
        Encabeza el PDF que le mandás al comitente: el logo de {data.name} y sus datos de contacto.
      </p>
      <div className="mt-4 grid gap-5 md:grid-cols-[16rem_1fr]">
        <div>
          <div className="flex h-28 items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-950">
            {logoUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={logoUrl} alt={`Logo de ${data.name}`} className="max-h-full max-w-full object-contain" />
            ) : (
              <span className="text-xs text-slate-400">Sin logo</span>
            )}
          </div>
          {canEdit && (
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 whitespace-nowrap text-xs">
              <input ref={fileRef} type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" className="hidden" onChange={onFile} />
              <button type="button" disabled={busy} onClick={() => fileRef.current?.click()}
                      className="font-semibold text-brand-600 hover:underline disabled:opacity-50 dark:text-brand-400">
                {data.has_logo ? "Cambiar logo" : "Subir logo"}
              </button>
              {data.has_logo && (
                <button type="button" disabled={busy}
                        onClick={() => void run(() => api.deleteLogo(), "Logo quitado.")}
                        className="text-slate-500 hover:text-red-600 disabled:opacity-50">
                  Quitar
                </button>
              )}
              <span className="basis-full text-slate-400">PNG o JPG, hasta 2 MB</span>
            </div>
          )}
        </div>
        <label className="block text-sm">
          <span className="font-medium text-slate-700 dark:text-slate-300">Datos de contacto</span>
          <textarea
            value={contact}
            disabled={!canEdit || busy}
            rows={4}
            maxLength={600}
            placeholder={"Dirección\nTeléfono · mail\nCUIT"}
            onChange={(e) => setContact(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 disabled:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-900"
          />
          <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">Una línea por dato. Aparecen arriba a la derecha.</span>
        </label>
      </div>
      <div className="mt-3 flex items-center justify-end gap-3">
        {error && <p className="mr-auto text-sm text-red-600 dark:text-red-400">{error}</p>}
        {!error && notice && <p className="mr-auto text-sm text-emerald-600 dark:text-emerald-400">{notice}</p>}
        {canEdit && (
          <button
            type="button"
            disabled={busy || contact === (data.contact_info ?? "")}
            onClick={() => void run(() => api.updateLetterhead(contact.trim() || null), "Datos guardados.")}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-40"
          >
            Guardar datos
          </button>
        )}
      </div>
    </section>
  );
}

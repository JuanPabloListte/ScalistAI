"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";

export default function MaterialsPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Verificación simple de auth: cualquier llamada protegida sirve.
    // En Etapa 5 reemplazamos esto por el listado real de materiales.
    api
      .listProjects()
      .catch((err) => {
        if (err instanceof Error && err.message.includes("401")) {
          router.push("/login");
          return;
        }
        setError(err instanceof Error ? err.message : "Error desconocido");
      })
      .finally(() => setLoading(false));
  }, [router]);

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-brand dark:text-sky-400">Materiales</h1>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
          Catálogo de materiales con rendimientos y precios.
        </p>
      </header>

      {loading && (
        <p className="text-slate-500 dark:text-slate-400">Cargando...</p>
      )}

      {error && (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      )}

      {!loading && !error && (
        <div className="rounded-xl border-2 border-dashed border-slate-300 px-6 py-16 text-center text-slate-500 dark:border-slate-700 dark:text-slate-400">
          <p className="mb-2 text-lg font-medium">Catálogo de materiales</p>
          <p className="text-sm">
            Próximamente: CRUD de materiales, importar/exportar Excel, asignación a elementos.
          </p>
        </div>
      )}
    </main>
  );
}

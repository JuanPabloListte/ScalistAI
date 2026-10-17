"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, isUnauthorized } from "@/lib/api";

/** El proyecto no tiene vista propia: manda a la que corresponde según el rol.
 *  Quien no ve financieros (capataz/comitente) iría a un 403 en /presupuesto
 *  → va a su obra. */
export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = Number(params.id);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getProjectMembers(projectId)
      .catch(() => null)
      .then((membersState) => {
        if (cancelled) return;
        const role = membersState?.my_role;
        const dest = role === "capataz" || role === "comitente" ? "obra" : "presupuesto";
        router.replace(`/projects/${projectId}/${dest}`);
      })
      .catch((err) => {
        if (cancelled) return;
        if (isUnauthorized(err)) router.push("/login");
        else setError(err instanceof Error ? err.message : "Error");
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, router]);

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <p className="text-slate-500 dark:text-slate-400">{error ?? "Cargando..."}</p>
    </main>
  );
}

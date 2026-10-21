import Link from "next/link";

/** Estado vacío para un proyecto que no existe (o que el usuario no puede ver). */
export function ProjectNotFound() {
  return (
    <main className="mx-auto max-w-4xl px-6 py-16 text-center">
      <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">Proyecto no encontrado</h1>
      <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
        No existe o no tenés acceso a él.
      </p>
      <Link
        href="/projects"
        className="mt-5 inline-block text-sm text-brand hover:underline dark:text-sky-400"
      >
        ← Volver a proyectos
      </Link>
    </main>
  );
}

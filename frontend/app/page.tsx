import Link from "next/link";

export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center">
      <h1 className="text-5xl font-bold text-brand dark:text-sky-400">ScalistAI</h1>
      <p className="max-w-xl text-lg text-slate-600 dark:text-slate-300">
        Cómputo métrico y presupuesto automatizado desde planos PDF, para la fase de
        preconstrucción y preventa inmobiliaria.
      </p>
      <div className="flex gap-3">
        <Link
          href="/login"
          className="rounded-lg bg-brand px-5 py-2 font-semibold text-white hover:bg-brand-dark"
        >
          Ingresar
        </Link>
        <Link
          href="/register"
          className="rounded-lg border border-brand px-5 py-2 font-semibold text-brand hover:bg-brand hover:text-white dark:border-sky-400 dark:text-sky-400 dark:hover:bg-sky-400 dark:hover:text-slate-900"
        >
          Crear cuenta
        </Link>
      </div>
    </main>
  );
}

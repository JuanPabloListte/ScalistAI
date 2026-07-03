"use client";

/**
 * Marco visual de la pantalla de login (reutilizable para cualquier pantalla
 * de autenticación). Reusa la estética de la landing: slate-950 con grilla
 * glows animados y el logo enlazando al home. El formulario se pasa como
 * children dentro de una card oscura.
 */

import Link from "next/link";
import type { ReactNode } from "react";

export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-950 px-6 py-12 font-sans text-slate-100 selection:bg-brand-500/30">
      {/* Blueprint grid + glows (idénticos a la landing) */}
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,#1e293b_1px,transparent_1px),linear-gradient(to_bottom,#1e293b_1px,transparent_1px)] bg-[size:40px_40px] opacity-30" />
      <div className="animate-blob pointer-events-none absolute -left-4 top-0 h-72 w-72 rounded-full bg-brand-500 opacity-20 mix-blend-multiply blur-[128px]" />
      <div className="animate-blob animation-delay-2000 pointer-events-none absolute -right-4 top-0 h-72 w-72 rounded-full bg-sky-400 opacity-20 mix-blend-multiply blur-[128px]" />
      <div className="animate-blob animation-delay-4000 pointer-events-none absolute -bottom-8 left-20 h-72 w-72 rounded-full bg-indigo-500 opacity-20 mix-blend-multiply blur-[128px]" />

      <div className="relative z-10 w-full max-w-md animate-slide-up" style={{ animationFillMode: "both" }}>
        {/* Logo → home */}
        <Link href="/" className="mb-8 flex items-center justify-center gap-2 text-xl font-bold tracking-tight text-white">
          <span className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-md">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.png" alt="ScalistAI" className="h-full w-full object-contain" />
          </span>
          ScalistAI
        </Link>

        <div className="rounded-3xl border border-slate-800 bg-slate-900/70 p-8 shadow-2xl shadow-brand-500/10 backdrop-blur-sm">
          <div className="mb-6 text-center">
            <h1 className="text-2xl font-bold tracking-tight text-white">{title}</h1>
            {subtitle && <p className="mt-2 text-sm text-slate-400">{subtitle}</p>}
          </div>
          {children}
        </div>

        {footer && <div className="mt-6 text-center text-sm text-slate-400">{footer}</div>}
      </div>
    </main>
  );
}

/** Input con el estilo dark de la app (mismo focus brand que el resto). */
export const authInputClass =
  "w-full rounded-xl border border-slate-700 bg-slate-950/60 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 outline-none transition focus:border-brand-500 focus:ring-1 focus:ring-brand-500";

/** Botón primario de auth (brand, con estado loading). */
export const authButtonClass =
  "flex w-full items-center justify-center gap-2 rounded-xl bg-brand-600 px-6 py-3 text-sm font-semibold text-white transition hover:bg-brand-500 hover:shadow-[0_0_30px_rgba(14,165,233,0.35)] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:shadow-none";

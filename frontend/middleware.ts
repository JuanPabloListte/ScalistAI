import { NextRequest, NextResponse } from "next/server";

import { DISABLED_PATHS } from "@/lib/features";

// Rutas del app que no deben ser accesibles en el deploy de landing (Vercel).
// Para el deploy completo (Docker/VPS) esta lista se ignora porque
// LANDING_ONLY no está seteado.
const APP_PATHS = [
  "/login",
  "/register",
  "/profile",
  "/projects",
  "/materials",
  "/reglas",
  "/team",
  "/admin",
];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Secciones apagadas por feature flag (lib/features.ts) → a Proyectos.
  if (DISABLED_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"))) {
    return NextResponse.redirect(new URL("/projects", request.url));
  }

  // La landing es para producción: en local (`next dev`) la raíz va directo al login.
  // SHOW_LANDING=true la muestra igual (para trabajar sobre la landing en local).
  if (
    pathname === "/" &&
    process.env.NODE_ENV !== "production" &&
    process.env.SHOW_LANDING !== "true"
  ) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (process.env.LANDING_ONLY !== "true") return NextResponse.next();

  const blocked = APP_PATHS.some(
    (p) => pathname === p || pathname.startsWith(p + "/"),
  );

  if (blocked) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return NextResponse.next();
}

export const config = {
  // Excluye archivos estáticos y rutas internas de Next.js del middleware.
  matcher: ["/((?!_next/static|_next/image|favicon\\.ico|.*\\..*).*)"],
};

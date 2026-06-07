import { NextRequest, NextResponse } from "next/server";

// Rutas del app que no deben ser accesibles en el deploy de landing (Vercel).
// Para el deploy completo (Docker/VPS) esta lista se ignora porque
// LANDING_ONLY no está seteado.
const APP_PATHS = [
  "/login",
  "/register",
  "/profile",
  "/projects",
  "/materials",
  "/team",
  "/admin",
];

export function middleware(request: NextRequest) {
  if (process.env.LANDING_ONLY !== "true") return NextResponse.next();

  const { pathname } = request.nextUrl;
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

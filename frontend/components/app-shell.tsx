"use client";

import { usePathname } from "next/navigation";

import { AppSidebar } from "@/components/app-sidebar";

const PUBLIC_PATHS = ["/", "/login", "/register"];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const showSidebar = !PUBLIC_PATHS.includes(pathname);

  if (!showSidebar) {
    return <>{children}</>;
  }

  return (
    <div className="min-h-screen">
      <AppSidebar />
      <div className="pl-16">{children}</div>
    </div>
  );
}

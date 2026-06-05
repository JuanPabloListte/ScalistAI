"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { ProfileMenu } from "@/components/profile-menu";
import { api, type User } from "@/lib/api";

type NavItem = {
  href: string;
  label: string;
  icon: ReactNode;
  matchPrefix: string;
};

const NAV_ITEMS: NavItem[] = [
  {
    href: "/projects",
    label: "Proyectos",
    matchPrefix: "/projects",
    icon: <FolderIcon />,
  },
  {
    href: "/materials",
    label: "Cómputos / Sistemas",
    matchPrefix: "/materials",
    icon: <PackageIcon />,
  },
];

export function AppSidebar() {
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    api.getMe()
      .then((u) => setUser(u))
      .catch((err) => console.error("Error fetching sidebar profile:", err));
  }, []);

  const isSuperadmin = user?.is_superadmin === true;
  const isOrgAdmin = user?.role === "admin" || isSuperadmin;

  const items = [...NAV_ITEMS];
  if (isOrgAdmin) {
    items.push({
      href: "/team",
      label: "Mi equipo",
      matchPrefix: "/team",
      icon: <UsersIcon />,
    });
  }
  if (isSuperadmin) {
    items.push({
      href: "/admin/organizations",
      label: "Organizaciones",
      matchPrefix: "/admin/organizations",
      icon: <BuildingIcon />,
    });
    items.push({
      href: "/admin/model",
      label: "Modelo ML",
      matchPrefix: "/admin/model",
      icon: <BrainIcon />,
    });
  }

  return (
    <aside className="fixed inset-y-0 left-0 z-40 flex w-16 flex-col items-center justify-between border-r border-slate-200 bg-white py-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-col items-center gap-6">
        <Link
          href="/projects"
          aria-label="ScalistAI · Inicio"
          className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-600 text-white transition hover:bg-brand-700 dark:bg-brand-500 dark:hover:bg-brand-400"
        >
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z" />
            <path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65" />
            <path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65" />
          </svg>
        </Link>

        <nav className="flex flex-col items-center gap-1">
          {items.map((item) => {
            const active = pathname.startsWith(item.matchPrefix);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-label={item.label}
                title={item.label}
                className={`flex h-10 w-10 items-center justify-center rounded-lg transition ${
                  active
                    ? "bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300"
                    : "text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                }`}
              >
                {item.icon}
              </Link>
            );
          })}
        </nav>
      </div>

      <ProfileMenu />
    </aside>
  );
}

function FolderIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
    </svg>
  );
}

function PackageIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m7.5 4.27 9 5.15" />
      <path d="M21 8 12 13 3 8" />
      <path d="M3 8v8l9 5 9-5V8" />
      <path d="m12 13 0 8" />
    </svg>
  );
}

function UsersIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}

function BuildingIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="4" y="2" width="16" height="20" rx="2" ry="2" />
      <path d="M9 22v-4h6v4" />
      <path d="M8 6h.01" />
      <path d="M16 6h.01" />
      <path d="M12 6h.01" />
      <path d="M12 10h.01" />
      <path d="M12 14h.01" />
      <path d="M16 10h.01" />
      <path d="M16 14h.01" />
      <path d="M8 10h.01" />
      <path d="M8 14h.01" />
    </svg>
  );
}

function BrainIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z" />
      <path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z" />
      <path d="M12 5v14" />
      <path d="M12 9h4" />
      <path d="M12 13h6" />
      <path d="M12 17h4" />
      <path d="M12 9H8" />
      <path d="M12 13H6" />
      <path d="M12 17H8" />
    </svg>
  );
}

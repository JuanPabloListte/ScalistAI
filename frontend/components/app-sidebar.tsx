"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode } from "react";

import { ProfileMenu } from "@/components/profile-menu";

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
    label: "Materiales",
    matchPrefix: "/materials",
    icon: <PackageIcon />,
  },
];

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed inset-y-0 left-0 z-40 flex w-16 flex-col items-center justify-between border-r border-slate-200 bg-white py-4 dark:border-slate-800 dark:bg-slate-950">
      <div className="flex flex-col items-center gap-6">
        <Link
          href="/projects"
          aria-label="MuroAI · Inicio"
          className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand text-lg font-bold text-white shadow-sm transition hover:bg-brand-dark dark:bg-sky-500 dark:text-slate-950 dark:hover:bg-sky-400"
        >
          M
        </Link>

        <nav className="flex flex-col items-center gap-2">
          {NAV_ITEMS.map((item) => {
            const active = pathname.startsWith(item.matchPrefix);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-label={item.label}
                title={item.label}
                className={`flex h-10 w-10 items-center justify-center rounded-lg transition ${
                  active
                    ? "bg-brand/10 text-brand dark:bg-sky-500/15 dark:text-sky-400"
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
